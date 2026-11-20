"""Autonomous voice research: routing → runs/groups, one announcement per group, delivery routing,
topic-less follow-ups, voice summaries, and the realtime handoff never polluting the user's words."""
from unittest import mock

import pytest

from backend.core import research_autopilot as ap
from backend.test_research_flow import _isolated, cleanup  # noqa: F401  (fixtures)


@pytest.fixture
def no_delivery():
    """No real scheduler/Telegram/voice; capture what would be delivered."""
    sent = {"notify": [], "telegram": []}
    sched = mock.MagicMock()
    sched.fire_notification.side_effect = lambda t, b, **k: sent["notify"].append((t, b, k))
    with mock.patch("backend.core.scheduler.get_scheduler", return_value=sched), \
         mock.patch("backend.telegram.push.push_research",
                    side_effect=lambda t, s, r: sent["telegram"].append((t, s)) or True):
        saved = list(ap._voice_hooks)
        ap._voice_hooks.clear()
        yield sent
        ap._voice_hooks[:] = saved


def _fake_start(store):
    def start(topic, **kw):
        if store._get_by_topic(topic) is None:
            store.create_research(topic, kw.get("research_type", "domain"), 2,
                                 allow_similar=bool((kw.get("options") or {}).get("group_id")))
        brief = {"request": kw.get("request", ""), "questions": []}
        if (kw.get("options") or {}).get("group_id"):
            brief["group_id"] = kw["options"]["group_id"]
        run = store.start_run(topic, brief, kw.get("budget"))
        start.calls.append((topic, kw))
        return {"run_id": run["id"], "topic": topic, "status": "running", "budget": run["budget"]}
    start.calls = []
    return start


def _finish(store, topic, run_id, answer="Solid-state cells reached 400 Wh/kg [1]."):
    store.update_run(topic, run_id, answers=[{"question": "Q?", "answer": answer, "claim_ids": []}])
    return store.finish_run(topic, run_id, status="completed")


def test_combined_request_starts_a_group_with_split_budget(_isolated, no_delivery):
    start = _fake_start(_isolated)
    res = ap.launch("analyse the market size and what the research says about solid-state batteries",
                    budget={"max_minutes": 10, "max_sources": 40, "max_cost_usd": 0.5}, start=start)
    assert res["group_id"] and [r["category"] for r in res["runs"]] == ["market", "academic"]
    assert res["explanation"].startswith("I'll research this in 2 parts")
    budgets = [kw["budget"] for _, kw in start.calls]
    assert all(b["max_minutes"] == 10 and b["max_sources"] == 20 and b["max_cost_usd"] == 0.25 for b in budgets)
    academic_kw = start.calls[1][1]
    assert academic_kw["options"]["field"] == "general" and academic_kw["research_type"] == "academic"
    assert "field" not in start.calls[0][1]["options"]                      # market gets no academic options
    assert ap.latest()["kind"] == "group" and len(ap.latest()["topics"]) == 2


def test_group_announces_once_when_the_last_run_finishes(_isolated, no_delivery):
    start = _fake_start(_isolated)
    res = ap.launch("compare Figma vs Canva as well as the market size for design tools", start=start)
    (t1, r1), (t2, r2) = [(r["topic"], r["run_id"]) for r in res["runs"]]
    assert ap.on_run_finished(t1, _finish(_isolated, t1, r1)) is None       # first part: silent
    item = ap.on_run_finished(t2, _finish(_isolated, t2, r2))
    assert item and "2 parts" in item["summary"] and "[1]" not in item["summary"]
    assert len(no_delivery["notify"]) == 1
    assert ap.on_run_finished(t2, _finish(_isolated, t2, r2)) is None       # never twice


def test_single_run_announcement_routes_to_voice_or_telegram(_isolated, no_delivery):
    start = _fake_start(_isolated)
    res = ap.launch("what does the research say about intermittent fasting", start=start)
    topic, rid = res["runs"][0]["topic"], res["runs"][0]["run_id"]
    final = _finish(_isolated, topic, rid)

    # nobody listening → Telegram + on-screen notification that speaks in classic voice + pending
    item = ap.on_run_finished(topic, final)
    assert not item["spoken"] and item["telegram"] and no_delivery["telegram"]
    assert no_delivery["notify"][-1][2]["extra"]["speak"] == item["summary"]
    assert [p["title"] for p in ap.take_pending()] == [item["title"]] and ap.take_pending() == []

    # live realtime session → spoken, no Telegram, notification does not speak a second time
    no_delivery["telegram"].clear()
    ap.register_voice_hook(lambda title, summary: True)
    item = ap.on_run_finished(topic, final)
    assert item["spoken"] and not no_delivery["telegram"]
    assert no_delivery["notify"][-1][2]["extra"]["speak"] == ""
    assert ap.take_pending() == []


def test_topicless_followups_use_the_latest_research(_isolated, no_delivery):
    from backend.functions import research_flow_functions as fns
    start = _fake_start(_isolated)
    res = ap.launch("research the market size of electric scooters in India", start=start)
    topic, rid = res["runs"][0]["topic"], res["runs"][0]["run_id"]
    assert fns.research_status_voice().startswith("Still working on")
    _finish(_isolated, topic, rid, "The Indian e-scooter market was about 1 billion dollars in 2024 [2].")
    spoken = fns.research_status_voice()
    assert "Indian e-scooter market" in spoken and "[2]" not in spoken
    assert topic in fns.research_status() or "Run " in fns.research_status()


def test_voice_summary_failed_and_length():
    from backend.core.research_report import voice_summary
    rec = {"topic": "T", "claims": []}
    assert "without a verified answer" in voice_summary(rec, {"status": "failed", "answers": []})
    long = {"status": "completed", "answers": [{"question": "q", "answer": ("word " * 400) + ".", "claim_ids": []}]}
    assert len(voice_summary(rec, long, max_chars=300)) <= 300


def test_realtime_handoff_is_not_the_users_words():
    from backend.assistant.realtime_worker import build_worker_prompt
    from backend.functions.research_flow_functions import _LISTED_QUESTIONS, user_words
    prompt = build_worker_prompt("research_start", {"topic": "e-bikes"}, "analyse the market for e-bikes")
    assert user_words(prompt) == "analyse the market for e-bikes"
    assert not _LISTED_QUESTIONS.search(user_words(prompt))
    assert user_words("plain typed request") == "plain typed request"


def test_live_session_registry_speaks_into_open_sessions():
    import asyncio
    import importlib
    vr = importlib.import_module("backend.voice.router")
    sent = []

    class WS:
        async def send(self, data):
            sent.append(data)

    async def go():
        vr._LIVE_SESSIONS["s"] = (asyncio.get_running_loop(), WS(), {"speaking": False})
        try:
            heard = await asyncio.to_thread(vr.speak_to_live_sessions, "Research done: X", "Found Y.")
            await asyncio.sleep(0.2)
            return heard
        finally:
            vr._LIVE_SESSIONS.pop("s", None)
    assert asyncio.run(go()) is True
    assert any("Found Y." in s for s in sent) and any("response.create" in s for s in sent)
    assert vr.speak_to_live_sessions("t", "s") is False                     # no sessions → not heard
