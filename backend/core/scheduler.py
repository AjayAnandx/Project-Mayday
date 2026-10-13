import asyncio
import json
import logging
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
        self._seen_gmail: set[str] = set()
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

    def fire_notification(self, title: str, body: str, category: str = "event_reminder", action_page: str = "chat"):
        n = {
            "type": "notification",
            "id": f"immediate_{uuid.uuid4().hex[:8]}",
            "title": title,
            "body": body,
            "category": category,
            "action": {"page": action_page},
        }
        with self._lock:
            self._fired_notifications.append(n)

    async def run(self):
        logger.info("Scheduler started")
        while True:
            await self._check_events()
            await self._check_todos()
            await self._check_reminders()
            await self._check_gmail()
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

    async def _check_gmail(self):
        """Poll the dedicated Mayday mailbox (60s, history.list incremental sync).

        Skips silently when gmail is disabled or not connected (no token).
        Survives historyId expiry via unread-list fallback. Leaves UNREAD set
        until the user reads via gmail_read + gmail_modify.
        """
        try:
            from backend.core.config import load_config
            cfg = load_config().get("gmail", {}) or {}
        except Exception:
            return
        if not cfg.get("enabled", True):
            return
        account = (cfg.get("account") or "agent").strip() or "agent"
        accounts = ["agent", "user"] if account == "both" else ["agent"]
        try:
            from backend.core import gmail_store
            from backend.core.gmail_service import NeedsOAuth
        except Exception as e:
            logger.warning("Scheduler _check_gmail import failed: %s", e)
            return
        loop = asyncio.get_running_loop()
        for acct in accounts:
            try:
                await loop.run_in_executor(None, self._sync_gmail_account, acct)
            except Exception as e:
                logger.warning("Scheduler _check_gmail(%s) error: %s", acct, e)

    def _sync_gmail_account(self, account: str) -> None:
        from backend.core import gmail_store
        from backend.core.gmail_service import (
            NeedsOAuth, get_history, get_message, get_profile, list_messages,
        )
        try:
            last = gmail_store.get_history_id(account)
            if last is None:
                prof = get_profile(account)
                if prof.get("historyId"):
                    gmail_store.set_history_id(account, str(prof["historyId"]))
                if prof.get("emailAddress"):
                    gmail_store.set_agent_email(prof["emailAddress"])
                return
            try:
                hist = get_history(last, account=account)
            except Exception as e:
                if "404" not in str(e):
                    raise
                # historyId expired — fallback to unread scan
                data = list_messages(query="is:unread", max_results=20, account=account)
                for m in data.get("messages", []) or []:
                    self._notify_gmail_message(account, m["id"],
                                               lambda mid: get_message(mid, fmt="metadata", account=account))
                return
            for rec in hist.get("history", []) or []:
                for added in rec.get("messagesAdded", []) or []:
                    mid = (added.get("message", {}) or {}).get("id", "")
                    if not mid:
                        continue
                    self._notify_gmail_message(account, mid,
                                               lambda m, _a=account: get_message(m, fmt="metadata", account=_a))
            if hist.get("historyId"):
                gmail_store.set_history_id(account, str(hist["historyId"]))
        except NeedsOAuth:
            pass  # not connected — stay silent until user connects
        except Exception as e:
            logger.warning("Gmail sync(%s) failed: %s", account, e)

    def _notify_gmail_message(self, account: str, message_id: str, fetch) -> None:
        key = f"gmail:{account}:{message_id}"
        if key in self._seen_gmail:
            return
        self._seen_gmail.add(key)
        try:
            meta = fetch(message_id)
        except Exception as e:
            logger.warning("Gmail metadata fetch failed for %s: %s", message_id, e)
            return
        hdrs = {h.get("name", ""): h.get("value", "")
                for h in ((meta.get("payload", {}) or {}).get("headers", []) or [])}
        frm, subject = hdrs.get("From", "?"), hdrs.get("Subject", "(no subject)")
        tid = meta.get("threadId", "")
        self.fire_notification("New Email", f"{frm}: {subject}",
                               category="email", action_page="chat")
        try:
            from backend.memory.knowledge_graph import get_graph
            get_graph().add_node("email", f"email:{message_id}",
                                 {"subject": subject, "from": frm,
                                  "thread_id": tid, "account": account})
        except Exception:
            pass
        try:
            from backend.core.operation_log import get_operation_log
            get_operation_log().record("create", "email", message_id, subject)
        except Exception:
            pass


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
