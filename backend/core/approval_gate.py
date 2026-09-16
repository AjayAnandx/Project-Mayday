"""Approval gate: pause phase when user says 'get my approval'.

Default = no confirmation. Only when user text matches the gate phrase we
emit a gate event and wait for confirm. Persisted to approval_gates.json.
"""
import json
import re
import threading
from pathlib import Path
from typing import Optional

from backend.core.config import load_config

_GATE_RE = re.compile(r"get my approval|pause (on|at) phase|wait for approval", re.I)

# phases that can be gated
PHASES = ("research", "design", "build", "audit", "trend", "verify", "deep_learn")

_gate_path: Path | None = None
_lock = threading.RLock()

def _path() -> Path:
    global _gate_path
    if _gate_path is None:
        cfg = load_config()
        raw = cfg.get("approval_gate", {}).get("path", "approval_gates.json") if isinstance(cfg.get("approval_gate"), dict) else "approval_gates.json"
        p = Path(str(raw))
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent.parent / p
        _gate_path = p
    return _gate_path

def should_gate(user_text: str, phase: str) -> bool:
    if not user_text or not phase:
        return False
    if phase not in PHASES and phase != "any":
        # allow any phase, but keep regex check
        pass
    return bool(_GATE_RE.search(user_text))

def _load() -> dict:
    pp = _path()
    if pp.exists():
        try:
            return json.loads(pp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save(data: dict):
    pp = _path()
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def set_gate(conversation_id: str, phase: str, gated: bool = True):
    with _lock:
        data = _load()
        if gated:
            data[conversation_id] = {"phase": phase, "gated": True}
        else:
            data.pop(conversation_id, None)
        _save(data)

def is_gated(conversation_id: str) -> tuple[bool, str]:
    with _lock:
        data = _load()
        rec = data.get(conversation_id)
        if rec and rec.get("gated"):
            return True, rec.get("phase", "")
        return False, ""

def clear_gate(conversation_id: str):
    set_gate(conversation_id, "", gated=False)
