from backend.core.data_store import get_store


def create_todo(title: str, description: str = "", due_date: str = None,
                priority: int = 2, tags: list[str] = None) -> str:
    store = get_store()
    todo = store.create_todo(title, description, due_date, priority, tags)
    return f"Created todo: {todo['title']} (id: {todo['id']})"


def update_todo(todo_id: str, **kwargs) -> str:
    store = get_store()
    todo = store.update_todo(todo_id, **kwargs)
    if todo:
        return f"Updated todo: {todo['title']}"
    return f"Todo {todo_id} not found"


def delete_todo(todo_id: str) -> str:
    store = get_store()
    if store.delete_todo(todo_id):
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
