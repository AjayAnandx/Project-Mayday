"""Deterministic tool router — NO LLM CALLS ALLOWED in this module.

Fixes OpenAI HTTP 400 ``Invalid 'tools': array too long (max 128)`` caused by
sending the full merged set (~150 defs: local + playwright + exa + MCP).

Design (all local, synchronous, <1ms):
- ``QueryClassifier`` intent groups -> primary tool names.
- ``ToolSelector`` TF-IDF hits -> lexical backup (supplement, never full set).
- ``ESSENTIAL_TOOL_NAMES`` (~10) -> always included, covers cross-cutting
  needs (search, memory, skill suggestion, weather).
- ``intent == "general"`` -> essentials + selector hits ONLY (never all groups).
  This is the key fix: previously ``general`` expanded to ``_all_groups()``.
- Hard cap (default 100, safe margin under the provider limit of 128)
  enforced for EVERY provider, not just cloud.

This module must never import LLMClient, httpx, or make network calls.
Pure functions: str/set in -> ordered names out.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Tools always sent: cross-cutting + discovery. All exist in
# LOCAL_TOOL_DEFINITIONS / EXA defs — verified, no guessing.
ESSENTIAL_TOOL_NAMES = frozenset({
    "unified_search",          # one-call search across all stores
    "recall",                  # memory search
    "recall_entity",           # entity detail
    "get_weather",             # proactive weather
    "suggest_skill",           # skill offer path
    "web_search_exa",          # complex web research
    "web_fetch_exa",           # URL content fetch
    "web_search_advanced_exa", # filtered search
    "list_projects",           # project discovery
    "get_conversations",       # conversation lookup
})

# Absolute provider ceiling (OpenAI/OpenRouter reject >128). Router default
# cap is lower (100) for headroom when skill tools append mid-loop.
PROVIDER_HARD_LIMIT = 128
DEFAULT_ROUTER_CAP = 100

# Maps MCP server name (tool["_mcp_server"]) -> GROUP_SETS group. Used by
# extended_groups() so dynamic MCP tools are routable instead of invisible
# (previously: not in any GROUP_SET -> never indexed -> never selected, or
# force-included via the full-set fallback).
SERVER_GROUP_MAP = {
    "git": "git",
    "github": "github",
    "fetch": "fetch",
    "opencode": "opencode",
    "ui-layouts": "design_mcp",
    "magic-ui": "design_mcp",
    "playwright": "browser",
    "exa": "basic",
    "firecrawl": "basic",
    "selenium": "browser",
}

# Per-intent demotions: tools that are valid but distracting for an intent.
# Demoted names are ordered LAST before the cap, so the cap drops distractors
# first and never essentials/intent tools. Essentials are never demoted.
# Rationale (seen live): "play me the radhima song" routed web_search_* +
# research/data pipeline tools next to music_play and the model picked search.
INTENT_DEMOTIONS: dict[str, frozenset[str]] = {
    "music": frozenset({
        "web_search_advanced_exa", "search_academic", "web_search_and_fetch",
        "extract_data_from_sources", "batch_add_data_points",
        "generate_chart", "generate_report", "create_research",
    }),
    "todo": frozenset({
        "web_search_advanced_exa", "search_academic", "extract_data_from_sources",
        "generate_chart", "generate_report",
    }),
    "calendar": frozenset({
        "web_search_advanced_exa", "search_academic", "extract_data_from_sources",
        "generate_chart", "generate_report",
    }),
    "weather": frozenset({
        "web_search_advanced_exa", "search_academic", "extract_data_from_sources",
        "batch_add_data_points", "generate_chart", "generate_report",
    }),
}

# Prefix fallback when _mcp_server is missing (local defs + stray MCP names).
_PREFIX_GROUP_MAP = (
    ("git_", "git"),
    ("Playwright_", "browser"),
    ("playwright_", "browser"),
    ("opencode_", "opencode"),
    ("sandbox_", "project"),
    ("design_", "design_mcp"),
    ("search_components", "design_mcp"),
    ("searchRegistryItems", "design_mcp"),
    ("getRegistryItem", "design_mcp"),
    ("get_source_code", "design_mcp"),
    ("music_", "music"),
    ("video_popup", "music"),
    ("gmail_", "gmail"),
)


def _infer_group(name: str, server: str = "") -> str | None:
    if server and server in SERVER_GROUP_MAP:
        return SERVER_GROUP_MAP[server]
    for prefix, group in _PREFIX_GROUP_MAP:
        if name.startswith(prefix):
            return group
    return None


class ToolRouter:
    """Deterministic router: intent groups + selector hits + essentials.

    Usage:
        router = ToolRouter(GROUP_SETS)
        extended = router.extended_groups(tools)   # once, at WS connect
        selector.build_index(tools, extended)
        # per message:
        ordered = router.route_names(intent.active_groups, selector_names,
                                     intent.intent, intent.confidence)
        filtered = router.route_tools(tools, ordered, cap=100)
    """

    def __init__(self, group_sets: dict[str, set[str]],
                 essentials: frozenset[str] | set[str] | None = None,
                 cap: int = DEFAULT_ROUTER_CAP):
        self._group_sets = {k: set(v) for k, v in group_sets.items()}
        self._essentials = frozenset(essentials) if essentials else ESSENTIAL_TOOL_NAMES
        self._cap = cap

    @property
    def essentials(self) -> frozenset[str]:
        return self._essentials

    def extended_groups(self, tools: list[dict]) -> dict[str, set[str]]:
        """Return GROUP_SETS plus dynamic assignments for unknown tool names.

        Tools whose name is in no known group are assigned via _mcp_server
        (or name-prefix fallback). Unassignable tools go to a generic
        ``mcp_dynamic`` group so the selector can still index them by
        description instead of dropping them silently.
        """
        extended: dict[str, set[str]] = {k: set(v) for k, v in self._group_sets.items()}
        known: set[str] = set()
        for names in extended.values():
            known.update(names)
        dynamic: set[str] = set()
        for t in tools:
            try:
                fn = t.get("function", t) if isinstance(t, dict) else {}
                name = fn.get("name", "") if isinstance(fn, dict) else ""
            except Exception:
                continue
            if not name or name in known:
                continue
            server = ""
            try:
                if isinstance(t, dict):
                    server = t.get("_mcp_server", "") or ""
            except Exception:
                server = ""
            group = _infer_group(name, server)
            if group and group in extended:
                extended[group].add(name)
                known.add(name)
            else:
                dynamic.add(name)
        if dynamic:
            extended.setdefault("mcp_dynamic", set()).update(dynamic)
        return extended

    def route_names(self, intent_groups: list[str] | set[str],
                    selector_names: set[str] | None,
                    intent_name: str = "",
                    confidence: float = 1.0) -> list[str]:
        """Compute priority-ordered tool names. Deterministic, no I/O.

        Order: intent groups (intent's own group first, names sorted) ->
        essentials (sorted) -> selector hits (sorted). Deduplicated.
        Intent tools rank first because weak models weight early tools more
        heavily; essentials are still always present for recall safety.
        ``general`` intent (or confidence < 0.5) contributes NO intent groups —
        only essentials + selector hits. Never returns the full set.
        """
        ordered: list[str] = []
        seen: set[str] = set()

        def _add(name: str):
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)

        is_general = (intent_name == "general") or (confidence < 0.5)
        if not is_general:
            wanted = [g for g in self._group_sets if g in set(intent_groups or [])]
            # The intent's own group (when the intent name matches a group)
            # goes first — weak models weight early tools more heavily.
            if intent_name in wanted:
                wanted = [intent_name] + [g for g in wanted if g != intent_name]
            # Skip the legacy 'core' monolith — essentials already cover it.
            for group in wanted:
                if group == "core":
                    continue
                for name in sorted(self._group_sets.get(group, ())):
                    _add(name)

        for name in sorted(self._essentials):
            _add(name)

        for name in sorted(selector_names or ()):
            _add(name)

        # Demote distractors for this intent to the tail (cap drops them first).
        # Essentials are never demoted. Order of the rest is preserved.
        demoted = INTENT_DEMOTIONS.get(intent_name or "", frozenset())
        if demoted:
            demote = {n for n in demoted if n not in self._essentials}
            head = [n for n in ordered if n not in demote]
            tail = sorted(n for n in ordered if n in demote)
            ordered = head + tail
        return ordered

    def route_tools(self, tools: list[dict], ordered_names: list[str],
                    cap: int | None = None) -> list[dict]:
        """Filter + priority-order + cap tool defs. Never returns full set
        on empty input — falls back to essentials present in ``tools``."""
        limit = self._cap if cap is None else cap
        by_name: dict[str, dict] = {}
        for t in tools:
            try:
                fn = t.get("function", t) if isinstance(t, dict) else {}
                name = fn.get("name", "") if isinstance(fn, dict) else ""
            except Exception:
                continue
            if name and name not in by_name:
                by_name[name] = t
        rank = {name: i for i, name in enumerate(ordered_names)}
        picked = [by_name[n] for n in ordered_names if n in by_name]
        if not picked:
            # Safe fallback: essentials only — NEVER the full set.
            picked = [by_name[n] for n in sorted(self._essentials) if n in by_name]
            logger.warning("ToolRouter: empty route — falling back to %d essentials", len(picked))
        if limit and limit > 0 and len(picked) > limit:
            dropped = [n for n in ordered_names if n in by_name][limit:]
            logger.warning("ToolRouter cap: sending %d of %d (limit %d); dropped: %s",
                           limit, len(picked), limit, ", ".join(dropped[:20]))
            picked = picked[:limit]
        return picked
