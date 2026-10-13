"""ToolRouter regression tests — deterministic routing, no LLM calls.

Covers the OpenAI 400 fix: routed tool count must stay <= cap (100) for all
representative queries, never the full ~150 set. Also asserts the router
module performs zero network/LLM I/O (pure function, <5ms per route).
"""
import time

from backend.core.tool_router import (
    ToolRouter, ESSENTIAL_TOOL_NAMES, DEFAULT_ROUTER_CAP, PROVIDER_HARD_LIMIT,
)
from backend.core.tool_selector import ToolSelector, apply_tool_cap, max_tools_limit


def _tdef(name, server=None, desc="test tool"):
    d = {"type": "function",
         "function": {"name": name, "description": desc,
                      "parameters": {"type": "object", "properties": {}}}}
    if server:
        d["_mcp_server"] = server
    return d


def _groups():
    from backend.api.chat import GROUP_SETS
    return GROUP_SETS


def test_essentials_exist_in_definitions():
    from backend.assistant.function_registry import get_tool_definitions
    names = {t["function"]["name"] for t in get_tool_definitions()}
    missing = [n for n in ESSENTIAL_TOOL_NAMES if n not in names]
    assert not missing, f"essentials missing from definitions: {missing}"


def test_general_never_returns_full_set():
    from backend.assistant.function_registry import get_tool_definitions
    tools = get_tool_definitions()
    assert len(tools) > 100, f"expected large base set, got {len(tools)}"
    router = ToolRouter(_groups())
    ordered = router.route_names(["basic", "todo", "calendar"], set(),
                                 intent_name="general", confidence=0.8)
    filtered = router.route_tools(tools, ordered, cap=100)
    assert len(filtered) <= 100
    assert len(filtered) < len(tools)


def test_todo_query_contains_todo_excludes_music_github():
    from backend.api.chat import GROUP_SETS, TODO_TOOL_NAMES
    router = ToolRouter(GROUP_SETS)
    ordered = router.route_names(["basic", "todo"], set(),
                                 intent_name="todo", confidence=0.9)
    assert TODO_TOOL_NAMES.issubset(set(ordered))
    assert "music_play" not in ordered
    assert "search_repositories" not in ordered


def test_low_confidence_drops_intent_groups():
    router = ToolRouter(_groups())
    ordered = router.route_names(["basic", "project", "research"], {"recall"},
                                 intent_name="research", confidence=0.2)
    # only essentials + selector hits
    assert "create_project" not in ordered
    assert "recall" in ordered


def test_empty_route_falls_back_to_essentials_not_full():
    from backend.assistant.function_registry import get_tool_definitions
    tools = get_tool_definitions()
    router = ToolRouter(_groups())
    filtered = router.route_tools(tools, [], cap=100)
    names = {t["function"]["name"] for t in filtered}
    assert names.issubset(ESSENTIAL_TOOL_NAMES | set(names))
    assert len(filtered) <= len(ESSENTIAL_TOOL_NAMES)
    assert len(filtered) < len(tools)


def test_extended_groups_assigns_mcp_server_tools():
    router = ToolRouter(_groups())
    tools = [_tdef("create_todo"),
             _tdef("mystery_blast", server="github", desc="github repo blast")]
    extended = router.extended_groups(tools)
    assert "mystery_blast" in extended.get("github", set()) | extended.get("mcp_dynamic", set())


def test_extended_groups_prefix_fallback():
    router = ToolRouter(_groups())
    tools = [_tdef("git_mystery_status")]
    extended = router.extended_groups(tools)
    assert "git_mystery_status" in extended.get("git", set()) | extended.get("mcp_dynamic", set())


def test_router_is_fast_and_offline():
    # No LLM/network: route 20 queries in well under a second.
    router = ToolRouter(_groups())
    start = time.time()
    for i in range(20):
        router.route_names(["basic", "todo"], {"recall"}, "todo", 0.9)
    assert time.time() - start < 1.0


def test_router_module_imports_no_llm_or_network():
    import re
    src = open(__import__("backend.core.tool_router", fromlist=["__file__"]).__file__).read()
    imports = "\n".join(l for l in src.splitlines()
                        if re.match(r"\s*(import|from)\s", l))
    for banned in ("LLMClient", "httpx", "requests", "urllib", "openai",
                   "llm_client", "providers"):
        assert banned not in imports, f"router must not import {banned}"


def test_representative_queries_all_under_cap():
    from backend.assistant.function_registry import get_tool_definitions
    from backend.core.query_classifier import QueryClassifier
    tools = get_tool_definitions()
    clf = QueryClassifier()
    router = ToolRouter(_groups())
    sel = ToolSelector()
    sel.build_index(tools, router.extended_groups(tools))
    queries = [
        "create a todo to buy milk",
        "what meetings do I have tomorrow?",
        "research AI agent growth 2020-2026 with a chart",
        "build a portfolio website",
        "remember that I like morning walks",
        "what is the weather in Chennai?",
        "play some chill music",
        "hello",
        "show the git log for this repo",
        "find my TCS exam notes pdf",
    ]
    for q in queries:
        intent = clf.classify(q)
        sel_names = sel.select_tool_names(q)
        ordered = router.route_names(intent.active_groups, sel_names,
                                     intent.intent, intent.confidence)
        filtered = router.route_tools(tools, ordered, cap=100)
        assert len(filtered) <= 100, f"{q!r} routed {len(filtered)}"
        assert len(filtered) <= PROVIDER_HARD_LIMIT
        assert len(filtered) < len(tools), f"{q!r} fell back to full set"


def test_selector_no_longer_seeds_core():
    sel = ToolSelector()
    sel.build_index([_tdef("create_todo", desc="create todo"),
                     _tdef("git_log", desc="git log")],
                    {"todo": {"create_todo"}, "git": {"git_log"}})
    assert "core" not in sel.select("completely unrelated zebra query xyz")


def test_max_tools_default_is_100():
    assert max_tools_limit({}) == 100
    assert max_tools_limit({"providers": {"max_tools": 32}}) == 32


def test_apply_tool_cap_still_prefers_intent():
    tools = [_tdef(n) for n in ["a_core", "b_want", "c_core", "d_want", "e_core"]]
    capped = apply_tool_cap(tools, {"b_want", "d_want"}, 3)
    assert [t["function"]["name"] for t in capped] == ["b_want", "d_want", "a_core"]


def test_provider_guard_truncates_over_128():
    from unittest.mock import MagicMock
    from backend.assistant.providers import router as rmod
    from backend.assistant.providers.base import ProviderSpec
    spec = MagicMock(spec=ProviderSpec)
    spec.name = "openai"
    spec.endpoint = "http://x"
    spec.build_body.return_value = {}
    spec.build_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    http = MagicMock()
    http.post.return_value = resp
    tools = [_tdef(f"t{i}") for i in range(150)]
    with open(__import__("backend.assistant.providers.router", fromlist=["__file__"]).__file__) as f:
        assert "128" in f.read()
    out, _ = rmod.post_with_fallback(http, [spec], [{"role": "user", "content": "hi"}],
                                     tools=tools)
    sent = spec.build_body.call_args[0][1]
    assert len(sent) <= 128


def test_llm_client_defaults_to_no_tools():
    import inspect
    from backend.assistant import llm_client as lc
    src = inspect.getsource(lc.LLMClient.chat)
    assert "get_tool_definitions" not in src


# ---- wrong-tool regression: "play me the radhima song" ----

def _route_query(q):
    from backend.assistant.function_registry import get_tool_definitions
    from backend.core.query_classifier import QueryClassifier
    from backend.api.chat import GROUP_SETS
    tools = get_tool_definitions()
    clf = QueryClassifier()
    intent = clf.classify(q)
    router = ToolRouter(GROUP_SETS)
    sel = ToolSelector()
    sel.build_index(tools, router.extended_groups(tools))
    ordered = router.route_names(intent.active_groups, sel.select_tool_names(q),
                                 intent.intent, intent.confidence)
    return intent, [t["function"]["name"] for t in router.route_tools(tools, ordered, cap=100)]


def test_play_song_routes_music_play_without_pipeline_distractors():
    intent, names = _route_query("play me the radhima song")
    assert intent.intent == "music"
    assert "music_play" in names
    assert len(names) <= 25, f"routed set too noisy: {len(names)}"
    for distractor in ("extract_data_from_sources", "batch_add_data_points",
                       "generate_chart", "generate_report", "create_research",
                       "search_academic", "web_search_and_fetch"):
        assert distractor not in names, f"distractor routed: {distractor}"
    # intent's own tools outrank generic search tools
    assert names.index("music_play") < names.index("web_search_advanced_exa")


def test_calendar_plurals_route_calendar_tools():
    intent, names = _route_query("what meetings do I have tomorrow?")
    assert intent.intent == "calendar"
    assert "list_events" in names and "query_events" in names


def test_todo_plurals_route_todo_tools():
    intent, names = _route_query("list my todos")
    assert intent.intent == "todo"
    assert "list_todos" in names and "create_todo" in names


def test_core_group_never_selected():
    from backend.assistant.function_registry import get_tool_definitions
    from backend.api.chat import GROUP_SETS
    tools = get_tool_definitions()
    router = ToolRouter(GROUP_SETS)
    sel = ToolSelector()
    sel.build_index(tools, router.extended_groups(tools))
    for q in ["play me the radhima song", "create a todo to buy milk",
              "what meetings do I have tomorrow?", "show the git log",
              "research AI growth with a chart"]:
        assert "core" not in sel.select(q), f"core selected for {q!r}"


def test_confusable_descriptions_discriminate():
    from backend.assistant.function_registry import get_tool_definitions
    defs = {t["function"]["name"]: t["function"].get("description", "")
            for t in get_tool_definitions()}
    assert "music_play" in defs["web_search_exa"]  # search excludes music
    assert "web search" in defs["music_play"].lower()  # music excludes search-first
    assert "batch_add_data_points" in defs["add_data_point"]
    assert "add_data_point" in defs["batch_add_data_points"]
    assert "add_research_note" in defs["add_project_note"]
    assert "add_finding" in defs["remember"]
    assert "remember" in defs["add_finding"]
    assert "opencode_read" in defs["read_file"]
    assert "opencode_bash" in defs["sandbox_exec"]
