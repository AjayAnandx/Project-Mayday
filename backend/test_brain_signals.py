"""Brain V3 P8: sensory layer — store/bus, privacy, focus/idle/transitions, detectors, API, sensor."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import signals as sg
from backend.brain import timing as tm


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    sensors = {"enabled": True, "pause": False, "desktop": True, "ui": True, "location": False,
               "retention_days": 14, "flush_seconds": 3600, "backend": True}
    monkeypatch.setattr(sg, "_cfg", lambda: dict(sensors))
    bus = sg.SignalBus()
    monkeypatch.setattr(sg, "_BUS", bus)
    timing = tm.TimingState()
    monkeypatch.setattr(tm, "_TIMING", timing)
    bus.subscribe(timing.on_signal)
    # timing publishes through the module-level publish -> route to this bus
    monkeypatch.setattr(tm, "publish", lambda *a, **k: bus.publish(*a, **k))
    yield {"bus": bus, "timing": timing, "sensors": sensors}


def kinds(bus, minutes=10_000):
    return [r["kind"] for r in reversed(bus.recent(minutes=minutes, limit=1000))]


# ---------------------------------------------------------------- store + privacy
def test_sanitize_drops_titles_urls_coords_and_redacts():
    v = sg.sanitize({"title": "Bank statement - Chrome", "url": "https://x", "lat": 13.0, "lon": 80.2,
                     "note": "call 98765 43210 or a@b.co", "cat": {"code": 12, "title": 3}, "n": 2})
    assert "title" not in v and "url" not in v and "lat" not in v and "lon" not in v
    assert v["note"] == "call [number] or [email]" and v["cat"] == {"code": 12} and v["n"] == 2


def test_publish_flush_recent_and_rejects_unknown(_env):
    bus = _env["bus"]
    assert bus.publish("not_a_kind", "x", {}) is None
    assert bus.publish("message", "backend", {"chars": 12})
    assert bus.flush() == 1
    rows = bus.recent("message")
    assert rows[0]["value"] == {"chars": 12}


def test_pause_and_toggles(_env):
    _env["sensors"]["desktop"] = False
    assert _env["bus"].publish("desktop_window", "desktop", {"window_s": 15}) is None
    _env["sensors"]["pause"] = True
    assert _env["bus"].publish("message", "backend", {}) is None


def test_prune_rolls_up_into_hourly_stats(_env):
    bus = _env["bus"]
    old = (datetime.now(timezone.utc) - timedelta(days=20)).replace(minute=5).isoformat()
    for i in range(3):
        bus.publish("response_latency", "ui", {"ms": 1000 * (i + 1)}, ts=old)
    bus.publish("response_latency", "ui", {"ms": 50})
    res = bus.prune()
    assert res["deleted"] == 3 and res["rolled_up"] == 3
    store = bus._store()
    st = store._rows("SELECT * FROM signal_stats WHERE kind='response_latency'")
    assert st[0]["n"] == 3 and json.loads(st[0]["sums"])["ms"] == 6000
    assert len(bus.recent("response_latency", minutes=60)) == 1


# ---------------------------------------------------------------- focus / idle / transitions
def _feed(bus, start, minutes, cat=None, switches=0, idle=False, locked=False):
    t = start
    for _ in range(int(minutes * 4)):
        v = {"window_s": 15, "cat": ({} if idle or locked else {cat: 15}), "switches": switches,
             "idle_s": 15 if (idle or locked) else 0, "locked": locked}
        bus.publish("desktop_window", "desktop", v, ts=t.isoformat())
        t += timedelta(seconds=15)
    return t


def test_focus_start_end_and_transition(_env):
    bus, timing = _env["bus"], _env["timing"]
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    t = _feed(bus, t0, 10, "code")
    assert "focus_start" not in kinds(bus)                       # 10 min is not enough
    t = _feed(bus, t, 12, "code")
    assert "focus_start" in kinds(bus)
    assert timing.snapshot(now=t)["focus"]["category"] == "code"
    t = _feed(bus, t, 4, "chat", switches=3)                     # switching to chat breaks focus
    k = kinds(bus)
    assert "focus_end" in k and "transition" in k
    tr = [r for r in bus.recent("transition", minutes=10_000)][0]
    assert tr["value"]["reason"] == "focus_ended" and tr["value"]["minutes"] >= 20


def test_browsing_is_not_focus(_env):
    bus = _env["bus"]
    _feed(bus, datetime.now(timezone.utc) - timedelta(hours=1), 30, "browser")
    assert "focus_start" not in kinds(bus)


def test_idle_then_back_after_break(_env):
    bus, timing = _env["bus"], _env["timing"]
    t = _feed(bus, datetime.now(timezone.utc) - timedelta(hours=3), 2, "docs")
    t = _feed(bus, t, 20, idle=True)
    assert "idle_start" in kinds(bus) and timing.snapshot(now=t)["away"]
    t = _feed(bus, t, 1, "docs")
    k = kinds(bus)
    assert "idle_end" in k
    tr = bus.recent("transition", minutes=10_000)[0]
    assert tr["value"]["reason"] == "back_after_break" and tr["value"]["away_minutes"] >= 15


def test_task_completed_is_a_transition(_env):
    _env["bus"].publish("planner_change", "backend", {"action": "complete", "kind": "task"}, subject="t1")
    assert [r["value"]["reason"] for r in _env["bus"].recent("transition")] == ["task_completed"]


# ---------------------------------------------------------------- detectors
def test_dissatisfaction():
    s, why = tm.dissatisfaction("no, that's wrong, I meant the Orbit deck", [])
    assert s >= 0.8 and "correction" in why
    s, _ = tm.dissatisfaction("thanks, perfect", [])
    assert s == 0
    s, why = tm.dissatisfaction("send the Orbit report to Dinesh by email",
                                ["please send the Orbit report to Dinesh by email"])
    assert s >= 0.4 and any("repeats" in w for w in why)


def test_urgency():
    s, _ = tm.urgency("Dinesh <dinesh@orbit.in>", "Need the invoice today?", "", {"Dinesh"})
    assert s >= 0.9
    s, _ = tm.urgency("Naukri <noreply@naukri.com>", "Urgent: 21 new jobs alert", "", {"Dinesh"})
    assert s < 0.6


# ---------------------------------------------------------------- planner emitters
def test_planner_changes_emit_signals(_env, monkeypatch, tmp_path):
    from backend.core import planner_store as ps
    monkeypatch.setattr(sg, "publish", lambda *a, **k: _env["bus"].publish(*a, **k))
    store = ps.PlannerStore.__new__(ps.PlannerStore)
    try:
        ps.PlannerStore.__init__(store, base_dir=tmp_path)            # newer signature
    except TypeError:
        pytest.skip("PlannerStore needs its own fixture")
    it = store.create_item("Revise GATE", kind="task", due_at="2026-11-21")
    store.update_item(it["id"], due_at="2026-11-25")
    store.complete_item(it["id"])
    actions = [r["value"]["action"] for r in reversed(_env["bus"].recent("planner_change"))]
    assert actions == ["create", "postpone", "complete"]


# ---------------------------------------------------------------- API
def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.brain import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_auth_and_kind_rules(_env, monkeypatch, tmp_path):
    import backend.api.brain as api
    monkeypatch.setattr(api, "SENSOR_TOKEN_FILE", tmp_path / "tok")
    monkeypatch.setattr(sg, "publish", lambda *a, **k: _env["bus"].publish(*a, **k))
    c = _client()
    w = {"kind": "desktop_window", "value": {"window_s": 15, "cat": {"code": 15}, "title": "secret.docx"}}
    assert c.post("/api/brain/signals", json=w).status_code == 401
    tok = api.ensure_sensor_token()
    assert c.post("/api/brain/signals", json=w, headers={"X-Brain-Token": tok}).json()["accepted"]
    assert c.post("/api/brain/signals", json={"kind": "urgent_message", "value": {}}).status_code == 403
    assert c.post("/api/brain/signals", json={"kind": "response_latency", "value": {"ms": 900}}).json()["accepted"]
    stored = _env["bus"].recent("desktop_window")[0]["value"]
    assert "title" not in stored and stored["cat"] == {"code": 15}
    # location: off by default, label only when on
    assert c.post("/api/brain/location", json={"lat": 13.03, "lon": 80.21}).status_code == 403
    _env["sensors"]["location"] = True
    monkeypatch.setattr("backend.brain.places.known_places", lambda: [("home", (13.0282, 80.2102))])
    assert c.post("/api/brain/location", json={"lat": 13.0283, "lon": 80.2103}).json()["place"] == "home"
    assert c.post("/api/brain/location", json={"lat": 12.97, "lon": 77.59}).json()["place"] == "travelling"
    rows = _env["bus"].recent("location_place")
    assert all(set(r["value"]) == {"place"} for r in rows)
    status = c.get("/api/brain/sensors").json()
    assert status["collectors"]["desktop"]["online"] and "timing" in status


# ---------------------------------------------------------------- desktop sensor (no Windows calls)
def test_sensor_aggregate_is_privacy_safe():
    from backend.brain import sensor_agent as sa
    seq = iter([("code.exe", "secret_plan.py - VS Code", 0)] * 8 +
               [("chrome.exe", "Google Meet - standup", 0)] * 4 +
               [("lockapp.exe", "", 200)] * 3)
    v = sa.aggregate(15, sa.DEFAULT_CATEGORIES, sample=lambda: next(seq), sleep=lambda s: None)
    assert v["cat"] == {"code": 8, "meeting": 4} and v["switches"] == 1 and v["idle_s"] == 3
    assert "secret" not in json.dumps(v) and "Meet" not in json.dumps(v)


def test_polite_no_is_not_dissatisfaction():
    for t in ("no worries, thanks", "no problem!", "No need, I got it", "nope, no rush"):
        assert tm.dissatisfaction(t, [])[0] < 0.4, t
    assert tm.dissatisfaction("no, that's the wrong file", [])[0] >= 0.5
