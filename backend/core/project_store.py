import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.core.config import load_config
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

logger = logging.getLogger(__name__)


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


ARTIFACT_THRESHOLD = 2000
CHECKPOINT_STALE_HOURS = 24
LOG_ROTATE_LINES = 10000
LOG_KEEP_LINES = 5000
TRUST_CACHE_TTL = 5.0  # seconds

# ---------------------------------------------------------------------------
# Hook helpers — pure functions extracted for testability
# ---------------------------------------------------------------------------

def _default_summarize(result: str, max_len: int = 200) -> str:
    if not result:
        return ""
    first_line = result.strip().splitlines()[0] if result.strip() else ""
    if len(result) <= max_len:
        return first_line or result.strip()[:max_len]
    return (first_line[:max_len] if first_line else result.strip()[:max_len]) + "…"


class ProjectStore:
    def __init__(self):
        cfg = load_config()
        path = cfg.get("data", {}).get("projects_path", "projects.json")
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent.parent.parent / path)
        self._path = Path(path)
        cfg_projects = cfg.get("data", {}).get("projects_dir", "")
        if cfg_projects:
            self._projects_dir = Path(cfg_projects).resolve()
        else:
            self._projects_dir = Path(__file__).resolve().parent.parent.parent / "projects"
        self._lock = threading.Lock()
        self._projects: list[dict] = []
        # Hook system — deferred emit outside the lock
        self._hooks: dict[str, list] = {}
        self._hook_lock = threading.Lock()
        self._emit_state = threading.local()
        # Rec 1: trust-level cache (mtime + TTL)
        self._trust_cache_value: str | None = None
        self._trust_cache_mtime: float = 0.0
        self._trust_cache_time: float = 0.0
        self._trust_cache_lock = threading.Lock()
        # Rec 2: O(1) indexes for project id and exact name
        self._id_index: dict[str, int] = {}
        self._name_index: dict[str, int] = {}
        # Rec 3: batched save (debounce) — disabled by default, enabled via config
        self._batch_enabled = bool(cfg.get("projects", {}).get("batch_saves", False) or cfg.get("data", {}).get("batch_saves", False))
        self._save_timer: threading.Timer | None = None
        self._save_timer_lock = threading.Lock()
        self._load()
        self._init_projects_dir()
        self._register_default_hooks()
        self._rebuild_indexes()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _rebuild_indexes(self):
        self._id_index.clear()
        self._name_index.clear()
        for i, p in enumerate(self._projects):
            pid = p.get("id")
            if pid:
                self._id_index[pid] = i
            name = p.get("name", "")
            if name:
                self._name_index[name.lower()] = i

    def _update_index_for(self, project: dict, idx: int):
        pid = project.get("id")
        if pid:
            self._id_index[pid] = idx
        name = project.get("name", "")
        if name:
            self._name_index[name.lower()] = idx

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._projects = data.get("projects", [])
                # Normalize old projects (additive fields with defaults)
                # Use cached trust to avoid repeated config reads during _load loop
                default_trust = None
                for p in self._projects:
                    if default_trust is None:
                        default_trust = self._get_trust_level(None)
                    p.setdefault("active_checkpoint", None)
                    p.setdefault("token_usage", 0)
                    p.setdefault("cost_usd", 0.0)
                    p.setdefault("process_handles", [])
                    p.setdefault("trust_level", default_trust)
                    p.setdefault("conversation_ids", [])
                    p.setdefault("tasks", [])
                    p.setdefault("data_points", [])
                    for t in p.get("tasks", []):
                        t.setdefault("result_summary", t.get("result", "")[:200])
                        t.setdefault("result_artifact", "")
                        t.setdefault("parent_task_id", None)
                        t.setdefault("subtasks", [])
                        t.setdefault("owner", "user")
                self._rebuild_indexes()
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("projects.json corrupt (%s) — attempting replay from task_events.log", e)
                recovered = self._replay_all_from_logs()
                if recovered is not None:
                    self._projects = recovered
                    try:
                        self._save(force=True)
                    except Exception:
                        pass
                    self._rebuild_indexes()
                else:
                    self._projects = []

    def _save(self, force: bool = False):
        # Rec 3: debounced batch save — coalesce rapid _save() bursts within 50 ms
        if self._batch_enabled and not force:
            with self._save_timer_lock:
                if self._save_timer is not None:
                    self._save_timer.cancel()
                self._save_timer = threading.Timer(0.05, self._save, kwargs={"force": True})
                self._save_timer.daemon = True
                self._save_timer.start()
                return
        with self._save_timer_lock:
            if self._save_timer is not None:
                try:
                    self._save_timer.cancel()
                except Exception:
                    pass
                self._save_timer = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # atomic write via temp file + rename to avoid torn reads
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"projects": self._projects}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            tmp.replace(self._path)
        except Exception:
            # fallback if replace fails (Windows lock)
            self._path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                tmp.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Append-only event log (A1)
    # ------------------------------------------------------------------

    def _event_log_path(self, folder: str) -> Path:
        return self._projects_dir / folder / "task_events.log"

    def _append_event(self, folder: str, event_type: str, payload: dict):
        try:
            log_path = self._event_log_path(folder)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            event = {"event_type": event_type, "timestamp": _utcnow(), **payload}
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            # Rec 6: log rotation — keep task_events.log bounded
            try:
                # cheap line count via file size heuristic; full count only when large
                if log_path.stat().st_size > 512 * 1024:  # >512 KB, check lines
                    # count quickly; if over threshold, rotate
                    with log_path.open("r", encoding="utf-8") as rf:
                        # fast count by iterating
                        lines = sum(1 for _ in rf)
                    if lines > LOG_ROTATE_LINES:
                        # snapshot current projects entry then trim log to last LOG_KEEP_LINES
                        with log_path.open("r", encoding="utf-8") as rf:
                            all_lines = rf.read().splitlines()
                        keep = all_lines[-LOG_KEEP_LINES:]
                        # write trimmed + also snapshot to .1 archived log
                        archive = log_path.with_suffix(".log.1")
                        try:
                            archive.write_text("\n".join(all_lines[:-LOG_KEEP_LINES]) + "\n", encoding="utf-8")
                        except Exception:
                            pass
                        log_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
                        logger.info("Rotated task_events.log for %s: %d -> %d lines", folder, lines, len(keep))
            except Exception as e:
                logger.debug("Log rotation check failed for %s: %s", folder, e)
        except Exception as e:
            logger.warning("Failed to append event %s for folder %s: %s", event_type, folder, e)

    def replay_events(self, folder: str) -> dict | None:
        """Rebuild a single project dict from its task_events.log. Returns None if no log."""
        log_path = self._event_log_path(folder)
        if not log_path.exists():
            return None
        try:
            project = None
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                et = ev.get("event_type", "")
                if et == "project.created":
                    project = {
                        "id": ev.get("project_id", ""),
                        "name": ev.get("name", ""),
                        "status": ev.get("status", "active"),
                        "description": ev.get("description", ""),
                        "created_at": ev.get("timestamp", _utcnow()),
                        "last_activity": ev.get("timestamp", _utcnow()),
                        "folder": folder,
                        "conversation_ids": [],
                        "tasks": [],
                        "data_points": [],
                        "active_checkpoint": None,
                        "token_usage": 0,
                        "cost_usd": 0.0,
                        "process_handles": [],
                    }
                elif project is None:
                    continue
                elif et == "task.added":
                    task = ev.get("task", {})
                    if task:
                        project.setdefault("tasks", []).append(task)
                    project["last_activity"] = ev.get("timestamp", project["last_activity"])
                elif et == "task.status":
                    tid = ev.get("task_id", "")
                    for t in project.get("tasks", []):
                        if t.get("id") == tid:
                            t["status"] = ev.get("status", t["status"])
                            if ev.get("result") is not None:
                                t["result"] = ev["result"]
                            if ev.get("result_summary") is not None:
                                t["result_summary"] = ev["result_summary"]
                            if ev.get("result_artifact") is not None:
                                t["result_artifact"] = ev["result_artifact"]
                            t["updated_at"] = ev.get("timestamp", t.get("updated_at", ""))
                            break
                    project["last_activity"] = ev.get("timestamp", project["last_activity"])
                elif et == "project.status":
                    project["status"] = ev.get("status", project["status"])
                    project["last_activity"] = ev.get("timestamp", project["last_activity"])
                elif et == "project.data_point":
                    dp = ev.get("data_point")
                    if dp:
                        project.setdefault("data_points", []).append(dp)
                elif et == "project.document":
                    doc_id = ev.get("doc_id", "")
                    if doc_id:
                        project.setdefault("documents", [])
                        if doc_id not in project["documents"]:
                            project["documents"].append(doc_id)
                elif et == "project.conversation_linked":
                    cid = ev.get("conversation_id", "")
                    if cid:
                        project.setdefault("conversation_ids", [])
                        if cid not in project["conversation_ids"]:
                            project["conversation_ids"].append(cid)
                elif et == "project.checkpoint":
                    project["active_checkpoint"] = ev.get("checkpoint")
                elif et == "project.checkpoint_cleared":
                    project["active_checkpoint"] = None
                elif et == "project.metrics":
                    project["token_usage"] = project.get("token_usage", 0) + ev.get("tokens", 0)
                    project["cost_usd"] = round(project.get("cost_usd", 0.0) + ev.get("cost", 0.0), 6)
                elif et == "project.process_registered":
                    pid = ev.get("pid")
                    if pid is not None:
                        project.setdefault("process_handles", [])
                        if pid not in project["process_handles"]:
                            project["process_handles"].append(pid)
                elif et == "project.process_unregistered":
                    pid = ev.get("pid")
                    if pid is not None and pid in project.get("process_handles", []):
                        project["process_handles"].remove(pid)
            return project
        except Exception as e:
            logger.warning("replay_events failed for %s: %s", folder, e)
            return None

    def _replay_all_from_logs(self) -> list[dict] | None:
        if not self._projects_dir.is_dir():
            return None
        recovered = []
        for entry in sorted(self._projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            log_path = entry / "task_events.log"
            if not log_path.exists():
                continue
            proj = self.replay_events(entry.name)
            if proj and proj.get("id"):
                recovered.append(proj)
        return recovered if recovered else None

    # ------------------------------------------------------------------
    # Hooks (C1 — deferred emit outside the lock)
    # ------------------------------------------------------------------

    def register_hook(self, event: str, callback):
        with self._hook_lock:
            self._hooks.setdefault(event, []).append(callback)

    def emit_hook(self, event: str, data: dict):
        st = self._emit_state
        if getattr(st, "depth", 0) > 0:
            if not hasattr(st, "queue"):
                st.queue = []
            st.queue.append((event, data))
            return
        st.depth = 1
        st.queue = []
        try:
            self._run_hooks(event, data)
            while st.queue:
                ev, d = st.queue.pop(0)
                self._run_hooks(ev, d)
        finally:
            st.depth = 0
            st.queue = []

    def _run_hooks(self, event: str, data: dict):
        with self._hook_lock:
            callbacks = list(self._hooks.get(event, []))
        for cb in callbacks:
            try:
                cb(data)
            except Exception as e:
                logger.warning("Hook %s callback failed: %s", event, e)

    def _register_default_hooks(self):
        def _op_log_hook(data: dict):
            et = data.get("_op_action", "")
            if not et:
                return
            get_operation_log().record(
                data.get("_op_action", ""),
                data.get("_op_entity_type", "project"),
                data.get("_op_entity_id", ""),
                data.get("_op_entity_name", ""),
                details=data.get("_op_details", {}),
            )

        def _kg_project_hook(data: dict):
            if data.get("event") == "project.created":
                kg = get_graph()
                kg.add_node("project", f"project:{data.get('name', '')}", {"id": data.get("project_id", ""), "status": "active"})
            elif data.get("event") == "project.status":
                kg = get_graph()
                kg.add_node("project", f"project:{data.get('name', '')}", {"id": data.get("project_id", ""), "status": data.get("status", "")})

        self.register_hook("project.created", lambda d: _op_log_hook(d) or _kg_project_hook(d))
        self.register_hook("project.status", lambda d: _op_log_hook(d) or _kg_project_hook(d))
        self.register_hook("task.added", lambda d: _op_log_hook(d))
        self.register_hook("task.post_transition", lambda d: _op_log_hook(d))
        self.register_hook("project.data_point", lambda d: _op_log_hook(d))
        self.register_hook("project.document", lambda d: None)
        self.register_hook("project.conversation_linked", lambda d: None)
        # Graph sync for task result — separate hook so it can be tested
        def _kg_task_result(d: dict):
            if d.get("result"):
                try:
                    kg = get_graph()
                    proj_name = d.get("project_name", "")
                    node_label = f"task:{proj_name}/{d.get('task_title', '')}"
                    kg.add_node("concept", node_label, {"type": "task_result", "project": proj_name, "task_title": d.get("task_title", "")})
                    project_node = kg.get_node_by_label(f"project:{proj_name}")
                    task_node = kg.get_node_by_label(node_label)
                    if project_node and task_node:
                        kg.add_edge_if_missing(project_node["id"], task_node["id"], "has_task_result")
                except Exception as e:
                    logger.warning("task result graph sync failed: %s", e)
        self.register_hook("task.post_transition", _kg_task_result)
        # C2: file.written hook — invariant warnings (no hard block, just log for observability)
        def _file_written_hook(data: dict):
            try:
                path = data.get("path", "")
                content = data.get("content", "") or ""
                if path.endswith("src/index.css") and content and not content.lstrip().startswith('@import "tailwindcss"'):
                    logger.warning("file.written invariant: src/index.css missing @import \"tailwindcss\" first line: %s", path)
                if "vite.config.ts" in path and content and "tailwindcss" not in content:
                    logger.warning("file.written invariant: vite.config.ts missing tailwindcss import: %s", path)
                # theme token drift: if App.tsx uses custom colors but index.css missing token, warn
                if path.endswith("src/App.tsx") and ("bg-midnight" in content or "bg-neon-mint" in content):
                    # try to check index.css exists
                    try:
                        # derive project dir from path
                        from pathlib import Path as _P
                        p = _P(path)
                        # find project folder (parent of src)
                        proj_dir = None
                        for parent in p.parents:
                            if (parent / "src" / "index.css").exists():
                                proj_dir = parent
                                break
                            if parent.name == "src" and (parent.parent / "src" / "index.css").exists():
                                proj_dir = parent.parent
                                break
                        if proj_dir is not None:
                            idx_css = proj_dir / "src" / "index.css"
                            if idx_css.exists():
                                css = idx_css.read_text(encoding="utf-8", errors="ignore")
                                if "bg-midnight" in content and "--color-midnight" not in css:
                                    logger.warning("file.written invariant: App.tsx uses bg-midnight but index.css missing --color-midnight @theme token")
                                if "bg-neon-mint" in content and "--color-neon-mint" not in css:
                                    logger.warning("file.written invariant: App.tsx uses bg-neon-mint but index.css missing --color-neon-mint token")
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("file.written hook error: %s", e)
        self.register_hook("file.written", _file_written_hook)

    # ------------------------------------------------------------------
    # Checkpoint (A2)
    # ------------------------------------------------------------------

    def set_checkpoint(self, project_id: str, task_id: str, iteration: int, last_tool: str = "", partial_result: str = "") -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            project = self._projects[idx]
            cp = {
                "task_id": task_id,
                "iteration": iteration,
                "last_tool": last_tool,
                "partial_result": (partial_result or "")[:500],
                "updated_at": _utcnow(),
            }
            project["active_checkpoint"] = cp
            self._save()
            folder = project.get("folder", "")
        self._append_event(folder, "project.checkpoint", {"project_id": project_id, "checkpoint": cp})
        self.emit_hook("project.checkpoint", {"project_id": project_id, "checkpoint": cp})
        return cp

    def clear_checkpoint(self, project_id: str):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return
            project = self._projects[idx]
            project["active_checkpoint"] = None
            self._save()
            folder = project.get("folder", "")
        self._append_event(folder, "project.checkpoint_cleared", {"project_id": project_id})
        self.emit_hook("project.checkpoint_cleared", {"project_id": project_id})

    def get_checkpoint(self, project_id: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            return (self._projects[idx].get("active_checkpoint") or None)

    # ------------------------------------------------------------------
    # Runtime metrics + process handles (A4)
    # ------------------------------------------------------------------

    def add_token_usage(self, project_id: str, tokens: int, cost: float = 0.0) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            project = self._projects[idx]
            project["token_usage"] = int(project.get("token_usage", 0) or 0) + int(tokens or 0)
            project["cost_usd"] = round(float(project.get("cost_usd", 0.0) or 0.0) + float(cost or 0.0), 6)
            self._save()
            folder = project.get("folder", "")
            tu = project["token_usage"]
            cu = project["cost_usd"]
        self._append_event(folder, "project.metrics", {"project_id": project_id, "tokens": tokens, "cost": cost})
        return {"token_usage": tu, "cost_usd": cu}

    def register_process(self, project_id: str, pid: int):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return False
            project = self._projects[idx]
            handles = project.get("process_handles")
            if handles is None:
                project["process_handles"] = []
                handles = project["process_handles"]
            if pid not in handles:
                handles.append(pid)
            self._save()
            folder = project.get("folder", "")
        self._append_event(folder, "project.process_registered", {"project_id": project_id, "pid": pid})
        return True

    def unregister_process(self, project_id: str, pid: int):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return False
            project = self._projects[idx]
            handles = project.get("process_handles", [])
            if pid in handles:
                handles.remove(pid)
            self._save()
            folder = project.get("folder", "")
        self._append_event(folder, "project.process_unregistered", {"project_id": project_id, "pid": pid})
        return True

    def get_runtime_state(self, project_id: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            p = self._projects[idx]
            return {
                "token_usage": int(p.get("token_usage", 0) or 0),
                "cost_usd": float(p.get("cost_usd", 0.0) or 0.0),
                "process_handles": list(p.get("process_handles", []) or []),
                "active_checkpoint": p.get("active_checkpoint"),
            }

    # ------------------------------------------------------------------
    # Artifact / result compaction (B1/B2)
    # ------------------------------------------------------------------

    def _store_result(
        self, project: dict, task: dict, result: str
    ) -> tuple[str, str, str]:
        if not result:
            return "", "", ""
        if len(result) > ARTIFACT_THRESHOLD:
            folder = project.get("folder", "unknown")
            task_id = task.get("id", "unknown")
            artifact_dir = self._projects_dir / folder / "tasks" / task_id
            try:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                artifact_path = artifact_dir / "result.md"
                artifact_path.write_text(result, encoding="utf-8")
                rel = f"tasks/{task_id}/result.md"
                summary = _default_summarize(result)
                task["result_summary"] = summary
                task["result_artifact"] = str(artifact_path)
                task["result"] = summary
                return summary, str(artifact_path), rel
            except Exception as e:
                logger.warning("Artifact write failed, storing inline: %s", e)
                task["result"] = result
                return result, "", ""
        else:
            task["result"] = result
            return result, "", ""

    def get_task_result(self, project_id: str, task_id: str) -> str | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            project = self._projects[idx]
            t_idx = self._find_task_index(project, task_id)
            if t_idx is None:
                for t in project.get("tasks", []):
                    if t.get("title", "").strip().lower() == task_id.strip().lower():
                        t_idx = project["tasks"].index(t)
                        break
                if t_idx is None:
                    return None
            task = project["tasks"][t_idx]
            artifact = task.get("result_artifact", "")
            if artifact:
                try:
                    p = Path(artifact)
                    if p.is_file():
                        return p.read_text(encoding="utf-8")
                except Exception:
                    pass
            return task.get("result", "")

    def _summarize(self, result: str) -> str:
        return _default_summarize(result)

    # ------------------------------------------------------------------
    # Trust / permissions (C2)
    # ------------------------------------------------------------------

    def _get_trust_level(self, project: dict | None = None) -> str:
        if project and project.get("trust_level"):
            return str(project["trust_level"]).lower()
        # Rec 1: cached config read — avoid re-parsing config.yaml on every trust check
        if not hasattr(self, "_trust_cache_lock"):
            self._trust_cache_value = None
            self._trust_cache_mtime = 0.0
            self._trust_cache_time = 0.0
            self._trust_cache_lock = threading.Lock()
        now = time.monotonic()
        with self._trust_cache_lock:
            # check TTL + mtime
            try:
                cfg_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
                mtime = cfg_path.stat().st_mtime if cfg_path.exists() else 0
            except Exception:
                mtime = 0
            if self._trust_cache_value is not None and (now - self._trust_cache_time) < TRUST_CACHE_TTL and mtime == self._trust_cache_mtime:
                return self._trust_cache_value
            try:
                cfg = load_config()
                raw = cfg.get("project_trust", cfg.get("projects", {}).get("trust", "medium"))
                val = str(raw or "medium").lower()
            except Exception:
                val = "medium"
            self._trust_cache_value = val
            self._trust_cache_mtime = mtime
            self._trust_cache_time = now
            return val

    def _check_trust(self, action: str, project: dict | None = None, trust_override: str | None = None) -> dict | None:
        level = (trust_override or self._get_trust_level(project)).lower()
        gated = {"scrap", "scrapped", "force_overwrite", "force_duplicate"}
        if action in gated and level == "low":
            return {"error": f"Action '{action}' requires confirmation at trust level 'low'. Pass confirmed=True to proceed.", "requires_confirmation": True}
        return None

    # ------------------------------------------------------------------
    # Context assembly (D1)
    # ------------------------------------------------------------------

    def assemble_project_context(self, project_id: str) -> dict:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return {"error": f"Project '{project_id}' not found"}
            project = dict(self._projects[idx])
            # shallow copy tasks to avoid mutation outside lock
            tasks_copy = [dict(t) for t in project.get("tasks", [])]
            project["tasks"] = tasks_copy

        # Outside lock for I/O
        folder = project.get("folder", "")
        files = []
        try:
            from backend.core.project_index import get_project_index
            files = get_project_index().search(folder, limit=5) if folder else []
            if not files:
                # fallback: list files directly
                proj_dir = self._projects_dir / folder if folder else None
                if proj_dir and proj_dir.is_dir():
                    for entry in sorted(proj_dir.iterdir(), key=lambda p: p.name)[:10]:
                        if entry.is_file():
                            files.append({"filename": entry.name, "rel_path": entry.name})
                        elif entry.is_dir() and entry.name not in ("node_modules", ".git"):
                            files.append({"filename": entry.name + "/", "rel_path": entry.name + "/"})
        except Exception:
            pass

        open_tasks = [t for t in tasks_copy if t.get("status") in ("pending", "in_progress")]
        in_progress = [t for t in tasks_copy if t.get("status") == "in_progress"]
        active_task = self.get_active_task(project_id)

        active_skill = None
        try:
            from backend.assistant.skill_manager import get_skill_manager
            sm = get_skill_manager()
            if active_task:
                sk = sm.get_skill_by_task_type(active_task.get("type", ""))
                if sk:
                    active_skill = {"name": sk.name, "description": sk.description}
        except Exception:
            pass

        recent_ops = []
        try:
            ops = get_operation_log().query(entity_type="project", query=project.get("name", ""), limit=5)
            if not ops:
                ops = get_operation_log().query(limit=5)
            recent_ops = [{"action": o.get("action"), "entity_name": o.get("entity_name"), "timestamp": o.get("timestamp", "")[:16]} for o in (ops or [])[:5]]
        except Exception:
            pass

        runtime = self.get_runtime_state(project_id) or {}
        checkpoint = project.get("active_checkpoint")
        # clear stale checkpoint display (older than 24h)
        if checkpoint:
            try:
                ts = checkpoint.get("updated_at", "")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if datetime.now(timezone.utc) - dt > timedelta(hours=CHECKPOINT_STALE_HOURS):
                        checkpoint = None
            except Exception:
                pass

        return {
            "project": {"id": project.get("id"), "name": project.get("name"), "status": project.get("status"), "folder": folder, "description": project.get("description", "")},
            "files": files[:10],
            "tasks": {"total": len(tasks_copy), "completed": sum(1 for t in tasks_copy if t["status"] == "completed"), "open": open_tasks[:5], "in_progress": in_progress[:3]},
            "active_task": active_task,
            "active_skill": active_skill,
            "recent_operations": recent_ops,
            "runtime": runtime,
            "checkpoint": checkpoint,
        }

    def format_context_block(self, project_id: str) -> str:
        ctx = self.assemble_project_context(project_id)
        if "error" in ctx:
            return ""
        proj = ctx.get("project", {})
        tasks = ctx.get("tasks", {})
        lines = [f"### Active Project: {proj.get('name', '')} ({proj.get('status', '')})"]
        if proj.get("description"):
            lines.append(f"Goal: {proj['description']}")
        lines.append(f"Folder: {proj.get('folder', '')}")
        total = tasks.get("total", 0)
        completed = tasks.get("completed", 0)
        lines.append(f"Tasks: {completed}/{total} complete")
        active = ctx.get("active_task")
        if active:
            lines.append(f"Next: {active['title']} ({active.get('status', '')})")
        if ctx.get("active_skill"):
            lines.append(f"Active skill: {ctx['active_skill']['name']}")
        rt = ctx.get("runtime", {})
        if rt.get("token_usage") or rt.get("cost_usd"):
            lines.append(f"Tokens: {rt.get('token_usage', 0)} cost: ${rt.get('cost_usd', 0.0):.4f}")
        if rt.get("process_handles"):
            lines.append(f"Processes: {rt['process_handles']}")
        cp = ctx.get("checkpoint")
        if cp:
            lines.append(f"Checkpoint: task {cp.get('task_id', '')} iter {cp.get('iteration', '')} last_tool={cp.get('last_tool', '')}")
        if ctx.get("files"):
            fnames = ", ".join(f.get("filename", "") for f in ctx["files"][:5])
            if fnames:
                lines.append(f"Files: {fnames}")
        if ctx.get("recent_operations"):
            lines.append("Recent ops: " + "; ".join(f"{o['action']} {o['entity_name']}" for o in ctx["recent_operations"][:3]))
        lines.append("###")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Existing helpers
    # ------------------------------------------------------------------

    @property
    def projects_dir(self) -> Path:
        return self._projects_dir

    def _init_projects_dir(self):
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def _find_index(self, project_id: str) -> int | None:
        # Rec 2: O(1) exact via index, fallback to scan for stale/migrated ids
        if not hasattr(self, "_id_index"):
            self._id_index = {}
            self._name_index = {}
            self._rebuild_indexes()
        idx = self._id_index.get(project_id)
        if idx is not None and idx < len(self._projects) and self._projects[idx].get("id") == project_id:
            return idx
        for i, p in enumerate(self._projects):
            if p["id"] == project_id:
                # heal index
                self._id_index[project_id] = i
                return i
        return None

    def _auto_pause(self, project: dict) -> bool:
        if project["status"] != "active":
            return False
        # clear stale checkpoint if paused
        try:
            last = datetime.fromisoformat(project["last_activity"])
            now = datetime.now(timezone.utc)
            if (now - last).days >= 30:
                project["status"] = "paused"
                # clear stale checkpoint
                if project.get("active_checkpoint"):
                    try:
                        cp_ts = project["active_checkpoint"].get("updated_at", "")
                        if cp_ts:
                            cp_dt = datetime.fromisoformat(cp_ts)
                            if (now - cp_dt) > timedelta(hours=CHECKPOINT_STALE_HOURS):
                                project["active_checkpoint"] = None
                    except Exception:
                        pass
                folder = project.get("folder", "")
                # record via hook path (outside lock if needed) — but we're inside lock here, so append directly
                try:
                    get_operation_log().record(
                        "pause", "project", project["id"], project["name"],
                        details={"reason": "30d inactive"},
                    )
                except Exception:
                    pass
                if folder:
                    try:
                        self._append_event(folder, "project.status", {"project_id": project["id"], "name": project["name"], "status": "paused"})
                    except Exception:
                        pass
                return True
        except (ValueError, TypeError):
            pass
        return False

    def create_project(self, name: str, tasks: list[dict] | None = None, description: str = "") -> dict:
        blocked_project = None
        with self._lock:
            if not hasattr(self, "_name_index"):
                self._id_index = {}
                self._name_index = {}
                self._rebuild_indexes()
            name = name.strip()
            if not name:
                return {"error": "Project name cannot be empty"}

            # Rec 2: O(1) exact duplicate via name index
            idx_exact = self._name_index.get(name.lower())
            if idx_exact is not None and idx_exact < len(self._projects):
                cand = self._projects[idx_exact]
                if cand["name"].lower() == name.lower() and cand["status"] in ("active", "paused"):
                    return {"error": f"Project '{name}' already exists (status: {cand['status']}). Use resume_project to access it."}
            # fallback scan for case where index stale
            existing = [p for p in self._projects if p["name"].lower() == name.lower()]
            active = [p for p in existing if p["status"] in ("active", "paused")]
            if active:
                return {"error": f"Project '{name}' already exists (status: {active[0]['status']}). Use resume_project to access it."}

            near = [
                (p, _kw_overlap(name, p["name"])) for p in self._projects
                if p["status"] in ("active", "paused") and p["name"].lower() != name.lower()
            ]
            near = [x for x in near if x[1] >= 0.6]
            if near:
                near.sort(key=lambda x: -x[1])
                suggestions = ", ".join(f"'{p['name']}' ({p['status']})" for p, _s in near[:3])
                return {
                    "error": (
                        f"A similar project already exists: {suggestions}. "
                        "Use resume_project to access it, or choose a different name."
                    )
                }

            project_id = "proj_" + uuid.uuid4().hex[:12]
            folder_name = _slugify(name)
            folder_path = self._projects_dir / folder_name

            project = {
                "id": project_id,
                "name": name,
                "status": "active",
                "description": description.strip(),
                "created_at": _utcnow(),
                "last_activity": _utcnow(),
                "folder": folder_name,
                "conversation_ids": [],
                "tasks": [],
                "data_points": [],
                "active_checkpoint": None,
                "token_usage": 0,
                "cost_usd": 0.0,
                "process_handles": [],
                "trust_level": self._get_trust_level(None),
            }
            self._projects.append(project)
            idx_new = len(self._projects) - 1
            self._update_index_for(project, idx_new)
            self._save()

            folder_path.mkdir(parents=True, exist_ok=True)

        # Emit outside lock
        self._append_event(folder_name, "project.created", {
            "project_id": project_id, "name": name, "status": "active", "description": description.strip()
        })
        self.emit_hook("project.created", {
            "event": "project.created",
            "project_id": project_id, "name": name, "status": "active", "description": description.strip(),
            "_op_action": "create", "_op_entity_type": "project", "_op_entity_id": project_id, "_op_entity_name": name, "_op_details": {"folder": folder_name}
        })

        if tasks:
            for t in tasks:
                self._add_task_inner(project_id, t.get("title", ""), t.get("type", "general"), t.get("depends_on", []), t.get("description", ""), parent_task_id=t.get("parent_task_id"), owner=t.get("owner", "user"))

        with self._lock:
            idx = self._find_index(project_id)
            if idx is not None:
                return dict(self._projects[idx])
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
            if not hasattr(self, "_name_index"):
                self._id_index = {}
                self._name_index = {}
                self._rebuild_indexes()
            key = name.strip().lower()
            # Rec 2: O(1) exact via name index
            idx = self._name_index.get(key)
            if idx is not None and idx < len(self._projects):
                cand = self._projects[idx]
                if cand.get("name", "").lower() == key:
                    self._auto_pause(cand)
                    return dict(cand)
            # fallback fuzzy scan
            best: dict | None = None
            best_score = 0.0
            for p in self._projects:
                if p["name"].lower() == key:
                    self._auto_pause(p)
                    # heal index
                    self._name_index[key] = self._projects.index(p)
                    return dict(p)
                score = _kw_overlap(key, p["name"])
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

    def update_project_status(self, project_id: str, new_status: str, confirmed: bool = False) -> dict | None:
        # trust check needs project — peek without holding lock long
        with self._lock:
            idx0 = self._find_index(project_id)
            _proj0 = self._projects[idx0] if idx0 is not None else None
        if new_status == "scrapped" and not confirmed:
            trust_err = self._check_trust("scrap", project=_proj0)
            if trust_err:
                return trust_err
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            old_status = self._projects[idx]["status"]
            self._projects[idx]["status"] = new_status
            self._projects[idx]["last_activity"] = _utcnow()
            if new_status == "scrapped":
                self._projects[idx]["active_checkpoint"] = None
            self._save()
            name = self._projects[idx]["name"]
            folder = self._projects[idx].get("folder", "")

        self._append_event(folder, "project.status", {"project_id": project_id, "name": name, "status": new_status, "from": old_status})
        self.emit_hook("project.status", {
            "event": "project.status",
            "project_id": project_id, "name": name, "status": new_status, "from": old_status,
            "_op_action": new_status if new_status != "active" else "resume",
            "_op_entity_type": "project", "_op_entity_id": project_id, "_op_entity_name": name,
            "_op_details": {"from": old_status, "to": new_status}
        })

        with self._lock:
            idx = self._find_index(project_id)
            if idx is not None:
                return dict(self._projects[idx])
            return None

    def update_project_name(self, project_id: str, new_name: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            old_name = self._projects[idx].get("name", "")
            if old_name:
                self._name_index.pop(old_name.lower(), None)
            self._projects[idx]["name"] = new_name.strip()
            self._name_index[new_name.strip().lower()] = idx
            self._save()
            return dict(self._projects[idx])

    def _find_task_index(self, project: dict, task_id: str) -> int | None:
        for i, t in enumerate(project.get("tasks", [])):
            if t["id"] == task_id:
                return i
        return None

    def _find_task_by_title(self, project: dict, title: str) -> dict | None:
        title_lower = title.strip().lower()
        for t in project.get("tasks", []):
            if t["title"].lower() == title_lower:
                return t
        return None

    def _find_task_by_id_or_title(self, project: dict, task_id: str) -> dict | None:
        for t in project.get("tasks", []):
            if t["id"] == task_id:
                return t
        # fallback by title
        return self._find_task_by_title(project, task_id)

    def _check_circular_dep(self, project: dict, title: str, depends_on: list[str], depth: int = 0) -> bool:
        if depth > 10:
            return True
        for dep_title in depends_on:
            dep = self._find_task_by_title(project, dep_title)
            if dep and dep.get("depends_on"):
                if title.lower() == dep_title.lower():
                    return True
                if self._check_circular_dep(project, title, dep["depends_on"], depth + 1):
                    return True
        return False

    def _add_task_inner(self, project_id: str, title: str, type: str = "general", depends_on: list[str] | None = None, description: str = "", force: bool = False, parent_task_id: str | None = None, owner: str = "user", confirmed: bool = False) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return {"error": "Project not found"}
            project = self._projects[idx]
            if project.get("tasks") is None:
                project["tasks"] = []

            title = title.strip()
            if not title:
                return {"error": "Task title cannot be empty"}

            if not force and self._find_task_by_title(project, title):
                return {
                    "error": (
                        f"Task '{title}' already exists in project '{project['name']}'. "
                        f"Pass force=True to add a duplicate."
                    )
                }
            if force and self._find_task_by_title(project, title) and not confirmed:
                te = self._check_trust("force_duplicate", project=project)
                if te:
                    return te

            valid_types = ("research", "general", "build")
            if type not in valid_types:
                return {"error": f"Invalid type '{type}'. Must be one of {valid_types}"}

            deps = depends_on or []
            for dep_title in deps:
                if not self._find_task_by_title(project, dep_title):
                    return {"error": f"Dependency '{dep_title}' not found. Create it first."}

            if self._check_circular_dep(project, title, deps):
                return {"error": "Circular dependency detected"}

            parent_task = None
            if parent_task_id:
                parent_task = next((t for t in project.get("tasks", []) if t["id"] == parent_task_id), None)
                if not parent_task:
                    parent_task = self._find_task_by_title(project, parent_task_id)
                    if parent_task:
                        parent_task_id = parent_task["id"]
                    else:
                        return {"error": f"Parent task '{parent_task_id}' not found"}

            task = {
                "id": "task_" + uuid.uuid4().hex[:8],
                "title": title,
                "description": description,
                "type": type,
                "status": "pending",
                "depends_on": deps,
                "result": "",
                "result_summary": "",
                "result_artifact": "",
                "parent_task_id": parent_task_id,
                "subtasks": [],
                "owner": owner or "user",
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            project["tasks"].append(task)
            if parent_task:
                parent_task.setdefault("subtasks", []).append(task["id"])
            project["last_activity"] = _utcnow()
            self._save()
            folder = project.get("folder", "")
            task_copy = dict(task)

        self._append_event(folder, "task.added", {"project_id": project_id, "task": task_copy})
        self.emit_hook("task.added", {
            "event": "task.added",
            "project_id": project_id, "project_name": project.get("name", ""), "task": task_copy,
            "_op_action": "add_task", "_op_entity_type": "project_task", "_op_entity_id": task_copy["id"], "_op_entity_name": title, "_op_details": {"project_id": project_id, "type": type}
        })
        return task_copy

    def add_task(self, project_id: str, title: str, type: str = "general", depends_on: list[str] | None = None, description: str = "", force: bool = False, parent_task_id: str | None = None, owner: str = "user", confirmed: bool = False) -> dict | None:
        return self._add_task_inner(project_id, title, type, depends_on, description, force, parent_task_id, owner, confirmed)

    def update_task_status(self, project_id: str, task_id: str, status: str, result: str = "") -> dict | None:
        VALID_TRANSITIONS = {
            "pending": ["in_progress"],
            "in_progress": ["completed", "blocked", "failed"],
        }
        hook_data = None
        emit_pre = None
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return {"error": "Project not found"}
            project = self._projects[idx]
            t_idx = self._find_task_index(project, task_id)
            if t_idx is None:
                # try title fallback
                t = self._find_task_by_title(project, task_id)
                if t:
                    t_idx = self._find_task_index(project, t["id"])
                if t_idx is None:
                    return {"error": f"Task '{task_id}' not found"}
            task = project["tasks"][t_idx]
            old_status = task["status"]
            # idempotent retain: same status → already done, don't treat as error
            if status == old_status:
                return {"id": task["id"], "title": task["title"], "status": status, "cached": True, "message": f"Task already {status}"}
            allowed = VALID_TRANSITIONS.get(old_status, [])
            if status not in allowed:
                return {"error": f"Cannot transition from '{old_status}' to '{status}'. Allowed: {allowed}"}
            emit_pre = {"project_id": project_id, "project_name": project["name"], "task_id": task["id"], "task_title": task["title"], "from": old_status, "to": status}
            task["status"] = status
            if result:
                self._store_result(project, task, result)
            task["updated_at"] = _utcnow()
            project["last_activity"] = _utcnow()
            self._save()
            folder = project.get("folder", "")
            task_copy = dict(task)
            hook_data = {
                "event": "task.post_transition",
                "project_id": project_id, "project_name": project["name"],
                "task_id": task["id"], "task_title": task["title"],
                "from": old_status, "to": status,
                "result": task.get("result", ""),
                "result_summary": task.get("result_summary", ""),
                "result_artifact": task.get("result_artifact", ""),
                "_op_action": status, "_op_entity_type": "project_task", "_op_entity_id": task["id"], "_op_entity_name": task["title"], "_op_details": {"project_id": project_id, "from": old_status, "to": status}
            }

        self._append_event(folder, "task.status", {
            "project_id": project_id, "task_id": task_copy["id"], "status": status,
            "result": task_copy.get("result", ""), "result_summary": task_copy.get("result_summary", ""), "result_artifact": task_copy.get("result_artifact", "")
        })
        # pre-transition hook outside lock (deferred queue handles re-entrancy)
        self.emit_hook("task.pre_transition", emit_pre)
        if hook_data:
            self.emit_hook("task.post_transition", hook_data)
            if status in ("completed", "blocked", "failed"):
                self.emit_hook("task.artifact_stored" if task_copy.get("result_artifact") else "task.completed", hook_data)

        return task_copy

    def list_tasks(self, project_id: str, status_filter: str | None = None, tree: bool = False) -> list[dict]:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return []
            project = self._projects[idx]
            tasks = project.get("tasks", [])
            if status_filter:
                tasks = [t for t in tasks if t["status"] == status_filter]
            result = [dict(t) for t in tasks]
            if tree:
                # build nested structure
                by_id = {t["id"]: dict(t, children=[]) for t in result}
                roots = []
                for t in result:
                    pid = t.get("parent_task_id")
                    if pid and pid in by_id:
                        by_id[pid]["children"].append(by_id[t["id"]])
                    else:
                        roots.append(by_id[t["id"]])
                return roots
            return result

    def get_active_task(self, project_id: str) -> dict | None:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return None
            project = self._projects[idx]
            tasks = project.get("tasks", [])
            # A parent is only eligible when all its subtasks are completed
            def _subtasks_done(task: dict) -> bool:
                for sid in task.get("subtasks", []) or []:
                    child = next((t for t in tasks if t["id"] == sid), None)
                    if child and child["status"] != "completed":
                        return False
                return True

            for t in tasks:
                if t["status"] == "in_progress":
                    return dict(t)
            for t in tasks:
                if t["status"] == "pending":
                    if not _subtasks_done(t):
                        continue
                    deps_met = True
                    for dep_title in t.get("depends_on", []):
                        dep = self._find_task_by_title(project, dep_title)
                        if not dep or dep["status"] != "completed":
                            deps_met = False
                            break
                    if deps_met:
                        return dict(t)
            return None

    def add_data_point(self, project_id: str, label: str, value: str, unit: str | None = None,
                       confidence: str | None = None, sources: list[str] | None = None) -> dict:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return {"error": "Project not found"}
            project = self._projects[idx]
            if project.get("data_points") is None:
                project["data_points"] = []
            dp = {
                "id": "pdp_" + uuid.uuid4().hex[:8],
                "label": str(label) if label is not None else "",
                "value": str(value) if value is not None else "",
                "unit": str(unit) if unit else "",
                "confidence": str(confidence) if confidence else "medium",
                "sources": sources or [],
                "created_at": _utcnow(),
            }
            project["data_points"].append(dp)
            project["last_activity"] = _utcnow()
            self._save()
            folder = project.get("folder", "")

        self._append_event(folder, "project.data_point", {"project_id": project_id, "data_point": dp})
        self.emit_hook("project.data_point", {
            "project_id": project_id, "data_point": dp,
            "_op_action": "add_data_point", "_op_entity_type": "project", "_op_entity_id": project_id, "_op_entity_name": project.get("name", ""), "_op_details": {"label": label, "value": value}
        })
        return dp

    def list_data_points(self, project_id: str) -> list[dict]:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return []
            return list(self._projects[idx].get("data_points", []))

    def get_outputs_dir(self, project: dict) -> Path:
        folder = project.get("folder", "unknown")
        return self._projects_dir / folder / "outputs"

    def list_outputs(self, project_id: str) -> list[dict]:
        """List generated chart outputs (chart_*/ directories) newest first."""
        from pathlib import Path
        import json as _json
        with self._lock:
            project = self.get_project(project_id)
            if not project:
                return {"error": f"Project '{project_id}' not found"}
            outputs = []
            outputs_dir = self.get_outputs_dir(project)
            if outputs_dir.is_dir():
                for entry in sorted(outputs_dir.iterdir(), key=lambda p: p.name, reverse=True):
                    if not entry.is_dir() or not entry.name.startswith("chart_"):
                        continue
                    json_path = entry / "chart.json"
                    chart_type = ""
                    data_points = 0
                    if json_path.is_file():
                        try:
                            chart_json = _json.loads(json_path.read_text(encoding="utf-8"))
                            chart_type = chart_json.get("type", "")
                            labels = chart_json.get("data", {}).get("labels", []) if isinstance(chart_json.get("data"), dict) else []
                            data_points = len(labels) if isinstance(labels, list) else 0
                        except Exception:
                            pass
                    outputs.append({
                        "dir": entry.name,
                        "chart_type": chart_type or "unknown",
                        "data_points": data_points,
                        "html_path": str(entry / "index.html"),
                        "relative_url": f"/projects/{project['folder']}/outputs/{entry.name}/index.html",
                        "created_at": entry.name.replace("chart_", "").replace("_", ":"),
                    })
            return outputs

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
            idx = self._find_index(project.get("id", ""))
            if idx is not None:
                self._projects[idx].setdefault("generated_outputs", []).append(out)
                self._projects[idx]["last_activity"] = _utcnow()
                self._save()
            return out

    def link_conversation(self, project_id: str, conversation_id: str):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return
            if conversation_id not in self._projects[idx]["conversation_ids"]:
                self._projects[idx]["conversation_ids"].append(conversation_id)
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()
            folder = self._projects[idx].get("folder", "")

        self._append_event(folder, "project.conversation_linked", {"project_id": project_id, "conversation_id": conversation_id})
        self.emit_hook("project.conversation_linked", {"project_id": project_id, "conversation_id": conversation_id})

    def get_project_docs_dir(self, project_id: str) -> Path:
        idx = self._find_index(project_id)
        if idx is None:
            return self._projects_dir / "unknown" / "pdfs"
        folder = self._projects[idx].get("folder", "unknown")
        return self._projects_dir / folder / "pdfs"

    def add_document(self, project_id: str, doc_id: str) -> bool:
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return False
            if "documents" not in self._projects[idx]:
                self._projects[idx]["documents"] = []
            if doc_id not in self._projects[idx]["documents"]:
                self._projects[idx]["documents"].append(doc_id)
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()
            folder = self._projects[idx].get("folder", "")

        self._append_event(folder, "project.document", {"project_id": project_id, "doc_id": doc_id})
        self.emit_hook("project.document", {"project_id": project_id, "doc_id": doc_id})
        return True

    def touch_activity(self, project_id: str):
        with self._lock:
            idx = self._find_index(project_id)
            if idx is None:
                return
            self._projects[idx]["last_activity"] = _utcnow()
            self._save()

    def soft_delete(self, project_id: str, confirmed: bool = False) -> dict | None:
        return self.update_project_status(project_id, "scrapped", confirmed=confirmed)

    def discover_host_projects(self) -> list[dict]:
        known_folders = {p.get("folder", "").lower() for p in self._projects if p.get("folder")}
        discovered = []
        if not self._projects_dir.is_dir():
            return discovered
        for entry in sorted(self._projects_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.lower() in known_folders:
                continue
            file_count = sum(1 for _ in entry.rglob("*") if _.is_file())
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            discovered.append({
                "name": entry.name,
                "folder": entry.name,
                "path": str(entry.resolve()),
                "file_count": file_count,
                "modified_at": mtime.isoformat(),
            })
        return discovered


_instance: ProjectStore | None = None
_instance_lock = threading.Lock()


def get_project_store() -> ProjectStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ProjectStore()
    return _instance
