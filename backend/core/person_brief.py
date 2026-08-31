from backend.core.user_awareness import get_awareness_store


def get_person_brief(name: str, max_chars: int = 400) -> str:
    """Return Mayday's aggregated, free-form brief about a named person.

    Assembles the relationship type, first/last mentioned dates, source chats,
    any linked situational notes, and personal notes that reference them.
    Sourced from the shared knowledge graph (single source of truth).
    """
    return get_awareness_store().person_brief(name, max_chars=max_chars)


def list_people() -> list[dict]:
    """Return every person Mayday has learned about, with their brief."""
    return get_awareness_store().list_people()
