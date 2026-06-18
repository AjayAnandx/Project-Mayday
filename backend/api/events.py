from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/events", tags=["events"])


class EventCreate(BaseModel):
    title: str
    start_time: str
    end_time: str
    description: str = ""
    all_day: bool = False


class EventUpdate(BaseModel):
    title: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    all_day: Optional[bool] = None


@router.get("")
def list_events(start_date: str = "", end_date: str = "", q: str = ""):
    store = get_store()
    return store.list_events(
        start_date=start_date or None,
        end_date=end_date or None,
        query=q,
    )


@router.get("/{event_id}")
def get_event(event_id: str):
    store = get_store()
    event = store.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", status_code=201)
def create_event(body: EventCreate):
    store = get_store()
    event = store.create_event(**body.model_dump())
    get_graph().sync_event(event)
    get_operation_log().record("create", "event", event["id"], event["title"])
    return event


@router.put("/{event_id}")
def update_event(event_id: str, body: EventUpdate):
    store = get_store()
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    event = store.update_event(event_id, **kwargs)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    get_graph().sync_event(event)
    get_operation_log().record("update", "event", event_id, event["title"], details=kwargs)
    return event


@router.delete("/{event_id}")
def delete_event(event_id: str):
    store = get_store()
    event = store.get_event(event_id)
    name = event["title"] if event else event_id
    if not store.delete_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    get_graph().delete_event_node(event_id)
    get_operation_log().record("delete", "event", event_id, name)
    return {"deleted": True}
