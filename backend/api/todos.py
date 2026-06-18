from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/todos", tags=["todos"])


class RecurrenceRule(BaseModel):
    pattern: str  # daily, weekly, biweekly, monthly, yearly
    interval: Optional[int] = None
    end_date: Optional[str] = None
    count: Optional[int] = None


class TodoCreate(BaseModel):
    title: str
    description: str = ""
    due_date: Optional[str] = None
    priority: int = 2
    tags: list[str] = []
    recurrence: Optional[RecurrenceRule] = None


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    completed: Optional[bool] = None
    tags: Optional[list[str]] = None
    recurrence: Optional[Any] = None


@router.get("")
def list_todos(include_completed: bool = True, q: str = ""):
    store = get_store()
    return store.list_todos(include_completed=include_completed, query=q)


@router.get("/check-duplicates")
def check_todo_duplicates(title: str = "", due_date: str = None, exclude_id: str = None):
    store = get_store()
    if not title.strip():
        return []
    return store.find_duplicate_todos(title, due_date, exclude_id)


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
    todo = store.create_todo(**body.model_dump())
    get_graph().sync_todo(todo)
    get_operation_log().record("create", "todo", todo["id"], todo["title"], details={"priority": todo.get("priority")})
    return todo


@router.put("/{todo_id}")
def update_todo(todo_id: str, body: TodoUpdate):
    store = get_store()
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    todo = store.update_todo(todo_id, **kwargs)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    get_graph().sync_todo(todo)
    get_operation_log().record("update", "todo", todo_id, todo["title"], details=kwargs)
    return todo


@router.delete("/{todo_id}")
def delete_todo(todo_id: str):
    store = get_store()
    todo = store.get_todo(todo_id)
    name = todo["title"] if todo else todo_id
    if not store.delete_todo(todo_id):
        raise HTTPException(status_code=404, detail="Todo not found")
    get_graph().delete_todo_node(todo_id)
    get_operation_log().record("delete", "todo", todo_id, name)
    return {"deleted": True}
