"""Brain V2 P3: gate, validator, apply (supersede, pending, commitments, ideas, aliases).

Uses a scripted fake LLM; the graph runs on the SQLite backend in a temp dir (conftest).
"""
import json

import pytest

from backend.brain import capture as cap


class FakeLLM:
    def __init__(self, ops):
        self.ops = ops
        self.calls = 0

    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": json.dumps({"ops": self.ops})}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    planned = []

    class FakePlanner:
        def create_item(self, title, kind="task", **f):
            planned.append((title, f.get("due_at")))
            return {"id": f"p{len(planned)}"}
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: FakePlanner())
    yield planned


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


def test_gate():
    assert cap.gate("my sister Meera's birthday is on March 14")
    assert cap.gate("I'm allergic to peanuts")
    assert not cap.gate("thanks!")
    assert not cap.gate("what's the weather like today?")
    assert not cap.gate("ok")
    assert cap.gate("random thought: a voice-first expense tracker for shops could work")


def test_validator_requires_verbatim_quote_and_supported_names_numbers():
    text = "I'm allergic to peanuts and my sister Meera's birthday is March 14"
    ops = [
        {"kind": "fact", "subject": "user", "predicate": "allergic to", "object": "peanuts",
         "confidence": 0.95, "quote": "I'm allergic to peanuts"},
        {"kind": "fact", "subject": "user", "predicate": "allergic_to", "object": "shellfish",
         "confidence": 0.9, "quote": "I am allergic to shellfish"},          # not in message
        {"kind": "fact", "subject": "Ravi", "predicate": "is", "object": "brother",
         "confidence": 0.9, "quote": "my sister Meera"},                      # subject never mentioned
        {"kind": "fact", "subject": "Meera", "predicate": "birthday", "object": "March 15",
         "confidence": 0.9, "quote": "birthday is March 14"},                 # number not in message
        {"kind": "fact", "subject": "Meera", "predicate": "birthday", "object": "March 14",
         "confidence": 0.65, "quote": "birthday is March 14"},
        {"kind": "fact", "subject": "user", "predicate": "likes", "object": "nuts",
         "confidence": 0.3, "quote": "peanuts"},
    ]
    got = [(o["decision"], o["reason"]) for o in cap.validate(ops, text)]
    assert got == [("auto", ""), ("drop", "quote not found in the message"),
                   ("drop", "subject not mentioned"), ("drop", "number not in the message"),
                   ("ask", "medium confidence"), ("drop", "low confidence")]


def test_capture_writes_facts_mirrors_graph_and_profile():
    llm = FakeLLM([{"kind": "fact", "subject": "user", "predicate": "allergic_to", "object": "peanuts",
                    "confidence": 0.95, "quote": "allergic to peanuts"}])
    res = cap.capture_turn(llm, "btw I'm allergic to peanuts", source_ref="conv:1")
    assert llm.calls == 1 and res["written"][0]["status"] == "active"
    store = kg()._store
    f = store.list_facts("active")[0]
    assert f["quote"] == "allergic to peanuts" and f["source_ref"] == "conv:1"
    from backend.core.phf import personal_facts
    assert "peanuts" in personal_facts()


def test_gated_turn_makes_no_model_call():
    llm = FakeLLM([])
    assert cap.capture_turn(llm, "thanks!")["gated"] and llm.calls == 0


def test_single_valued_fact_supersedes_old_one():
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "lives_in",
                               "object": "Chennai", "confidence": 0.95, "quote": "I live in Chennai"}]),
                     "I live in Chennai now")
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "lives_in",
                               "object": "Bengaluru", "confidence": 0.95, "quote": "moved to Bengaluru"}]),
                     "I moved to Bengaluru last month")
    store = kg()._store
    active = store.list_facts("active")
    old = store.list_facts("superseded")
    assert [f["object"] for f in active] == ["Bengaluru"] and old[0]["object"] == "Chennai"
    assert active[0]["supersedes"] == old[0]["id"]
    from backend.core.phf import personal_facts
    p = personal_facts()
    assert "Bengaluru" in p and "Chennai" not in p


def test_pending_fact_not_in_graph_until_confirmed():
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "prefers",
                               "object": "tea", "confidence": 0.6, "quote": "I think I prefer tea"}]),
                     "hmm I think I prefer tea these days")
    store = kg()._store
    assert store.list_facts("pending")[0]["object"] == "tea"
    assert kg().get_node_by_label("tea") is None


def test_commitment_becomes_planner_task_and_idea_is_stored(_sqlite_backend):
    text = "I'll send Dinesh the invoice on 2026-11-27. random thought: a voice-first expense tracker"
    cap.capture_turn(FakeLLM([
        {"kind": "commitment", "who": "user", "text": "send Dinesh the invoice", "due": "2026-11-27",
         "confidence": 0.9, "quote": "I'll send Dinesh the invoice on 2026-11-27"},
        {"kind": "idea", "text": "voice-first expense tracker", "confidence": 0.85,
         "quote": "a voice-first expense tracker"}]), text)
    assert _sqlite_backend == [("send Dinesh the invoice", "2026-11-27")]
    store = kg()._store
    assert store.list_commitments()[0]["planner_item_id"] == "p1"
    assert store.list_ideas()[0]["text"] == "voice-first expense tracker"


def test_sensitive_fact_stored_private_and_kept_out_of_profile():
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "phone_number",
                               "object": "9876543210", "confidence": 0.95,
                               "quote": "my number is 9876543210"}]),
                     "save this, my number is 9876543210")
    f = kg()._store.list_facts("active")[0]
    assert f["sensitivity"] == "private"
    from backend.core.phf import personal_facts
    assert "9876543210" not in personal_facts()


def test_alias_resolves_subject():
    k = kg()
    nid = k.add_node("person", "person:Lakshmi Iyer", {"name": "Lakshmi Iyer"})
    cap.capture_turn(FakeLLM([{"kind": "alias", "alias": "mom", "canonical": "Lakshmi Iyer",
                               "confidence": 0.9, "quote": "mom (Lakshmi Iyer)"}]),
                     "my mom (Lakshmi Iyer) called")
    assert k._store.resolve_alias("mom") == nid
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "mom", "predicate": "likes", "object": "jasmine",
                               "confidence": 0.9, "quote": "mom likes jasmine"}]), "my mom likes jasmine")
    assert k._store.list_facts("active")[0]["subject_id"] == nid


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.brain import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_learned_confirm_reject_edit():
    c = _client()
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "lives_in",
                               "object": "Chennai", "confidence": 0.95, "quote": "I live in Chennai"}]),
                     "I live in Chennai")
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "lives_in",
                               "object": "Pune", "confidence": 0.95, "quote": "moved to Pune"}]),
                     "I moved to Pune")
    cap.capture_turn(FakeLLM([{"kind": "fact", "subject": "user", "predicate": "prefers",
                               "object": "tea", "confidence": 0.6, "quote": "maybe tea"}]), "maybe tea for me")
    data = c.get("/api/brain/learned").json()
    assert data["counts"] == {"active": 1, "pending": 1}
    pune = next(i for i in data["items"] if i["object"] == "Pune")
    assert pune["text"] == "you lives in Pune" and pune["quote"] == "moved to Pune"
    # "wrong" on Pune restores Chennai
    assert c.post(f"/api/brain/learned/fact/{pune['id']}/reject").json()["ok"]
    store = kg()._store
    assert [f["object"] for f in store.list_facts("active")] == ["Chennai"]
    assert kg().get_node_by_label("Chennai") and not any(
        e["relation"] == "lives_in" and kg().get_node(e["target"])["label"] == "Pune" for e in kg()._edges)
    # confirm the pending one -> active, in the graph
    tea = next(i for i in c.get("/api/brain/learned?status=pending").json()["items"])
    assert c.post(f"/api/brain/learned/fact/{tea['id']}/confirm").json()["ok"]
    assert "tea" in [f["object"] for f in store.list_facts("active")]
    # edit Chennai -> Coimbatore
    chennai = next(f for f in store.list_facts("active") if f["object"] == "Chennai")
    assert c.put(f"/api/brain/learned/fact/{chennai['id']}", json={"object": "Coimbatore"}).json()["ok"]
    objs = {f["object"] for f in store.list_facts("active")}
    assert "Coimbatore" in objs and "Chennai" not in objs


def test_goal_is_not_a_commitment_and_flags_are_dropped():
    text = "I want to clear the GATE exam in February and I take long walks when stressed"
    ops = cap.validate([
        {"kind": "commitment", "who": "user", "text": "clear the GATE exam", "confidence": 0.9,
         "quote": "I want to clear the GATE exam"},
        {"kind": "fact", "subject": "user", "predicate": "takes_walks_when_stressed", "object": "true",
         "confidence": 0.9, "quote": "I take long walks when stressed"}], text)
    assert ops[0]["kind"] == "fact" and ops[0]["predicate"] == "goal" and ops[0]["decision"] == "auto"
    assert ops[1]["decision"] == "drop"
