"""Brain V3 P9: working memory, session/decision episodes, roll-ups, habits, decay, typed facts."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import reflection as rf


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, messages, **kw):
        self.prompts.append(messages[0]["content"])
        r = self.reply(messages[0]["content"]) if callable(self.reply) else self.reply
        return {"content": r if isinstance(r, str) else json.dumps(r)}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    from backend.brain import signals as sg, timing as tm, working as wk
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    monkeypatch.setattr(sg, "_cfg", lambda: {"enabled": True, "pause": False, "desktop": True, "ui": True,
                                             "location": True, "backend": True, "retention_days": 14,
                                             "flush_seconds": 3600})
    bus, timing, working = sg.SignalBus(), tm.TimingState(), wk.WorkingContext()
    for mod, name, obj in ((sg, "_BUS", bus), (tm, "_TIMING", timing), (wk, "_WORKING", working)):
        monkeypatch.setattr(mod, name, obj)
    monkeypatch.setattr(tm, "publish", lambda *a, **k: bus.publish(*a, **k))
    bus.subscribe(timing.on_signal)
    bus.subscribe(working.on_signal)
    yield {"bus": bus, "working": working}


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


# ---------------------------------------------------------------- working memory
def test_working_memory_render(_env, monkeypatch):
    bus, working = _env["bus"], _env["working"]
    monkeypatch.setattr(working, "_current_block", lambda: {"id": "p1", "title": "Revise GATE", "until": "23:00"})
    t = datetime.now(timezone.utc) - timedelta(minutes=25)
    for i in range(100):     # 25 min of code
        bus.publish("desktop_window", "desktop", {"window_s": 15, "cat": {"code": 15}, "switches": 0, "idle_s": 0},
                    ts=(t + timedelta(seconds=15 * i)).isoformat())
    bus.publish("urgent_message", "backend", {"score": 0.9}, subject="m1")
    bus.publish("location_place", "location", {"place": "college"})
    line = working.render()
    assert "deep focus (code" in line and "Revise GATE" in line and "at college" in line
    assert "urgent email" in line


def test_now_block_includes_working_memory(_env, monkeypatch):
    from backend.brain import context as ctx
    monkeypatch.setattr(_env["working"], "render", lambda now=None: "Right now the user is away from the laptop.")
    monkeypatch.setattr("backend.core.planner_store.get_planner",
                        lambda: type("P", (), {"list_items": lambda self, **k: []})())
    assert ctx.now_block().startswith("Right now the user is away")


# ---------------------------------------------------------------- episodes
DAY_REPLY = {"summary": "You worked on Orbit and the GATE revision.", "decisions": ["cut scope"],
             "open_loops": [], "mood": "busy",
             "sessions": [{"ref": "c1", "goal": "Finish the Orbit launch checklist", "outcome": "partial",
                           "blockers": "waiting on Dinesh"}],
             "decision_episodes": [{"situation": "Orbit launch deadline slipping", "options": ["cut scope",
                                    "work late"], "chosen": "cut scope", "reason": "keep evenings free",
                                    "outcome": "launched on time", "refs": ["c1"]}]}


def test_session_and_decision_episodes_from_one_call(monkeypatch):
    monkeypatch.setattr(rf, "day_transcript", lambda day, n: ("## [c1] Orbit\nUser: ...", ["conv-9"]))
    llm = FakeLLM(DAY_REPLY)
    rf.write_episode(kg(), llm, "2026-11-19")
    store = kg()._store
    assert len(llm.prompts) == 1 and "decision_episodes" in llm.prompts[0]
    sess = store.list_episodes("session")
    assert sess[0]["conversation_id"] == "conv-9" and sess[0]["outcome"] == "partial"
    dec = store.list_episodes("decision")[0]
    assert json.loads(dec["data"])["chosen"] == "cut scope" and dec["outcome"] == "launched on time"
    assert json.loads(dec["data"])["conversations"] == ["conv-9"]
    # similar situation later -> found, and shown in recall
    assert rf.similar_decisions(store, "the launch deadline is slipping again")[0]["id"] == dec["id"]
    from backend.brain.context import retrieve
    out = retrieve("Orbit deadline slipping, what should I do?")
    assert "Past decision" in out and "cut scope" in out


def test_rollups_week_and_month():
    store = kg()._store
    for d in ("2026-11-09", "2026-11-11", "2026-11-13"):
        store.add_episode(kind="day", day=d, summary=f"day {d}", open_loops=["x"], mood="ok")
    for d in ("2026-10-05", "2026-10-20"):
        store.add_episode(kind="day", day=d, summary=f"day {d}")
    llm = FakeLLM({"summary": "A steady period.", "decisions": [], "open_loops": [], "mood": "ok"})
    done = rf.rollup(kg(), llm, datetime(2026, 11, 20, 3, 0))
    assert done == ["week", "month"]                # week of Nov 9 (3 days) + October (2 days)
    assert rf.rollup(kg(), llm, datetime(2026, 11, 20, 3, 0)) == []   # no repeats
    assert rf.rollup(kg(), llm, datetime(2026, 10, 14, 3, 0)) == []   # week of Oct 5 has 1 day only
    assert store.list_episodes("week")[0]["day"] == "2026-11-09"


# ---------------------------------------------------------------- habits
def test_planner_habit_mined(monkeypatch):
    from backend.brain import habits
    base = datetime(2026, 11, 2, 6, 10)              # Monday
    comps = [{"at": (base + timedelta(days=d)).isoformat()} for d in (0, 1, 2, 7, 8, 9)]
    items = [{"id": "g", "title": "Gym", "completions": comps, "completed_at": None},
             {"id": "x", "title": "Random once", "completions": [], "completed_at": base.isoformat()}]
    monkeypatch.setattr("backend.core.planner_store.get_planner",
                        lambda: type("P", (), {"all_items": lambda self: items})())
    res = habits.mine(kg(), datetime(2026, 11, 12))
    assert res["new"] == 1 and "\"Gym\" around 06:00 on weekdays" in res["habits"][0]
    assert habits.mine(kg(), datetime(2026, 11, 12))["updated"] == 1     # no duplicate
    from backend.core.phf import personal_facts
    assert "Gym" in personal_facts()


def test_focus_habit_needs_two_weeks(_env):
    from backend.brain import habits
    bus = _env["bus"]
    now = datetime.now(timezone.utc)
    for d in (1, 2, 3):                               # one week only
        bus.publish("focus_start", "desktop", {"category": "code"},
                    ts=(now - timedelta(days=d)).replace(hour=15).isoformat())
    assert habits.focus_habits(datetime.now()) == []
    for d in (8, 9):
        bus.publish("focus_start", "desktop", {"category": "code"},
                    ts=(now - timedelta(days=d)).replace(hour=15).isoformat())
    hs = habits.focus_habits(datetime.now())
    assert hs and "deep work (code)" in hs[0]["text"]


# ---------------------------------------------------------------- decay
def test_decay_archives_only_weak_generic_and_can_restore():
    from backend.brain import decay
    k = kg()
    store = k._store
    me = k.add_node("user", "user", {})
    junk = k.add_node("concept", "random note 42", {})
    kept_fact = k.add_node("concept", "peanuts", {})
    k.add_edge(me, kept_fact, "allergic_to", {"fact_id": "f1"})
    person = k.add_node("person", "person:Old Friend", {})
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    for nid in (junk, kept_fact, person):
        store._conn.execute("INSERT OR REPLACE INTO memory_stats(item_id, importance, reinforcements, last_used, "
                            "created_at) VALUES (?, ?, 0, NULL, ?)", (nid, 0.3, old))
    rep = decay.run(k)
    assert rep["archived"] == 1 and k.get_node(junk) is None
    assert k.get_node(kept_fact) and k.get_node(person)
    assert decay.restore(k, junk) and k.get_node(junk)["label"] == "random note 42"


def test_strength_formula():
    from backend.brain.decay import strength
    now = datetime.now(timezone.utc)
    fresh = {"importance": 0.3, "reinforcements": 0, "last_used": now.isoformat()}
    used = {"importance": 0.3, "reinforcements": 8, "last_used": now.isoformat()}
    stale = {"importance": 0.3, "reinforcements": 0, "last_used": (now - timedelta(days=200)).isoformat()}
    assert strength("concept", used, now) > strength("concept", fresh, now) > strength("concept", stale, now)
    assert strength("person", stale, now) == pytest.approx(0.3)          # protected: never decays


# ---------------------------------------------------------------- typed facts from capture
def test_capture_typed_nodes_and_undo():
    from backend.brain import capture as cap

    class L(FakeLLM):
        pass
    text = "I never take meetings before 10 and Sundays are for family"
    llm = L({"ops": [
        {"kind": "fact", "subject": "user", "predicate": "no_meetings_before", "object": "before 10",
         "category": "constraint", "confidence": 0.95, "quote": "I never take meetings before 10"},
        {"kind": "fact", "subject": "user", "predicate": "values", "object": "family time on Sundays",
         "category": "value", "confidence": 0.9, "quote": "Sundays are for family"}]})
    cap.capture_turn(llm, text)
    k = kg()
    assert k.get_node_by_label("constraint:before 10")["type"] == "constraint"
    assert k.get_node_by_label("value:family time on Sundays")["type"] == "value"
    facts = k._store.list_facts("active")
    assert {f["category"] for f in facts} == {"constraint", "value"}
    cap._unmirror_fact(k, next(f for f in facts if f["category"] == "value"))
    v = k.get_node_by_label("value:family time on Sundays")
    assert not k._adj_idx.get(v["id"], {}).get("in")


def test_health_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.brain import router
    app = FastAPI()
    app.include_router(router)
    kg()._store.add_episode(kind="decision", day="2026-11-19", summary="x", data={"chosen": "y"})
    h = TestClient(app).get("/api/brain/health").json()
    assert h["episodes"]["decision"] == 1 and "working" in h and "procedural" in h


def test_decay_never_archives_personal_facts_without_fact_id():
    from backend.brain import decay
    k = kg()
    me = k.add_node("user", "user:Mayday-user", {})
    food = k.add_node("concept", "biryani", {})
    k.add_edge(me, food, "like")                     # legacy remember() edge, no fact_id
    old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
    k._store._conn.execute("INSERT OR REPLACE INTO memory_stats(item_id, importance, reinforcements, last_used, "
                           "created_at) VALUES (?, 0.3, 0, NULL, ?)", (food, old))
    assert decay.run(k)["archived"] == 0 and k.get_node(food)
