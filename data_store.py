import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


class DataStore:
    def __init__(self, path: str = "data.json"):
        self._path = Path(path)
        self._todos: list[dict] = []
        self._events: list[dict] = []
        self._conversations: list[dict] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._todos = data.get("todos", [])
                self._events = data.get("events", [])
                self._conversations = data.get("conversations", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        data = {
            "todos": self._todos,
            "events": self._events,
            "conversations": self._conversations,
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- Todos ---

    def create_todo(self, title: str, description: str = "", due_date: str = None,
                    priority: int = 2, tags: list[str] = None) -> dict:
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
        before = len(self._todos)
        self._todos = [t for t in self._todos if t["id"] != todo_id]
        if len(self._todos) != before:
            self._save()
            return True
        return False

    def list_todos(self, include_completed: bool = True) -> list[dict]:
        if include_completed:
            return list(self._todos)
        return [t for t in self._todos if not t["completed"]]

    def get_todo(self, todo_id: str) -> dict | None:
        for todo in self._todos:
            if todo["id"] == todo_id:
                return todo
        return None

    # --- Events ---

    def create_event(self, title: str, start_time: str, end_time: str,
                     description: str = "", all_day: bool = False) -> dict:
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
        before = len(self._events)
        self._events = [e for e in self._events if e["id"] != event_id]
        if len(self._events) != before:
            self._save()
            return True
        return False

    def list_events(self, start_date: str = None, end_date: str = None) -> list[dict]:
        events = list(self._events)
        if start_date:
            events = [e for e in events if e["start_time"] >= start_date]
        if end_date:
            events = [e for e in events if e["start_time"] <= end_date]
        return events

    def get_event(self, event_id: str) -> dict | None:
        for event in self._events:
            if event["id"] == event_id:
                return event
        return None

    # --- Conversations ---

    def create_conversation(self, title: str = "New conversation") -> dict:
        conv = {
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "messages": [],
        }
        self._conversations.append(conv)
        self._save()
        return conv

    def add_message(self, conversation_id: str, role: str, content: str) -> dict | None:
        for conv in self._conversations:
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
                self._save()
                return msg
        return None

    def get_conversation(self, conversation_id: str) -> dict | None:
        for conv in self._conversations:
            if conv["id"] == conversation_id:
                return conv
        return None

    def list_conversations(self) -> list[dict]:
        return sorted(self._conversations, key=lambda c: c["updated_at"], reverse=True)

    def delete_conversation(self, conversation_id: str) -> bool:
        before = len(self._conversations)
        self._conversations = [c for c in self._conversations if c["id"] != conversation_id]
        if len(self._conversations) != before:
            self._save()
            return True
        return False

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
