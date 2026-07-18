import os
from pathlib import Path

from backend.core.project_store import get_project_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph


def _project_folder(project: dict) -> Path:
    folder = project.get("folder", "")
    store = get_project_store()
    return store.projects_dir / folder


def create_project(name: str, tasks: list[dict] | None = None) -> str:
    store = get_project_store()
    result = store.create_project(name, tasks)
    if "error" in result:
        return result["error"]
    task_count = len(result.get("tasks", []))
    project_root = store.projects_dir
    if task_count:
        return (
            f"Project '{result['name']}' created with {task_count} tasks. "
            f"Progress: 0/{task_count}. Folder: {project_root / result['folder']}"
        )
    return (
        f"Project '{result['name']}' created (status: {result['status']}). "
        f"Folder: {project_root / result['folder']}"
    )


def resume_project(name: str) -> str:
    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        fuzzy = store.fuzzy_search(name)
        if fuzzy:
            suggestions = "\n".join(
                f"  - {p['name']} ({p['status']})" for p in fuzzy
            )
            return (
                f"No project found with the name '{name}'.\n"
                f"Did you mean one of these?\n{suggestions}"
            )
        return f"No project found with the name '{name}'."

    lines = [f"Found it! The {project['name']} project (started {project['created_at'][:10]})."]
    lines.append(f"Status: {project['status']}")
    lines.append(f"Last activity: {project['last_activity'][:10]}")
    folder_path = _project_folder(project)
    lines.append(f"Folder: {folder_path}")
    if folder_path.exists():
        files = [f.name for f in folder_path.iterdir() if f.is_file()]
        if files:
            lines.append(f"Files ({len(files)}): {', '.join(files)}")

    if project.get("conversation_ids"):
        count = len(project["conversation_ids"])
        lines.append(f"Linked conversations: {count}")
        for cid in project["conversation_ids"]:
            lines.append(f"  - {cid}")

    tasks = project.get("tasks", [])
    if tasks:
        done = sum(1 for t in tasks if t["status"] == "completed")
        blocked = sum(1 for t in tasks if t["status"] == "blocked")
        part = f"Tasks: {done}/{len(tasks)} complete"
        if blocked:
            part += f" ({blocked} blocked)"
        lines.append(part)
        active_task = store.get_active_task(project["id"])
        if active_task:
            lines.append(f"Next: {active_task['title']}")

    kg = get_graph()
    node = kg.get_node_by_label(f"project:{project['name']}")
    if node:
        sg = kg.get_subgraph(node["id"], depth=1)
        edges = sg.get("edges", [])
        if edges:
            for e in edges:
                target = e.get("target_label", e.get("target", ""))
                rel = e.get("relation", "")
                lines.append(f"  {rel} → {target}")

    return "\n".join(lines)


def list_projects(status: str = "") -> str:
    store = get_project_store()
    projects = store.list_projects(status=status or None)
    if not projects:
        return "No projects found." if not status else f"No {status} projects found."
    lines = [f"Projects ({len(projects)}):"]
    for p in projects:
        lines.append(f"  {p['status']} {p['name']} (last: {p['last_activity'][:10]})")
    return "\n".join(lines)


def update_project_status(name: str, status: str) -> str:
    valid = ("active", "paused", "scrapped")
    if status not in valid:
        return f"Invalid status '{status}'. Must be one of {valid}."

    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    updated = store.update_project_status(project["id"], status)
    if not updated:
        return f"Failed to update project '{name}'."

    if status == "scrapped":
        return f"Project '{name}' has been scrapped. You can resume it later with resume_project()."
    return f"Project '{name}' status updated to '{status}'."


def add_project_note(filename: str, content: str, name: str = "") -> str:
    store = get_project_store()
    if not name:
        active = store.list_projects(status="active")
        if active:
            name = active[0]["name"]
        else:
            return "No project name provided and no active project to fall back to."
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    if not filename.endswith(".md"):
        filename += ".md"

    folder_path = _project_folder(project)
    folder_path.mkdir(parents=True, exist_ok=True)

    file_path = folder_path / filename
    file_path.write_text(content, encoding="utf-8")

    store.touch_activity(project["id"])

    kg = get_graph()
    kg.add_node("concept", filename, {"project_id": project["id"], "type": "note"})
    node = kg.get_node_by_label(f"project:{project['name']}")
    note_node = kg.get_node_by_label(filename)
    if node and note_node:
        kg.add_edge_if_missing(node["id"], note_node["id"], "has_note")

    get_operation_log().record(
        "write", "project", project["id"], f"{project['name']}/{filename}",
        details={"size": len(content)},
    )

    return f"Note saved: {folder_path / filename} ({len(content)} chars)"


def add_project_task(name: str, title: str, type: str = "general", depends_on: list[str] | None = None, description: str = "") -> str:
    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    valid_types = ("research", "general", "build")
    if type not in valid_types:
        return f"Invalid type '{type}'. Must be one of {valid_types}."

    result = store.add_task(project["id"], title, type, depends_on or [], description)
    if "error" in result:
        return result["error"]

    tasks = project.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)
    return f"Task '{title}' added to '{name}'. Progress: {done}/{total}."


def update_task_status(name: str, task_id: str = "", status: str = "in_progress", result: str = "", task_title: str | None = None) -> str:
    valid = ("in_progress", "completed", "blocked", "failed")
    if status not in valid:
        return f"Invalid status '{status}'. Must be one of {valid}."

    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    task = next((t for t in project.get("tasks", []) if t["id"] == task_id), None)
    if not task and task_title:
        task = next((t for t in project.get("tasks", []) if t["title"].lower() == task_title.strip().lower()), None)
    if not task:
        return f"Task not found. Use list_project_tasks to see available tasks."

    updated = store.update_task_status(project["id"], task["id"], status, result)
    if "error" in updated:
        return updated["error"]

    tasks = project.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)
    msg = f"Task '{task['title']}' → {status}. Progress: {done}/{total}."
    if status == "completed":
        active_task = store.get_active_task(project["id"])
        if active_task:
            msg += f" Next: {active_task['title']}"
    return msg


def list_project_tasks(name: str, status: str = "") -> str:
    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    tasks = store.list_tasks(project["id"], status or None)
    if not tasks:
        return f"No tasks found in '{name}'." if not status else f"No {status} tasks in '{name}'."

    icons = {"completed": "✅", "in_progress": "⏳", "pending": "⬜", "blocked": "🚫", "failed": "❌"}
    lines = [f"Tasks ({len(tasks)}) for {name}:"]
    for i, t in enumerate(tasks):
        icon = icons.get(t["status"], "⬜")
        desc = f" — {t['description']}" if t.get("description") else ""
        deps = f" — depends on: {', '.join(t['depends_on'])}" if t.get("depends_on") else ""
        lines.append(f"{i+1}. {icon} {t['title']} ({t['type']}){desc}{deps}")

    all_tasks = project.get("tasks", [])
    done = sum(1 for t in all_tasks if t["status"] == "completed")
    total = len(all_tasks)
    lines.append(f"\nProgress: {done}/{total}")
    active_task = store.get_active_task(project["id"])
    if active_task:
        lines.append(f"Next: {active_task['title']}")
    return "\n".join(lines)
