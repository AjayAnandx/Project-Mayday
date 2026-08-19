"""Regression tests for the DSPy bridge (R5 interactive tier).

These validate gating behaviour deterministically by patching the config, so
they hold whether or not DSPy is enabled in the live config.yaml. When disabled,
every DSPy helper is a safe no-op returning None so callers fall back to
deterministic prompts; when enabled, the bridge configures the LM.
"""
import backend.dspy.bridge as bridge_mod
from backend.dspy.bridge import DspyBridge, has_pii, dspy_available
from backend.dspy.modules import (
    humanize_dspy,
    classify_dspy,
    dspy_interactive_enabled,
)


def _patch(monkeypatch, enabled, interactive_tier=True, model="llama3.2:3b"):
    cfg = {
        "dspy": {
            "enabled": enabled,
            "interactive_tier": interactive_tier,
            "model": "",
            "endpoint": "",
        },
        "models": {
            "interactive": {
                "model": model,
                "endpoint": "http://localhost:11434/v1/chat/completions",
            }
        },
        "ollama": {
            "model": "gemma4:31b-cloud",
            "endpoint": "http://localhost:11434/v1/chat/completions",
        },
    }
    import backend.core.config as cc

    monkeypatch.setattr(cc, "load_config", lambda: cfg)
    monkeypatch.setattr(bridge_mod, "load_config", lambda: cfg)
    bridge_mod.reset_bridge()


def test_dspy_available():
    assert dspy_available() is True


def test_bridge_disabled_when_config_off(monkeypatch):
    _patch(monkeypatch, enabled=False)
    assert DspyBridge().is_enabled() is False


def test_interactive_enabled_false_when_disabled(monkeypatch):
    _patch(monkeypatch, enabled=False)
    assert dspy_interactive_enabled() is False


def test_helpers_noop_when_disabled(monkeypatch):
    _patch(monkeypatch, enabled=False)
    assert humanize_dspy("Some worker answer.", "any question") is None
    intent, complex_flag = classify_dspy("hi there")
    assert intent is None and complex_flag is None


def test_bridge_enabled_configures_lm(monkeypatch):
    _patch(monkeypatch, enabled=True)
    bridge = DspyBridge()
    assert bridge.is_enabled() is True
    assert dspy_interactive_enabled() is True


def test_pii_gate():
    assert has_pii("contact me at jane.doe@example.com please") is True
    assert has_pii("call +1 (415) 555-0132 tomorrow") is True
    assert has_pii("the dentist appointment is on august 20") is False
    assert has_pii("Dentist appointment 2026-08-20 15:00. Reminder set.") is False
    assert has_pii("") is False


def test_tiers_fallback_when_dspy_forced_off(monkeypatch):
    import backend.assistant.tiers as tiers

    monkeypatch.setattr(tiers, "_DSPY_OK", False)
    monkeypatch.setattr(tiers, "get_interactive_client", lambda: _FakeClient("TRIVIAL"))
    assert tiers.classify_intent("hi there") == "TRIVIAL"


class _FakeClient:
    def __init__(self, reply):
        self._reply = reply

    def chat(self, messages, stream=False, tools=None, max_tokens=None):
        return self._reply

    def extract_response(self, resp):
        return (resp, None)
