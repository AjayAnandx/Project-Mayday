"""Brain V2 P5: clearer descriptions for the tools a personal assistant confuses most.

Form: what it does. Use when … Don't use when … (use X instead). Example.
Applied on top of the original definitions (copies; the originals are untouched).
Add an entry here when the tool log shows a tool being chosen wrongly.
"""
from __future__ import annotations

import copy

OVERRIDES: dict[str, str] = {
    "recall": (
        "Search Mayday's long-term memory about the user (people, preferences, facts, decisions, ideas). "
        "Use when the user asks what you know or remember about someone or something ('what did Kiran say "
        "about the trip', 'what's my sister's birthday'). Don't use for tasks/events (plan_list) or "
        "past chat transcripts by date (get_conversations). Example: recall(query='Kiran trip')."),
    "remember": (
        "Store a durable fact about the user or someone they know. Use only when the user explicitly asks "
        "you to remember something ('remember that…'); ordinary facts are captured automatically. "
        "Don't use for tasks or reminders (plan_add) or research results (add_finding)."),
    "forget": (
        "Delete a memory or a whole entity. Use when the user says something you remember is wrong or asks "
        "you to forget it. Don't use to complete or delete tasks (plan_complete / plan_delete)."),
    "unified_search": (
        "One search across tasks, events, conversations, memories and the activity log. Use when the user "
        "is looking for something and you don't know where it lives ('find that thing about the invoice'). "
        "Prefer recall for facts about people, plan_list for today's plan."),
    "get_conversations": (
        "List past conversations from one date (YYYY-MM-DD). Use when the user refers to a day ('what did "
        "we discuss yesterday'). Don't use to look up facts (recall)."),
    "get_conversation_history": (
        "Load the messages of one past conversation by its id (from get_conversations or a project). "
        "Use to continue or quote an earlier conversation."),
    "query_operations": (
        "Search the log of things created, updated or deleted (tasks, events, projects…), by action, type "
        "or date. Use for 'what did I delete last week', 'when did I create X'."),
    "get_weather": (
        "Current weather and forecast for a city (default: the user's city). Use for weather, rain, umbrella, "
        "temperature or 'should I go out' questions. Don't use web search for weather."),
    "open_application": (
        "Open a desktop application by name ('open spotify', 'launch zoom'). Searches Start menu, registry "
        "and Program Files. Don't use for files or web pages."),
    "close_application": "Close a running desktop application by name ('close chrome').",
    "set_volume": (
        "Set the system volume 0-100. Use for 'too loud' (lower by ~20), 'louder', 'mute' (0), "
        "'volume 40'. Check get_volume first when the change is relative."),
    "get_volume": "Read the current system volume (0-100). Use before a relative change ('a bit louder').",
    "search_pdfs": (
        "Search the text of the user's uploaded PDFs. Use when the user asks what a document says "
        "('what does my offer letter say about notice period'). Then read_pdf for the full text."),
    "read_pdf": "Read the text of one uploaded PDF by doc_id/pdf_id (find it with search_pdfs or list_pdfs).",
    "resume_project": (
        "Load a project's full state (tasks, notes, files, history) to continue working on it. Use for "
        "'let's continue with X', 'back to X'. Don't use to list projects (list_projects)."),
    "list_projects": (
        "List the user's projects with status. Use for 'what am I working on', 'my projects'. "
        "To work on one, call resume_project."),
}


def apply_overrides(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        name = t.get("function", {}).get("name", "")
        if name in OVERRIDES:
            t = copy.deepcopy(t)
            t["function"]["description"] = OVERRIDES[name]
        out.append(t)
    return out
