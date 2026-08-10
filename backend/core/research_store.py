import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.core.config import load_config
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _slugify(topic: str) -> str:
    s = topic.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


RESEARCH_TYPES = (
    "market", "technical", "financial", "sales", "business",
    "academic", "competitive", "product", "domain", "person_org",
    "legal", "trend", "community",
)

RESEARCH_TYPE_TASKS = {
    "market": [
        "Define scope & TAM",
        "Segment analysis & competitors",
        "Pricing & revenue models",
        "Synthesize report + infographic",
    ],
    "technical": [
        "Survey tools & frameworks",
        "Architecture evaluation",
        "Benchmarks & limitations",
        "Recommendation report",
    ],
    "financial": [
        "Gather financial data",
        "Analyze metrics & ratios",
        "Risk assessment",
        "Investment thesis",
    ],
    "sales": [
        "Define ICP & segments",
        "Competitor positioning",
        "Sales channels & pricing",
        "Playbook + outreach strategy",
    ],
    "business": [
        "Define business model",
        "Value chain mapping",
        "SWOT analysis",
        "Strategic recommendations",
    ],
    "academic": [
        "Literature survey",
        "Methodology analysis",
        "Results & limitations",
        "Citation network map",
        "Knowledge gaps",
    ],
    "competitive": [
        "Identify competitors",
        "Feature comparison",
        "Market positioning",
        "Win/loss analysis",
        "Strategic gaps",
    ],
    "product": [
        "Feature inventory",
        "UX & experience review",
        "Technical architecture",
        "Roadmap & gaps",
    ],
    "domain": [
        "Industry structure",
        "Ecosystem mapping",
        "Regulatory landscape",
        "Key players & trends",
    ],
    "person_org": [
        "Background research",
        "Key achievements",
        "Current focus & traction",
        "Reputation analysis",
    ],
    "legal": [
        "IP & patents",
        "Litigation history",
        "Regulatory exposure",
        "Legal risk summary",
    ],
    "trend": [
        "Signal gathering",
        "Pattern identification",
        "Impact analysis",
        "Foresight scenarios",
    ],
    "community": [
        "Community mapping",
        "Governance analysis",
        "Health metrics",
        "Fragmentation analysis",
    ],
}


class ResearchStore:
    def __init__(self):
        cfg = load_config()
        path = cfg.get("data", {}).get("research_path", "research.json")
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent.parent.parent / path)
        self._path = Path(path)

        outputs_dir = cfg.get("data", {}).get("research_outputs_dir", "research")
        if not Path(outputs_dir).is_absolute():
            outputs_dir = str(Path(__file__).resolve().parent.parent.parent / outputs_dir)
        self._outputs_dir = Path(outputs_dir)

        self._lock = threading.Lock()
        self._projects: list[dict] = []
        self._migrate_legacy_storage()
        self._load()
        self._backfill_research_node_types()

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    def _migrate_legacy_storage(self):
        """One-time move of legacy repo-root storage into the Mayday Research folder.

        Guarded by 'old path exists AND new path missing' so re-runs are safe
        and a populated new location always wins. Only runs when the new
        location genuinely differs from the legacy repo-root location.
        """
        old_json = self._repo_root() / "research.json"
        old_topics = self._repo_root() / "research"
        relocated = (self._path.resolve() != old_json.resolve()
                     or self._outputs_dir.resolve() != old_topics.resolve())
        if not relocated:
            return
        try:
            if old_json.is_file() and not self._path.exists():
                self._path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_json), str(self._path))
            if old_topics.is_dir() and not self._outputs_dir.exists():
                self._outputs_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_topics), str(self._outputs_dir))
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning("Research storage migration skipped: %s", e)

    def _backfill_research_node_types(self):
        """Ensure every research record has a `research`-type graph node.

        Re-types legacy `research:*` nodes stored as 'project', and re-creates
        nodes that were removed by past graph cleanups.
        """
        try:
            kg = get_graph()
            for node in kg.get_nodes_by_type("project"):
                if node["label"].strip().lower().startswith("research:"):
                    kg.set_node_type(node["id"], "research")
            for p in self._projects:
                topic = p.get("topic", "")
                if not topic:
                    continue
                node = kg.get_node_by_label(f"research:{topic}")
                if node is None and p.get("graph_node_id"):
                    node = kg.get_node(p["graph_node_id"])
                if node is None:
                    node_id = kg.add_node("research", f"research:{topic}", {
                        "id": p.get("id", ""),
                        "type": p.get("type", ""),
                        "status": p.get("status", "active"),
                    })
                    p["graph_node_id"] = node_id
                elif node["type"] != "research":
                    kg.set_node_type(node["id"], "research")
                if p.get("graph_node_id") != node["id"]:
                    p["graph_node_id"] = node["id"]
            self._save()
        except Exception:
            pass

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

    def _find_index(self, project_id: str) -> int | None:
        for i, p in enumerate(self._projects):
            if p["id"] == project_id:
                return i
        return None

    def _find_by_topic(self, topic: str) -> dict | None:
        q = topic.strip().lower()
        for p in self._projects:
            if p.get("topic", "").strip().lower() == q:
                return p
        return None

    def create_research(self, topic: str, research_type: str, depth: int = 2, questions: list[str] | None = None) -> dict:
        with self._lock:
            topic = topic.strip()
            if not topic:
                return {"error": "Research topic cannot be empty"}
            if research_type not in RESEARCH_TYPES:
                return {"error": f"Invalid research type '{research_type}'. Must be one of: {', '.join(RESEARCH_TYPES)}"}
            if depth not in (1, 2, 3, 4):
                return {"error": "Depth must be 1-4"}

            existing = self._find_by_topic(topic)
            if existing:
                return {"error": f"Research '{topic}' already exists (status: {existing.get('status')}). Use resume_research to access it."}

            project_id = "res_" + uuid.uuid4().hex[:12]
            slug = _slugify(topic)

            task_titles = RESEARCH_TYPE_TASKS.get(research_type, [])
            tasks = []
            for i, title in enumerate(task_titles):
                task = {
                    "id": "task_" + uuid.uuid4().hex[:8],
                    "title": title,
                    "description": "",
                    "type": "research",
                    "status": "pending",
                    "depends_on": [tasks[-1]["title"]] if tasks else [],
                    "result": "",
                    "created_at": _utcnow(),
                    "updated_at": _utcnow(),
                }
                tasks.append(task)

            project = {
                "id": project_id,
                "topic": topic,
                "slug": slug,
                "type": research_type,
                "depth": depth,
                "status": "active",
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                "summary": "",
                "research_questions": questions or [],
                "data_points": [],
                "entities": [],
                "findings": [],
                "generated_outputs": [],
                "tasks": tasks,
                "conversation_ids": [],
                "graph_node_id": None,
            }

            kg = get_graph()
            node_id = kg.add_node("research", f"research:{topic}", {
                "id": project_id,
                "type": research_type,
                "status": "active",
            })
            if node_id:
                project["graph_node_id"] = node_id

            self._projects.append(project)
            self._save()

            get_operation_log().record(
                "create", "research", project_id, topic,
                details={"type": research_type, "depth": depth, "tasks": len(tasks)},
            )

            return {
                "id": project_id,
                "topic": topic,
                "type": research_type,
                "depth": depth,
                "status": "active",
                "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"]} for t in tasks],
                "task_count": len(tasks),
            }

    def resume_research(self, topic: str) -> dict | None:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return None
            project["updated_at"] = _utcnow()
            self._save()
            return dict(project)

    def list_projects(self, status: str | None = None) -> list[dict]:
        with self._lock:
            results = []
            for p in self._projects:
                if status is None or p["status"] == status:
                    results.append({
                        "id": p["id"],
                        "topic": p["topic"],
                        "type": p["type"],
                        "status": p["status"],
                        "depth": p.get("depth", 2),
                        "data_point_count": len(p.get("data_points", [])),
                        "entity_count": len(p.get("entities", [])),
                        "finding_count": len(p.get("findings", [])),
                        "task_count": len(p.get("tasks", [])),
                        "created_at": p["created_at"],
                        "updated_at": p["updated_at"],
                    })
            results.sort(key=lambda x: x["updated_at"], reverse=True)
            return results

    def update_status(self, topic: str, status: str) -> dict | None:
        if status not in ("active", "paused", "completed"):
            return {"error": f"Invalid status '{status}'. Must be active, paused, or completed."}
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return None
            old_status = project["status"]
            project["status"] = status
            project["updated_at"] = _utcnow()
            self._save()

            get_operation_log().record(
                status, "research", project["id"], topic,
                details={"from": old_status, "to": status},
            )

            kg = get_graph()
            kg.add_node("research", f"research:{topic}", {"id": project["id"], "status": status})

            return dict(project)

    def _get_by_topic(self, topic: str) -> dict | None:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return None
            return project

    def add_data_point(self, topic: str, label: str, value: str, unit: str | None = None,
                       confidence: str | None = None, sources: list[str] | None = None) -> dict:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            dp = {
                "id": "dp_" + uuid.uuid4().hex[:8],
                "label": label,
                "value": value,
                "unit": unit or "",
                "confidence": confidence or "medium",
                "sources": sources or [],
                "created_at": _utcnow(),
            }
            project["data_points"].append(dp)
            project["updated_at"] = _utcnow()
            self._save()

            get_operation_log().record(
                "add_data_point", "research", project["id"], topic,
                details={"label": label, "value": value},
            )
            return dp

    def add_entity(self, topic: str, name: str, entity_type: str = "company",
                   description: str | None = None, relevance: float | None = None,
                   sources: list[str] | None = None) -> dict:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            ent = {
                "id": "ent_" + uuid.uuid4().hex[:8],
                "name": name,
                "type": entity_type,
                "description": description or "",
                "relevance": relevance or 0.5,
                "sources": sources or [],
                "created_at": _utcnow(),
            }
            project["entities"].append(ent)
            project["updated_at"] = _utcnow()
            self._save()

            get_operation_log().record(
                "add_entity", "research", project["id"], topic,
                details={"name": name, "type": entity_type},
            )
            return ent

    def add_finding(self, topic: str, content: str, confidence: str | None = None,
                    sources: list[str] | None = None) -> dict:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            fin = {
                "id": "fin_" + uuid.uuid4().hex[:8],
                "content": content,
                "confidence": confidence or "medium",
                "sources": sources or [],
                "created_at": _utcnow(),
            }
            project["findings"].append(fin)
            project["updated_at"] = _utcnow()
            self._save()

            get_operation_log().record(
                "add_finding", "research", project["id"], topic,
                details={"content": content[:120]},
            )
            return fin

    def get_outputs_dir(self, project: dict) -> Path:
        return self._outputs_dir / project["slug"] / "outputs"

    def get_notes_dir(self, project: dict) -> Path:
        return self._outputs_dir / project["slug"] / "notes"

    def add_research_note(self, topic: str, filename: str, content: str) -> dict:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            if not filename.strip():
                return {"error": "Note filename cannot be empty"}
            if not filename.endswith(".md"):
                filename += ".md"
            notes_dir = self.get_notes_dir(project)
            notes_dir.mkdir(parents=True, exist_ok=True)
            file_path = notes_dir / filename
            file_path.write_text(content, encoding="utf-8")
            project["updated_at"] = _utcnow()
            self._save()

            kg = get_graph()
            note_node = kg.get_node_by_label(filename)
            if note_node is None:
                note_node_id = kg.add_node("concept", filename, {"type": "note", "research_topic": topic})
            else:
                note_node_id = note_node["id"]
            research_node = kg.get_node_by_label(f"research:{topic}")
            if research_node:
                kg.add_edge_if_missing(research_node["id"], note_node_id, "has_note")

            get_operation_log().record(
                "write", "research", project["id"], f"{topic}/{filename}",
                details={"size": len(content)},
            )
            return {"filename": filename, "path": str(file_path), "size": len(content)}

    def list_research_notes(self, topic: str) -> list[dict]:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return []
            notes_dir = self.get_notes_dir(project)
            if not notes_dir.is_dir():
                return []
            notes = []
            for f in sorted(notes_dir.glob("*.md")):
                notes.append({
                    "filename": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "updated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
            return notes

    def add_generated_output(self, project: dict, file_path: str, fmt: str, chart_type: str | None = None) -> dict:
        with self._lock:
            out = {
                "id": "out_" + uuid.uuid4().hex[:8],
                "path": file_path,
                "format": fmt,
                "generated_at": _utcnow(),
            }
            if chart_type:
                out["chart_type"] = chart_type
            p = self._find_by_topic(project["topic"])
            if p:
                p["generated_outputs"].append(out)
                p["updated_at"] = _utcnow()
                self._save()
            return out

    def update_summary(self, topic: str, summary: str):
        with self._lock:
            project = self._find_by_topic(topic)
            if project:
                project["summary"] = summary
                project["updated_at"] = _utcnow()
                self._save()

    def link_conversation(self, topic: str, conversation_id: str):
        with self._lock:
            project = self._find_by_topic(topic)
            if project and conversation_id not in project["conversation_ids"]:
                project["conversation_ids"].append(conversation_id)
                project["updated_at"] = _utcnow()
                self._save()

    def promote_to_project(self, topic: str, project_name: str | None = None) -> dict:
        from backend.core.project_store import get_project_store
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            if project.get("moved_to_project"):
                return {"error": f"Research '{topic}' was already promoted to project '{project['moved_to_project']}' on {project.get('promoted_at', '')}. Use resume_project to access it."}

            base_name = (project_name or "").strip() or project["topic"]
            pstore = get_project_store()

            name = base_name
            suffix = 2
            created = pstore.create_project(name)
            while "error" in created and suffix <= 10:
                name = f"{base_name} (Research {suffix})"
                created = pstore.create_project(name)
                suffix += 1
            if "error" in created:
                return {"error": f"Could not create target project for promote: {created['error']}"}

            target = pstore.find_project_by_name(name)
            target_folder = pstore.projects_dir / target["folder"]
            target_folder.mkdir(parents=True, exist_ok=True)

            src_topic_dir = self._outputs_dir / project["slug"]
            copied = {"notes": [], "outputs": []}
            for sub in ("notes", "outputs"):
                src = src_topic_dir / sub
                dst = target_folder / sub
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.glob("*"):
                        if f.is_file():
                            shutil.copy2(str(f), str(dst / f.name))
                            copied[sub].append(f.name)

            for conv_id in project.get("conversation_ids", []):
                pstore.link_conversation(target["id"], conv_id)

            kg = get_graph()
            research_node = kg.get_node_by_label(f"research:{topic}")
            project_node = kg.get_node_by_label(f"project:{name}")
            if research_node and project_node:
                kg.add_edge_if_missing(research_node["id"], project_node["id"], "promoted_to")

            project["status"] = "completed"
            project["moved_to_project"] = name
            project["promoted_at"] = _utcnow()
            project["updated_at"] = _utcnow()
            self._save()

            if research_node:
                kg.set_status(research_node["label"], "completed")

            get_operation_log().record(
                "promote", "research", project["id"], topic,
                details={"project": name, "notes": len(copied["notes"]), "outputs": len(copied["outputs"])},
            )

            return {
                "topic": topic,
                "project": name,
                "project_id": target["id"],
                "folder": str(target_folder),
                "copied": copied,
                "status": "completed",
            }

    def get_active_task(self, topic: str) -> dict | None:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return None
            tasks = project.get("tasks", [])
            for t in tasks:
                if t["status"] == "in_progress":
                    return dict(t)
            for t in tasks:
                if t["status"] == "pending":
                    deps_met = True
                    for dep_title in t.get("depends_on", []):
                        dep = self._find_task_by_title(tasks, dep_title)
                        if not dep or dep["status"] != "completed":
                            deps_met = False
                            break
                    if deps_met:
                        return dict(t)
            return None

    def _find_task_by_title(self, tasks: list[dict], title: str) -> dict | None:
        q = title.strip().lower()
        for t in tasks:
            if t["title"].lower() == q:
                return t
        return None


_instance: ResearchStore | None = None
_instance_lock = threading.Lock()


def get_research_store() -> ResearchStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ResearchStore()
    return _instance
