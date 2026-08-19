"""DSPy Module C — User Awareness + Personal Task Store compiled brain.

Flag-gated, additive, default-off. Nothing here runs unless BOTH
``dspy.enabled`` and the specific module flag (e.g. ``dspy.ua5_gate``) are true.
When disabled, every module falls back to the deterministic heuristic it
replaces, so behavior is identical to the non-DSPy path.

All compiled inputs/results stay local (T1/T2 never leave the machine); cloud
models are only used for T0 beliefs and only when explicitly opted in via
``dspy.reflection_model``.
"""
from typing import Optional

from backend.core.config import load_config
from backend.core.user_awareness import AwarenessStore


def _cfg():
    return load_config().get("dspy", {})


def _module_enabled(flag: str) -> bool:
    return bool(_cfg().get("enabled", False) and _cfg().get(flag, False))


def _load_compiled(module_name: str):
    """Lazily load a compiled DSPy program. Returns None if unavailable."""
    try:
        import dspy  # noqa: F401
    except ImportError:
        return None
    artifacts_dir = _cfg().get("artifacts_dir", "dspy_artifacts")
    import os
    from pathlib import Path
    path = Path(artifacts_dir) / f"{module_name}.json"
    if not path.exists():
        return None
    try:
        return dspy.load(str(path))
    except Exception:
        return None


# ---- UA-1 BeliefExtractor ----
def extract_beliefs(text: str, slot_hint: Optional[str] = None) -> list[dict]:
    from backend.core.awareness_observer import extract_candidates
    cands = extract_candidates(text)
    if slot_hint:
        cands = [c for c in cands if c["slot"] == slot_hint.lower()]
    return cands


# ---- UA-2 ConfidenceAssessor ----
def assess_confidence(belief: dict, evidence: list[str]) -> float:
    store = AwarenessStore()
    existing = store.find_belief(belief.get("slot", ""), belief.get("value", ""))
    if existing:
        return float(existing["confidence"])
    return float(belief.get("confidence", 0.55))


# ---- UA-3 AskPolicy ----
def ask_policy(context: str, beliefs: list[dict], action: str) -> dict:
    if _module_enabled("ua3_ask_policy"):
        prog = _load_compiled("ua3_ask_policy")
        if prog:
            try:
                out = prog(context=context, beliefs=beliefs, action=action)
                return {"ask": bool(getattr(out, "ask", False)),
                        "question": getattr(out, "question", "")}
            except Exception:
                pass
    # heuristic: ask if any belief is low-confidence
    low = [b for b in beliefs if b.get("confidence", 1.0) < 0.5]
    return {"ask": bool(low), "question": ""}


# ---- UA-4 Reflector ----
def reflect(month_beliefs: list[dict]) -> dict:
    store = AwarenessStore()
    return store.run_reflection()


# ---- UA-5 GatePolicy (starred pilot) ----
def gate_policy(action: str, text: str, entities: Optional[list[str]] = None,
                context: str = "") -> dict:
    store = AwarenessStore()
    heuristic = store.can_do(action, text, entities=entities, context=context)
    if _module_enabled("ua5_gate"):
        prog = _load_compiled("ua5_gate")
        if prog:
            try:
                out = prog(action=action, text=text, entities=entities or [],
                           beliefs=store.list_beliefs())
                verdict = getattr(out, "verdict", heuristic["verdict"])
                # Safety: never override a hard consent block.
                if heuristic["verdict"] == "block":
                    return heuristic
                return {
                    "verdict": verdict,
                    "reason": getattr(out, "reason", heuristic["reason"]),
                    "suggestion": getattr(out, "suggestion", heuristic["suggestion"]),
                    "slot": getattr(out, "slot", heuristic["slot"]),
                    "entities": getattr(out, "entities", heuristic["entities"]),
                    "compiled": True,
                }
            except Exception:
                pass
    return heuristic


# ---- UA-6 SnapshotSelector ----
def select_snapshot(context: str, beliefs: list[dict], top_k: int = 8) -> list[dict]:
    store = AwarenessStore()
    snap = store.snapshot(context=context, top_k=top_k)
    # return chosen belief subset (parse from snapshot is lossy; expose raw list)
    return store.list_beliefs()[:top_k]


# ---- PTS-1 TaskInterpreter ----
def interpret_task(text: str) -> dict:
    """Heuristic task text -> {kind, time, entities}."""
    import re
    kind = "todo"
    if re.search(r"\b(meet|call|appointment|event|birthday|party)\b", text, re.I):
        kind = "event"
    elif re.search(r"\b(remind|remember to|don't forget)\b", text, re.I):
        kind = "reminder"
    elif re.search(r"\b(note|jot|write down)\b", text, re.I):
        kind = "note"
    time_m = re.search(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})\b", text)
    # crude entity extraction: capitalized noun phrases
    entities = re.findall(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b", text)
    return {
        "kind": kind,
        "time": time_m.group(1) if time_m else None,
        "entities": entities[:5],
    }
