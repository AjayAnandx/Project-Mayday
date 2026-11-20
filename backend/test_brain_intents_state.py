"""Brain V3 P13: latent goals (belief updates) and state estimation (personal baseline, corrections)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.brain import intents as it
from backend.brain import state as st


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat(self, messages, **kw):
        self.calls += 1
        return {"content": json.dumps(self.reply)}

    def extract_response(self, resp):
        return resp["content"], None


@pytest.fixture(autouse=True)
def env(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    from backend.brain import timing as tm
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    monkeypatch.setattr(tm, "_TIMING", tm.TimingState())
    monkeypatch.setattr(it, "_cfg", lambda: {"enabled": True, "min_interval_h": 2, "max_per_day": 4, "decay": 0.85,
                                             "working_p": 0.8, "drop_p": 0.2})
    monkeypatch.setattr(st, "_cfg", lambda: {"enabled": True, "min_baseline_days": 7, "cache_s": 0})
    monkeypatch.setattr(st, "_planner_load", lambda now: (0, 0.0, []))


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


ITEMS = [{"n": 1, "ref": "p:ev1", "text": "Planner event: Orbit investor pitch at 2026-11-26T10:00"},
         {"n": 2, "ref": "e_x", "text": "Session: edited the Orbit slide deck"},
         {"n": 3, "ref": "conv:c1", "text": "Asked Mayday: flights to Bengaluru on Wednesday"},
         {"n": 4, "ref": "", "text": "Tools used recently: maps_route×2"}]


# ---------------------------------------------------------------- inference
def test_infer_keeps_supported_hypotheses_only():
    llm = FakeLLM({"hypotheses": [
        {"goal": "Pitch prep for the Orbit investor meeting", "evidence": [1, 2, 3], "p": 0.75,
         "implies": ["final deck", "travel booked"], "horizon": "2026-11-26"},
        {"goal": "A holiday in Bengaluru", "evidence": [3], "p": 0.3, "implies": [], "horizon": None},
        {"goal": "Learn maps", "evidence": [4, 99], "p": 0.5, "implies": [], "horizon": None}]})
    hyps = it.infer(llm, ITEMS, datetime(2026, 11, 20))
    assert [h["goal"] for h in hyps] == ["Pitch prep for the Orbit investor meeting"]
    assert hyps[0]["evidence"] == ["p:ev1", "e_x", "conv:c1"] and hyps[0]["horizon"] == "2026-11-26"


def test_belief_update_merge_promote_decay_drop():
    h = {"goal": "Pitch prep for the Orbit investor meeting", "p": 0.7, "evidence": ["p:ev1", "e_x"],
         "implies": ["final deck"], "horizon": "2026-11-26"}
    assert it.update([h])["created"] == 1
    other = {"goal": "Revise for GATE exam", "p": 0.5, "evidence": ["e_y"], "implies": [], "horizon": None}
    it.update([other])
    # the pitch hypothesis is seen again with new evidence -> merged and promoted to working
    res = it.update([{**h, "p": 0.85, "evidence": ["p:ev1", "conv:c1", "conv:c2"]}])
    assert res["updated"] == 1
    rows = {r["goal"]: r for r in it._store()._rows("SELECT * FROM intents")}
    pitch = rows["Pitch prep for the Orbit investor meeting"]
    assert pitch["status"] == "working" and pitch["p"] >= 0.8
    assert set(json.loads(pitch["evidence"])) == {"p:ev1", "e_x", "conv:c1", "conv:c2"}
    # GATE not seen for many rounds -> decays below 0.2 -> dropped
    for _ in range(8):
        it.update([])
    gate = it._store()._rows("SELECT * FROM intents WHERE goal LIKE 'Revise%'")[0]
    assert gate["status"] == "dropped"


def test_confirm_and_reject():
    it.update([{"goal": "Plan Coorg trip", "p": 0.5, "evidence": ["x"], "implies": [], "horizon": None},
               {"goal": "Buy a new laptop", "p": 0.6, "evidence": ["y"], "implies": [], "horizon": None}])
    rows = {r["goal"]: r["id"] for r in it._store()._rows("SELECT * FROM intents")}
    assert it.confirm(rows["Plan Coorg trip"], True) and it.confirm(rows["Buy a new laptop"], False)
    for _ in range(10):
        it.update([])                                   # confirmed never decays
    assert [w["goal"] for w in it.working()] == ["Plan Coorg trip"]
    assert it._store()._rows("SELECT status FROM intents WHERE goal='Buy a new laptop'")[0]["status"] == "rejected"


def test_maybe_run_throttles():
    llm = FakeLLM({"hypotheses": []})
    it.maybe_run(datetime(2026, 11, 20, 10), llm=llm, force=False)
    assert it.maybe_run(datetime(2026, 11, 20, 10, 30), llm=llm)["skipped"] == "too soon"
    assert llm.calls <= 1


def test_prereq_candidates_skip_planned_items(monkeypatch):
    now = datetime(2026, 11, 22, 9)
    it.update([{"goal": "Pitch prep for the Orbit investor meeting", "p": 0.9, "evidence": ["p:ev1", "e_x"],
                "implies": ["final slide deck", "travel booked to Bengaluru", "talking points"],
                "horizon": "2026-11-26"}])
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: type("P", (), {
        "all_items": lambda self: [{"title": "Finish the slide deck", "status": "open"}]})())
    c = it.candidates(now)
    assert len(c) == 1 and "travel booked to Bengaluru" in c[0]["text"] and "slide deck" not in c[0]["text"]
    assert c[0]["mode"] == "framing" and c[0]["evidence"][0].startswith("i:")
    from backend.brain.ledger import evidence_exists
    assert evidence_exists(c[0]["evidence"][0])          # the intent itself is citable evidence


# ---------------------------------------------------------------- state
def test_state_neutral_and_calibrating_without_history():
    s = st.estimate(use_cache=False)
    assert all(0 <= s[d] <= 1 for d in st.DIMS)
    assert s["stress"] < 0.3 and s["fatigue"] < 0.3
    assert "load" in s["calibrating"] and "focus" in s["calibrating"]


def test_self_reports_and_frictions_raise_fatigue_and_stress():
    store = kg()._store
    store.add_fact(subject_id=None, predicate="mood", object="exhausted", confidence=0.9,
                   quote="honestly I'm exhausted, didn't sleep")
    from backend.brain.friction import _SCHEMA
    with store._lock:
        store._conn.execute(_SCHEMA)
        for k, sev in (("a", "high"), ("b", "high"), ("c", "medium")):
            store._conn.execute("INSERT INTO frictions(key, kind, severity, day, title, status, first_seen, last_seen) "
                                "VALUES (?, 'conflict', ?, '2026-11-21', 't', 'open', 'x', 'x')", (k, sev))
    s = st.estimate(use_cache=False)
    assert s["fatigue"] >= 0.5 and any("exhausted" in r for r in s["reasons"]["fatigue"])
    assert s["stress"] >= 0.5 and "3 open problems" in s["reasons"]["stress"][0]
    d = st.directives(s)
    assert "short and calm" in d and "never mention" in d


def test_focus_from_timing_and_load_z_score(monkeypatch):
    from backend.brain import timing as tm
    t = tm.TimingState()
    t.windows.append((datetime.now(timezone.utc), {"window_s": 15}))
    t.focus = {"category": "code", "since": datetime.now(timezone.utc) - timedelta(minutes=60)}
    monkeypatch.setattr(tm, "_TIMING", t)
    monkeypatch.setattr(st, "_planner_load", lambda now: (4, 9.0, [3.0, 4.0, 3.5, 2.5, 4.0, 3.0, 3.5, 4.5]))
    s = st.estimate(use_cache=False)
    assert s["focus"] >= 0.9 and s["load"] >= 0.8 and "load" not in s["calibrating"]
    assert "usual" in " ".join(s["reasons"]["load"])
    assert "deep work" in st.directives(s) and "at most 2 options" in st.directives(s)


def test_user_correction_overrides_and_is_counted():
    store = kg()._store
    store.add_fact(subject_id=None, predicate="mood", object="stressed", confidence=0.9, quote="so stressed")
    assert st.estimate(use_cache=False)["stress"] >= 0.5
    s = st.correct("stress", 0.1)
    assert s["stress"] == 0.1 and s["reasons"]["stress"][0] == "you corrected this"
    assert st.corrections_last_week() == 1
    with pytest.raises(ValueError):
        st.correct("mood", 0.5)


def test_stress_raises_the_decision_bar(monkeypatch):
    from backend.brain import proactive as pr
    monkeypatch.setattr(pr, "_cfg", lambda: {"enabled": True, "dial": "balanced", "quiet_hours": "22:30-07:00",
                                             "urgent_cap": 3, "cooldown_min": 30, "preauthorized": [],
                                             "earned_autonomy_after": 5, "min_sample": 0.0})
    f = kg()._store.add_fact(subject_id=None, predicate="deadline", object="Friday", confidence=0.9, quote="q")
    c = {"type": "idea", "text": "Try a new app", "why": "You mentioned Notion on Tuesday.", "evidence": [f["id"]],
         "value": 0.45, "urgency": "timely", "confidence": 0.9, "mode": "nudge"}
    assert pr.evaluate(c, datetime(2026, 11, 20, 12))["decision"] == "deliver"
    monkeypatch.setattr(st, "estimate", lambda *a, **k: {"focus": 0, "load": 0.2, "fatigue": 0.2, "stress": 0.8})
    assert pr.evaluate(c, datetime(2026, 11, 20, 12))["decision"] == "thought"
