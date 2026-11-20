"""Brain V3 P11: candidate generators (deterministic). P12/P13 add friction, prep and intent generators.

Each generator returns candidate dicts for proactive.submit(); none of them speak directly.
run_all() is called at natural transitions and every ~30 min by the scheduler.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
_last_run = 0.0
_lock = threading.Lock()


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def commitments_due(now: datetime) -> list[dict]:
    """Promises the user made (captured) that come due within 36 h and aren't in the Planner."""
    out = []
    store = _store()
    for c in store.list_commitments("open", limit=50):
        if c.get("planner_item_id") or not c.get("due"):
            continue
        try:
            due = datetime.fromisoformat(str(c["due"])[:10])
        except ValueError:
            continue
        hours = (due - now).total_seconds() / 3600
        if not -24 <= hours <= 36:
            continue
        when = "today" if due.date() == now.date() else due.strftime("%A")
        out.append({
            "type": "commitment_due", "source": "generators.commitments_due", "dedupe": c["id"],
            "text": f"You said you'd {c['text']} by {when}. Add it to your Planner?",
            "why": f"You told me \"{c['quote'][:80]}\" and it is due {when}.",
            "evidence": [c["id"]], "value": 0.75 if hours <= 12 else 0.6, "urgency": "timely",
            "confidence": 0.85, "mode": "nudge",
            "action": {"kind": "planner_create_task", "payload": {"title": c["text"], "due_at": str(c["due"])[:10]}},
            "expires_in_min": 12 * 60})
    return out


def learned_review(now: datetime) -> list[dict]:
    """Several captured items waiting for the user's OK → one low-priority reminder."""
    store = _store()
    pending = store.list_facts("pending", limit=20)
    lessons = store._rows("SELECT id, lesson FROM lessons WHERE status='candidate' LIMIT 5")
    n = len(pending) + len(lessons)
    if n < 3:
        return []
    example = pending[0]["quote"] if pending else lessons[0]["lesson"]
    ev = [f["id"] for f in pending[:3]] + [le["id"] for le in lessons[:2]]
    return [{
        "type": "review_learned", "source": "generators.learned_review", "dedupe": f"{now.date()}",
        "text": f"{n} things I picked up are waiting for your OK in Brain → Learned.",
        "why": f"I wasn't sure enough to save {n} items, for example \"{example[:60]}\".",
        "evidence": ev, "value": 0.45, "urgency": "low", "confidence": 0.9, "mode": "nudge",
        "expires_in_min": 24 * 60}]


def friction(now: datetime) -> list[dict]:
    """Brain V3 P12: 72-hour simulation -> conflicts, overload, unscheduled, missing prep, waiting risk."""
    from backend.brain.friction import candidates
    return candidates(now)


def intent_prereqs(now: datetime) -> list[dict]:
    """Brain V3 P13: refresh goal hypotheses (throttled) and offer missing prerequisites."""
    from backend.brain import intents
    try:
        intents.maybe_run(now)
    except Exception as e:
        logger.warning("intent inference: %s", e)
    try:
        from backend.brain.state import log as state_log
        state_log(now)
    except Exception as e:
        logger.debug("state log: %s", e)
    return intents.candidates(now)


def routine_due(now: datetime) -> list[dict]:
    """Brain V3 P14: a learned routine at its usual time ("your usual Friday report?")."""
    from backend.brain.routines import candidates
    return candidates(now)


GENERATORS = [commitments_due, learned_review, friction, intent_prereqs, routine_due]


def run_all(now: datetime | None = None, force: bool = False, min_interval_s: int = 1800) -> list[dict]:
    """Run every generator and submit its candidates. Throttled unless force=True."""
    global _last_run
    from backend.brain.proactive import submit
    with _lock:
        if not force and time.time() - _last_run < min_interval_s:
            return []
        _last_run = time.time()
    now = now or datetime.now()
    results = []
    for gen in GENERATORS:
        try:
            for c in gen(now):
                results.append({"type": c["type"], **submit(c)})
        except Exception as e:
            logger.warning("generator %s failed: %s", gen.__name__, e)
    try:  # Brain V3 P12: prep packs (silent preparation; model calls capped per day)
        from backend.brain.prep import run as prep_run
        results += [{"type": "prep", **r} for r in prep_run(now)]
    except Exception as e:
        logger.warning("prep packs failed: %s", e)
    return results


def on_transition_async() -> None:
    """Natural break: deliver deferred items, then look for new ones (off the publishing thread)."""
    def run():
        try:
            from backend.brain.proactive import on_transition
            on_transition()
            run_all(force=True)
        except Exception as e:
            logger.warning("transition handling failed: %s", e)
    threading.Thread(target=run, daemon=True, name="brain-transition").start()
