import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.core.config import load_config
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _kw_overlap(query: str, stored: str) -> float:
    qt = _tokenize(query)
    st = _tokenize(stored)
    if not qt or not st:
        return 0.0
    overlap = len(qt & st)
    return overlap / max(len(qt), len(st))


class ProjectStore:
    def __init__(self):
        cfg = load_config()
        path = cfg.get("data", {}).get("projects_path", "projects.json")
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent.parent.parent / path)
        self._path = Path(path)
        self._projects_dir = Path(__file__).resolve().parent.parent.parent / "projects"
        self._lock = threading.Lock()
        self._projects: list[dict] = []
        self._load()
        self._init_projects_dir()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._projects = data.get("projects", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"projects": self._projects}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _init_projects_dir(self):
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def _find_index(self, project_id: str) -> int | None:
        for i, p in enumerate(self._projects):
            if p["id"] == project_id:
                return i
        return None

    def _auto_pause(self, project: dict) -> bool:
        if project["status"] != "active":
            return False
        try:
            last = datetime.fromisoformat(project["last_activity"])
            now = datetime.now(timezone.utc)
            if (now - last).days >= 30:
                project["status"] = "paused"
                get_operation_log().record(
                    "pause", "project", project["id"], project["name"],
                    details={"reason": "30d inactive"},
                )
                return True
        except (ValueError, TypeError):
            pass
        return False

    def create_project(self, name: str) -> dict:
        with self._lock:
            name = name.strip()
            if not name:
                return {"error": "Project name cannot be empty"}

            existing = [p for p in self._projects if p["name"].lower() == name.lower()]
            active = [p for p in existing if p["status"] in ("active", "paused")]
            if active:
                return {"error": f"Project '{name}' already exists (status: {active[0]['status']}). Use resume_project to access it."}

            project_id = "proj_" + uuid.uuid4().hex[:12]
            folder_name = _slugify(name)
            folder_path = self._projects_dir / folder_name

            project = {
                "id": project_id,
                "name": name,
                "status": "active",
                "created_at": _utcnow(),
                "last_activity": _utcnow(),
                "folder": f"projects/{folder_name}/",
                "conversation_ids": [],
            }
            self._projects.append(project)
            self._save()

            folder_path.mkdir(parents=True, exist_ok=True)

            kg = get_graph()
            kg.add_node("project", f"project:{name}", {"id": project_id, "status": "active"})

            get_operation_log().record(
                "create", "project", project_id, name,
                details={"folder": project["folder"]},
            )

            return project

    def get_project(self, project_id: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            self._auto_pause(self._projects[idx])
            return dict(self._projects[idx])

    def find_project_by_name(self, name: str) -> dict | None:
        with self._lock:
            name = name.strip().lower()
            best: dict | None = None
            best_score = 0.0

            for p in self._projects:
                if p["name"].lower() == name:
                    self._auto_pause(p)
                    return dict(p)
                score = _kw_overlap(name, p["name"])
                if score > best_score:
                    best_score = score
                    best = p

            if best and best_score >= 0.4:
                self._auto_pause(best)
                return dict(best)
            return None

    def fuzzy_search(self, name: str) -> list[dict]:
        with self._lock:
            name = name.strip().lower()
            scored = []
            for p in self._projects:
                score = _kw_overlap(name, p["name"])
                if score > 0:
                    scored.append((score, p))
            scored.sort(key=lambda x: -x[0])
            return [dict(p) for _, p in scored[:5]]

    def list_projects(self, status: str | None = None) -> list[dict]:
        with self._lock:
            results = []
            for p in self._projects:
                self._auto_pause(p)
                if status is None or p["status"] == status:
                    results.append(dict(p))
            self._save()
            return results

    def update_project_status(self, project_id: str, new_status: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            old_status = self._projects[idx]["status"]
            self._projects[idx]["status"] = new_status
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()

            name = self._projects[idx]["name"]
            get_operation_log().record(
                new_status if new_status != "active" else "resume",
                "project", project_id, name,
                details={"from": old_status, "to": new_status},
            )

            kg = get_graph()
            kg.add_node("project", f"project:{name}", {"id": project_id, "status": new_status})

            return dict(self._projects[idx])

    def update_project_name(self, project_id: str, new_name: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            self._projects[idx]["name"] = new_name.strip()
            self._save()
            return dict(self._projects[idx])

    def link_conversation(self, project_id: str, conversation_id: str):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return
            if conversation_id not in self._projects[idx]["conversation_ids"]:
                self._projects[idx]["conversation_ids"].append(conversation_id)
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()

    def touch_activity(self, project_id: str):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()

    def soft_delete(self, project_id: str) -> dict | None:
        return self.update_project_status(project_id, "scrapped")


_instance: ProjectStore | None = None
_instance_lock = threading.Lock()


def get_project_store() -> ProjectStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ProjectStore()
    return _instance
