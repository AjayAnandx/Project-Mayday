"""Regression tests for the unified LLM gateway (Ollama Local/Cloud + OpenRouter).

All HTTP is mocked via httpx.MockTransport — no network, no API keys needed.
"""
import json

import httpx
import pytest

import backend.assistant.llm_client as llmmod
import backend.assistant.providers.router as routermod
from backend.assistant.llm_client import (
    LLMClient,
    _client_for,
    reset_llm_clients,
)
from backend.assistant.providers.base import ProviderError
from backend.assistant.providers.router import (
    fallback_order,
    free_max_iterations,
    primary_for_role,
    resolve_chain,
)


def _cfg():
    return {
        "ollama": {
            "model": "gemma4:31b-cloud",
            "endpoint": "http://localhost:11434/v1/chat/completions",
            "timeout": 600,
            "keep_alive": -1,
        },
        "models": {
            "interactive": {
                "model": "llama3.2:3b",
                "endpoint": "http://localhost:11434/v1/chat/completions",
                "api_key": "",
            },
            "worker": {
                "model": "gemma4:31b-cloud",
                "endpoint": "http://localhost:11434/v1/chat/completions",
                "api_key": "",
            },
        },
        "providers": {
            "default": "openrouter",
            "interactive": "ollama_local",
            "fallback_order": ["openrouter", "ollama_cloud", "ollama_local"],
            "max_tools": 64,
            "free_max_iterations": 8,
        },
        "ollama_cloud": {
            "endpoint": "https://api.ollama.com/v1/chat/completions",
            "model": "gemma4:31b-cloud",
            "api_key": "oc-test",
        },
        "openrouter": {
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "api_key": "or-test",
            "title": "Mayday",
            "referer": "",
            "provider": {"require_parameters": True, "allow_fallbacks": True},
        },
    }


@pytest.fixture
def cfg(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(llmmod, "load_config", lambda: cfg)
    monkeypatch.setattr(routermod, "load_config", lambda: cfg)
    reset_llm_clients()
    yield cfg
    reset_llm_clients()


def _tdef(name):
    return {"type": "function", "function": {"name": name}}


def _ok(content="hi"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _recorder(handler):
    calls = []

    def wrapped(request: httpx.Request):
        try:
            body = json.loads(request.content.decode())
        except Exception:
            body = {}
        calls.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        return handler(request, body, len(calls))

    return calls, wrapped


def _client(provider, cfg, handler, **kw):
    calls, wrapped = _recorder(handler)
    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    kw.setdefault("retry_delay", 0)
    client = LLMClient(provider=provider, http_client=http, **kw)
    return client, calls


# ---- wire parity: legacy local bodies must be byte-identical ----

def test_legacy_local_body_parity():
    """Pre-gateway body shape for ollama_local, from the original client:
    model/messages/tools/stream always; tool_choice iff truthy; max_tokens
    iff set; keep_alive iff set."""
    from backend.assistant.providers.router import resolve_spec
    legacy_cfg = {"ollama": _cfg()["ollama"]}
    spec = resolve_spec("ollama_local", legacy_cfg)
    tools = [_tdef("list_todos")]
    body = spec.build_body([{"role": "user", "content": "hi"}], tools, "auto",
                           None, None, False)
    assert body == {
        "model": "gemma4:31b-cloud",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": tools,
        "stream": False,
        "tool_choice": "auto",
        "keep_alive": -1,
    }
    # Legacy also always sent the tools key (even []) + keep_alive.
    body2 = spec.build_body([{"role": "user", "content": "hi"}], [], None,
                            None, None, False)
    assert body2["tools"] == [] and "tool_choice" not in body2
    assert body2["keep_alive"] == -1
    assert spec.build_headers() == {"Content-Type": "application/json"}


# ---- provider request shapes ----

def test_openrouter_headers_and_body(cfg):
    client, calls = _client("openrouter", cfg, lambda req, body, n: _ok())
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[_tdef("list_todos")],
                       tool_choice="auto", max_tokens=10, temperature=0.2)
    content, tc = client.extract_response(resp)
    assert content == "hi" and tc is None
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["authorization"] == "Bearer or-test"
    assert call["headers"]["x-openrouter-title"] == "Mayday"
    body = call["body"]
    assert body["model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert body["tool_choice"] == "auto"
    assert body["max_tokens"] == 10
    assert body["temperature"] == 0.2
    assert body["provider"]["require_parameters"] is True
    assert "keep_alive" not in body
    assert client.last_provider == "openrouter"
    assert client.last_fallbacks == []


def test_openrouter_no_routing_object_by_default(cfg):
    # Parity: no provider object unless config sets one.
    from backend.assistant.providers.router import resolve_spec
    bare = {"openrouter": {"api_key": "x"}}
    spec = resolve_spec("openrouter", bare)
    body = spec.build_body([{"role": "user", "content": "hi"}], [_tdef("x")], "auto")
    assert "provider" not in body
    assert body["tools"] != [] and body["tool_choice"] == "auto"


def test_ollama_cloud_bearer_no_keepalive(cfg):
    client, calls = _client("ollama_cloud", cfg, lambda req, body, n: _ok())
    client.chat([{"role": "user", "content": "hi"}], tools=[_tdef("get_weather")], tool_choice="auto")
    call = calls[0]
    assert call["headers"]["authorization"] == "Bearer oc-test"
    assert "keep_alive" not in call["body"]
    assert call["body"]["tool_choice"] == "auto"


def test_ollama_local_legacy_shape(cfg):
    client, calls = _client("ollama_local", cfg, lambda req, body, n: _ok())
    client.chat([{"role": "user", "content": "hi"}], tools=[_tdef("x")], tool_choice="auto")
    call = calls[0]
    assert "authorization" not in call["headers"]
    assert call["body"]["keep_alive"] == -1
    assert call["body"]["tool_choice"] == "auto"  # passed through, as before


# ---- empty-tools normalization (cloud only) ----

def test_chat_sends_legacy_keys_when_empty_cloud(cfg):
    # Parity: clouds send the legacy shape too (tools key always present).
    client, calls = _client("openrouter", cfg, lambda req, body, n: _ok())
    client.chat([{"role": "user", "content": "hi"}], tools=[], tool_choice="auto")
    assert calls[0]["body"]["tools"] == []
    assert calls[0]["body"]["tool_choice"] == "auto"


# ---- fallback policy ----

def test_429_retries_same_provider_then_succeeds(cfg):
    def handler(req, body, n):
        if n == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}}, headers={"Retry-After": "0"})
        return _ok("recovered")

    client, calls = _client("openrouter", cfg, handler, retry_same=True)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "recovered"
    assert len(calls) == 2  # opt-in retry on same provider, no failover
    assert client.last_fallbacks == []


def test_429_default_single_attempt_then_failover(cfg):
    def handler(req, body, n):
        if "openrouter.ai" in str(req.url):
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return _ok("via-cloud")

    client, calls = _client("openrouter", cfg, handler)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "via-cloud"
    assert len([c for c in calls if "openrouter.ai" in c["url"]]) == 1  # no same-provider retry
    assert client.last_provider == "ollama_cloud"


def test_402_fails_over_without_retry(cfg):
    def handler(req, body, n):
        if "openrouter.ai" in str(req.url):
            return httpx.Response(402, json={"error": {"message": "no credits"}})
        return _ok("via-cloud")

    client, calls = _client("openrouter", cfg, handler)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "via-cloud"
    assert len([c for c in calls if "openrouter.ai" in c["url"]]) == 1  # no retry on 402
    assert client.last_provider == "ollama_cloud"
    assert any("openrouter" in f and "402" in f for f in client.last_fallbacks)
    assert "402" in client.fallback_notice()


def test_missing_keys_skipped_without_network(cfg):
    cfg["openrouter"]["api_key"] = ""
    cfg["ollama_cloud"]["api_key"] = ""
    client, calls = _client("openrouter", cfg, lambda req, body, n: _ok("local"))
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "local"
    assert len(calls) == 1
    assert "localhost" in calls[0]["url"]
    assert client.last_provider == "ollama_local"
    assert len(client.last_fallbacks) == 2  # both cloud specs skipped


def test_all_providers_fail_raises(cfg):
    client, _ = _client("openrouter", cfg,
                        lambda req, body, n: httpx.Response(500, json={"error": {"message": "down"}}))
    with pytest.raises(ProviderError):
        client.chat([{"role": "user", "content": "hi"}], tools=[])


def test_400_raises_immediately_no_failover(cfg):
    def handler(req, body, n):
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    client, calls = _client("openrouter", cfg, handler)
    with pytest.raises(ProviderError):
        client.chat([{"role": "user", "content": "hi"}], tools=[])
    assert len(calls) == 1  # request bug — other providers not tried


# ---- streaming parser (OpenRouter SSE quirks) ----

def test_extract_stream_chunk_skips_comments_and_usage_chunk(cfg):
    client, _ = _client("openrouter", cfg, lambda req, body, n: _ok())
    assert client.extract_stream_chunk(b": OPENROUTER PROCESSING") == (None, None, False)
    usage = b'data: {"id":"gen-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":5}}'
    assert client.extract_stream_chunk(usage) == (None, None, False)
    assert client.extract_stream_chunk(b"data: [DONE]") == (None, None, True)
    text = b'data: {"choices":[{"delta":{"content":"hello"}}]}'
    assert client.extract_stream_chunk(text) == ("hello", None, False)


def test_extract_stream_chunk_mid_stream_error_raises(cfg):
    client, _ = _client("openrouter", cfg, lambda req, body, n: _ok())
    err = (b'data: {"error":{"code":429,"message":"Rate limit exceeded"},'
           b'"choices":[{"index":0,"delta":{},"finish_reason":"error"}]}')
    with pytest.raises(ProviderError):
        client.extract_stream_chunk(err)


# ---- role routing + legacy compat ----

def test_client_for_roles(cfg):
    inter = _client_for("interactive")
    assert inter.provider_name == "ollama_local"
    assert inter.model == "llama3.2:3b"
    worker = _client_for("worker")
    assert worker.provider_name == "openrouter"
    # legacy models.worker endpoint (localhost) must NOT override OpenRouter
    assert worker.endpoint == "https://openrouter.ai/api/v1/chat/completions"
    assert worker.model == "nvidia/nemotron-3-super-120b-a12b:free"


def test_legacy_config_preserves_single_provider(monkeypatch):
    legacy = {"ollama": _cfg()["ollama"]}
    monkeypatch.setattr(llmmod, "load_config", lambda: legacy)
    monkeypatch.setattr(routermod, "load_config", lambda: legacy)
    reset_llm_clients()
    try:
        assert primary_for_role(legacy, "worker") == "ollama_local"
        c = LLMClient()
        assert c.provider_name == "ollama_local"
        assert c.endpoint == "http://localhost:11434/v1/chat/completions"
        assert fallback_order(legacy)[-1] == "ollama_local"
        chain = resolve_chain("ollama_local", legacy)
        assert [s.name for s in chain] == ["ollama_local", "openrouter", "ollama_cloud"]
    finally:
        reset_llm_clients()


def test_explicit_endpoint_pins_local_semantics(cfg):
    c = LLMClient(endpoint="http://myhost:11434/v1/chat/completions")
    assert c.provider_name == "ollama_local"
    assert c.endpoint == "http://myhost:11434/v1/chat/completions"


# ---- tool cap ----

def test_apply_tool_cap_prefers_intent_tools():
    from backend.core.tool_selector import apply_tool_cap
    tools = [_tdef(n) for n in ["a_core", "b_want", "c_core", "d_want", "e_core"]]
    capped = apply_tool_cap(tools, {"b_want", "d_want"}, 3)
    assert [t["function"]["name"] for t in capped] == ["b_want", "d_want", "a_core"]


def test_apply_tool_cap_noop_under_limit():
    from backend.core.tool_selector import apply_tool_cap
    tools = [_tdef("a")]
    assert apply_tool_cap(tools, set(), 64) is tools


def test_max_tools_and_free_budget_defaults():
    from backend.core.tool_selector import max_tools_limit
    assert max_tools_limit({}) == 64
    assert max_tools_limit({"providers": {"max_tools": 32}}) == 32
    assert max_tools_limit({"providers": {"max_tools": "bad"}}) == 64
    assert free_max_iterations({}) == 20  # parity default (opt-in lower)
    assert free_max_iterations({"providers": {"free_max_iterations": 5}}) == 5
    from backend.assistant.providers.router import retry_same_default
    assert retry_same_default({}) is False
    assert retry_same_default({"providers": {"retry_same": True}}) is True


def test_build_index_regression():
    """The WS-connect crash path: ToolSelector must tokenize + index."""
    from backend.core.tool_selector import ToolSelector
    from backend.assistant.function_registry import get_tool_definitions
    s = ToolSelector()
    assert s._tokenize("show the git log") == ["show", "git", "log"]
    tools = get_tool_definitions()
    s.build_index(tools, {"core": {t["function"]["name"] for t in tools}})
    assert len(s._index) > 100


def test_validate_tool_definitions_drops_malformed():
    from backend.assistant.function_registry import get_tool_definitions
    tools = get_tool_definitions(mcp_tools=[
        {"type": "function", "function": {"name": "good_mcp",
                                          "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {}},          # no name
        {"type": "chat", "function": {"name": "wrong"}},  # bad type
        {"nope": True},                                 # not a tool at all
    ])
    names = [t["function"]["name"] for t in tools]
    assert "good_mcp" in names
    assert "wrong" not in names
    assert len(tools) > 100  # base set intact


# ---- text-dialect parser ----

def test_parse_plain_tool_call_block():
    from backend.assistant.llm_client import _parse_tool_call_text
    text = 'Let me check. <tool_call>{"name": "list_todos", "arguments": {}}</tool_call> done.'
    cleaned, tcs = _parse_tool_call_text(text)
    assert tcs and tcs[0]["function"]["name"] == "list_todos"
    assert "tool_call" not in (cleaned or "")


def test_parse_fenced_json_tool_call():
    from backend.assistant.llm_client import _parse_tool_call_text
    text = ('I will call it:\n```json\n{"name": "create_todo", '
            '"arguments": {"title": "milk"}}\n```\nThere.')
    cleaned, tcs = _parse_tool_call_text(text)
    assert tcs and tcs[0]["function"] == {"name": "create_todo",
                                          "arguments": {"title": "milk"}}
    assert "```" not in (cleaned or "")


def test_fenced_non_tool_json_untouched():
    from backend.assistant.llm_client import _parse_tool_call_text
    text = 'Here is data:\n```json\n{"city": "Chennai", "temp": 31}\n```'
    cleaned, tcs = _parse_tool_call_text(text)
    assert tcs is None
    assert "Chennai" in (cleaned or "")


def test_plain_prose_untouched():
    from backend.assistant.llm_client import _parse_tool_call_text
    text = "Hello! How can I help you today?"
    assert _parse_tool_call_text(text) == (text, None)


# ---- error bodies + response summary ----

def test_fallback_string_carries_provider_message(cfg):
    def handler(req, body, n):
        if "openrouter.ai" in str(req.url):
            return httpx.Response(402, json={"error": {"message": "Insufficient credits: add funds"}})
        return _ok("via-cloud")

    client, _ = _client("openrouter", cfg, handler)
    client.chat([{"role": "user", "content": "hi"}], tools=[])
    assert any("Insufficient credits" in f for f in client.last_fallbacks)


def test_response_summary_logged(cfg, caplog):
    def handler(req, body, n):
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "list_todos", "arguments": "{}"}}]}}]})

    client, _ = _client("openrouter", cfg, handler)
    with caplog.at_level("INFO"):
        client.chat([{"role": "user", "content": "hi"}], tools=[_tdef("list_todos")])
    assert "finish=tool_calls" in caplog.text
    assert "tool_calls=1" in caplog.text
    assert "tools_sent=1" in caplog.text


def _empty_choices(error_msg=None):
    body = {"id": "gen-x", "choices": []}
    if error_msg is not None:
        body["error"] = {"message": error_msg, "code": 500}
    return httpx.Response(200, json=body)


def test_empty_choices_retries_once_then_succeeds(cfg):
    def handler(req, body, n):
        return _empty_choices() if n == 1 else _ok("recovered")

    client, calls = _client("openrouter", cfg, handler, retry_same=True)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "recovered"
    assert len(calls) == 2
    assert client.last_fallbacks == []


def test_empty_choices_twice_fails_over_with_message(cfg):
    def handler(req, body, n):
        if "openrouter.ai" in str(req.url):
            return _empty_choices("upstream overloaded")
        return _ok("via-cloud")

    client, calls = _client("openrouter", cfg, handler)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[])
    content, _ = client.extract_response(resp)
    assert content == "via-cloud"
    assert client.last_provider == "ollama_cloud"
    assert any("empty choices" in f and "overloaded" in f for f in client.last_fallbacks)


def test_empty_choices_all_fail_raises(cfg):
    client, _ = _client("openrouter", cfg, lambda req, body, n: _empty_choices("down"))
    with pytest.raises(ProviderError) as ei:
        client.chat([{"role": "user", "content": "hi"}], tools=[])
    assert "empty choices" in str(ei.value)
