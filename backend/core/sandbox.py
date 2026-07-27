import logging
import re

from backend.core.project_runner import ProjectRunner

logger = logging.getLogger(__name__)

CONTAINER_NAME_PREFIX = "mayday-build"

def _to_slug(name: str) -> str:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    return re.sub(r"[^a-z0-9-]", "", slug)


def sandbox_start(project_name: str) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get_or_create(slug)
    return runner.prepare()


def sandbox_exec(project_name: str, command: str, background: bool = False) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'. Call sandbox_start first."
    if background:
        result = runner.exec_background(command)
        return result["message"]
    return runner.exec(command)


def sandbox_stop(project_name: str, copy_out: bool = True) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'."
    return runner.stop()


def sandbox_status(project_name: str) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'."
    return runner.status()


def sandbox_write_file(project_name: str, path: str, content: str) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'. Call sandbox_start first."
    return runner.write_file(path, content)


def sandbox_read_file(project_name: str, path: str) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'. Call sandbox_start first."
    return runner.read_file(path)


def sandbox_delete_file(project_name: str, path: str) -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'. Call sandbox_start first."
    return runner.delete_file(path)


def sandbox_list_files(project_name: str, path: str = ".") -> str:
    slug = _to_slug(project_name)
    runner = ProjectRunner.get(slug)
    if not runner:
        return f"No sandbox found for '{project_name}'. Call sandbox_start first."
    return runner.list_files(path)


def sandbox_sync_from_host(project_name: str) -> str:
    return "Not needed — files are already on the host."


def sandbox_sync_to_host(project_name: str) -> str:
    return "Not needed — files are already on the host."


def list_host_projects() -> str:
    from backend.core.project_store import get_project_store
    store = get_project_store()
    discovered = store.discover_host_projects()
    if not discovered:
        return "No unregistered project folders found on disk."
    lines = ["Unregistered project folders found on disk:"]
    for p in discovered:
        lines.append(f"  - {p['name']} ({p['file_count']} files, modified {p['modified_at']})")
        lines.append(f"    Path: {p['path']}")
    return "\n".join(lines)
