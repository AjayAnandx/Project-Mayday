import json
import asyncio
import logging
import os
import re
from datetime import date, timedelta, datetime

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.config import load_config
from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.assistant.llm_client import LLMClient
from backend.assistant.function_registry import dispatch_call, get_tool_definitions
from backend.assistant.mcp_manager import MCPManager
from backend.assistant.selenium_tools import SELENIUM_TOOL_DEFINITIONS
from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
from backend.assistant.memory.conversation_manager import ConversationManager
from backend.memory.knowledge_graph import get_graph, extract_keywords, KnowledgeGraph
from backend.api.screenshots import get_screenshot_store

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """You are Mayday, an AI personal assistant running on the user's desktop.
You help manage todos, calendar events, and answer questions conversationally.
You have git tools (git_log, git_status, git_diff, git_branch, git_commit, git_add, git_checkout) that call the local git CLI. ALWAYS pass "repo_path": "." for those.
You also have GitHub API tools — you can search repositories, list commits, read file contents, and get repo info on ANY public GitHub repo. Use owner/repo format (e.g. "facebook/react").
Do not say you lack access. You have the tools.
Be concise, helpful, and friendly. When you use a tool, explain what you did.
Current date: {date}"""

PERSONALITY_INSTRUCTIONS = """
### Personality
Tone: {tone}
Traits: {traits}
Rules: {rules}

### Auto-Learning
- If the user gives feedback about your behavior or style, call remember(entity="Mayday", relation="style_feedback", value="<feedback>", node_type="personality")
- Before responding, recall("style_feedback") to check for recent feedback
- Adapt your tone based on stored feedback
- Todos and events are auto-synced to the knowledge graph when created/updated/deleted
- Before creating a new todo, event, or entity, call recall() or recall_entity() first to check for existing data — this prevents duplicates
- Conversations are also synced to the knowledge graph as nodes — use recall_entity() on a conversation ID to find linked projects
### Forgetting / Deleting
- If the user asks to forget, delete, or remove a project, topic, or entity, call forget(entity="<name>") with ONLY the entity name (no relation/value needed). This will scrap the entire entity by setting its status to 'scraped'.
- Do NOT guess relation/value for forget(). Just pass the entity name alone.
- Scraped entities stay in the knowledge graph with status 'scraped'. You can find them with recall() or recall_entity(). Tell the user the entity is now scraped but can be reactivated with set_status().
- If the user wants to restore a scraped entity, call set_status(name="<entity>", status="active").
- If forget(entity="<name>") returns "No entity found", the entity might be stored with a "project:" or "tag:" prefix. Try forget(entity="project:<name>") or search with recall("<name>") first to find the exact label.
### Querying the Knowledge Graph
- When listing projects, call recall("project:") (with colon) - this finds only project-prefixed nodes and returns clean results.
- Do NOT use recall("project") (without colon) - it finds many irrelevant nodes.
- recall_entity("project:<name>") is best for getting a single project's full context.
- Only use recall("") with a specific query, not to get the entire graph.
### Operation Reporting
- After EVERY tool call, tell the user what you did: what was created/updated/deleted and what changed.
- For creates: state the title and type (todo/event/project/memory).
- For updates: state what fields changed and their new values.
- For deletes: state what was removed and confirm it's gone from both the data store and the knowledge graph.
- Example: "Created todo 'Buy milk' (high priority, due tomorrow). I also synced it to the knowledge graph."
- Example: "Updated todo 'Buy milk' - set priority from 1 to 2. Knowledge graph is also updated."
- Example: "Deleted project 'AGI Personal Assistant' — status set to 'scraped'. It can be reactivated with set_status() if needed."""

PROJECT_INSTRUCTIONS = """
### Project Tracking
- When starting a NEW project, link it by calling:
    remember(entity="project:<name>", relation="status", value="started", node_type="project")
- When RESUMING an existing project:
    1. recall_entity("project:<name>") to find the project and ALL linked conversations
    2. If the entity exists with status 'scraped', tell the user: "The project '<name>' was scrapped previously. Use set_status('project:<name>', 'active') to reactivate it."
    3. If the entity does not exist (returns "No entity found"), tell the user: "No project found with that name."
    4. Otherwise, call get_conversation_history(<conv_id>) for EACH linked conversation by ID
    5. Present a full summary: what was done, what was next, what to do now
- Update progress:
    remember(entity="project:<name>", relation="last_task", value="<what_was_done>", node_type="project")
    remember(entity="project:<name>", relation="next_task", value="<what_is_next>", node_type="project")
- To list all active projects, call recall("project:") (with colon) — this finds all project-prefixed nodes in the knowledge graph. Check each project's 'status' field to see if it's active, inactive, or scraped."""

CORE_TOOL_NAMES = {
    "create_todo", "update_todo", "delete_todo", "list_todos",
    "create_event", "update_event", "delete_event", "list_events", "query_events",
    "remember", "recall", "recall_entity", "forget", "delete_entity", "set_status",
    "get_conversations", "get_conversation_history",
    "list_screenshots", "get_screenshot", "delete_screenshot",
    "query_operations",
}

GIT_KEYWORDS = re.compile(r"\b(git|commit|branch|diff|log|status|staged|unstaged|push|pull|clone)\b", re.I)
GITHUB_KEYWORDS = re.compile(r"\b(github|repo|repository|issue|pr|pull\s*request|release|fork|star)\b", re.I)
BROWSER_KEYWORDS = re.compile(r"\b(browser|web|url|http|navigate|click|type|input|page|selenium|website|google)\b", re.I)
FETCH_KEYWORDS = re.compile(r"\b(fetch|curl|api\s*request)\b", re.I)

GIT_TOOL_NAMES = {
    "git_status", "git_diff_unstaged", "git_diff_staged", "git_diff",
    "git_commit", "git_add", "git_reset", "git_log",
    "git_create_branch", "git_checkout", "git_show", "git_branch",
}

GITHUB_TOOL_NAMES = {
    "create_branch", "create_or_update_file", "create_repository",
    "delete_file", "fork_repository", "get_commit", "get_file_contents",
    "get_latest_release", "get_me", "get_release_by_tag", "get_tag",
    "list_branches", "list_commits", "list_releases",
    "list_repository_collaborators", "list_tags", "push_files",
    "search_code", "search_commits", "search_repositories",
}

FETCH_TOOL_NAMES = {"fetch"}

SELENIUM_TOOL_NAMES = {
    "navigate", "get_an_element", "get_direct_children", "get_elements",
    "click_to_element", "set_value_to_input_element", "take_screenshot",
    "run_javascript_in_console", "run_javascript_and_get_console_output",
    "get_console_logs", "get_network_logs", "get_response",
    "get_style_an_element", "check_page_ready", "local_storage_add",
    "local_storage_read", "local_storage_remove", "local_storage_read_all",
    "local_storage_remove_all",
}


def filter_tools(text: str, all_tools: list[dict]) -> list[dict]:
    active_groups = {"core"}

    if GIT_KEYWORDS.search(text):
        active_groups.add("git")
    if GITHUB_KEYWORDS.search(text):
        active_groups.add("github")
    if BROWSER_KEYWORDS.search(text):
        active_groups.add("browser")
    if FETCH_KEYWORDS.search(text):
        active_groups.add("fetch")

    allowed = dict.fromkeys(CORE_TOOL_NAMES)
    if "git" in active_groups:
        allowed.update(dict.fromkeys(GIT_TOOL_NAMES))
    if "github" in active_groups:
        allowed.update(dict.fromkeys(GITHUB_TOOL_NAMES))
    if "browser" in active_groups:
        allowed.update(dict.fromkeys(SELENIUM_TOOL_NAMES))
    if "fetch" in active_groups:
        allowed.update(dict.fromkeys(FETCH_TOOL_NAMES))

    result = [t for t in all_tools if t["function"]["name"] in allowed]
    if len(result) < len(all_tools):
        filtered = len(all_tools) - len(result)
        exclude = [t["function"]["name"] for t in all_tools if t["function"]["name"] not in allowed]
        logger.debug("Filtered %d tools (excluded: %s)", filtered, exclude)
    return result


MAX_TOOL_RESULT_LENGTH = 3000

SKIP_SECOND_CALL = {
    # CRUD operations — result IS the answer
    "create_todo", "update_todo", "delete_todo",
    "create_event", "update_event", "delete_event",
    # Memory management
    "forget", "delete_entity", "set_status", "remember",
    # Screenshot delete
    "delete_screenshot",
    # Browser actions (not reads)
    "navigate", "click_to_element", "set_value_to_input_element",
    "take_screenshot", "run_javascript_in_console",
    "check_page_ready",
    "local_storage_add", "local_storage_read", "local_storage_remove",
    "local_storage_read_all", "local_storage_remove_all",
    # Git actions (not reads)
    "git_commit", "git_add", "git_reset",
    "git_create_branch", "git_checkout",
    # GitHub actions (not reads)
    "create_branch", "create_or_update_file", "create_repository",
    "delete_file", "fork_repository", "push_files",
}

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
    kg: KnowledgeGraph | None = None,
):
    system = SYSTEM_PROMPT.format(date=date.today().isoformat())

    _personality = load_config().get("personality", {})
    if _personality:
        system += PERSONALITY_INSTRUCTIONS.format(
            tone=_personality.get("default_tone", "neutral"),
            traits=", ".join(_personality.get("traits", [])),
            rules="\n".join(f"- {r}" for r in _personality.get("rules", [])),
        )
    system += PROJECT_INSTRUCTIONS

    if kg:
        keywords = extract_keywords(user_text)
        if keywords:
            query = " ".join(keywords)
            memories = [m for m in kg.search(query) if m.get("properties", {}).get("search_result") != "true"]
            memory_lines = ""
            if memories:
                memory_lines += "\n".join(f"- [{m['type']}] {m['label']}" for m in memories[:8])
            from backend.core.data_store import get_store as get_data_store
            store = get_data_store()
            q = query.lower()
            store_matches = []
            for t in store.list_todos(include_completed=True):
                if q in t["title"].lower() or q in t.get("description", "").lower():
                    store_matches.append(f"- [todo] {t['title']}")
            for e in store.list_events():
                if q in e["title"].lower() or q in e.get("description", "").lower():
                    store_matches.append(f"- [event] {e['title']}")
            if store_matches:
                if memory_lines:
                    memory_lines += "\n"
                memory_lines += "\n".join(store_matches[:4])
            if memory_lines:
                system += f"\n\n### Relevant memories:\n{memory_lines}\n###"

    HISTORY_KEYWORDS = re.compile(r"\b(delete|cancel|remov|yesterday|last\s*week|this\s*month|changed|created|operation|activity|log)\b", re.I)
    if HISTORY_KEYWORDS.search(user_text):
        ops = get_operation_log().query(limit=10)
        if ops:
            lines = ["### Recent operations:"]
            for op in ops:
                ts = op.get("timestamp", "")[:10]
                act = op.get("action", "")
                etype = op.get("entity_type", "")
                name = op.get("entity_name", "")
                lines.append(f"  [{ts}] {act} {etype} '{name}'")
            lines.append("###")
            system += "\n\n" + "\n".join(lines)

    conv.add_message("user", user_text)
    messages = [{"role": "system", "content": system}] + conv.get_context()

    loop = asyncio.get_running_loop()

    filtered_tools = filter_tools(user_text, tools)
    if len(filtered_tools) == 0:
        filtered_tools = tools

    try:
        def first_call(msgs):
            logger.info("Calling LLM with %d tools (filtered from %d): %s", len(filtered_tools), len(tools), [t["function"]["name"] for t in filtered_tools])
            resp = llm.chat(msgs, stream=False, tools=filtered_tools)
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
            if len(result) > MAX_TOOL_RESULT_LENGTH:
                result = result[:MAX_TOOL_RESULT_LENGTH] + "\n...[truncated]"
            conv.add_message("assistant", f"[Called {fn_name}] {result}")

            if kg and fn_name in ("create_todo", "update_todo", "delete_todo"):
                from backend.core.data_store import get_store as get_data_store
                store = get_data_store()
                if fn_name == "delete_todo":
                    kg.delete_todo_node(fn_args.get("todo_id", ""))
                elif fn_name == "create_todo":
                    m = re.search(r'\(id: ([a-f0-9]+)\)', result)
                    if m:
                        todo = store.get_todo(m.group(1))
                        if todo:
                            kg.sync_todo(todo)
                else:
                    todo_id = fn_args.get("todo_id", "")
                    if todo_id:
                        todo = store.get_todo(todo_id)
                        if todo:
                            kg.sync_todo(todo)

            if kg and fn_name in ("create_event", "update_event", "delete_event"):
                from backend.core.data_store import get_store as get_data_store
                store = get_data_store()
                if fn_name == "delete_event":
                    kg.delete_event_node(fn_args.get("event_id", ""))
                elif fn_name == "create_event":
                    m = re.search(r'\(id: ([a-f0-9]+)\)', result)
                    if m:
                        event = store.get_event(m.group(1))
                        if event:
                            kg.sync_event(event)
                else:
                    event_id = fn_args.get("event_id", "")
                    if event_id:
                        event = store.get_event(event_id)
                        if event:
                            kg.sync_event(event)

            tool_msg = {"type": "tool_call", "name": fn_name, "result": result}

            if fn_name == "take_screenshot":
                path_start = result.find("screenshot_")
                if path_start != -1:
                    raw_filename = result[path_start:].split()[0].rstrip(". \n")
                    store = get_screenshot_store()
                    src_path = os.path.join(os.path.dirname(__file__), "..", "..", raw_filename)
                    saved = store.add_screenshot(src_path)
                    if saved:
                        tool_msg["image_url"] = f"/screenshots/{saved}"

            if fn_name == "get_screenshot":
                try:
                    data = json.loads(result)
                    if "filename" in data:
                        tool_msg["image_url"] = f"/screenshots/{data['filename']}"
                except (json.JSONDecodeError, TypeError):
                    pass

            await _send_json(ws, tool_msg)

        skip = all(tc["function"]["name"] in SKIP_SECOND_CALL for tc in tool_calls)

        if not skip:
            messages = [{"role": "system", "content": system}] + conv.get_context()

            try:
                def second_call(msgs):
                    resp = llm.chat(msgs, stream=False, tools=[])
                    resp.raise_for_status()
                    return llm.extract_response(resp)

                content, _ = await loop.run_in_executor(None, second_call, messages)
            except Exception as e:
                logger.error(f"Second LLM call error: {e}")
                content = None

    if content:
        conv.add_message("assistant", content)
        await _send_json(ws, {"type": "token", "content": content})

    if kg and conv.current_id:
        conv_data = get_store().get_conversation(conv.current_id)
        if conv_data:
            kg.sync_conversation(conv_data)

    await _send_json(ws, {"type": "done"})


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    conv = ConversationManager()
    llm = LLMClient()
    conv.new_conversation()

    kg = get_graph()

    config = load_config()
    mcp_servers = config.get("mcp", {}).get("servers", {})
    mcp = MCPManager()
    if mcp_servers:
        for name, cfg in mcp_servers.items():
            if cfg.get("lazy"):
                try:
                    await mcp.add_server_stdio(
                        name,
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env"),
                        lazy=True,
                    )
                except Exception as e:
                    logger.error("Failed to register lazy MCP server '%s': %s", name, e)
            else:
                try:
                    await mcp.add_server_stdio(
                        name,
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env"),
                    )
                except Exception as e:
                    logger.error("Failed to connect MCP server '%s': %s", name, e)
    if mcp_servers:
        for name, cfg in mcp_servers.items():
            if cfg.get("lazy"):
                if name == "selenium":
                    mcp.add_static_tools(name, SELENIUM_TOOL_DEFINITIONS)
                elif name == "fetch":
                    mcp.add_static_tools(name, FETCH_TOOL_DEFINITIONS)
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
                await _run_engine(websocket, user_text, conv, llm, tools, mcp, kg)
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
