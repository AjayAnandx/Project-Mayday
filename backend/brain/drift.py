"""Brain V3 P14: preference drift — notice when the user's routines and priorities change.

Nightly, deterministic:
  rhythm drift   hour-of-day distribution of messages and of deep-focus starts: last 4 weeks vs the
                 4 weeks before (Jensen–Shannon distance on hourly counts from signals + signal_stats).
                 Low impact -> the matching habit is updated automatically (old text kept).
  stale beliefs  goals / values / constraints not mentioned or used for 45+ days ->
                 "Is '<x>' still true?" (framing: Still true / Not anymore). High impact -> always asked.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("drift", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "window_weeks": int(c.get("window_weeks", 4)),
            "js_threshold": float(c.get("js_threshold", 0.2)), "min_events": int(c.get("min_events", 20)),
            "stale_days": int(c.get("stale_days", 45))}


def js_distance(p: Counter, q: Counter, bins=range(24)) -> float:
    """Jensen–Shannon distance (sqrt of divergence, base 2) between two count histograms; 0..1."""
    tp, tq = sum(p.values()) or 1, sum(q.values()) or 1
    P = [p.get(b, 0) / tp for b in bins]
    Q = [q.get(b, 0) / tq for b in bins]
    M = [(a + b) / 2 for a, b in zip(P, Q)]

    def kl(a, m):
        return sum(x * math.log2(x / y) for x, y in zip(a, m) if x > 0 and y > 0)
    return math.sqrt(max(0.0, (kl(P, M) + kl(Q, M)) / 2))


def _local_hour(ts: str) -> tuple[datetime, int]:
    t = datetime.fromisoformat(ts if len(ts) > 13 else ts + ":00:00")
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    lt = t.astimezone()
    return lt, lt.hour


def hour_histograms(store, kind: str, now: datetime, weeks: int) -> tuple[Counter, Counter]:
    """(recent, previous) hour-of-day counts for a signal kind."""
    now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    split = now_utc - timedelta(weeks=weeks)
    start = now_utc - timedelta(weeks=2 * weeks)
    recent, prev = Counter(), Counter()
    seen_hours = set()
    for r in store._rows("SELECT ts FROM signals WHERE kind=? AND ts >= ?", (kind, start.isoformat())):
        lt, h = _local_hour(r["ts"])
        seen_hours.add(r["ts"][:13])
        (recent if lt >= split else prev)[h] += 1
    for r in store._rows("SELECT hour, n FROM signal_stats WHERE kind=? AND hour >= ?",
                         (kind, start.strftime("%Y-%m-%dT%H"))):
        if r["hour"] in seen_hours:
            continue                                    # raw rows of that hour already counted
        lt, h = _local_hour(r["hour"])
        (recent if lt >= split else prev)[h] += r["n"]
    return recent, prev


def _peak(c: Counter) -> int:
    return max(range(24), key=lambda h: c.get(h, 0) + 0.5 * (c.get((h - 1) % 24, 0) + c.get((h + 1) % 24, 0)))


def rhythm_drift(store, kind: str, now: datetime) -> dict | None:
    cfg = _cfg()
    recent, prev = hour_histograms(store, kind, now, cfg["window_weeks"])
    if sum(recent.values()) < cfg["min_events"] or sum(prev.values()) < cfg["min_events"]:
        return None
    d = js_distance(recent, prev)
    if d < cfg["js_threshold"]:
        return None
    return {"kind": kind, "distance": round(d, 3), "peak_now": _peak(recent), "peak_before": _peak(prev),
            "events": [sum(recent.values()), sum(prev.values())]}


def _apply_rhythm(kg, drift: dict) -> str:
    """Low-impact: update the matching habit node (keep the previous text)."""
    label = {"message": "habit:active:hours", "focus_start": "habit:focus:code"}.get(drift["kind"])
    what = "talks to Mayday" if drift["kind"] == "message" else "starts deep work"
    text = f"{what} most around {drift['peak_now']:02d}:00 (was {drift['peak_before']:02d}:00)"
    node = kg.get_node_by_label(label) if label else None
    if node:
        props = node["properties"]
        props["previous_text"] = props.get("text", "")
        props["text"] = text
        props["drift_at"] = datetime.now(timezone.utc).isoformat()
        kg._index_node(node)
        kg._save()
    return text


def stale_beliefs(store, kg, now: datetime) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_cfg()["stale_days"])).isoformat()
    out = []
    for f in store._rows("SELECT * FROM facts WHERE status='active' AND category IN ('goal','value','constraint') "
                         "AND created_at < ?", (cutoff,)):
        label = f"{f['category']}:{f['object']}"
        node = kg.get_node_by_label(label)
        stat = store.memory_stat(node["id"]) if node else None
        if stat and (stat.get("last_used") or "") >= cutoff:
            continue                                     # still being used: not stale
        noun = {"goal": "one of your goals", "value": "important to you", "constraint": "one of your limits"}[f["category"]]
        out.append({
            "type": "drift_belief", "source": "drift", "dedupe": f["id"],
            "text": f"Is \"{f['object']}\" still {noun}?",
            "why": f"You told me \"{(f['quote'] or f['object'])[:70]}\" over {_cfg()['stale_days']} days ago and it "
                   f"hasn't come up since.",
            "evidence": [f["id"]], "value": 0.45, "urgency": "low", "confidence": 0.5, "mode": "framing",
            "options": [{"label": "Still true", "action": {"kind": "fact_keep", "payload": {"fact_id": f["id"]}}},
                        {"label": "Not anymore", "action": {"kind": "fact_retire", "payload": {"fact_id": f["id"]}}}],
            "expires_in_min": 72 * 60})
    return out


def run(now: datetime | None = None) -> dict:
    from backend.memory.knowledge_graph import get_graph
    from backend.brain.ledger import log_candidate
    cfg = _cfg()
    kg = get_graph()
    store = kg._store
    if not cfg["enabled"] or store is None:
        return {"skipped": True}
    now = now or datetime.now(timezone.utc)
    changes = []
    for kind in ("message", "focus_start"):
        d = rhythm_drift(store, kind, now)
        if d:
            text = _apply_rhythm(kg, d)
            changes.append(text)
            log_candidate(type="drift_rhythm", text=f"Updated: the user {text}.", why="", evidence=[],
                          source="drift", decision="noted", gates=d, validate=False,
                          reason=f"Jensen–Shannon distance {d['distance']} between the last two 4-week windows")
    stale = stale_beliefs(store, kg, now)
    if stale:
        from backend.brain.proactive import submit
        for c in stale[:3]:
            submit(c)
    return {"rhythm": changes, "stale_questions": len(stale)}
