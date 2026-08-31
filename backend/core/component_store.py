import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


_COMPONENT_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "component_store.json"


class ComponentStore:
    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else _COMPONENT_STORE_PATH
        self._lock = threading.Lock()
        self._components: list[dict] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._components = data.get("components", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.write_text(json.dumps({"components": self._components}, indent=2, ensure_ascii=False), encoding="utf-8")

    def store_component(self, name: str, code: str, description: str = "", framework: str = "react", tags: list[str] | None = None, replace: bool = False) -> dict:
        tags = tags or []
        with self._lock:
            existing = [c for c in self._components if c["name"] == name]
            if existing and not replace:
                existing_code = existing[0].get("code", "")
                if len(code) < len(existing_code):
                    existing[0]["code"] = code
                    existing[0]["description"] = description
                    existing[0]["framework"] = framework
                    existing[0]["tags"] = tags
                    existing[0]["updated_at"] = _utcnow()
                    existing[0]["version"] = existing[0].get("version", 1) + 1
                    self._save()
                    return {"message": f"Component '{name}' replaced with shorter version (was {len(existing_code)} chars, now {len(code)} chars)", "component": existing[0]}
                existing[0]["description"] = description
                existing[0]["framework"] = framework
                existing[0]["tags"] = list(set(existing[0].get("tags", []) + tags))
                existing[0]["updated_at"] = _utcnow()
                self._save()
                return {"message": f"Component '{name}' already exists. Updated metadata.", "component": existing[0]}
            if existing and replace:
                comp = existing[0]
                comp["code"] = code
                comp["description"] = description
                comp["framework"] = framework
                comp["tags"] = tags
                comp["updated_at"] = _utcnow()
                comp["version"] = comp.get("version", 1) + 1
                self._save()
                return {"message": f"Component '{name}' replaced (v{comp['version']})", "component": comp}
            comp = {
                "id": str(uuid.uuid4())[:8],
                "name": name,
                "code": code,
                "description": description,
                "framework": framework,
                "tags": tags,
                "version": 1,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            self._components.append(comp)
            self._save()
            return {"message": f"Stored component '{name}' ({len(code)} chars)", "component": comp}

    def get_component(self, name: str) -> dict | None:
        with self._lock:
            for c in self._components:
                if c["name"] == name:
                    return dict(c)
            return None

    def list_components(self, framework: str | None = None, tag: str | None = None) -> list[dict]:
        with self._lock:
            results = list(self._components)
            if framework:
                results = [c for c in results if c.get("framework") == framework]
            if tag:
                results = [c for c in results if tag in c.get("tags", [])]
            return [{"name": c["name"], "description": c.get("description", ""), "framework": c.get("framework", "react"), "tags": c.get("tags", []), "version": c.get("version", 1), "updated_at": c.get("updated_at", "")} for c in results]

_instance: ComponentStore | None = None
_lock = threading.Lock()


def get_component_store() -> ComponentStore:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ComponentStore()
    return _instance
