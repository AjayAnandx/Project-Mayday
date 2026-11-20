"""Brain V3 P12: friction and bottleneck simulation over the next 72 hours (deterministic).

    simulate(events, tasks, waiting, now, cfg) -> [friction]     pure function (tested)
    detect(now) -> [friction]                                    reads the Planner, stores `frictions`
    candidates(now) -> [candidate]                               frictions -> proactive.submit() inputs

Model of a day:
  waking window   = outside quiet hours (07:00–22:30 by default)
  busy            = timed events + tasks already time-blocked
  capacity (min)  = free waking minutes × focus_factor (0.6: nobody works every free minute)
  demand (min)    = open tasks due that day, not yet time-blocked (estimate_min, else a default)
Detections:
  conflict        two timed events overlap (≥ 5 min)
  overload        demand > capacity on a day
  unscheduled     an important task due within 48 h with no time block → proposes the first free slot
  missing_prep    an exam / interview / pitch / presentation / demo within 72 h and no open task
                  mentions it → offers revision/prep blocks (and triggers a prep pack, prep.py)
  waiting_risk    something someone owes you is due within 48 h and still open
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta

from backend.core.config import load_config

PREP_WORDS = re.compile(r"\b(exam|exams|test|interview|pitch|presentation|demo|viva|review|defen[cs]e|"
                        r"meeting with|client|investor|deadline|submission)\b", re.I)
_STOP = {"with", "the", "and", "for", "meeting", "call", "exam", "exams", "test", "review", "session"}


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("friction", {}) or {}
    p = (load_config().get("brain", {}) or {}).get("proactive", {}) or {}
    return {"horizon_hours": int(c.get("horizon_hours", 72)), "focus_factor": float(c.get("focus_factor", 0.6)),
            "default_task_min": int(c.get("default_task_min", 45)),
            "important_priority": int(c.get("important_priority", 2)),
            "quiet_hours": str(p.get("quiet_hours", "22:30-07:00"))}


def _t(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:16]) if len(str(s)) > 10 else datetime.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _has_time(s: str | None) -> bool:
    return bool(s) and len(str(s)) > 10


def _waking(day: date, quiet: str) -> tuple[datetime, datetime]:
    try:
        a, b = quiet.split("-")
        sleep_h, sleep_m = (int(x) for x in a.split(":"))
        wake_h, wake_m = (int(x) for x in b.split(":"))
    except ValueError:
        sleep_h, sleep_m, wake_h, wake_m = 22, 30, 7, 0
    return (datetime.combine(day, datetime.min.time()).replace(hour=wake_h, minute=wake_m),
            datetime.combine(day, datetime.min.time()).replace(hour=sleep_h, minute=sleep_m))


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def free_slots(day: date, busy: list[tuple[datetime, datetime]], quiet: str,
               not_before: datetime | None = None) -> list[tuple[datetime, datetime]]:
    lo, hi = _waking(day, quiet)
    if not_before and not_before > lo:
        lo = not_before
    slots, cur = [], lo
    for s, e in _merge([(max(s, lo), min(e, hi)) for s, e in busy if e > lo and s < hi]):
        if s > cur:
            slots.append((cur, s))
        cur = max(cur, e)
    if cur < hi:
        slots.append((cur, hi))
    return slots


def _keywords(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (title or "").lower()) if w not in _STOP}


def _fmt_day(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return d.strftime("%A")


def simulate(events: list[dict], tasks: list[dict], waiting: list[dict], now: datetime,
             cfg: dict | None = None) -> list[dict]:
    """events: timed instances {id,title,start,end}; tasks: open {id,title,due,priority,estimate_min,block};
    waiting: open {id,title,due,person}. Returns friction dicts (no I/O)."""
    cfg = cfg or _cfg()
    horizon = now + timedelta(hours=cfg["horizon_hours"])
    today = now.date()
    out: list[dict] = []

    ev = sorted([e for e in events if e["start"] and e["end"] and e["end"] > now and e["start"] < horizon],
                key=lambda e: e["start"])
    # conflicts
    for i, a in enumerate(ev):
        for b in ev[i + 1:]:
            if b["start"] >= a["end"]:
                break
            overlap = (min(a["end"], b["end"]) - b["start"]).total_seconds() / 60
            if overlap >= 5:
                hours_away = (a["start"] - now).total_seconds() / 3600
                out.append({"kind": "conflict", "key": f"conflict:{a['id']}:{b['id']}",
                            "severity": "high" if hours_away < 24 else "medium", "day": a["start"].date().isoformat(),
                            "title": f"\"{a['title']}\" and \"{b['title']}\" overlap {_fmt_day(a['start'].date(), today)} "
                                     f"at {b['start']:%H:%M}",
                            "evidence": [f"p:{a['id']}", f"p:{b['id']}"], "hours_away": hours_away,
                            "detail": {"a": a["id"], "b": b["id"], "overlap_min": round(overlap)}})

    blocks = [(t["block"][0], t["block"][1]) for t in tasks if t.get("block")]
    busy_all = [(e["start"], e["end"]) for e in ev] + blocks
    days = sorted({(now + timedelta(days=k)).date() for k in range(0, cfg["horizon_hours"] // 24 + 1)})

    # overload per day
    for d in days:
        due = [t for t in tasks if t.get("due") and t["due"].date() == d and not t.get("block")]
        demand = sum(int(t.get("estimate_min") or cfg["default_task_min"]) for t in due)
        free = sum((e - s).total_seconds() / 60 for s, e in free_slots(d, busy_all, cfg["quiet_hours"],
                                                                       now if d == today else None))
        capacity = free * cfg["focus_factor"]
        if due and demand > capacity:
            out.append({"kind": "overload", "key": f"overload:{d.isoformat()}", "severity": "medium",
                        "day": d.isoformat(),
                        "title": f"{_fmt_day(d, today).capitalize()} needs ~{demand // 60}h{demand % 60:02d} for "
                                 f"{len(due)} due tasks but has ~{int(capacity) // 60}h{int(capacity) % 60:02d} free",
                        "evidence": [f"p:{t['id']}" for t in due[:5]],
                        "detail": {"demand_min": demand, "capacity_min": int(capacity),
                                   "tasks": [t["id"] for t in due]}})

    # important tasks due within 48h with no time block -> first free slot
    for t in tasks:
        due = t.get("due")
        if not due or t.get("block") or int(t.get("priority") or 4) > cfg["important_priority"]:
            continue
        if not now <= due <= now + timedelta(hours=48) and not (due.date() == today):
            continue
        need = int(t.get("estimate_min") or cfg["default_task_min"])
        # must finish before the deadline (date-only deadline = end of that day)
        deadline = due if _has_time(t.get("due_raw")) else datetime.combine(due.date(), datetime.max.time())
        slot = None
        d = today
        while slot is None and d <= due.date():
            for s, e in free_slots(d, busy_all, cfg["quiet_hours"], now if d == today else None):
                end = s + timedelta(minutes=need)
                if end <= e and end <= deadline:
                    slot = (s, end)
                    break
            d += timedelta(days=1)
        if slot:
            busy_all.append(slot)
            out.append({"kind": "unscheduled", "key": f"unscheduled:{t['id']}", "severity": "medium",
                        "day": due.date().isoformat(),
                        "title": f"\"{t['title']}\" is due {_fmt_day(due.date(), today)} and has no time set aside",
                        "evidence": [f"p:{t['id']}"],
                        "detail": {"task": t["id"], "slot": [slot[0].isoformat(timespec="minutes"),
                                                             slot[1].isoformat(timespec="minutes")],
                                   "minutes": need}})

    # missing preparation before exams / interviews / pitches …
    open_kw = [(_keywords(t["title"]), t["id"]) for t in tasks]
    for e in ev:
        if not PREP_WORDS.search(e["title"]):
            continue
        kw = _keywords(e["title"])
        if any(kw and len(kw & tk) >= 1 for tk, tid in open_kw):
            continue
        days_left = (e["start"].date() - today).days
        out.append({"kind": "missing_prep", "key": f"missing_prep:{e['id']}:{e['start']:%Y%m%d}",
                    "severity": "high" if days_left <= 1 else "medium", "day": e["start"].date().isoformat(),
                    "title": f"\"{e['title']}\" is {_fmt_day(e['start'].date(), today)} at {e['start']:%H:%M} "
                             f"and nothing is planned to prepare for it",
                    "evidence": [f"p:{e['id']}"], "detail": {"event": e["id"], "starts": e["start"].isoformat(),
                                                             "days_left": days_left}})

    # waiting-on risk
    for w in waiting:
        due = w.get("due")
        if due and now - timedelta(hours=24) <= due <= now + timedelta(hours=48):
            who = w.get("person") or "Someone"
            out.append({"kind": "waiting_risk", "key": f"waiting:{w['id']}", "severity": "medium",
                        "day": due.date().isoformat(),
                        "title": f"{who} still owes you \"{w['title']}\", due {_fmt_day(due.date(), today)}",
                        "evidence": [f"p:{w['id']}"], "detail": {"item": w["id"], "person": who}})
    return out


# ------------------------------------------------------------------ planner I/O
def _planner_inputs(now: datetime) -> tuple[list, list, list]:
    from backend.core.planner_store import get_planner
    p = get_planner()
    hi = now + timedelta(hours=_cfg()["horizon_hours"])
    lo = datetime.combine(now.date(), datetime.min.time())
    people = {x["id"]: x.get("name") for x in p.list_people()}
    events, tasks, waiting = [], [], []
    for i in p.all_items():
        if i.get("status") != "open":
            continue
        if i["kind"] == "event":
            for inst in p.expand(i, lo, hi):
                s = _t(inst.get("start_at"))
                if not s or not _has_time(inst.get("start_at")):
                    continue
                e = _t(inst.get("end_at")) or s + timedelta(hours=1)
                events.append({"id": i["id"], "title": i.get("title", ""), "start": s, "end": e})
        elif i["kind"] in ("task", "reminder"):
            blk = i.get("scheduled_block") or {}
            block = (_t(blk.get("start")), _t(blk.get("end"))) if blk.get("start") and blk.get("end") else None
            tasks.append({"id": i["id"], "title": i.get("title", ""), "due": _t(i.get("due_at")),
                          "due_raw": i.get("due_at"), "priority": i.get("priority") or 4,
                          "estimate_min": i.get("estimate_min"), "block": block})
        elif i["kind"] == "waiting":
            waiting.append({"id": i["id"], "title": i.get("title", ""), "due": _t(i.get("due_at")),
                            "person": people.get(i.get("person_id") or "")})
    return events, tasks, waiting


_SCHEMA = """CREATE TABLE IF NOT EXISTS frictions (
    key TEXT PRIMARY KEY, kind TEXT NOT NULL, severity TEXT, day TEXT, title TEXT NOT NULL,
    detail TEXT, evidence TEXT, status TEXT NOT NULL DEFAULT 'open', first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL)"""


def detect(now: datetime | None = None) -> list[dict]:
    """Run the simulator on the Planner; upsert `frictions`; mark vanished ones resolved."""
    from backend.memory.knowledge_graph import get_graph
    now = now or datetime.now()
    found = simulate(*_planner_inputs(now), now)
    store = get_graph()._store
    if store is not None:
        stamp = datetime.now().isoformat(timespec="seconds")
        with store._lock:
            store._conn.execute(_SCHEMA)
            keys = {f["key"] for f in found}
            for f in found:
                store._conn.execute(
                    "INSERT INTO frictions(key, kind, severity, day, title, detail, evidence, status, first_seen, "
                    "last_seen) VALUES (?,?,?,?,?,?,?,'open',?,?) ON CONFLICT(key) DO UPDATE SET "
                    "severity=excluded.severity, title=excluded.title, detail=excluded.detail, "
                    "last_seen=excluded.last_seen, status='open'",
                    (f["key"], f["kind"], f["severity"], f["day"], f["title"], json.dumps(f["detail"]),
                     json.dumps(f["evidence"]), stamp, stamp))
            for r in store._conn.execute("SELECT key FROM frictions WHERE status='open'").fetchall():
                if r[0] not in keys:
                    store._conn.execute("UPDATE frictions SET status='resolved', last_seen=? WHERE key=?",
                                        (stamp, r[0]))
    return found


def to_candidate(f: dict, now: datetime) -> dict | None:
    """One friction -> one proactive candidate (mode/value/urgency by kind)."""
    base = {"source": f"friction.{f['kind']}", "dedupe": f["key"], "evidence": f["evidence"],
            "why": f["title"] + ".", "expires_in_min": 12 * 60}
    if f["kind"] == "conflict":
        urgent = f.get("hours_away", 99) < 6
        return {**base, "type": "friction_conflict", "text": f"Clash: {f['title']}. Want to move one?",
                "value": 0.85, "urgency": "urgent" if urgent else "timely", "confidence": 0.95, "mode": "nudge"}
    if f["kind"] == "overload":
        return {**base, "type": "friction_overload",
                "text": f"{f['title']}. Push the lowest-priority ones to a lighter day?",
                "value": 0.65, "urgency": "timely", "confidence": 0.7, "mode": "framing",
                "options": [{"label": "Show me the tasks", "action": None},
                            {"label": "Leave it", "action": None}]}
    if f["kind"] == "unscheduled":
        s, e = f["detail"]["slot"]
        return {**base, "type": "friction_unscheduled",
                "text": f"{f['title'].split(' is due')[0]}: block {s[11:16]}–{e[11:16]} "
                        f"{'today' if s[:10] == now.date().isoformat() else s[:10]} for it?",
                "value": 0.6, "urgency": "timely", "confidence": 0.75, "mode": "nudge",
                "action": {"kind": "planner_schedule_task",
                           "payload": {"item_id": f["detail"]["task"], "start": s, "end": e}}}
    if f["kind"] == "missing_prep":
        d = f["detail"]
        start = datetime.fromisoformat(d["starts"])
        n = 2 if d["days_left"] >= 2 else 1
        title = f["title"].split('"')[1] if '"' in f["title"] else "it"
        opts = [{"label": f"Add {n} prep session{'s' if n > 1 else ''}",
                 "action": {"kind": "planner_create_task",
                            "payload": {"title": f"Prepare for {title}",
                                        "due_at": (start - timedelta(days=1)).date().isoformat()}}},
                {"label": "I'm prepared", "action": None}]
        return {**base, "type": "friction_missing_prep", "text": f"{f['title']}. Plan some prep time?",
                "value": 0.8 if d["days_left"] <= 3 else 0.6,
                "urgency": "timely", "confidence": 0.65, "mode": "framing", "options": opts}
    if f["kind"] == "waiting_risk":
        return {**base, "type": "friction_waiting", "text": f"{f['title']}. Draft a polite nudge?",
                "value": 0.6, "urgency": "timely", "confidence": 0.8, "mode": "nudge",
                "action": {"kind": "planner_nudge_draft", "payload": {"item_id": f["detail"]["item"]}}}
    return None


def candidates(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    out = []
    for f in detect(now):
        c = to_candidate(f, now)
        if c:
            out.append(c)
    return out
