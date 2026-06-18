import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _today_str():
    return _utcnow().strftime("%Y-%m-%d")


REMINDERS_PATH = Path(__file__).resolve().parent.parent.parent / "reminders.json"


class Scheduler:
    def __init__(self):
        self._reminders: dict[str, dict] = {}
        self._seen_events: set[str] = set()
        self._seen_todos: set[str] = set()
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._lock = threading.Lock()
        self._fired_notifications: list[dict] = []
        self._load_reminders()

    def _reminders_path(self) -> Path:
        return REMINDERS_PATH

    def _load_reminders(self):
        p = self._reminders_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._reminders = {r["id"]: r for r in data.get("reminders", [])}
            except (json.JSONDecodeError, OSError):
                pass

    def _save_reminders(self):
        p = self._reminders_path()
        data = {"reminders": list(self._reminders.values())}
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_reminder(self, message: str, datetime_str: str) -> tuple[str, bool, str]:
        now_utc = _utcnow()
        adjusted = False
        try:
            local_dt = datetime.fromisoformat(datetime_str)
        except ValueError:
            local_dt = now_utc
            adjusted = True

        offset = now_utc.astimezone().utcoffset()
        if offset is not None:
            dt_utc = (local_dt - offset).replace(tzinfo=timezone.utc)
        else:
            dt_utc = local_dt.replace(tzinfo=timezone.utc)

        if dt_utc.replace(microsecond=0) < now_utc.replace(microsecond=0):
            dt_utc = now_utc + timedelta(minutes=1)
            adjusted = True

        datetime_utc_str = dt_utc.isoformat()[:16]
        reminder_id = uuid.uuid4().hex[:12]
        reminder = {
            "id": reminder_id,
            "message": message,
            "datetime": datetime_utc_str,
            "created_at": now_utc.isoformat(),
            "fired": False,
        }
        with self._lock:
            self._reminders[reminder_id] = reminder
            self._save_reminders()
        return reminder_id, adjusted, datetime_utc_str

    def get_reminder(self, reminder_id: str) -> dict | None:
        with self._lock:
            return self._reminders.get(reminder_id)

    def list_reminders(self) -> list[dict]:
        with self._lock:
            return [
                r for r in self._reminders.values()
                if not r["fired"] and r["datetime"] >= _utcnow().isoformat()[:16]
            ]

    def delete_reminder(self, reminder_id: str) -> bool:
        with self._lock:
            if reminder_id in self._reminders:
                del self._reminders[reminder_id]
                self._save_reminders()
                return True
            return False

    def get_queue(self) -> asyncio.Queue:
        return self._queue

    def get_fired_notifications(self) -> list[dict]:
        with self._lock:
            result = list(self._fired_notifications)
            self._fired_notifications.clear()
            return result

    async def run(self):
        logger.info("Scheduler started")
        while True:
            await self._check_events()
            await self._check_todos()
            await self._check_reminders()
            await asyncio.sleep(60)

    async def _check_events(self):
        try:
            from backend.core.data_store import get_store
            store = get_store()
            now = _utcnow()
            window_end = (now + timedelta(minutes=30)).isoformat()
            now_iso = now.isoformat()
            raw = store.list_events(start_date=now_iso, end_date=window_end)
            for ev in raw:
                ev_id = ev["id"]
                if ev_id in self._seen_events:
                    continue
                expanded = store.expand_recurring(ev, now_iso[:10], (now + timedelta(days=1)).isoformat()[:10])
                for inst in expanded:
                    if inst.get("_recurring"):
                        inst_id = inst.get("_original_id", ev_id) + "_" + inst.get("start_time", "")
                    else:
                        inst_id = ev_id
                    if inst_id in self._seen_events:
                        continue
                    self._seen_events.add(inst_id)
                    start = inst.get("start_time", "")
                    if start <= window_end and start >= now_iso:
                        await self._queue.put({
                            "type": "notification",
                            "id": inst_id,
                            "title": "Upcoming Event",
                            "body": f"{inst['title']} at {start[:16]}",
                            "category": "event_reminder",
                            "action": {"page": "calendar"},
                        })
        except Exception as e:
            logger.exception("Scheduler _check_events error: %s", e)

    async def _check_todos(self):
        try:
            from backend.core.data_store import get_store
            store = get_store()
            today = _today_str()
            todos = store.list_todos(include_completed=False)
            for t in todos:
                due = t.get("due_date")
                if not due:
                    continue
                if due >= today:
                    continue
                todo_key = t["id"] + "_" + today
                if todo_key in self._seen_todos:
                    continue
                self._seen_todos.add(todo_key)
                await self._queue.put({
                    "type": "notification",
                    "id": todo_key,
                    "title": "Overdue Todo",
                    "body": f"{t['title']} was due {due}",
                    "category": "todo_overdue",
                    "action": {"page": "todos"},
                })
        except Exception as e:
            logger.exception("Scheduler _check_todos error: %s", e)

    async def _check_reminders(self):
        try:
            now_str = _utcnow().isoformat()[:16]
            to_fire: list[dict] = []
            with self._lock:
                for rid, r in list(self._reminders.items()):
                    if not r["fired"] and r["datetime"] <= now_str:
                        r["fired"] = True
                        to_fire.append(dict(r))
                if to_fire:
                    self._save_reminders()
            for r in to_fire:
                n = {
                    "type": "notification",
                    "id": r["id"],
                    "title": "Reminder",
                    "body": r["message"],
                    "category": "custom_reminder",
                    "action": {"page": "chat"},
                }
                await self._queue.put(n)
                with self._lock:
                    self._fired_notifications.append(n)
        except Exception as e:
            logger.exception("Scheduler _check_reminders error: %s", e)


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
