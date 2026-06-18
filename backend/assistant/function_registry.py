import asyncio
import logging

from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.functions.todo_functions import create_todo, update_todo, delete_todo, list_todos
from backend.functions.calendar_functions import create_event, update_event, delete_event, list_events, query_events
from backend.functions.reminder_functions import create_reminder, list_reminders, delete_reminder
from backend.memory.memory_tools import remember, recall, recall_entity, forget, delete_entity, set_status
from backend.api.screenshots import list_screenshots, get_screenshot_info, delete_screenshot_file

logger = logging.getLogger(__name__)


def get_conversations_from_store(date: str) -> str:
    convs = get_store().list_conversations(date=date)
    if not convs:
        return f"No conversations found on {date}."
    lines = [f"Conversations on {date}:"]
    for c in convs:
        title = c.get("title", "Untitled")
        count = c.get("message_count", 0)
        lines.append(f"  - {title} ({count} messages, id: {c['id']})")
    return "\n".join(lines)


TOOL_KEYWORDS = (
    "create_todo", "update_todo", "delete_todo", "list_todos",
    "create_event", "update_event", "delete_event", "list_events",
    "remember", "recall", "recall_entity", "forget",
    "get_conversations", "get_conversation_history",
)


def get_conversation_history_from_store(conversation_id: str, limit: int = 5) -> str:
    store = get_store()
    conv = store.get_conversation(conversation_id)
    if not conv:
        return f"Conversation not found: {conversation_id}"
    msgs = store.get_recent_messages(conversation_id, limit=limit)
    if not msgs:
        return f"Conversation '{conv.get('title', 'Untitled')}' ({conversation_id}) has no messages."

    tool_counts: dict[str, int] = {}
    for m in msgs:
        c = m.get("content", "")
        for kw in TOOL_KEYWORDS:
            if kw in c:
                tool_counts[kw] = tool_counts.get(kw, 0) + 1

    first = msgs[0]
    last = msgs[-1]

    parts = [f"=== Previous Session: \"{conv.get('title', 'Untitled')}\" ==="]
    parts.append(f"ID: {conversation_id} — {len(msgs)} messages")
    if tool_counts:
        parts.append("Tools: " + ", ".join(f"{k} ({v}x)" for k, v in sorted(tool_counts.items())))
    first_text = first.get("content", "")[:150]
    parts.append(f"First: {first.get('role')}: {first_text}")
    if last is not first:
        last_text = last.get("content", "")[:150]
        parts.append(f"Last:  {last.get('role')}: {last_text}")
    return "\n".join(parts)


def query_operations_from_log(action: str | None = None, entity_type: str | None = None,
                               date_from: str | None = None, date_to: str | None = None,
                               query: str | None = None) -> str:
    log = get_operation_log()
    results = log.query(action=action, entity_type=entity_type,
                        date_from=date_from, date_to=date_to, query=query, limit=20)
    if not results:
        return "No matching operations found."
    lines = [f"Found {len(results)} operation(s):"]
    for op in results:
        ts = op.get("timestamp", "")[:16]
        action = op.get("action", "")
        etype = op.get("entity_type", "")
        name = op.get("entity_name", "")
        msg = op.get("user_message", "")
        lines.append(f"  [{ts}] {action} {etype} '{name}'")
        if msg:
            lines.append(f"    user said: {msg[:120]}")
    return "\n".join(lines)


def unified_search(query: str) -> str:
    from backend.api.search import unified_search as search_api
    result = search_api(q=query, limit=10)
    parts = []
    if result["todos"]:
        parts.append("📋 Todos:\n" + "\n".join(f"  - {t['title']} ({t['id']})" for t in result["todos"]))
    if result["events"]:
        parts.append("📅 Events:\n" + "\n".join(f"  - {e['title']} ({e['snippet']})" for e in result["events"]))
    if result["conversations"]:
        parts.append("💬 Conversations:\n" + "\n".join(f"  - {c['title']} ({c['date']})" for c in result["conversations"]))
    if result["graph_nodes"]:
        parts.append("🧠 Memories:\n" + "\n".join(f"  - [{n['type']}] {n['label']}" for n in result["graph_nodes"]))
    if result["operations"]:
        parts.append("📜 Operations:\n" + "\n".join(f"  - [{o['timestamp'][:10]}] {o['action']} {o['entity_type']} '{o['entity_name']}'" for o in result["operations"]))
    if not parts:
        return f"No results found for: {query}"
    return "\n\n".join(parts)


LOCAL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a new todo item. If duplicate detection warns you, set force=True to bypass the check and create anyway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Todo title"},
                    "description": {"type": "string", "description": "Optional description"},
                    "due_date": {"type": "string", "description": "Due date in ISO format"},
                    "priority": {"type": "integer", "description": "1=high, 2=medium, 3=low"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "force": {"type": "boolean", "description": "Set to true to bypass duplicate detection and create anyway"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule for repeating todos",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer", "description": "Every N units (default 1)"},
                            "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                            "count": {"type": "integer", "description": "Maximum occurrences"},
                        },
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update an existing todo",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "Todo ID"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_date": {"type": "string"},
                    "priority": {"type": "integer"},
                    "completed": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule. Set to null to remove recurrence.",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer"},
                            "end_date": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Delete a todo",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {"type": "string", "description": "Todo ID"},
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "List all todos, optionally filter",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_completed": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a new calendar event. If duplicate detection warns you, set force=True to bypass the check and create anyway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO format"},
                    "end_time": {"type": "string", "description": "End time in ISO format"},
                    "description": {"type": "string", "description": "Optional description"},
                    "all_day": {"type": "boolean", "description": "All day event"},
                    "force": {"type": "boolean", "description": "Set to true to bypass duplicate detection and create anyway"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule for repeating events",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer", "description": "Every N units (default 1)"},
                            "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                            "count": {"type": "integer", "description": "Maximum occurrences"},
                        },
                    },
                },
                "required": ["title", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Update an existing event",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "description": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule. Set to null to remove recurrence.",
                        "properties": {
                            "pattern": {"type": "string", "enum": ["daily", "weekly", "biweekly", "monthly", "yearly"]},
                            "interval": {"type": "integer"},
                            "end_date": {"type": "string"},
                            "count": {"type": "integer"},
                        },
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Delete an event",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List events, optionally filtered by date range",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in ISO format"},
                    "end_date": {"type": "string", "description": "End date in ISO format"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_events",
            "description": "Search events by keyword",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a fact or relationship in long-term memory",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject entity"},
                    "relation": {"type": "string", "description": "Relationship type (e.g. prefers, mentions, relates_to)"},
                    "value": {"type": "string", "description": "The object value or entity"},
                    "context": {"type": "string", "description": "Optional context for disambiguation"},
                    "node_type": {"type": "string", "description": "Node type for the entity (concept, personality, project, tag, date). Default: concept"},
                },
                "required": ["entity", "relation", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Search memory for any information matching a query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_entity",
            "description": "Get all information stored about a specific entity",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove a memory (entity, relationship, or entire entity). Pass only 'entity' to remove the entire entity and all its connections. Pass entity+relation+value to remove a specific relationship edge. If you are unsure of the relation/value, pass only entity — it will remove everything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject entity to forget or remove"},
                    "relation": {"type": "string", "description": "Relationship type (optional — omit to remove entire entity)"},
                    "value": {"type": "string", "description": "The object value or entity (optional — omit to remove entire entity)"},
                },
                "required": ["entity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_entity",
            "description": "Set an entity's status to 'scraped'. The entity stays in the knowledge graph and can be reactivated later with set_status(). Use when the user wants to remove, abandon, or scrap a project/concept.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact name of the entity to scrap"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_status",
            "description": "Change an entity's status between 'active', 'inactive', and 'scraped'. Use 'scraped' to abandon an entity, 'inactive' to pause it, 'active' to reactivate it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact name of the entity"},
                    "status": {"type": "string", "enum": ["active", "inactive", "scraped"], "description": "New status value"},
                },
                "required": ["name", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversations",
            "description": "Retrieve conversations from a specific date to recall past discussions. Use when the user asks about a previous conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversation_history",
            "description": "Retrieve a summary of a past conversation by ID. Returns title, message count, tools used, and first/last messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "The conversation ID to retrieve (use recall_entity on a project to find linked conversation IDs).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent messages to return (default 20).",
                    },
                },
                "required": ["conversation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_screenshots",
            "description": "List all stored screenshots with timestamps. Use this to find past screenshots to show the user.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_screenshot",
            "description": "Get metadata for a specific screenshot by filename. The image will be displayed in the chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Screenshot filename (e.g. screenshot_20260617_114042.png)"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_screenshot",
            "description": "Permanently delete a screenshot file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Screenshot filename to delete"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_operations",
            "description": "Search the history of all create/update/delete operations across todos, events, conversations, projects, and memory entities. Use when the user asks about past activity like deleted items, cancellations, or changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update", "delete"], "description": "Filter by action type (optional)"},
                    "entity_type": {"type": "string", "description": "Filter by entity type: todo, event, conversation, project, concept (optional)"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD (optional)"},
                    "query": {"type": "string", "description": "Full-text search in entity name or user message (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unified_search",
            "description": "Search across all Mayday data (todos, events, conversations, memories, operations) at once. Use this when the user asks a broad question like 'find that thing about the API' or 'what did I do with X' instead of guessing which specific store to search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Set a reminder that will fire as a desktop notification at the specified time. Use 24-hour format for the time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Reminder message"},
                    "datetime": {"type": "string", "description": "ISO datetime string (YYYY-MM-DDTHH:MM) when the reminder should fire"},
                },
                "required": ["message", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List all pending reminders that haven't fired yet.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete a pending reminder by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Reminder ID to delete"},
                },
                "required": ["reminder_id"],
            },
        },
    },
]

FUNCTION_MAP = {
    "create_todo": create_todo,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "list_todos": list_todos,
    "create_event": create_event,
    "update_event": update_event,
    "delete_event": delete_event,
    "list_events": list_events,
    "query_events": query_events,
    "remember": remember,
    "recall": recall,
    "recall_entity": recall_entity,
    "forget": forget,
    "delete_entity": delete_entity,
    "set_status": set_status,
    "get_conversations": get_conversations_from_store,
    "get_conversation_history": get_conversation_history_from_store,
    "list_screenshots": list_screenshots,
    "get_screenshot": get_screenshot_info,
    "delete_screenshot": delete_screenshot_file,
    "query_operations": query_operations_from_log,
    "unified_search": unified_search,
    "create_reminder": create_reminder,
    "list_reminders": list_reminders,
    "delete_reminder": delete_reminder,
}


def get_tool_definitions(mcp_tools: list[dict] | None = None) -> list[dict]:
    tools = list(LOCAL_TOOL_DEFINITIONS)
    if mcp_tools:
        tools.extend(mcp_tools)
    return tools


async def dispatch_call(name: str, arguments: dict, mcp_manager=None) -> str:
    if name in FUNCTION_MAP:
        fn = FUNCTION_MAP[name]
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, lambda: fn(**arguments))
        except Exception as e:
            logger.exception("Error executing local function '%s'", name)
            return f"Error executing {name}: {e}"
    if mcp_manager is not None:
        return await mcp_manager.call_tool(name, arguments)
    return f"Unknown function: {name}"
