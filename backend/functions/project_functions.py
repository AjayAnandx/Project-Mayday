import os
from pathlib import Path

from backend.core.project_store import get_project_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph


def _project_folder(project: dict) -> Path:
    folder = project.get("folder", "")
    store = get_project_store()
    return store.projects_dir / folder


def create_project(name: str, tasks: list[dict] | None = None, description: str = "") -> str:
    store = get_project_store()
    result = store.create_project(name, tasks, description)
    if "error" in result:
        return result["error"]
    task_count = len(result.get("tasks", []))
    project_root = store.projects_dir
    desc_line = f" Description: {result['description']}" if result.get("description") else ""
    if task_count:
        return (
            f"Project '{result['name']}' created with {task_count} tasks. "
            f"Progress: 0/{task_count}. Folder: {project_root / result['folder']}{desc_line}"
        )
    return (
        f"Project '{result['name']}' created (status: {result['status']}). "
        f"Folder: {project_root / result['folder']}{desc_line}"
    )


def resume_project(name: str = "", project: str = "") -> str:
    if not name and project:
        name = project
    if not name:
        return "No project name provided."
    store = get_project_store()
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        # Fallback: scan disk for a matching folder
        from backend.core.sandbox import _to_slug
        slug = _to_slug(name)
        disk_folder = store.projects_dir / slug
        if disk_folder.is_dir():
            created = store.create_project(name)
            if "error" not in created:
                return (
                    f"Found and registered project '{name}' from disk at {disk_folder}. "
                    f"Project now has a store entry and graph node. "
                    f"Status: {created['status']}."
                )

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

    lines = [f"Found it! The {project_obj['name']} project (started {project_obj['created_at'][:10]})."]
    lines.append(f"Status: {project_obj['status']}")
    lines.append(f"Last activity: {project_obj['last_activity'][:10]}")
    folder_path = _project_folder(project_obj)
    lines.append(f"Folder: {folder_path}")
    if folder_path.exists():
        files = [f.name for f in folder_path.iterdir() if f.is_file()]
        if files:
            lines.append(f"Files ({len(files)}): {', '.join(files)}")

    if project_obj.get("conversation_ids"):
        count = len(project_obj["conversation_ids"])
        lines.append(f"Linked conversations: {count}")
        for cid in project_obj["conversation_ids"]:
            lines.append(f"  - {cid}")

    tasks = project_obj.get("tasks", [])
    if tasks:
        done = sum(1 for t in tasks if t["status"] == "completed")
        blocked = sum(1 for t in tasks if t["status"] == "blocked")
        part = f"Tasks: {done}/{len(tasks)} complete"
        if blocked:
            part += f" ({blocked} blocked)"
        lines.append(part)
        active_task = store.get_active_task(project_obj["id"])
        if active_task:
            lines.append(f"Next: {active_task['title']}")

    kg = get_graph()
    node = kg.get_node_by_label(f"project:{project_obj['name']}")
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


def update_project_status(name: str = "", status: str = "", project: str = "") -> str:
    valid = ("active", "paused", "scrapped")
    if not name and project:
        name = project
    if not name:
        return "No project name provided."
    if status not in valid:
        return f"Invalid status '{status}'. Must be one of {valid}."

    store = get_project_store()
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        return f"No project found with the name '{name}'."

    updated = store.update_project_status(project_obj["id"], status)
    if not updated:
        return f"Failed to update project '{name}'."

    if status == "scrapped":
        return f"Project '{name}' has been scrapped. You can resume it later with resume_project()."
    return f"Project '{name}' status updated to '{status}'."


def add_project_note(filename: str = "", content: str = "", name: str = "", project: str = "", file_name: str = "") -> str:
    if not filename and file_name:
        filename = file_name
    if not filename:
        filename = "notes.md"
    store = get_project_store()
    if not name and project:
        name = project
    if not name:
        active = store.list_projects(status="active")
        if active:
            name = active[0]["name"]
        else:
            return "No project name provided and no active project to fall back to."
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        return f"No project found with the name '{name}'."

    if not filename.endswith(".md"):
        filename += ".md"

    folder_path = _project_folder(project_obj)
    folder_path.mkdir(parents=True, exist_ok=True)

    file_path = folder_path / filename
    file_path.write_text(content, encoding="utf-8")

    store.touch_activity(project_obj["id"])

    kg = get_graph()
    kg.add_node("concept", filename, {"project_id": project_obj["id"], "type": "note"})
    node = kg.get_node_by_label(f"project:{project_obj['name']}")
    note_node = kg.get_node_by_label(filename)
    if node and note_node:
        kg.add_edge_if_missing(node["id"], note_node["id"], "has_note")

    get_operation_log().record(
        "write", "project", project_obj["id"], f"{project_obj['name']}/{filename}",
        details={"size": len(content)},
    )

    return f"Note saved: {folder_path / filename} ({len(content)} chars)"


def add_project_task(name: str = "", title: str = "", type: str = "general", depends_on: list[str] | None = None, description: str = "", project: str = "") -> str:
    if not name and project:
        name = project
    if not name:
        return "No project name provided."
    store = get_project_store()
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        return f"No project found with the name '{name}'."

    valid_types = ("research", "general", "build")
    if type not in valid_types:
        return f"Invalid type '{type}'. Must be one of {valid_types}."

    result = store.add_task(project_obj["id"], title, type, depends_on or [], description)
    if "error" in result:
        return result["error"]

    tasks = project_obj.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)
    return f"Task '{title}' added to '{name}'. Progress: {done}/{total}."


def update_task_status(name: str = "", task_id: str = "", status: str = "in_progress", result: str = "", task_title: str | None = None, project: str = "") -> str:
    valid = ("in_progress", "completed", "blocked", "failed")
    if status not in valid:
        return f"Invalid status '{status}'. Must be one of {valid}."

    if not name and project:
        name = project
    if not name:
        return "No project name provided."

    store = get_project_store()
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        from backend.core.research_store import get_research_store
        research = get_research_store()._get_by_topic(name)
        if research:
            return (
                f"'{name}' is a **research project**, not a regular project. "
                f"Manage it with research tools instead: resume_research(topic=\"{name}\"), "
                f"then update its tasks via update_research_status(topic=\"{name}\", status=...) "
                f"or add data with add_data_point/add_finding."
            )
        fuzzy = store.fuzzy_search(name)
        if fuzzy:
            suggestions = "\n".join(f"  - {p['name']} ({p['status']})" for p in fuzzy)
            return f"No project found with the name '{name}'.\nDid you mean one of these?\n{suggestions}"
        return f"No project found with the name '{name}'."

    def _match(t):
        if task_id and t["id"] == task_id:
            return True
        if not task_id and not task_title:
            return False
        candidates = [task_id, task_title or ""]
        return any(c and t["title"].strip().lower() == c.strip().lower() for c in candidates)

    task = next((t for t in project_obj.get("tasks", []) if _match(t)), None)
    if not task:
        tasks = project_obj.get("tasks", [])
        if tasks:
            listing = "\n".join(
                f"  - {t['title']} ({t['status']})" for t in tasks
            )
            return (
                f"Task '{task_id or task_title}' not found in project '{name}'. "
                f"Available tasks:\n{listing}\n"
                f"Pass the exact task title, or create a new task with add_project_task(name=\"{name}\", title=...) if it doesn't exist yet."
            )
        return f"No tasks exist in project '{name}' yet. Create one with add_project_task(name=\"{name}\", title=...)."

    updated = store.update_task_status(project_obj["id"], task["id"], status, result)
    if "error" in updated:
        return updated["error"]

    tasks = project_obj.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)
    msg = f"Task '{task['title']}' → {status}. Progress: {done}/{total}."
    if status == "completed":
        active_task = store.get_active_task(project_obj["id"])
        if active_task:
            msg += f" Next: {active_task['title']}"
    return msg


def list_project_tasks(name: str = "", status: str = "", project: str = "") -> str:
    if not name and project:
        name = project
    if not name:
        return "No project name provided."
    store = get_project_store()
    project_obj = store.find_project_by_name(name)
    if not project_obj:
        return f"No project found with the name '{name}'."

    tasks = store.list_tasks(project_obj["id"], status or None)
    if not tasks:
        return f"No tasks found in '{name}'." if not status else f"No {status} tasks in '{name}'."

    icons = {"completed": "✅", "in_progress": "⏳", "pending": "⬜", "blocked": "🚫", "failed": "❌"}
    lines = [f"Tasks ({len(tasks)}) for {name}:"]
    for i, t in enumerate(tasks):
        icon = icons.get(t["status"], "⬜")
        desc = f" — {t['description']}" if t.get("description") else ""
        deps = f" — depends on: {', '.join(t['depends_on'])}" if t.get("depends_on") else ""
        lines.append(f"{i+1}. {icon} {t['title']} ({t['type']}){desc}{deps}")

    all_tasks = project_obj.get("tasks", [])
    done = sum(1 for t in all_tasks if t["status"] == "completed")
    total = len(all_tasks)
    lines.append(f"\nProgress: {done}/{total}")
    active_task = store.get_active_task(project_obj["id"])
    if active_task:
        lines.append(f"Next: {active_task['title']}")
    return "\n".join(lines)
