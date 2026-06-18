import json
import os
import uuid
import threading
import calendar
from datetime import datetime, timezone, timedelta
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
                    priority: int = 2, tags: list[str] = None,
                    recurrence: dict = None) -> dict:
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
            if recurrence:
                todo["recurrence"] = recurrence
            self._todos.append(todo)
            self._save()
            return todo

    def update_todo(self, todo_id: str, **kwargs) -> dict | None:
        with self._lock:
            for todo in self._todos:
                if todo["id"] == todo_id:
                    for k, v in kwargs.items():
                        if k in ("title", "description", "due_date", "priority", "completed", "tags", "recurrence"):
                            if v is None:
                                todo.pop(k, None)
                            else:
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

    def find_duplicate_todos(self, title: str, due_date: str = None, exclude_id: str = None) -> list[dict]:
        with self._lock:
            q = title.strip().lower()
            results = []
            for t in self._todos:
                if exclude_id and t["id"] == exclude_id:
                    continue
                if t["title"].strip().lower() != q:
                    continue
                if due_date and t.get("due_date"):
                    if t["due_date"] != due_date:
                        continue
                results.append(dict(t))
            return results

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
                     description: str = "", all_day: bool = False,
                     recurrence: dict = None) -> dict:
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
            if recurrence:
                event["recurrence"] = recurrence
            self._events.append(event)
            self._save()
            return event

    def update_event(self, event_id: str, **kwargs) -> dict | None:
        with self._lock:
            for event in self._events:
                if event["id"] == event_id:
                    for k, v in kwargs.items():
                        if k in ("title", "description", "start_time", "end_time", "all_day", "recurrence"):
                            if v is None:
                                event.pop(k, None)
                            else:
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

    def find_duplicate_events(self, title: str, start_time: str, exclude_id: str = None) -> list[dict]:
        with self._lock:
            q = title.strip().lower()
            start_day = start_time[:10]
            results = []
            for e in self._events:
                if exclude_id and e["id"] == exclude_id:
                    continue
                if e["title"].strip().lower() != q:
                    continue
                if e["start_time"][:10] != start_day:
                    continue
                results.append(dict(e))
            return results

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

    # --- Recurrence Expansion ---

    @staticmethod
    def _add_months(dt: datetime, months: int) -> datetime:
        total = dt.month - 1 + months
        year = dt.year + total // 12
        month = total % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day,
                          hour=dt.hour, minute=dt.minute, second=dt.second)

    def expand_recurring(self, entity: dict, start_date: str, end_date: str) -> list[dict]:
        rec = entity.get("recurrence")
        if not rec:
            return [entity]
        pattern = rec["pattern"]
        interval = rec.get("interval", 1)
        max_end = rec.get("end_date") or end_date
        max_count = rec.get("count")
        if end_date < start_date:
            return [entity]
        if max_end and max_end < start_date:
            return [entity]
        if max_count is not None and max_count < 1:
            return [entity]

        if "start_time" in entity:
            dt_field = "start_time"
            end_dt_field = "end_time"
        else:
            dt_field = "due_date"
            end_dt_field = None

        try:
            current = datetime.fromisoformat(entity[dt_field]).replace(tzinfo=None)
            end_current = datetime.fromisoformat(entity[end_dt_field]).replace(tzinfo=None) if end_dt_field and entity.get(end_dt_field) else None
        except (ValueError, KeyError):
            return [entity]

        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=None) if start_date else current
        end_dt = datetime.fromisoformat(end_date).replace(tzinfo=None) if end_date else current
        max_end_dt = datetime.fromisoformat(max_end).replace(tzinfo=None) if max_end else None

        instances = []
        count = 0
        max_recurrences = 500

        while count < max_recurrences:
            if dt_field == "due_date":
                date_str = current.strftime("%Y-%m-%d")
            else:
                date_str = current.isoformat()

            if current > end_dt:
                break
            if max_end_dt and current > max_end_dt:
                break
            if max_count is not None and count >= max_count:
                break

            if current >= start_dt:
                instance = dict(entity)
                instance[dt_field] = date_str
                instance["_recurring"] = True
                instance["_original_id"] = entity["id"]
                if end_current and end_dt_field:
                    delta = end_current - (datetime.fromisoformat(entity[dt_field]).replace(tzinfo=None) if dt_field != "due_date" else current)
                    instance[end_dt_field] = (current + delta).isoformat()
                instances.append(instance)
                count += 1

            if pattern == "daily":
                current += timedelta(days=interval)
            elif pattern == "weekly":
                current += timedelta(weeks=interval)
            elif pattern == "biweekly":
                current += timedelta(weeks=2 * interval)
            elif pattern == "monthly":
                current = self._add_months(current, interval)
            elif pattern == "yearly":
                current = self._add_months(current, 12 * interval)
            else:
                break

        if not instances:
            instances.append(entity)
        return instances

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
