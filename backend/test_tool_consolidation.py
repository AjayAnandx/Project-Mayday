"""Phase 1 tool consolidation: music 21 -> 5 merged tools.

- Budget: local defs 147 -> 131 (music merge) -> 140 (+9 gmail tools).
  MCP/skill tools append separately at runtime.
- Dead names: retired music names appear nowhere in chat.py / sender.py / def list.
- Dispatch: each action routes to the right impl, old-name aliases resolve,
  invalid/missing action errors list valid actions, per-action folds/defaults apply.
- Schema leanness: each merged def carries <= 9 properties.
"""
import asyncio
import re

import backend.assistant.function_registry as reg
from backend.assistant.function_registry import dispatch_call, get_tool_definitions

RETIRED_MUSIC = [
    "play_song", "play_radio", "play_mood", "queue_song", "discover_trending",
    "my_top_songs", "open_video_popup", "search_youtube_videos",
    "add_favorite", "remove_favorite", "list_favorites", "toggle_favorite",
    "play_favorites", "add_trusted_channel", "remove_trusted_channel",
    "list_trusted_channels", "recommend_best_video",
    "list_popout_tabs", "close_popout_tab", "focus_popout_tab", "toggle_popout_tab",
]

MERGED_MUSIC = ["music_play", "music_discover", "music_library", "music_channels", "video_popup"]


def _run(coro):
    return asyncio.run(coro)


def _defs_by_name():
    return {d["function"]["name"]: d for d in get_tool_definitions()}


# ---- budget + dead names ----

def test_tool_budget_phase1():
    defs = get_tool_definitions()
    assert len(defs) == 140, f"expected 140 defs (131 music-merge + 9 gmail), got {len(defs)}"


def test_retired_music_names_gone_from_defs():
    names = set(_defs_by_name())
    assert not (set(RETIRED_MUSIC) & names)
    assert set(MERGED_MUSIC) <= names


def test_dead_music_names_in_chat_and_sender():
    for path in ["backend/api/chat.py", "backend/telegram/sender.py"]:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for n in RETIRED_MUSIC:
            assert not re.search(r"\b" + n + r"\b", src), f"{n} still referenced in {path}"


def test_merged_schemas_lean_and_enum_complete():
    defs = _defs_by_name()
    for name in MERGED_MUSIC:
        props = defs[name]["function"]["parameters"]["properties"]
        assert len(props) <= 9, f"{name} has {len(props)} properties (cap 9)"
        action = props["action"]
        assert sorted(action["enum"]) == sorted(reg._MERGED_ACTIONS[name].keys())


# ---- dispatch routing (impls stubbed — no network) ----

def _stub(monkeypatch, tool, action):
    calls = {}

    def fake(**kw):
        calls.update(kw)
        return f"{tool}/{action} ok"

    monkeypatch.setitem(reg._MERGED_ACTIONS[tool], action, fake)
    return calls


def test_music_play_routes(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "play")
    out = _run(dispatch_call("music_play", {"action": "play", "song": "hello"}))
    assert out == "music_play/play ok" and calls.get("song") == "hello"


def test_old_name_alias_resolves(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "play")
    out = _run(dispatch_call("play_song", {"song": "hello"}))
    assert out == "music_play/play ok" and calls.get("song") == "hello"


def test_explicit_action_wins_over_alias(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "queue")
    out = _run(dispatch_call("play_song", {"action": "queue", "song": "hello"}))
    assert out == "music_play/queue ok" and calls.get("song") == "hello"


def test_ambiguous_fold_radio(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "radio")
    out = _run(dispatch_call("music_play", {"action": "radio", "query": "lofi"}))
    assert out == "music_play/radio ok" and calls.get("seed_track") == "lofi"


def test_action_alias_normalized(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "queue")
    out = _run(dispatch_call("music_play", {"action": "add", "song": "x"}))
    assert out == "music_play/queue ok"


def test_unknown_action_lists_valid(monkeypatch):
    out = _run(dispatch_call("music_play", {"action": "dance", "song": "x"}))
    assert "Unknown action" in out and "play" in out and "favorites" in out


def test_missing_action_errors(monkeypatch):
    out = _run(dispatch_call("music_play", {"song": "x"}))
    assert "Missing required parameter" in out and "action" in out


def test_per_action_required_query(monkeypatch):
    out = _run(dispatch_call("music_discover", {"action": "search"}))
    assert "Missing required parameter" in out and "query" in out


def test_per_action_required_tab(monkeypatch):
    out = _run(dispatch_call("video_popup", {"action": "close"}))
    assert "Missing required parameter" in out and "tab_id" in out


def test_per_action_defaults(monkeypatch):
    calls = _stub(monkeypatch, "music_discover", "trending")
    _run(dispatch_call("music_discover", {"action": "trending"}))
    assert calls.get("count") == 10
    calls2 = _stub(monkeypatch, "music_play", "mood")
    _run(dispatch_call("music_play", {"action": "mood"}))
    assert calls2.get("mood") == "chill" and calls2.get("count") == 15


def test_explicit_false_not_overwritten_by_default(monkeypatch):
    calls = _stub(monkeypatch, "music_play", "favorites")
    _run(dispatch_call("music_play", {"action": "favorites", "shuffle": False}))
    assert calls.get("shuffle") is False
