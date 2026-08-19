import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.core.config import load_config


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


class PersonalNotesStore:
    """Standalone personal notes (distinct from project/research notes)."""

    def __init__(self):
        cfg = load_config()
        path = cfg.get("personal_notes", {}).get("storage_path", "notes.json")
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent.parent.parent / path)
        self._path = Path(path)
        self._lock = threading.RLock()
        self._notes: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._notes = {n["id"]: n for n in data.get("notes", [])}
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"notes": list(self._notes.values())}
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_note(self, text: str, title: str = "", entities: Optional[list[str]] = None,
                    tags: Optional[list[str]] = None) -> dict:
        with self._lock:
            text = text.strip()
            if not text:
                return {"error": "Note text cannot be empty"}
            note = {
                "id": "note_" + uuid.uuid4().hex[:12],
                "title": (title or text[:40]).strip(),
                "text": text,
                "entities": entities or [],
                "tags": tags or [],
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            self._notes[note["id"]] = note
            self._save()
            return note

    def get_note(self, note_id: str) -> Optional[dict]:
        return self._notes.get(note_id)

    def list_notes(self) -> list[dict]:
        with self._lock:
            notes = [dict(n) for n in self._notes.values()]
            notes.sort(key=lambda x: x["updated_at"], reverse=True)
            return notes

    def search_notes(self, query: str) -> list[dict]:
        q = _norm(query)
        qt = _tokenize(query)
        out = []
        for n in self._notes.values():
            hay = _norm(n["title"] + " " + n["text"] + " " + " ".join(n["entities"]))
            if q in hay or qt.issubset(_tokenize(hay)):
                out.append(dict(n))
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def update_note(self, note_id: str, **fields) -> dict:
        with self._lock:
            n = self._notes.get(note_id)
            if n is None:
                return {"error": "Note not found"}
            for k in ("title", "text", "entities", "tags"):
                if k in fields:
                    n[k] = fields[k]
            n["updated_at"] = _utcnow()
            self._save()
            return n

    def delete_note(self, note_id: str) -> bool:
        with self._lock:
            if note_id in self._notes:
                del self._notes[note_id]
                self._save()
                return True
            return False


_instance: Optional[PersonalNotesStore] = None
_instance_lock = threading.Lock()


def get_personal_notes_store() -> PersonalNotesStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PersonalNotesStore()
    return _instance


def reset_personal_notes_store():
    global _instance
    _instance = None


# ---------------------------------------------------------------------------
# Personal Task Store (PTS) — unified facade across todo/event/note/reminder.
# ---------------------------------------------------------------------------
def personal_plate(context: Optional[str] = None, include_completed: bool = False) -> dict:
    """One query answering 'what's on my plate' across all four stores."""
    from backend.core.data_store import get_store
    from backend.core.scheduler import get_scheduler

    store = get_store()
    notes_store = get_personal_notes_store()
    scheduler = get_scheduler()

    todos = store.list_todos(include_completed=include_completed)
    events = store.list_events()
    notes = notes_store.list_notes()
    reminders = scheduler.list_reminders()

    items = []
    for t in todos:
        items.append({
            "id": t["id"], "kind": "todo", "text": t.get("title", ""),
            "time": t.get("due_date"), "entities": t.get("tags", []),
            "source": "todos",
        })
    for e in events:
        items.append({
            "id": e["id"], "kind": "event", "text": e.get("title", ""),
            "time": e.get("start_time"), "entities": [],
            "source": "events",
        })
    for n in notes:
        items.append({
            "id": n["id"], "kind": "note", "text": n.get("title", ""),
            "time": n.get("updated_at"), "entities": n.get("entities", []),
            "source": "notes",
        })
    for r in reminders:
        items.append({
            "id": r["id"], "kind": "reminder", "text": r.get("message", ""),
            "time": r.get("datetime"), "entities": [],
            "source": "reminders",
        })

    ctx_tokens = _tokenize(context or "")
    if ctx_tokens:
        for it in items:
            ent = set(it["entities"]) | _tokenize(it["text"])
            it["_relevance"] = len(ctx_tokens & ent)
        items.sort(key=lambda x: -x.get("_relevance", 0))

    return {
        "counts": {
            "todos": len(todos),
            "events": len(events),
            "notes": len(notes),
            "reminders": len(reminders),
        },
        "items": items,
    }
