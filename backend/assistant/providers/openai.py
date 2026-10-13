"""openai provider: https://api.openai.com/v1/chat/completions.

Bearer OPENAI_API_KEY. Stock OpenAI-compatible incl. native function calling
(tools must be resent every turn — the engine already does this),
tool_choice supported. No keep_alive, no extra headers, no provider routing
object, no concurrency limit (unlike ollama_cloud).
"""
from __future__ import annotations

from .base import ProviderSpec

DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


def load_spec(cfg: dict, model_override=None, endpoint_override=None,
              api_key_override=None) -> ProviderSpec:
    ollama = cfg.get("ollama", {}) or {}
    oai = cfg.get("openai", {}) or {}
    if api_key_override is not None:
        api_key = api_key_override
    else:
        api_key = oai.get("api_key", "")
    return ProviderSpec(
        name="openai",
        endpoint=endpoint_override or oai.get("endpoint", DEFAULT_ENDPOINT),
        model=model_override or oai.get("model", DEFAULT_MODEL),
        api_key=api_key,
        keep_alive=None,
        supports_tool_choice=True,
        supports_keep_alive=False,
        requires_api_key=True,
        read_timeout=float(oai.get("timeout", ollama.get("timeout", 600))),
    )
