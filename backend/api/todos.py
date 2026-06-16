from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.data_store import get_store

router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodoCreate(BaseModel):
    title: str
    description: str = ""
    due_date: Optional[str] = None
    priority: int = 2
    tags: list[str] = []


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    completed: Optional[bool] = None
    tags: Optional[list[str]] = None


@router.get("")
def list_todos(include_completed: bool = True, q: str = ""):
    store = get_store()
    return store.list_todos(include_completed=include_completed, query=q)


@router.get("/{todo_id}")
def get_todo(todo_id: str):
    store = get_store()
    todo = store.get_todo(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.post("", status_code=201)
def create_todo(body: TodoCreate):
    store = get_store()
    return store.create_todo(**body.model_dump())


@router.put("/{todo_id}")
def update_todo(todo_id: str, body: TodoUpdate):
    store = get_store()
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    todo = store.update_todo(todo_id, **kwargs)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/{todo_id}")
def delete_todo(todo_id: str):
    store = get_store()
    if not store.delete_todo(todo_id):
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"deleted": True}
