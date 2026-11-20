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


REMINDERS_PATH = Path(__file__).resolve().parent.parent.parent / "reminders.json"  # legacy; migrated into the planner
BROADCAST_KEEP = 200  # notifications kept for multi-client polling


def _hhmm(value: str | None) -> str:
    if not value or len(value) < 16:
        return ""
    return datetime.fromisoformat(value).strftime("%I:%M %p").lstrip("0")


def build_planner_notification(alert: dict) -> dict:
    """Turn a PlannerStore alert into the UI notification payload."""
    item = alert["item"]
    kind, reason, title = item["kind"], alert["reason"], item["title"]
    person = (alert.get("person") or {}).get("name", "")
    actions = ["done", "snooze"]
    if reason == "reminder" and kind == "event":
        head, cat, actions = "Upcoming event", "event_reminder", ["snooze"]
        when = _hhmm(alert.get("occurrence"))
        body = f"{title}" + (f" at {when}" if when else "")
    elif reason == "reminder" and kind == "reminder":
        head, cat, body = "Reminder", "custom_reminder", title
    elif reason == "reminder":
        head, cat, body = "Task due", "task_due", title
    elif reason == "overdue":
        head, cat, body = "Overdue", "todo_overdue", f"{title} was due {item.get('due_at', '')[:10]}"
    elif reason == "due_today":
        head, cat, body = "Due today", "task_due", title
    elif reason == "follow_up":
        head, cat = f"Follow up with {person or 'them'}", "follow_up"
        body = f"Still waiting on: {title}"
    else:  # snooze
        head, cat, body = "Snoozed reminder", "custom_reminder", title
    return {
        "type": "notification",
        "id": alert["key"],
        "title": head,
        "body": body,
        "category": cat,
        "item_id": item["id"],
        "item_kind": kind,
        "actions": actions,
        "action": {"page": "planner"},
    }


def _auto_draft_nudge(item_id: str) -> bool:
    """Draft (never send) a follow-up email for a waiting item. True if drafted."""
    try:
        from backend.core.planner_nudge import draft_nudge
        return bool(draft_nudge(item_id, automatic=True).get("drafted"))
    except Exception as e:
        logger.warning("auto nudge draft failed for %s: %s", item_id, e)
        return False


class Scheduler:
    def __init__(self):
        self._seen_gmail: set[str] = set()
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._lock = threading.Lock()
        self._fired_notifications: list[dict] = []   # legacy drain-on-read buffer
        self._broadcast: list[tuple[int, dict]] = []  # (seq, notification) for multi-client reads
        self._seq = 0

    # ── reminder API (backed by the Planner store; kind="reminder") ──────────
    @staticmethod
    def _planner():
        from backend.core.planner_store import get_planner
        return get_planner()

    def add_reminder(self, message: str, datetime_str: str) -> tuple[str, bool, str]:
        """Create a reminder at local time `datetime_str`. Past times move to now+1min.

        Returns (id, adjusted, stored_local_time)."""
        from backend.core.planner_store import norm_time, now_local
        adjusted = False
        try:
            normalized = norm_time(datetime_str)
            when = datetime.fromisoformat(normalized)
            if len(normalized) == 10:
                when = when.replace(hour=9)  # date-only reminder → 09:00
        except (ValueError, TypeError):
            when, adjusted = now_local(), True
        if when < now_local():
            when, adjusted = now_local() + timedelta(minutes=1), True
        stored = when.strftime("%Y-%m-%dT%H:%M")
        item = self._planner().create_item(message, kind="reminder", due_at=stored,
                                           source={"type": "reminder_api"})
        return item["id"], adjusted, stored

    def list_reminders(self) -> list[dict]:
        from backend.core.planner_store import now_local
        now = now_local().strftime("%Y-%m-%dT%H:%M")
        out = []
        for it in self._planner().list_items("all", kinds=("reminder",)):
            if (it.get("due_at") or "") >= now[: len(it.get("due_at") or "")]:
                out.append({"id": it["id"], "message": it["title"], "datetime": it["due_at"],
                            "created_at": it["created_at"], "fired": False})
        return out

    def delete_reminder(self, reminder_id: str) -> bool:
        item = self._planner().get_item(reminder_id)
        if not item or item["kind"] != "reminder":
            return False
        return self._planner().delete_item(reminder_id)

    # ── delivery ─────────────────────────────────────────────────────────────
    def get_queue(self) -> asyncio.Queue:
        return self._queue

    def get_fired_notifications(self) -> list[dict]:
        with self._lock:
            result = list(self._fired_notifications)
            self._fired_notifications.clear()
            return result

    def get_fired_since(self, since: int | None) -> dict:
        """Broadcast read: every client sees every notification newer than `since`.

        A client starts with since=-1 (or omitted) to learn the current cursor
        without replaying history, then polls with the returned `seq`.
        """
        with self._lock:
            if since is None or since < 0:
                return {"seq": self._seq, "items": []}
            return {"seq": self._seq, "items": [n for s, n in self._broadcast if s > since]}

    def _deliver(self, n: dict):
        """Single delivery path: broadcast log (multi-tab UI) + legacy drain buffer + WS queue."""
        with self._lock:
            self._seq += 1
            self._broadcast.append((self._seq, n))
            del self._broadcast[:-BROADCAST_KEEP]
            self._fired_notifications.append(n)
        try:
            self._queue.put_nowait(n)
        except Exception:
            pass

    def fire_notification(self, title: str, body: str, category: str = "event_reminder", action_page: str = "chat",
                          extra: dict | None = None):
        self._deliver({**(extra or {}),
            "type": "notification",
            "id": f"immediate_{uuid.uuid4().hex[:8]}",
            "title": title,
            "body": body,
            "category": category,
            "action": {"page": action_page},
        })

    async def run(self):
        logger.info("Scheduler started")
        while True:
            await self._check_planner()
            await self._check_digest()
            await self._check_gmail()
            await self._check_commute()
            await self._check_brain()
            await asyncio.sleep(60)

    async def _check_brain(self):
        """Brain V2 P6: nightly consolidation + weekly persona (each at most once)."""
        try:
            from backend.brain.reflection import maybe_reflect
            await asyncio.get_running_loop().run_in_executor(None, maybe_reflect)
        except Exception as e:
            logger.exception("Scheduler _check_brain error: %s", e)

    # ── planner alerts ───────────────────────────────────────────────────────
    async def _check_planner(self):
        try:
            planner = self._planner()
            for alert in planner.pending_alerts():
                n = build_planner_notification(alert)
                if alert["reason"] == "follow_up":
                    drafted = await asyncio.get_running_loop().run_in_executor(
                        None, _auto_draft_nudge, alert["item"]["id"])
                    if drafted:
                        n["body"] += " — a polite follow-up draft is waiting in Gmail for your approval."
                self._deliver(n)
                planner.mark_fired(alert["key"])
        except Exception as e:
            logger.exception("Scheduler _check_planner error: %s", e)

    async def _check_digest(self):
        try:
            from backend.core.planner_digest import maybe_send_digests
            await asyncio.get_running_loop().run_in_executor(None, maybe_send_digests)
        except Exception as e:
            logger.exception("Scheduler _check_digest error: %s", e)

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
                # Agent slot owns the stored agent_email; a user-slot sync must
                # never overwrite it with the personal address.
                if account == "agent" and prof.get("emailAddress"):
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
        # Brain V3 P8: urgent-message signal (sender identity reduced to "known"/"unknown").
        try:
            from backend.brain.signals import publish
            from backend.brain.timing import important_senders, urgency
            score, reasons = urgency(frm, subject, meta.get("snippet", ""), important_senders())
            if score >= 0.6:
                publish("urgent_message", "backend", {"channel": "gmail", "account": account,
                                                      "score": round(score, 2), "reasons": reasons},
                        subject=message_id)
        except Exception as e:
            logger.debug("urgency scoring failed: %s", e)
        # Emails are not written to the knowledge graph (Brain V2): they live in
        # Gmail + the operation log, and as graph nodes they were 1 in 5 nodes of
        # pure retrieval noise. tid/account stay for the op-log/notification.
        _ = (tid, account)
        try:
            from backend.core.operation_log import get_operation_log
            get_operation_log().record("create", "email", message_id, subject)
        except Exception:
            pass

    async def _check_commute(self):
        """Commute guard: for events starting in ~15-45 min with a place-like
        destination, check live traffic from home and nudge when tight.
        Once per event. Silent when Maps is off/keyless."""
        try:
            from backend.core.config import load_config
            maps_cfg = load_config().get("maps", {}) or {}
        except Exception:
            return
        if not maps_cfg.get("enabled", True) or not (maps_cfg.get("api_key") or "").strip():
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._sync_commute)
        except Exception as e:
            logger.warning("Scheduler _check_commute error: %s", e)

    def _sync_commute(self) -> None:
        import re
        from backend.core.data_store import get_store

        try:
            from backend.core.maps_service import (compute_route, fmt_duration,
                                                   resolve_point, search_places)
        except Exception as e:
            logger.warning("Commute guard maps import failed: %s", e)
            return
        try:
            from backend.core.location import resolve_location
            loc = resolve_location() or {}
        except Exception:
            loc = {}
        now = _utcnow()
        window_end = now + timedelta(minutes=45)
        try:
            events = get_store().list_events(start_date=now.isoformat(),
                                            end_date=window_end.isoformat())
        except Exception:
            return
        for ev in events:
            ev_id = ev.get("id", "")
            key = f"commute:{ev_id}"
            if key in self._seen_gmail:
                continue
            start = ev.get("start_time", "")
            if not start or start <= now.isoformat() or start > window_end.isoformat():
                continue
            text = f"{ev.get('title', '')} {ev.get('description', '')}".strip()
            dest = None
            m = re.search(r"\b(?:at|in|to|@)\s+([A-Z][\w\s&'\-.]{2,40})", text)
            if m:
                dest = m.group(1).strip()
            if not dest:
                continue
            try:
                o = resolve_point("home", loc.get("lat"), loc.get("lon"))
                hits = search_places(dest, o["lat"], o["lng"], max_results=1)
                if not hits or hits[0].get("lat") is None:
                    continue
                h = hits[0]
                d = {"lat": h["lat"], "lng": h["lng"], "label": h["name"]}
                r = compute_route(o, d, mode="drive")
                best = r.get("best", {}) or {}
                dur = best.get("duration_s")
                if dur is None:
                    continue
                from datetime import datetime as _dt
                start_dt = _dt.fromisoformat(start)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=now.tzinfo)
                leave_by = start_dt - timedelta(seconds=dur + 600)
                if now >= leave_by:
                    self._seen_gmail.add(key)
                    self.fire_notification(
                        "Leave now 🚗",
                        f"{ev.get('title', 'Event')} at {start[11:16]} — "
                        f"{fmt_duration(dur)} with traffic to {h['name']}.",
                        category="commute", action_page="chat")
                    try:
                        from backend.brain.signals import publish
                        static = best.get("static_duration_s") or dur
                        publish("traffic_delay", "backend",
                                {"travel_min": round(dur / 60), "delay_min": round(max(0, dur - static) / 60),
                                 "starts_in_min": round((start_dt - now).total_seconds() / 60)},
                                subject=ev_id)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Commute check failed for event %s: %s", ev_id, e)
                continue


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
