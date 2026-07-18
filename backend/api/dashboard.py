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
