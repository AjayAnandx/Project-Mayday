import json
import logging
import re
import httpx

from backend.core.config import load_config
from backend.assistant.function_registry import get_tool_definitions
from backend.assistant.providers.base import ProviderError
from backend.assistant.providers.router import (
    fallback_order,
    primary_for_role,
    resolve_spec,
    post_with_fallback,
    retry_same_default,
)

logger = logging.getLogger(__name__)

_TOOL_CALL_BLOCK_RE = re.compile(
    r'</?\|?tool_call[^>]*>(.*?)</?\|?tool_call\|?>',
    re.DOTALL,
)

_FUNC_CALL_RE = re.compile(
    r'call:(\w+)\(([^)]*)\)',
)

_ARG_RE = re.compile(
    r'(\w+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))',
)

# Fenced JSON tool calls some models emit instead of native tool_calls:
# ```json {"name": "create_todo", "arguments": {...}} ```
_FENCED_JSON_RE = re.compile(
    r'```(?:json)?\s*(\{.*?\})\s*```',
    re.DOTALL,
)

_VALID_TOOL_NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _parse_tool_call_text(text: str) -> tuple[str | None, list[dict] | None]:
    if not text or ("<tool" not in text and "```" not in text):
        return text, None

    blocks = _TOOL_CALL_BLOCK_RE.findall(text)
    parsed_tool_calls: list[dict] = []
    cleaned = text
    if blocks:
        cleaned = _TOOL_CALL_BLOCK_RE.sub("", cleaned).strip()
        for block in blocks:
            block = block.strip()

            try:
                tc = json.loads(block)
                name = tc.get("name", tc.get("function", ""))
                args = tc.get("arguments", tc.get("parameters", {}))
                if isinstance(args, str):
                    args = json.loads(args)
                parsed_tool_calls.append({
                    "id": f"call_{name}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                })
                continue
            except (json.JSONDecodeError, TypeError):
                pass

            m = _FUNC_CALL_RE.search(block)
            if m:
                name = m.group(1)
                args_str = m.group(2)
                args = {}
                for am in _ARG_RE.finditer(args_str):
                    val = am.group(2) or am.group(3) or am.group(4)
                    args[am.group(1)] = val
                parsed_tool_calls.append({
                    "id": f"call_{name}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                })
                continue

            try:
                tc = json.loads("{" + block + "}")
                name = tc.get("name", "")
                args = {k: v for k, v in tc.items() if k != "name"}
                if name:
                    parsed_tool_calls.append({
                        "id": f"call_{name}",
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    })
            except (json.JSONDecodeError, TypeError):
                pass

    if "```" in cleaned:
        # Fenced-JSON dialect: only counts when the object literally looks like
        # a tool call (valid identifier "name" + "arguments"/"parameters" dict).
        spans = []
        for m in _FENCED_JSON_RE.finditer(cleaned):
            try:
                tc = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(tc, dict):
                continue
            name = tc.get("name", "")
            args = tc.get("arguments", tc.get("parameters", None))
            if (isinstance(name, str) and _VALID_TOOL_NAME_RE.match(name)
                    and isinstance(args, dict)):
                parsed_tool_calls.append({
                    "id": f"call_{name}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                })
                spans.append(m.span())
        for start, end in reversed(spans):
            cleaned = (cleaned[:start] + cleaned[end:]).strip()

    return cleaned or None, parsed_tool_calls if parsed_tool_calls else None


class LLMClient:
    """Backward-compatible chat client, routed through the provider gateway.

    ``LLMClient()`` resolves the worker primary (``providers.default`` when
    the block exists, else legacy ``ollama:`` block) and automatically fails
    over through ``providers.fallback_order`` on 401/402/429/5xx, timeouts
    and connect errors. With the legacy config the local request bodies are
    byte-identical to the pre-gateway client.

    After each :meth:`chat`, ``last_provider`` names the spec that answered
    and ``last_fallbacks`` lists skipped providers (empty on a clean primary
    hit) — chat.py surfaces these as a fallback notice.
    """

    def __init__(self, model: str | None = None, endpoint: str | None = None,
                 api_key: str | None = None, provider: str | None = None,
                 role: str = "worker", http_client=None, retry_delay: float = 1.0,
                 retry_same: bool | None = None):
        cfg = load_config()
        if provider is None:
            if endpoint is not None:
                # Explicit endpoint pin (legacy callers) — keep local semantics.
                provider = "ollama_local"
            else:
                provider = primary_for_role(cfg, role)
        self.provider_name = provider
        self.role = role
        self.retry_delay = retry_delay
        self.retry_same = retry_same if retry_same is not None else retry_same_default(cfg)
        self._spec = resolve_spec(provider, cfg, model, endpoint, api_key)
        # Convenience mirrors of the resolved primary spec (legacy attributes).
        self.model = self._spec.model
        self.endpoint = self._spec.endpoint
        self.api_key = self._spec.api_key
        self.keep_alive = self._spec.keep_alive
        self.last_provider: str = provider
        self.last_fallbacks: list[str] = []
        if http_client is not None:
            self._http = http_client
        else:
            self._http = httpx.Client(timeout=httpx.Timeout(
                connect=15.0,
                read=self._spec.read_timeout,
                write=60.0,
                pool=15.0,
            ))

    def _build_headers(self) -> dict:
        return self._spec.build_headers()

    def _chain(self, provider: str | None = None):
        """Primary spec (already resolved) + configured fallbacks."""
        primary = provider or self.provider_name
        if primary == self.provider_name:
            chain = [self._spec]
        else:
            chain = [resolve_spec(primary)]
        cfg = load_config()
        for name in fallback_order(cfg):
            if name == primary:
                continue
            chain.append(resolve_spec(name, cfg))
        return primary, chain

    def chat(self, messages: list[dict], stream: bool = False, tools: list[dict] | None = None,
             tool_choice: str | None = None, max_tokens: int | None = None,
             temperature: float | None = None, provider: str | None = None):
        body_tools = tools if tools is not None else get_tool_definitions()
        primary, chain = self._chain(provider)
        resp, fallbacks = post_with_fallback(
            self._http, chain, messages, body_tools, tool_choice,
            max_tokens, temperature, stream, retry_delay=self.retry_delay,
            retry_same=self.retry_same,
        )
        self.last_fallbacks = list(fallbacks)
        self.last_provider = self._detect_provider(chain, primary, resp, fallbacks)
        self._log_response(resp, len(body_tools) if isinstance(body_tools, list) else -1)
        return resp

    def _detect_provider(self, chain, primary, resp, fallbacks) -> str:
        try:
            url = str(getattr(resp, "url", "") or "")
            return primary if not fallbacks else next(
                (s.name for s in chain if s.endpoint in url), chain[-1].name)
        except Exception:
            return primary if not fallbacks else chain[-1].name

    def _log_response(self, resp, tools_sent: int) -> None:
        """One log line per LLM call (finish/content/tool_calls)."""
        try:
            data = resp.json()
            choices = data.get("choices", []) if isinstance(data, dict) else []
            if not choices:
                err = (data.get("error") if isinstance(data, dict) else None) or {}
                logger.warning("LLM %s: tools_sent=%d EMPTY choices — top_keys=%s error=%s",
                               self.last_provider, tools_sent,
                               sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
                               str(err)[:500])
                return
            ch = choices[0]
            msg = ch.get("message", {}) or {}
            content = msg.get("content") or ""
            tcs = msg.get("tool_calls") or []
            logger.info("LLM %s model=%s: tools_sent=%d finish=%s content_chars=%d tool_calls=%d",
                        self.last_provider, getattr(self, "model", "?"), tools_sent,
                        ch.get("finish_reason"), len(content), len(tcs))
        except Exception as e:
            logger.debug("LLM response summary failed: %s", e)

    def fallback_notice(self) -> str:
        if not self.last_fallbacks:
            return ""
        detail = "; ".join(self.last_fallbacks)
        return (f"Primary LLM provider failed ({detail}); "
                f"answered with {self.last_provider}.")

    def extract_response(self, response) -> tuple[str | None, list[dict] | None]:
        try:
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return None, None
            msg = choices[0].get("message", {})
        except Exception:
            return None, None
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")

        if tool_calls:
            return content, tool_calls

        return _parse_tool_call_text(content)

    def extract_stream_chunk(self, line: bytes) -> tuple[str | None, list[dict] | None, bool]:
        # OpenRouter SSE keep-alive comments (": OPENROUTER PROCESSING") — skip.
        if line.startswith(b":"):
            return None, None, False
        if line.startswith(b"data: "):
            payload = line[6:].strip()
            if payload == b"[DONE]":
                return None, None, True
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return None, None, False
            # Mid-stream provider error (HTTP 200 with error event) — raise so
            # streaming callers can fail over to the next provider.
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                code = err.get("code") if isinstance(err, dict) else None
                msg = (err.get("message") if isinstance(err, dict) else str(err)) or "mid-stream error"
                raise ProviderError(self.provider_name, f"mid-stream error: {msg}",
                                    code if isinstance(code, int) else None, "mid_stream")
            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices:
                # Terminal usage chunk (content-free delta repeating
                # finish_reason) — nothing to forward.
                return None, None, False
            delta = choices[0].get("delta", {})
            content = delta.get("content")
            tool_calls = delta.get("tool_calls")

            if tool_calls:
                return content, tool_calls, False

            if content and ("<tool" in content or "```" in content):
                cleaned, parsed = _parse_tool_call_text(content)
                if parsed:
                    return cleaned, parsed, False
                return content, None, False

            return content, tool_calls, False
        return None, None, False

_INTERACTIVE_CLIENT: "LLMClient | None" = None
_WORKER_CLIENT: "LLMClient | None" = None


def reset_llm_clients() -> None:
    """Clear cached tier singletons (tests + config-reload paths)."""
    global _INTERACTIVE_CLIENT, _WORKER_CLIENT
    _INTERACTIVE_CLIENT = None
    _WORKER_CLIENT = None


def _client_for(role: str) -> "LLMClient":
    cfg = load_config()
    primary = primary_for_role(cfg, role)
    if primary == "ollama_local":
        # Legacy models.<role> overrides were written for local Ollama —
        # apply them only when the primary is still local.
        tier = (cfg.get("models", {}) or {}).get(role, {}) or {}
        return LLMClient(
            model=tier.get("model") or None,
            endpoint=tier.get("endpoint") or None,
            api_key=tier.get("api_key") or None,
            provider=primary,
            role=role,
        )
    return LLMClient(provider=primary, role=role)


def get_interactive_client() -> "LLMClient":
    """Local small model that talks to the user and humanizes worker answers."""
    global _INTERACTIVE_CLIENT
    if _INTERACTIVE_CLIENT is None:
        _INTERACTIVE_CLIENT = _client_for("interactive")
    return _INTERACTIVE_CLIENT


def get_worker_client() -> "LLMClient":
    """Capable model that performs the heavy tool/reasoning work."""
    global _WORKER_CLIENT
    if _WORKER_CLIENT is None:
        _WORKER_CLIENT = _client_for("worker")
    return _WORKER_CLIENT

