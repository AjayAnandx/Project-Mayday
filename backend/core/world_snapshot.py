"""World snapshot — daily habitus + persons + todos/events.

Runs once per day via Scheduler._check_world_snapshot().
Stitches PHF habitus top traits + 3 person briefs + 3 followups + 5 todos + 5 events + 5 ops
into world_snapshots/YYYY-MM-DD.json (≈1.2k tokens) under magma.token_budget.

T1 privacy: local-only facts filtered before cloud reflection model (enforced elsewhere).
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def build_snapshot() -> dict:
    snap: dict = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "habitus": None,
        "persons": [],
        "followups": [],
        "todos": [],
        "events": [],
        "operations": [],
    }
    # habitus
    try:
        from backend.core.phf import disposition_summary
        snap["habitus"] = disposition_summary()
    except Exception as e:
        snap["habitus"] = f"habitus unavailable: {e}"
    # persons + followups
    try:
        from backend.core.user_awareness import get_awareness_store
        store = get_awareness_store()
        # awareness store has get_person_brief etc — best effort
        if hasattr(store, "get_persons"):
            snap["persons"] = store.get_persons()[:3]
        if hasattr(store, "get_pending_followups"):
            snap["followups"] = store.get_pending_followups()[:3]
    except Exception as e:
        logger.warning("world snapshot persons failed: %s", e)
    # todos/events
    try:
        from backend.core.data_store import get_store
        ds = get_store()
        todos = ds.list_todos(include_completed=False) or []
        snap["todos"] = [{"title": t.get("title"), "due_date": t.get("due_date"), "priority": t.get("priority")} for t in todos[:5]]
        events = ds.list_events() or []
        snap["events"] = [{"title": e.get("title"), "start_time": e.get("start_time")} for e in events[:5]]
    except Exception as e:
        logger.warning("world snapshot todos/events failed: %s", e)
    # operations
    try:
        from backend.core.operation_log import get_operation_log
        op = get_operation_log()
        snap["operations"] = op.query(limit=5)
    except Exception:
        snap["operations"] = []

    # persist
    try:
        cfg_path = Path(__file__).resolve().parent.parent.parent / "world_snapshots"
        cfg_path.mkdir(parents=True, exist_ok=True)
        out = cfg_path / f"{snap['date']}.json"
        out.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("world snapshot persist failed: %s", e)

    return snap
