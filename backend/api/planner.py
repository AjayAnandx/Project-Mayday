"""Planner REST API — unified tasks / events / reminders / waiting-on + people."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.core.planner_store import get_planner
from backend.functions.planner_functions import record_change

router = APIRouter(prefix="/api/planner", tags=["planner"])


class ItemIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    kind: str = "task"
    notes: str = ""
    list_name: str = Field("", alias="list")
    tags: list[str] = []
    priority: int = 4
    start_at: Optional[str] = None
    due_at: Optional[str] = None
    end_at: Optional[str] = None
    all_day: bool = False
    deadline: Optional[str] = None
    estimate_min: Optional[int] = None
    reminders: Optional[list[Any]] = None
    recurrence: Optional[dict] = None
    parent_id: Optional[str] = None
    checklist: list[dict] = []
    person_id: Optional[str] = None
    follow_up_at: Optional[str] = None


class QuickAddIn(BaseModel):
    text: str
    commit: bool = True


class CompleteIn(BaseModel):
    done: bool = True


class SnoozeIn(BaseModel):
    minutes: Optional[int] = None
    until: Optional[str] = None


class ScheduleIn(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class DelegateIn(BaseModel):
    title: str
    person: str
    due_at: Optional[str] = None
    follow_up_at: Optional[str] = None
    notes: str = ""
    email: str = ""


class PersonIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    relation: str = ""
    notes: str = ""


def _or_404(item, what="Item"):
    if not item:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return item


def _bad_request(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── items ───────────────────────────────────────────────────────────────────

@router.get("/items")
def list_items(view: str = "all", start: str = "", end: str = "", list: str = "", tag: str = "",
               q: str = "", kind: str = "", person_id: str = "", include_done: bool = False,
               days: int = Query(14, ge=1, le=366)):
    kinds = tuple(k for k in kind.split(",") if k) or None
    return _bad_request(get_planner().list_items, view, start=start or None, end=end or None,
                        list_name=list or None, tag=tag or None, query=q or None, kinds=kinds,
                        person_id=person_id or None, include_done=include_done, days=days)


@router.get("/items/{item_id}")
def get_item(item_id: str):
    return _or_404(get_planner().get_item(item_id))


@router.post("/items", status_code=201)
def create_item(body: ItemIn):
    data = body.model_dump(by_alias=True)
    title, kind = data.pop("title"), data.pop("kind")
    item = _bad_request(get_planner().create_item, title, kind=kind, **data)
    record_change("create", item)
    return item


@router.post("/quick-add", status_code=201)
def quick_add(body: QuickAddIn):
    """Parse natural language ('Ravi to send deck by fri #work !p1') and optionally create it."""
    from backend.core.planner_parse import parse_quick_add
    parsed = parse_quick_add(body.text)
    if not body.commit:
        return {"parsed": parsed}
    fields = dict(parsed)
    title, kind, person = fields.pop("title"), fields.pop("kind"), fields.pop("person", None)
    p = get_planner()
    if kind == "waiting" and person:
        item = _bad_request(p.delegate, title, person, due_at=fields.pop("due_at", None), **fields)
    else:
        item = _bad_request(p.create_item, title, kind=kind, **fields)
    record_change("create", item)
    return {"parsed": parsed, "item": item}


@router.put("/items/{item_id}")
def update_item(item_id: str, body: dict):
    body.pop("id", None)
    item = _or_404(_bad_request(get_planner().update_item, item_id, **body))
    record_change("update", item, details={k: str(v)[:80] for k, v in body.items()})
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: str):
    p = get_planner()
    item = _or_404(p.get_item(item_id))
    p.delete_item(item_id)
    record_change("delete", item)
    return {"deleted": True}


@router.post("/items/{item_id}/complete")
def complete_item(item_id: str, body: CompleteIn = CompleteIn()):
    item = _or_404(get_planner().complete_item(item_id, done=body.done))
    record_change("update", item, details={"completed": body.done})
    return item


@router.post("/items/{item_id}/snooze")
def snooze_item(item_id: str, body: SnoozeIn):
    item = _or_404(get_planner().snooze_item(item_id, minutes=body.minutes, until=body.until))
    record_change("update", item, details={"snoozed_until": item.get("snoozed_until")})
    return item


@router.post("/items/{item_id}/schedule")
def schedule_item(item_id: str, body: ScheduleIn):
    item = _or_404(_bad_request(get_planner().schedule_item, item_id, body.start, body.end))
    record_change("update", item, details={"scheduled_block": item.get("scheduled_block")})
    return item


@router.post("/items/{item_id}/nudge")
def nudge_item(item_id: str):
    from backend.core.planner_nudge import draft_nudge
    _or_404(get_planner().get_item(item_id))
    return draft_nudge(item_id)


@router.post("/delegate", status_code=201)
def delegate(body: DelegateIn):
    item = _bad_request(get_planner().delegate, body.title, body.person, due_at=body.due_at,
                        follow_up_at=body.follow_up_at, notes=body.notes, email=body.email)
    record_change("create", item, details={"delegated_to": body.person})
    return item


# ── overview ────────────────────────────────────────────────────────────────

@router.get("/summary")
def summary():
    p = get_planner()
    return {"counts": p.counts(), "lists": p.lists(),
            "tags": sorted({t for i in p.all_items() if i["status"] == "open" for t in i.get("tags", [])})}


@router.get("/plan-day")
def plan_day(date: str = "", day_start: str = "09:00", day_end: str = "18:00"):
    from backend.core.planner_autoplan import propose_day
    return propose_day(date or None, day_start, day_end)


# ── people ──────────────────────────────────────────────────────────────────

@router.get("/people")
def list_people():
    return get_planner().list_people()


@router.post("/people", status_code=201)
def create_person(body: PersonIn):
    p = get_planner()
    person = _bad_request(p.create_person, body.name, email=body.email, phone=body.phone,
                          relation=body.relation, notes=body.notes)
    return person


@router.get("/people/{person_id}")
def get_person(person_id: str):
    p = get_planner()
    person = _or_404(p.find_person(person_id), "Person")
    return {**person, **p.person_ledger(person["id"])}


@router.put("/people/{person_id}")
def update_person(person_id: str, body: dict):
    return _or_404(get_planner().update_person(person_id, **body), "Person")


@router.delete("/people/{person_id}")
def delete_person(person_id: str):
    if not get_planner().delete_person(person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return {"deleted": True}


# ── digest ──────────────────────────────────────────────────────────────────

@router.get("/digest")
def preview_digest(kind: str = "morning"):
    if kind not in ("morning", "evening"):
        raise HTTPException(status_code=400, detail="kind must be morning or evening")
    from backend.core.planner_digest import build_digest, _digest_cfg
    d = build_digest(kind)
    cfg = _digest_cfg()
    return {**d, "to": cfg["to"], "enabled": cfg["enabled"], "morning": cfg["morning"], "evening": cfg["evening"]}


@router.post("/digest/send")
def send_digest_now(kind: str = "morning"):
    if kind not in ("morning", "evening"):
        raise HTTPException(status_code=400, detail="kind must be morning or evening")
    from backend.core.planner_digest import send_digest
    return send_digest(kind)
