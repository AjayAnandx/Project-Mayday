from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log


def create_todo(title: str, description: str = "", due_date: str = None,
                priority: int = 2, tags: list[str] = None,
                recurrence: dict = None, force: bool = False) -> str:
    store = get_store()
    if not force:
        dups = store.find_duplicate_todos(title, due_date)
        if dups:
            dup_info = "; ".join(
                f"'{d['title']}' (id: {d['id']}, due: {d.get('due_date', 'none')}, status: {'✓ done' if d['completed'] else '○ pending'})"
                for d in dups[:3]
            )
            extra = f" and {len(dups) - 3} more" if len(dups) > 3 else ""
            return (f"⚠️ Potential duplicate detected! The following similar todo(s) already exist: {dup_info}{extra}. "
                    f"I did NOT create the new todo. Would you like to review the existing one(s) instead, or proceed with creating a new one?")
    todo = store.create_todo(title, description, due_date, priority, tags, recurrence)
    get_operation_log().record("create", "todo", todo["id"], todo["title"],
                                details={"priority": priority, "recurrence": recurrence})
    return f"Created todo: {todo['title']} (id: {todo['id']})"


def update_todo(todo_id: str, **kwargs) -> str:
    store = get_store()
    todo = store.update_todo(todo_id, **kwargs)
    if todo:
        get_operation_log().record("update", "todo", todo_id, todo["title"], details=kwargs)
        return f"Updated todo: {todo['title']} (id: {todo['id']})"
    return f"Todo {todo_id} not found"


def delete_todo(todo_id: str) -> str:
    store = get_store()
    todo = store.get_todo(todo_id)
    name = todo["title"] if todo else todo_id
    if store.delete_todo(todo_id):
        get_operation_log().record("delete", "todo", todo_id, name)
        return f"Deleted todo {todo_id}"
    return f"Todo {todo_id} not found"


def list_todos(include_completed: bool = True) -> str:
    store = get_store()
    todos = store.list_todos(include_completed)
    if not todos:
        return "No todos found."
    lines = []
    for t in todos:
        status = "✓" if t["completed"] else "○"
        pri = {1: "🔴", 2: "🟡", 3: "🟢"}.get(t["priority"], "⚪")
        due = f" (due: {t['due_date']})" if t.get("due_date") else ""
        lines.append(f"{status} {pri} {t['title']}{due} — {t['id']}")
    return "\n".join(lines)
