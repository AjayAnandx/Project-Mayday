"""Brain V3 P10: meta-cognition — explainability, ledger, feedback parsing, lessons (Reflexion/ExpeL)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import feedback as fb, ledger, lessons as ls


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, **kw):
        self.calls += 1
        r = self.reply(messages[0]["content"]) if callable(self.reply) else self.reply
        return {"content": r if isinstance(r, str) else json.dumps(r)}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    monkeypatch.setattr(ls, "_QUEUE", ls.LessonQueue())
    monkeypatch.setattr(ls, "_cfg", lambda: {"enabled": True, "max_per_day": 6, "min_dissatisfaction": 0.5,
                                             "inject": 3})


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


# ---------------------------------------------------------------- explainability
def test_validate_why():
    f = kg()._store.add_fact(subject_id=None, predicate="deadline", object="Thursday", confidence=0.9, quote="x")
    ok, _ = ledger.validate_why("Because your Orbit pitch is on Thursday and the deck hasn't changed.", [f["id"]])
    assert ok
    assert ledger.validate_why("", [f["id"]]) == (False, "missing why")
    assert ledger.validate_why("This might be helpful for you.", [f["id"]])[1] == "why is generic"
    assert ledger.validate_why("Because things are happening.", [f["id"]])[1] == "why names nothing specific"
    assert ledger.validate_why("Your pitch is Thursday. Also the deck.", [f["id"]])[1] == "why must be one sentence"
    assert ledger.validate_why("Your pitch is on Thursday.", [])[1] == "no evidence"
    assert "evidence not found" in ledger.validate_why("Your pitch is on Thursday.", ["f_nope"])[1]


def test_unexplained_candidate_is_rejected_and_logged():
    row = ledger.log_candidate(type="prep", text="Prep the deck", why="It might help.", evidence=["f_x"],
                               source="test", decision="suggest")
    assert row["decision"] == "rejected_unexplained"
    stored = kg()._store._rows("SELECT * FROM candidates")[0]
    assert stored["decision"] == "rejected_unexplained" and stored["reason"]


def test_explain_returns_stored_reason():
    f = kg()._store.add_fact(subject_id=None, predicate="x", object="y", confidence=0.9, quote="q")
    c = ledger.log_candidate(type="nudge", text="Nudge Dinesh", why="Dinesh's feedback was due on Friday.",
                             evidence=[f["id"]], source="test", decision="suggest")
    s = ledger.record_suggestion(type="nudge", mode="nudge", text="Nudge Dinesh?", why=c["why"],
                                 candidate_id=c["id"])
    assert ledger.explain(s["id"]) == {"id": s["id"], "why": c["why"], "evidence": [f["id"]]}


# ---------------------------------------------------------------- feedback parsing
def test_outcomes_update_type_stats_and_threshold():
    for outcome in ("accepted", "accepted", "dismissed"):
        s = ledger.record_suggestion(type="nudge", mode="nudge", text="t", why="w")
        ledger.resolve_suggestion(s["id"], outcome)
    st = fb.type_stat("nudge")
    assert st["accepts"] == 3.0                     # both resolved fast -> 1.5 each
    assert st["dismisses"] == 1.0
    a, b = fb.acceptance_prior("nudge")
    assert a > b
    s = ledger.record_suggestion(type="digest_idea", mode="nudge", text="t", why="w")
    ledger.resolve_suggestion(s["id"], "less")
    assert fb.threshold_offset("digest_idea") == pytest.approx(0.15)
    s = ledger.record_suggestion(type="digest_idea", mode="nudge", text="t", why="w")
    ledger.resolve_suggestion(s["id"], "later")
    assert fb.threshold_offset("digest_idea") == pytest.approx(0.15)     # timing only


def test_expired_suggestion_counts_as_ignored():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    s = ledger.record_suggestion(type="brief", mode="nudge", text="t", why="w", expires_at=past)
    assert ledger.expire_suggestions() == 1
    assert kg()._store._rows("SELECT outcome FROM suggestions WHERE id=?", (s["id"],))[0]["outcome"] == "ignored"
    assert fb.type_stat("brief")["ignores"] == 1


def test_undo_demotes_type():
    a = ledger.record_action(mode="autonomous", type="move_buffer", payload={}, why="w", evidence=[],
                             undo_payload={"x": 1})
    ledger.mark_action_undone(a["id"])
    assert fb.threshold_offset("move_buffer") == pytest.approx(0.2)
    assert fb.acceptance_prior("move_buffer")[1] == 3


def test_learned_feed_signals_and_planner_calibration():
    p = fb.FeedbackParser()
    p.on_signal({"kind": "suggestion_feedback", "value": {"surface": "learned", "action": "reject", "kind": "fact"}})
    assert fb.type_stat("capture:fact")["dismisses"] == 1
    for i in range(3):
        p.on_signal({"kind": "planner_change", "ts": f"2026-11-2{i}T10:00:00",
                     "value": {"action": "postpone", "source": "llm", "fields": ["due_at"]}})
    prefs = fb.active_prefs()
    assert prefs and "due date" in prefs[0]["preference"]
    # edits on items the USER created don't count
    p.on_signal({"kind": "planner_change", "value": {"action": "update", "source": "manual", "fields": ["title"]}})
    assert not kg()._store._rows("SELECT * FROM prefs_calibrated WHERE scope='planner:title'")


# ---------------------------------------------------------------- lessons
LESSON = {"trigger": "when the user says 'send it to him'", "lesson": "Confirm who 'him' is before drafting an email.",
          "scope": "tool:gmail_send", "confidence": 0.9}


def test_dissatisfaction_becomes_candidate_then_active_on_repeat():
    q = ls.get_queue()
    llm = FakeLLM(LESSON)
    q.observe_turn("no, I meant Dinesh not Kiran", "c1", ["email him the report"], "Drafted to Kiran.", 0.85,
                   ["correction"])
    q.observe_turn("thanks", "c1", [], "", 0.0, [])                 # not a mistake: nothing queued
    out = q.process(llm)
    assert len(out) == 1 and out[0]["status"] == "candidate" and llm.calls == 1
    assert ls.relevant("email him the report", ["gmail_send"]) == []   # candidates are not injected
    q.observe_turn("wrong person again", "c2", ["send it to him"], "Sent to Kiran.", 0.9, ["says it's wrong"])
    out = q.process(FakeLLM({**LESSON, "lesson": "Confirm the recipient when the user says 'him'."}))
    assert out[0].get("merged")
    row = kg()._store._rows("SELECT * FROM lessons")[0]
    assert row["status"] == "active" and row["votes"] == 2
    block = ls.prompt_block("email him the report", ["gmail_send"], conv_id="c3")
    assert "Confirm who 'him' is" in block


def test_injected_lesson_downvoted_when_mistake_repeats():
    les = ls.merge({"trigger": "when booking a meeting", "lesson": "Ask for the timezone.", "scope": "general"})
    ls.vote(les["id"], 1)                                            # -> active, votes 2
    assert ls.prompt_block("booking a meeting with Kiran", [], conv_id="c9")
    ls.get_queue().observe_turn("no, wrong time zone again", "c9", ["book a meeting"], "Booked 10am", 0.9, ["x"])
    assert kg()._store._rows("SELECT votes FROM lessons WHERE id=?", (les["id"],))[0]["votes"] == 1


def test_tool_error_lesson_on_second_occurrence():
    q = ls.get_queue()
    err = [{"tool": "maps_route", "error": "REQUEST_DENIED: billing 123", "args_keys": ["destination"]}]
    q.observe_tool_errors("route to college", err, "c1")
    assert q.pending() == 0
    q.observe_tool_errors("route to office", [{**err[0], "error": "REQUEST_DENIED: billing 456"}], "c1")
    assert q.pending() == 1
    out = q.process(FakeLLM({"trigger": "when maps returns REQUEST_DENIED", "lesson": "Tell the user Maps billing "
                             "is off instead of retrying.", "scope": "general", "confidence": 0.8}))
    assert out[0]["scope"] == "tool:maps_route"


def test_none_and_low_confidence_lessons_are_dropped_and_cap_holds(monkeypatch):
    q = ls.get_queue()
    q.observe_turn("no!", "c1", ["x"], "y", 0.9, ["no"])
    assert q.process(FakeLLM({"none": True})) == []
    monkeypatch.setattr(ls, "_cfg", lambda: {"enabled": True, "max_per_day": 0, "min_dissatisfaction": 0.5,
                                             "inject": 3})
    q.observe_turn("wrong", "c1", ["x"], "y", 0.9, ["no"])
    llm = FakeLLM(LESSON)
    assert q.process(llm) == [] and llm.calls == 0


def test_maintain_retires_stale():
    les = ls.merge({"trigger": "when x happens", "lesson": "do y", "scope": "general"})
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    kg()._store._conn.execute("UPDATE lessons SET created_at=? WHERE id=?", (old, les["id"]))
    assert ls.maintain()["retired_candidates"] == 1


def test_api_learned_lists_lessons_and_confirm_activates():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.brain import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    les = ls.merge({"trigger": "when summarising PDFs", "lesson": "Quote page numbers.", "scope": "general"})
    items = c.get("/api/brain/learned?status=pending").json()["items"]
    assert any(i["kind"] == "lesson" and i["id"] == les["id"] for i in items)
    assert c.post(f"/api/brain/learned/lesson/{les['id']}/confirm").json()["ok"]
    assert kg()._store._rows("SELECT status FROM lessons WHERE id=?", (les["id"],))[0]["status"] == "active"
    s = ledger.record_suggestion(type="nudge", mode="nudge", text="t", why="Dinesh owes feedback since Friday.")
    assert c.post(f"/api/brain/suggestions/{s['id']}/accepted").json()["ok"]
    assert c.post(f"/api/brain/suggestions/{s['id']}/bogus").status_code == 400
    assert c.get(f"/api/brain/why/{s['id']}").json()["why"].startswith("Dinesh")
    assert "types" in c.get("/api/brain/learning").json()
