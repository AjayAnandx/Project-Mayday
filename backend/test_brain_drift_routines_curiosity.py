"""Brain V3 P14: drift detection (synthetic rhythm change), routines (AWM + verification), curiosity."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import curiosity as cu
from backend.brain import drift as dr
from backend.brain import routines as ro


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, messages, **kw):
        self.prompts.append(messages[0]["content"])
        r = self.reply(messages[0]["content"]) if callable(self.reply) else self.reply
        return {"content": json.dumps(r)}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture(autouse=True)
def env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


def _signal(kind, ts):
    kg()._store._conn.execute("INSERT INTO signals(ts, kind, source, value) VALUES (?, ?, 'backend', '{}')",
                              (ts.isoformat(), kind))


# ---------------------------------------------------------------- drift
def test_js_distance():
    assert dr.js_distance(Counter({22: 10}), Counter({22: 10})) == pytest.approx(0)
    assert dr.js_distance(Counter({22: 10}), Counter({9: 10})) == pytest.approx(1.0)


def test_synthetic_rhythm_change_is_caught_and_habit_updated():
    now = datetime.now(timezone.utc)
    for d in range(29, 56):                       # 4–8 weeks ago: nights (22:00 local)
        t = (now - timedelta(days=d)).astimezone().replace(hour=22, minute=0).astimezone(timezone.utc)
        _signal("message", t)
    for d in range(1, 28):                        # last 4 weeks: mornings (09:00 local)
        t = (now - timedelta(days=d)).astimezone().replace(hour=9, minute=0).astimezone(timezone.utc)
        _signal("message", t)
    d = dr.rhythm_drift(kg()._store, "message", now)
    assert d and d["peak_now"] == 9 and d["peak_before"] == 22 and d["distance"] > 0.5
    k = kg()
    k.add_node("habit", "habit:active:hours", {"text": "talks to Mayday most around 22:00"})
    res = dr.run(now)
    node = k.get_node_by_label("habit:active:hours")
    assert "around 09:00 (was 22:00)" in node["properties"]["text"]
    assert node["properties"]["previous_text"] == "talks to Mayday most around 22:00"
    assert res["rhythm"]
    noted = k._store._rows("SELECT * FROM candidates WHERE type='drift_rhythm'")
    assert noted and noted[0]["decision"] == "noted"


def test_no_drift_when_stable_or_too_little_data():
    now = datetime.now(timezone.utc)
    for d in range(1, 56):
        _signal("message", (now - timedelta(days=d)).astimezone().replace(hour=21).astimezone(timezone.utc))
    assert dr.rhythm_drift(kg()._store, "message", now) is None
    assert dr.rhythm_drift(kg()._store, "focus_start", now) is None          # no data


def test_stale_goal_question_and_retire_undo(monkeypatch):
    store = kg()._store
    from backend.brain.capture import _mirror_fact
    me = kg().add_node("user", "user", {})
    f = store.add_fact(subject_id=me, predicate="goal", object="learn piano", confidence=0.9,
                       quote="I want to learn piano", category="goal")
    _mirror_fact(kg(), me, "goal", "learn piano", f["id"], "goal")
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    store._conn.execute("UPDATE facts SET created_at=? WHERE id=?", (old, f["id"]))
    cands = dr.stale_beliefs(store, kg(), datetime.now())
    assert len(cands) == 1 and "learn piano" in cands[0]["text"] and cands[0]["mode"] == "framing"
    from backend.brain.proactive import execute, undo
    a = execute("fact_retire", {"fact_id": f["id"]}, mode="approved", why="w", evidence=[f["id"]])
    assert store.get_fact(f["id"])["status"] == "retired"
    assert not kg()._adj_idx.get(kg().get_node_by_label("goal:learn piano")["id"], {}).get("in")
    assert undo(a["id"]) and store.get_fact(f["id"])["status"] == "active"
    # a recently used goal is not stale
    node = kg().get_node_by_label("goal:learn piano")
    store.touch([node["id"]])
    assert dr.stale_beliefs(store, kg(), datetime.now()) == []


# ---------------------------------------------------------------- routines
def _log(ts, query, used):
    kg()._store._conn.execute("CREATE TABLE IF NOT EXISTS tool_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, "
                              "conv_id TEXT, intent TEXT, query TEXT, sent TEXT, used TEXT, searched TEXT, n_sent INTEGER)")
    kg()._store._conn.execute("INSERT INTO tool_log(ts, query, used) VALUES (?,?,?)",
                              (ts.isoformat(), query, json.dumps(used)))


def _fridays(n):
    base = datetime(2026, 10, 30, 17, 10)          # a Friday, local time
    return [(base + timedelta(weeks=k)).astimezone(timezone.utc) for k in range(n)]


def test_mine_finds_repeated_sequence_with_schedule(monkeypatch):
    monkeypatch.setattr(ro, "_cfg", lambda: {"enabled": True, "min_count": 3, "min_days": 2, "lookback_days": 400,
                                             "max_induce_per_night": 2})
    for t in _fridays(3):
        _log(t, "weekly report for Dinesh", ["recall", "research_status", "research_export", "gmail_draft"])
    _log(datetime(2026, 11, 2, 10).astimezone(timezone.utc), "once", ["maps_route", "gmail_draft"])
    found = ro.mine()
    assert len(found) == 1
    c = found[0]
    assert c["sequence"] == ["research_status", "research_export", "gmail_draft"]   # trivial 'recall' removed
    assert c["schedule"] == {"weekday": 4, "hour": 17}


def test_verify_rejects_wrong_or_invented_steps():
    cand = {"sequence": ["research_status", "research_export", "gmail_draft"]}
    good = {"name": "Weekly report", "description": "Report for Dinesh",
            "steps": [{"tool": t} for t in cand["sequence"]]}
    assert ro.verify(good, cand, set(cand["sequence"]))[0]
    assert ro.verify({**good, "steps": [{"tool": "gmail_send"}]}, cand, set(cand["sequence"]))[1] == "unknown tool"
    rev = {**good, "steps": [{"tool": t} for t in reversed(cand["sequence"])]}
    assert ro.verify(rev, cand, None)[1] == "steps don't follow what was observed"
    assert ro.verify({**good, "steps": [{"tool": "research_status"}]}, cand, None)[1] == "steps don't cover the observed tools"


def test_run_saves_routine_offers_it_and_prompts(monkeypatch):
    monkeypatch.setattr(ro, "_cfg", lambda: {"enabled": True, "min_count": 3, "min_days": 2, "lookback_days": 400,
                                             "max_induce_per_night": 2})
    monkeypatch.setattr(ro, "_known_tools", lambda: {"research_status", "research_export", "gmail_draft"})
    for t in _fridays(3):
        _log(t, "weekly report for Dinesh", ["research_status", "research_export", "gmail_draft"])
    llm = FakeLLM({"name": "Weekly research report", "description": "Exports the research report and drafts it to Dinesh.",
                   "trigger_phrases": ["weekly report", "send Dinesh the report"],
                   "steps": [{"tool": "research_status", "purpose": "x"}, {"tool": "research_export", "purpose": "y"},
                             {"tool": "gmail_draft", "purpose": "z"}]})
    res = ro.run(llm=llm)
    assert res["created"] == ["Weekly research report"] and len(llm.prompts) == 1
    assert ro.run(llm=llm)["created"] == [] and len(llm.prompts) == 1                     # no re-induction
    assert "Weekly research report" in ro.prompt_block("can you do the weekly report for Dinesh")
    assert ro.prompt_block("what's the weather") == ""
    friday = datetime(2026, 11, 20, 17, 30)            # Friday, usual time, not done today
    c = ro.candidates(friday)
    assert c and c[0]["chat_prompt"].startswith("Run my usual routine") and c[0]["evidence"][0].startswith("wf_")
    from backend.brain.ledger import validate_why
    assert validate_why(c[0]["why"], c[0]["evidence"])[0]
    assert ro.candidates(datetime(2026, 11, 19, 17, 30)) == []                               # Thursday


# ---------------------------------------------------------------- curiosity
ITEMS = [{"n": 1, "ref": "conv:c1", "text": "Asked Mayday: how does Coorg weather look in December"},
         {"n": 2, "ref": "conv:c2", "text": "Asked Mayday: best homestays in Coorg"},
         {"n": 3, "ref": "conv:c3", "text": "Asked Mayday: hi"},
         {"n": 4, "ref": "p:x", "text": "Planner event: final exam"}]


def test_discover_requires_two_conversations_and_skips_known(monkeypatch):
    monkeypatch.setattr("backend.brain.intents.activity", lambda now, hours=0: ITEMS)
    monkeypatch.setattr(cu, "_known_topics", lambda: ["Nifty 50 Growth 1990-2025"])
    llm = FakeLLM({"topics": [
        {"topic": "Coorg trip planning", "question": "Best time and route for a Coorg trip in December?",
         "evidence": ["c1", "conv:c2"]},
        {"topic": "Greetings", "question": "?", "evidence": ["c3"]},
        {"topic": "Nifty 50 growth", "question": "x", "evidence": ["c1", "c2"]}]})
    found = cu.discover(llm, datetime(2026, 11, 20))
    assert [f["topic"] for f in found] == ["Coorg trip planning"]
    assert json.loads(found[0]["evidence"]) == ["conv:c1", "conv:c2"]


def test_learn_respects_daily_cap_and_flags_runs(monkeypatch):
    monkeypatch.setattr(cu, "_cfg", lambda: {"enabled": True, "max_per_day": 1, "lookback_days": 14})
    store = cu._store()
    for t in ("Coorg trip", "Laptop buying"):
        store._insert("curiosity", {"id": f"cu_{t[:3]}", "topic": t, "question": f"About {t}?", "evidence": "[]",
                                    "status": "queued", "run_id": None, "created_at": cu._now(), "updated_at": cu._now()})
    calls = []
    started = cu.learn(start=lambda topic, **kw: calls.append((topic, kw)) or {"run_id": "r1"})
    assert len(started) == 1 and calls[0][1]["options"] == {"brain_curiosity": True}
    assert calls[0][1]["budget"]["max_cost_usd"] <= 0.1                                    # quick preset


def test_finished_run_goes_through_the_gate_not_straight_to_the_user(monkeypatch):
    store = cu._store()
    store._insert("curiosity", {"id": "cu_x", "topic": "Coorg trip", "question": "Best time?",
                                "evidence": json.dumps(["conv:c1", "conv:c2"]), "status": "researching",
                                "run_id": "r1", "created_at": cu._now(), "updated_at": cu._now()})
    submitted = []
    monkeypatch.setattr("backend.brain.proactive.submit", lambda c, *a: submitted.append(c) or {})
    cu.on_research_finished("Coorg trip", {"status": "completed", "answers": [{"q": "x"}]})
    assert store._rows("SELECT status FROM curiosity WHERE id='cu_x'")[0]["status"] == "done"
    assert submitted and submitted[0]["type"] == "curiosity_brief" and submitted[0]["urgency"] == "low"
