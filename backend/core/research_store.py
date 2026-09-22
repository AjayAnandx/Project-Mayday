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


def _kw_overlap(query: str, stored: str) -> float:
    qt = set(re.findall(r"[a-z0-9_]+", query.lower()))
    st = set(re.findall(r"[a-z0-9_]+", stored.lower()))
    if not qt or not st:
        return 0.0
    overlap = len(qt & st)
    return overlap / max(len(qt), len(st))


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

        self._lock = threading.RLock()
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

    def _normalize_source(self, s):
        """Normalize a source entry: str url → dict, dict → canonical dict with defaults."""
        if isinstance(s, str):
            return {"url": s, "title": "", "doi": None, "score": 0.5, "published_date": "", "citationCount": None, "corpus": "web"}
        if isinstance(s, dict):
            url = str(s.get("url", "") or "")
            if not url and s.get("doi"):
                url = f"https://doi.org/{s['doi']}"
            return {
                "url": url,
                "title": str(s.get("title", "") or ""),
                "doi": s.get("doi"),
                "score": float(s.get("score", 0.5) or 0.5),
                "published_date": str(s.get("published_date", "") or s.get("publishedDate", "") or "")[:10],
                "citationCount": s.get("citationCount", s.get("cited_by_count")),
                "corpus": str(s.get("corpus", "web") or "web"),
            }
        return {"url": str(s), "title": "", "doi": None, "score": 0.5, "published_date": "", "citationCount": None, "corpus": "web"}

    def _normalize_projects(self):
        """Backfill defaults for older records (branching, source struct, run_count)."""
        for p in self._projects:
            p.setdefault("depth", 2)
            for t in p.get("tasks", []):
                t.setdefault("parent_task_id", None)
                t.setdefault("hypothesis", None)
                t.setdefault("branch_slug", _slugify(t.get("title", ""))[:48] if t.get("title") else None)
                t.setdefault("frozen", False)
                t.setdefault("run_count", 0)
                t.setdefault("children", [])
                t.setdefault("result", "")
                t.setdefault("result_summary", t.get("result", "")[:200])
                t.setdefault("sources", [])
            for key in ("data_points", "entities", "findings"):
                for item in p.get(key, []):
                    if "sources" in item and isinstance(item["sources"], list):
                        item["sources"] = [self._normalize_source(s) for s in item["sources"]]
            # ensure operations threshold warning
            try:
                from backend.core.operation_log import get_operation_log
                total = get_operation_log().query(limit=1)
                # cheap check via index length if available
                if len(self._projects) > 10000:
                    import logging as _lg
                    _lg.getLogger(__name__).warning("research_store: projects>10000 consider SQLite WAL (openresearch/src/store.rs:150)")
            except Exception:
                pass

    def _migrate_artifacts_if_needed(self):
        """Lazy auto-move: topics/{slug}/outputs → topics/{slug}/artifacts/{reports,figures,data}."""
        try:
            for p in self._projects:
                slug = p.get("slug", "")
                if not slug:
                    continue
                topic_dir = self._outputs_dir / slug
                outputs_dir = topic_dir / "outputs"
                artifacts_dir = topic_dir / "artifacts"
                if not outputs_dir.is_dir():
                    continue
                # if artifacts already has content, skip (idempotent)
                if artifacts_dir.is_dir() and any(artifacts_dir.iterdir()):
                    # still migrate any leftover chart_* that may be newer than artifacts
                    # check if outputs still has chart_* not in artifacts/figures
                    leftover = [e for e in outputs_dir.iterdir() if e.is_dir() and e.name.startswith("chart_")]
                    if not leftover and not any(f.name == "report.md" for f in outputs_dir.iterdir() if f.is_file()):
                        continue
                reports_dir = artifacts_dir / "reports"
                figures_dir = artifacts_dir / "figures"
                data_dir = artifacts_dir / "data"
                reports_dir.mkdir(parents=True, exist_ok=True)
                figures_dir.mkdir(parents=True, exist_ok=True)
                data_dir.mkdir(parents=True, exist_ok=True)
                moved = []
                for entry in list(outputs_dir.iterdir()):
                    try:
                        if entry.is_file():
                            if entry.name == "report.md":
                                target = reports_dir / entry.name
                                if not target.exists():
                                    shutil.move(str(entry), str(target))
                                    moved.append(f"report.md→artifacts/reports/")
                            elif entry.suffix.lower() in (".csv", ".pdf"):
                                target = data_dir / entry.name
                                if not target.exists():
                                    shutil.move(str(entry), str(target))
                                    moved.append(f"{entry.name}→artifacts/data/")
                            elif entry.suffix.lower() in (".json", ".html"):
                                # loose files → data
                                target = data_dir / entry.name
                                if not target.exists():
                                    shutil.move(str(entry), str(target))
                                    moved.append(entry.name)
                        elif entry.is_dir() and entry.name.startswith("chart_"):
                            target = figures_dir / entry.name
                            if not target.exists():
                                shutil.move(str(entry), str(target))
                                moved.append(f"{entry.name}→artifacts/figures/")
                    except OSError:
                        continue
                # also handle legacy report.pdf at outputs/report.pdf
                if moved:
                    try:
                        get_operation_log().record("migrate_artifacts", "research", p.get("id", ""), p.get("topic", ""), details={"moved": moved[:10]})
                    except Exception:
                        pass
                # remove empty outputs dir
                try:
                    if outputs_dir.is_dir() and not any(outputs_dir.iterdir()):
                        outputs_dir.rmdir()
                except OSError:
                    pass
        except Exception:
            pass

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._projects = data.get("projects", [])
                self._normalize_projects()
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        # auto-migrate before persisting
        try:
            self._migrate_artifacts_if_needed()
        except Exception:
            pass
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"projects": self._projects}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                tmp.replace(self._path)
            except OSError:
                # Windows lock fallback
                self._path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
                try:
                    tmp.unlink()
                except Exception:
                    pass
        except Exception:
            # last resort direct write
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

            near = [
                (p, _kw_overlap(topic, p.get("topic", ""))) for p in self._projects
                if p.get("topic", "").strip().lower() != topic.strip().lower()
            ]
            near = [x for x in near if x[1] >= 0.6]
            if near:
                near.sort(key=lambda x: -x[1])
                suggestions = ", ".join(f"'{p['topic']}' ({p['status']})" for p, _s in near[:3])
                return {
                    "error": (
                        f"A similar research topic already exists: {suggestions}. "
                        "Use resume_research to access it, or choose a different topic."
                    )
                }

            project_id = "res_" + uuid.uuid4().hex[:12]
            slug = _slugify(topic)

            full_titles = RESEARCH_TYPE_TASKS.get(research_type, [])
            # depth slicing: 1→2, 2→4, 3→all, 4→all (depth 4 reserves fan slots)
            depth_map = {1: 2, 2: 4, 3: len(full_titles), 4: len(full_titles)}
            slice_len = depth_map.get(depth, len(full_titles))
            task_titles = full_titles[: min(slice_len, len(full_titles))] if full_titles else []
            if not task_titles and full_titles:
                task_titles = full_titles[:2]
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
                    "result_summary": "",
                    "parent_task_id": None,
                    "hypothesis": None,
                    "branch_slug": _slugify(title)[:48],
                    "frozen": False,
                    "run_count": 0,
                    "children": [],
                    "sources": [],
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
            norm_sources = [self._normalize_source(s) for s in (sources or [])]
            dp = {
                "id": "dp_" + uuid.uuid4().hex[:8],
                "label": str(label) if label is not None else "",
                "value": str(value) if value is not None else "",
                "unit": str(unit) if unit else "",
                "confidence": str(confidence) if confidence else "medium",
                "sources": norm_sources,
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
            norm_sources = [self._normalize_source(s) for s in (sources or [])]
            ent = {
                "id": "ent_" + uuid.uuid4().hex[:8],
                "name": name,
                "type": entity_type,
                "description": description or "",
                "relevance": relevance or 0.5,
                "sources": norm_sources,
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
            norm_sources = [self._normalize_source(s) for s in (sources or [])]
            fin = {
                "id": "fin_" + uuid.uuid4().hex[:8],
                "content": content,
                "confidence": confidence or "medium",
                "sources": norm_sources,
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
        """Legacy outputs dir (kept for compatibility). New code should use get_reports_dir/get_figures_dir."""
        return self._outputs_dir / project["slug"] / "outputs"

    def get_artifacts_dir(self, project: dict) -> Path:
        return self._outputs_dir / project["slug"] / "artifacts"

    def get_reports_dir(self, project: dict) -> Path:
        return self.get_artifacts_dir(project) / "reports"

    def get_figures_dir(self, project: dict) -> Path:
        return self.get_artifacts_dir(project) / "figures"

    def get_data_dir(self, project: dict) -> Path:
        return self.get_artifacts_dir(project) / "data"

    def list_outputs(self, topic: str) -> list[dict]:
        """Unified list of artifacts: charts + reports + data. Supports both artifacts/ and legacy outputs/."""
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            outputs: list[dict] = []
            slug = project["slug"]
            # New artifacts layout
            artifacts_dir = self.get_artifacts_dir(project)
            figures_dir = self.get_figures_dir(project)
            reports_dir = self.get_reports_dir(project)
            data_dir = self.get_data_dir(project)
            # Collect figures (chart_*)
            for base in (figures_dir, self.get_outputs_dir(project)):
                if base.is_dir():
                    for entry in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
                        if not entry.is_dir() or not entry.name.startswith("chart_"):
                            continue
                        # dedup: if already collected from artifacts, skip legacy duplicate name
                        if any(o.get("dir") == entry.name for o in outputs):
                            continue
                        json_path = entry / "chart.json"
                        chart_type = ""
                        data_points = 0
                        if json_path.is_file():
                            try:
                                chart_json = json.loads(json_path.read_text(encoding="utf-8"))
                                chart_type = chart_json.get("type", "")
                                dp = chart_json.get("data", {}).get("labels", []) if isinstance(chart_json.get("data"), dict) else 0
                                if isinstance(dp, list):
                                    data_points = len(dp)
                            except Exception:
                                pass
                        # compute relative_url: check if entry is under artifacts/figures
                        if str(entry).replace("\\", "/").find("/artifacts/figures/") != -1:
                            rel = f"/research/{slug}/artifacts/figures/{entry.name}/index.html"
                        else:
                            rel = f"/research/{slug}/outputs/{entry.name}/index.html"
                        outputs.append({
                            "dir": entry.name,
                            "chart_type": chart_type or "unknown",
                            "data_points": data_points,
                            "html_path": str(entry / "index.html"),
                            "relative_url": rel,
                            "created_at": entry.name.replace("chart_", "").replace("_", ":"),
                            "kind": "chart",
                        })
            # Reports
            for base in (reports_dir, self.get_outputs_dir(project)):
                if base.is_dir():
                    for entry in base.iterdir():
                        if entry.is_file() and entry.name in ("report.md", "report.pdf"):
                            if any(o.get("filename") == entry.name and o.get("kind") == "report" for o in outputs):
                                continue
                            # determine url
                            if str(entry).find("artifacts") != -1:
                                rel = f"/research/{slug}/artifacts/reports/{entry.name}"
                            else:
                                rel = f"/research/{slug}/outputs/{entry.name}"
                            outputs.append({
                                "kind": "report",
                                "filename": entry.name,
                                "path": str(entry),
                                "relative_url": rel,
                                "size": entry.stat().st_size if entry.exists() else 0,
                            })
            # Data files (csv/pdf) under artifacts/data + outputs legacy loose csv
            for base in (data_dir, self.get_outputs_dir(project)):
                if base.is_dir():
                    for entry in base.iterdir():
                        if entry.is_file() and entry.suffix.lower() in (".csv", ".pdf") and entry.name not in ("report.md", "report.pdf"):
                            if any(o.get("filename") == entry.name and o.get("kind") == "data" for o in outputs):
                                continue
                            rel = f"/research/{slug}/artifacts/data/{entry.name}" if str(entry).find("artifacts") != -1 else f"/research/{slug}/outputs/{entry.name}"
                            outputs.append({
                                "kind": "data",
                                "filename": entry.name,
                                "path": str(entry),
                                "relative_url": rel,
                                "size": entry.stat().st_size if entry.exists() else 0,
                            })
            # Sort charts newest first, then reports/data by name
            charts = [o for o in outputs if o.get("kind") == "chart"]
            others = [o for o in outputs if o.get("kind") != "chart"]
            charts.sort(key=lambda x: x.get("dir", ""), reverse=True)
            # If only charts requested historically, return all; preserve backward compat: return full list but existing callers expecting chart list still work
            # For backward compat, if caller expects only charts, filter is done by caller; we return unified list sorted charts first
            # To keep old behavior for list_research_outputs expecting chart_* only, keep chart list separate but we return unified — caller updated to handle it
            return outputs if outputs else []

    def get_notes_dir(self, project: dict) -> Path:
        return self._outputs_dir / project["slug"] / "notes"

    def add_research_note(self, topic: str, filename: str, content: str, force: bool = False) -> dict:
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
            if file_path.exists() and not force:
                return {
                    "error": (
                        f"Note '{filename}' already exists for research '{topic}'. "
                        f"Pass force=True to overwrite it."
                    )
                }
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
            # force index refresh (best effort)
            try:
                from backend.core.research_index import get_research_index
                get_research_index().force_rebuild()
            except Exception:
                pass
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
            # force index refresh
            try:
                from backend.core.research_index import get_research_index
                get_research_index().force_rebuild()
            except Exception:
                pass
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
            copied = {"notes": [], "outputs": [], "artifacts": []}
            for sub in ("notes", "outputs", "artifacts"):
                src = src_topic_dir / sub
                dst = target_folder / sub
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(src)
                            dest_file = dst / rel
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(f), str(dest_file))
                            copied["artifacts" if sub == "artifacts" else sub].append(str(rel).replace("\\", "/"))
            # also ensure legacy outputs copied via artifacts fallback if needed
            if not copied["outputs"] and not copied["artifacts"]:
                # nothing copied, but keep structure
                pass

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
            # prefer in_progress that is not frozen
            for t in tasks:
                if t.get("frozen"):
                    continue
                if t["status"] == "in_progress":
                    # parent must be completed if has parent
                    pid = t.get("parent_task_id")
                    if pid:
                        parent = self._find_task_by_id(tasks, pid)
                        if parent and parent.get("status") not in ("completed", "in_progress"):
                            continue
                    return dict(t)
            for t in tasks:
                if t.get("frozen") or t["status"] != "pending":
                    continue
                # parent check: if has parent, parent must be completed or winner
                pid = t.get("parent_task_id")
                if pid:
                    parent = self._find_task_by_id(tasks, pid)
                    if not parent or parent.get("status") != "completed":
                        continue
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

    def _find_task_by_id(self, tasks: list[dict], task_id: str) -> dict | None:
        for t in tasks:
            if t.get("id") == task_id:
                return t
        return None

    def fan_hypothesis(self, topic: str, parent_task_id: str | None, hypotheses: list[str]) -> dict:
        """Branch a parent task into sibling hypothesis tasks (stacked-bushes fan)."""
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            if not hypotheses or not isinstance(hypotheses, list):
                return {"error": "hypotheses must be a non-empty list of strings (1-5)"}
            hypotheses = [h.strip() for h in hypotheses if h and h.strip()]
            if not hypotheses:
                return {"error": "hypotheses list empty after trimming"}
            if len(hypotheses) > 5:
                return {"error": "Fan limited to 5 hypotheses per parent (stacked bushes: fan a little). Use 2-3 recommended."}
            # resolve parent: if None, use first pending/completed? require explicit for now
            tasks = project.get("tasks", [])
            parent = None
            if parent_task_id:
                parent = self._find_task_by_id(tasks, parent_task_id) or self._find_task_by_title(tasks, parent_task_id)
                if not parent:
                    return {"error": f"Parent task '{parent_task_id}' not found"}
                if parent.get("frozen"):
                    return {"error": f"Parent task '{parent['title']}' is frozen — cannot branch"}
            else:
                # if no parent given, use first completed or active task as fan point
                parent = self.get_active_task(topic)
                # get_active_task returns pending, so find last completed instead
                if not parent:
                    # fallback to first task
                    parent = tasks[0] if tasks else None
                if not parent:
                    return {"error": "No parent task available for fanning"}
                # re-resolve to actual object in list
                parent = self._find_task_by_id(tasks, parent["id"]) if parent.get("id") else self._find_task_by_title(tasks, parent["title"])

            # OR cardinal: avoid flat fan (all children of root) and noodle (single child chain of co-equal)
            # We enforce parent not being root's direct sibling fan if already fanned?
            # Count existing children of this parent
            existing_children = [t for t in tasks if t.get("parent_task_id") == parent.get("id")]
            if len(existing_children) + len(hypotheses) > 5:
                return {"error": f"Parent '{parent['title']}' already has {len(existing_children)} children; adding {len(hypotheses)} would exceed 5 cap"}

            # check duplicate hypothesis titles
            new_tasks = []
            for h in hypotheses:
                slug = _slugify(h)[:48]
                # duplicate title check
                if self._find_task_by_title(tasks, h) or any(t.get("hypothesis") == h for t in tasks):
                    return {"error": f"Hypothesis '{h}' already exists as a task/hypothesis"}
                task = {
                    "id": "task_" + uuid.uuid4().hex[:8],
                    "title": h,
                    "description": f"Hypothesis branch of '{parent['title']}': {h}",
                    "type": "research",
                    "status": "pending",
                    "depends_on": [],
                    "result": "",
                    "result_summary": "",
                    "parent_task_id": parent.get("id"),
                    "hypothesis": h,
                    "branch_slug": slug,
                    "frozen": False,
                    "run_count": 0,
                    "children": [],
                    "sources": [],
                    "created_at": _utcnow(),
                    "updated_at": _utcnow(),
                }
                tasks.append(task)
                new_tasks.append(task)
            # link parent children
            parent.setdefault("children", []).extend([t["id"] for t in new_tasks])
            project["updated_at"] = _utcnow()
            self._save()
            # graph edges
            try:
                kg = get_graph()
                research_node = kg.get_node_by_label(f"research:{topic}")
                for t in new_tasks:
                    label = f"hypothesis:{topic}/{t['title']}"
                    node_id = kg.add_node("concept", label, {"type": "hypothesis", "research_topic": topic, "parent": parent.get("title", "")})
                    if research_node and node_id:
                        kg.add_edge_if_missing(research_node["id"], node_id, "has_hypothesis")
            except Exception:
                pass
            get_operation_log().record("fan_hypothesis", "research", project["id"], topic, details={"parent": parent.get("title", ""), "hypotheses": hypotheses, "new_ids": [t["id"] for t in new_tasks]})
            try:
                from backend.core.research_index import get_research_index
                get_research_index().force_rebuild()
            except Exception:
                pass
            return {"topic": topic, "parent": parent.get("title", ""), "parent_id": parent.get("id"), "tasks": [{"id": t["id"], "title": t["title"], "hypothesis": t["hypothesis"]} for t in new_tasks], "count": len(new_tasks)}

    def update_task_status(self, topic: str, task_id: str, status: str, result: str = "") -> dict:
        """Update research task status with frozen + run_count guards (OR cardinal)."""
        valid = {"pending", "in_progress", "completed", "blocked", "failed", "frozen"}
        if status not in valid:
            return {"error": f"Invalid status '{status}'. Must be one of {valid}"}
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            tasks = project.get("tasks", [])
            task = self._find_task_by_id(tasks, task_id) or self._find_task_by_title(tasks, task_id)
            if not task:
                return {"error": f"Task '{task_id}' not found in '{topic}'"}
            if task.get("frozen") and status != "frozen":
                return {"error": f"Task '{task['title']}' is frozen (winner answered) — cannot change"}
            old = task.get("status", "pending")
            # frozen transition: once completed + winner, freeze siblings
            if status == "completed" and old != "completed":
                task["status"] = "completed"
                task["updated_at"] = _utcnow()
                if result:
                    task["result"] = result[:2000]
                    task["result_summary"] = result[:200]
                # auto-freeze logic: if this task has siblings under same parent, freeze losing siblings that are not completed?
                # For now, do not auto-freeze — explicit freeze_task handles it. Just increment no.
            elif status in ("failed", "blocked"):
                # increment run_count and cap 2
                task["run_count"] = int(task.get("run_count", 0) or 0) + 1
                if task["run_count"] >= 2 and status == "failed":
                    task["status"] = "blocked"
                    task["updated_at"] = _utcnow()
                    if result:
                        task["result"] = result[:2000]
                    project["updated_at"] = _utcnow()
                    self._save()
                    return {"id": task["id"], "title": task["title"], "status": "blocked", "run_count": task["run_count"], "note": "Run cap 2 reached — ask user before retry (OR cardinal: 2 failing runs then ask)"}
                task["status"] = status
                task["updated_at"] = _utcnow()
                if result:
                    task["result"] = result[:2000]
            elif status == "frozen":
                task["frozen"] = True
                task["status"] = "frozen"
                task["updated_at"] = _utcnow()
            else:
                task["status"] = status
                task["updated_at"] = _utcnow()
                if result:
                    task["result"] = result[:2000]
                    task["result_summary"] = result[:200]
            project["updated_at"] = _utcnow()
            self._save()
            get_operation_log().record("update_task_status", "research", project["id"], f"{topic}/{task['title']}", details={"from": old, "to": task["status"], "run_count": task.get("run_count", 0)})
            try:
                from backend.core.research_index import get_research_index
                get_research_index().force_rebuild()
            except Exception:
                pass
            return {"id": task["id"], "title": task["title"], "status": task["status"], "frozen": task.get("frozen", False), "run_count": task.get("run_count", 0)}

    def freeze_task(self, topic: str, task_id: str) -> dict:
        return self.update_task_status(topic, task_id, "frozen")

    def list_tasks(self, topic: str, status: str | None = None) -> list[dict]:
        with self._lock:
            project = self._find_by_topic(topic)
            if not project:
                return {"error": f"Research '{topic}' not found"}
            tasks = project.get("tasks", [])
            if status:
                tasks = [t for t in tasks if t.get("status") == status]
            return [dict(t) for t in tasks]


_instance: ResearchStore | None = None
_instance_lock = threading.Lock()


def get_research_store() -> ResearchStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ResearchStore()
    return _instance
