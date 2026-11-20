"""Brain V3 P13: cognitive / emotional state estimate — relative to the user's OWN baseline.

    estimate(now) -> {"focus", "load", "fatigue", "stress": 0..1, "reasons": {dim: [..]},
                      "calibrating": [dims without enough history]}
    directives(state) -> prompt lines that adapt tone, complexity and length (never mention the
                         estimate to the user, never label or diagnose)
    correct(dim, value) -> the user says "I'm fine, just busy": a 24 h override + logged for calibration
    log(now) -> state_log row (used for baselines and the "corrections per week" metric)

Signals (no model calls):
  focus    timing.focus (deep-focus minutes)
  load     open tasks due in 48 h, today's scheduled hours, app-switch rate — each as a z-score
           against the user's last 4 weeks (signal_stats / Planner history)
  fatigue  late-night activity last night, active minutes today, reply latency vs the user's median,
           self-reports captured in the last 24 h ("tired", "didn't sleep")
  stress   open high/medium frictions, deadlines within 24 h, frustration signals in the last 2 h,
           stress words captured in the last 24 h
Each dimension = sigmoid of a weighted sum; dimensions whose baseline has < 7 days of data are
estimated from absolute rules only and reported as "calibrating".
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config

DIMS = ("focus", "load", "fatigue", "stress")
_FATIGUE_WORDS = ("tired", "exhausted", "sleepy", "didn't sleep", "did not sleep", "no sleep", "drained", "worn out")
_STRESS_WORDS = ("stressed", "anxious", "overwhelmed", "panic", "pressure", "worried", "tense")
_SCHEMA = """CREATE TABLE IF NOT EXISTS state_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, state TEXT NOT NULL, reasons TEXT,
    corrected TEXT)"""
_cache: dict = {"at": None, "value": None}


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("state", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "min_baseline_days": int(c.get("min_baseline_days", 7)),
            "cache_s": int(c.get("cache_s", 60))}


def _store():
    from backend.memory.knowledge_graph import get_graph
    store = get_graph()._store
    if store is not None:
        with store._lock:
            store._conn.execute(_SCHEMA)
    return store


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _z(value: float, history: list[float]) -> tuple[float, bool]:
    """z-score of value against history; (0, False) when the history is too short to trust."""
    if len(history) < 7:
        return 0.0, False
    mu = statistics.mean(history)
    sd = statistics.pstdev(history) or max(abs(mu) * 0.25, 1.0)
    return (value - mu) / sd, True


# ------------------------------------------------------------------ inputs (each tolerant of missing data)
def _planner_load(now: datetime) -> tuple[int, float, list[float]]:
    """(# open tasks due within 48 h, scheduled hours today, scheduled hours per day over the last 28 days)."""
    try:
        from backend.core.planner_store import get_planner
        p = get_planner()
        items = p.all_items()
    except Exception:
        return 0, 0.0, []
    soon = (now + timedelta(hours=48)).isoformat(timespec="minutes")
    due = sum(1 for i in items if i.get("status") == "open" and i["kind"] in ("task", "reminder")
              and i.get("due_at") and i["due_at"] <= soon)

    def hours_on(day) -> float:
        lo = datetime.combine(day, datetime.min.time())
        hi = lo + timedelta(days=1)
        total = 0.0
        for i in items:
            if i["kind"] != "event" or i.get("status") == "cancelled":
                continue
            for inst in p.expand(i, lo, hi):
                s, e = inst.get("start_at") or "", inst.get("end_at") or ""
                if len(s) > 10 and len(e) > 10:
                    total += (datetime.fromisoformat(e[:16]) - datetime.fromisoformat(s[:16])).total_seconds() / 3600
        return total
    today = hours_on(now.date())
    history = [hours_on(now.date() - timedelta(days=k)) for k in range(1, 29)]
    history = [h for h in history if h > 0] if sum(1 for h in history if h > 0) >= 7 else history[:0]
    return due, today, history


def _signal_rows(store, kind: str, since: datetime) -> list[dict]:
    rows = store._rows("SELECT ts, value FROM signals WHERE kind=? AND ts >= ? ORDER BY id", (kind, since.isoformat()))
    for r in rows:
        r["value"] = json.loads(r["value"] or "{}")
    return rows


def _hourly_stats(store, kind: str, days: int = 28) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H")
    rows = store._rows("SELECT hour, n, sums FROM signal_stats WHERE kind=? AND hour >= ?", (kind, since))
    for r in rows:
        r["sums"] = json.loads(r["sums"] or "{}")
    return rows


def _recent_self_reports(store, words: tuple[str, ...]) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    hits = []
    for f in store._rows("SELECT predicate, object, quote FROM facts WHERE created_at >= ? AND status IN "
                         "('active','pending')", (since,)):
        text = f"{f['predicate']} {f['object']} {f['quote'] or ''}".lower()
        if any(w in text for w in words):
            hits.append(f["object"])
    return hits


# ------------------------------------------------------------------ estimate
def estimate(now: datetime | None = None, use_cache: bool = True) -> dict:
    cfg = _cfg()
    if use_cache and _cache["at"] and (datetime.now() - _cache["at"]).total_seconds() < cfg["cache_s"]:
        return _cache["value"]
    now = now or datetime.now()
    now_utc = datetime.now(timezone.utc)
    store = _store()
    reasons: dict[str, list[str]] = {d: [] for d in DIMS}
    calibrating: set[str] = set()
    score = {d: 0.0 for d in DIMS}

    # focus
    try:
        from backend.brain.timing import get_timing
        t = get_timing().snapshot()
    except Exception:
        t = {}
    if t.get("focus"):
        mins = t["focus"]["minutes"]
        score["focus"] = min(1.0, 0.5 + mins / 120)
        reasons["focus"].append(f"{int(mins)} min of deep work ({t['focus']['category']})")
    elif not t.get("sensor_online"):
        calibrating.add("focus")
        reasons["focus"].append("desktop sensor offline")

    # load
    due, today_h, hist_h = _planner_load(now)
    z_h, ok_h = _z(today_h, hist_h)
    load_x = -1.0 + 0.35 * due + (0.6 * z_h if ok_h else 0.25 * max(0.0, today_h - 4))
    if due:
        reasons["load"].append(f"{due} tasks due within 48 h")
    if today_h:
        reasons["load"].append(f"{today_h:.1f} h scheduled today" + (f" (usual {statistics.mean(hist_h):.1f} h)" if ok_h else ""))
    if not ok_h:
        calibrating.add("load")
    if store is not None:
        rows = _signal_rows(store, "desktop_window", now_utc - timedelta(hours=1))
        if rows:
            rate = sum(float(r["value"].get("switches") or 0) for r in rows) / max(len(rows) / 4, 0.25)
            hist = [r["sums"].get("switches", 0) / 60 for r in _hourly_stats(store, "desktop_window") if r["n"] >= 120]
            z_s, ok_s = _z(rate / 60, hist)
            if ok_s and z_s > 1:
                load_x += 0.5 * z_s
                reasons["load"].append("switching between apps more than usual")
    score["load"] = _sig(load_x)

    # fatigue
    fat_x = -1.5
    if store is not None:
        last_night = [r for r in _signal_rows(store, "message", now_utc - timedelta(hours=18))
                      if 0 <= datetime.fromisoformat(r["ts"]).astimezone().hour < 5]
        if last_night:
            fat_x += 1.0
            reasons["fatigue"].append(f"active after midnight ({len(last_night)} messages)")
        lat = [float(r["value"].get("ms") or 0) for r in _signal_rows(store, "response_latency", now_utc - timedelta(hours=2))]
        hist_lat = [r["sums"].get("ms", 0) / max(r["n"], 1) for r in _hourly_stats(store, "response_latency")]
        if lat:
            z_l, ok_l = _z(statistics.median(lat), hist_lat)
            if ok_l and z_l > 1:
                fat_x += 0.5 * min(z_l, 3)
                reasons["fatigue"].append("replying slower than usual")
            elif not ok_l:
                calibrating.add("fatigue")
        reports = _recent_self_reports(store, _FATIGUE_WORDS)
        if reports:
            fat_x += 2.0          # what the user says outweighs inferred hints
            reasons["fatigue"].append(f"you mentioned: {reports[0]}")
    active_today = [r for r in (_signal_rows(store, "message", now_utc.replace(hour=0, minute=0)) if store else [])]
    if len(active_today) > 40:
        fat_x += 0.5
        reasons["fatigue"].append("a long day of activity")
    score["fatigue"] = _sig(fat_x)

    # stress
    st_x = -1.5
    if store is not None:
        try:
            fr = store._rows("SELECT severity FROM frictions WHERE status='open'")
            high = sum(1 for f in fr if f["severity"] == "high")
            if fr:
                st_x += 0.8 * high + 0.25 * (len(fr) - high)
                reasons["stress"].append(f"{len(fr)} open problem{'s' if len(fr) > 1 else ''} in the next 3 days")
        except Exception:
            pass
        frus = _signal_rows(store, "dissatisfaction", now_utc - timedelta(hours=2))
        if frus:
            st_x += 0.6 * len(frus)
            reasons["stress"].append("recent frustration with answers")
        reports = _recent_self_reports(store, _STRESS_WORDS)
        if reports:
            st_x += 2.0
            reasons["stress"].append(f"you mentioned: {reports[0]}")
    if due >= 3:
        st_x += 0.3 * (due - 2)
    score["stress"] = _sig(st_x)

    # user corrections (24 h)
    if store is not None:
        for d in DIMS:
            o = store.get_meta(f"state_override:{d}")
            if o:
                val, until = o.split("|")
                if datetime.fromisoformat(until) > now_utc:
                    score[d] = float(val)
                    reasons[d].insert(0, "you corrected this")
    out = {"ts": now_utc.isoformat(), **{d: round(score[d], 2) for d in DIMS}, "reasons": reasons,
           "calibrating": sorted(calibrating)}
    _cache.update(at=datetime.now(), value=out)
    try:
        from backend.brain.working import get_working
        get_working().state = {d: out[d] for d in DIMS}
    except Exception:
        pass
    return out


def directives(state: dict) -> str:
    """Prompt adaptation. Behaviour only — never tell the user what was estimated."""
    lines = []
    if state.get("fatigue", 0) >= 0.6 or state.get("stress", 0) >= 0.6:
        lines.append("Keep it short and calm; one step at a time; no new ideas or side-quests unless asked.")
    if state.get("load", 0) >= 0.7:
        lines.append("They have a lot on: give at most 2 options and lead with a recommendation.")
    if state.get("focus", 0) >= 0.7:
        lines.append("They are in deep work: answer exactly what was asked, briefly.")
    if not lines:
        return ""
    return ("\n\n### How to talk right now (adapt silently; never mention or label the user's state)\n"
            + "\n".join(f"- {x}" for x in lines))


def correct(dim: str, value: float, hours: int = 24) -> dict:
    if dim not in DIMS:
        raise ValueError(f"dim must be one of {DIMS}")
    store = _store()
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    store._set_meta(f"state_override:{dim}", f"{max(0.0, min(1.0, value))}|{until}")
    with store._lock:
        store._conn.execute("INSERT INTO state_log(ts, state, reasons, corrected) VALUES (?,?,?,?)",
                            (datetime.now(timezone.utc).isoformat(), json.dumps({dim: value}), "[]", dim))
    _cache.update(at=None)
    return estimate(use_cache=False)


def log(now: datetime | None = None) -> None:
    store = _store()
    if store is None:
        return
    s = estimate(now, use_cache=False)
    with store._lock:
        store._conn.execute("INSERT INTO state_log(ts, state, reasons, corrected) VALUES (?,?,?,NULL)",
                            (s["ts"], json.dumps({d: s[d] for d in DIMS}), json.dumps(s["reasons"])))


def corrections_last_week() -> int:
    store = _store()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return store._rows("SELECT COUNT(*) n FROM state_log WHERE corrected IS NOT NULL AND ts >= ?", (since,))[0]["n"]
