import asyncio
import base64
import json
import logging
import time

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.config import load_config

from .deepgram_stt import relay_stt
from .deepgram_tts import synthesize
from backend.assistant.realtime_session import (
    REALTIME_WS_URL,
    build_escalation_ack,
    build_function_output_item,
    build_interactive_instructions,
    build_interactive_tools,
    build_session_update,
    get_realtime_api_key,
    get_realtime_config,
    is_echo_transcript,
    is_worker_control_tool,
    mint_ephemeral_session,
    needs_worker_escalation,
    parse_function_call_arguments,
    realtime_status,
)


class TtsRequest(BaseModel):
    text: str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

realtime_router = APIRouter(prefix="/api/realtime", tags=["realtime"])


def _get_api_key() -> str:
    cfg = load_config()
    return (cfg.get("voice", {}) or {}).get("deepgram_api_key", "") or ""


@router.get("/status")
def status():
    key = _get_api_key()
    enabled = bool(key)
    return {
        "enabled": enabled,
        "stt": "deepgram",
        "tts": "deepgram",
        "note": "Voice handled via Deepgram STT (WebSocket) + TTS (REST)",
    }


@router.websocket("/stt")
async def voice_stt(ws: WebSocket):
    api_key = _get_api_key()
    if not api_key:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Deepgram API key not configured"})
        await ws.close()
        return
    try:
        await relay_stt(ws, api_key)
    except WebSocketDisconnect:
        logger.info("Frontend STT WebSocket disconnected")
    except Exception as e:
        logger.error(f"STT WebSocket error: {e}")


@router.post("/tts")
async def voice_tts(body: TtsRequest):
    api_key = _get_api_key()
    if not api_key:
        return Response(status_code=400, content="Deepgram API key not configured")
    text = body.text.strip()
    if not text:
        return Response(status_code=400, content="No text provided")
    try:
        cfg = load_config()
        voice = (cfg.get("voice", {}) or {}).get("tts_voice", "aura-asteria-en")
        audio_bytes = await synthesize(text, api_key, voice)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return Response(status_code=500, content=f"TTS failed: {e}")


# ---- OpenAI Realtime — interactive voice agent (Hybrid Stage 1: WS relay) ----
# Key discipline: the long-lived OPENAI_API_KEY is only ever used server-side
# (relay connect + ephemeral mint). The browser only talks to these endpoints.
# When Realtime is unreachable or the key is missing: text-only fallback
# (error JSON + close; chat over /ws/chat is unaffected).


@realtime_router.get("/status")
def realtime_status_endpoint():
    return realtime_status()


@realtime_router.post("/session")
async def realtime_mint_session():
    """Mint a short-lived client_secret for WebRTC-direct (Hybrid Stage 2).

    Stage 1 relay does not need this, but the endpoint is live now so Stage 2
    needs no new auth code — only the SDP endpoint + frontend switch.
    """
    st = realtime_status()
    if not st["ready"]:
        return Response(status_code=503, content=f"Realtime not ready: {st['reason']}")
    try:
        data = await mint_ephemeral_session(
            get_realtime_api_key(), st["model"], st["voice"])
        if not data.get("client_secret"):
            return Response(status_code=502, content="Realtime mint returned no secret")
        # Never leak anything beyond the short-lived secret + metadata.
        return {
            "client_secret": data["client_secret"],
            "expires_at": data.get("expires_at", ""),
            "model": data.get("model", st["model"]),
            "voice": st["voice"],
        }
    except Exception as e:
        logger.error(f"Realtime session mint failed: {e}")
        return Response(status_code=502, content=f"Realtime mint failed: {e}")


def _realtime_headers(api_key: str) -> dict:
    """Auth headers for the GA Realtime interface.

    NOTE: do NOT send `OpenAI-Beta: realtime-v1` — that opts into the retired
    Beta wire protocol, which the server rejects by closing the socket with
    4000 / invalid_request_error.beta_api_shape_disabled (GA migration guide:
    "Remove the OpenAI-Beta: realtime=v1 header when calling the GA
    interface").
    """
    return {"Authorization": f"Bearer {api_key}"}


async def _realtime_connect(api_key: str, model: str, call_id: str = ""):
    """Open the server-side WebSocket to OpenAI Realtime (GA interface).

    With a call_id this attaches to an in-progress WebRTC/SIP call as a
    sideband control connection (same session, server-only events).
    """
    import websockets

    url = (f"{REALTIME_WS_URL}?call_id={call_id}" if call_id
           else f"{REALTIME_WS_URL}?model={model}")
    headers = _realtime_headers(api_key)
    try:
        # websockets >= 14 renamed extra_headers -> additional_headers.
        return await websockets.connect(url, additional_headers=headers)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers)


class _NullBrowserWS:
    """send_json sink for server-only (sideband) worker jobs — no browser attached."""

    async def send_json(self, data: dict):
        pass


def _describe_realtime_close(error: Exception) -> str:
    """Map known upstream close reasons to actionable hints."""
    text = str(error)
    if "beta_api_shape_disabled" in text:
        return (f"{text} — server rejected the retired Beta wire protocol. "
                "Ensure no OpenAI-Beta header is sent and session/event shapes "
                "follow the GA interface.")
    if "401" in text or "invalid_api_key" in text or "unauthorized" in text.lower():
        return f"{text} — check OPENAI_API_KEY (.env or config.yaml realtime.api_key)."
    return text


def _build_interactive_tool_slice() -> list[dict]:
    """Local tool defs filtered to the interactive slice (no MCP spawn)."""
    try:
        from backend.assistant.function_registry import get_tool_definitions
        return build_interactive_tools(get_tool_definitions(None))
    except Exception as e:
        logger.error(f"Realtime tool slice build failed: {e}")
        return []


async def _speak_to_session(oai_ws, text: str):
    """Make a realtime session say one short thing (system-prompted turn)."""
    try:
        await oai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        }))
        await oai_ws.send(json.dumps({"type": "response.create"}))
    except Exception as e:
        logger.warning("Realtime speak send failed: %s", e)


async def _run_worker_and_announce(oai_ws, notify_ws, worker_ctx, tool_name: str,
                                   args: dict, transcript: str,
                                   job_id: str = "", state: dict | None = None):
    """Run an escalated job through the engine loop, then speak the outcome.

    job_id/state back the interactive agent's monitor + stop control: status
    flips running -> done/failed, and asyncio cancellation (via cancel_worker)
    is reported as worker_cancelled to the browser plus a spoken confirmation.
    """
    from backend.assistant.realtime_worker import run_worker_job
    jobs = (state.get("worker_jobs") or {}) if isinstance(state, dict) else {}
    entry = jobs.get(job_id) if job_id else None
    if isinstance(entry, dict):
        entry["status"] = "running"
    try:
        summary = await run_worker_job(worker_ctx, notify_ws, tool_name, args, transcript,
                                       job_id=job_id)
    except asyncio.CancelledError:
        if isinstance(entry, dict):
            entry["status"] = "cancelled"
        try:
            await notify_ws.send_json({"type": "worker_cancelled", "tool": tool_name,
                                       "job_id": job_id})
        except Exception:
            pass
        await _speak_to_session(
            oai_ws,
            "System note: the background worker job "
            f"'{tool_name}' (job {job_id or 'unknown'}) was just cancelled because "
            "the user said stop. Briefly confirm in one short sentence that it "
            "is stopped and nothing further will run.")
        return
    except Exception as e:
        logger.exception("Realtime worker task failed for %s", tool_name)
        summary = f"Sorry — the background job for {tool_name} failed ({e})."
        if isinstance(entry, dict):
            entry["status"] = "failed"
            entry["summary"] = summary[:2000]
        await _speak_to_session(
            oai_ws,
            "System note: the background worker just failed the escalated "
            f"task '{tool_name}' (job {job_id or 'unknown'}). Briefly tell the user "
            f"in one or two short sentences: {summary}")
        return
    from backend.assistant.realtime_worker import build_machine_result
    result = build_machine_result(summary, tool_name, status="done")
    if isinstance(entry, dict):
        entry["status"] = "done"
        entry["summary"] = (summary or "")[:2000]
        entry["result"] = result
    facts_text = "; ".join(result.get("facts") or [])[:1000]
    hint_text = (result.get("hint") or summary or "")[:500]
    # Proactive completion: speak even if the user interrupted mid-job. The
    # worker speaks in terse facts; the interactive voice humanizes them.
    await _speak_to_session(
        oai_ws,
        "System note: the background worker just finished the escalated "
        f"task '{tool_name}' (job {job_id or 'unknown'}). Proactively tell the user "
        "now in 1-2 short warm human sentences — do not read JSON, humanize "
        f"these facts: {facts_text}. Headline outcome: {hint_text}")


async def _ensure_worker_ctx(state: dict):
    """Lazily build the engine context for escalated jobs (once per session)."""
    if state.get("worker_ctx") is None:
        from backend.assistant.realtime_worker import build_worker_context
        state["worker_ctx"] = await build_worker_context()
    return state["worker_ctx"]


def _new_realtime_state() -> dict:
    """Per-connection voice state.

    speaking: True while assistant audio is streaming (echo window).
    last_assistant: trailing slice of the last spoken transcript, used for
        the server-side echo filter.
    worker_jobs: job_id -> {tool, task, args, transcript, status, summary,
        result}. result is the machine contract {status, tool, facts, hint} —
        terse worker data the interactive voice humanizes. Gives the
        interactive agent full monitor + stop control over parallel
        background work. Asyncio Tasks live in worker_tasks (same keys) so
        cancel_worker can stop them; both dicts are per-connection.
    """
    return {"transcript": "", "worker_ctx": None, "speaking": False,
            "last_assistant": "", "echo_dropped": 0,
            "worker_jobs": {}, "worker_tasks": {}, "job_seq": 0}


MAX_WORKER_JOBS = 3


async def _handle_transcript_completed(ws, state: dict, transcript: str) -> bool:
    """Store + forward a user transcript unless it looks like our own echo.

    Returns True when forwarded, False when suppressed as echo.
    """
    text = (transcript or "").strip()
    if not text:
        return False
    if state.get("speaking") and is_echo_transcript(
            text, state.get("last_assistant", "")):
        state["echo_dropped"] = int(state.get("echo_dropped", 0) or 0) + 1
        logger.info("Realtime echo suppressed (%d so far): %r",
                    state["echo_dropped"], text[:120])
        try:
            await ws.send_json({"type": "echo_suppressed", "text": text[:500]})
        except Exception:
            pass
        return False
    state["transcript"] = text[-2000:]
    try:
        await ws.send_json({"type": "user_transcript", "text": text})
    except Exception:
        pass
    return True


def _note_upstream_event(state: dict, event: dict) -> None:
    """Track the assistant floor for the echo filter."""
    etype = event.get("type", "")
    if etype == "response.created":
        state["speaking"] = True
    elif etype in ("response.output_audio.delta", "response.audio.delta"):
        if event.get("delta"):
            state["speaking"] = True
    elif etype in ("response.output_audio.done", "response.audio.done",
                   "response.done"):
        state["speaking"] = False
    elif etype in ("response.output_audio_transcript.done",
                   "response.audio_transcript.done"):
        tr = event.get("transcript")
        if isinstance(tr, str) and tr.strip():
            state["last_assistant"] = tr.strip()[-2000:]
    elif etype == "input_audio_buffer.speech_started":
        # Genuine user barge-in takes the floor back.
        state["speaking"] = False


def _next_job_id(state: dict) -> str:
    seq = int(state.get("job_seq", 0) or 0) + 1
    state["job_seq"] = seq
    return f"w{seq}"


def _running_jobs(state: dict) -> list[tuple[str, dict]]:
    jobs = state.get("worker_jobs") or {}
    return [(jid, e) for jid, e in jobs.items()
            if isinstance(e, dict) and e.get("status") == "running"]


def _describe_jobs(state: dict, job_id: str = "") -> str:
    jobs = state.get("worker_jobs") or {}
    if job_id:
        entry = jobs.get(job_id)
        if not isinstance(entry, dict):
            return f"No worker job '{job_id}'."
        return (f"Job {job_id}: status={entry.get('status', '?')}, "
                f"tool={entry.get('tool', '?')}, "
                f"task={(entry.get('task') or '')[:500]}"
                + (f", summary={(entry.get('summary') or '')[:500]}"
                   if entry.get("status") in ("done", "failed") else ""))
    if not jobs:
        return "No background worker jobs."
    lines = []
    for jid, entry in jobs.items():
        if not isinstance(entry, dict):
            continue
        line = (f"Job {jid}: status={entry.get('status', '?')}, "
                f"tool={entry.get('tool', '?')}, "
                f"task={(entry.get('task') or '')[:200]}")
        hint = ((entry.get("result") or {}).get("hint")
                if isinstance(entry.get("result"), dict) else "") or ""
        if hint and entry.get("status") in ("done", "failed"):
            line += f", outcome={hint[:200]}"
        lines.append(line)
    return "\n".join(lines) if lines else "No background worker jobs."


async def _reply_tool(oai_ws, notify_ws, call_id: str, name: str, output: str,
                      escalated: bool = False, extra: dict | None = None):
    """Send a tool result back to the OpenAI session (and the browser)."""
    try:
        await oai_ws.send(json.dumps(build_function_output_item(call_id, output or "")))
        await oai_ws.send(json.dumps({"type": "response.create"}))
    except Exception as e:
        logger.warning("Realtime tool-output send failed for %s: %s", name, e)
    if not isinstance(notify_ws, _NullBrowserWS):
        try:
            payload = {"type": "tool_result", "name": name, "result": output,
                       "escalated": escalated}
            if extra:
                payload.update(extra)
            await notify_ws.send_json(payload)
        except Exception:
            pass


async def _spawn_delegated_job(oai_ws, notify_ws, state: dict, call_id: str,
                               task: str, transcript: str):
    """Start a delegate_to_worker job tracked in state for status/cancel."""
    task_text = (task or "").strip()
    if not task_text:
        await _reply_tool(oai_ws, notify_ws, call_id, "delegate_to_worker",
                          "No task provided — ask the user what they want done.")
        await _speak_to_session(
            oai_ws, "System note: delegate_to_worker was called with no task. "
            "Ask the user briefly what they want done.")
        return
    if len(_running_jobs(state)) >= MAX_WORKER_JOBS:
        await _reply_tool(oai_ws, notify_ws, call_id, "delegate_to_worker",
                          f"Too many running jobs (max {MAX_WORKER_JOBS}). "
                          "Use worker_status and cancel one first.")
        await _speak_to_session(
            oai_ws, "System note: the worker pool is full. Briefly tell the user "
            "you are already running several jobs and ask which to stop first.")
        return
    try:
        worker_ctx = await _ensure_worker_ctx(state)
    except Exception as e:
        logger.exception("Realtime worker context build failed")
        await _reply_tool(oai_ws, notify_ws, call_id, "delegate_to_worker",
                          f"Worker failed to start ({e}).")
        await _speak_to_session(
            oai_ws, "System note: the background worker failed to start "
            f"({e}). Apologize briefly and offer to try another way.")
        return
    job_id = _next_job_id(state)
    args = {"task": task_text[:2000]}
    state.setdefault("worker_jobs", {})[job_id] = {
        "tool": "delegated_task", "task": task_text[:2000], "args": args,
        "transcript": (transcript or "")[-2000:], "status": "running", "summary": "",
    }
    ack = build_escalation_ack("delegated_task") + f" (job {job_id})."
    await _reply_tool(oai_ws, notify_ws, call_id, "delegate_to_worker",
                      f"Started background job {job_id}: {task_text[:500]}",
                      escalated=True,
                      extra={"ack": ack, "job_id": job_id})
    await _speak_to_session(
        oai_ws, "System note: you just delegated the voice request to the "
        f"background worker as job {job_id}. Briefly tell the user in one "
        f"sentence: {ack}")
    try:
        coro = _run_worker_and_announce(
            oai_ws, notify_ws, worker_ctx, "delegated_task", args,
            state.get("transcript", ""), job_id=job_id, state=state)
        state.setdefault("worker_tasks", {})[job_id] = asyncio.create_task(coro)
    except Exception as e:
        logger.exception("Realtime worker spawn failed for job %s", job_id)
        state.get("worker_jobs", {}).pop(job_id, None)
        state.get("worker_tasks", {}).pop(job_id, None)
        await _speak_to_session(
            oai_ws, f"System note: could not start the background job ({e}). "
            "Apologize briefly.")


async def _cancel_worker_job(oai_ws, notify_ws, state: dict, call_id: str,
                             job_id: str, reason: str):
    """Cancel a tracked worker task on behalf of the interactive agent."""
    jobs = state.get("worker_jobs") or {}
    tasks = state.get("worker_tasks") or {}
    target = (job_id or "").strip()
    if not target:
        running = _running_jobs(state)
        if not running:
            await _reply_tool(oai_ws, notify_ws, call_id, "cancel_worker",
                              "No running worker jobs to stop.")
            await _speak_to_session(
                oai_ws, "System note: cancel_worker was called but no jobs are "
                "running. Briefly tell the user there is nothing to stop.")
            return
        target = running[-1][0]
    entry = jobs.get(target)
    task = tasks.get(target)
    if not isinstance(entry, dict) or entry.get("status") != "running" or task is None:
        status = (entry.get("status") if isinstance(entry, dict) else None) or "unknown"
        await _reply_tool(oai_ws, notify_ws, call_id, "cancel_worker",
                          f"Job {target} is not running (status={status}).")
        await _speak_to_session(
            oai_ws, f"System note: job {target} is already {status}. Briefly "
            "tell the user so.")
        return
    entry["status"] = "cancelling"
    if reason:
        entry["cancel_reason"] = reason[:300]
    try:
        task.cancel()
    except Exception as e:
        logger.warning("Realtime job %s cancel failed: %s", target, e)
    await _reply_tool(oai_ws, notify_ws, call_id, "cancel_worker",
                      f"Stopping background job {target}.",
                      extra={"job_id": target, "cancelled": True})
    # The task's CancelledError path speaks the final confirmation, so the
    # interactive agent stays in sync without polling.


async def _handle_realtime_tool_event(oai_ws, notify_ws, state: dict, event: dict):
    """Shared tool router for relay + sideband: inline fast tools, escalate heavy ones.

    notify_ws is the browser socket (relay) or _NullBrowserWS (sideband).
    Sideband progress has no browser to stream to — it is only logged.
    """
    from backend.assistant.function_registry import dispatch_call

    call_id, name, args = parse_function_call_arguments(event)
    if not name:
        return
    args = args or {}
    # Worker-control tools: the interactive agent's full monitor + stop API.
    if is_worker_control_tool(name):
        if name == "delegate_to_worker":
            await _spawn_delegated_job(oai_ws, notify_ws, state, call_id,
                                       args.get("task", ""),
                                       state.get("transcript", ""))
            return
        if name == "worker_status":
            await _reply_tool(oai_ws, notify_ws, call_id, name,
                              _describe_jobs(state, (args.get("job_id") or "")))
            return
        if name == "cancel_worker":
            await _cancel_worker_job(oai_ws, notify_ws, state, call_id,
                                     args.get("job_id", ""),
                                     args.get("reason", ""))
            return
        return
    has_browser = not isinstance(notify_ws, _NullBrowserWS)
    if not needs_worker_escalation(name):
        try:
            result = await dispatch_call(name, args or {})
        except Exception as e:
            result = f"Error executing {name}: {e}"
        if isinstance(result, str) and len(result) > 8000:
            result = result[:8000] + "\n...[truncated]"
        try:
            await oai_ws.send(json.dumps(build_function_output_item(call_id, result or "")))
            await oai_ws.send(json.dumps({"type": "response.create"}))
        except Exception as e:
            logger.warning("Realtime tool-output send failed for %s: %s", name, e)
        if has_browser:
            try:
                await notify_ws.send_json({"type": "tool_result", "name": name,
                                           "result": result, "escalated": False})
            except Exception:
                pass
        return
    # Escalated: full engine loop as a tracked background job so the
    # interactive agent can monitor (worker_status) and stop (cancel_worker) it.
    if len(_running_jobs(state)) >= MAX_WORKER_JOBS:
        await _reply_tool(oai_ws, notify_ws, call_id, name,
                          f"Too many running jobs (max {MAX_WORKER_JOBS}).")
        await _speak_to_session(
            oai_ws, "System note: the worker pool is full. Briefly tell the user "
            "you are already running several jobs and ask which to stop first.")
        return
    ack = build_escalation_ack(name)
    job_id = _next_job_id(state)
    state.setdefault("worker_jobs", {})[job_id] = {
        "tool": name, "task": "", "args": args or {},
        "transcript": state.get("transcript", ""), "status": "running", "summary": "",
    }
    await _reply_tool(oai_ws, notify_ws, call_id, name,
                      f"Started background job {job_id} for {name}.",
                      escalated=True,
                      extra={"ack": ack, "job_id": job_id})
    await _speak_to_session(
        oai_ws,
        "System note: you just decided to escalate the voice request to "
        f"the background worker (tool '{name}', job {job_id}). Briefly tell the user in "
        f"one sentence: {ack}")
    try:
        worker_ctx = await _ensure_worker_ctx(state)
    except Exception as e:
        logger.exception("Realtime worker context build failed")
        state.get("worker_jobs", {}).pop(job_id, None)
        await _speak_to_session(
            oai_ws,
            "System note: the background worker failed to start "
            f"({e}). Apologize briefly and offer to try another way.")
        return
    try:
        coro = _run_worker_and_announce(
            oai_ws, notify_ws, worker_ctx, name, args or {},
            state.get("transcript", ""), job_id=job_id, state=state)
        state.setdefault("worker_tasks", {})[job_id] = asyncio.create_task(coro)
    except Exception as e:
        logger.exception("Realtime worker spawn failed for %s", name)
        state.get("worker_jobs", {}).pop(job_id, None)
        state.get("worker_tasks", {}).pop(job_id, None)
        await _speak_to_session(
            oai_ws,
            f"System note: could not start the background job ({e}). Apologize briefly.")


@realtime_router.websocket("/voice")
async def realtime_voice(ws: WebSocket):
    st = realtime_status()
    await ws.accept()
    if not st["ready"]:
        await ws.send_json({"type": "error",
                            "message": f"Realtime unavailable ({st['reason']}) — text-only fallback",
                            "fallback": "text-only"})
        await ws.close()
        return

    api_key = get_realtime_api_key()
    cfg = get_realtime_config()
    deadline = time.time() + cfg["max_minutes_per_session"] * 60

    try:
        oai_ws = await _realtime_connect(api_key, cfg["model"])
    except Exception as e:
        logger.error(f"Realtime upstream connect failed: {e}")
        try:
            await ws.send_json({"type": "error",
                                "message": f"Realtime unavailable ({_describe_realtime_close(e)}) — text-only fallback",
                                "fallback": "text-only"})
            await ws.close()
        except Exception:
            pass
        return

    # Interactive tool slice: local defs only (no MCP subprocess spawn per
    # voice session). MCP/heavy tools escalate to the worker by design.
    interactive_tools = _build_interactive_tool_slice()

    try:
        await oai_ws.send(json.dumps(build_session_update(
            build_interactive_instructions(), interactive_tools)))
    except Exception as e:
        logger.error(f"Realtime session.update failed: {e}")
        try:
            await ws.send_json({"type": "error",
                                "message": f"Realtime setup failed ({_describe_realtime_close(e)}) — text-only fallback",
                                "fallback": "text-only"})
        except Exception:
            pass
        try:
            await oai_ws.close()
        except Exception:
            pass
        await ws.close()
        return

    logger.info("Realtime relay open (model=%s, %d interactive tools)",
                cfg["model"], len(interactive_tools))
    try:
        await ws.send_json({"type": "session_ready", "model": cfg["model"],
                            "voice": cfg["voice"],
                            "interactive_tools": len(interactive_tools)})
    except Exception:
        pass

    # Per-connection voice state: last user transcript (for worker prompts)
    # + lazily built worker context (engine loop for escalated jobs).
    # speaking/last_assistant back the server-side echo filter.
    state: dict = _new_realtime_state()

    async def _handle_function_call(event: dict):
        await _handle_realtime_tool_event(oai_ws, ws, state, event)

    async def _frontend_to_upstream():
        try:
            while True:
                if time.time() > deadline:
                    try:
                        await ws.send_json({"type": "session_ended",
                                            "message": "Voice session time limit reached"})
                    except Exception:
                        pass
                    break
                try:
                    msg = await ws.receive()
                except (WebSocketDisconnect, RuntimeError):
                    break
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    # Raw PCM16 frames from a minimal frontend: wrap as append.
                    b64 = base64.b64encode(msg["bytes"]).decode()
                    try:
                        await oai_ws.send(json.dumps(
                            {"type": "input_audio_buffer.append", "audio": b64}))
                    except Exception:
                        break
                elif msg.get("text") is not None:
                    # JSON control/audio events pass through untouched.
                    try:
                        await oai_ws.send(msg["text"])
                    except Exception:
                        break
        except Exception:
            pass

    async def _upstream_to_frontend():
        try:
            async for raw in oai_ws:
                if time.time() > deadline:
                    break
                try:
                    event = json.loads(raw) if isinstance(raw, (str, bytes)) else {}
                except Exception:
                    continue
                etype = event.get("type", "")
                _note_upstream_event(state, event)
                if etype == "conversation.item.input_audio_transcription.completed":
                    await _handle_transcript_completed(
                        ws, state, event.get("transcript") or "")
                    continue
                if etype == "response.function_call_arguments.done":
                    await _handle_function_call(event)
                    continue
                if etype == "error":
                    logger.warning("Realtime upstream error: %s", str(event)[:300])
                try:
                    await ws.send_text(raw if isinstance(raw, str) else json.dumps(event))
                except Exception:
                    break
        except Exception:
            pass

    try:
        await asyncio.gather(_frontend_to_upstream(), _upstream_to_frontend())
    finally:
        for closer in (oai_ws.close, ws.close):
            try:
                await closer()
            except Exception:
                pass
        logger.info("Realtime relay closed")


# ---- WebRTC direct (Hybrid Stage 2): unified SDP interface + sideband ----
# The browser POSTs its SDP offer here; the server forwards it (multipart +
# session config) to OpenAI with the long-lived key and returns the SDP
# answer plus the call_id. The server then attaches a sideband WS
# (?call_id=) that owns tools + worker escalation for that call — the same
# shared router the relay uses. relay_only stays true by default, so nothing
# changes until the frontend flips to WebRTC.


@realtime_router.post("/calls")
async def realtime_webrtc_calls(request: Request):
    """WebRTC unified interface: SDP offer in → SDP answer + call_id out."""
    st = realtime_status()
    if not st["ready"]:
        return Response(status_code=503, content=f"Realtime not ready: {st['reason']}")
    offer_sdp = (await request.body()).decode("utf-8", "replace").strip()
    if not offer_sdp or "v=0" not in offer_sdp:
        return Response(status_code=400, content="Expected raw SDP offer (application/sdp)")
    import httpx as _httpx
    from backend.assistant.realtime_session import (
        REALTIME_CALLS_URL, build_calls_session_config, parse_call_id,
    )
    session_cfg = build_calls_session_config(
        build_interactive_instructions(), _build_interactive_tool_slice())
    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                REALTIME_CALLS_URL,
                headers={"Authorization": f"Bearer {get_realtime_api_key()}"},
                files={
                    "session": (None, json.dumps(session_cfg), "application/json"),
                    "sdp": (None, offer_sdp, "application/sdp"),
                },
            )
        if resp.status_code >= 400:
            logger.warning("Realtime /calls upstream HTTP %s: %s",
                           resp.status_code, resp.text[:300])
            return Response(status_code=502,
                            content=f"Realtime calls failed (HTTP {resp.status_code})")
        call_id = parse_call_id(resp.headers.get("Location", ""))
        if not call_id:
            # Fallback: some responses embed the id in the JSON body.
            try:
                call_id = parse_call_id(resp.json().get("id", "") or "")
            except Exception:
                call_id = ""
        return {"sdp": resp.text, "call_id": call_id, "model": st["model"]}
    except Exception as e:
        logger.error(f"Realtime /calls failed: {e}")
        return Response(status_code=502, content=f"Realtime calls failed: {e}")


@realtime_router.websocket("/sideband")
async def realtime_sideband(ws: WebSocket):
    """Server-only control channel for an in-progress WebRTC call.

    Query: ?call_id=rtc_... Listens for function calls on that session and
    executes them (interactive inline, heavy via worker). No browser audio —
    progress is logged, outcomes are spoken back into the call.
    """
    st = realtime_status()
    await ws.accept()
    call_id = (ws.query_params.get("call_id", "") or "").strip()
    if not st["ready"]:
        await ws.send_json({"type": "error",
                            "message": f"Realtime unavailable ({st['reason']})"})
        await ws.close()
        return
    if not call_id:
        await ws.send_json({"type": "error", "message": "Missing ?call_id=rtc_..."})
        await ws.close()
        return
    try:
        oai_ws = await _realtime_connect(get_realtime_api_key(), st["model"],
                                         call_id=call_id)
    except Exception as e:
        logger.error(f"Realtime sideband connect failed for {call_id}: {e}")
        try:
            await ws.send_json({"type": "error", "message": f"Sideband failed: {e}"})
            await ws.close()
        except Exception:
            pass
        return
    try:
        await oai_ws.send(json.dumps(build_session_update(
            build_interactive_instructions(), _build_interactive_tool_slice())))
    except Exception as e:
        logger.error(f"Realtime sideband session.update failed: {e}")
        try:
            await oai_ws.close()
        except Exception:
            pass
        await ws.close()
        return

    logger.info("Realtime sideband open for %s", call_id)
    state: dict = _new_realtime_state()
    null_browser = _NullBrowserWS()
    try:
        await ws.send_json({"type": "sideband_ready", "call_id": call_id})
    except Exception:
        pass
    try:
        async for raw in oai_ws:
            try:
                event = json.loads(raw) if isinstance(raw, (str, bytes)) else {}
            except Exception:
                continue
            etype = event.get("type", "")
            _note_upstream_event(state, event)
            if etype == "conversation.item.input_audio_transcription.completed":
                transcript = (event.get("transcript") or "").strip()
                if not transcript:
                    continue
                if state.get("speaking") and is_echo_transcript(
                        transcript, state.get("last_assistant", "")):
                    state["echo_dropped"] = int(state.get("echo_dropped", 0) or 0) + 1
                    logger.info("Realtime sideband echo suppressed for %s (%d): %r",
                                call_id, state["echo_dropped"], transcript[:120])
                    continue
                state["transcript"] = transcript[-2000:]
                continue
            if etype == "response.function_call_arguments.done":
                await _handle_realtime_tool_event(oai_ws, null_browser, state, event)
                continue
            if etype == "error":
                logger.warning("Realtime sideband upstream error: %s", str(event)[:300])
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logger.warning("Realtime sideband loop ended for %s: %s", call_id, e)
    finally:
        for closer in (oai_ws.close, ws.close):
            try:
                await closer()
            except Exception:
                pass
        logger.info("Realtime sideband closed for %s", call_id)
