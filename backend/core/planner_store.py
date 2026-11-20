"""Planner store — the single source of truth for tasks, events, reminders and
waiting-on (delegated) items, plus the people they involve.

Replaces the separate todo/event lists in data.json and reminders.json. The old
DataStore todo/event methods and the scheduler's reminder API are thin adapters
over this store, so existing callers (dashboard, search, graph sync, REST) keep
working.

Times are stored as naive LOCAL wall-clock strings:
    "YYYY-MM-DD"        all-day / date-only
    "YYYY-MM-DDTHH:MM"  timed
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.core import recurrence as rec
from backend.core.search_index import NgramIndex

KINDS = ("task", "event", "reminder", "waiting")
STATUSES = ("open", "done", "cancelled")
VIEWS = ("inbox", "today", "upcoming", "waiting", "done", "all", "calendar")
DEFAULT_EVENT_REMINDER_MIN = 30
OVERDUE_ALERT_HOUR = 9
ALERT_GRACE = timedelta(hours=6)       # never fire alerts older than this (no floods after downtime)
FIRED_RETENTION = timedelta(days=21)

_ROOT = Path(__file__).resolve().parent.parent.parent

# Fields callers may set through create/update.
_EDITABLE = {
    "kind", "title", "notes", "status", "list", "tags", "priority",
    "start_at", "due_at", "end_at", "all_day", "deadline", "estimate_min",
    "scheduled_block", "reminders", "recurrence", "parent_id", "checklist",
    "person_id", "follow_up_at", "snoozed_until", "source",
}


# ── time helpers ────────────────────────────────────────────────────────────

def now_local() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def norm_time(value) -> str | None:
    """Normalize any ISO-ish date/datetime to local 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'.

    Timezone-aware inputs (e.g. '...Z') are converted to local time.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat()
    else:
        s = str(value).strip()
        if len(s) == 10:
            date.fromisoformat(s)  # validate
            return s
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_time(value: str | None) -> tuple[datetime | None, bool]:
    """(datetime, has_time). Date-only values become midnight with has_time=False."""
    if not value:
        return None, False
    if len(value) == 10:
        return datetime.fromisoformat(value), False
    return datetime.fromisoformat(value), True


def _fmt(dt: datetime, has_time: bool) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M") if has_time else dt.strftime("%Y-%m-%d")


def _utc_stamp() -> str:
    return datetime.now().astimezone().isoformat()


def _anchor_field(item: dict) -> str:
    return "start_at" if item["kind"] == "event" else "due_at"


# ── store ───────────────────────────────────────────────────────────────────

class PlannerStore:
    def __init__(self, base_dir: Path | str | None = None, migrate: bool = True):
        if base_dir is None:
            try:
                from backend.core.config import load_config
                cfg_path = (load_config().get("data", {}) or {}).get("planner_path")
            except Exception:
                cfg_path = None
            base_dir = Path(cfg_path) if cfg_path else _ROOT / "planner"
            if not base_dir.is_absolute():
                base_dir = _ROOT / base_dir
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items_path = self._dir / "items.json"
        self._people_path = self._dir / "people.json"
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        self._people: dict[str, dict] = {}
        self._fired: dict[str, str] = {}
        self._idx = NgramIndex(3)
        fresh = not self._items_path.exists()
        self._load()
        if fresh and migrate:
            self.migrate_legacy()

    # persistence ------------------------------------------------------------
    def _load(self):
        if self._items_path.exists():
            try:
                data = json.loads(self._items_path.read_text(encoding="utf-8"))
                self._items = {i["id"]: i for i in data.get("items", [])}
                self._fired = data.get("fired", {})
            except (json.JSONDecodeError, OSError):
                pass
        if self._people_path.exists():
            try:
                data = json.loads(self._people_path.read_text(encoding="utf-8"))
                self._people = {p["id"]: p for p in data.get("people", [])}
            except (json.JSONDecodeError, OSError):
                pass
        for it in self._items.values():
            self._index(it)

    @staticmethod
    def _atomic_write(path: Path, payload: dict):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def _save(self):
        self._atomic_write(self._items_path, {
            "version": 1, "items": list(self._items.values()), "fired": self._fired,
        })

    def _save_people(self):
        self._atomic_write(self._people_path, {"version": 1, "people": list(self._people.values())})

    def _index(self, item: dict):
        self._idx.update(item["id"], f"{item['title']} {item.get('notes', '')} {' '.join(item.get('tags', []))}")

    # validation -------------------------------------------------------------
    def _clean(self, fields: dict, existing: dict | None = None) -> dict:
        out = {k: v for k, v in fields.items() if k in _EDITABLE}
        if "kind" in out and out["kind"] not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if "status" in out and out["status"] not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        for k in ("start_at", "due_at", "end_at", "deadline", "follow_up_at", "snoozed_until"):
            if k in out:
                out[k] = norm_time(out[k])
        if "priority" in out:
            out["priority"] = max(1, min(4, int(out["priority"] or 4)))
        if "recurrence" in out:
            out["recurrence"] = rec.normalize_rule(out["recurrence"])
        if "tags" in out:
            tags = out["tags"] or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            out["tags"] = [t.strip().lstrip("#") for t in tags if t and t.strip()]
        if "reminders" in out and out["reminders"] is not None:
            out["reminders"] = [self._clean_reminder(r) for r in out["reminders"]]
        if "checklist" in out:
            out["checklist"] = [
                {"id": c.get("id") or uuid.uuid4().hex[:8], "text": str(c.get("text", "")).strip(),
                 "done": bool(c.get("done"))}
                for c in (out["checklist"] or []) if str(c.get("text", "")).strip()
            ]
        if "scheduled_block" in out and out["scheduled_block"]:
            b = out["scheduled_block"]
            out["scheduled_block"] = {"start": norm_time(b["start"]), "end": norm_time(b["end"])}
        if "estimate_min" in out and out["estimate_min"] is not None:
            out["estimate_min"] = max(0, int(out["estimate_min"]))
        return out

    @staticmethod
    def _clean_reminder(r) -> dict:
        if isinstance(r, (int, float)):
            r = {"offset_min": int(r)}
        elif isinstance(r, str):
            r = {"at": r}
        out = {"id": r.get("id") or uuid.uuid4().hex[:8]}
        if r.get("at"):
            out["at"] = norm_time(r["at"])
        else:
            out["offset_min"] = int(r.get("offset_min", 0))
        return out

    # items CRUD -------------------------------------------------------------
    def create_item(self, title: str, kind: str = "task", item_id: str | None = None, **fields) -> dict:
        if not title or not str(title).strip():
            raise ValueError("title is required")
        ts = _utc_stamp()
        item = {
            "id": item_id or uuid.uuid4().hex[:12],
            "kind": kind, "title": str(title).strip(), "notes": "",
            "status": "open", "completed_at": None,
            "list": "", "tags": [], "priority": 4,
            "start_at": None, "due_at": None, "end_at": None, "all_day": False,
            "deadline": None, "estimate_min": None, "scheduled_block": None,
            "reminders": None,            # None = kind defaults; [] = explicitly none
            "recurrence": None, "completions": [],
            "parent_id": None, "checklist": [],
            "person_id": None, "follow_up_at": None, "chase_log": [],
            "snoozed_until": None,
            "source": {"type": "manual"},
            "created_at": ts, "updated_at": ts,
        }
        item.update(self._clean({"kind": kind, **fields}))
        self._apply_kind_rules(item)
        with self._lock:
            self._items[item["id"]] = item
            self._index(item)
            self._save()
        _signal("create", item)
        return dict(item)

    @staticmethod
    def _apply_kind_rules(item: dict):
        if item["kind"] == "event":
            start, has_time = parse_time(item.get("start_at"))
            item["all_day"] = bool(item.get("all_day")) or (start is not None and not has_time)
            if start and not item.get("end_at") and has_time:
                item["end_at"] = _fmt(start + timedelta(hours=1), True)
        if item["kind"] == "reminder" and not item.get("due_at"):
            item["due_at"] = _fmt(now_local() + timedelta(minutes=1), True)

    def update_item(self, item_id: str, **fields) -> dict | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            clean = self._clean(fields, item)
            if "status" in clean:
                if clean["status"] == "done" and item["status"] != "done":
                    item["completed_at"] = _utc_stamp()
                elif clean["status"] == "open":
                    item["completed_at"] = None
            before_due = item.get("due_at") or item.get("start_at")
            item.update(clean)
            self._apply_kind_rules(item)
            item["updated_at"] = _utc_stamp()
            self._index(item)
            self._save()
            out = dict(item)
        fields_changed = sorted(clean)
        if "snoozed_until" in clean and clean["snoozed_until"]:
            action = "snooze"
        elif (("due_at" in clean or "start_at" in clean) and before_due
              and (item.get("due_at") or item.get("start_at") or "") > before_due):
            action = "postpone"
        elif clean.get("status") == "done":
            action = "complete"
        else:
            action = "update"
        _signal(action, out, fields=fields_changed)
        return out

    def delete_item(self, item_id: str) -> bool:
        with self._lock:
            _gone = self._items.pop(item_id, None)
            if _gone is None:
                return False
            _signal("delete", _gone)
            self._idx.remove(item_id)
            for child in [i for i in self._items.values() if i.get("parent_id") == item_id]:
                child["parent_id"] = None
            self._save()
            return True

    def get_item(self, item_id: str) -> dict | None:
        with self._lock:
            it = self._items.get(item_id)
            return dict(it) if it else None

    def complete_item(self, item_id: str, done: bool = True) -> dict | None:
        """Complete an item. Recurring items roll forward to their next occurrence."""
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            if not done:
                return self.update_item(item_id, status="open")
            rule = item.get("recurrence")
            field = _anchor_field(item)
            anchor, has_time = parse_time(item.get(field))
            if rule and anchor:
                completed_at = now_local()
                nxt = rec.advance(anchor, rule, completed_at, len(item.get("completions", [])))
                item.setdefault("completions", []).append(
                    {"at": _utc_stamp(), "due": item.get(field)})
                if nxt is not None:
                    shift = nxt - anchor
                    item[field] = _fmt(nxt, has_time)
                    if item.get("end_at"):
                        e, e_time = parse_time(item["end_at"])
                        item["end_at"] = _fmt(e + shift, e_time)
                    if item.get("follow_up_at"):
                        f, f_time = parse_time(item["follow_up_at"])
                        item["follow_up_at"] = _fmt(f + shift, f_time)
                    for c in item.get("checklist", []):
                        c["done"] = False
                    item["snoozed_until"] = None
                    item["scheduled_block"] = None
                    item["updated_at"] = _utc_stamp()
                    self._save()
                    out = dict(item)
                    out["_rolled_to"] = item[field]
                    _signal("complete", out, recurring=True)
                    return out
            item["status"] = "done"
            item["completed_at"] = _utc_stamp()
            item["snoozed_until"] = None
            item["updated_at"] = _utc_stamp()
            self._save()
            _signal("complete", item)
            return dict(item)

    def snooze_item(self, item_id: str, minutes: int | None = None, until: str | None = None) -> dict | None:
        target = norm_time(until) if until else _fmt(now_local() + timedelta(minutes=minutes or 10), True)
        return self.update_item(item_id, snoozed_until=target)

    def schedule_item(self, item_id: str, start: str | None, end: str | None = None) -> dict | None:
        """Time-block a task into a calendar slot (start=None clears the block)."""
        if not start:
            return self.update_item(item_id, scheduled_block=None)
        item = self.get_item(item_id)
        if not item:
            return None
        s, _ = parse_time(norm_time(start))
        if end:
            e, _ = parse_time(norm_time(end))
        else:
            e = s + timedelta(minutes=item.get("estimate_min") or 30)
        return self.update_item(item_id, scheduled_block={"start": _fmt(s, True), "end": _fmt(e, True)})

    # queries ----------------------------------------------------------------
    def all_items(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items.values()]

    def search(self, query: str, limit: int = 30) -> list[dict]:
        ids = self._idx.search_top(query, top_k=limit)
        with self._lock:
            return [dict(self._items[i]) for i in ids if i in self._items]

    def find_duplicates(self, title: str, kind: str | None = None, day: str | None = None,
                        exclude_id: str | None = None) -> list[dict]:
        q = title.strip().lower()
        out = []
        for it in self.all_items():
            if it["id"] == exclude_id or it["title"].strip().lower() != q:
                continue
            if kind and it["kind"] != kind:
                continue
            if day:
                anchor = it.get(_anchor_field(it)) or ""
                if anchor and anchor[:10] != day[:10]:
                    continue
            out.append(it)
        return out

    def expand(self, item: dict, start: datetime, end: datetime) -> list[dict]:
        """Instances of `item` whose anchor falls in [start, end] (recurrence-aware)."""
        field = _anchor_field(item)
        anchor, has_time = parse_time(item.get(field))
        if anchor is None:
            return []
        rule = item.get("recurrence")
        # date-only anchors match the whole day
        lo = start.replace(hour=0, minute=0) if not has_time else start
        if not rule:
            return [dict(item, occurrence_at=item[field])] if lo <= anchor <= end else []
        out = []
        dur = None
        if item.get("end_at"):
            e, _ = parse_time(item["end_at"])
            dur = e - anchor
        for occ in rec.occurrences(anchor, rule, lo, end):
            inst = dict(item)
            inst[field] = _fmt(occ, has_time)
            inst["occurrence_at"] = inst[field]
            inst["_instance"] = occ != anchor
            if dur is not None:
                inst["end_at"] = _fmt(occ + dur, has_time)
            out.append(inst)
        return out

    def list_items(self, view: str = "all", start: str | None = None, end: str | None = None,
                   list_name: str | None = None, tag: str | None = None, query: str | None = None,
                   kinds: tuple | list | None = None, person_id: str | None = None,
                   include_done: bool = False, days: int = 14) -> list[dict]:
        if view not in VIEWS:
            raise ValueError(f"view must be one of {VIEWS}")
        items = self.search(query, limit=200) if query else self.all_items()
        if kinds:
            items = [i for i in items if i["kind"] in kinds]
        if list_name:
            items = [i for i in items if (i.get("list") or "").lower() == list_name.lower()]
        if tag:
            items = [i for i in items if tag.lower().lstrip("#") in [t.lower() for t in i.get("tags", [])]]
        if person_id:
            items = [i for i in items if i.get("person_id") == person_id]

        now = now_local()
        today = now.date()
        open_items = [i for i in items if i["status"] == "open"]

        if view == "all":
            out = items if include_done else open_items
        elif view == "done":
            out = sorted([i for i in items if i["status"] == "done" or i.get("completions")],
                         key=lambda i: i.get("completed_at") or (i.get("completions") or [{}])[-1].get("at", ""),
                         reverse=True)
            return out[:100]
        elif view == "inbox":
            out = [i for i in open_items if i["kind"] == "task" and not i.get("due_at")
                   and not i.get("list") and not i.get("scheduled_block") and not i.get("parent_id")]
        elif view == "waiting":
            out = [i for i in open_items if i["kind"] == "waiting"]
            out.sort(key=lambda i: i.get("follow_up_at") or i.get("due_at") or "9999")
            return out
        elif view == "today":
            day_start = datetime.combine(today, datetime.min.time())
            day_end = day_start + timedelta(days=1) - timedelta(minutes=1)
            out = []
            for i in open_items:
                if i["kind"] == "event":
                    out.extend(self.expand(i, day_start, day_end))
                    continue
                due = (i.get("due_at") or "")[:10]
                fu = (i.get("follow_up_at") or "")[:10]
                blk = ((i.get("scheduled_block") or {}).get("start") or "")[:10]
                t = today.isoformat()
                if (due and due <= t) or (fu and fu <= t) or blk == t:
                    out.append(i)
        elif view in ("upcoming", "calendar"):
            if view == "calendar":
                lo = datetime.fromisoformat(norm_time(start)) if start else datetime.combine(today.replace(day=1), datetime.min.time())
                hi = datetime.fromisoformat(norm_time(end)) if end else lo + timedelta(days=42)
                if len(norm_time(end) or "") == 10:
                    hi = hi + timedelta(days=1) - timedelta(minutes=1)
                pool = items if include_done else [i for i in items if i["status"] != "cancelled"]
            else:
                lo = datetime.combine(today, datetime.min.time())
                hi = lo + timedelta(days=days)
                pool = open_items
            out = []
            for i in pool:
                inst = self.expand(i, lo, hi)
                out.extend(inst)
                blk = i.get("scheduled_block")
                if blk and not inst:
                    b, _ = parse_time(blk["start"])
                    if lo <= b <= hi:
                        out.append(dict(i, occurrence_at=blk["start"]))
        else:
            out = open_items
        out.sort(key=self._sort_key)
        return out

    @staticmethod
    def _sort_key(i: dict):
        when = (i.get("occurrence_at") or (i.get("scheduled_block") or {}).get("start")
                or i.get("start_at") or i.get("due_at") or i.get("follow_up_at") or "9999-12-31")
        return (when[:10], 0 if len(when) == 10 else 1, when, i.get("priority", 4), i["title"].lower())

    def lists(self) -> list[dict]:
        counts: dict[str, int] = {}
        for i in self.all_items():
            if i.get("list") and i["status"] == "open":
                counts[i["list"]] = counts.get(i["list"], 0) + 1
        return [{"name": k, "open": v} for k, v in sorted(counts.items())]

    def counts(self) -> dict:
        today = now_local().date().isoformat()
        c = {v: 0 for v in ("inbox", "today", "upcoming", "waiting", "overdue")}
        c["inbox"] = len(self.list_items("inbox"))
        c["today"] = len(self.list_items("today"))
        c["upcoming"] = len(self.list_items("upcoming", days=7))
        c["waiting"] = len(self.list_items("waiting"))
        c["overdue"] = sum(
            1 for i in self.all_items()
            if i["status"] == "open" and i["kind"] in ("task", "waiting", "reminder")
            and i.get("due_at") and i["due_at"][:10] < today
        )
        return c

    # people -----------------------------------------------------------------
    def create_person(self, name: str, email: str = "", phone: str = "", relation: str = "",
                      notes: str = "") -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required")
        with self._lock:
            existing = self.find_person(name)
            if existing:
                return existing
            p = {"id": uuid.uuid4().hex[:10], "name": name, "email": email.strip(),
                 "phone": phone.strip(), "relation": relation.strip(), "notes": notes,
                 "created_at": _utc_stamp(), "updated_at": _utc_stamp()}
            self._people[p["id"]] = p
            self._save_people()
        try:
            from backend.core.awareness_observer import _ensure_person_node
            _ensure_person_node(name, relation or "contact")
        except Exception:
            pass
        return dict(p)

    def update_person(self, person_id: str, **fields) -> dict | None:
        with self._lock:
            p = self._people.get(person_id)
            if not p:
                return None
            for k in ("name", "email", "phone", "relation", "notes"):
                if k in fields and fields[k] is not None:
                    p[k] = str(fields[k]).strip()
            p["updated_at"] = _utc_stamp()
            self._save_people()
            return dict(p)

    def delete_person(self, person_id: str) -> bool:
        with self._lock:
            if self._people.pop(person_id, None) is None:
                return False
            for it in self._items.values():
                if it.get("person_id") == person_id:
                    it["person_id"] = None
            self._save_people()
            self._save()
            return True

    def find_person(self, name_or_id: str) -> dict | None:
        key = (name_or_id or "").strip().lower()
        if not key:
            return None
        with self._lock:
            if name_or_id in self._people:
                return dict(self._people[name_or_id])
            for p in self._people.values():
                if p["name"].lower() == key or (p.get("email") and p["email"].lower() == key):
                    return dict(p)
            # unique first-name match ("Ravi" → "Ravi Kumar")
            hits = [p for p in self._people.values() if p["name"].lower().split()[0] == key]
            return dict(hits[0]) if len(hits) == 1 else None

    def list_people(self) -> list[dict]:
        with self._lock:
            people = [dict(p) for p in self._people.values()]
        for p in people:
            led = self.person_ledger(p["id"])
            p["waiting_count"] = len(led["they_owe"])
            p["owed_count"] = len(led["i_owe"])
        return sorted(people, key=lambda p: p["name"].lower())

    def person_ledger(self, person_id: str) -> dict:
        items = [i for i in self.all_items() if i.get("person_id") == person_id and i["status"] == "open"]
        return {
            "they_owe": [i for i in items if i["kind"] == "waiting"],
            "i_owe": [i for i in items if i["kind"] == "task"],
            "events": [i for i in items if i["kind"] == "event"],
        }

    def delegate(self, title: str, person: str, due_at: str | None = None,
                 follow_up_at: str | None = None, notes: str = "", email: str = "",
                 **extra) -> dict:
        """Create a waiting-on item: `person` owes you `title`.

        follow_up_at defaults to the morning of the due date, else 3 days from now.
        """
        p = self.find_person(person) or self.create_person(person, email=email)
        if email and not p.get("email"):
            p = self.update_person(p["id"], email=email) or p
        if not follow_up_at:
            if due_at:
                d, has_time = parse_time(norm_time(due_at))
                follow_up_at = _fmt(d if has_time else d.replace(hour=OVERDUE_ALERT_HOUR), True)
            else:
                follow_up_at = _fmt((now_local() + timedelta(days=3)).replace(hour=OVERDUE_ALERT_HOUR, minute=0), True)
        return self.create_item(title, kind="waiting", person_id=p["id"], due_at=due_at,
                                follow_up_at=follow_up_at, notes=notes, **extra)

    def log_chase(self, item_id: str, channel: str, note: str = "", draft_id: str = "") -> dict | None:
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return None
            item.setdefault("chase_log", []).append(
                {"at": _utc_stamp(), "channel": channel, "note": note, "draft_id": draft_id})
            item["updated_at"] = _utc_stamp()
            self._save()
            return dict(item)

    # alerts (used by the scheduler) ------------------------------------------
    def effective_reminders(self, item: dict) -> list[dict]:
        if item.get("reminders") is not None:
            return item["reminders"]
        field = _anchor_field(item)
        _, has_time = parse_time(item.get(field))
        if item["kind"] == "event":
            return [{"id": "default", "offset_min": DEFAULT_EVENT_REMINDER_MIN}] if has_time else []
        if item["kind"] in ("task", "reminder") and has_time:
            return [{"id": "default", "offset_min": 0}]
        return []

    def pending_alerts(self, now: datetime | None = None) -> list[dict]:
        """Alerts due at `now` that have not fired yet. Call mark_fired(alert['key']) after delivery."""
        now = now or now_local()
        horizon_lo = now - ALERT_GRACE
        out: list[dict] = []
        for item in self.all_items():
            if item["status"] != "open":
                continue
            kind = item["kind"]
            field = _anchor_field(item)
            # 1) scheduled reminders, per occurrence
            rems = self.effective_reminders(item)
            if rems:
                max_off = max((r.get("offset_min", 0) for r in rems if "at" not in r), default=0)
                for inst in self.expand(item, now - ALERT_GRACE, now + timedelta(minutes=max_off + 1)):
                    occ, occ_time = parse_time(inst[field])
                    if not occ_time:
                        occ = occ.replace(hour=OVERDUE_ALERT_HOUR)
                    for r in rems:
                        if "at" in r:
                            continue
                        fire = occ - timedelta(minutes=r.get("offset_min", 0))
                        if horizon_lo <= fire <= now:
                            out.append(self._alert(item, f"{item['id']}|{r['id']}|{inst[field]}", "reminder",
                                                   occurrence=inst[field], offset=r.get("offset_min", 0)))
                for r in rems:
                    if "at" in r:
                        fire, _ = parse_time(r["at"])
                        if horizon_lo <= fire <= now:
                            out.append(self._alert(item, f"{item['id']}|{r['id']}|{r['at']}", "reminder",
                                                   occurrence=r["at"]))
            # 2) daily 09:00 nudge: overdue items, and date-only items due today
            if kind in ("task", "reminder") and item.get("due_at") and now.hour >= OVERDUE_ALERT_HOUR:
                due, has_time = parse_time(item["due_at"])
                day = now.date().isoformat()
                if due.date() < now.date():
                    out.append(self._alert(item, f"{item['id']}|overdue|{day}", "overdue"))
                elif due.date() == now.date() and not has_time:
                    out.append(self._alert(item, f"{item['id']}|due_today|{day}", "due_today"))
            # 3) waiting-on follow-ups
            if kind == "waiting" and item.get("follow_up_at"):
                fu, _ = parse_time(item["follow_up_at"])
                if fu <= now:
                    out.append(self._alert(item, f"{item['id']}|followup|{item['follow_up_at']}", "follow_up"))
            # 4) snoozes
            if item.get("snoozed_until"):
                s, _ = parse_time(item["snoozed_until"])
                if s <= now:
                    out.append(self._alert(item, f"{item['id']}|snooze|{item['snoozed_until']}", "snooze"))
        with self._lock:
            return [a for a in out if a["key"] not in self._fired]

    def _alert(self, item: dict, key: str, reason: str, occurrence: str | None = None, offset: int = 0) -> dict:
        person = self._people.get(item.get("person_id") or "")
        return {"key": key, "reason": reason, "item": item, "occurrence": occurrence,
                "offset_min": offset, "person": dict(person) if person else None}

    def mark_fired(self, key: str):
        with self._lock:
            self._fired[key] = now_local().isoformat()
            cutoff = (now_local() - FIRED_RETENTION).isoformat()
            self._fired = {k: v for k, v in self._fired.items() if v >= cutoff}
            # a fired snooze is consumed
            parts = key.split("|")
            if len(parts) == 3 and parts[1] == "snooze" and parts[0] in self._items:
                self._items[parts[0]]["snoozed_until"] = None
            self._save()

    # legacy shapes ------------------------------------------------------------
    @staticmethod
    def to_legacy_todo(item: dict) -> dict:
        r = item.get("recurrence")
        out = {
            "id": item["id"], "title": item["title"], "description": item.get("notes", ""),
            "due_date": item.get("due_at"), "priority": min(3, item.get("priority") or 2),
            "completed": item["status"] == "done", "tags": item.get("tags", []),
            "created_at": item["created_at"], "updated_at": item["updated_at"],
        }
        if r:
            out["recurrence"] = {"pattern": r["freq"], "interval": r.get("interval", 1),
                                 "end_date": r.get("until"), "count": r.get("count")}
        return out

    @staticmethod
    def to_legacy_event(item: dict) -> dict:
        r = item.get("recurrence")
        out = {
            "id": item["id"], "title": item["title"], "description": item.get("notes", ""),
            "start_time": item.get("occurrence_at") or item.get("start_at"),
            "end_time": item.get("end_at") or item.get("start_at"),
            "all_day": bool(item.get("all_day")),
            "created_at": item["created_at"], "updated_at": item["updated_at"],
        }
        if r:
            out["recurrence"] = {"pattern": r["freq"], "interval": r.get("interval", 1),
                                 "end_date": r.get("until"), "count": r.get("count")}
        if item.get("_instance"):
            out["_recurring"] = True
            out["_original_id"] = item["id"]
        return out

    # migration ----------------------------------------------------------------
    def migrate_legacy(self, data_path: Path | None = None, reminders_path: Path | None = None) -> dict:
        """Import data.json todos/events + reminders.json once. Idempotent (ids preserved)."""
        stats = {"todos": 0, "events": 0, "reminders": 0}
        if data_path is None:
            try:
                from backend.core.config import load_config
                p = Path((load_config().get("data", {}) or {}).get("storage_path", "data.json"))
            except Exception:
                p = Path("data.json")
            data_path = p if p.is_absolute() else _ROOT / p
        reminders_path = reminders_path or _ROOT / "reminders.json"

        def _safe(v):
            try:
                return norm_time(v)
            except (ValueError, TypeError):
                return None

        if data_path.exists():
            try:
                data = json.loads(data_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            for t in data.get("todos", []):
                if t.get("id") in self._items:
                    continue
                self._items[t["id"]] = self._legacy_item(t, "task", {
                    "notes": t.get("description", ""), "due_at": _safe(t.get("due_date")),
                    "priority": t.get("priority", 2), "tags": t.get("tags", []),
                    "recurrence": rec.normalize_rule(t.get("recurrence")),
                    "status": "done" if t.get("completed") else "open",
                })
                stats["todos"] += 1
            for e in data.get("events", []):
                if e.get("id") in self._items:
                    continue
                start = _safe(e.get("start_time"))
                self._items[e["id"]] = self._legacy_item(e, "event", {
                    "notes": e.get("description", ""), "start_at": start,
                    "end_at": _safe(e.get("end_time")), "all_day": bool(e.get("all_day")),
                    "recurrence": rec.normalize_rule(e.get("recurrence")),
                })
                stats["events"] += 1
        if reminders_path.exists():
            try:
                rdata = json.loads(reminders_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                rdata = {}
            for r in rdata.get("reminders", []):
                if r.get("id") in self._items:
                    continue
                # legacy reminders were stored as UTC minute strings
                due = _safe(f"{r['datetime']}+00:00") if r.get("datetime") else None
                self._items[r["id"]] = self._legacy_item(
                    {"id": r["id"], "title": r.get("message") or "Reminder",
                     "created_at": r.get("created_at")}, "reminder",
                    {"due_at": due, "status": "done" if r.get("fired") else "open"})
                stats["reminders"] += 1
        for it in self._items.values():
            self._index(it)
        self._save()
        return stats

    def _legacy_item(self, src: dict, kind: str, fields: dict) -> dict:
        ts = src.get("created_at") or _utc_stamp()
        item = {
            "id": src["id"], "kind": kind, "title": (src.get("title") or "Untitled").strip(),
            "notes": "", "status": "open", "completed_at": None, "list": "", "tags": [],
            "priority": 4, "start_at": None, "due_at": None, "end_at": None, "all_day": False,
            "deadline": None, "estimate_min": None, "scheduled_block": None, "reminders": None,
            "recurrence": None, "completions": [], "parent_id": None, "checklist": [],
            "person_id": None, "follow_up_at": None, "chase_log": [], "snoozed_until": None,
            "source": {"type": "migration"}, "created_at": ts,
            "updated_at": src.get("updated_at") or ts,
        }
        item.update({k: v for k, v in fields.items() if v is not None or k in ("due_at", "start_at", "end_at")})
        if item["status"] == "done":
            item["completed_at"] = item["updated_at"]
        return item


_instance: PlannerStore | None = None
_instance_lock = threading.Lock()


def _signal(action: str, item: dict | None, **extra) -> None:
    """Brain V3 P8: Planner changes are explicit signals (never blocks or raises)."""
    if not item:
        return
    try:
        from backend.brain.signals import publish
        publish("planner_change", "backend",
                {"action": action, "kind": item.get("kind"), "priority": item.get("priority"),
                 "source": (item.get("source") or {}).get("type") if isinstance(item.get("source"), dict) else None,
                 **extra}, subject=item.get("id"))
    except Exception:
        pass


def get_planner() -> PlannerStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PlannerStore()
    return _instance


def set_planner(store: PlannerStore | None):
    """Test hook: swap the singleton."""
    global _instance
    _instance = store
