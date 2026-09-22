"""ollama_local provider: http://localhost:11434/v1/chat/completions.

No auth (api_key ignored). Bodies are byte-identical to the pre-gateway
client: keep_alive always sent, tool_choice passed through untouched.
"""
from __future__ import annotations

from .base import ProviderSpec

DEFAULT_ENDPOINT = "http://localhost:11434/v1/chat/completions"


def load_spec(cfg: dict, model_override=None, endpoint_override=None,
              api_key_override=None) -> ProviderSpec:
    ollama = cfg.get("ollama", {}) or {}
    return ProviderSpec(
        name="ollama_local",
        endpoint=endpoint_override or ollama.get("endpoint", DEFAULT_ENDPOINT),
        model=model_override or ollama.get("model", "gemma4:31b-cloud"),
        api_key="",  # local server ignores auth; never send a cloud key here
        keep_alive=ollama.get("keep_alive", -1),
        supports_tool_choice=True,  # wire parity: pre-gateway client sent it
        supports_keep_alive=True,
        requires_api_key=False,
        read_timeout=float(ollama.get("timeout", 600)),
    )
