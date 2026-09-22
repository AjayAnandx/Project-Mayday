"""Provider resolution + fallback-chain policy for the LLM gateway.

Role routing (config ``providers:`` block, all optional — sane defaults apply):
- ``interactive`` role -> ``providers.interactive`` (default ``ollama_local``).
  Always local: fast, free, and the interactive tier never uses tools.
- ``worker`` role (default ``LLMClient()``) -> ``providers.default``
  (default ``openrouter`` per the gateway plan).

``providers.fallback_order`` (default ``[openrouter, ollama_cloud,
ollama_local]``) is tried in order after the primary. Missing credentials do
not hard-fail: the spec raises ``missing_key`` and the router moves on, so a
fresh checkout with no keys still runs on local Ollama.

Ollama Cloud allows 1 concurrent request — cloud calls are serialized with a
module-level semaphore shared by every LLMClient.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from backend.core.config import load_config
from .base import ProviderError, ProviderSpec
from . import ollama_cloud as _ollama_cloud
from . import ollama_local as _ollama_local
from . import openrouter as _openrouter

logger = logging.getLogger(__name__)

KNOWN_PROVIDERS = ("openrouter", "ollama_cloud", "ollama_local")
DEFAULT_FALLBACK_ORDER = ["openrouter", "ollama_cloud", "ollama_local"]

_LOADERS = {
    "ollama_local": _ollama_local.load_spec,
    "ollama_cloud": _ollama_cloud.load_spec,
    "openrouter": _openrouter.load_spec,
}

# Ollama Cloud plan limit: 1 concurrent request.
_ollama_cloud_sem = threading.Semaphore(1)


def _providers_cfg(cfg: dict) -> dict:
    return cfg.get("providers", {}) or {}


def primary_for_role(cfg: dict, role: str) -> str:
    pcfg = _providers_cfg(cfg)
    if not pcfg:
        # Legacy config (no providers: block): preserve the old single-provider
        # behavior — everything resolves from the `ollama:` block.
        return "ollama_local"
    if role == "interactive":
        return pcfg.get("interactive", "ollama_local")
    return pcfg.get("default", "openrouter")


def fallback_order(cfg: dict) -> list[str]:
    pcfg = _providers_cfg(cfg)
    order = pcfg.get("fallback_order", list(DEFAULT_FALLBACK_ORDER)) or []
    seen, out = set(), []
    for name in order:
        if name in _LOADERS and name not in seen:
            seen.add(name)
            out.append(name)
    for name in DEFAULT_FALLBACK_ORDER:  # always keep local as last resort
        if name not in seen and name in _LOADERS:
            out.append(name)
    return out


def retry_same_default(cfg: dict) -> bool:
    """Whether a transient failure is retried on the SAME provider before
    failing over. Default False (parity/loud: single attempt, then next
    link — extra retries burn free-tier quota)."""
    try:
        return bool(_providers_cfg(cfg).get("retry_same", False))
    except Exception:
        return False


def free_max_iterations(cfg: dict, default: int = 20) -> int:
    """Per-turn iteration budget when the primary model is a `:free` variant.

    Default 20 = parity with the local loop budget. Lower it (e.g. 8) to
    bound free-tier quota burn (~22 calls/turn worst case otherwise).
    """
    try:
        return int(_providers_cfg(cfg).get("free_max_iterations", default))
    except Exception:
        return default


def resolve_spec(provider: str, cfg: dict | None = None, model_override=None,
                 endpoint_override=None, api_key_override=None) -> ProviderSpec:
    cfg = cfg if cfg is not None else load_config()
    loader = _LOADERS.get(provider)
    if loader is None:
        raise ValueError(f"Unknown LLM provider {provider!r} (known: {KNOWN_PROVIDERS})")
    return loader(cfg, model_override, endpoint_override, api_key_override)


def resolve_chain(primary: str, cfg: dict | None = None, model_override=None,
                  endpoint_override=None, api_key_override=None) -> list[ProviderSpec]:
    """Primary spec first, then fallback_order (deduped). Per-spec overrides
    only apply to the primary; fallbacks use their own configured model."""
    cfg = cfg if cfg is not None else load_config()
    chain = [resolve_spec(primary, cfg, model_override, endpoint_override, api_key_override)]
    for name in fallback_order(cfg):
        if name == primary:
            continue
        chain.append(resolve_spec(name, cfg))
    return chain


def _empty_choices_error(provider: str, resp):
    """Free-tier providers occasionally answer HTTP 200 with zero choices
    (overload blip, filtered output). Never valid OpenAI — treat as failure
    so the chain retries once, then fails over, instead of dying silently."""
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("choices"):
        return None
    err = data.get("error") or {}
    msg = err.get("message") if isinstance(err, dict) else str(err)
    return ProviderError(provider,
                         f"empty choices response{': ' + str(msg)[:200] if msg else ''}",
                         None, "mid_stream")


def _retry_after_seconds(response) -> float:
    try:
        val = response.headers.get("Retry-After")
        if val is not None:
            return max(0.0, min(float(val), 10.0))
    except Exception:
        pass
    return 1.0


def classify_http_error(provider: str, exc: httpx.HTTPStatusError):
    """Map an HTTP error to (ProviderError, retryable_now)."""
    status = exc.response.status_code
    try:
        data = exc.response.json()
        msg = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
    except Exception:
        msg = None
    if status == 402:
        return ProviderError(provider,
                             msg or "Provider credits exhausted (402) — failing over",
                             status, "insufficient_credits"), False
    if status == 401:
        return ProviderError(provider,
                             msg or "Unauthorized (401) — check API key, failing over",
                             status, "unauthorized"), False
    if status in (429, 502, 503, 504):
        return ProviderError(provider,
                             msg or f"Provider returned HTTP {status} — retry/failover",
                             status, "transient"), True
    return ProviderError(provider, msg or f"Provider returned HTTP {status}",
                         status, "http_error"), False


def post_with_fallback(http: httpx.Client, chain: list[ProviderSpec], messages,
                       tools=None, tool_choice=None, max_tokens=None,
                       temperature=None, stream: bool = False,
                       retry_delay: float = 1.0, retry_same: bool = False):
    """POST through the chain. Returns (response, fallbacks).

    - Missing-key specs are skipped without a network call.
    - 402/401 skip immediately; 429/5xx/empty-choices fail over to the next
      provider (single attempt each by default; retry_same=True restores one
      same-provider retry honoring Retry-After).
    - 400/404/422 raise immediately (request bug, not an outage).
    - Timeouts/connect errors fail over to the next provider.
    - ollama_cloud calls are serialized (1-concurrent plan limit).
    """
    fallbacks: list[str] = []
    last_error: Exception | None = None

    for spec in chain:
        try:
            spec.check_ready()
        except ProviderError as e:
            logger.warning("%s not ready: %s", spec.name, e)
            fallbacks.append(f"{spec.name}: skipped ({e})")
            last_error = e
            continue

        body = spec.build_body(messages, tools if tools is not None else [],
                               tool_choice, max_tokens, temperature, stream)
        headers = spec.build_headers()

        def _do_post():
            if stream:
                return http.stream("POST", spec.endpoint, json=body, headers=headers)
            return http.post(spec.endpoint, json=body, headers=headers)

        attempts = 0
        while True:
            attempts += 1
            try:
                if spec.name == "ollama_cloud":
                    with _ollama_cloud_sem:
                        resp = _do_post()
                else:
                    resp = _do_post()
                if not stream:
                    resp.raise_for_status()
                    empty_err = _empty_choices_error(spec.name, resp)
                    if empty_err is not None:
                        last_error = empty_err
                        if retry_same and attempts == 1:
                            logger.warning("%s — retrying once", empty_err)
                            continue
                        fallbacks.append(f"{spec.name}: ({empty_err.error_type}) — {empty_err}")
                        break
                return resp, fallbacks
            except httpx.HTTPStatusError as e:
                perr, retryable = classify_http_error(spec.name, e)
                last_error = perr
                if perr.status_code in (400, 404, 422):
                    raise perr from e
                if retryable and retry_same and attempts == 1:
                    delay = _retry_after_seconds(e.response)
                    wait = min(delay, retry_delay) if retry_delay else delay
                    logger.warning("%s transient HTTP %s — retrying in %.1fs",
                                   spec.name, perr.status_code, wait)
                    if wait:
                        time.sleep(wait)
                    continue
                logger.warning("%s failed (%s) — failing over", spec.name, perr)
                detail = str(perr)
                if len(detail) > 180:
                    detail = detail[:180] + "…"
                fallbacks.append(f"{spec.name}: HTTP {perr.status_code} ({perr.error_type}) — {detail}")
                break
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                kind = "timeout" if isinstance(e, httpx.TimeoutException) else "connect"
                last_error = ProviderError(spec.name, f"{spec.name} {kind}: {e}",
                                           None, kind)
                logger.warning("%s %s — failing over", spec.name, kind)
                edetail = str(e)
                if len(edetail) > 120:
                    edetail = edetail[:120] + "…"
                fallbacks.append(f"{spec.name}: {kind} — {edetail}" if edetail else f"{spec.name}: {kind}")
                break

    assert last_error is not None
    raise last_error
