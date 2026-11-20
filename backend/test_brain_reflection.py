"""Brain V2 P6: nightly consolidation, episodes, weekly persona, scheduling, digest loops."""
import json
from datetime import datetime, timedelta

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
def _sqlite(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    monkeypatch.setattr(rf, "day_transcript", lambda day, n: ("", []))


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


def _fact(subject_id, pred, obj, status="active", created=None):
    f = kg()._store.add_fact(subject_id=subject_id, predicate=pred, object=obj, confidence=0.9,
                             quote=obj, status=status)
    if created:
        with kg()._store._lock:
            kg()._store._conn.execute("UPDATE facts SET created_at=? WHERE id=?", (created, f["id"]))
    return f


def test_contradictions_keep_newest():
    me = kg().add_node("user", "user", {})
    _fact(me, "lives_in", "Chennai", created="2026-01-01T00:00:00")
    _fact(me, "lives_in", "Pune", created="2026-06-01T00:00:00")
    _fact(me, "likes", "tea")
    _fact(me, "likes", "coffee")                      # multi-valued: both stay
    assert rf.resolve_contradictions(kg()) == 1
    active = {f["object"] for f in kg()._store.list_facts("active")}
    assert active == {"Pune", "tea", "coffee"}


def test_expire_pending():
    me = kg().add_node("user", "user", {})
    _fact(me, "prefers", "tea", status="pending", created="2026-01-01T00:00:00")
    _fact(me, "prefers", "milk", status="pending")
    assert rf.expire_pending(kg(), 14, datetime(2026, 11, 20)) == 1
    assert [f["object"] for f in kg()._store.list_facts("pending")] == ["milk"]


def test_merge_duplicates_on_live_graph():
    a = kg().add_node("person", "Ajay", {})
    b = kg().add_node("person", "person:Ajay", {})
    me = kg().add_node("user", "user", {})
    kg().add_edge(me, a, "friend")
    kg().add_edge(me, b, "friend")
    assert rf.merge_duplicates(kg()) == 1
    people = kg().get_nodes_by_type("person")
    assert len(people) == 1
    # persisted
    import backend.memory.knowledge_graph as kgmod
    kgmod._graph = None
    assert len(kg().get_nodes_by_type("person")) == 1


def test_episode_written_once_and_backfilled(monkeypatch):
    monkeypatch.setattr(rf, "day_transcript", lambda day, n: (f"User: worked on Orbit on {day}", ["c1"]))
    llm = FakeLLM({"summary": "You worked on Orbit.", "decisions": ["use Supabase"],
                   "open_loops": ["send Dinesh the invoice"], "mood": "busy"})
    res = rf.nightly(datetime(2026, 11, 20, 3, 5), llm)
    day_calls = lambda: sum(p.startswith("Summarise the user's day") for p in llm.prompts)  # noqa: E731
    assert res["episodes"] == ["2026-11-17", "2026-11-18", "2026-11-19"] and day_calls() == 3
    res = rf.nightly(datetime(2026, 11, 20, 3, 6), llm)
    assert res["episodes"] == [] and day_calls() == 3           # nothing re-summarised
    assert rf.open_loops(kg()._store) == ["send Dinesh the invoice"]


def test_episode_failure_does_not_block_and_is_retried(monkeypatch):
    monkeypatch.setattr(rf, "day_transcript", lambda day, n: ("User: hi there friend", ["c1"]))
    res = rf.nightly(datetime(2026, 11, 20, 3, 5), FakeLLM("not json"))
    assert "episode_error" in res and "contradictions" in res
    ok = FakeLLM({"summary": "A day.", "decisions": [], "open_loops": [], "mood": ""})
    assert len(rf.nightly(datetime(2026, 11, 21, 3, 5), ok)["episodes"]) == 3


def test_persona_requires_valid_evidence_and_reaches_profile():
    me = kg().add_node("user", "user:Mayday-user", {"name": "Asha"})
    f1 = _fact(me, "goal", "clear the GATE exam")
    f2 = _fact(me, "routine", "gym at 6 am")
    _fact(me, "likes", "filter coffee")
    _fact(me, "phone_number", "9876543210")
    llm = FakeLLM(lambda p: {"lines": [
        {"text": "Asha is preparing for the GATE exam.", "evidence": [f1["id"]]},
        {"text": "Asha secretly loves opera.", "evidence": ["f_made_up"]},          # bad cite -> dropped
        {"text": "Trains early in the morning.", "evidence": [f2["id"]]}]})
    out = rf.build_persona(kg(), llm)
    assert [l["text"] for l in out["lines"]] == ["Asha is preparing for the GATE exam.",
                                                 "Trains early in the morning."]
    assert "9876543210" not in llm.prompts[0]                # private facts never sent
    from backend.core.phf import personal_facts
    assert "In short: Asha is preparing for the GATE exam." in personal_facts()


def test_maybe_reflect_schedule(monkeypatch):
    calls = []
    monkeypatch.setattr(rf, "nightly", lambda now, llm=None: calls.append(("n", now)) or {})
    monkeypatch.setattr(rf, "weekly", lambda now, llm=None: calls.append(("w", now)) or {})
    kg()
    sun = datetime(2026, 11, 22)                     # a Sunday
    assert rf.maybe_reflect(sun.replace(hour=2, minute=59)) == []
    assert rf.maybe_reflect(sun.replace(hour=3, minute=0)) == ["nightly", "weekly"]
    assert rf.maybe_reflect(sun.replace(hour=4)) == []
    assert rf.maybe_reflect((sun + timedelta(days=1)).replace(hour=3, minute=1)) == ["nightly"]


def test_digest_shows_open_loops(monkeypatch):
    kg()._store.add_commitment(text="send Meera the photos", status="open", due="2026-11-21")

    class P:
        def all_items(self):
            return []

        def list_people(self):
            return []
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: P())
    from backend.core.planner_digest import build_digest
    d = build_digest("morning", datetime(2026, 11, 20, 7, 30))
    assert ("From your conversations", ["send Meera the photos (by 2026-11-21)"]) in d["sections"]


def test_config_yaml_parses_and_brain_sections_present():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
    b = cfg["brain"]
    assert {"capture", "recall", "tools", "reflection"} <= set(b)
    import re
    assert re.search(b["reflection"]["skip_pattern"], "Add a task 'ZZTEST buy groceries'")
    assert not re.search(b["reflection"]["skip_pattern"], "I met Kiran today")
