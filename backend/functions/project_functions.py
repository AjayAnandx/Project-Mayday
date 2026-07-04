import os
from pathlib import Path

from backend.core.project_store import get_project_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph


def create_project(name: str) -> str:
    store = get_project_store()
    result = store.create_project(name)
    if "error" in result:
        return result["error"]
    return (
        f"Project '{result['name']}' created (status: {result['status']}). "
        f"Folder: {result['folder']}"
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
    lines.append(f"Folder: {project['folder']}")

    folder_path = Path(__file__).resolve().parent.parent.parent / project["folder"]
    if folder_path.exists():
        files = [f.name for f in folder_path.iterdir() if f.is_file()]
        if files:
            lines.append(f"Files ({len(files)}): {', '.join(files)}")

    if project.get("conversation_ids"):
        count = len(project["conversation_ids"])
        lines.append(f"Linked conversations: {count}")
        for cid in project["conversation_ids"]:
            lines.append(f"  - {cid}")

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


def add_project_note(name: str, filename: str, content: str) -> str:
    store = get_project_store()
    project = store.find_project_by_name(name)
    if not project:
        return f"No project found with the name '{name}'."

    if not filename.endswith(".md"):
        filename += ".md"

    base = Path(__file__).resolve().parent.parent.parent
    folder_path = base / project["folder"]
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

    return f"Note saved: {project['folder']}{filename} ({len(content)} chars)"
