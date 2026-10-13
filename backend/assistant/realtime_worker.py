"""Background worker for realtime voice escalations (Phase 2).

When the interactive realtime agent hits a heavy/multi-step tool, the relay
spawns a worker job: the full ``_run_engine`` tool loop (ToolRouter +
ToolSelector + MCP lazy tools + skills + project sandbox) running as an
asyncio background task. Progress events (token/tool_call/done/...) are
forwarded to the browser over the realtime socket wrapped as
``{"type": "worker_progress", "event": {...}}`` so the voice UI can render
them into chat exactly like /ws/chat traffic.

Design notes:
- One WorkerContext per realtime WS connection, built lazily on the first
  escalation. MCP servers are registered lazy-only — no subprocess spawns
  until a tool actually needs one (mirrors chat_websocket).
- One ConversationManager per JOB (not per connection) so concurrent
  escalations can't interleave messages. Cross-job context is carried in the
  job prompt (voice transcript + triggering tool call).
- The sender adapter satisfies chat._send_json's duck-type (send_json).
  All sends are best-effort: if the browser already hung up, the job still
  runs to completion in the background (results persist in stores/graph).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from backend.core.config import load_config

logger = logging.getLogger(__name__)

WORKER_SUMMARY_CHARS = 600
# Machine-format contract: the worker thinks in data, the interactive voice
# humanizes. FACTS are short lines for the speaker; HINT is one terse line.
WORKER_FACTS_MAX = 5
WORKER_HINT_CHARS = 150
# Progress throttle: coalesce token chatter so the browser gets milestones,
# not a WS message per token. Full text still accumulates for the summary.
WORKER_TOKEN_FLUSH_CHARS = 200


@dataclass
class WorkerContext:
    conv: object = None
    llm: object = None
    tools: list = field(default_factory=list)
    mcp: object = None
    kg: object = None
    selector: object = None
    router: object = None
    skill_manager: object = None
    query_classifier: object = None


async def build_worker_context() -> WorkerContext:
    """Build the engine context once per voice connection (lazy MCP, no eager connects)."""
    from backend.assistant.function_registry import get_tool_definitions
    from backend.assistant.mcp_manager import MCPManager
    from backend.assistant.memory.conversation_manager import ConversationManager
    from backend.assistant.llm_client import LLMClient
    from backend.assistant.playwright_tools import PLAYWRIGHT_TOOL_DEFINITIONS  # noqa: F401 (parity import)
    from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
    from backend.assistant.mcp_server_opencode import STATIC_TOOL_DEFINITIONS as OPENCODE_TOOL_DEFINITIONS
    from backend.assistant.function_registry import (
        DESIGN_MCP_TOOL_NAMES,  # noqa: F401 (parity import)
        UI_LAYOUTS_TOOL_DEFINITIONS, MAGIC_UI_TOOL_DEFINITIONS,
    )
    from backend.core.tool_router import ToolRouter
    from backend.core.tool_selector import ToolSelector
    from backend.core.query_classifier import QueryClassifier
    from backend.memory.knowledge_graph import get_graph
    from backend.api.chat import GROUP_SETS

    config = load_config()
    mcp = MCPManager()
    for name, cfg in (config.get("mcp", {}) or {}).get("servers", {}).items():
        try:
            # Voice sessions are transient: force EVERY server lazy so no
            # subprocess spawns until a tool actually needs one. On-demand
            # connect happens inside MCPManager._ensure_connected at call time.
            kwargs = dict(command=cfg["command"], args=cfg.get("args", []),
                          env=cfg.get("env"), lazy=True)
            await mcp.add_server_stdio(name, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Realtime worker: MCP server '%s' skipped: %s", name, e)
    for name in (config.get("mcp", {}) or {}).get("servers", {}):
        mcp_cfg = (config.get("mcp", {}) or {}).get("servers", {}).get(name, {})
        if mcp_cfg.get("lazy"):
            if name == "fetch":
                mcp.add_static_tools(name, FETCH_TOOL_DEFINITIONS)
            elif name == "opencode":
                mcp.add_static_tools(name, OPENCODE_TOOL_DEFINITIONS)
            elif name == "ui-layouts":
                mcp.add_static_tools(name, UI_LAYOUTS_TOOL_DEFINITIONS)
            elif name == "magic-ui":
                mcp.add_static_tools(name, MAGIC_UI_TOOL_DEFINITIONS)
    mcp_tools = []
    try:
        mcp_tools = await mcp.discover_tools()
    except Exception as e:
        logger.warning("Realtime worker: MCP discovery failed: %s", e)

    tools = get_tool_definitions(mcp_tools)
    tool_router = ToolRouter(GROUP_SETS)
    extended_groups = tool_router.extended_groups(tools)
    selector = ToolSelector()
    selector.build_index(tools, extended_groups)

    skill_manager = None
    if (config.get("skills", {}) or {}).get("enabled", True):
        try:
            from backend.assistant.skill_manager import get_skill_manager
            skill_manager = get_skill_manager(
                (config.get("skills", {}) or {}).get("directory", ""))
        except Exception as e:
            logger.warning("Realtime worker: skills unavailable: %s", e)

    return WorkerContext(
        conv=None,  # fresh ConversationManager per job (see run_worker_job)
        llm=LLMClient(),  # worker role by default
        tools=tools,
        mcp=mcp,
        kg=get_graph(),
        selector=selector,
        router=tool_router,
        skill_manager=skill_manager,
        query_classifier=QueryClassifier(),
    )


class RealtimeWorkerSender:
    """Duck-typed sender for chat._send_json: wraps engine events as worker_progress.

    Token chatter is coalesced: every token still accumulates into summary(),
    but the browser only gets one worker_progress message per
    WORKER_TOKEN_FLUSH_CHARS so long jobs don't flood the realtime socket.
    Milestones (tool_call, done, error, ...) always forward immediately.
    """

    def __init__(self, browser_ws):
        self._ws = browser_ws
        self.summary_parts: list[str] = []
        self.done = False
        self._pending = ""

    async def _forward(self, data: dict):
        try:
            await self._ws.send_json({"type": "worker_progress", "event": data})
        except Exception:
            pass  # browser gone — job continues in background

    async def _flush_tokens(self):
        if self._pending:
            pending, self._pending = self._pending, ""
            await self._forward({"type": "token", "content": pending})

    async def send_json(self, data: dict):
        if isinstance(data, dict) and data.get("type") == "token":
            content = data.get("content") or ""
            if content:
                self.summary_parts.append(content)
                self._pending += content
            if len("".join(self.summary_parts)) > WORKER_SUMMARY_CHARS * 4:
                # Bound memory on pathological streams; summary() truncates anyway.
                self.summary_parts = [ "".join(self.summary_parts)[-WORKER_SUMMARY_CHARS * 4:] ]
            if len(self._pending) >= WORKER_TOKEN_FLUSH_CHARS:
                await self._flush_tokens()
            return
        if isinstance(data, dict) and data.get("type") == "done":
            self.done = True
        # Milestone: flush any coalesced tokens first to preserve order.
        await self._flush_tokens()
        await self._forward(data)

    def summary(self) -> str:
        text = "".join(self.summary_parts).strip()
        if len(text) > WORKER_SUMMARY_CHARS:
            text = text[:WORKER_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
        return text


def build_worker_prompt(tool_name: str, args: dict, transcript: str) -> str:
    """Synthesize the engine prompt for an escalated voice tool call.

    The worker is the terse half of Mayday: it thinks in data, and the
    interactive voice agent humanizes. So the prompt bans pleasantries and
    demands a machine FACTS/HINT block at the end (cheap to parse, cheap in
    tokens) instead of a chatty prose report.
    """
    heard = f'"{transcript}"' if (transcript or "").strip() else "(no transcript captured)"
    try:
        args_json = json.dumps(args or {}, ensure_ascii=False)[:2000]
    except Exception:
        args_json = str(args)[:2000]
    return (
        "[Voice realtime handoff] The user spoke to Mayday by voice. "
        f"What was heard: {heard}. "
        f"The interactive agent determined this needs the tool '{tool_name}' "
        f"with arguments: {args_json}. "
        "Carry out the task fully with your tools. "
        "Reply TERSE MACHINE FORMAT: no greetings, no pleasantries, no filler. "
        "Do the work, then end with a FACTS block of 1-5 short lines "
        "(each <= 15 words, just outcomes/numbers/names) and one HINT line "
        f"(<= {WORKER_HINT_CHARS} chars, the single most user-relevant outcome). "
        "Format:\nFACTS:\n- <fact>\nHINT: <one line>"
    )


def extract_facts(summary: str, limit: int = WORKER_FACTS_MAX) -> list[str]:
    """Pull the FACTS block out of a worker summary (fallback: sentences)."""
    text = (summary or "").strip()
    if not text:
        return []
    facts: list[str] = []
    if "FACTS:" in text.upper():
        try:
            upper = text.upper()
            start = upper.index("FACTS:") + len("FACTS:")
            end = upper.index("HINT:", start) if "HINT:" in upper[start:] else len(text)
            block = text[start:end]
            for line in block.splitlines():
                line = line.strip().lstrip("-•*").strip()
                if line:
                    facts.append(line[:200])
                if len(facts) >= limit:
                    break
        except Exception:
            facts = []
    if not facts:
        # Fallback: first few sentences of whatever the worker said.
        import re
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
        facts = [p[:200] for p in parts[:limit]]
    return facts[:limit]


def extract_hint(summary: str) -> str:
    """Pull the HINT line out of a worker summary (fallback: first line)."""
    text = (summary or "").strip()
    if not text:
        return ""
    if "HINT:" in text.upper():
        try:
            hint = text.upper().split("HINT:", 1)[1].strip().splitlines()[0].strip()
            # Recover original casing from the raw text tail.
            idx = text.upper().rfind("HINT:")
            hint = text[idx + 5:].strip().splitlines()[0].strip()
            return hint[:WORKER_HINT_CHARS]
        except Exception:
            pass
    first = text.splitlines()[0].strip()
    return first[:WORKER_HINT_CHARS]


def build_machine_result(summary: str, tool_name: str,
                         status: str = "done") -> dict:
    """Structured worker result: status + facts + hint (one Mayday)."""
    facts = extract_facts(summary)
    hint = extract_hint(summary) or (f"Finished {tool_name}.")
    return {"status": status, "tool": tool_name, "facts": facts, "hint": hint}


async def run_worker_job(ctx: WorkerContext, browser_ws, tool_name: str,
                         args: dict, transcript: str, job_id: str = "") -> str:
    """Run one escalated job through the full engine loop. Returns a summary.

    job_id is echoed in the worker_done event so the interactive agent and
    the browser can match completion to the tracked job. Cancellation
    (asyncio.CancelledError from cancel_worker) propagates to the caller —
    it is NOT swallowed here — so the relay can report worker_cancelled.
    """
    from backend.api.chat import _run_engine
    from backend.assistant.memory.conversation_manager import ConversationManager

    conv = ConversationManager()
    try:
        conv.new_conversation()
    except Exception as e:
        logger.warning("Realtime worker: new_conversation failed: %s", e)
    sender = RealtimeWorkerSender(browser_ws)
    if job_id:
        try:
            await browser_ws.send_json({"type": "worker_started", "tool": tool_name,
                                        "job_id": job_id})
        except Exception:
            pass
    prompt = build_worker_prompt(tool_name, args, transcript)
    try:
        await _run_engine(
            sender, prompt, conv, ctx.llm, ctx.tools, ctx.mcp, ctx.kg,
            selector=ctx.selector, router=ctx.router,
            skill_manager=ctx.skill_manager,
            pending_suggestion=[], active_skill=[],
            query_classifier=ctx.query_classifier,
            humanize_output=False,
        )
    except asyncio.CancelledError:
        try:
            await browser_ws.send_json({"type": "worker_cancelled", "tool": tool_name,
                                        "job_id": job_id})
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception("Realtime worker job failed for %s", tool_name)
        try:
            await sender.send_json({"type": "error", "content": f"Worker failed: {e}"})
            await sender.send_json({"type": "done"})
        except Exception:
            pass
    summary = sender.summary() or f"Finished {tool_name}."
    result = build_machine_result(summary, tool_name, status="done")
    try:
        await browser_ws.send_json({"type": "worker_done", "tool": tool_name,
                                    "job_id": job_id,
                                    "summary": summary[:2000],
                                    "result": result})
    except Exception:
        pass
    return summary
