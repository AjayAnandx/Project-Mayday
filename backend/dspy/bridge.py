"""DSPy bridge for Mayday.

Single, self-killing entry point shared by every DSPy consumer (the research
pipeline in backend/dspy/* and the interactive-tier modules in tiers.py).

If dspy is not installed, or the ``dspy`` master switch is off, or
configuration is incomplete, the bridge reports ``is_enabled() == False`` and
every DSPy call silently falls back to the deterministic path.

Two LM profiles are supported via one configured global LM (whichever tier is
active wins, since they are never both enabled by default):
  * interactive_tier  -> local qwen2.5:0.5b (models.interactive)
  * research modules  -> ollama.model / dspy.model (capable model)
"""
import logging
import os
import pathlib
import re

from backend.core.config import load_config

logger = logging.getLogger("dspy.bridge")

_DSPY_AVAILABLE = False
try:
    import dspy  # noqa: F401
    _DSPY_AVAILABLE = True
except Exception as exc:  # pragma: no cover - environment dependent
    logger.warning("dspy not available: %s", exc)

# Basic PII gate (used before any artifact is saved or served).
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")


def has_pii(text: str) -> bool:
    if not text:
        return False
    if _EMAIL_RE.search(text):
        return True
    # The phone regex also matches ISO dates (e.g. 2026-08-20); require a
    # structural phone signal so dates are not false-flagged.
    for m in _PHONE_RE.finditer(text):
        s = m.group(0)
        digits = sum(1 for ch in s if ch.isdigit())
        if digits < 10:
            continue
        if "+" in s or "(" in s:
            return True
        if re.search(r"\d{3}[-\s]\d{3}[-\s]\d{4}", s):
            return True
        if any(len(g) >= 7 for g in re.findall(r"\d+", s)):
            return True
    return False


def dspy_available() -> bool:
    return _DSPY_AVAILABLE


_BASE = pathlib.Path(__file__).resolve().parent


class DspyBridge:
    """Singleton configuring a DSPy LM and exposing module flags."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.enabled = False
        self.lm = None
        self.artifacts_dir = _BASE / "dspy_artifacts"
        self._cfg = load_config().get("dspy", {})
        try:
            os.makedirs(self.artifacts_dir, exist_ok=True)
        except Exception:
            pass
        if not _DSPY_AVAILABLE:
            return
        try:
            if not self._cfg.get("enabled", False):
                return
            interactive = bool(self._cfg.get("interactive_tier", False))
            models = load_config().get("models", {})
            ollama = load_config().get("ollama", {})
            if interactive:
                model = self._cfg.get("model") or models.get("interactive", {}).get("model")
                endpoint = self._cfg.get("endpoint") or models.get("interactive", {}).get("endpoint")
            else:
                model = self._cfg.get("model") or ollama.get("model")
                endpoint = self._cfg.get("endpoint") or ollama.get("endpoint")
            api_key = self._cfg.get("api_key", "") or ""
            if not model or not endpoint:
                logger.warning("dspy enabled but model/endpoint missing; disabling")
                return
            api_base = endpoint
            if api_base.endswith("/v1/chat/completions"):
                api_base = api_base[: -len("/v1/chat/completions")] + "/v1"
            elif not api_base.endswith("/v1"):
                api_base = api_base.rstrip("/") + "/v1"
            self.lm = dspy.LM(  # type: ignore[attr-defined]
                model=f"openai/{model}",
                api_base=api_base,
                api_key=api_key or "ollama",
                temperature=0.3,
                max_tokens=1024,
            )
            dspy.settings.configure(lm=self.lm)  # type: ignore[attr-defined]
            self.enabled = True
            logger.info("DSPy bridge enabled on %s", model)
        except Exception as exc:  # pragma: no cover - runtime dependent
            logger.warning("DSPy bridge init failed: %s", exc)
            self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled

    def module_enabled(self, name: str) -> bool:
        if not self.enabled:
            return False
        return bool(self._cfg.get(name, False))

    def call_with_fallback(self, fn):
        """Run ``fn`` (which performs a DSPy call) with a safe fallback to None."""
        try:
            return fn()
        except Exception as exc:
            logger.warning("dspy call failed, using fallback: %s", exc)
            return None

    def reconfigure(self) -> bool:
        """Re-read config and (re)configure the LM. Returns enabled state."""
        DspyBridge._instance = None
        return DspyBridge().is_enabled()


def get_bridge() -> "DspyBridge":
    return DspyBridge()


def configure_dspy() -> bool:
    """Module-level helper used by the eval/compile CLIs. Returns enabled state."""
    return get_bridge().reconfigure()


def reset_bridge() -> None:
    """Test helper: force re-init on next access."""
    DspyBridge._instance = None
