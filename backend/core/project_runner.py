import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from backend.core.config import load_config
from backend.core.port_utils import find_free_port

logger = logging.getLogger(__name__)

_cfg = load_config()
_cfg_dir = _cfg.get("data", {}).get("projects_dir", "")
PROJECTS_DIR = Path(_cfg_dir).resolve() if _cfg_dir else (Path(__file__).resolve().parent.parent.parent / "projects")

ALLOWED_COMMANDS = {
    "pip", "npm", "npx", "python", "python3", "node",
    "git", "bun", "cargo", "go", "make", "poetry", "uv",
    "cp", "mkdir", "copy", "docker",
}

BLOCKED_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/", re.I),
    re.compile(r"del\s+/f", re.I),
    re.compile(r"format\s+[c-z]:", re.I),
    re.compile(r">\s*/dev/"),
    re.compile(r"\|\s*(bash|sh|cmd|powershell)"),
    re.compile(r"eval\s*\("),
    re.compile(r"exec\s*\("),
]

_background_processes: dict[str, list[int]] = {}
_global_lock = threading.Lock()
_instances: dict[str, "ProjectRunner"] = {}


class ProjectRunner:
    def __init__(self, slug: str):
        self.slug = slug
        self.project_dir = PROJECTS_DIR / slug

    @classmethod
    def get_or_create(cls, slug: str) -> "ProjectRunner":
        with _global_lock:
            if slug not in _instances:
                _instances[slug] = cls(slug)
            return _instances[slug]

    @classmethod
    def get(cls, slug: str) -> "ProjectRunner | None":
        return _instances.get(slug)

    @classmethod
    def remove(cls, slug: str):
        with _global_lock:
            _instances.pop(slug, None)

    def prepare(self) -> str:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        pkg_json = self.project_dir / "package.json"
        results = []
        if pkg_json.exists():
            r = self._run("npm install", timeout=120)
            results.append(r)
        msg = f"Project '{self.slug}' ready at {self.project_dir}."
        if results:
            msg += "\n" + "\n".join(results)
        return msg

    def exec(self, command: str, timeout: int = 300) -> str:
        return self._run(command, timeout=timeout)

    def exec_background(self, command: str, preferred_port: int | None = None) -> dict:
        actual_port = None
        if preferred_port:
            actual_port = find_free_port(preferred_port)
            command = re.sub(r"--port\s+\d+", f"--port {actual_port}", command)
        proc = subprocess.Popen(
            command, shell=True, cwd=self.project_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        with _global_lock:
            if self.slug not in _background_processes:
                _background_processes[self.slug] = []
            _background_processes[self.slug].append(proc.pid)
        time.sleep(2)
        return {"pid": proc.pid, "port": actual_port, "message": f"Started (PID {proc.pid})"}

    def stop(self) -> str:
        with _global_lock:
            pids = _background_processes.pop(self.slug, [])
        killed = 0
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=5)
                killed += 1
            except Exception:
                pass
        self.remove(self.slug)
        return f"Stopped {killed} process(es) for '{self.slug}'."

    def status(self) -> str:
        pids = _background_processes.get(self.slug, [])
        alive = []
        for pid in pids:
            try:
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                   capture_output=True, text=True, timeout=5)
                if str(pid) in r.stdout:
                    alive.append(pid)
            except Exception:
                pass
        if alive:
            return f"Project '{self.slug}': {self.project_dir} — {len(alive)} process(es) running (PIDs: {alive})"
        return f"Project '{self.slug}': {self.project_dir} — no processes running"

    def write_file(self, path: str, content: str) -> str:
        full = self._resolve_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {self.slug}/{path}"

    def read_file(self, path: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"File not found: {path}"
        return full.read_text(encoding="utf-8")

    def delete_file(self, path: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"Not found: {path}"
        if full.is_dir():
            import shutil
            shutil.rmtree(full)
        else:
            full.unlink()
        return f"Deleted: {path}"

    def list_files(self, path: str = ".") -> str:
        full = self._resolve_path(path)
        if not full.is_dir():
            return f"Directory not found: {path}"
        result = subprocess.run(
            ["cmd", "/c", "dir", str(full)],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout or result.stderr

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.project_dir / p
        p = p.resolve()
        if not str(p).startswith(str(self.project_dir.resolve())):
            raise PermissionError(f"Path escape detected: {path}")
        return p

    def _run(self, command: str, timeout: int = 300) -> str:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=self.project_dir, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            output = result.stdout or result.stderr or "(no output)"
            if result.returncode != 0:
                output = f"Exit code {result.returncode}:\n{result.stderr.strip() or result.stdout.strip()}"
            return output.strip()
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s:\n{command[:200]}"
        except Exception as e:
            return f"Error executing command: {e}"

    @property
    def is_running(self) -> bool:
        pids = _background_processes.get(self.slug, [])
        if not pids:
            return False
        for pid in pids:
            try:
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                   capture_output=True, text=True, timeout=5)
                if str(pid) in r.stdout:
                    return True
            except Exception:
                pass
        return False

    @classmethod
    def cleanup_orphans(cls):
        with _global_lock:
            for slug, pids in list(_background_processes.items()):
                for pid in pids:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True, timeout=5)
                    except Exception:
                        pass
            _background_processes.clear()
            _instances.clear()
