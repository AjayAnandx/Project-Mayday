"""OpenAI Realtime API — interactive voice agent session helpers.

Stage 1 (Hybrid): browser <-> FastAPI WS relay (/api/realtime/voice) <-> OpenAI.
The long-lived OPENAI_API_KEY never leaves the server. Realtime function calls
for the ~10 fast interactive tools are executed locally via dispatch_call;
anything heavier is escalated to the background worker (existing _run_engine).

No network calls happen at import time. mint_ephemeral_session() is the only
function that hits OpenAI (mock it in tests).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from backend.core.config import load_config

logger = logging.getLogger(__name__)

REALTIME_WS_URL = "wss://api.openai.com/v1/realtime"
REALTIME_SESSION_URL = "https://api.openai.com/v1/realtime/sessions"
REALTIME_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"

# Thin interactive slice: fast, single-turn, read-mostly tools the realtime
# session may call directly. Everything else escalates to the worker, which
# owns the full ToolRouter + MCP + skills + opencode/sandbox tool loop.
# Must stay << OpenAI's 128-tool limit (11 interactive + 3 worker-control).
INTERACTIVE_TOOL_NAMES = frozenset({
    "get_weather",
    "list_todos",
    "list_events",
    "query_events",
    "unified_search",
    "recall",
    "recall_entity",
    "get_system_info",
    "get_active_window",
    "list_projects",
    "suggest_skill",
})

# Worker-control tools: advertised in EVERY realtime session (relay + WebRTC)
# so the interactive agent — not just the server router — owns the worker
# lifecycle. delegate_to_worker is the reachable escalation entry point
# (heavy tools such as create_event are deliberately NOT advertised, otherwise
# the model could never call them); worker_status / cancel_worker give the
# interactive agent full monitor + stop control.
WORKER_CONTROL_TOOL_NAMES = frozenset({
    "delegate_to_worker",
    "worker_status",
    "cancel_worker",
})

WORKER_CONTROL_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "delegate_to_worker",
            "description": (
                "Hand a heavy or multi-step task to the background worker "
                "(scheduling meetings, creating/updating/deleting events or "
                "todos, building, researching, writing files, running commands, "
                "or anything needing many steps). Pass the FULL task in plain "
                "words. The worker runs in parallel; use worker_status to "
                "check it and tell the user when it finishes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Full task description, including all details the user gave (titles, times, names).",
                    },
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worker_status",
            "description": (
                "Check background worker jobs started with delegate_to_worker. "
                "Returns each job's id, task, and status "
                "(running, done, failed, cancelled). Call this when the user "
                "interrupts to ask whether the work is finished — 'is it done', "
                "'still going', 'how is it going' — and reassure them it is "
                "still running when that is the status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Optional job id to inspect. Empty checks all jobs.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_worker",
            "description": (
                "Stop a running background worker job. Call this when the user "
                "says stop, cancel, or never mind about delegated work. "
                "Pass the job_id from worker_status, or empty to stop the "
                "latest running job."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job id to stop. Empty stops the latest running job.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the job is being stopped (user asked, stale request, ...).",
                    },
                },
            },
        },
    },
]


def get_worker_control_tools() -> list[dict]:
    """Return the worker-control tool definitions (no MCP spawn, no secrets)."""
    return [dict(t) for t in WORKER_CONTROL_TOOL_DEFINITIONS]


def is_worker_control_tool(tool_name: str) -> bool:
    """True for delegate_to_worker / worker_status / cancel_worker."""
    return tool_name in WORKER_CONTROL_TOOL_NAMES

# Prefixes that ALWAYS escalate even if a same-named tool sneaks into the
# interactive set (multi-step / side-effecting / long-running families).
HEAVY_TOOL_PREFIXES = (
    "opencode_",
    "sandbox_",
    "Playwright_",
    "scaffold_",
    "visual_",
    "create_",
    "update_",
    "delete_",
    "add_",
    "generate_",
    "promote_",
    "import_",
    "extract_",
    "batch_",
    "export_",
)


def get_realtime_config() -> dict:
    """Return the `realtime:` config block (never includes secrets)."""
    cfg = load_config()
    rt = (cfg.get("realtime") or {}) if isinstance(cfg, dict) else {}
    return {
        "enabled": bool(rt.get("enabled", True)),
        "model": rt.get("model") or "gpt-realtime-2.1",
        "voice": rt.get("voice") or "marin",
        "relay_only": bool(rt.get("relay_only", True)),
        "max_minutes_per_session": int(rt.get("max_minutes_per_session", 15) or 15),
        "vad_threshold": float(rt.get("vad_threshold", 0.65) or 0.65),
        "vad_silence_duration_ms": int(rt.get("vad_silence_duration_ms", 600) or 600),
        "vad_prefix_padding_ms": int(rt.get("vad_prefix_padding_ms", 200) or 200),
    }


def get_realtime_api_key() -> str:
    """Resolve the server-side OpenAI key (realtime block falls back to openai block)."""
    cfg = load_config()
    rt = (cfg.get("realtime") or {}) if isinstance(cfg, dict) else {}
    oai = (cfg.get("openai") or {}) if isinstance(cfg, dict) else {}
    return (rt.get("api_key") or oai.get("api_key") or "").strip()


def realtime_status() -> dict:
    """JSON for GET /api/realtime/status. Text-only fallback when not ready."""
    conf = get_realtime_config()
    ready = bool(conf["enabled"] and get_realtime_api_key())
    reason = ""
    if not conf["enabled"]:
        reason = "realtime.enabled=false in config.yaml"
    elif not get_realtime_api_key():
        reason = "OPENAI_API_KEY missing (.env or config.yaml realtime.api_key)"
    return {
        "enabled": conf["enabled"],
        "ready": ready,
        "transport": "relay",
        "relay_only": conf["relay_only"],
        "webrtc": True,  # POST /api/realtime/calls + sideband WS are live (Stage 2)
        "model": conf["model"],
        "voice": conf["voice"],
        "fallback": "text-only",
        "reason": reason,
    }


def build_interactive_tools(all_tools: list[dict]) -> list[dict]:
    """Filter a full tool-definition list down to the interactive slice.

    Preserves the input order. Drops malformed entries defensively so one bad
    def can never 400 the whole session.update.
    """
    out = []
    for t in all_tools or []:
        try:
            fn = t.get("function", {}) if isinstance(t, dict) else {}
            name = fn.get("name", "")
            if name in INTERACTIVE_TOOL_NAMES:
                out.append(t)
        except Exception:
            continue
    return out


def needs_worker_escalation(tool_name: str) -> bool:
    """True when a realtime function call must go to the background worker."""
    if not tool_name:
        return True
    if tool_name in WORKER_CONTROL_TOOL_NAMES:
        # delegate/cancel are worker-lifecycle calls; status is answered from
        # local job state. All three are handled by the relay with state —
        # never by the generic inline dispatch path.
        return tool_name != "worker_status"
    if tool_name.startswith(HEAVY_TOOL_PREFIXES):
        return True
    return tool_name not in INTERACTIVE_TOOL_NAMES


def build_interactive_instructions() -> str:
    """Slim system instructions for the realtime session (fast voice, no build protocol)."""
    now = datetime.now(timezone.utc).astimezone().strftime("%A, %Y-%m-%d %H:%M %Z")
    try:
        personality = load_config().get("personality", {}) or {}
    except Exception:
        personality = {}
    tone = personality.get("default_tone", "warm, empathetic, and human")
    traits = ", ".join(personality.get("traits", []) or [])
    base = (
        "You are Mayday, a warm voice companion running on the user's desktop. "
        f"Current time: {now}. Tone: {tone}."
    )
    if traits:
        base += f" Traits: {traits}."
    base += (
        " Keep spoken replies to 1-3 short sentences. You have a small set of "
        "fast lookup tools (weather, todos, events, search, memory). For anything "
        "that needs scheduling, creating, updating, deleting, building, "
        "researching, writing files, running commands, or multiple steps, you "
        "MUST call delegate_to_worker with the full task in plain words — never "
        "claim you did it yourself and never ask the user to type it elsewhere. "
        "The worker runs in parallel in the background while you keep talking. "
        "If the user interrupts mid-job, disambiguate: status checks like "
        "'is it done', 'still going', 'how is it going' mean call worker_status "
        "and reassure them it is still running and you will tell them the moment "
        "it finishes — do NOT cancel. Only words like 'stop', 'cancel', or "
        "'never mind' mean call cancel_worker. When the worker finishes, "
        "proactively tell the user the outcome in warm human words even if they "
        "interrupted earlier — the worker gives you terse facts and you "
        "humanize them into 1-2 short sentences."
    )
    return base


def _turn_detection_config(cfg: dict) -> dict:
    """Server VAD block shared by relay session.update + WebRTC calls config.

    Tuned against speaker echo: a higher threshold + longer silence window
    means short TTS leakage is less likely to open a user turn, while real
    close-mic speech still triggers promptly. `interrupt_response` preserves
    barge-in (frontend re-opens the mic on speech_started).
    """
    return {
        "type": "server_vad",
        "threshold": cfg.get("vad_threshold", 0.65),
        "silence_duration_ms": cfg.get("vad_silence_duration_ms", 600),
        "prefix_padding_ms": cfg.get("vad_prefix_padding_ms", 200),
        "create_response": True,
        "interrupt_response": True,
    }


def _normalize_echo_text(text: str) -> str:
    import re
    import string
    t = (text or "").lower()
    t = t.translate(str.maketrans("", "", string.punctuation))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_echo_transcript(user_transcript: str, assistant_text: str) -> bool:
    """True when a freshly transcribed user turn looks like our own TTS echo.

    Used as a second line of defence behind the frontend half-duplex mic
    gate: if the assistant just said X and the mic hears X again while the
    `speaking` flag is set, drop it instead of feeding it to the worker.
    """
    u = _normalize_echo_text(user_transcript)
    a = _normalize_echo_text(assistant_text)
    if not u or not a:
        return False
    # Short fragments that appear verbatim inside what we just said.
    if len(u) <= 120 and (u in a or a in u):
        return True
    uw = u.split()
    aw = set(a.split())
    if not uw:
        return False
    # High word overlap with a short hearing vs a recent assistant turn.
    overlap = sum(1 for w in uw if w in aw) / max(len(uw), 1)
    return len(uw) <= 30 and overlap >= 0.7


def build_session_update(instructions: str, interactive_tools: list[dict]) -> dict:
    """Client event sent right after the relay connects to OpenAI."""
    cfg = get_realtime_config()
    realtime_tools = []
    for t in list(interactive_tools or []) + get_worker_control_tools():
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        realtime_tools.append({
            "type": "function",
            "name": fn.get("name", ""),
            "description": fn.get("description", "")[:500],
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": cfg["model"],
            "instructions": instructions,
            "audio": {
                "input": {"turn_detection": _turn_detection_config(cfg)},
                "output": {"voice": cfg["voice"]},
            },
            "tools": realtime_tools,
            "tool_choice": "auto",
        },
    }


async def mint_ephemeral_session(
    api_key: str,
    model: str,
    voice: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict:
    """Mint a short-lived client_secret for WebRTC-direct (Stage 2).

    Stage 1 relay does NOT call this (key stays server-side). Kept here so
    Stage 2 needs no new auth code — only the SDP endpoint + frontend switch.
    """
    payload = {"model": model, "voice": voice}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    close_after = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
        close_after = True
    try:
        # GA endpoint first (migration guide); legacy beta path as fallback.
        resp = await client.post(REALTIME_CLIENT_SECRET_URL, json=payload, headers=headers)
        if resp.status_code == 404:
            resp = await client.post(REALTIME_SESSION_URL, json=payload,
                                     headers=headers)
        resp.raise_for_status()
        data = resp.json()
        secret = ((data.get("client_secret") or {}).get("value")
                  if isinstance(data.get("client_secret"), dict)
                  else data.get("client_secret"))
        return {
            "client_secret": secret or "",
            "expires_at": (data.get("client_secret") or {}).get("expires_at", "")
            if isinstance(data.get("client_secret"), dict) else "",
            "model": data.get("model", model),
            "voice": voice,
            "raw": data,
        }
    finally:
        if close_after:
            try:
                await client.aclose()
            except Exception:
                pass


def parse_function_call_arguments(event: dict) -> tuple[str, str, dict]:
    """Extract (call_id, name, args) from a response.function_call_arguments.done event."""
    call_id = event.get("call_id", "") or event.get("item_id", "") or ""
    name = event.get("name", "") or ""
    raw = event.get("arguments", "{}")
    if isinstance(raw, dict):
        return call_id, name, raw
    try:
        args = json.loads(raw or "{}")
        return call_id, name, args if isinstance(args, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Realtime function call had non-JSON arguments for %s", name)
        return call_id, name, {}


def build_function_output_item(call_id: str, output: str) -> dict:
    """conversation.item.create event carrying a tool result back to the session."""
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": (output or "")[:8000],
        },
    }


def build_escalation_ack(tool_name: str) -> str:
    """Short spoken ack the interactive agent says before handing off to the worker."""
    return ("On it — that's a bigger job, so I'm handing it to my background "
            f"worker now ({tool_name}). I'll post progress in chat as it runs.")


def build_calls_session_config(instructions: str, interactive_tools: list[dict]) -> dict:
    """Session-config part of the WebRTC unified-interface multipart request."""
    cfg = get_realtime_config()
    realtime_tools = []
    for t in list(interactive_tools or []) + get_worker_control_tools():
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        realtime_tools.append({
            "type": "function",
            "name": fn.get("name", ""),
            "description": fn.get("description", "")[:500],
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return {
        "type": "realtime",
        "model": cfg["model"],
        "instructions": instructions,
        "audio": {
            "input": {"turn_detection": _turn_detection_config(cfg)},
            "output": {"voice": cfg["voice"]},
        },
        "tools": realtime_tools,
        "tool_choice": "auto",
    }


def parse_call_id(location: str) -> str:
    """Extract the call_id from a Realtime /calls Location header."""
    loc = (location or "").strip()
    if not loc:
        return ""
    tail = loc.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.startswith("rtc_") else ""
