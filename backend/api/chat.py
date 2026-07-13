import json
import asyncio
import logging
import os
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.config import load_config
from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.assistant.llm_client import LLMClient
from backend.assistant.function_registry import dispatch_call, get_tool_definitions
from backend.assistant.mcp_manager import MCPManager
from backend.assistant.selenium_tools import SELENIUM_TOOL_DEFINITIONS
from backend.assistant.exa_tools import EXA_TOOL_DEFINITIONS
from backend.assistant.fetch_tools import FETCH_TOOL_DEFINITIONS
from backend.assistant.mcp_server_opencode import STATIC_TOOL_DEFINITIONS as OPENCODE_TOOL_DEFINITIONS
from backend.assistant.skill_manager import get_skill_manager, SkillManager
from backend.assistant.memory.conversation_manager import ConversationManager
from backend.memory.knowledge_graph import get_graph, extract_keywords, KnowledgeGraph
from backend.api.screenshots import get_screenshot_store
from backend.core.tool_selector import ToolSelector

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """You are Mayday, an AI personal assistant running on the user's desktop.
You help manage todos, calendar events, and answer questions conversationally.
You have git tools (git_log, git_status, git_diff, git_branch, git_commit, git_add, git_checkout) that call the local git CLI. ALWAYS pass "repo_path": "." for those.
You also have GitHub API tools — you can search repositories, list commits, read file contents, and get repo info on ANY public GitHub repo. Use owner/repo format (e.g. "facebook/react").
You also have web search tools available:
- web_search_exa and web_search_advanced_exa: ALWAYS AVAILABLE. Use these for complex research, news, finding information on the web, company research, academic papers, etc.
- web_fetch_exa (Exa): ALWAYS AVAILABLE. Use for fetching full article content, documentation pages, or any URL where you need rich/extracted content.
- fetch (simple): Available when user mentions "fetch" or "curl". Use this for simple URL-to-markdown fetches. For complex content extraction, use web_fetch_exa instead.
Rule of thumb: complex → Exa tools, simple URL fetch → fetch tool.
Do not say you lack access. You have the tools.
Be concise, helpful, and friendly. When you use a tool, explain what you did.
Current date and time (your local timezone): {date}"""

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

WEATHER_INSTRUCTIONS = """
### Proactive Weather
- get_weather(location, days) returns current conditions + forecast.
- When the user mentions a meeting, event, trip, or outdoor plan at a specific location and date, YOU MUST proactively call get_weather() for that location to check conditions.
- If the location is a neighborhood or area, include the city name (e.g. "Anna Nagar, Chennai").
- get_weather() without a location uses the user's stored location.
- Only mention weather in your response if the forecast data covers the relevant date. If the forecast doesn't reach that date, say nothing about weather."""

PROJECT_INSTRUCTIONS = """
### Project Tracking
- You have dedicated project tools: create_project, resume_project, list_projects, update_project_status, add_project_note, add_project_task, update_task_status, list_project_tasks. Use these instead of remember/recall for projects.
- When RESUME is called, resume_project(name) returns full project state (status, files, conversations, graph edges, task progress). If fuzzy match succeeds it says "Found it!" — otherwise it suggests similar names.
- To LIST active projects, call list_projects(status="active"). Filters: active, paused, scrapped.
- To UPDATE status, call update_project_status(name, status). Valid statuses: active, paused, scrapped.
- To add research notes, call add_project_note(name, filename, content). This writes a .md to the project folder.
- Projects auto-pause after 30 days of no activity.
- Conversation IDs are auto-linked to the project — no need to call remember() for that.
- To BUILD code, use opencode tools (opencode_write, opencode_bash, opencode_read, opencode_edit, opencode_glob, opencode_grep).

### Task Lifecycle
- add_project_task(project, title, type, depends_on, description): Add a task. Type options: research, general, build. ALWAYS include a description (problem/goal statement) for research tasks.
- update_task_status(project, task_id, status, result): Transition through pending → in_progress → completed | blocked | failed.
  Use task_id (preferred) or task_title (fallback) to identify the task.
  For blocked/failed, set status and explain why. For completed, include a result summary.
- list_project_tasks(project, status): View tasks. Use status filter (in_progress, pending, etc.) to focus.
- When status transitions to "completed", check get_active_task for what to do next.
- When a task type is 'research', the research skill will be auto-loaded. When type is 'build', the build skill will be auto-loaded.
- CRITICAL: After EVERY opencode tool call (opencode_write, opencode_bash, opencode_read, opencode_edit, opencode_glob, opencode_grep), you MUST call update_task_status() to mark progress — 'completed' on success, 'blocked' or 'failed' on error.
- After EVERY project/task tool call, tell the user what happened.
- IMPORTANT: Do NOT ask the user for permission or confirmation between steps. Collect all the information you need upfront, then execute autonomously. The user has already given you full authority to execute project tasks. Just inform them of what you're doing and the results."""

BUILD_MODE_INSTRUCTIONS = """
### Build Mode — Iterative Project Building
When the user asks you to build, create, make, scaffold, or set up a project:
1. Collect all requirements upfront — ask clarifying questions once, then proceed.
2. Plan — briefly describe your approach.
3. Create — use opencode_bash (mkdir, git init, npm init) and opencode_write to create files.
4. Install — run dependency installers (npm install, pip install, etc.).
5. Code — write the actual source files.
6. Test — run the test command (npm test, pytest, etc.).
7. Fix — if tests fail, read the error output, fix the code, and re-run tests.
8. Complete — when ALL tests pass, stop calling tools and describe what was built.
You can think out loud between tool calls. Your intermediate thoughts will be shown to the user in real-time.
Never call the same tool with the same arguments more than 3 times. If you are stuck, explain the issue instead of repeating.
CRITICAL: Do NOT ask the user "can I proceed?", "should I continue?", or "do you approve?" between steps. Once you understand the requirements, execute everything autonomously. Just inform the user of progress and results."""

RESEARCH_MODE_INSTRUCTIONS = """
### Research Mode — Comprehensive Multi-Source Investigation
When the user says "research &lt;topic&gt;", "investigate", "find out about", "look into", or asks a complex factual question:

1. DEFINE — Create a project (or resume if exists) and add a research task with a clear "description" field that captures the problem/goal.
2. BREAK DOWN — For complex topics, split into sub-tasks with dependencies (depends_on). Each sub-task gets its own goal definition.
3. SEARCH WIDELY — Run multiple search queries to cover different angles, terminology, and perspectives. Do NOT stop after one search — use 3-5 different queries to surface diverse sources. Search across documentation, news, articles, forums, academic sources, and competitor analysis.
4. FOLLOW LEADS — When you find a promising source, use web_fetch_exa to read it in full. Extract key findings, citations, and references. Follow those references too (snowball search).
5. FIND RELATED CONCEPTS — Actively look for related technologies, alternatives, dependencies, and context around the topic. The user wants the complete picture, not just a direct answer.
6. DOCUMENT — Save structured findings via add_project_note (creates .md files in the project folder). Each major subtopic gets its own note.
7. ANALYZE — Connect insights across sources. Identify patterns, contradictions, gaps, and open questions. Note what's well-established vs what's disputed.
8. CONCLUDE — Summarize all findings. Update the task as completed with a result summary that covers key discoveries and any remaining open questions.
9. ITERATE — If new questions or leads emerge during research, add follow-up tasks automatically.

- Always include a description (goal/problem statement) when creating research tasks.
- For complex research: break into multiple sub-tasks with depends_on so each piece can be tackled in order.
- After each sub-task completes, check what's next via list_project_tasks or get_active_task.
- Document findings as .md files in the project folder so results persist.
- CRITICAL: Thorough research means multiple queries, multiple sources, following cross-references. A single search is never enough."""

SKILL_DESCRIPTIONS_TEMPLATE = """
### Available Skills
When a user's request matches one of the skills below, call suggest_skill() to offer it:
{descriptions}"""

CORE_TOOL_NAMES = {
    "create_todo", "update_todo", "delete_todo", "list_todos",
    "create_event", "update_event", "delete_event", "list_events", "query_events",
    "remember", "recall", "recall_entity", "forget", "delete_entity", "set_status",
    "get_conversations", "get_conversation_history",
    "list_screenshots", "get_screenshot", "delete_screenshot",
    "query_operations",
    "unified_search",
    "create_reminder", "list_reminders", "delete_reminder",
    "web_search_exa", "web_fetch_exa", "web_search_advanced_exa",
    # Project tools (always available)
    "create_project", "resume_project", "list_projects",
    "update_project_status", "add_project_note",
    "add_project_task", "update_task_status", "list_project_tasks",
    # System commands
    "open_application", "close_application",
    "set_volume", "get_volume",
    "copy_to_clipboard",
    "get_system_info", "get_active_window",
    # File access
    "read_file", "write_file", "append_file", "list_directory",
    "get_weather",
    "opencode_bash", "opencode_write", "opencode_read",
    "opencode_edit", "opencode_glob", "opencode_grep",
    "opencode_stop",
    # Screenshot tools
    "capture_page_screenshot",
    # Skill suggestion
    "suggest_skill",
}

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

SELENIUM_TOOL_NAMES = {
    "navigate", "get_an_element", "get_direct_children", "get_elements",
    "click_to_element", "set_value_to_input_element", "take_screenshot",
    "run_javascript_in_console", "run_javascript_and_get_console_output",
    "get_console_logs", "get_network_logs", "get_response",
    "get_style_an_element", "check_page_ready", "local_storage_add",
    "local_storage_read", "local_storage_remove", "local_storage_read_all",
    "local_storage_remove_all",
}

FETCH_TOOL_NAMES = {"fetch"}

OPENCODE_TOOL_NAMES = {
    "opencode_bash", "opencode_write", "opencode_read",
    "opencode_edit", "opencode_glob", "opencode_grep",
    "opencode_stop",
}

GROUP_SETS = {
    "core": CORE_TOOL_NAMES,
    "git": GIT_TOOL_NAMES,
    "github": GITHUB_TOOL_NAMES,
    "browser": SELENIUM_TOOL_NAMES,
    "fetch": FETCH_TOOL_NAMES,
    "opencode": OPENCODE_TOOL_NAMES,
    "skill": set(),
}


MAX_TOOL_RESULT_LENGTH = 50000

_BUILD_REQUEST_KEYWORDS = re.compile(r"\b(build|create|make|scaffold|init|set up)\b", re.I)

CONNECTION_HINT = (
    "Make sure Ollama is running locally (`ollama serve`), "
    "or update config.yaml with your cloud endpoint and API key."
)


async def _send_json(ws: WebSocket, data: dict):
    await ws.send_text(json.dumps(data))


def _make_voice_text(text: str) -> str:
    stripped = text
    stripped = re.sub(r'```[\s\S]*?```', '', stripped)
    stripped = re.sub(r'`([^`]+)`', r'\1', stripped)
    stripped = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', stripped)
    stripped = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', stripped)
    stripped = re.sub(r'^#{1,6}\s+', '', stripped, flags=re.M)
    stripped = re.sub(r'\*\*([^*]+)\*\*', r'\1', stripped)
    stripped = re.sub(r'\*([^*]+)\*', r'\1', stripped)
    stripped = re.sub(r'__([^_]+)__', r'\1', stripped)
    stripped = re.sub(r'~~([^~]+)~~', r'\1', stripped)
    stripped = re.sub(r'^>\s+', '', stripped, flags=re.M)
    stripped = re.sub(r'^[*-]\s+', '', stripped, flags=re.M)
    stripped = re.sub(r'^\d+\.\s+', '', stripped, flags=re.M)
    stripped = re.sub(r'^[-*_]{3,}\s*$', '', stripped, flags=re.M)
    stripped = re.sub(r'<[^>]*>', '', stripped)
    stripped = re.sub(r'\n+', '. ', stripped)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    sentences = re.split(r'(?<=[.!?:;])\s+', stripped)
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        if len(stripped) > 200:
            return stripped[:200].rsplit(' ', 1)[0] + '. Check the chat for more details.'
        return stripped[:300] if stripped else ""
    short = ' '.join(sentences[:2])
    if len(sentences) == 1 and len(short) > 200:
        short = short[:200].rsplit(' ', 1)[0] + '. Check the chat for more details.'
    elif len(sentences) > 2:
        short = short.rstrip('.!?:;') + '. Check the chat for more details.'
    if len(short) > 300:
        short = short[:300].rsplit(' ', 1)[0] + '. Check the chat for more details.'
    return short


def _build_active_project_block():
    from backend.core.project_store import get_project_store
    store = get_project_store()
    active_projects = store.list_projects(status="active")
    if not active_projects:
        return ""
    lines = ["### Active Projects"]
    for p in active_projects[:5]:
        tasks = p.get("tasks", [])
        done = sum(1 for t in tasks if t["status"] == "completed")
        total = len(tasks)
        progress = f"{done}/{total}" if total else "no tasks"
        active_task = store.get_active_task(p["id"])
        next_line = f" — next: {active_task['title']}" if active_task else ""
        lines.append(f"- {p['name']} ({progress}){next_line}")
    lines.append("###")
    return "\n".join(lines)


def _auto_load_skill_for_active_task(kg, active_skill, skill_manager):
    if not kg or not skill_manager:
        return
    if active_skill and active_skill[0]:
        return
    from backend.core.project_store import get_project_store
    store = get_project_store()
    active_projects = store.list_projects(status="active")
    if not active_projects:
        return
    for p in active_projects:
        task = store.get_active_task(p["id"])
        if task:
            skill = skill_manager.get_skill_by_task_type(task["type"])
            if skill:
                active_skill.append(skill)
                logger.info("Auto-loaded skill '%s' for task '%s'", skill.name, task["title"])
                return


async def _run_engine(
    ws: WebSocket,
    user_text: str,
    conv: ConversationManager,
    llm: LLMClient,
    tools: list[dict],
    mcp: MCPManager | None,
    kg: KnowledgeGraph | None = None,
    selector: ToolSelector | None = None,
    skill_manager: SkillManager | None = None,
    pending_suggestion: list | None = None,
    active_skill: list | None = None,
):
    now = datetime.now(timezone.utc).astimezone()
    system = SYSTEM_PROMPT.format(
        date=now.strftime("%A, %Y-%m-%d %H:%M:%S %Z (%z)")
    )

    _personality = load_config().get("personality", {})
    if _personality:
        system += PERSONALITY_INSTRUCTIONS.format(
            tone=_personality.get("default_tone", "neutral"),
            traits=", ".join(_personality.get("traits", [])),
            rules="\n".join(f"- {r}" for r in _personality.get("rules", [])),
        )
    system += WEATHER_INSTRUCTIONS
    system += PROJECT_INSTRUCTIONS
    system += BUILD_MODE_INSTRUCTIONS
    system += RESEARCH_MODE_INSTRUCTIONS

    if skill_manager:
        descs = skill_manager.get_skill_descriptions()
        if descs:
            system += SKILL_DESCRIPTIONS_TEMPLATE.format(descriptions=descs)

    active_block = _build_active_project_block()
    if active_block:
        system += "\n\n" + active_block

    if active_skill and active_skill[0]:
        skill = active_skill[0]
        system += f"\n\n### Active Skill: {skill.name}\n{skill.body}\n###"
    elif kg and not (active_skill and active_skill[0]):
        _auto_load_skill_for_active_task(kg, active_skill, skill_manager)

    if kg:
        keywords = extract_keywords(user_text)
        if keywords and len(keywords) >= 2:
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

    if selector is not None:
        allowed_names = selector.select_tool_names(user_text)
        filtered_tools = [t for t in tools if t["function"]["name"] in allowed_names]
        if len(filtered_tools) == 0:
            filtered_tools = tools
    else:
        filtered_tools = tools

    if active_skill and skill_manager:
        skill = active_skill[0]
        body, skill_tool_defs, skill_func_map = skill_manager.apply_skill(skill.name)
        for sd in skill_tool_defs:
            if sd not in filtered_tools:
                filtered_tools.append(sd)

    try:
        def first_call(msgs):
            logger.info("Calling LLM with %d tools (filtered from %d): %s", len(filtered_tools), len(tools), [t["function"]["name"] for t in filtered_tools])
            resp = llm.chat(msgs, stream=False, tools=filtered_tools)
            resp.raise_for_status()
            data = resp.json()
            logger.info("LLM response choices: %d", len(data.get("choices", [])))
            return llm.extract_response(resp)

        content, tool_calls = await loop.run_in_executor(None, first_call, messages)
    except asyncio.CancelledError:
        logger.info("WebSocket client disconnected during first LLM call")
        return
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

    MAX_ITERATIONS = 20
    DUPLICATE_LIMIT = 3
    seen_calls: list[tuple] = []
    opencode_used = False
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1

        if iteration > 1:
            try:
                def llm_call(msgs):
                    resp = llm.chat(msgs, stream=False, tools=filtered_tools)
                    resp.raise_for_status()
                    return llm.extract_response(resp)
                content, tool_calls = await loop.run_in_executor(None, llm_call, messages)
            except asyncio.CancelledError:
                logger.info("WebSocket client disconnected during iterative tool loop")
                break
            except httpx.ConnectError:
                await _send_json(ws, {"type": "error", "content": f"Cannot reach Ollama. {CONNECTION_HINT}"})
                break
            except httpx.HTTPStatusError as e:
                await _send_json(ws, {"type": "error", "content": f"LLM returned HTTP {e.response.status_code}. Check your model and API key."})
                break
            except Exception as e:
                await _send_json(ws, {"type": "error", "content": f"LLM error: {e}"})
                break

        if not tool_calls:
            break

        conv.add_message("assistant", content or "", tool_calls=tool_calls)

        if content and content.strip():
            await _send_json(ws, {"type": "token", "content": content})

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"]["arguments"]
            tool_call_id = tc.get("id", f"call_{iteration}_{fn_name}")

            if isinstance(fn_args, str):
                fn_args = json.loads(fn_args)

            if fn_name == "suggest_skill":
                skill_name = fn_args.get("name", "")
                if skill_manager and skill_manager.get_skill(skill_name):
                    skill = skill_manager.get_skill(skill_name)
                    if active_skill is not None:
                        active_skill.clear()
                        active_skill.append(skill)
                    body, skill_tool_defs, _ = skill_manager.apply_skill(skill_name)
                    for sd in skill_tool_defs:
                        if sd not in filtered_tools:
                            filtered_tools.append(sd)
                    system += f"\n\n### Active Skill: {skill.name}\n{body}\n###"
                    await _send_json(ws, {
                        "type": "skill_activated",
                        "name": skill_name,
                    })
                    result = f"Auto-activated skill '{skill_name}' for this task."
                else:
                    avail = skill_manager.list_skills() if skill_manager else []
                    result = f"Skill '{skill_name}' not found. Available: {', '.join(avail)}"
                conv.add_message("tool", result, tool_call_id=tool_call_id)
                await _send_json(ws, {"type": "tool_call", "name": fn_name, "result": result})

            if fn_name == "capture_page_screenshot":
                url = fn_args.get("url", "")
                if not url:
                    result = "Error: No URL provided."
                else:
                    try:
                        await mcp.call_tool("navigate", {"url": url})
                    except Exception as e:
                        result = f"navigate error: {e}"
                        tool_msg = {"type": "tool_call", "name": fn_name, "result": result}
                        await _send_json(ws, tool_msg)
                        conv.add_message("tool", result, tool_call_id=tool_call_id)
                        continue
                    await asyncio.sleep(1.5)
                    ss_dir = os.path.join(os.path.dirname(__file__), "..", "..", "screenshots")
                    os.makedirs(ss_dir, exist_ok=True)
                    try:
                        ss_result = await mcp.call_tool("take_screenshot", {"save_path": ss_dir})
                    except Exception as e:
                        result = f"screenshot error: {e}"
                        tool_msg = {"type": "tool_call", "name": fn_name, "result": result}
                        await _send_json(ws, tool_msg)
                        conv.add_message("tool", result, tool_call_id=tool_call_id)
                        continue
                    import re as _scr
                    _scr_match = _scr.search(r"Screenshot saved to (.+\.png)", ss_result)
                    ss_path = _scr_match.group(1) if _scr_match else ""
                    if ss_path and os.path.exists(ss_path):
                        ss_store = get_screenshot_store()
                        saved = ss_store.add_screenshot(ss_path)
                        if saved:
                            tool_msg = {
                                "type": "tool_call", "name": fn_name,
                                "result": f"Screenshot captured at {url}",
                                "image_url": f"/screenshots/{saved}",
                            }
                            await _send_json(ws, tool_msg)
                            conv.add_message("tool", f"Screenshot captured at {url}", tool_call_id=tool_call_id)
                            seen_calls.append((fn_name, json.dumps(fn_args, sort_keys=True), ""))
                            continue
                    result = "Screenshot taken but could not be registered in store."

            if fn_name in OPENCODE_TOOL_NAMES:
                opencode_used = True

            result = await dispatch_call(fn_name, fn_args, mcp_manager=mcp)
            if len(result) > MAX_TOOL_RESULT_LENGTH:
                result = result[:MAX_TOOL_RESULT_LENGTH] + "\n...[truncated]"

            if fn_name == "update_task_status" and skill_manager and not (active_skill and active_skill[0]):
                new_status = fn_args.get("status", "")
                if new_status == "in_progress":
                    task_title = fn_args.get("task_title", "")
                    proj_name = fn_args.get("name", "")
                    if proj_name:
                        from backend.core.project_store import get_project_store
                        pstore = get_project_store()
                        project = pstore.find_project_by_name(proj_name)
                        if project:
                            target_task = None
                            for t in project.get("tasks", []):
                                if t["id"] == fn_args.get("task_id", ""):
                                    target_task = t
                                    break
                                if task_title and t["title"].lower() == task_title.lower():
                                    target_task = t
                                    break
                            if target_task:
                                skill = skill_manager.get_skill_by_task_type(target_task["type"])
                                if skill:
                                    if active_skill is not None:
                                        active_skill.clear()
                                        active_skill.append(skill)
                                        logger.info("Point B: Auto-loaded skill '%s' for task '%s'", skill.name, target_task["title"])

            args_hash = json.dumps(fn_args, sort_keys=True)
            result_head = result[:100]
            call_key = (fn_name, args_hash, result_head)
            seen_calls.append(call_key)
            dup_count = sum(1 for c in seen_calls if c == call_key)
            if dup_count >= DUPLICATE_LIMIT:
                result = f"[Stuck after {dup_count} identical attempts] {result}"
                content = "I got stuck — the same action repeated with the same result."
                tool_calls = None
                await _send_json(ws, {"type": "tool_call", "name": fn_name, "result": result})
                break

            conv.add_message("tool", result, tool_call_id=tool_call_id)

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
                import re as _re
                _path_match = _re.search(r"Screenshot saved to (.+\.png)", result)
                if _path_match:
                    src_path = _path_match.group(1)
                else:
                    _start = result.find("screenshot_")
                    if _start != -1:
                        src_path = result[_start:].split()[0].rstrip(". \n")
                    else:
                        src_path = ""
                if src_path and os.path.exists(src_path):
                    ss_store = get_screenshot_store()
                    saved = ss_store.add_screenshot(src_path)
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

        if not tool_calls:
            break

        messages = [{"role": "system", "content": system}] + conv.get_context()

        if iteration >= MAX_ITERATIONS:
            content = (content or "") + "\n\n[Reached maximum iterations — the build may be incomplete.]"

    if not content:
        messages = [{"role": "system", "content": system}] + conv.get_context()
        try:
            def final_call(msgs):
                resp = llm.chat(msgs, stream=False, tools=[])
                resp.raise_for_status()
                return llm.extract_response(resp)
            summary, _ = await loop.run_in_executor(None, final_call, messages)
            if summary:
                content = summary
        except asyncio.CancelledError:
            logger.info("WebSocket client disconnected during final summary")
        except Exception as e:
            logger.error("Final summary call failed: %s", e)

    if content:
        voice_text = _make_voice_text(content)
        logger.info("Voice: ui=%d chars, voice=%d chars", len(content), len(voice_text))
        conv.add_message("assistant", content)
        await _send_json(ws, {"type": "token", "content": content, "voice_content": voice_text})

    if kg and conv.current_id:
        conv_data = get_store().get_conversation(conv.current_id)
        if conv_data:
            kg.sync_conversation(conv_data)
        from backend.core.project_store import get_project_store
        pstore = get_project_store()
        active_projects = pstore.list_projects(status="active")
        for proj in active_projects:
            if conv.current_id not in proj.get("conversation_ids", []):
                pstore.link_conversation(proj["id"], conv.current_id)
                logger.info("Auto-linked conversation %s to project '%s'", conv.current_id, proj["name"])

    if active_skill and not tool_calls:
        active_skill.clear()
        await _send_json(ws, {"type": "skill_deactivated"})

    if opencode_used and _BUILD_REQUEST_KEYWORDS.search(user_text) and content:
        from backend.core.scheduler import get_scheduler
        get_scheduler().fire_notification(
            title="Build Complete",
            body=content[:200],
            category="event_reminder",
        )

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
            try:
                kwargs = dict(command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env"))
                if cfg.get("lazy"):
                    kwargs["lazy"] = True
                await mcp.add_server_stdio(name, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Failed to connect MCP server '%s': %s", name, e)
    if mcp_servers:
        for name, cfg in mcp_servers.items():
            if cfg.get("lazy"):
                if name == "selenium":
                    mcp.add_static_tools(name, SELENIUM_TOOL_DEFINITIONS)
                elif name == "exa":
                    mcp.add_static_tools(name, EXA_TOOL_DEFINITIONS)
                elif name == "fetch":
                    mcp.add_static_tools(name, FETCH_TOOL_DEFINITIONS)
                elif name == "opencode":
                    mcp.add_static_tools(name, OPENCODE_TOOL_DEFINITIONS)
    mcp_tools = []
    if mcp._sessions:
        try:
            mcp_tools = await mcp.discover_tools()
        except Exception as e:
            logger.error("MCP tool discovery error: %s", e)
    tools = get_tool_definitions(mcp_tools)

    selector = ToolSelector()
    selector.build_index(tools, GROUP_SETS)
    logger.info("ToolSelector built index for %d tools in %d groups",
                len(tools), len(GROUP_SETS))

    skill_manager = None
    skills_cfg = config.get("skills", {})
    if skills_cfg.get("enabled", True):
        try:
            skill_manager = get_skill_manager(skills_cfg.get("directory", ""))
            logger.info("Loaded %d skills", len(skill_manager.list_skills()))
        except Exception as e:
            logger.error("Failed to load skills: %s", e)

    pending_suggestion: list = []
    active_skill: list = []

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "message":
                user_text = msg.get("content", "")
                await _run_engine(websocket, user_text, conv, llm, tools, mcp, kg,
                                  selector=selector, skill_manager=skill_manager,
                                  pending_suggestion=pending_suggestion,
                                  active_skill=active_skill)
            elif msg.get("type") == "confirm_skill":
                skill_name = msg.get("name", "")
                if skill_manager:
                    body, skill_tool_defs, func_map = skill_manager.apply_skill(skill_name)
                    if body:
                        pending_suggestion.clear()
                        skill = skill_manager.get_skill(skill_name)
                        if active_skill:
                            active_skill.clear()
                            active_skill.append(skill)
                        await _send_json(websocket, {
                            "type": "skill_activated",
                            "name": skill_name,
                        })
                        await _run_engine(websocket, f"Activate skill: {skill_name}", conv, llm, tools, mcp, kg,
                                          selector=selector, skill_manager=skill_manager,
                                          pending_suggestion=pending_suggestion,
                                          active_skill=active_skill)
                    else:
                        await _send_json(websocket, {"type": "error", "content": f"Skill '{skill_name}' not found"})
                pending_suggestion.clear()
            elif msg.get("type") == "dismiss_skill":
                pending_suggestion.clear()
                if active_skill:
                    active_skill.clear()
                    await _send_json(websocket, {"type": "skill_deactivated"})
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
    except asyncio.CancelledError:
        logger.info("WebSocket task cancelled (client disconnected)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await _send_json(websocket, {"type": "error", "content": str(e)})
        except Exception:
            pass
    finally:
        await mcp.close()
