"""Brain V3 P12: 72-hour friction simulation (seeded scenarios) and prep packs (citations enforced)."""
import json
from datetime import datetime, timedelta

import pytest

from backend.brain import friction as fr

NOW = datetime(2026, 11, 20, 9, 0)          # Friday 09:00
CFG = {"horizon_hours": 72, "focus_factor": 0.6, "default_task_min": 45, "important_priority": 2,
       "quiet_hours": "22:30-07:00"}


def ev(id, title, start, hours=1.0):
    s = datetime.fromisoformat(start)
    return {"id": id, "title": title, "start": s, "end": s + timedelta(hours=hours)}


def task(id, title, due, priority=4, est=None, block=None):
    d = datetime.fromisoformat(due)
    return {"id": id, "title": title, "due": d, "due_raw": due, "priority": priority, "estimate_min": est,
            "block": block}


def kinds(found):
    return sorted(f["kind"] for f in found)


def test_conflict_detected_with_severity():
    found = fr.simulate([ev("a", "Standup", "2026-11-20T10:00"), ev("b", "Dentist", "2026-11-20T10:30"),
                         ev("c", "Lunch", "2026-11-20T13:00")], [], [], NOW, CFG)
    c = [f for f in found if f["kind"] == "conflict"]
    assert len(c) == 1 and c[0]["severity"] == "high" and "10:30" in c[0]["title"]


def test_back_to_back_is_not_a_conflict():
    found = fr.simulate([ev("a", "A", "2026-11-20T10:00"), ev("b", "B", "2026-11-20T11:00")], [], [], NOW, CFG)
    assert "conflict" not in kinds(found)


def test_overload_when_demand_exceeds_capacity():
    events = [ev(f"m{i}", f"Meeting {i}", f"2026-11-21T{8 + 2 * i:02d}:00", 1.5) for i in range(7)]
    tasks = [task(f"t{i}", f"Report part {i}", "2026-11-21", est=120) for i in range(3)]
    o = [f for f in fr.simulate(events, tasks, [], NOW, CFG) if f["kind"] == "overload"]
    assert o and o[0]["day"] == "2026-11-21" and o[0]["detail"]["demand_min"] == 360


def test_light_day_is_not_overloaded():
    assert "overload" not in kinds(fr.simulate([], [task("t", "Small", "2026-11-21", est=30)], [], NOW, CFG))


def test_unscheduled_important_task_gets_a_free_slot_before_deadline():
    events = [ev("e1", "Class", "2026-11-20T09:00", 3)]
    t = task("t1", "Submit lab record", "2026-11-20T18:00", priority=1, est=90)
    u = [f for f in fr.simulate(events, [t], [], NOW, CFG) if f["kind"] == "unscheduled"][0]
    start, end = u["detail"]["slot"]
    assert start == "2026-11-20T12:00" and end == "2026-11-20T13:30"     # after class, before the deadline
    low = task("t2", "Someday", "2026-11-20T18:00", priority=4)
    assert "unscheduled" not in kinds(fr.simulate([], [low], [], NOW, CFG))
    blocked = task("t3", "Already planned", "2026-11-20T18:00", priority=1,
                   block=(datetime(2026, 11, 20, 14), datetime(2026, 11, 20, 15)))
    assert "unscheduled" not in kinds(fr.simulate([], [blocked], [], NOW, CFG))


def test_missing_prep_unless_a_task_mentions_it():
    exam = ev("x", "Theory Exam", "2026-11-22T10:00", 3)
    f = [x for x in fr.simulate([exam], [], [], NOW, CFG) if x["kind"] == "missing_prep"]
    assert f and f[0]["detail"]["days_left"] == 2
    prep = task("p", "Revise theory units 1-3", "2026-11-21")
    assert "missing_prep" not in kinds(fr.simulate([exam], [prep], [], NOW, CFG))
    assert "missing_prep" not in kinds(fr.simulate([ev("y", "Lunch with Kiran", "2026-11-21T13:00")],
                                                   [], [], NOW, CFG))


def test_waiting_risk():
    w = {"id": "w", "title": "feedback on the deck", "due": datetime(2026, 11, 21), "person": "Dinesh"}
    f = [x for x in fr.simulate([], [], [w], NOW, CFG) if x["kind"] == "waiting_risk"]
    assert f and "Dinesh still owes you" in f[0]["title"]


def test_candidates_shape_and_urgency():
    c = fr.to_candidate({"kind": "conflict", "key": "k", "title": "A and B overlap today at 10:30",
                         "evidence": ["p:a"], "hours_away": 2, "detail": {}}, NOW)
    assert c["urgency"] == "urgent" and c["why"].endswith(".")
    u = fr.to_candidate({"kind": "unscheduled", "key": "u", "title": "\"Lab\" is due today and has no time",
                         "evidence": ["p:t"], "detail": {"task": "t", "slot": ["2026-11-20T12:00",
                                                                                 "2026-11-20T13:30"]}}, NOW)
    assert u["action"]["kind"] == "planner_schedule_task" and "12:00–13:30 today" in u["text"]
    m = fr.to_candidate({"kind": "missing_prep", "key": "m", "title": "\"Final Exam\" is Sunday at 10:00 and …",
                         "evidence": ["p:x"], "detail": {"event": "x", "starts": "2026-11-22T10:00",
                                                         "days_left": 2}}, NOW)
    assert m["mode"] == "framing" and m["options"][0]["action"]["payload"]["title"] == "Prepare for Final Exam"


# ---------------------------------------------------------------- prep packs
class FakeLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, messages, **kw):
        self.prompts.append(messages[0]["content"])
        return {"content": json.dumps(self.reply)}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture
def sqlite_env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    from backend.brain import prep
    monkeypatch.setattr(prep, "_cfg", lambda: {"enabled": True, "lead_hours": 18, "show_before_min": 30,
                                               "max_per_day": 3, "use_gmail": False})
    return prep


def test_prep_build_keeps_only_cited_lines(sqlite_env):
    prep = sqlite_env
    sources = [{"n": 1, "kind": "planner", "ref": "p:x", "text": "event: Orbit pitch"},
               {"n": 2, "kind": "memory", "ref": "n1", "text": "Dinesh is the client contact"}]
    llm = FakeLLM({"briefing": ["Pitch to Orbit's client [1][2]", "Uncited guess", "Bad cite [7]"],
                   "changed": [], "raise": ["Ask Dinesh for the feedback [2]"],
                   "action_items": ["Finalize the deck [1]"]})
    pack = prep.build({"kind": "event", "title": "Orbit pitch", "starts_at": "2026-11-21T10:00"}, llm, sources)
    assert pack["briefing"] == ["Pitch to Orbit's client [1][2]"]
    assert pack["raise"] == ["Ask Dinesh for the feedback [2]"] and pack["action_items"]
    assert prep.build({"kind": "event", "title": "x", "starts_at": "y"}, llm, sources[:1]) is None   # too little


def test_prep_run_end_to_end(sqlite_env, monkeypatch):
    prep = sqlite_env
    from backend.memory.memory_tools import remember
    remember("Dinesh", "is", "client contact at Orbit Logistics", node_type="person")
    from backend.memory.knowledge_graph import get_graph
    get_graph()._store.add_commitment(text="send Dinesh the revised deck", quote="I'll send Dinesh the deck")
    target = {"key": "e1:2026-11-21T10:00", "id": "e1", "kind": "event", "title": "Pitch with Dinesh",
              "notes": "", "starts_at": "2026-11-21T10:00", "people": [{"name": "Dinesh"}]}
    monkeypatch.setattr(prep, "targets", lambda now: [target])
    submitted = []
    monkeypatch.setattr("backend.brain.proactive.submit", lambda c, *a: submitted.append(c) or {"decision": "prepare"})
    llm = FakeLLM({"briefing": ["Dinesh is Orbit's client contact [2]"], "changed": [],
                   "raise": ["You promised the revised deck [3]"], "action_items": ["Send the deck [3]"]})
    res = prep.run(datetime(2026, 11, 20, 18, 0), llm)
    assert res and res[0]["decision"] == "prepare" and submitted[0]["mode"] == "silent_prep"
    src_text = llm.prompts[0]
    assert "client contact at Orbit Logistics" in src_text and "revised deck" in src_text
    prep.run(datetime(2026, 11, 20, 18, 5), llm)
    assert len(llm.prompts) == 1                                                      # built once per target
    packs = prep.list_packs()
    assert packs[0]["title"] == "Pitch with Dinesh" and packs[0]["opened_at"] is None
    # 20 min before the event, an unopened pack is announced (urgent: inside show_before_min)
    submitted.clear()
    out = prep.announce(datetime(2026, 11, 21, 9, 40))
    assert len(out) == 1 and submitted[0]["type"] == "prep_ready" and submitted[0]["urgency"] == "urgent"
    assert prep.announce(datetime(2026, 11, 21, 9, 45)) == []                           # announced once
    # opening marks it used (the "opened before the event" metric)
    assert prep.open_pack(packs[0]["id"])["id"] == packs[0]["id"]
    assert prep.list_packs()[0]["opened_at"]
