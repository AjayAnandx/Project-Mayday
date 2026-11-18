import logging
import time
import os
import json
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter

from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.core.project_store import get_project_store
from backend.memory.knowledge_graph import get_graph
from backend.core.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_ai_news_cache: dict | None = None
_ai_news_cache_time: float = 0
_AI_NEWS_TTL = 3600


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _in_days(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).strftime("%Y-%m-%d")


@router.get("")
def get_dashboard():
    store = get_store()
    op_log = get_operation_log()
    project_store = get_project_store()
    kg = get_graph()

    today = _today_str()
    next_week = _in_days(7)

    all_todos = store.list_todos(include_completed=True)
    open_todos = [t for t in all_todos if not t["completed"]]
    overdue_todos = [t for t in open_todos if t.get("due_date") and t["due_date"] < today]

    all_events = store.list_events(start_date=today, end_date=next_week)
    today_events = [e for e in all_events if e["start_time"][:10] == today]

    conversations = store.list_conversations()

    projects = project_store.list_projects()
    active_projects = [p for p in projects if p.get("status") == "active"]

    kg_stats = kg.stats()
    graph_nodes = kg_stats.get("nodes", 0)

    recent = op_log.query(limit=10)

    try:
        analytics = _build_analytics(op_log, all_todos, today)
    except Exception as e:
        logger.warning("dashboard analytics block failed: %s", e)
        analytics = None

    # Music block — top played + language mix (additive, never breaks dashboard)
    music_block = None
    try:
        from backend.core.music_history import get_music_history
        mh = get_music_history()
        music_block = {
            "total_plays": mh.total_plays(),
            "language_stats": mh.language_stats(),
            "top_week": mh.top_played(n=5, days=7),
            "top_all": mh.top_played(n=5),
        }
    except Exception as e:
        logger.warning("dashboard music block failed: %s", e)
        music_block = {"total_plays": 0, "language_stats": {}, "top_week": [], "top_all": []}

    return {
        "stats": {
            "open_todos": len(open_todos),
            "overdue_todos": len(overdue_todos),
            "today_events": len(today_events),
            "upcoming_events_count": len(all_events),
            "total_conversations": len(conversations),
            "active_projects": len(active_projects),
            "graph_nodes": graph_nodes,
        },
        "upcoming_events": sorted(all_events, key=lambda e: e["start_time"])[:7],
        "open_todos": sorted(open_todos, key=lambda t: t.get("due_date") or "9999-12-31")[:5],
        "overdue_todos": sorted(overdue_todos, key=lambda t: t.get("due_date") or "")[:5],
        "recent_activity": recent,
        "music": music_block,
        "analytics": analytics,
    }


_HEATMAP_BUCKETS = 6  # 4-hour slots: 00, 04, 08, 12, 16, 20

# Raw op-log entity types → the 6 categories shown in the Activity Mix card.
_MIX_GROUPS = {
    "email": "email", "email_draft": "email",
    "research": "research", "data": "research", "concept": "research", "belief": "research",
    "project": "projects", "project_task": "projects",
    "todo": "tasks", "reminder": "tasks",
    "event": "calendar",
    "memory": "memory", "person": "memory", "document": "memory", "conversation": "memory",
}
_MIX_ORDER = ["email", "research", "projects", "tasks", "calendar", "memory"]
_CREATE_ACTIONS = {"create", "created", "add_data_point", "add_task", "add_finding", "add_entity", "import", "write"}
_REMOVE_ACTIONS = {"delete", "scrapped"}


def _last_months(now: datetime, n: int) -> list[str]:
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _mix_group(entity_type: str | None) -> str:
    return _MIX_GROUPS.get(entity_type or "", "memory")


def _action_kind(action: str | None) -> str:
    if action in _CREATE_ACTIONS:
        return "created"
    if action in _REMOVE_ACTIONS:
        return "removed"
    return "updated"


def _build_mix(ops: list[dict], daily_keys: list[str], tz, by_month: bool = False) -> dict:
    """Category totals + created/updated/removed split + per-category trend series.

    Series buckets are days (YYYY-MM-DD) or, with by_month, months (YYYY-MM)."""
    idx = {k: i for i, k in enumerate(daily_keys)}
    groups = {g: {"count": 0, "daily": [0] * len(daily_keys)} for g in _MIX_ORDER}
    actions = {"created": 0, "updated": 0, "removed": 0}
    for op in ops:
        g = groups[_mix_group(op.get("entity_type"))]
        g["count"] += 1
        actions[_action_kind(op.get("action"))] += 1
        ts = op.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                key = dt.astimezone(tz).date().isoformat()
                i = idx.get(key[:7] if by_month else key)
                if i is not None:
                    g["daily"][i] += 1
            except ValueError:
                pass
    return {
        "total": len(ops),
        "buckets": daily_keys,
        "groups": [{"key": k, **groups[k]} for k in _MIX_ORDER],
        "actions": actions,
    }


def _build_analytics(op_log, all_todos: list[dict], today: str) -> dict:
    """Aggregate the operation log into chart-ready series (local time)."""
    now_local = datetime.now().astimezone()
    days = 30
    start_local = (now_local - timedelta(days=2 * days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    date_from = start_local.astimezone(timezone.utc).isoformat()
    ops = op_log.query(date_from=date_from, limit=1_000_000)

    cur_start = (now_local - timedelta(days=days - 1)).date()
    daily: dict[str, int] = {
        (cur_start + timedelta(days=i)).isoformat(): 0 for i in range(days)
    }
    heatmap = [[0] * 7 for _ in range(_HEATMAP_BUCKETS)]  # [bucket][weekday Sun..Sat]
    parts = {"morning": 0, "afternoon": 0, "evening": 0}
    by_entity: dict[str, int] = {}
    prev_total = 0
    recent_ops: list[dict] = []

    for op in ops:
        ts = op.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(now_local.tzinfo)
        d = local.date()
        if d < cur_start:
            prev_total += 1
            continue
        recent_ops.append(op)
        key = d.isoformat()
        if key in daily:
            daily[key] += 1
        weekday = (local.weekday() + 1) % 7  # Mon=0 -> Sun=0
        heatmap[local.hour // 4][weekday] += 1
        h = local.hour
        if 5 <= h < 12:
            parts["morning"] += 1
        elif 12 <= h < 17:
            parts["afternoon"] += 1
        else:
            parts["evening"] += 1
        et = op.get("entity_type") or "other"
        by_entity[et] = by_entity.get(et, 0) + 1

    completed = sum(1 for t in all_todos if t.get("completed"))
    overdue = sum(
        1 for t in all_todos
        if not t.get("completed") and t.get("due_date") and t["due_date"] < today
    )

    return {
        "daily": [{"date": k, "count": v} for k, v in daily.items()],
        "total": sum(daily.values()),
        "prev_total": prev_total,
        "heatmap": heatmap,
        "day_parts": parts,
        "by_entity": dict(sorted(by_entity.items(), key=lambda kv: kv[1], reverse=True)),
        "todos": {"total": len(all_todos), "completed": completed, "overdue": overdue},
        "mix": {
            "recent": _build_mix(recent_ops, list(daily.keys()), now_local.tzinfo),
            "all": _build_mix(op_log.query(limit=1_000_000), _last_months(now_local, 12), now_local.tzinfo, by_month=True),
        },
    }


@router.get("/weather")
def get_dashboard_weather():
    from backend.core.location import resolve_location
    loc = resolve_location()

    if not loc or not loc.get("city"):
        return {"available": False, "message": "No location set"}

    from backend.core.weather import get_weather
    result_str = get_weather(loc["city"], lat=loc.get("lat"), lon=loc.get("lon"), days=1)

    if not result_str or result_str.startswith("Could not") or result_str.startswith("Weather data not available"):
        return {"available": False, "message": result_str}

    return {"available": True, "location": loc["city"], "raw": result_str}


@router.get("/ai-news")
def get_ai_news():
    global _ai_news_cache, _ai_news_cache_time

    now = time.time()
    if _ai_news_cache and (now - _ai_news_cache_time) < _AI_NEWS_TTL:
        return _ai_news_cache

    config = load_config()
    env = config.get("env", {})
    exa_key = env.get("EXA_API_KEY") or os.environ.get("EXA_API_KEY", "")

    if not exa_key:
        result = {
            "articles": [],
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "error": "EXA_API_KEY not configured",
        }
        _ai_news_cache = result
        _ai_news_cache_time = now
        return result

    try:
        resp = httpx.post(
            "https://api.exa.ai/search",
            headers={
                "Authorization": f"Bearer {exa_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": "latest breakthroughs advances in artificial intelligence AI 2026",
                "numResults": 5,
                "contents": {"text": {"maxCharacters": 200}},
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            articles = []
            for r in data.get("results", []):
                articles.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "published_date": (r.get("publishedDate") or "")[:10],
                    "summary": (r.get("text", "") or "")[:250],
                })
            result = {
                "articles": articles,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            result = {
                "articles": [],
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "error": f"Exa API error: HTTP {resp.status_code}",
            }
    except Exception as e:
        result = {
            "articles": [],
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }

    _ai_news_cache = result
    _ai_news_cache_time = now
    return result
