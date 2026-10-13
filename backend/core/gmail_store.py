"""gmail_state.json persistence — historyId + agent email (thread-safe).

Survives restarts so the 60s poll can resume incremental sync via
users.history.list(startHistoryId) without a full rescan.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent.parent / "gmail_state.json"

_lock = threading.Lock()


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "history_id_agent": None,
        "history_id_user": None,
        "agent_email": "",
        "last_sync_at": "",
    }


def _read() -> dict:
    if not STATE_PATH.exists():
        return _default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    merged = _default_state()
    merged.update({k: v for k, v in data.items() if k in merged})
    return merged


def _write(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _history_key(account: str) -> str:
    return "history_id_user" if account == "user" else "history_id_agent"


def get_history_id(account: str = "agent") -> str | None:
    with _lock:
        return _read().get(_history_key(account))


def set_history_id(account: str, history_id: str) -> None:
    with _lock:
        state = _read()
        state[_history_key(account)] = str(history_id)
        state["last_sync_at"] = _utcnow_str()
        _write(state)


def get_agent_email() -> str:
    with _lock:
        return _read().get("agent_email", "") or ""


def set_agent_email(email: str) -> None:
    with _lock:
        state = _read()
        state["agent_email"] = (email or "").strip()
        _write(state)
