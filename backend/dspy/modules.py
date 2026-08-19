"""DSPy modules for Mayday's interactive (local 0.5b) tier.

Two compiled behaviours replace the hand-written few-shot prompts in
``backend/assistant/tiers.py``:

  * ``HumanSynthesizer``  — rewrite the worker model's factual answer into a
    natural, on-persona first-person reply (the interactive tier's core job).
  * ``IntentRouter``      — classify a user message into a routing intent and
    a complexity flag (drives the interactive/worker split).

If the DSPy bridge is disabled or a call fails, the helper functions return
``None`` so the caller falls back to the deterministic prompt path.
"""
import logging
import os

from backend.dspy.bridge import DspyBridge, has_pii

logger = logging.getLogger("dspy.modules")

try:
    import dspy
    _DSPY_OK = True
except Exception:  # pragma: no cover
    dspy = None
    _DSPY_OK = False

_ART_DIR = os.path.join(os.path.dirname(__file__), "artifacts", "interactive_tier")
os.makedirs(_ART_DIR, exist_ok=True)


if _DSPY_OK:
    class HumanSynthesizerSig(dspy.Signature):  # type: ignore[misc]
        """Rewrite a draft assistant answer into a natural, friendly first-person
        reply for the user. Keep every fact. Do not invent new claims. Do NOT
        reply with a question; state the answer directly in first person."""
        user_question = dspy.InputField(desc="What the user asked (may be empty)")
        draft_answer = dspy.InputField(desc="The worker model's raw factual answer")
        response = dspy.OutputField(desc="Natural, concise first-person reply, 1-4 sentences")

    class IntentRouterSig(dspy.Signature):  # type: ignore[misc]
        """Classify a user message to route it in a two-tier assistant."""
        message = dspy.InputField(desc="The user's message")
        intent = dspy.OutputField(desc="One of TRIVIAL, WHY, WHEN, ENTITY, TASK")
        is_complex = dspy.OutputField(desc="true if the request needs heavy tools/reasoning, else false")

    class HumanSynthesizer(dspy.Module):  # type: ignore[misc]
        def __init__(self):
            super().__init__()
            self.generate = dspy.Predict(HumanSynthesizerSig)

        def forward(self, user_question, draft_answer):
            return self.generate(user_question=user_question, draft_answer=draft_answer)

    class IntentRouter(dspy.Module):  # type: ignore[misc]
        def __init__(self):
            super().__init__()
            self.route = dspy.Predict(IntentRouterSig)

        def forward(self, message):
            return self.route(message=message)


_HS_PATH = os.path.join(_ART_DIR, "human_synth.json")
_IR_PATH = os.path.join(_ART_DIR, "intent_router.json")

_hs = None
_ir = None


def dspy_interactive_enabled() -> bool:
    if not _DSPY_OK:
        return False
    cfg = __import__("backend.core.config", fromlist=["load_config"]).load_config()
    if not cfg.get("dspy", {}).get("interactive_tier", False):
        return False
    return DspyBridge().is_enabled()


def _load_modules():
    global _hs, _ir
    if _hs is not None or _ir is not None:
        return
    _hs = HumanSynthesizer()
    if os.path.exists(_HS_PATH):
        try:
            if not has_pii(open(_HS_PATH, encoding="utf-8").read()):
                _hs.load(_HS_PATH)
        except Exception as exc:
            logger.warning("failed to load HumanSynthesizer artifact: %s", exc)
    _ir = IntentRouter()
    if os.path.exists(_IR_PATH):
        try:
            if not has_pii(open(_IR_PATH, encoding="utf-8").read()):
                _ir.load(_IR_PATH)
        except Exception as exc:
            logger.warning("failed to load IntentRouter artifact: %s", exc)


def humanize_dspy(answer: str, question: str = "") -> str | None:
    if not dspy_interactive_enabled() or not answer:
        return None
    try:
        _load_modules()
        pred = _hs(user_question=question or "", draft_answer=answer)
        out = (pred.response or "").strip()
        return out or None
    except Exception as exc:
        logger.warning("humanize_dspy failed, falling back: %s", exc)
        return None


_INTENTS = ("TRIVIAL", "WHY", "WHEN", "ENTITY", "TASK")
import re as _re


def classify_dspy(question: str):
    if not dspy_interactive_enabled() or not question:
        return None, None
    try:
        _load_modules()
        pred = _ir(message=question)
        # 0.5b sometimes prefixes reasoning (e.g. "=> TRIVIAL"); extract the
        # first known intent token rather than trusting the raw string.
        intent = None
        m = _re.search(r"\b(" + "|".join(_INTENTS) + r")\b", (pred.intent or "").upper())
        if m:
            intent = m.group(1)
        complex_flag = "true" in (pred.is_complex or "").lower()
        return intent, complex_flag
    except Exception as exc:
        logger.warning("classify_dspy failed, falling back: %s", exc)
        return None, None
