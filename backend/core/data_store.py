import json
import os
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.core.config import load_config


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class DataStore:
    def __init__(self):
        cfg = load_config()
        path = Path(cfg.get("data", {}).get("storage_path", "data.json"))
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent.parent / path
        self._path = path
        self._conv_dir = Path(__file__).resolve().parent.parent.parent / "conversations"
        self._lock = threading.Lock()
        self._todos: list[dict] = []
        self._events: list[dict] = []
        self._load()
        self._init_conv_dir()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._todos = data.get("todos", [])
                self._events = data.get("events", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        data = {
            "todos": self._todos,
            "events": self._events,
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _init_conv_dir(self):
        if not self._conv_dir.exists():
            self._conv_dir.mkdir(parents=True, exist_ok=True)
            self._migrate_conversations()

    def _migrate_conversations(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                convs = data.get("conversations", [])
                if not convs:
                    return
                index = self._load_index()
                for conv in convs:
                    conv_date = conv.get("created_at", "")[:10] or _today_str()
                    day = self._load_day(conv_date)
                    for existing in day["conversations"]:
                        if existing["id"] == conv["id"]:
                            break
                    else:
                        day["conversations"].append(conv)
                        self._save_day(conv_date, day)
                    index.append({
                        "id": conv["id"],
                        "date": conv_date,
                        "title": conv.get("title", "Conversation"),
                        "message_count": len(conv.get("messages", [])),
                    })
                self._save_index(index)
                data["conversations"] = []
                self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except (json.JSONDecodeError, OSError):
                pass

    def _daily_path(self, date_str: str) -> Path:
        return self._conv_dir / f"{date_str}.json"

    def _load_day(self, date_str: str) -> dict:
        p = self._daily_path(date_str)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"date": date_str, "conversations": []}

    def _save_day(self, date_str: str, data: dict):
        self._daily_path(date_str).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _index_path(self) -> Path:
        return self._conv_dir / "index.json"

    def _load_index(self) -> list[dict]:
        p = self._index_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_index(self, index: list[dict]):
        self._index_path().write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _rebuild_index(self):
        index = []
        for fname in os.listdir(str(self._conv_dir)):
            if fname.endswith(".json") and fname != "index.json":
                try:
                    day = json.loads((self._conv_dir / fname).read_text(encoding="utf-8"))
                    for conv in day.get("conversations", []):
                        index.append({
                            "id": conv["id"],
                            "date": day["date"],
                            "title": conv.get("title", "Conversation"),
                            "message_count": len(conv.get("messages", [])),
                        })
                except (json.JSONDecodeError, OSError):
                    pass
        self._save_index(index)

    # --- Todos ---

    def create_todo(self, title: str, description: str = "", due_date: str = None,
                    priority: int = 2, tags: list[str] = None) -> dict:
        with self._lock:
            todo = {
                "id": uuid.uuid4().hex[:12],
                "title": title,
                "description": description,
                "due_date": due_date,
                "priority": priority,
                "completed": False,
                "tags": tags or [],
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            self._todos.append(todo)
            self._save()
            return todo

    def update_todo(self, todo_id: str, **kwargs) -> dict | None:
        with self._lock:
            for todo in self._todos:
                if todo["id"] == todo_id:
                    for k, v in kwargs.items():
                        if k in ("title", "description", "due_date", "priority", "completed", "tags"):
                            todo[k] = v
                    todo["updated_at"] = _utcnow()
                    self._save()
                    return todo
            return None

    def delete_todo(self, todo_id: str) -> bool:
        with self._lock:
            before = len(self._todos)
            self._todos = [t for t in self._todos if t["id"] != todo_id]
            if len(self._todos) != before:
                self._save()
                return True
            return False

    def list_todos(self, include_completed: bool = True, query: str = "") -> list[dict]:
        with self._lock:
            todos = list(self._todos)
        if not include_completed:
            todos = [t for t in todos if not t["completed"]]
        if query:
            q = query.lower()
            todos = [t for t in todos if q in t["title"].lower()]
        return todos

    def get_todo(self, todo_id: str) -> dict | None:
        with self._lock:
            for todo in self._todos:
                if todo["id"] == todo_id:
                    return todo
            return None

    # --- Events ---

    def create_event(self, title: str, start_time: str, end_time: str,
                     description: str = "", all_day: bool = False) -> dict:
        with self._lock:
            event = {
                "id": uuid.uuid4().hex[:12],
                "title": title,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "all_day": all_day,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            self._events.append(event)
            self._save()
            return event

    def update_event(self, event_id: str, **kwargs) -> dict | None:
        with self._lock:
            for event in self._events:
                if event["id"] == event_id:
                    for k, v in kwargs.items():
                        if k in ("title", "description", "start_time", "end_time", "all_day"):
                            event[k] = v
                    event["updated_at"] = _utcnow()
                    self._save()
                    return event
            return None

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            before = len(self._events)
            self._events = [e for e in self._events if e["id"] != event_id]
            if len(self._events) != before:
                self._save()
                return True
            return False

    def list_events(self, start_date: str = None, end_date: str = None, query: str = "") -> list[dict]:
        with self._lock:
            events = list(self._events)
        if start_date:
            events = [e for e in events if e["start_time"] >= start_date]
        if end_date:
            events = [e for e in events if e["start_time"] <= end_date]
        if query:
            q = query.lower()
            events = [e for e in events if q in e["title"].lower() or q in e.get("description", "").lower()]
        return events

    def get_event(self, event_id: str) -> dict | None:
        with self._lock:
            for event in self._events:
                if event["id"] == event_id:
                    return event
            return None

    # --- Conversations (per-day files) ---

    def create_conversation(self, title: str = "New conversation") -> dict:
        with self._lock:
            conv = {
                "id": uuid.uuid4().hex[:12],
                "title": title,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                "messages": [],
            }
            date_str = _today_str()
            day = self._load_day(date_str)
            day["conversations"].append(conv)
            self._save_day(date_str, day)
            index = self._load_index()
            index.append({
                "id": conv["id"],
                "date": date_str,
                "title": title,
                "message_count": 0,
            })
            self._save_index(index)
            return conv

    def add_message(self, conversation_id: str, role: str, content: str) -> dict | None:
        with self._lock:
            index = self._load_index()
            entry = next((e for e in index if e["id"] == conversation_id), None)
            if not entry:
                return None
            day = self._load_day(entry["date"])
            for conv in day["conversations"]:
                if conv["id"] == conversation_id:
                    msg = {
                        "role": role,
                        "content": content,
                        "timestamp": _utcnow(),
                    }
                    conv["messages"].append(msg)
                    conv["updated_at"] = _utcnow()
                    if len(conv["messages"]) == 1 and role == "user":
                        conv["title"] = content[:60]
                        entry["title"] = conv["title"]
                    entry["message_count"] = len(conv["messages"])
                    self._save_day(entry["date"], day)
                    self._save_index(index)
                    return msg
            return None

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            index = self._load_index()
            entry = next((e for e in index if e["id"] == conversation_id), None)
            if not entry:
                return None
            day = self._load_day(entry["date"])
            for conv in day["conversations"]:
                if conv["id"] == conversation_id:
                    return conv
            return None

    def list_conversations(self, date: str | None = None) -> list[dict]:
        with self._lock:
            index = self._load_index()
            if date:
                index = [e for e in index if e["date"] == date]
            sorted_index = sorted(index, key=lambda e: e.get("date", ""), reverse=True)
            result = []
            for entry in sorted_index:
                day = self._load_day(entry["date"])
                for conv in day["conversations"]:
                    if conv["id"] == entry["id"]:
                        conv_slim = {
                            "id": conv["id"],
                            "title": conv["title"],
                            "created_at": conv["created_at"],
                            "updated_at": conv["updated_at"],
                            "message_count": len(conv["messages"]),
                        }
                        result.append(conv_slim)
                        break
            return result

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            index = self._load_index()
            entry = next((e for e in index if e["id"] == conversation_id), None)
            if not entry:
                return False
            day = self._load_day(entry["date"])
            before = len(day["conversations"])
            day["conversations"] = [c for c in day["conversations"] if c["id"] != conversation_id]
            if len(day["conversations"]) == before:
                return False
            if day["conversations"]:
                self._save_day(entry["date"], day)
            else:
                self._daily_path(entry["date"]).unlink(missing_ok=True)
            index = [e for e in index if e["id"] != conversation_id]
            self._save_index(index)
            return True

    def get_recent_messages(self, conversation_id: str, limit: int = 20) -> list[dict]:
        conv = self.get_conversation(conversation_id)
        if conv:
            return conv["messages"][-limit:]
        return []


_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store
