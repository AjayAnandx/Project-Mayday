"""LLM tools for the Planner (tasks, events, reminders, waiting-on, people).

Every write goes through record_change() so the operation log and knowledge
graph stay in sync, whether the change came from chat or the REST API.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from backend.core import recurrence as rec
from backend.core.planner_store import get_planner, now_local

logger = logging.getLogger(__name__)


# ── shared side effects ─────────────────────────────────────────────────────

_ENTITY = {"task": "todo", "waiting": "todo", "reminder": "reminder", "event": "event"}


def record_change(action: str, item: dict, details: dict | None = None):
    """Operation log + knowledge-graph sync for a planner write (best effort)."""
    entity = _ENTITY.get(item.get("kind"), "todo")
    try:
        from backend.core.operation_log import get_operation_log
        get_operation_log().record(action, entity, item["id"], item.get("title", ""), details=details or {})
    except Exception:
        logger.debug("op log failed", exc_info=True)
    try:
        from backend.memory.knowledge_graph import get_graph
        kg = get_graph()
        p = get_planner()
        if action == "delete":
            (kg.delete_event_node if item.get("kind") == "event" else kg.delete_todo_node)(item["id"])
        elif item.get("kind") == "event":
            kg.sync_event(p.to_legacy_event(item))
        elif item.get("kind") in ("task", "waiting"):
            kg.sync_todo(p.to_legacy_todo(item))
    except Exception:
        logger.debug("graph sync failed", exc_info=True)


# ── formatting ──────────────────────────────────────────────────────────────

def _fmt_when(v: str | None) -> str:
    if not v:
        return ""
    d = datetime.fromisoformat(v)
    today = now_local().date()
    if d.date() == today:
        day = "today"
    elif (d.date() - today).days == 1:
        day = "tomorrow"
    else:
        day = d.strftime("%a %d %b")
    return f"{day} {d.strftime('%H:%M')}" if len(v) > 10 else day


def describe_item(i: dict) -> str:
    p = get_planner()
    mark = {"done": "✓", "cancelled": "✗"}.get(i["status"], "○")
    icon = {"event": "📅", "reminder": "⏰", "waiting": "⏳"}.get(i["kind"], "")
    parts = [f"{mark} {icon}{' ' if icon else ''}{i['title']}"]
    when = i.get("occurrence_at") or (i.get("start_at") if i["kind"] == "event" else i.get("due_at"))
    if when:
        parts.append(("at " if i["kind"] == "event" else "due ") + _fmt_when(when))
    if i.get("scheduled_block"):
        parts.append(f"blocked {_fmt_when(i['scheduled_block']['start'])}")
    if i["kind"] == "waiting" and i.get("person_id"):
        person = p.find_person(i["person_id"])
        parts.append(f"waiting on {person['name'] if person else '?'}")
        if i.get("follow_up_at"):
            parts.append(f"follow up {_fmt_when(i['follow_up_at'])}")
    if i.get("priority", 4) < 4:
        parts.append(f"p{i['priority']}")
    if i.get("list"):
        parts.append(f"list:{i['list']}")
    if i.get("tags"):
        parts.append(" ".join(f"#{t}" for t in i["tags"]))
    if i.get("recurrence"):
        parts.append(f"↻ {rec.describe(i['recurrence'])}")
    return " · ".join(parts) + f" [id: {i['id']}]"


def _resolve(ref: str) -> tuple[dict | None, str]:
    """Find an item by id, or by a unique title match. Returns (item, error)."""
    p = get_planner()
    ref = (ref or "").strip()
    if not ref:
        return None, "Missing required parameter: item_id (an id or the item's title)."
    item = p.get_item(ref)
    if item:
        return item, ""
    exact = [i for i in p.all_items() if i["title"].lower() == ref.lower() and i["status"] == "open"]
    if len(exact) == 1:
        return exact[0], ""
    hits = [i for i in p.search(ref, limit=5) if i["status"] == "open"]
    if len(hits) == 1:
        return hits[0], ""
    if hits:
        opts = "; ".join(describe_item(h) for h in hits[:5])
        return None, f"'{ref}' matches several items — call again with the id. Candidates: {opts}"
    return None, f"No planner item found for '{ref}'. Use plan_list to find the id."


_ISO_WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?$")
_PRIORITY_WORDS = {"urgent": 1, "critical": 1, "highest": 1, "high": 1, "important": 1, "p1": 1,
                   "medium": 2, "normal": 2, "p2": 2, "low": 3, "p3": 3,
                   "none": 4, "no": 4, "lowest": 4, "p4": 4}


def resolve_when(val):
    """Turn natural phrases ('friday', 'tomorrow 6pm', 'next monday 9am') into local
    'YYYY-MM-DD[THH:MM]' in code, so weekday arithmetic never depends on the model.
    ISO input passes through (normalized); unparseable text is returned unchanged
    so the store raises its usual validation error."""
    if val in (None, ""):
        return val
    v = str(val).strip()
    if _ISO_WHEN.match(v):
        return v.replace(" ", "T")[:16]
    from backend.core.planner_parse import parse_quick_add
    parsed = parse_quick_add(f"x {v}", now=now_local().replace(second=0, microsecond=0))
    return parsed.get("due_at") or parsed.get("start_at") or v


def normalize_priority(val):
    """1 high · 2 medium · 3 low · 4 none. Accepts ints or words ('high', 'urgent', 'p1')."""
    if val in (None, ""):
        return None
    if isinstance(val, str):
        w = val.strip().lower().lstrip("!")
        if w in _PRIORITY_WORDS:
            return _PRIORITY_WORDS[w]
        try:
            val = int(w)
        except ValueError:
            return None
    try:
        return min(4, max(1, int(val)))
    except (TypeError, ValueError):
        return None


def _fields(due=None, start=None, end=None, follow_up=None, **kw) -> dict:
    if "priority" in kw:
        kw["priority"] = normalize_priority(kw["priority"])
    out = {k: v for k, v in kw.items() if v not in (None, "")}
    for src, dst in (("due", "due_at"), ("start", "start_at"), ("end", "end_at"), ("follow_up", "follow_up_at")):
        val = locals()[src]
        if val not in (None, ""):
            out[dst] = resolve_when(val)
    if "list_name" in out:
        out["list"] = out.pop("list_name")
    return out


# ── tools ───────────────────────────────────────────────────────────────────

def plan_add(title: str, kind: str = "task", due: str = "", start: str = "", end: str = "",
             notes: str = "", list_name: str = "", tags: list | None = None, priority: int | None = None,
             recurrence: dict | None = None, reminders: list | None = None,
             estimate_min: int | None = None, all_day: bool = False, force: bool = False) -> str:
    p = get_planner()
    kind = (kind or "task").lower()
    if kind == "todo":
        kind = "task"
    if kind == "event" and not start:
        start = due
        due = ""
    start, due = resolve_when(start), resolve_when(due)
    if not force:
        day = (start or due or "")[:10] or None
        dups = [d for d in p.find_duplicates(title, day=day) if d["status"] == "open"]
        if dups:
            return ("⚠️ Possible duplicate — not created. Existing: "
                    + "; ".join(describe_item(d) for d in dups[:3])
                    + ". Ask the user, then call again with force=true if they still want a new one.")
    try:
        item = p.create_item(title, kind=kind, **_fields(
            due=due, start=start, end=end, notes=notes, list_name=list_name, tags=tags,
            priority=priority, recurrence=recurrence, reminders=reminders,
            estimate_min=estimate_min, all_day=all_day or None, source={"type": "llm"}))
    except ValueError as e:
        return f"Could not create item: {e}"
    record_change("create", item)
    return f"Created {kind}: {describe_item(item)}"


def plan_update(item_id: str, title: str = "", due: str = "", start: str = "", end: str = "",
                notes: str = "", list_name: str = "", tags: list | None = None, priority: int | None = None,
                recurrence: dict | None = None, reminders: list | None = None,
                estimate_min: int | None = None, status: str = "", follow_up: str = "",
                clear_due: bool = False) -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    fields = _fields(title=title, due=due, start=start, end=end, notes=notes, list_name=list_name,
                     tags=tags, priority=priority, recurrence=recurrence, reminders=reminders,
                     estimate_min=estimate_min, status=status, follow_up=follow_up)
    if clear_due:
        fields["due_at"] = None
    if not fields:
        return "Nothing to update — pass at least one field to change."
    try:
        updated = get_planner().update_item(item["id"], **fields)
    except ValueError as e:
        return f"Could not update: {e}"
    record_change("update", updated, details={k: str(v) for k, v in fields.items()})
    return f"Updated: {describe_item(updated)}"


def plan_complete(item_id: str, done: bool = True) -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    res = get_planner().complete_item(item["id"], done=done)
    record_change("update", res, details={"completed": done})
    if res.get("_rolled_to"):
        return f"✓ Done for this time. '{res['title']}' repeats — next one {_fmt_when(res['_rolled_to'])}. [id: {res['id']}]"
    return f"{'Completed' if done else 'Reopened'}: {describe_item(res)}"


def plan_delete(item_id: str) -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    get_planner().delete_item(item["id"])
    record_change("delete", item)
    return f"Deleted {item['kind']} '{item['title']}' [id: {item['id']}]"


def plan_list(view: str = "today", query: str = "", list_name: str = "", tag: str = "",
              person: str = "", start: str = "", end: str = "", days: int = 14) -> str:
    p = get_planner()
    person_id = None
    if person:
        pr = p.find_person(person)
        if not pr:
            return f"No person named '{person}' in the planner."
        person_id = pr["id"]
    try:
        items = p.list_items(view or "today", start=start or None, end=end or None,
                             list_name=list_name or None, tag=tag or None, query=query or None,
                             person_id=person_id, days=days)
    except ValueError as e:
        return str(e)
    if not items:
        return f"Nothing in {view}."
    head = f"{view.capitalize()} ({len(items)}):"
    return head + "\n" + "\n".join(f"  {describe_item(i)}" for i in items[:60])


def plan_snooze(item_id: str, minutes: int = 10, until: str = "") -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    res = get_planner().snooze_item(item["id"], minutes=minutes, until=resolve_when(until) or None)
    record_change("update", res, details={"snoozed_until": res["snoozed_until"]})
    return f"Snoozed '{res['title']}' until {_fmt_when(res['snoozed_until'])}."


def plan_schedule(item_id: str, start: str, end: str = "") -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    res = get_planner().schedule_item(item["id"], resolve_when(start) or None, resolve_when(end) or None)
    record_change("update", res, details={"scheduled_block": res.get("scheduled_block")})
    if not res.get("scheduled_block"):
        return f"Removed the time block from '{res['title']}'."
    b = res["scheduled_block"]
    return f"Blocked {_fmt_when(b['start'])}–{b['end'][11:]} for '{res['title']}'."


def plan_delegate(title: str, person: str, due: str = "", follow_up: str = "",
                  notes: str = "", email: str = "") -> str:
    if not person:
        return "Missing required parameter: person (who is doing it)."
    due_at, follow_at = resolve_when(due) or None, resolve_when(follow_up) or None
    if due_at and follow_at and follow_at[:10] > due_at[:10]:
        follow_at = due_at  # first chase lands no later than the deadline
    item = get_planner().delegate(title, person, due_at=due_at,
                                  follow_up_at=follow_at,
                                  notes=notes, email=email, source={"type": "llm"})
    record_change("create", item, details={"delegated_to": person})
    hint = "" if (get_planner().find_person(person) or {}).get("email") else \
        f" (No email saved for {person} — add one with plan_people so Mayday can draft follow-ups.)"
    return f"Tracking: {describe_item(item)}{hint}"


def plan_people(action: str = "list", name: str = "", email: str = "", phone: str = "",
                relation: str = "", notes: str = "") -> str:
    p = get_planner()
    action = (action or "list").lower()
    if action == "list":
        people = p.list_people()
        if not people:
            return "No people saved yet."
        return "People:\n" + "\n".join(
            f"  {x['name']}{' <' + x['email'] + '>' if x.get('email') else ''}"
            f" — they owe {x['waiting_count']}, you owe {x['owed_count']} [id: {x['id']}]" for x in people)
    if not name:
        return f"Missing required parameter: name for plan_people action '{action}'."
    if action in ("add", "create", "save"):
        pr = p.create_person(name, email=email, phone=phone, relation=relation, notes=notes)
        if email or phone or relation or notes:
            pr = p.update_person(pr["id"], email=email or None, phone=phone or None,
                                 relation=relation or None, notes=notes or None) or pr
        return f"Saved {pr['name']}{' <' + pr['email'] + '>' if pr.get('email') else ''} [id: {pr['id']}]"
    pr = p.find_person(name)
    if not pr:
        return f"No person named '{name}'. Use action='add' to save them."
    if action == "update":
        pr = p.update_person(pr["id"], email=email or None, phone=phone or None,
                             relation=relation or None, notes=notes or None)
        return f"Updated {pr['name']} [id: {pr['id']}]"
    if action in ("show", "get", "ledger"):
        led = p.person_ledger(pr["id"])
        lines = [f"{pr['name']}{' <' + pr['email'] + '>' if pr.get('email') else ''}"]
        lines.append(f"They owe you ({len(led['they_owe'])}):")
        lines += [f"  {describe_item(i)}" for i in led["they_owe"]] or ["  —"]
        lines.append(f"You owe them ({len(led['i_owe'])}):")
        lines += [f"  {describe_item(i)}" for i in led["i_owe"]] or ["  —"]
        return "\n".join(lines)
    return f"Unknown action '{action}' for plan_people. Valid: list, add, update, show."


def plan_nudge(item_id: str) -> str:
    item, err = _resolve(item_id)
    if not item:
        return err
    from backend.core.planner_nudge import draft_nudge
    res = draft_nudge(item["id"])
    if res.get("drafted"):
        return (f"Drafted a follow-up to {res['to']} (draft id: {res['draft_id']}), subject "
                f"'{res['subject']}'. Show it to the user and send ONLY after they approve.")
    preview = f" Suggested text:\n{res['body']}" if res.get("body") else ""
    return f"No draft created: {res.get('reason')}.{preview}"


def plan_day(date: str = "", day_start: str = "09:00", day_end: str = "18:00") -> str:
    """Propose time blocks for today's open tasks in the gaps between events."""
    from backend.core.planner_autoplan import propose_day
    proposal = propose_day(date or None, day_start, day_end)
    if not proposal["blocks"]:
        return proposal["summary"]
    lines = [proposal["summary"]]
    lines += [f"  {b['start'][11:]}–{b['end'][11:]}  {b['title']} [id: {b['item_id']}]" for b in proposal["blocks"]]
    if proposal["unplaced"]:
        lines.append("Didn't fit: " + ", ".join(u["title"] for u in proposal["unplaced"]))
    lines.append("Ask the user to confirm, then call plan_schedule for each block they accept.")
    return "\n".join(lines)
