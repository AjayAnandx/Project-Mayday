from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log


def create_event(title: str, start_time: str, end_time: str,
                 description: str = "", all_day: bool = False) -> str:
    store = get_store()
    event = store.create_event(title, start_time, end_time, description, all_day)
    get_operation_log().record("create", "event", event["id"], event["title"])
    return f"Created event: {event['title']} (id: {event['id']})"


def update_event(event_id: str, **kwargs) -> str:
    store = get_store()
    event = store.update_event(event_id, **kwargs)
    if event:
        get_operation_log().record("update", "event", event_id, event["title"], details=kwargs)
        return f"Updated event: {event['title']} (id: {event['id']})"
    return f"Event {event_id} not found"


def delete_event(event_id: str) -> str:
    store = get_store()
    event = store.get_event(event_id)
    name = event["title"] if event else event_id
    if store.delete_event(event_id):
        get_operation_log().record("delete", "event", event_id, name)
        return f"Deleted event {event_id}"
    return f"Event {event_id} not found"


def list_events(start_date: str = None, end_date: str = None) -> str:
    store = get_store()
    events = store.list_events(start_date, end_date)
    if not events:
        return "No events found."
    lines = []
    for e in events:
        dates = f"{e['start_time']} → {e['end_time']}"
        all_day = " [All day]" if e.get("all_day") else ""
        lines.append(f"📅 {e['title']} — {dates}{all_day} ({e['id']})")
    return "\n".join(lines)


def query_events(query: str) -> str:
    store = get_store()
    events = store.list_events(query=query)
    if not events:
        return "No matching events found."
    lines = [f"📅 {e['title']} — {e['start_time']} ({e['id']})" for e in events]
    return "\n".join(lines)
