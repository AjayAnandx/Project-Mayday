"""Regression tests for the OpenAI Realtime interactive/worker split (Phase 0+1).

No network calls: mint_ephemeral_session uses an injected fake HTTP client,
and load_config is monkeypatched per-test.
"""
import asyncio
import json

import pytest

import backend.assistant.realtime_session as rt


def _run(coro):
    return asyncio.run(coro)


def _cfg(key="sk-test"):
    return {
        "realtime": {
            "enabled": True,
            "model": "gpt-realtime-2.1",
            "voice": "marin",
            "relay_only": True,
            "max_minutes_per_session": 15,
            "vad_threshold": 0.5,
            "api_key": key,
        },
        "openai": {"api_key": key},
        "personality": {"default_tone": "warm", "traits": ["kind"]},
        "skills": {"enabled": False},
        "mcp": {"servers": {
            "opencode": {"command": "python", "args": ["-m", "x"], "lazy": True},
            "fetch": {"command": "uvx", "args": ["y"], "lazy": True},
        }},
    }


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(rt, "load_config", lambda: _cfg())
    return _cfg()


def test_interactive_slice_is_small_and_fast(cfg):
    from backend.assistant.function_registry import get_tool_definitions
    sliced = rt.build_interactive_tools(get_tool_definitions(None))
    assert 5 <= len(sliced) <= len(rt.INTERACTIVE_TOOL_NAMES)
    names = {(t.get("function") or {}).get("name") for t in sliced}
    assert names <= set(rt.INTERACTIVE_TOOL_NAMES)
    # Heavy families must never leak into the realtime session.
    assert "opencode_bash" not in names
    assert "scaffold_ui_project" not in names
    assert "create_todo" not in names


def test_escalation_routing(cfg):
    assert rt.needs_worker_escalation("get_weather") is False
    assert rt.needs_worker_escalation("list_todos") is False
    assert rt.needs_worker_escalation("opencode_bash") is True
    assert rt.needs_worker_escalation("create_todo") is True
    assert rt.needs_worker_escalation("unknown_tool_xyz") is True
    assert rt.needs_worker_escalation("") is True


def test_parse_function_call_arguments(cfg):
    cid, name, args = rt.parse_function_call_arguments({
        "type": "response.function_call_arguments.done",
        "call_id": "call_1", "name": "get_weather",
        "arguments": '{"location": "Chennai"}'})
    assert (cid, name, args) == ("call_1", "get_weather", {"location": "Chennai"})
    # Dict-form arguments pass through.
    _, _, args2 = rt.parse_function_call_arguments(
        {"call_id": "c", "name": "recall", "arguments": {"query": "x"}})
    assert args2 == {"query": "x"}
    # Non-JSON arguments degrade to {} instead of raising.
    _, _, args3 = rt.parse_function_call_arguments(
        {"call_id": "c", "name": "recall", "arguments": "not-json{{{"})
    assert args3 == {}


def test_function_output_item_shape(cfg):
    item = rt.build_function_output_item("call_9", "sunny, 31C")
    assert item["type"] == "conversation.item.create"
    assert item["item"]["type"] == "function_call_output"
    assert item["item"]["call_id"] == "call_9"
    assert "sunny" in item["item"]["output"]


def test_session_update_shape(cfg):
    from backend.assistant.function_registry import get_tool_definitions
    sliced = rt.build_interactive_tools(get_tool_definitions(None))
    ev = rt.build_session_update("Be nice.", sliced)
    assert ev["type"] == "session.update"
    sess = ev["session"]
    assert sess["model"] == "gpt-realtime-2.1"
    assert sess["tool_choice"] == "auto"
    assert sess["audio"]["output"]["voice"] == "marin"
    # 11 interactive max + 3 worker-control tools (delegate/status/cancel).
    assert 8 <= len(sess["tools"]) <= 14
    for t in sess["tools"]:
        assert t["type"] == "function" and t["name"]
    names = {t["name"] for t in sess["tools"]}
    assert {"delegate_to_worker", "worker_status", "cancel_worker"} <= names


def test_status_ready_and_not_ready(monkeypatch):
    monkeypatch.setattr(rt, "load_config", lambda: _cfg(key="sk-x"))
    st = rt.realtime_status()
    assert st["ready"] is True and st["fallback"] == "text-only"
    monkeypatch.setattr(rt, "load_config", lambda: _cfg(key=""))
    st2 = rt.realtime_status()
    assert st2["ready"] is False and st2["reason"]


def test_instructions_are_slim(cfg):
    text = rt.build_interactive_instructions()
    assert "Mayday" in text
    assert "Keep spoken replies" in text
    # Delegation is now explicit so scheduling can't get stuck locally.
    assert "delegate_to_worker" in text
    assert "cancel_worker" in text
    # Interrupt disambiguation: status checks reassure, only stop cancels.
    assert "worker_status" in text
    assert "still running" in text
    # The 9-file website build protocol must never bloat the voice session.
    assert "scaffold_ui_project" not in text
    assert "tailwindcss" not in text


def test_worker_control_tools_advertised(cfg):
    tools = rt.get_worker_control_tools()
    names = {t["function"]["name"] for t in tools}
    assert names == {"delegate_to_worker", "worker_status", "cancel_worker"}
    assert rt.is_worker_control_tool("delegate_to_worker") is True
    assert rt.is_worker_control_tool("get_weather") is False
    # Control routing: delegate/cancel run as tracked jobs, status is local.
    assert rt.needs_worker_escalation("delegate_to_worker") is True
    assert rt.needs_worker_escalation("cancel_worker") is True
    assert rt.needs_worker_escalation("worker_status") is False


class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, data):
        self._data = data
        self.posts = []

    async def post(self, url, json=None, headers=None):
        self.posts.append((url, json))
        return _FakeResp(self._data)


def test_mint_ephemeral_session(cfg):
    fake = _FakeClient({"client_secret": {"value": "ek-123", "expires_at": 999},
                        "model": "gpt-realtime-2.1"})
    out = _run(rt.mint_ephemeral_session("sk-x", "gpt-realtime-2.1", "marin",
                                         http_client=fake))
    assert out["client_secret"] == "ek-123"
    assert out["model"] == "gpt-realtime-2.1"
    # GA endpoint first (client_secrets), legacy beta path only as fallback.
    assert fake.posts and fake.posts[0][0] == rt.REALTIME_CLIENT_SECRET_URL


def test_ga_handshake_has_no_beta_header(cfg):
    """Retired OpenAI-Beta header must never be sent (server closes with 4000)."""
    import importlib
    router_mod = importlib.import_module("backend.voice.router")
    headers = router_mod._realtime_headers("sk-x")
    assert headers == {"Authorization": "Bearer sk-x"}
    assert not any(k.lower() == "openai-beta" for k in headers)


def test_realtime_connect_sends_ga_headers(cfg, monkeypatch):
    import importlib
    import sys
    router_mod = importlib.import_module("backend.voice.router")

    class _FakeWSModule:
        def __init__(self):
            self.calls = []

        async def connect(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return "ws-conn"

    fake = _FakeWSModule()
    monkeypatch.setitem(sys.modules, "websockets", fake)
    conn = _run(router_mod._realtime_connect("sk-x", "gpt-realtime-2.1"))
    assert conn == "ws-conn"
    url, kwargs = fake.calls[0]
    assert "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1" == url
    sent = kwargs.get("additional_headers", {})
    assert sent == {"Authorization": "Bearer sk-x"}


def test_close_hint_maps_beta_shape_disabled(cfg):
    import importlib
    router_mod = importlib.import_module("backend.voice.router")
    hint = router_mod._describe_realtime_close(
        Exception("received 4000 (private use) invalid_request_error.beta_api_shape_disabled"))
    assert "Beta" in hint and "OpenAI-Beta" in hint


def test_status_advertises_webrtc(cfg):
    st = rt.realtime_status()
    assert st["webrtc"] is True
    assert st["transport"] == "relay"


def test_parse_call_id():
    assert rt.parse_call_id("/v1/realtime/calls/rtc_abc123") == "rtc_abc123"
    assert rt.parse_call_id("https://api.openai.com/v1/realtime/calls/rtc_x/") == "rtc_x"
    assert rt.parse_call_id("") == ""
    assert rt.parse_call_id("/v1/realtime/calls/not-a-call-id") == ""


def test_calls_session_config_shape(cfg):
    from backend.assistant.function_registry import get_tool_definitions
    sliced = rt.build_interactive_tools(get_tool_definitions(None))
    scfg = rt.build_calls_session_config("Be nice.", sliced)
    assert scfg["type"] == "realtime"
    assert scfg["model"] == "gpt-realtime-2.1"
    assert scfg["audio"]["output"]["voice"] == "marin"
    assert 8 <= len(scfg["tools"]) <= 14
    assert all(t["type"] == "function" and t["name"] for t in scfg["tools"])
    assert {"delegate_to_worker", "worker_status", "cancel_worker"} <= {
        t["name"] for t in scfg["tools"]}


class _FakeBrowserWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def test_worker_sender_wraps_and_summarizes(cfg):
    from backend.assistant.realtime_worker import RealtimeWorkerSender
    ws = _FakeBrowserWS()
    sender = RealtimeWorkerSender(ws)
    _run(sender.send_json({"type": "token", "content": "Hello "}))
    _run(sender.send_json({"type": "token", "content": "world"}))
    _run(sender.send_json({"type": "tool_call", "name": "list_todos", "result": "ok"}))
    _run(sender.send_json({"type": "done"}))
    assert sender.done is True
    assert sender.summary() == "Hello world"
    # Tokens coalesce (one message for "Hello world"), milestones flush through.
    assert [m["type"] for m in ws.sent] == ["worker_progress"] * 3
    assert ws.sent[0]["event"] == {"type": "token", "content": "Hello world"}
    assert ws.sent[1]["event"]["type"] == "tool_call"


def test_worker_sender_throttles_long_streams(cfg):
    from backend.assistant.realtime_worker import (
        RealtimeWorkerSender, WORKER_TOKEN_FLUSH_CHARS)
    ws = _FakeBrowserWS()
    sender = RealtimeWorkerSender(ws)
    _run(sender.send_json({"type": "token", "content": "x" * WORKER_TOKEN_FLUSH_CHARS}))
    _run(sender.send_json({"type": "token", "content": "y" * 10}))
    _run(sender.send_json({"type": "done"}))
    # First chunk flushed at threshold, tail flushed on done — not per token.
    assert len(ws.sent) == 3
    assert ws.sent[0]["event"] == {"type": "token",
                                   "content": "x" * WORKER_TOKEN_FLUSH_CHARS}
    assert ws.sent[1]["event"] == {"type": "token", "content": "y" * 10}
    assert sender.summary().startswith("x" * 10)


def test_worker_sender_summary_truncates(cfg):
    from backend.assistant.realtime_worker import RealtimeWorkerSender
    sender = RealtimeWorkerSender(_FakeBrowserWS())
    _run(sender.send_json({"type": "token", "content": "x" * 2000}))
    assert len(sender.summary()) <= 601  # 600 chars + ellipsis


def test_worker_prompt_shape(cfg):
    from backend.assistant.realtime_worker import build_worker_prompt
    p = build_worker_prompt("create_todo", {"title": "milk"}, "buy some milk")
    assert "create_todo" in p and "milk" in p and "Voice realtime handoff" in p
    # Terse machine contract keeps worker tokens low; interactive humanizes.
    assert "FACTS:" in p and "HINT:" in p and "TERSE MACHINE FORMAT" in p
    p2 = build_worker_prompt("opencode_bash", {}, "")
    assert "no transcript captured" in p2


def test_machine_result_parsing(cfg):
    from backend.assistant.realtime_worker import (
        build_machine_result, extract_facts, extract_hint)
    s = ("Did stuff.\nFACTS:\n- Meeting booked for 10am\n- Invited Anil\n"
         "HINT: Meeting booked for 10am tomorrow")
    assert extract_facts(s) == ["Meeting booked for 10am", "Invited Anil"]
    assert extract_hint(s) == "Meeting booked for 10am tomorrow"
    r = build_machine_result(s, "delegated_task")
    assert r["status"] == "done" and len(r["facts"]) == 2 and "10am" in r["hint"]
    # Fallback when the worker forgets the block: sentences, first line.
    r2 = build_machine_result("Booked it. All set.", "delegated_task")
    assert r2["facts"] and r2["hint"]


def test_build_worker_context_no_network(cfg, monkeypatch):
    """Engine context builds with lazy MCP only — no subprocess, no LLM call."""
    import backend.assistant.realtime_worker as rwmod
    import backend.assistant.llm_client as llmmod
    import backend.assistant.providers.router as routermod
    # build_worker_context resolves load_config from its own module namespace.
    monkeypatch.setattr(rwmod, "load_config", lambda: _cfg())
    monkeypatch.setattr(llmmod, "load_config", lambda: _cfg())
    monkeypatch.setattr(routermod, "load_config", lambda: _cfg())
    ctx = _run(rwmod.build_worker_context())
    assert ctx.llm is not None and ctx.tools and ctx.mcp is not None
    assert ctx.selector is not None and ctx.router is not None
    assert ctx.query_classifier is not None
    # No eager MCP subprocesses spawned at build time (all forced lazy).
    assert not getattr(ctx.mcp, "_sessions", {})
    # Static tool defs ARE present (opencode/fetch/ui registries) without connects.
    names = {(t.get("function") or {}).get("name") for t in ctx.tools}
    assert "opencode_bash" in names


def test_echo_filter_drops_own_tts(cfg):
    """Own TTS echo heard while speaking must be flagged, real speech not."""
    assert rt.is_echo_transcript("hello world", "Hello world, how are you?") is True
    assert rt.is_echo_transcript(
        "what is the weather in Chennai", "Hello world, how are you?") is False
    assert rt.is_echo_transcript("", "Hello") is False
    assert rt.is_echo_transcript("hello", "") is False


def test_session_update_has_echo_resistant_vad(cfg):
    from backend.assistant.function_registry import get_tool_definitions
    sliced = rt.build_interactive_tools(get_tool_definitions(None))
    ev = rt.build_session_update("Be nice.", sliced)
    vad = ev["session"]["audio"]["input"]["turn_detection"]
    assert vad["type"] == "server_vad"
    assert vad["threshold"] == 0.5  # passes through the (fixture) configured value
    assert vad["silence_duration_ms"] >= 500
    assert vad["interrupt_response"] is True  # barge-in preserved
    # Production default is raised from the old 0.5 to resist speaker echo.
    prod = rt._turn_detection_config({"vad_threshold": 0.65,
                                      "vad_silence_duration_ms": 600,
                                      "vad_prefix_padding_ms": 200})
    assert prod["threshold"] >= 0.6


def test_relay_transcript_echo_suppression(cfg):
    import importlib
    router_mod = importlib.import_module("backend.voice.router")
    st = router_mod._new_realtime_state()
    st["speaking"] = True
    st["last_assistant"] = "Hello world how are you today"

    class _WS:
        def __init__(self):
            self.sent = []

        async def send_json(self, data):
            self.sent.append(data)

    ws = _WS()
    fwd_echo = _run(router_mod._handle_transcript_completed(ws, st, "hello world"))
    assert fwd_echo is False
    assert st["transcript"] == ""  # echo never pollutes worker prompt context
    assert st["echo_dropped"] == 1
    assert ws.sent and ws.sent[0]["type"] == "echo_suppressed"

    ws2 = _WS()
    fwd_real = _run(router_mod._handle_transcript_completed(
        ws2, st, "what is the weather in Chennai"))
    assert fwd_real is True
    assert "Chennai" in st["transcript"]

    # Same words when NOT speaking are genuine user speech — forward them.
    st2 = router_mod._new_realtime_state()
    st2["last_assistant"] = "Hello world"
    ws3 = _WS()
    assert _run(router_mod._handle_transcript_completed(ws3, st2, "hello world")) is True


def test_relay_speaking_floor_tracking(cfg):
    import importlib
    router_mod = importlib.import_module("backend.voice.router")
    st = router_mod._new_realtime_state()
    router_mod._note_upstream_event(st, {"type": "response.output_audio.delta",
                                         "delta": "abc"})
    assert st["speaking"] is True
    router_mod._note_upstream_event(
        st, {"type": "response.output_audio_transcript.done",
             "transcript": "Hello world"})
    assert st["last_assistant"] == "Hello world"
    router_mod._note_upstream_event(st, {"type": "response.output_audio.done"})
    assert st["speaking"] is False
    router_mod._note_upstream_event(st, {"type": "response.created"})
    assert st["speaking"] is True
    router_mod._note_upstream_event(st, {"type": "input_audio_buffer.speech_started"})
    assert st["speaking"] is False  # barge-in takes the floor back


class _FakeOaiWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def _delegate_event(task):
    return {"type": "response.function_call_arguments.done", "call_id": "call-d1",
            "name": "delegate_to_worker", "arguments": {"task": task}}


def test_delegate_spawns_tracked_job(cfg, monkeypatch):
    import importlib
    router_mod = importlib.import_module("backend.voice.router")

    async def _fake_ctx(state):
        state["worker_ctx"] = object()
        return state["worker_ctx"]

    spawned = {}

    async def _fake_announce(oai_ws, notify_ws, worker_ctx, tool_name, args,
                             transcript, job_id="", state=None):
        spawned["job_id"] = job_id
        spawned["tool"] = tool_name
        if state is not None and job_id:
            state["worker_jobs"][job_id]["status"] = "done"
            state["worker_jobs"][job_id]["summary"] = "ok"

    monkeypatch.setattr(router_mod, "_ensure_worker_ctx", _fake_ctx)
    monkeypatch.setattr(router_mod, "_run_worker_and_announce", _fake_announce)

    async def _fake_speak(*a, **k):
        return None

    monkeypatch.setattr(router_mod, "_speak_to_session", _fake_speak)

    async def go():
        oai = _FakeOaiWS()
        ws = _FakeBrowserWS()
        st = router_mod._new_realtime_state()
        st["transcript"] = "schedule a meeting tomorrow at 10am"
        await router_mod._handle_realtime_tool_event(
            oai, ws, st, _delegate_event("Schedule a meeting tomorrow at 10am"))
        # Drain the spawned task (fake announce already ran inline? no — it is
        # wrapped in create_task, so await it).
        for t in list((st.get("worker_tasks") or {}).values()):
            await t
        return oai, ws, st

    oai, ws, st = _run(go())
    assert spawned["tool"] == "delegated_task"
    job_id = spawned["job_id"]
    assert job_id and job_id in st["worker_jobs"]
    assert st["worker_jobs"][job_id]["status"] == "done"
    # Model got a function output with the job id (monitor handle).
    assert any(job_id in m for m in oai.sent)
    # Browser got the escalation with the same job id.
    assert any(isinstance(m, dict) and m.get("job_id") == job_id for m in ws.sent)


def test_worker_status_and_cancel(cfg):
    import importlib
    router_mod = importlib.import_module("backend.voice.router")

    async def go():
        oai = _FakeOaiWS()
        ws = _FakeBrowserWS()
        st = router_mod._new_realtime_state()
        st["worker_jobs"] = {"w1": {"tool": "delegated_task", "task": "meeting",
                                    "args": {}, "transcript": "",
                                    "status": "running", "summary": ""}}
        await router_mod._handle_realtime_tool_event(
            oai, ws, st, {"type": "response.function_call_arguments.done",
                          "call_id": "c-s", "name": "worker_status",
                          "arguments": {}})
        assert any("w1" in m and "running" in m for m in oai.sent)

        # Cancel with a live task flips to cancelled via the task path.
        async def _job():
            await asyncio.sleep(60)

        t = asyncio.create_task(_job())
        st["worker_tasks"] = {"w1": t}
        oai2 = _FakeOaiWS()
        await router_mod._handle_realtime_tool_event(
            oai2, ws, st, {"type": "response.function_call_arguments.done",
                           "call_id": "c-c", "name": "cancel_worker",
                           "arguments": {"job_id": "w1"}})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert t.cancelled() or t.done()
        assert any("w1" in m for m in oai2.sent)
        try:
            await t
        except asyncio.CancelledError:
            pass
        return True

    assert _run(go()) is True


def test_worker_announce_marks_done_and_cancelled(cfg, monkeypatch):
    import importlib
    import backend.assistant.realtime_worker as rwmod
    router_mod = importlib.import_module("backend.voice.router")

    async def _fake_run(ctx, notify_ws, tool_name, args, transcript, job_id=""):
        return "did the thing"

    monkeypatch.setattr(rwmod, "run_worker_job", _fake_run)
    # Rebind the already-imported symbol inside router's function closure by
    # patching the module attribute it imports lazily.
    oai = _FakeOaiWS()
    ws = _FakeBrowserWS()
    st = router_mod._new_realtime_state()
    st["worker_jobs"] = {"w9": {"tool": "delegated_task", "task": "x",
                                "args": {}, "transcript": "",
                                "status": "running", "summary": ""}}
    _run(router_mod._run_worker_and_announce(oai, ws, object(), "delegated_task",
                                             {"task": "x"}, "", job_id="w9",
                                             state=st))
    assert st["worker_jobs"]["w9"]["status"] == "done"
    assert "did the thing" in st["worker_jobs"]["w9"]["summary"]
    # Machine result stored for monitor + humanized proactive announce.
    assert st["worker_jobs"]["w9"]["result"]["status"] == "done"
    assert st["worker_jobs"]["w9"]["result"]["hint"]
    assert any("response.create" in m for m in oai.sent)
    assert any("humanize" in m.lower() for m in oai.sent)
