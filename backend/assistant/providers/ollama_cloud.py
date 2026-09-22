"""ollama_cloud provider: https://api.ollama.com/v1/chat/completions.

Bearer OLLAMA_API_KEY. OpenAI-compatible incl. tools + tool_choice.
No keep_alive (cloud-side). Plan limit: 1 concurrent request — the router
serializes cloud calls with a semaphore.
"""
from __future__ import annotations

from .base import ProviderSpec

DEFAULT_ENDPOINT = "https://api.ollama.com/v1/chat/completions"


def load_spec(cfg: dict, model_override=None, endpoint_override=None,
              api_key_override=None) -> ProviderSpec:
    ollama = cfg.get("ollama", {}) or {}
    cloud = cfg.get("ollama_cloud", {}) or {}
    if api_key_override is not None:
        api_key = api_key_override
    else:
        api_key = cloud.get("api_key", "") or ollama.get("api_key", "")
    return ProviderSpec(
        name="ollama_cloud",
        endpoint=endpoint_override or cloud.get("endpoint", DEFAULT_ENDPOINT),
        model=model_override or cloud.get("model")
        or ollama.get("model", "gemma4:31b-cloud"),
        api_key=api_key,
        keep_alive=None,
        supports_tool_choice=True,
        supports_keep_alive=False,
        requires_api_key=True,
        read_timeout=float(cloud.get("timeout", ollama.get("timeout", 600))),
    )
