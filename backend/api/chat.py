import json
import asyncio
import logging
from datetime import date

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.config import load_config
from backend.core.data_store import get_store
from backend.assistant.llm_client import LLMClient
from backend.assistant.function_registry import dispatch_call, get_tool_definitions
from backend.assistant.mcp_manager import MCPManager
from backend.assistant.memory.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """You are Mayday, an AI personal assistant running on the user's desktop.
You help manage todos, calendar events, and answer questions conversationally.
You have git tools (git_log, git_status, git_diff, git_branch, git_commit, git_add, git_checkout) that call the local git CLI. ALWAYS pass "repo_path": "." for those.
You also have GitHub API tools — you can search repositories, list commits, read file contents, and get repo info on ANY public GitHub repo. Use owner/repo format (e.g. "facebook/react").
Do not say you lack access. You have the tools.
Be concise, helpful, and friendly. When you use a tool, explain what you did.
Current date: {date}"""

CONNECTION_HINT = (
    "Make sure Ollama is running locally (`ollama serve`), "
    "or update config.yaml with your cloud endpoint and API key."
)


async def _send_json(ws: WebSocket, data: dict):
    await ws.send_text(json.dumps(data))


async def _run_engine(
    ws: WebSocket,
    user_text: str,
    conv: ConversationManager,
    llm: LLMClient,
    tools: list[dict],
    mcp: MCPManager | None,
):
    system = SYSTEM_PROMPT.format(date=date.today().isoformat())
    conv.add_message("user", user_text)
    messages = [{"role": "system", "content": system}] + conv.get_context()

    loop = asyncio.get_running_loop()

    try:
        def first_call(msgs):
            logger.info("Calling LLM with %d tools: %s", len(tools), [t["function"]["name"] for t in tools])
            resp = llm.chat(msgs, stream=False, tools=tools)
            resp.raise_for_status()
            data = resp.json()
            logger.info("LLM response choices: %d", len(data.get("choices", [])))
            return llm.extract_response(resp)

        content, tool_calls = await loop.run_in_executor(None, first_call, messages)
    except httpx.ConnectError:
        await _send_json(ws, {"type": "error", "content": f"Cannot reach Ollama. {CONNECTION_HINT}"})
        await _send_json(ws, {"type": "done"})
        return
    except httpx.HTTPStatusError as e:
        await _send_json(ws, {"type": "error", "content": f"LLM returned HTTP {e.response.status_code}. Check your model and API key."})
        await _send_json(ws, {"type": "done"})
        return
    except Exception as e:
        await _send_json(ws, {"type": "error", "content": f"LLM error: {e}"})
        await _send_json(ws, {"type": "done"})
        return

    if tool_calls:
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"]["arguments"]
            if isinstance(fn_args, str):
                fn_args = json.loads(fn_args)
            result = await dispatch_call(fn_name, fn_args, mcp_manager=mcp)
            conv.add_message("assistant", f"[Called {fn_name}] {result}")
            await _send_json(ws, {
                "type": "tool_call",
                "name": fn_name,
                "result": result,
            })

        messages = [{"role": "system", "content": system}] + conv.get_context()

        try:
            def second_call(msgs):
                resp = llm.chat(msgs, stream=False, tools=tools)
                resp.raise_for_status()
                return llm.extract_response(resp)

            content, _ = await loop.run_in_executor(None, second_call, messages)
        except Exception as e:
            logger.error(f"Second LLM call error: {e}")
            content = None

    if content:
        conv.add_message("assistant", content)
        await _send_json(ws, {"type": "token", "content": content})

    await _send_json(ws, {"type": "done"})


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    conv = ConversationManager()
    llm = LLMClient()
    conv.new_conversation()

    config = load_config()
    mcp_servers = config.get("mcp", {}).get("servers", {})
    mcp = MCPManager()
    if mcp_servers:
        for name, cfg in mcp_servers.items():
            try:
                await mcp.add_server_stdio(
                    name,
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=cfg.get("env"),
                )
            except Exception as e:
                logger.error("Failed to connect MCP server '%s': %s", name, e)
    mcp_tools = []
    if mcp._sessions:
        try:
            mcp_tools = await mcp.discover_tools()
        except Exception as e:
            logger.error("MCP tool discovery error: %s", e)
    tools = get_tool_definitions(mcp_tools)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "message":
                user_text = msg.get("content", "")
                await _run_engine(websocket, user_text, conv, llm, tools, mcp)
            elif msg.get("type") == "new_conversation":
                conv.new_conversation()
                await _send_json(websocket, {"type": "conversation_created"})
            elif msg.get("type") == "load_conversation":
                conv_id = msg.get("conversation_id", "")
                if conv.load_conversation(conv_id):
                    conv_data = get_store().get_conversation(conv_id)
                    await _send_json(websocket, {
                        "type": "conversation_loaded",
                        "conversation": conv_data,
                    })
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await _send_json(websocket, {"type": "error", "content": str(e)})
        except Exception:
            pass
    finally:
        await mcp.close()
