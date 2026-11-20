import json
from datetime import datetime, timedelta

import pytest

from backend.core import planner_store as ps
from backend.core.planner_store import PlannerStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    # person nodes go to the knowledge graph — keep tests hermetic
    monkeypatch.setattr("backend.core.awareness_observer._ensure_person_node", lambda *a, **k: False)
    return PlannerStore(base_dir=tmp_path / "planner", migrate=False)


def freeze(monkeypatch, iso):
    monkeypatch.setattr(ps, "now_local", lambda: datetime.fromisoformat(iso))


def test_create_normalizes_times_and_tags(store):
    it = store.create_item("Pay rent", due_at="2026-12-01T09:00:00Z", tags="home, #bills")
    assert it["kind"] == "task" and it["status"] == "open"
    assert len(it["due_at"]) == 16 and "T" in it["due_at"]  # local minute precision
    assert it["tags"] == ["home", "bills"]


def test_event_gets_default_end_and_all_day(store):
    e = store.create_item("Standup", kind="event", start_at="2026-11-20T10:00")
    assert e["end_at"] == "2026-11-20T11:00" and e["all_day"] is False
    d = store.create_item("Holiday", kind="event", start_at="2026-12-25")
    assert d["all_day"] is True


def test_invalid_kind_rejected(store):
    with pytest.raises(ValueError):
        store.create_item("x", kind="nope")


def test_persistence_roundtrip(store, tmp_path):
    store.create_item("Persist me")
    again = PlannerStore(base_dir=tmp_path / "planner", migrate=False)
    assert [i["title"] for i in again.all_items()] == ["Persist me"]


def test_complete_recurring_rolls_forward(store, monkeypatch):
    freeze(monkeypatch, "2026-11-18T10:00")
    it = store.create_item("Gym", due_at="2026-11-18T07:00", recurrence={"freq": "daily"},
                           checklist=[{"text": "stretch", "done": True}])
    done = store.complete_item(it["id"])
    assert done["status"] == "open" and done["due_at"] == "2026-11-19T07:00"
    assert done["_rolled_to"] == "2026-11-19T07:00"
    assert done["checklist"][0]["done"] is False
    assert len(done["completions"]) == 1


def test_complete_non_recurring_marks_done(store):
    it = store.create_item("One-off")
    assert store.complete_item(it["id"])["status"] == "done"
    assert store.complete_item(it["id"], done=False)["status"] == "open"


def test_views(store, monkeypatch):
    freeze(monkeypatch, "2026-11-18T08:00")
    store.create_item("Inbox thing")
    store.create_item("Due today", due_at="2026-11-18")
    store.create_item("Overdue", due_at="2026-11-10")
    store.create_item("Next week", due_at="2026-11-24")
    store.create_item("Weekly sync", kind="event", start_at="2026-01-05T10:00",
                      recurrence={"freq": "weekly"})  # Mondays → none today (Wed)
    store.create_item("Today mtg", kind="event", start_at="2026-11-18T15:00")
    titles = lambda v, **k: [i["title"] for i in store.list_items(v, **k)]
    assert titles("inbox") == ["Inbox thing"]
    assert set(titles("today")) == {"Due today", "Overdue", "Today mtg"}
    up = titles("upcoming", days=7)
    assert "Next week" in up and up.count("Weekly sync") == 1  # Mon 23rd only


def test_calendar_expands_recurring_events(store):
    store.create_item("Weekly sync", kind="event", start_at="2026-01-05T10:00",
                      recurrence={"freq": "weekly"})
    nov = store.list_items("calendar", start="2026-11-01", end="2026-11-30")
    assert [i["occurrence_at"] for i in nov] == [
        "2026-11-02T10:00", "2026-11-09T10:00", "2026-11-16T10:00",
        "2026-11-23T10:00", "2026-11-30T10:00"]
    assert nov[0]["end_at"] == "2026-11-02T11:00"


def test_schedule_block_shows_in_calendar(store):
    it = store.create_item("Write report", estimate_min=90)
    store.schedule_item(it["id"], "2026-11-19T14:00")
    blk = store.get_item(it["id"])["scheduled_block"]
    assert blk == {"start": "2026-11-19T14:00", "end": "2026-11-19T15:30"}
    cal = store.list_items("calendar", start="2026-11-19", end="2026-11-19")
    assert [i["title"] for i in cal] == ["Write report"]


def test_delegate_and_ledger(store, monkeypatch):
    freeze(monkeypatch, "2026-11-18T08:00")
    w = store.delegate("Send the deck", "Ravi Kumar", due_at="2026-11-21", email="ravi@example.com")
    assert w["kind"] == "waiting" and w["follow_up_at"] == "2026-11-21T09:00"
    p = store.find_person("ravi")  # unique first-name match
    assert p and p["email"] == "ravi@example.com"
    assert [i["title"] for i in store.person_ledger(p["id"])["they_owe"]] == ["Send the deck"]
    # default follow-up when no due date: 3 days out at 09:00
    w2 = store.delegate("Share notes", "Ravi Kumar")
    assert w2["follow_up_at"] == "2026-11-21T09:00"
    assert store.list_people()[0]["waiting_count"] == 2


def test_alerts_event_reminder_fires_once(store, monkeypatch):
    store.create_item("Dentist", kind="event", start_at="2026-11-18T15:00")
    freeze(monkeypatch, "2026-11-18T14:20")
    assert store.pending_alerts() == []
    freeze(monkeypatch, "2026-11-18T14:31")
    alerts = store.pending_alerts()
    assert len(alerts) == 1 and alerts[0]["reason"] == "reminder"
    store.mark_fired(alerts[0]["key"])
    assert store.pending_alerts() == []


def test_alerts_recurring_event_after_first_occurrence(store, monkeypatch):
    # regression: recurring events used to be filtered out before expansion
    store.create_item("Weekly sync", kind="event", start_at="2026-01-05T10:00",
                      recurrence={"freq": "weekly"})
    freeze(monkeypatch, "2026-11-16T09:35")
    alerts = store.pending_alerts()
    assert len(alerts) == 1 and alerts[0]["occurrence"] == "2026-11-16T10:00"


def test_alerts_overdue_due_today_followup_snooze(store, monkeypatch):
    freeze(monkeypatch, "2026-11-18T09:05")
    store.create_item("Old", due_at="2026-11-10")
    store.create_item("Today", due_at="2026-11-18")
    w = store.delegate("Deck", "Ravi", follow_up_at="2026-11-18T09:00")
    s = store.create_item("Later")
    store.snooze_item(s["id"], until="2026-11-18T09:00")
    reasons = sorted(a["reason"] for a in store.pending_alerts())
    assert reasons == ["due_today", "follow_up", "overdue", "snooze"]
    snooze = next(a for a in store.pending_alerts() if a["reason"] == "snooze")
    store.mark_fired(snooze["key"])
    assert store.get_item(s["id"])["snoozed_until"] is None
    assert all(a["item"]["id"] != w["id"] or a["person"]["name"] == "Ravi" for a in store.pending_alerts())


def test_alerts_respect_grace_window(store, monkeypatch):
    store.create_item("Ancient", kind="event", start_at="2026-11-01T10:00")
    freeze(monkeypatch, "2026-11-18T10:00")
    assert store.pending_alerts() == []


def test_explicit_empty_reminders_disable_default(store, monkeypatch):
    store.create_item("Quiet", kind="event", start_at="2026-11-18T15:00", reminders=[])
    freeze(monkeypatch, "2026-11-18T14:31")
    assert store.pending_alerts() == []


def test_search_and_duplicates(store):
    store.create_item("Buy milk", due_at="2026-11-20")
    assert [i["title"] for i in store.search("milk")] == ["Buy milk"]
    assert store.find_duplicates("buy MILK", kind="task", day="2026-11-20")
    assert not store.find_duplicates("buy milk", day="2026-11-21")


def test_migration_imports_legacy_and_is_idempotent(tmp_path):
    data = tmp_path / "data.json"
    data.write_text(json.dumps({
        "todos": [{"id": "t1", "title": "Old todo", "description": "d", "due_date": "2026-09-26T21:45:00",
                   "priority": 1, "completed": False, "tags": ["x"], "created_at": "c", "updated_at": "u",
                   "recurrence": {"pattern": "biweekly"}}],
        "events": [{"id": "e1", "title": "Mtg", "start_time": "2026-06-30T10:00:00Z",
                    "end_time": "2026-06-30T11:00:00Z", "all_day": False}],
    }))
    rem = tmp_path / "reminders.json"
    rem.write_text(json.dumps({"reminders": [
        {"id": "r1", "message": "Call mom", "datetime": "2026-12-01T04:30", "fired": False}]}))
    s = PlannerStore(base_dir=tmp_path / "planner", migrate=False)
    stats = s.migrate_legacy(data, rem)
    assert stats == {"todos": 1, "events": 1, "reminders": 1}
    t = s.get_item("t1")
    assert t["kind"] == "task" and t["due_at"] == "2026-09-26T21:45" and t["recurrence"]["interval"] == 2
    assert s.get_item("e1")["kind"] == "event" and len(s.get_item("e1")["start_at"]) == 16
    assert s.get_item("r1")["kind"] == "reminder"
    assert s.migrate_legacy(data, rem) == {"todos": 0, "events": 0, "reminders": 0}


def test_legacy_shapes(store):
    t = store.create_item("T", due_at="2026-11-20", priority=4)
    lt = PlannerStore.to_legacy_todo(t)
    assert lt["due_date"] == "2026-11-20" and lt["priority"] == 3 and lt["completed"] is False
    e = store.create_item("E", kind="event", start_at="2026-11-20T10:00")
    le = PlannerStore.to_legacy_event(e)
    assert le["start_time"] == "2026-11-20T10:00" and le["end_time"] == "2026-11-20T11:00"
