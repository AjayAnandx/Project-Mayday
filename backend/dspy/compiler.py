"""Offline compile for Mayday's interactive-tier DSPy modules.

Run:  python -m backend.dspy.compiler

Builds a few hand-written demos, compiles HumanSynthesizer + IntentRouter with
BootstrapFewShot against the local 0.5b model, PII-gates the artifacts, and
saves them under backend/dspy/artifacts/interactive_tier/. Safe no-op if the
DSPy bridge is disabled. Runtime uses these artifacts when present; otherwise
it runs the uncompiled signatures (still correct, just less tuned).
"""
import logging
import os

try:
    import dspy
except Exception:  # pragma: no cover - environment dependent
    dspy = None

logger = logging.getLogger("dspy.compiler")

from backend.dspy.bridge import DspyBridge, has_pii, reset_bridge
from backend.dspy.modules import (
    HumanSynthesizer,
    IntentRouter,
    HumanSynthesizerSig,
    IntentRouterSig,
    _ART_DIR,
)

_HS_PATH = os.path.join(_ART_DIR, "human_synth.json")
_IR_PATH = os.path.join(_ART_DIR, "intent_router.json")


def _hs_trainset():
    pairs = [
        ("when is my dentist appointment",
         "Dentist appointment 2026-08-20 15:00. Reminder set.",
         "Hey! Your dentist appointment is on August 20 at 3 PM - I've set a reminder for it."),
        ("what todos do I have",
         "Todos: 1) buy milk (due tomorrow) 2) call plumber (overdue).",
         "You've got two open todos: buy milk (due tomorrow) and a overdue call to the plumber."),
        ("summarize the build result",
         "Build completed. 3 components created, 0 errors, dev server started on port 5173.",
         "Done! The build finished cleanly - 3 components created, no errors, and the dev server is live on port 5173."),
    ]
    return [
        dspy.Example(user_question=q, draft_answer=d, response=r).with_inputs(
            "user_question", "draft_answer"
        )
        for q, d, r in pairs
    ]


def _ir_trainset():
    pairs = [
        ("hi there", "TRIVIAL", "false"),
        ("thanks!", "TRIVIAL", "false"),
        ("why did I miss the exam", "WHY", "true"),
        ("when is my dentist appointment", "WHEN", "true"),
        ("tell me about my brother Arjun", "ENTITY", "true"),
        ("create a todo to buy milk", "TASK", "true"),
    ]
    return [
        dspy.Example(message=m, intent=i, is_complex=c).with_inputs("message")
        for m, i, c in pairs
    ]


def _exact_intent(example, pred, trace=None) -> float:
    return 1.0 if (pred.intent or "").strip().upper() == example.intent else 0.0


def _nonempty(example, pred, trace=None) -> float:
    return 1.0 if (pred.response or "").strip() else 0.0


def compile_interactive_tier() -> bool:
    reset_bridge()
    bridge = DspyBridge()
    if not bridge.is_enabled():
        logger.warning("DSPy bridge disabled; nothing to compile.")
        return False

    hs_prog = HumanSynthesizer()
    hs_compiled = dspy.BootstrapFewShot(metric=_nonempty, max_bootstrapped_demos=2).compile(
        hs_prog, trainset=_hs_trainset()
    )
    _save(hs_compiled, _HS_PATH)

    ir_prog = IntentRouter()
    ir_compiled = dspy.BootstrapFewShot(metric=_exact_intent, max_bootstrapped_demos=2).compile(
        ir_prog, trainset=_ir_trainset()
    )
    _save(ir_compiled, _IR_PATH)
    logger.info("Interactive-tier DSPy modules compiled and saved.")
    return True


def _save(program, path: str) -> None:
    try:
        program.save(path)
        if has_pii(open(path, encoding="utf-8").read()):
            os.remove(path)
            logger.error("PII detected in artifact %s; discarded.", path)
    except Exception as exc:
        logger.warning("failed to save artifact %s: %s", path, exc)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    ok = compile_interactive_tier()
    sys.exit(0 if ok else 1)
