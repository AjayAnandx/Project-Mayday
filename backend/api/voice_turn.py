import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core.config import load_config
from backend.assistant.memory.conversation_manager import ConversationManager
from backend.assistant.llm_client import LLMClient
from backend.memory.knowledge_graph import get_graph
from backend.assistant.mcp_manager import MCPManager
from backend.assistant.function_registry import (
    get_tool_definitions,
    UI_LAYOUTS_TOOL_DEFINITIONS,
    MAGIC_UI_TOOL_DEFINITIONS,
)
from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
from backend.assistant.mcp_server_opencode import (
    STATIC_TOOL_DEFINITIONS as OPENCODE_TOOL_DEFINITIONS,
)
from backend.core.tool_selector import ToolSelector
from backend.core.query_classifier import QueryClassifier
from backend.assistant.skill_manager import get_skill_manager
from backend.api.chat import _run_engine, _run_interactive_only, _build_engine_context
from backend.assistant.tiers import tiering_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _check_token(request: Request) -> bool:
    """Return True if the request is authorized. Empty configured token = open
    (dev). When a token is configured it must match the ?token= param."""
    expected = (load_config().get("voice", {}) or {}).get("cloudflare_token", "") or ""
    if not expected:
        return True
    return request.query_params.get("token", "") == expected


class _VoiceStream:
    """Bridges _run_engine (which expects a `ws` with an async send_text) to a
    streaming HTTP response. Speakable text is delivered through the `sink`
    callback; the dummy ws interface just satisfies _send_json so the engine
    can run unchanged."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def send_text(self, _s: str):
        # _send_json calls ws.send_text(json.dumps(data)). The JSON protocol is
        # ignored here — speakable text arrives via sink().
        return

    async def sink(self, text: str):
        if text:
            await self.queue.put(text)

    async def close(self):
        await self.queue.put(None)


@router.post("/turn")
async def voice_turn(request: Request):
    if not _check_token(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid body"}, status_code=400)

    transcript = (body.get("transcript") or "").strip()
    if not transcript:
        return JSONResponse({"error": "empty transcript"}, status_code=400)

    ctx = await _build_engine_context()
    stream = _VoiceStream()

    async def _run_and_close():
        try:
            intent = ctx["query_classifier"].classify(transcript)
            if tiering_enabled() and not intent.requires_llm:
                await _run_interactive_only(
                    stream, transcript, ctx["conv"], sink=stream.sink
                )
            else:
                await _run_engine(
                    stream,
                    transcript,
                    ctx["conv"],
                    ctx["llm"],
                    ctx["tools"],
                    ctx["mcp"],
                    kg=ctx["kg"],
                    selector=ctx["selector"],
                    skill_manager=ctx["skill_manager"],
                    pending_suggestion=ctx["pending_suggestion"],
                    active_skill=ctx["active_skill"],
                    query_classifier=ctx["query_classifier"],
                    humanize_output=ctx["humanize_output"],
                    sink=stream.sink,
                )
        except Exception as e:
            logger.exception("Voice turn failed: %s", e)
        finally:
            try:
                await ctx["mcp"].close()
            except Exception:
                pass
            await stream.close()

    # Run the engine as a background task; stream speakable text as it's produced.
    asyncio.create_task(_run_and_close())

    async def event_gen():
        while True:
            item = await stream.queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(event_gen(), media_type="text/plain; charset=utf-8")


@router.post("/sync")
async def voice_sync(request: Request):
    if not _check_token(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid body"}, status_code=400)

    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"ok": True, "note": "nothing to sync"})

    conv = ConversationManager()
    conv.new_conversation(f"Voice {datetime.now().strftime('%Y-%m-%d')}")
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            conv.add_message(role, content)

    # Mirror REST conversation creation: persist into the knowledge graph.
    try:
        from backend.core.data_store import get_store
        data = get_store().get_conversation(conv.current_id)
        if data:
            get_graph().sync_conversation(data)
    except Exception as e:
        logger.warning("Voice sync graph sync failed: %s", e)

    return JSONResponse({"ok": True, "conversation_id": conv.current_id})
