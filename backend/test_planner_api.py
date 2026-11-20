"""Planner V2 end-to-end (hermetic): REST API, LLM tools, scheduler delivery,
nudge drafts, digest, quick-add parser and day auto-planner."""
import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import planner_store as ps
from backend.core.planner_store import PlannerStore, set_planner


@pytest.fixture
def planner(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.awareness_observer._ensure_person_node", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr("backend.functions.planner_functions.record_change",
                        lambda action, item, details=None: calls.append((action, item["id"])))
    monkeypatch.setattr("backend.api.planner.record_change",
                        lambda action, item, details=None: calls.append((action, item["id"])))
    store = PlannerStore(base_dir=tmp_path / "planner", migrate=False)
    store.changes = calls
    set_planner(store)
    yield store
    set_planner(None)


@pytest.fixture
def client(planner):
    from backend.api.planner import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def freeze(monkeypatch, iso):
    monkeypatch.setattr(ps, "now_local", lambda: datetime.fromisoformat(iso))
    monkeypatch.setattr(ps, "_utc_stamp", lambda: datetime.fromisoformat(iso).astimezone().isoformat())
    for mod in ("backend.functions.planner_functions",):
        monkeypatch.setattr(f"{mod}.now_local", lambda: datetime.fromisoformat(iso))


# ── REST ────────────────────────────────────────────────────────────────────

def test_rest_crud_complete_and_views(client, planner):
    r = client.post("/api/planner/items", json={"title": "Buy milk", "due_at": "2026-11-18"})
    assert r.status_code == 201
    iid = r.json()["id"]
    assert client.get(f"/api/planner/items/{iid}").json()["title"] == "Buy milk"
    r = client.put(f"/api/planner/items/{iid}", json={"priority": 1, "tags": ["errand"]})
    assert r.json()["priority"] == 1
    assert client.post(f"/api/planner/items/{iid}/complete", json={"done": True}).json()["status"] == "done"
    assert client.get("/api/planner/items", params={"view": "done"}).json()[0]["id"] == iid
    assert client.delete(f"/api/planner/items/{iid}").json() == {"deleted": True}
    assert client.get(f"/api/planner/items/{iid}").status_code == 404
    assert [c[0] for c in planner.changes] == ["create", "update", "update", "delete"]


def test_rest_validation_errors(client):
    assert client.post("/api/planner/items", json={"title": "x", "kind": "bogus"}).status_code == 400
    assert client.get("/api/planner/items", params={"view": "nope"}).status_code == 400


def test_rest_calendar_snooze_schedule(client):
    ev = client.post("/api/planner/items", json={"title": "Sync", "kind": "event",
                                                 "start_at": "2026-11-02T10:00",
                                                 "recurrence": {"freq": "weekly"}}).json()
    cal = client.get("/api/planner/items", params={"view": "calendar", "start": "2026-11-01",
                                                   "end": "2026-11-15"}).json()
    assert [c["occurrence_at"] for c in cal] == ["2026-11-02T10:00", "2026-11-09T10:00"]
    t = client.post("/api/planner/items", json={"title": "Write", "estimate_min": 60}).json()
    s = client.post(f"/api/planner/items/{t['id']}/schedule", json={"start": "2026-11-20T14:00"}).json()
    assert s["scheduled_block"] == {"start": "2026-11-20T14:00", "end": "2026-11-20T15:00"}
    z = client.post(f"/api/planner/items/{ev['id']}/snooze", json={"until": "2026-11-20T09:00"}).json()
    assert z["snoozed_until"] == "2026-11-20T09:00"


def test_rest_quick_add_delegation_and_people(client, planner):
    r = client.post("/api/planner/quick-add", json={"text": "Ravi to send the deck by friday #work"}).json()
    assert r["item"]["kind"] == "waiting" and r["item"]["tags"] == ["work"]
    people = client.get("/api/planner/people").json()
    assert people[0]["name"] == "Ravi" and people[0]["waiting_count"] == 1
    detail = client.get(f"/api/planner/people/{people[0]['id']}").json()
    assert detail["they_owe"][0]["title"] == "Send the deck"
    preview = client.post("/api/planner/quick-add", json={"text": "Gym every mon at 7am", "commit": False}).json()
    assert "item" not in preview and preview["parsed"]["recurrence"]["byweekday"] == [0]


def test_rest_summary(client):
    client.post("/api/planner/items", json={"title": "Inbox one"})
    client.post("/api/planner/items", json={"title": "Listed", "list": "Home", "tags": ["x"]})
    s = client.get("/api/planner/summary").json()
    assert s["counts"]["inbox"] == 1 and s["lists"] == [{"name": "Home", "open": 1}] and s["tags"] == ["x"]


# ── LLM tools ────────────────────────────────────────────────────────────────

def test_tools_add_dedupe_complete_by_title(planner, monkeypatch):
    from backend.functions import planner_functions as pf
    freeze(monkeypatch, "2026-11-18T08:00")
    out = pf.plan_add("Water plants", due="2026-11-18", recurrence={"freq": "daily", "interval": 3})
    assert out.startswith("Created task") and "every 3 days" in out
    assert "duplicate" in pf.plan_add("water plants", due="2026-11-18")
    done = pf.plan_complete("Water plants")
    assert "repeats" in done and "21 Nov" in done
    assert "Nothing in inbox" in pf.plan_list("inbox")


def test_tools_event_uses_start_and_list_views(planner, monkeypatch):
    from backend.functions import planner_functions as pf
    freeze(monkeypatch, "2026-11-18T08:00")
    pf.plan_add("Dentist", kind="event", due="2026-11-18T15:00")  # due → start for events
    ev = planner.all_items()[0]
    assert ev["start_at"] == "2026-11-18T15:00" and ev["due_at"] is None
    assert "Dentist" in pf.plan_list("today")


def test_tools_delegate_people_nudge_without_gmail(planner, monkeypatch):
    from backend.functions import planner_functions as pf
    out = pf.plan_delegate("Send invoice", "Asha")
    assert "waiting on Asha" in out and "No email saved" in out
    assert "No draft created: no email saved" in pf.plan_nudge("Send invoice")
    pf.plan_people("update", name="Asha", email="asha@example.com")
    monkeypatch.setattr("backend.core.gmail_service.is_authenticated", lambda account="agent": False)
    res = pf.plan_nudge("Send invoice")
    assert "Gmail not connected" in res and "Hi Asha" in res
    assert "They owe you (1)" in pf.plan_people("show", name="Asha")


def test_tools_resolve_ambiguity(planner):
    from backend.functions import planner_functions as pf
    planner.create_item("Call bank about card")
    planner.create_item("Call bank about loan")
    assert "matches several items" in pf.plan_complete("call bank")


def test_dispatch_aliases_reach_planner(planner, monkeypatch):
    from backend.assistant.function_registry import dispatch_call

    class _NoLog:
        def record(self, *a, **k):
            pass
    monkeypatch.setattr("backend.functions.reminder_functions.get_operation_log", lambda: _NoLog())
    out = asyncio.run(dispatch_call("plan_add", {"name": "Renew passport", "due_date": "2026-12-01",
                                                 "description": "bring photos"}))
    assert out.startswith("Created task")
    it = planner.all_items()[0]
    assert it["due_at"] == "2026-12-01" and it["notes"] == "bring photos"
    # retired names still dispatch, now backed by the planner
    out = asyncio.run(dispatch_call("create_reminder", {"message": "Stretch", "datetime": "2030-01-01T10:00"}))
    assert "Reminder set" in out
    assert any(i["kind"] == "reminder" for i in planner.all_items())


# ── scheduler delivery ───────────────────────────────────────────────────────

def test_scheduler_delivers_to_rest_poll_with_actions(planner, monkeypatch):
    from backend.core.scheduler import Scheduler
    freeze(monkeypatch, "2026-11-18T14:31")
    planner.create_item("Dentist", kind="event", start_at="2026-11-18T15:00")
    planner.create_item("Old task", due_at="2026-11-10")
    sch = Scheduler()
    asyncio.run(sch._check_planner())
    fired = sch.get_fired_notifications()
    by_cat = {n["category"]: n for n in fired}
    assert set(by_cat) == {"event_reminder", "todo_overdue"}
    assert by_cat["event_reminder"]["body"] == "Dentist at 3:00 PM"
    assert by_cat["todo_overdue"]["actions"] == ["done", "snooze"] and by_cat["todo_overdue"]["item_id"]
    asyncio.run(sch._check_planner())
    assert sch.get_fired_notifications() == []  # each alert fires once


def test_scheduler_follow_up_auto_drafts(planner, monkeypatch):
    from backend.core.scheduler import Scheduler
    freeze(monkeypatch, "2026-11-18T09:01")
    planner.delegate("Send deck", "Ravi", follow_up_at="2026-11-18T09:00", email="ravi@example.com")
    drafts = []

    class _NoLog:
        def record(self, *a, **k):
            pass
    monkeypatch.setattr("backend.core.operation_log.get_operation_log", lambda: _NoLog())
    monkeypatch.setattr("backend.core.gmail_service.is_authenticated", lambda account="agent": True)
    monkeypatch.setattr("backend.core.gmail_service.create_draft",
                        lambda to, subject, text, **kw: drafts.append((to, subject, text)) or {"id": "d1"})
    sch = Scheduler()
    asyncio.run(sch._check_planner())
    n = sch.get_fired_notifications()[0]
    assert n["title"] == "Follow up with Ravi" and "draft is waiting in Gmail" in n["body"]
    assert drafts[0][0] == "ravi@example.com" and "Send deck" in drafts[0][1]
    assert planner.all_items()[0]["chase_log"][0]["draft_id"] == "d1"


def test_scheduler_reminder_api_backed_by_planner(planner, monkeypatch):
    from backend.core.scheduler import Scheduler
    freeze(monkeypatch, "2026-11-18T10:00")
    sch = Scheduler()
    rid, adjusted, stored = sch.add_reminder("Call mom", "2026-11-18T18:30")
    assert not adjusted and stored == "2026-11-18T18:30"
    assert [r["message"] for r in sch.list_reminders()] == ["Call mom"]
    _, adjusted, stored = sch.add_reminder("Late", "2026-11-17T08:00")
    assert adjusted and stored == "2026-11-18T10:01"
    assert sch.delete_reminder(rid) and not sch.delete_reminder(rid)


# ── digest ──────────────────────────────────────────────────────────────────

def test_digest_morning_and_evening(planner, monkeypatch):
    from backend.core import planner_digest as pd
    freeze(monkeypatch, "2026-11-18T07:30")
    planner.create_item("Standup", kind="event", start_at="2026-11-18T10:00")
    planner.create_item("Overdue bill", due_at="2026-11-15", priority=1)
    planner.create_item("Due today", due_at="2026-11-18")
    planner.delegate("Send deck", "Ravi", follow_up_at="2026-11-18T09:00")
    m = pd.build_digest("morning")
    heads = [h for h, _ in m["sections"]]
    assert heads[0] == "Focus on these first" and m["sections"][0][1][0] == "Overdue bill"
    assert any(h.startswith("Follow up today") for h in heads)
    assert "10:00 AM — Standup" in m["text"] and "<h2" in m["html"]
    planner.complete_item(planner.find_duplicates("Due today")[0]["id"])
    e = pd.build_digest("evening")
    assert e["sections"][0] == ("Done today (1)", ["Due today"])


def test_digest_sends_once_per_day(planner, monkeypatch):
    from backend.core import planner_digest as pd
    monkeypatch.setattr(pd, "_cfg", lambda: {"planner": {"digest": {"enabled": True, "morning": "07:30",
                                                                     "evening": "21:00", "to": "me@x.com"}}})
    sent = []
    monkeypatch.setattr("backend.core.gmail_service.is_authenticated", lambda account="agent": True)
    monkeypatch.setattr("backend.core.gmail_service.send_message",
                        lambda to, subject, text, **kw: sent.append((to, subject)) or {"id": "m1"})
    freeze(monkeypatch, "2026-11-18T07:00")
    assert pd.maybe_send_digests(datetime(2026, 11, 18, 7, 0)) == []
    assert pd.maybe_send_digests(datetime(2026, 11, 18, 7, 31)) == ["morning"]
    assert pd.maybe_send_digests(datetime(2026, 11, 18, 8, 15)) == []
    assert pd.maybe_send_digests(datetime(2026, 11, 18, 21, 5)) == ["evening"]
    assert [s[0] for s in sent] == ["me@x.com", "me@x.com"]


# ── auto-plan ───────────────────────────────────────────────────────────────

def test_plan_day_fills_gaps_around_events(planner, monkeypatch):
    from backend.core.planner_autoplan import propose_day
    freeze(monkeypatch, "2026-11-18T08:00")
    planner.create_item("Standup", kind="event", start_at="2026-11-18T09:00", end_at="2026-11-18T09:30")
    planner.create_item("Lunch", kind="event", start_at="2026-11-18T12:00", end_at="2026-11-18T13:00")
    planner.create_item("Big report", due_at="2026-11-18", estimate_min=120, priority=1)
    planner.create_item("Overdue email", due_at="2026-11-10", estimate_min=30)
    planner.create_item("Future", due_at="2026-11-25")
    plan = propose_day("2026-11-18", "09:00", "14:00")
    blocks = [(b["title"], b["start"][11:], b["end"][11:]) for b in plan["blocks"]]
    assert blocks == [("Overdue email", "09:30", "10:00"), ("Big report", "10:00", "12:00")]
    assert plan["unplaced"] == []


def test_notifications_broadcast_to_every_client(planner, monkeypatch):
    from backend.core.scheduler import Scheduler
    sch = Scheduler()
    a = sch.get_fired_since(-1)
    b = sch.get_fired_since(-1)
    assert a == {"seq": 0, "items": []}  # joining never replays history
    sch.fire_notification("Hi", "there")
    tab1 = sch.get_fired_since(a["seq"])
    tab2 = sch.get_fired_since(b["seq"])
    assert [n["title"] for n in tab1["items"]] == ["Hi"] == [n["title"] for n in tab2["items"]]
    assert sch.get_fired_since(tab1["seq"])["items"] == []
    assert [n["title"] for n in sch.get_fired_notifications()] == ["Hi"]  # legacy drain still works


def test_tools_resolve_relative_dates_in_code(planner, monkeypatch):
    """Weekday math happens server-side — 'friday' from Thu 19 Nov is Fri 20 Nov."""
    from backend.functions import planner_functions as pf
    freeze(monkeypatch, "2026-11-19T10:50")
    assert pf.resolve_when("friday") == "2026-11-20"
    assert pf.resolve_when("tomorrow 6pm") == "2026-11-20T18:00"
    assert pf.resolve_when("next monday 9am") == "2026-11-23T09:00"
    assert pf.resolve_when("2026-12-01 14:30") == "2026-12-01T14:30"
    pf.plan_delegate("Budget report", "Ravi", follow_up="friday")
    w = [i for i in planner.all_items() if i["kind"] == "waiting"][0]
    assert w["follow_up_at"].startswith("2026-11-20")
    pf.plan_add("Groceries", due="tomorrow 6pm", priority="high")
    g = planner.find_duplicates("Groceries")[0]
    assert g["due_at"] == "2026-11-20T18:00" and g["priority"] == 1


def test_priority_words_map_to_scale():
    from backend.functions.planner_functions import normalize_priority as n
    assert [n("high"), n("urgent"), n("medium"), n("low"), n("none"), n(2), n("!p1"), n(9), n("x")] == \
           [1, 1, 2, 3, 4, 2, 1, 4, None]


def test_delegate_follow_up_never_after_deadline(planner, monkeypatch):
    from backend.functions import planner_functions as pf
    freeze(monkeypatch, "2026-11-19T10:50")
    pf.plan_delegate("Report", "Ravi", due="friday", follow_up="2026-11-26")
    w = [i for i in planner.all_items() if i["kind"] == "waiting"][0]
    assert w["follow_up_at"][:10] == "2026-11-20"
