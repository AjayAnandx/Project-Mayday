"""Brain V3 P11: decision policy + graduated agency.

    submit(candidate) -> outcome           the single entry point for every proactive idea
    on_transition()                        deliver deferred items at a natural break
    execute_accepted(suggestion_id)        "Do it" on a nudge / an option chosen on a framing card
    undo(action_id)                        reverse a silent / autonomous action

A candidate:
    {"type": "commitment_due", "text": "…", "why": "<one sentence>", "evidence": ["c_…"],
     "source": "generator name", "value": 0..1, "urgency": "urgent|timely|low",
     "confidence": 0..1, "mode": "silent_prep|nudge|framing|autonomous",
     "action": {"kind": "<ACTIONS key>", "payload": {...}} | None,
     "options": [{"label": "…", "action": {...}}] (framing only), "expires_in_min": 240}

Four gates, in order (a failing gate CHANGES the outcome rather than just blocking):
  G1 relevance/utility   value >= base + dial + learned type threshold, and a valid "why"   → else: thought
  G2 timing/receptivity  urgent bypass; deep focus or away → defer; Thompson-sampled acceptance
                         for this type (Beta from type_stats) too low → morning digest           → else: defer/digest
  G3 confidence vs risk  autonomous needs pre-authorised + reversible + confidence ≥ 0.85, else → nudge;
                         confidence < 0.6 → framing (if options) else thought
  G4 budget              daily cap by dial, 30-min cool-down after a dismissal, quiet hours     → digest
Everything is written to the ledger (candidates / suggestions / actions).
"""
from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config

logger = logging.getLogger(__name__)

DIALS = {"off": {"budget": 0, "offset": 1.0}, "quiet": {"budget": 1, "offset": 0.15},
         "balanced": {"budget": 3, "offset": 0.0}, "eager": {"budget": 6, "offset": -0.1}}
BASE_THRESHOLD = 0.4
MODES = ("silent_prep", "nudge", "framing", "autonomous")


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("proactive", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "dial": str(c.get("dial", "balanced")),
            "quiet_hours": str(c.get("quiet_hours", "22:30-07:00")), "urgent_cap": int(c.get("urgent_cap", 3)),
            "cooldown_min": int(c.get("cooldown_min", 30)),
            "preauthorized": list(c.get("preauthorized", ["planner_move_own_block"])),
            "earned_autonomy_after": int(c.get("earned_autonomy_after", 5)),
            "min_sample": float(c.get("min_sample", 0.2))}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def dial() -> str:
    """User override (stored in brain.db) beats config."""
    store = _store()
    d = store.get_meta("proactive_dial") if store is not None else None
    d = d or _cfg()["dial"]
    return d if d in DIALS else "balanced"


def set_dial(value: str) -> str:
    if value not in DIALS:
        raise ValueError(f"dial must be one of {list(DIALS)}")
    _store()._set_meta("proactive_dial", value)
    return value


# ------------------------------------------------------------------ actions (risk table + executors)
def _planner():
    from backend.core.planner_store import get_planner
    return get_planner()


def _exec_move_block(p: dict) -> dict:
    item = _planner().get_item(p["item_id"])
    if not item:
        raise ValueError("item not found")
    prev = item.get("scheduled_block")
    _planner().schedule_item(p["item_id"], p.get("start"), p.get("end"))
    return {"item_id": p["item_id"], "previous_block": prev}


def _undo_move_block(u: dict) -> None:
    prev = u.get("previous_block") or {}
    _planner().schedule_item(u["item_id"], prev.get("start"), prev.get("end"))


def _exec_create_task(p: dict) -> dict:
    item = _planner().create_item(p["title"], kind=p.get("kind", "task"), due_at=p.get("due_at"),
                                  source={"type": "brain", "why": p.get("why", "")[:200]})
    return {"item_id": item["id"]}


def _undo_create_task(u: dict) -> None:
    _planner().delete_item(u["item_id"])


def _exec_gmail_draft(p: dict) -> dict:
    from backend.core.gmail_service import create_draft
    d = create_draft(to=p["to"], subject=p["subject"], text=p["text"])
    return {"draft_id": (d or {}).get("id")}


def _undo_gmail_draft(u: dict) -> None:
    try:
        from backend.core.gmail_service import get_gmail_service
        if u.get("draft_id"):
            get_gmail_service("agent").users().drafts().delete(userId="me", id=u["draft_id"]).execute()
    except Exception as e:
        logger.warning("draft undo failed: %s", e)


def _exec_nudge_draft(p: dict) -> dict:
    from backend.core.planner_nudge import draft_nudge
    r = draft_nudge(p["item_id"])
    if not r.get("drafted"):
        raise ValueError(r.get("reason") or "could not draft")
    return {"draft_id": r.get("draft_id")}


def _exec_fact_retire(p: dict) -> dict:
    """'Not anymore': the fact stops being active (kept, restorable)."""
    from backend.brain.capture import _unmirror_fact
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    f = kg._store.get_fact(p["fact_id"])
    if not f:
        raise ValueError("fact not found")
    kg._store.update_fact(f["id"], status="retired", valid_to=datetime.now(timezone.utc).isoformat())
    _unmirror_fact(kg, f)
    return {"fact_id": f["id"]}


def _undo_fact_retire(u: dict) -> None:
    from backend.brain.capture import _mirror_fact
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    f = kg._store.update_fact(u["fact_id"], status="active", valid_to=None)
    if f:
        _mirror_fact(kg, f["subject_id"], f["predicate"], f["object"], f["id"], f.get("category") or "fact")


def _exec_fact_keep(p: dict) -> dict:
    """'Still true': reinforce it, so it isn't asked about again soon."""
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    f = kg._store.get_fact(p["fact_id"])
    if not f:
        raise ValueError("fact not found")
    cat = f.get("category") or "fact"
    node = kg.get_node_by_label(f"{cat}:{f['object']}") or kg.get_node_by_label(f["object"])
    kg._store.touch([x for x in (node["id"] if node else None, f["subject_id"]) if x], importance=0.9)
    kg._store.update_fact(f["id"], confidence=1.0)
    return {"fact_id": f["id"]}


def _exec_note(p: dict) -> dict:
    """Silent preparation result kept for the user (e.g. a prep pack) — just recorded."""
    return {"note": p.get("title", "")}


ACTIONS: dict[str, dict] = {
    # kind:                     risk        reversible  internal  executor            undo
    "planner_move_own_block": {"risk": 0.2, "reversible": True, "internal": True,
                               "exec": _exec_move_block, "undo": _undo_move_block},
    "planner_create_task": {"risk": 0.3, "reversible": True, "internal": True,
                            "exec": _exec_create_task, "undo": _undo_create_task},
    "gmail_draft": {"risk": 0.35, "reversible": True, "internal": True,
                    "exec": _exec_gmail_draft, "undo": _undo_gmail_draft},
    "planner_schedule_task": {"risk": 0.25, "reversible": True, "internal": True,
                              "exec": _exec_move_block, "undo": _undo_move_block},
    "planner_nudge_draft": {"risk": 0.35, "reversible": True, "internal": True,
                            "exec": _exec_nudge_draft, "undo": _undo_gmail_draft},
    "fact_retire": {"risk": 0.2, "reversible": True, "internal": True,
                    "exec": _exec_fact_retire, "undo": _undo_fact_retire},
    "fact_keep": {"risk": 0.05, "reversible": True, "internal": True,
                  "exec": _exec_fact_keep, "undo": lambda u: None},
    "prepare_note": {"risk": 0.05, "reversible": True, "internal": True,
                     "exec": _exec_note, "undo": lambda u: None},
}
NEVER_AUTONOMOUS = {"gmail_send", "payment", "booking", "delete", "message_new_contact"}


def execute(kind: str, payload: dict, *, mode: str, why: str, evidence: list[str]) -> dict:
    from backend.brain.ledger import record_action
    spec = ACTIONS.get(kind)
    if not spec:
        raise ValueError(f"unknown action {kind}")
    undo_payload = spec["exec"](payload)
    return record_action(mode=mode, type=kind, payload=payload, why=why, evidence=evidence,
                         undo_payload=undo_payload)


def undo(action_id: str) -> bool:
    from backend.brain.ledger import mark_action_undone
    store = _store()
    rows = store._rows("SELECT * FROM actions WHERE id=?", (action_id,))
    if not rows or rows[0]["undone_at"]:
        return False
    spec = ACTIONS.get(rows[0]["type"])
    if spec:
        spec["undo"](json.loads(rows[0]["undo_payload"] or "{}"))
    mark_action_undone(action_id)
    _reset_streak(rows[0]["type"])
    return True


# ------------------------------------------------------------------ earned autonomy
def _streak_key(kind: str) -> str:
    return f"autonomy_streak:{kind}"


def _reset_streak(kind: str) -> None:
    store = _store()
    if store is not None:
        store._set_meta(_streak_key(kind), "0")


def note_accept(kind: str, edited: bool) -> int:
    """Consecutive accepts without edits for an action kind; returns the new streak."""
    store = _store()
    n = 0 if edited else int(store.get_meta(_streak_key(kind)) or 0) + 1
    store._set_meta(_streak_key(kind), str(n))
    return n


def preauthorized() -> set[str]:
    store = _store()
    extra = set(json.loads(store.get_meta("preauthorized_extra") or "[]")) if store is not None else set()
    removed = set(json.loads(store.get_meta("preauthorized_removed") or "[]")) if store is not None else set()
    return (set(_cfg()["preauthorized"]) | extra) - removed - NEVER_AUTONOMOUS


def set_preauthorized(kind: str, allowed: bool) -> set[str]:
    if kind in NEVER_AUTONOMOUS or kind not in ACTIONS:
        raise ValueError(f"{kind} cannot be pre-authorised")
    store = _store()
    extra = set(json.loads(store.get_meta("preauthorized_extra") or "[]"))
    removed = set(json.loads(store.get_meta("preauthorized_removed") or "[]"))
    (extra.add if allowed else extra.discard)(kind)
    (removed.discard if allowed else removed.add)(kind)
    store._set_meta("preauthorized_extra", json.dumps(sorted(extra)))
    store._set_meta("preauthorized_removed", json.dumps(sorted(removed)))
    return preauthorized()


# ------------------------------------------------------------------ gates
def _in_quiet_hours(now_local: datetime) -> bool:
    try:
        a, b = _cfg()["quiet_hours"].split("-")
        start = tuple(int(x) for x in a.split(":"))
        end = tuple(int(x) for x in b.split(":"))
    except ValueError:
        return False
    t = (now_local.hour, now_local.minute)
    return (start <= t or t < end) if start > end else (start <= t < end)


def _shown_today(urgent: bool | None = None) -> int:
    store = _store()
    since = _now().replace(hour=0, minute=0, second=0).isoformat()
    rows = store._rows("SELECT type FROM suggestions WHERE ts >= ? AND channel != 'digest'", (since,))
    if urgent is None:
        return len(rows)
    return sum(1 for r in rows if r["type"].startswith("urgent:") == urgent)


def _recent_dismissal(minutes: int) -> bool:
    store = _store()
    since = (_now() - timedelta(minutes=minutes)).isoformat()
    return bool(store._rows("SELECT 1 FROM suggestions WHERE outcome IN ('dismissed','less') AND outcome_at >= ?",
                            (since,)))


def _sample_acceptance(type_: str) -> float:
    from backend.brain.feedback import acceptance_prior
    a, b = acceptance_prior(type_)
    return random.betavariate(a, b)


def evaluate(c: dict, now_local: datetime | None = None) -> dict:
    """Run the four gates. Returns {"decision", "mode", "gates", "reason"} without side effects."""
    from backend.brain.feedback import threshold_offset
    from backend.brain.ledger import validate_why
    cfg = _cfg()
    now_local = now_local or datetime.now()
    d = dial()
    gates: dict = {"dial": d}
    urgent = c.get("urgency") == "urgent"

    # G1 relevance & utility
    ok, why_reason = validate_why(c.get("why", ""), c.get("evidence"))
    thr = BASE_THRESHOLD + DIALS[d]["offset"] + threshold_offset(c["type"])
    # Brain V3 P13: a stressed / overloaded user gets fewer non-urgent ideas
    try:
        from backend.brain.state import estimate
        st = estimate()
        gates["state"] = {k: st[k] for k in ("focus", "load", "fatigue", "stress")}
        if not urgent and st["stress"] >= 0.7:
            thr += 0.1
    except Exception:
        st = {}
    gates["G1"] = {"value": c.get("value", 0), "threshold": round(thr, 3), "why_ok": ok}
    if not ok:
        return {"decision": "rejected_unexplained", "mode": None, "gates": gates, "reason": why_reason}
    if c.get("value", 0) < thr and not urgent:
        return {"decision": "thought", "mode": None, "gates": gates, "reason": "below utility threshold"}

    # G3 first decides the *mode* (it doesn't depend on timing), then timing/budget decide *when*
    mode = c.get("mode") or "nudge"
    action = c.get("action") or {}
    kind = action.get("kind")
    spec = ACTIONS.get(kind or "", {})
    conf = float(c.get("confidence", 0.5))
    if mode == "autonomous":
        if not (kind in preauthorized() and spec.get("reversible") and conf >= 0.85):
            mode = "nudge"
            gates["G3"] = {"downgraded": "autonomous→nudge", "preauthorized": kind in preauthorized()}
    if mode == "silent_prep" and not (spec.get("internal") and spec.get("reversible")):
        mode = "nudge"
        gates["G3"] = {"downgraded": "silent_prep→nudge"}
    if mode in ("nudge", "autonomous") and conf < 0.6:
        mode = "framing" if c.get("options") else None
        gates["G3"] = {"downgraded": f"low confidence {conf:.2f}"}
        if mode is None:
            return {"decision": "thought", "mode": None, "gates": gates, "reason": "too uncertain to suggest"}
    gates.setdefault("G3", {"mode": mode, "risk": spec.get("risk")})

    if mode == "silent_prep":
        return {"decision": "prepare", "mode": mode, "gates": gates, "reason": ""}

    # G2 timing & receptivity
    from backend.brain.timing import get_timing
    t = get_timing().snapshot()
    gates["G2"] = {"focus": bool(t.get("focus")), "away": t.get("away"), "sensor_online": t.get("sensor_online")}
    if urgent:
        if _shown_today(urgent=True) >= cfg["urgent_cap"]:
            return {"decision": "digest", "mode": mode, "gates": gates, "reason": "urgent cap reached"}
        return {"decision": "deliver", "mode": mode, "gates": gates, "reason": "urgent"}
    sample = _sample_acceptance(c["type"])
    gates["G2"]["sampled_acceptance"] = round(sample, 3)
    if sample < cfg["min_sample"]:
        return {"decision": "digest", "mode": mode, "gates": gates, "reason": "low learned receptivity"}
    if st.get("load", 0) >= 0.8 and c.get("urgency") == "low":
        return {"decision": "digest", "mode": mode, "gates": gates, "reason": "heavy load right now"}
    if t.get("focus") or t.get("away"):
        return {"decision": "defer", "mode": mode, "gates": gates,
                "reason": "deep focus" if t.get("focus") else "away"}

    # G4 budget
    budget = DIALS[d]["budget"]
    gates["G4"] = {"budget": budget, "shown_today": _shown_today(urgent=False)}
    if _in_quiet_hours(now_local):
        return {"decision": "digest", "mode": mode, "gates": gates, "reason": "quiet hours"}
    if gates["G4"]["shown_today"] >= budget:
        return {"decision": "digest", "mode": mode, "gates": gates, "reason": "daily budget used"}
    if _recent_dismissal(cfg["cooldown_min"]):
        return {"decision": "defer", "mode": mode, "gates": gates, "reason": "cool-down after a dismissal"}
    return {"decision": "autonomous" if mode == "autonomous" else "deliver", "mode": mode, "gates": gates,
            "reason": ""}


# ------------------------------------------------------------------ submit / deliver
_lock = threading.Lock()


def _dedupe_key(c: dict) -> str:
    return f"{c['type']}|{c.get('dedupe') or c.get('text', '')[:80]}"


def _seen_recently(key: str, hours: int = 20) -> bool:
    store = _store()
    since = (_now() - timedelta(hours=hours)).isoformat()
    rows = store._rows("SELECT gates FROM candidates WHERE ts >= ? AND decision != 'thought'", (since,))
    return any(json.loads(r["gates"] or "{}").get("key") == key for r in rows)


def submit(c: dict, now_local: datetime | None = None) -> dict:
    """Evaluate, act on and log one candidate. Returns {"decision", "candidate_id", ...}."""
    from backend.brain.ledger import log_candidate
    if not _cfg()["enabled"] or dial() == "off" and c.get("urgency") != "urgent":
        return {"decision": "disabled"}
    key = _dedupe_key(c)
    with _lock:
        if _seen_recently(key):
            return {"decision": "duplicate"}
        ev = evaluate(c, now_local)
        gates = {**ev["gates"], "key": key, "mode": ev["mode"], "candidate": _slim(c)}
        row = log_candidate(type=c["type"], text=c["text"], why=c.get("why", ""), evidence=c.get("evidence", []),
                            source=c.get("source", ""), decision=ev["decision"], gates=gates,
                            reason=ev["reason"], validate=False)
    out = {"decision": ev["decision"], "mode": ev["mode"], "candidate_id": row["id"], "reason": ev["reason"]}
    try:
        if ev["decision"] == "prepare":
            out["action"] = _do_action(c, "silent_prep")
        elif ev["decision"] == "autonomous":
            out["action"] = _do_action(c, "autonomous")
            out["suggestion"] = _show(c, row["id"], "autonomous", action_id=out["action"]["id"])
        elif ev["decision"] == "deliver":
            out["suggestion"] = _show(c, row["id"], ev["mode"])
    except Exception as e:
        logger.warning("proactive %s failed for %s: %s", ev["decision"], c["type"], e)
        out["error"] = str(e)[:200]
    return out


def _slim(c: dict) -> dict:
    return {k: c[k] for k in ("type", "text", "why", "evidence", "source", "value", "urgency", "confidence", "mode",
                              "action", "options", "expires_in_min", "chat_prompt") if k in c}


def _do_action(c: dict, mode: str) -> dict:
    a = c.get("action") or {}
    return execute(a["kind"], {**a.get("payload", {}), "why": c.get("why", "")}, mode=mode, why=c.get("why", ""),
                   evidence=c.get("evidence", []))


def _show(c: dict, candidate_id: str, mode: str, action_id: str | None = None) -> dict:
    from backend.brain.ledger import record_suggestion
    from backend.core.scheduler import get_scheduler
    exp = (_now() + timedelta(minutes=int(c.get("expires_in_min", 240)))).isoformat()
    type_ = ("urgent:" if c.get("urgency") == "urgent" else "") + c["type"]
    s = record_suggestion(type=type_, mode=mode, text=c["text"], why=c.get("why", ""), channel="toast",
                          candidate_id=candidate_id, expires_at=exp)
    title = {"autonomous": "Done for you", "framing": "Your call", "nudge": "Suggestion"}.get(mode, "Suggestion")
    get_scheduler().fire_notification(
        title, c["text"], category="suggestion", action_page="chat",
        extra={"suggestion_id": s["id"], "why": c.get("why", ""), "mode": mode,
               "options": [o.get("label") for o in (c.get("options") or [])][:3],
               "action_id": action_id, "has_action": bool(c.get("action") or c.get("chat_prompt")),
               "chat_prompt": c.get("chat_prompt")})
    return s


def on_transition() -> list[dict]:
    """Natural break: re-evaluate deferred candidates (oldest first), deliver what now passes."""
    store = _store()
    if store is None:
        return []
    since = (_now() - timedelta(hours=12)).isoformat()
    rows = store._rows("SELECT * FROM candidates WHERE decision='defer' AND ts >= ? ORDER BY ts", (since,))
    delivered = []
    for r in rows:
        c = json.loads(r["gates"] or "{}").get("candidate")
        if not c:
            continue
        ev = evaluate(c)
        if ev["decision"] in ("deliver", "autonomous"):
            with store._lock:
                store._conn.execute("UPDATE candidates SET decision=?, reason=? WHERE id=?",
                                    (ev["decision"], "delivered at a transition", r["id"]))
            if ev["decision"] == "autonomous":
                act = _do_action(c, "autonomous")
                delivered.append(_show(c, r["id"], "autonomous", action_id=act["id"]))
            else:
                delivered.append(_show(c, r["id"], ev["mode"]))
        elif ev["decision"] == "digest":
            with store._lock:
                store._conn.execute("UPDATE candidates SET decision='digest', reason=? WHERE id=?",
                                    (ev["reason"], r["id"]))
    return delivered


def digest_items(limit: int = 5) -> list[dict]:
    """Candidates batched for the morning digest (last 24 h), best value first; marks them sent."""
    store = _store()
    since = (_now() - timedelta(hours=24)).isoformat()
    rows = store._rows("SELECT * FROM candidates WHERE decision IN ('digest','defer') AND ts >= ? ORDER BY ts",
                       (since,))
    items = []
    for r in rows:
        c = json.loads(r["gates"] or "{}").get("candidate") or {}
        items.append((c.get("value", 0), r, c))
    items.sort(key=lambda x: -x[0])
    out = []
    with store._lock:
        for _, r, c in items[:limit]:
            store._conn.execute("UPDATE candidates SET decision='digested' WHERE id=?", (r["id"],))
            out.append({"text": r["text"], "why": r["why"], "candidate_id": r["id"], "type": r["type"]})
    return out


# ------------------------------------------------------------------ accept / options
def execute_accepted(suggestion_id: str, option_index: int | None = None, edited: bool = False) -> dict | None:
    """User pressed "Do it" (or chose an option): run the suggestion's action, update earned autonomy."""
    store = _store()
    s = store._rows("SELECT * FROM suggestions WHERE id=?", (suggestion_id,))
    if not s or not s[0].get("candidate_id"):
        return None
    cand = store._rows("SELECT * FROM candidates WHERE id=?", (s[0]["candidate_id"],))
    c = json.loads(cand[0]["gates"] or "{}").get("candidate") if cand else None
    if not c:
        return None
    if option_index is not None and c.get("options"):
        opt = c["options"][option_index]
        c = {**c, "action": opt.get("action")}
    if not c.get("action"):
        return {"done": False, "reason": "no action attached"}
    act = _do_action(c, "approved")
    kind = c["action"]["kind"]
    streak = note_accept(kind, edited)
    out = {"done": True, "action": act, "streak": streak}
    if (streak >= _cfg()["earned_autonomy_after"] and kind not in preauthorized()
            and kind not in NEVER_AUTONOMOUS and ACTIONS.get(kind, {}).get("reversible")):
        out["offer_autonomy"] = kind        # UI offers "Let Mayday do this automatically?"
    return out
