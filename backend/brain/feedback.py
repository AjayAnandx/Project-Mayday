"""Brain V3 P10: implicit feedback parsing. After every action or non-action, learn.

| reaction                       | update                                                       |
|--------------------------------|--------------------------------------------------------------|
| accepted fast (< 30 s)         | accepts += 1.5, threshold − 0.04                              |
| accepted                       | accepts += 1,   threshold − 0.02                              |
| edited before use              | edits += 1 (calibration, not a vote against the content)     |
| later / not now                | later += 1 (timing only — threshold unchanged)               |
| dismissed                      | dismisses += 1, threshold + 0.05                              |
| less of this                   | dismisses += 2, threshold + 0.15                              |
| ignored (expired, no reaction) | ignores += 1,   threshold + 0.02                              |
| undone (autonomous action)     | undos += 1,     threshold + 0.20                              |

`type_stats` keeps these per suggestion/action type; P11's decision gate reads
`acceptance_prior(type)` (Beta parameters) and `threshold_offset(type)`.

Also: repeated user edits of things Mayday created (e.g. the due date of tasks it adds)
become a calibrated preference (`prefs_calibrated`), injected with the lessons.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

_UPDATES = {
    "accepted_fast": {"accepts": 1.5, "threshold": -0.04},
    "accepted": {"accepts": 1.0, "threshold": -0.02},
    "edited": {"edits": 1.0, "threshold": 0.0},
    "later": {"later": 1.0, "threshold": 0.0},
    "dismissed": {"dismisses": 1.0, "threshold": 0.05},
    "less": {"dismisses": 2.0, "threshold": 0.15},
    "ignored": {"ignores": 1.0, "threshold": 0.02},
    "undone": {"undos": 1.0, "threshold": 0.20},
}
_MIN_T, _MAX_T = -0.3, 0.6
CALIBRATION_MIN = 3
_CALIBRATED_FIELDS = {"due_at": "due date", "start_at": "time", "title": "title", "priority": "priority",
                      "list": "list", "tags": "tags", "reminders": "reminders"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def update_type(type_: str, reaction: str) -> dict | None:
    upd = _UPDATES.get(reaction)
    store = _store()
    if not upd or store is None:
        return None
    col = next(k for k in upd if k != "threshold")
    with store._lock:
        store._conn.execute("INSERT OR IGNORE INTO type_stats(type, updated_at) VALUES (?, ?)", (type_, _now()))
        store._conn.execute(
            f"UPDATE type_stats SET {col} = {col} + ?, threshold_offset = MIN(?, MAX(?, threshold_offset + ?)), "
            "updated_at = ? WHERE type = ?", (upd[col], _MAX_T, _MIN_T, upd["threshold"], _now(), type_))
    return type_stat(type_)


def type_stat(type_: str) -> dict | None:
    store = _store()
    rows = store._rows("SELECT * FROM type_stats WHERE type=?", (type_,)) if store is not None else []
    return rows[0] if rows else None


def acceptance_prior(type_: str) -> tuple[float, float]:
    """Beta(alpha, beta) for P11's Thompson sampling. Edits count as half an accept."""
    s = type_stat(type_) or {}
    alpha = 1 + (s.get("accepts") or 0) + 0.5 * (s.get("edits") or 0)
    beta = 1 + (s.get("dismisses") or 0) + 0.5 * (s.get("ignores") or 0) + 2 * (s.get("undos") or 0)
    return alpha, beta


def threshold_offset(type_: str) -> float:
    return float((type_stat(type_) or {}).get("threshold_offset") or 0.0)


def on_suggestion_outcome(s: dict) -> None:
    """Called by the ledger when a suggestion or action is resolved."""
    outcome = s.get("outcome")
    if outcome == "accepted" and (s.get("latency_s") or 1e9) < 30:
        outcome = "accepted_fast"
    update_type(s.get("type") or "unknown", outcome)


# ---------------------------------------------------------------- bus subscriber
class FeedbackParser:
    def __init__(self):
        self._edits: dict[str, list[str]] = defaultdict(list)   # field -> timestamps

    def on_signal(self, sig: dict) -> None:
        k, v = sig["kind"], sig.get("value") or {}
        if k == "suggestion_feedback" and v.get("surface") == "learned":
            # capture quality: confirm = accepted, reject = dismissed, edit = edited
            reaction = {"confirm": "accepted", "reject": "dismissed", "edit": "edited"}.get(v.get("action"))
            if reaction:
                update_type(f"capture:{v.get('kind', 'fact')}", reaction)
        elif k == "ui_dismiss":
            update_type(f"notify:{v.get('surface', 'toast')}", "dismissed")
        elif k == "planner_change" and v.get("source") == "llm" and v.get("action") in ("update", "postpone"):
            for f in v.get("fields") or []:
                if f in _CALIBRATED_FIELDS:
                    self._calibrate(f, sig.get("ts") or _now())

    def _calibrate(self, field: str, ts: str) -> None:
        """User keeps changing <field> on items Mayday created -> calibrated preference."""
        store = _store()
        if store is None:
            return
        scope = f"planner:{field}"
        pref = (f"The user often changes the {_CALIBRATED_FIELDS[field]} of Planner items Mayday creates: "
                f"ask or confirm the {_CALIBRATED_FIELDS[field]} instead of guessing.")
        rows = store._rows("SELECT * FROM prefs_calibrated WHERE scope=?", (scope,))
        with store._lock:
            if rows:
                store._conn.execute("UPDATE prefs_calibrated SET votes = votes + 1, updated_at=? WHERE scope=?",
                                    (ts, scope))
            else:
                store._conn.execute(
                    "INSERT INTO prefs_calibrated(id, scope, preference, evidence, votes, created_at, updated_at) "
                    "VALUES (?,?,?,?,1,?,?)", ("pc_" + uuid.uuid4().hex[:10], scope, pref, "planner edits", ts, ts))


def active_prefs(limit: int = 5) -> list[dict]:
    store = _store()
    if store is None:
        return []
    return store._rows("SELECT * FROM prefs_calibrated WHERE votes >= ? ORDER BY votes DESC LIMIT ?",
                       (CALIBRATION_MIN, limit))


_PARSER = FeedbackParser()


def get_parser() -> FeedbackParser:
    return _PARSER
