"""openrouter provider: https://openrouter.ai/api/v1/chat/completions.

Bearer OPENROUTER_API_KEY + optional HTTP-Referer / X-OpenRouter-Title.
OpenAI-compatible tool calling (tools must be resent every turn — the engine
already does this), tool_choice + parallel_tool_calls supported.

Quirks handled here / in llm_client.extract_stream_chunk:
- SSE keep-alive comments (": OPENROUTER PROCESSING") — must be skipped.
- Terminal usage chunk repeats finish_reason with a content-free delta.
- Mid-stream errors arrive as SSE error events under HTTP 200.
- Free-variant limits: 20 RPM, 50 RPD (<10 credits) / 1000 RPD (>=10 credits);
  402 = out of credits (fail over immediately, no retry).
- provider.require_parameters=true keeps routing on tool-capable endpoints.
"""
from __future__ import annotations

from .base import ProviderSpec

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def load_spec(cfg: dict, model_override=None, endpoint_override=None,
              api_key_override=None) -> ProviderSpec:
    ollama = cfg.get("ollama", {}) or {}
    orq = cfg.get("openrouter", {}) or {}
    if api_key_override is not None:
        api_key = api_key_override
    else:
        api_key = orq.get("api_key", "")
    routing = dict(orq.get("provider", {}) or {})
    # No forced routing object (parity): only what config.yaml sets is sent.
    return ProviderSpec(
        name="openrouter",
        endpoint=endpoint_override or orq.get("endpoint", DEFAULT_ENDPOINT),
        model=model_override or orq.get("model", DEFAULT_MODEL),
        api_key=api_key,
        keep_alive=None,
        supports_tool_choice=True,
        supports_keep_alive=False,
        requires_api_key=True,
        referer=orq.get("referer", ""),
        title=orq.get("title", "Mayday"),
        provider_routing=routing,
        read_timeout=float(orq.get("timeout", ollama.get("timeout", 600))),
    )
