"""Brain V3 P11: the four gates, graduated agency, delivery, undo, earned autonomy, generators."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import proactive as pr


class FakePlanner:
    def __init__(self):
        self.items = {}

    def create_item(self, title, kind="task", **f):
        iid = f"p{len(self.items) + 1}"
        self.items[iid] = {"id": iid, "title": title, "kind": kind, **f}
        return self.items[iid]

    def delete_item(self, iid):
        return self.items.pop(iid, None) is not None

    def get_item(self, iid):
        return self.items.get(iid)

    def schedule_item(self, iid, start, end=None):
        self.items[iid]["scheduled_block"] = {"start": start, "end": end} if start else None
        return self.items[iid]


class FakeScheduler:
    def __init__(self):
        self.sent = []

    def fire_notification(self, title, body, category="", action_page="", extra=None):
        self.sent.append({"title": title, "body": body, "category": category, **(extra or {})})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    from backend.brain import timing as tm
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    planner, sched = FakePlanner(), FakeScheduler()
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: planner)
    monkeypatch.setattr("backend.core.scheduler.get_scheduler", lambda: sched)
    timing = tm.TimingState()
    monkeypatch.setattr(tm, "_TIMING", timing)
    settings = {"enabled": True, "dial": "balanced", "quiet_hours": "22:30-07:00", "urgent_cap": 3,
                "cooldown_min": 30, "preauthorized": ["planner_move_own_block"], "earned_autonomy_after": 5,
                "min_sample": 0.0}
    monkeypatch.setattr(pr, "_cfg", lambda: dict(settings))
    yield {"planner": planner, "sched": sched, "timing": timing, "settings": settings}


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


NOON = datetime(2026, 11, 20, 12, 0)


def cand(**kw):
    f = kg()._store.add_fact(subject_id=None, predicate="deadline", object="Friday", confidence=0.9, quote="by Friday")
    c = {"type": "commitment_due", "text": "Add 'send invoice' to your Planner?",
         "why": "You told me \"I'll send Dinesh the invoice by Friday\" and it is due Friday.",
         "evidence": [f["id"]], "source": "test", "value": 0.7, "urgency": "timely", "confidence": 0.85,
         "mode": "nudge", "action": {"kind": "planner_create_task", "payload": {"title": "send invoice"}}}
    c.update(kw)
    return c


# ---------------------------------------------------------------- gates
def test_deliver_and_accept_runs_action(env):
    out = pr.submit(cand(), NOON)
    assert out["decision"] == "deliver" and env["sched"].sent[0]["suggestion_id"] == out["suggestion"]["id"]
    from backend.brain.ledger import resolve_suggestion
    resolve_suggestion(out["suggestion"]["id"], "accepted")
    res = pr.execute_accepted(out["suggestion"]["id"])
    assert res["done"] and env["planner"].items["p1"]["title"] == "send invoice"
    assert pr.undo(res["action"]["id"]) and env["planner"].items == {}


def test_g1_low_value_and_unexplained():
    assert pr.submit(cand(value=0.1, text="low"), NOON)["decision"] == "thought"
    assert pr.submit(cand(why="This might be helpful.", text="vague"), NOON)["decision"] == "rejected_unexplained"


def test_learned_threshold_raises_bar(env):
    from backend.brain.feedback import update_type
    for _ in range(3):
        update_type("commitment_due", "less")                 # +0.45
    assert pr.submit(cand(value=0.7), NOON)["decision"] == "thought"


def test_g2_focus_defers_and_transition_delivers(env):
    env["timing"].focus = {"category": "code", "since": datetime.now(timezone.utc) - timedelta(minutes=40)}
    out = pr.submit(cand(), NOON)
    assert out["decision"] == "defer" and env["sched"].sent == []
    env["timing"].focus = None
    delivered = pr.on_transition()
    assert len(delivered) == 1 and env["sched"].sent


def test_urgent_bypasses_focus_and_budget_but_has_cap(env):
    env["timing"].focus = {"category": "code", "since": datetime.now(timezone.utc)}
    for i in range(3):
        assert pr.submit(cand(urgency="urgent", text=f"Leave now {i}"), NOON)["decision"] == "deliver"
    assert pr.submit(cand(urgency="urgent", text="Leave now 4"), NOON)["decision"] == "digest"


def test_g4_budget_quiet_hours_cooldown(env):
    for i in range(3):
        assert pr.submit(cand(text=f"t{i}"), NOON)["decision"] == "deliver"
    assert pr.submit(cand(text="t4"), NOON)["decision"] == "digest"           # budget 3 used
    assert pr.submit(cand(text="night"), datetime(2026, 11, 20, 23, 30))["decision"] == "digest"
    pr.set_dial("eager")
    from backend.brain.ledger import resolve_suggestion
    sid = kg()._store._rows("SELECT id FROM suggestions LIMIT 1")[0]["id"]
    resolve_suggestion(sid, "dismissed")
    assert pr.submit(cand(text="after dismiss"), NOON)["decision"] == "defer"   # cool-down


def test_dedupe_and_dial_off(env):
    pr.submit(cand(dedupe="c1"), NOON)
    assert pr.submit(cand(dedupe="c1"), NOON)["decision"] == "duplicate"
    pr.set_dial("off")
    assert pr.submit(cand(dedupe="c2"), NOON)["decision"] == "disabled"


def test_digest_items_collects_batched(env):
    env["settings"]["min_sample"] = 1.01                                   # receptivity gate always fails
    pr.submit(cand(text="for the morning", dedupe="m1"), NOON)
    items = pr.digest_items()
    assert items and items[0]["text"] == "for the morning"
    assert pr.digest_items() == []                                         # sent once


# ---------------------------------------------------------------- G3 / agency
def test_autonomous_requires_preauthorization(env):
    env["planner"].create_item("Buffer", kind="task")
    move = {"kind": "planner_move_own_block", "payload": {"item_id": "p1", "start": "2026-11-21T18:00",
                                                            "end": "2026-11-21T18:30"}}
    out = pr.submit(cand(mode="autonomous", confidence=0.9, action=move, text="Moved your buffer"), NOON)
    assert out["decision"] == "autonomous" and out["action"]["mode"] == "autonomous"
    assert env["planner"].items["p1"]["scheduled_block"]["start"] == "2026-11-21T18:00"
    assert env["sched"].sent[-1]["mode"] == "autonomous" and env["sched"].sent[-1]["action_id"]
    # not pre-authorised -> downgraded to a nudge
    out = pr.submit(cand(mode="autonomous", confidence=0.95, text="Create task"), NOON)
    assert out["decision"] == "deliver" and out["mode"] == "nudge"


def test_low_confidence_becomes_framing_or_thought():
    opts = [{"label": "Move the gym", "action": None}, {"label": "Keep it", "action": None}]
    assert pr.submit(cand(confidence=0.4, options=opts, text="Thursday overloaded"), NOON)["mode"] == "framing"
    assert pr.submit(cand(confidence=0.4, text="Unsure"), NOON)["decision"] == "thought"


def test_silent_prep_and_never_autonomous_kinds(env):
    out = pr.submit(cand(mode="silent_prep", action={"kind": "prepare_note", "payload": {"title": "Prep pack"}},
                         text="Prepared"), NOON)
    assert out["decision"] == "prepare" and env["sched"].sent == []
    with pytest.raises(ValueError):
        pr.set_preauthorized("gmail_send", True)


def test_earned_autonomy_offer_after_five_clean_accepts(env):
    from backend.brain.ledger import resolve_suggestion
    pr.set_dial("eager")
    env["settings"]["cooldown_min"] = 0
    res = None
    for i in range(5):
        out = pr.submit(cand(text=f"task {i}", dedupe=f"d{i}"), NOON)
        sid = out["suggestion"]["id"]
        resolve_suggestion(sid, "accepted")
        res = pr.execute_accepted(sid)
    assert res["offer_autonomy"] == "planner_create_task"
    pr.set_preauthorized("planner_create_task", True)
    assert "planner_create_task" in pr.preauthorized()


def test_framing_option_runs_its_action(env):
    opts = [{"label": "Add to Planner", "action": {"kind": "planner_create_task", "payload": {"title": "revise"}}},
            {"label": "Skip", "action": None}]
    out = pr.submit(cand(confidence=0.5, options=opts, text="Revision plan?"), NOON)
    from backend.brain.ledger import resolve_suggestion
    resolve_suggestion(out["suggestion"]["id"], "accepted")
    assert pr.execute_accepted(out["suggestion"]["id"], option_index=0)["done"]
    assert env["planner"].items["p1"]["title"] == "revise"


# ---------------------------------------------------------------- generators
def test_commitment_generator(env):
    store = kg()._store
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    store.add_commitment(text="send Meera the photos", due=tomorrow, quote="I'll send Meera the photos tomorrow")
    store.add_commitment(text="far away", due="2030-01-01", quote="x")
    from backend.brain import generators as g
    cands = g.commitments_due(datetime.now())
    assert len(cands) == 1 and "Meera" in cands[0]["text"]
    res = g.run_all(force=True)
    assert any(r["type"] == "commitment_due" and r["decision"] in ("deliver", "defer", "digest") for r in res)


# ---------------------------------------------------------------- API
def test_api_flow(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.brain import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    out = pr.submit(cand(), NOON)
    r = c.post(f"/api/brain/suggestions/{out['suggestion']['id']}/accepted").json()
    assert r["result"]["done"] and env["planner"].items
    aid = r["result"]["action"]["id"]
    assert any(a["id"] == aid for a in c.get("/api/brain/actions").json()["actions"])
    assert c.post(f"/api/brain/actions/{aid}/undo").json()["ok"] and not env["planner"].items
    assert c.post(f"/api/brain/actions/{aid}/undo").status_code == 409
    assert c.put("/api/brain/proactive", json={"dial": "quiet"}).json()["budget"] == 1
    assert c.put("/api/brain/proactive", json={"dial": "loud"}).status_code == 400
    assert c.post("/api/brain/proactive/preauthorize", json={"kind": "gmail_send", "allowed": True}).status_code == 400
    th = c.get("/api/brain/thoughts").json()["thoughts"]
    assert th and th[0]["gates"]["G1"]["why_ok"]
