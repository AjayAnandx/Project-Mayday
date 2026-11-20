"""Brain V3 P10: explainability check + the ledger of everything Mayday considers, shows or does.

    validate_why(why, evidence) -> (ok, reason)
        one plain sentence, specific (names a thing, time, number or quoted detail), not a
        generic filler line, and every evidence id must resolve to something real
    log_candidate(...)    a thought/suggestion candidate and what was decided (incl. "held back")
    record_suggestion(...) / resolve_suggestion(...)   what was shown and how the user reacted
    record_action(...) / undo_action(...)              audit trail for silent/autonomous actions

Rule: a candidate whose "why" fails validation is dropped (decision "rejected_unexplained").
"Why?" questions are answered from the stored why + evidence, never re-generated.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

_GENERIC = re.compile(
    r"^(because )?(i thought|it might|this (might|may|could) (help|be (useful|helpful))|based on your (data|"
    r"history|activity)|you (might|may) (like|want|find)|just in case|to help you|for your information)\b", re.I)
_SPECIFIC = re.compile(r"\d|\"|'|\b[A-Z][a-z]{2,}|(?i:\b(today|tomorrow|tonight|yesterday|monday|tuesday|"
                       r"wednesday|thursday|friday|saturday|sunday|morning|evening|week|deadline|due)\b)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def _has_table(store, name: str) -> bool:
    return bool(store._rows("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def evidence_exists(eid: str) -> bool:
    """Evidence ids: fact f_*, episode e_*, commitment c_*, idea i_*, signal s:<id>,
    planner p:<id>, graph node (any other id)."""
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    store = kg._store
    eid = str(eid or "")
    if not eid:
        return False
    if eid.startswith("s:") and store is not None:
        return bool(store._rows("SELECT 1 FROM signals WHERE id=?", (eid[2:],)))
    if eid.startswith("conv:"):
        try:
            from backend.core.data_store import get_store
            return get_store().get_conversation(eid[5:]) is not None
        except Exception:
            return False
    if eid.startswith("i:") and store is not None:
        return bool(store._rows("SELECT 1 FROM intents WHERE id=?", (eid[2:],))) if _has_table(store, "intents") \
            else False
    if eid.startswith("p:"):
        try:
            from backend.core.planner_store import get_planner
            return get_planner().get_item(eid[2:]) is not None
        except Exception:
            return False
    if store is not None:
        for prefix, table in (("wf_", "workflows"), ("cu_", "curiosity"), ("f_", "facts"), ("e_", "episodes"),
                              ("c_", "commitments"), ("i_", "ideas"), ("l_", "lessons")):
            if eid.startswith(prefix):
                return bool(store._rows(f"SELECT 1 FROM {table} WHERE id=?", (eid,)))
    return kg.get_node(eid) is not None


def validate_why(why: str, evidence: list[str] | None) -> tuple[bool, str]:
    w = " ".join((why or "").split())
    if not w:
        return False, "missing why"
    if len(w) > 220:
        return False, "why is longer than one sentence"
    if len(re.findall(r"[.!?](\s|$)", w)) > 1:
        return False, "why must be one sentence"
    if _GENERIC.search(w):
        return False, "why is generic"
    # the sentence's first word is capitalised anyway, so it doesn't count as a name
    if not _SPECIFIC.search(w.split(" ", 1)[1] if " " in w else ""):
        return False, "why names nothing specific"
    ev = [e for e in (evidence or []) if e]
    if not ev:
        return False, "no evidence"
    missing = [e for e in ev if not evidence_exists(e)]
    if missing:
        return False, f"evidence not found: {', '.join(missing[:3])}"
    return True, ""


def log_candidate(*, type: str, text: str, why: str, evidence: list[str], source: str,
                  decision: str, gates: dict | None = None, reason: str = "", validate: bool = True) -> dict:
    """Record a candidate. If the why fails validation the decision becomes rejected_unexplained."""
    if validate:
        ok, why_reason = validate_why(why, evidence)
        if not ok:
            decision, reason = "rejected_unexplained", why_reason
    row = {"id": "k_" + uuid.uuid4().hex[:12], "ts": _now(), "type": type, "source": source,
           "text": text[:500], "why": (why or "")[:300], "evidence": json.dumps(evidence or []),
           "gates": json.dumps(gates or {}), "decision": decision, "reason": reason[:200]}
    store = _store()
    if store is not None:
        store._insert("candidates", row)
    return row


def record_suggestion(*, type: str, mode: str, text: str, why: str, channel: str = "toast",
                      candidate_id: str | None = None, expires_at: str | None = None) -> dict:
    row = {"id": "g_" + uuid.uuid4().hex[:12], "candidate_id": candidate_id, "ts": _now(), "type": type,
           "mode": mode, "channel": channel, "text": text[:500], "why": why[:300], "expires_at": expires_at,
           "outcome": None, "outcome_at": None, "latency_s": None}
    _store()._insert("suggestions", row)
    return row


def resolve_suggestion(sid: str, outcome: str) -> dict | None:
    """outcome: accepted | edited | later | dismissed | less | ignored"""
    store = _store()
    rows = store._rows("SELECT * FROM suggestions WHERE id=?", (sid,))
    if not rows or rows[0]["outcome"]:
        return rows[0] if rows else None
    shown = datetime.fromisoformat(rows[0]["ts"])
    latency = (datetime.now(timezone.utc) - shown).total_seconds()
    with store._lock:
        store._conn.execute("UPDATE suggestions SET outcome=?, outcome_at=?, latency_s=? WHERE id=?",
                            (outcome, _now(), latency, sid))
    out = dict(rows[0], outcome=outcome, latency_s=latency)
    from backend.brain.feedback import on_suggestion_outcome
    on_suggestion_outcome(out)
    return out


def record_action(*, mode: str, type: str, payload: dict, why: str, evidence: list[str],
                  undo_payload: dict | None) -> dict:
    row = {"id": "a_" + uuid.uuid4().hex[:12], "ts": _now(), "mode": mode, "type": type,
           "payload": json.dumps(payload, ensure_ascii=False), "why": why[:300],
           "evidence": json.dumps(evidence or []), "undo_payload": json.dumps(undo_payload or {}),
           "outcome": "done", "undone_at": None}
    _store()._insert("actions", row)
    return row


def mark_action_undone(aid: str) -> dict | None:
    store = _store()
    rows = store._rows("SELECT * FROM actions WHERE id=?", (aid,))
    if not rows or rows[0]["undone_at"]:
        return None
    with store._lock:
        store._conn.execute("UPDATE actions SET outcome='undone', undone_at=? WHERE id=?", (_now(), aid))
    from backend.brain.feedback import on_suggestion_outcome
    on_suggestion_outcome({"type": rows[0]["type"], "outcome": "undone", "latency_s": None})
    return rows[0]


def explain(item_id: str) -> dict | None:
    """'Why?' for any candidate (k_), suggestion (g_) or action (a_): the stored reason + evidence."""
    store = _store()
    table = {"k_": "candidates", "g_": "suggestions", "a_": "actions"}.get(item_id[:2])
    if not table:
        return None
    rows = store._rows(f"SELECT * FROM {table} WHERE id=?", (item_id,))
    if not rows:
        return None
    r = rows[0]
    ev = r.get("evidence")
    if ev is None and r.get("candidate_id"):
        c = store._rows("SELECT evidence FROM candidates WHERE id=?", (r["candidate_id"],))
        ev = c[0]["evidence"] if c else "[]"
    return {"id": item_id, "why": r.get("why"), "evidence": json.loads(ev or "[]")}


def expire_suggestions(now: datetime | None = None) -> int:
    """Shown suggestions that expired without a reaction count as 'ignored'."""
    store = _store()
    if store is None:
        return 0
    now_s = (now or datetime.now(timezone.utc)).isoformat()
    rows = store._rows("SELECT id FROM suggestions WHERE outcome IS NULL AND expires_at IS NOT NULL "
                       "AND expires_at < ?", (now_s,))
    for r in rows:
        resolve_suggestion(r["id"], "ignored")
    return len(rows)
