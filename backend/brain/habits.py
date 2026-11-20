"""Brain V3 P9: habit mining (deterministic, nightly).

A habit is a pattern seen at least `min_count` times across at least `min_weeks` different
ISO weeks. Sources:
  * Planner completions: the same task done at a similar time ("gym" around 06:00 on weekdays)
  * focus sessions: deep work tends to start at a similar hour ("deep work (code) ~21:00")
  * active hours: when the user usually talks to Mayday
Each habit becomes a `habit` node (label habit:<key>) linked from the user with `has_habit`,
so the profile, recall and later the friction simulator can use it. Re-mining updates the
same node; habits not seen for `stale_days` are left to decay (decay.py).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("habits", {}) or {}
    return {"min_count": int(c.get("min_count", 3)), "min_weeks": int(c.get("min_weeks", 2)),
            "lookback_days": int(c.get("lookback_days", 42))}


def _local(ts: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if t.tzinfo is None:
        return t
    return t.astimezone().replace(tzinfo=None)


def _norm_title(t: str) -> str:
    t = re.sub(r"[^a-z ]+", " ", (t or "").lower())
    return " ".join(w for w in t.split() if len(w) > 2)[:40]


def _day_pattern(days: list[int]) -> str:
    s = set(days)
    if s <= {0, 1, 2, 3, 4} and len(s) >= 3:
        return "on weekdays"
    if s <= {5, 6}:
        return "on weekends"
    if len(s) == 1:
        return f"on {_DAYS[next(iter(s))]}s"
    if len(s) >= 5:
        return "most days"
    return "on " + "/".join(_DAYS[d] for d in sorted(s))


def _summarise(times: list[datetime]) -> dict | None:
    """Typical hour (mode of hour buckets) and weekday pattern, if the times are consistent."""
    cfg = _cfg()
    if len(times) < cfg["min_count"]:
        return None
    weeks = {t.isocalendar()[:2] for t in times}
    if len(weeks) < cfg["min_weeks"]:
        return None
    hours = Counter(t.hour for t in times)
    hour, n = hours.most_common(1)[0]
    near = sum(c for h, c in hours.items() if abs(h - hour) <= 1)
    if near < max(cfg["min_count"], 0.6 * len(times)):
        return None                                        # no consistent time of day
    return {"hour": hour, "days": _day_pattern([t.weekday() for t in times]), "count": len(times),
            "weeks": len(weeks), "share": round(near / len(times), 2)}


def planner_habits(now: datetime) -> list[dict]:
    try:
        from backend.core.planner_store import get_planner
        items = get_planner().all_items()
    except Exception:
        return []
    since = now - timedelta(days=_cfg()["lookback_days"])
    by_title: dict[str, list[datetime]] = defaultdict(list)
    names: dict[str, str] = {}
    for i in items:
        key = _norm_title(i.get("title", ""))
        if not key:
            continue
        stamps = [c.get("at") for c in (i.get("completions") or [])] + [i.get("completed_at")]
        for st in stamps:
            t = _local(st) if st else None
            if t and t >= since:
                by_title[key].append(t)
                names.setdefault(key, i.get("title", key))
    out = []
    for key, times in by_title.items():
        s = _summarise(times)
        if s:
            out.append({"key": f"task:{key}", "source": "planner",
                        "text": f"does \"{names[key]}\" around {s['hour']:02d}:00 {s['days']}", **s})
    return out


def focus_habits(now: datetime) -> list[dict]:
    from backend.brain.signals import get_bus
    rows = get_bus().recent("focus_start", minutes=_cfg()["lookback_days"] * 1440, limit=2000)
    by_cat: dict[str, list[datetime]] = defaultdict(list)
    for r in rows:
        t = _local(r["ts"])
        if t:
            by_cat[(r["value"] or {}).get("category") or "work"].append(t)
    out = []
    for cat, times in by_cat.items():
        s = _summarise(times)
        if s:
            out.append({"key": f"focus:{cat}", "source": "focus",
                        "text": f"usually starts deep work ({cat}) around {s['hour']:02d}:00 {s['days']}", **s})
    return out


def active_hours(now: datetime) -> list[dict]:
    from backend.brain.signals import get_bus
    rows = get_bus().recent("message", minutes=_cfg()["lookback_days"] * 1440, limit=5000)
    times = [t for t in (_local(r["ts"]) for r in rows) if t]
    if len(times) < 20 or len({t.isocalendar()[:2] for t in times}) < _cfg()["min_weeks"]:
        return []
    hours = Counter(t.hour for t in times)
    top = sorted(h for h, _ in hours.most_common(3))
    return [{"key": "active:hours", "source": "messages", "count": len(times),
             "weeks": len({t.isocalendar()[:2] for t in times}),
             "text": "talks to Mayday most around " + ", ".join(f"{h:02d}:00" for h in top)}]


def mine(kg, now: datetime | None = None) -> dict:
    """Upsert habit nodes; returns {"new": n, "updated": n, "habits": [...] }."""
    now = now or datetime.now()
    found = planner_habits(now) + focus_habits(now) + active_hours(now)
    me = kg.get_node_by_label("user:Mayday-user") or kg.get_node_by_label("user")
    me_id = me["id"] if me else kg.add_node("user", "user", {})
    new = updated = 0
    stamp = datetime.now(timezone.utc).isoformat()
    for h in found:
        label = f"habit:{h['key']}"
        props = {"text": h["text"], "source": h["source"], "evidence_count": str(h["count"]),
                 "weeks": str(h["weeks"]), "last_seen": stamp, "key": h["key"]}
        node = kg.get_node_by_label(label)
        if node:
            node["properties"].update(props)
            kg._index_node(node)
            updated += 1
        else:
            nid = kg.add_node("habit", label, props)
            kg.add_edge_if_missing(me_id, nid, "has_habit")
            new += 1
        if kg._store is not None:
            n = kg.get_node_by_label(label)
            kg._store.touch([n["id"]], importance=0.7)
    if found:
        kg._save()
    return {"new": new, "updated": updated, "habits": [h["text"] for h in found]}
