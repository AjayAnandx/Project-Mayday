import asyncio
import logging

from backend.core.data_store import get_store
from backend.functions.todo_functions import create_todo, update_todo, delete_todo, list_todos
from backend.functions.calendar_functions import create_event, update_event, delete_event, list_events, query_events
from backend.memory.memory_tools import remember, recall, recall_entity, forget

logger = logging.getLogger(__name__)

LOCAL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a new todo item",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Todo title"},
                    "description": {"type": "string", "description": "Optional description"},
                    "due_date": {"type": "string", "description": "Due date in ISO format"},
                    "priority": {"type": "integer", "description": "1=high, 2=medium, 3=low"},
                    "tags": {"type": "array", "items": {"type": "string"}},
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
            "description": "Create a new calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO format"},
                    "end_time": {"type": "string", "description": "End time in ISO format"},
                    "description": {"type": "string", "description": "Optional description"},
                    "all_day": {"type": "boolean", "description": "All day event"},
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
            "description": "Remove a specific memory fact",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject entity"},
                    "relation": {"type": "string", "description": "Relationship type"},
                    "value": {"type": "string", "description": "The object value or entity"},
                },
                "required": ["entity", "relation", "value"],
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
}


def get_tool_definitions(mcp_tools: list[dict] | None = None) -> list[dict]:
    tools = list(LOCAL_TOOL_DEFINITIONS)
    if mcp_tools:
        tools.extend(mcp_tools)
    return tools


async def dispatch_call(name: str, arguments: dict, mcp_manager=None) -> str:
    if name in FUNCTION_MAP:
        fn = FUNCTION_MAP[name]
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: fn(**arguments))
        except Exception as e:
            logger.exception("Error executing local function '%s'", name)
            return f"Error executing {name}: {e}"
    if mcp_manager is not None:
        return await mcp_manager.call_tool(name, arguments)
    return f"Unknown function: {name}"
