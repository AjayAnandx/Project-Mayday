from backend.core.user_awareness import get_awareness_store


def get_person_brief(name: str, max_chars: int = 400) -> str:
    """Return Mayday's aggregated, free-form brief about a named person.

    Assembles the relationship type, first/last mentioned dates, source chats,
    any linked situational notes, and personal notes that reference them.
    """
    return get_awareness_store().person_brief(name, max_chars=max_chars)


def list_people() -> list[dict]:
    """Return every person Mayday has learned about, with their brief."""
    store = get_awareness_store()
    people = []
    for b in store.list_beliefs(slot="relations"):
        name = b["value"]
        people.append({
            "name": name,
            "relation_type": b.get("relation_type") or "relation",
            "brief": store.person_brief(name),
            "confidence": b.get("confidence", 0.0),
        })
    return people
