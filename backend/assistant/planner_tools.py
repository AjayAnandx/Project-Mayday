"""OpenAI-format tool definitions for the Planner (see functions/planner_functions.py)."""

_WHEN = ("Pass the user's own words for relative dates ('friday', 'tomorrow 6pm', 'next monday 9am', "
         "'in 3 days') — the server resolves them exactly. Use 'YYYY-MM-DD' / 'YYYY-MM-DDTHH:MM' only for "
         "explicit calendar dates.")
_PRIORITY = {"type": "string", "enum": ["high", "medium", "low", "none"],
             "description": "Use the user's word: 'high' for high/urgent/important. Omit if not mentioned."}

_RECURRENCE = {
    "type": "object",
    "description": "Repeat rule. freq: daily|weekly|monthly|yearly; interval (every N); "
                   "byweekday [0=Mon..6=Sun] for weekly (e.g. weekdays=[0,1,2,3,4]); "
                   "bymonthday for monthly; until 'YYYY-MM-DD'; count; "
                   "repeat_from 'completion' to repeat N days after it's done.",
    "properties": {
        "freq": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
        "interval": {"type": "integer"},
        "byweekday": {"type": "array", "items": {"type": "integer"}},
        "bymonthday": {"type": "integer"},
        "until": {"type": "string"},
        "count": {"type": "integer"},
        "repeat_from": {"type": "string", "enum": ["due", "completion"]},
    },
    "required": ["freq"],
}

_REMINDERS = {
    "type": "array",
    "description": "Alerts before the due/start time, as minutes-before numbers (e.g. [60, 10]) "
                   "or absolute local times. Omit for defaults (events: 30 min before; "
                   "timed tasks: at due time). [] = no alerts.",
    "items": {},
}


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []},
    }}


_ITEM_REF = {"type": "string", "description": "Item id (preferred) or its exact title"}

PLANNER_TOOL_DEFINITIONS = [
    _fn("plan_add",
        "Add something to the user's planner: a task/todo, a calendar event (meeting, appointment), "
        "or a reminder. Supports due times, recurrence, reminders, lists, tags and priority. "
        "For things SOMEONE ELSE must do, use plan_delegate instead.",
        {
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": ["task", "event", "reminder"],
                     "description": "task (default) = something the user does; event = fixed-time "
                                    "calendar entry; reminder = a simple alert at a time"},
            "due": {"type": "string", "description": "When a task/reminder is due. " + _WHEN},
            "start": {"type": "string", "description": "Event start. " + _WHEN},
            "end": {"type": "string", "description": "Event end (default start + 1h). " + _WHEN},
            "notes": {"type": "string"},
            "list_name": {"type": "string", "description": "List/area, e.g. Home, Work, Errands"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "priority": _PRIORITY,
            "recurrence": _RECURRENCE,
            "reminders": _REMINDERS,
            "estimate_min": {"type": "integer", "description": "Expected minutes of work (used for time-blocking)"},
            "all_day": {"type": "boolean"},
            "force": {"type": "boolean", "description": "Create even if a same-title item exists that day"},
        }, ["title"]),
    _fn("plan_update",
        "Change a planner item: reschedule, rename, change priority/list/tags/recurrence/reminders, "
        "or set status (open/done/cancelled).",
        {
            "item_id": _ITEM_REF,
            "title": {"type": "string"},
            "due": {"type": "string", "description": _WHEN},
            "start": {"type": "string", "description": _WHEN},
            "end": {"type": "string", "description": _WHEN},
            "notes": {"type": "string"},
            "list_name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "priority": _PRIORITY,
            "recurrence": _RECURRENCE,
            "reminders": _REMINDERS,
            "estimate_min": {"type": "integer"},
            "status": {"type": "string", "enum": ["open", "done", "cancelled"]},
            "follow_up": {"type": "string", "description": "Waiting items: when to chase. " + _WHEN},
            "clear_due": {"type": "boolean", "description": "Remove the due date"},
        }, ["item_id"]),
    _fn("plan_complete",
        "Mark a task/reminder/waiting item done (recurring ones roll to their next date). "
        "done=false reopens it.",
        {"item_id": _ITEM_REF, "done": {"type": "boolean"}}, ["item_id"]),
    _fn("plan_delete", "Permanently delete a planner item (task, event, reminder or waiting item).",
        {"item_id": _ITEM_REF}, ["item_id"]),
    _fn("plan_list",
        "Read the planner. Views: today (due/overdue tasks + today's events), upcoming (next `days`), "
        "inbox (undated tasks), waiting (things others owe the user), done, all, "
        "calendar (needs start/end). Filter by query, list, tag or person.",
        {
            "view": {"type": "string", "enum": ["today", "upcoming", "inbox", "waiting", "done", "all", "calendar"]},
            "query": {"type": "string", "description": "Text search"},
            "list_name": {"type": "string"},
            "tag": {"type": "string"},
            "person": {"type": "string", "description": "Only items involving this person"},
            "start": {"type": "string", "description": "calendar view range start"},
            "end": {"type": "string", "description": "calendar view range end"},
            "days": {"type": "integer", "description": "upcoming window (default 14)"},
        }),
    _fn("plan_snooze", "Snooze an item's alert for N minutes or until a time.",
        {"item_id": _ITEM_REF, "minutes": {"type": "integer"}, "until": {"type": "string", "description": _WHEN}},
        ["item_id"]),
    _fn("plan_schedule",
        "Time-block a task into the calendar (start, optional end; default length = estimate or 30 min). "
        "Empty start removes the block.",
        {"item_id": _ITEM_REF, "start": {"type": "string", "description": _WHEN},
         "end": {"type": "string", "description": _WHEN}}, ["item_id", "start"]),
    _fn("plan_delegate",
        "Track work SOMEONE ELSE owes the user ('Ravi will send the deck by Friday', 'waiting on the "
        "landlord'). Creates a waiting-on item; Mayday reminds the user to follow up and can draft a chase email.",
        {
            "title": {"type": "string", "description": "What they owe, e.g. 'Send the Q3 deck'"},
            "person": {"type": "string", "description": "Who owes it"},
            "due": {"type": "string", "description": "Only when the user gives a deadline ('by Friday'). "
                    "Leave empty otherwise. " + _WHEN},
            "follow_up": {"type": "string", "description": "When the user says 'follow up / check in / chase on X', put X here verbatim (e.g. 'friday'). Default: due date 09:00, else 3 days. " + _WHEN},
            "notes": {"type": "string"},
            "email": {"type": "string", "description": "Their email, saved for follow-up drafts"},
        }, ["title", "person"]),
    _fn("plan_people",
        "Manage the user's people directory and see who owes what. action: list | add | update | show "
        "(show = what they owe the user and what the user owes them).",
        {
            "action": {"type": "string", "enum": ["list", "add", "update", "show"]},
            "name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
            "relation": {"type": "string", "description": "e.g. colleague, client, family"},
            "notes": {"type": "string"},
        }),
    _fn("plan_nudge",
        "Draft (NOT send) a polite follow-up email to the person a waiting item is on. "
        "Show the draft to the user; send only after explicit approval.",
        {"item_id": _ITEM_REF}, ["item_id"]),
    _fn("plan_day",
        "Propose a time-blocked plan for a day: fits open tasks (overdue first) into free gaps "
        "between events. Returns proposals only — confirm with the user, then plan_schedule each.",
        {"date": {"type": "string", "description": "YYYY-MM-DD (default today)"},
         "day_start": {"type": "string", "description": "HH:MM (default 09:00)"},
         "day_end": {"type": "string", "description": "HH:MM (default 18:00)"}}),
]

PLANNER_TOOL_NAMES = frozenset(t["function"]["name"] for t in PLANNER_TOOL_DEFINITIONS)

# Pre-V2 tools: still dispatchable (stale history, voice worker), no longer advertised.
RETIRED_PLANNER_TOOLS = frozenset({
    "create_todo", "update_todo", "delete_todo", "list_todos",
    "create_event", "update_event", "delete_event", "list_events", "query_events",
    "create_reminder", "list_reminders", "delete_reminder",
})
