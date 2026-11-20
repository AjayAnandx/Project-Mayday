"""Thin wrappers that reproduce what production does today, for measuring.

Each probe mirrors the live code path (chat.py) so the baseline reflects what the
model actually receives. When Brain V2 replaces a path, the probe is switched to
the new entry point and the same suite shows the delta.
"""
from __future__ import annotations

import time

from backend.core.config import load_config


# ---------- recall: mirrors what chat.py injects about the user ----------
def profile_block() -> str:
    """Always-on part (chat.py _phf_context_section -> phf personal facts)."""
    from backend.core.phf import personal_facts
    return personal_facts()


def recall_block(user_text: str, recent_user_texts: list[str] | None = None) -> str:
    """Per-turn part: chat.py _personal_recall_section + "Relevant memories"."""
    from backend.memory.knowledge_graph import extract_keywords, get_graph
    parts = []
    try:
        from backend.api.chat import _personal_recall_section
        people = _personal_recall_section(user_text).strip()
        if people:
            parts.append(people)
    except Exception:
        pass
    kg = get_graph()
    magma = load_config().get("magma", {})
    if extract_keywords(user_text):
        block = ""
        from backend.brain import context as brain_ctx
        if brain_ctx._cfg()["enabled"] and kg._store is not None:
            block = brain_ctx.retrieve(user_text, recent_user_texts)
        elif magma.get("enabled", False):
            try:
                from backend.memory.retrieval import magma_retrieve
                block = magma_retrieve(user_text, token_budget=int(magma.get("token_budget", 4000)))
            except Exception:
                block = ""
        else:
            mems = [m for m in kg.search(" ".join(extract_keywords(user_text)))
                    if m.get("properties", {}).get("search_result") != "true"]
            block = "\n".join(f"- [{m['type']}] {m['label']}" for m in mems[:8])
        if block:
            parts.append(block)
    return "\n".join(parts)


# ---------- tools: mirrors chat.py routing (classifier + selector + router) ----------
class ToolRoutingProbe:
    def __init__(self):
        from backend.api.chat import GROUP_SETS
        from backend.assistant.function_registry import get_tool_definitions
        from backend.core.query_classifier import QueryClassifier
        from backend.core.tool_router import DEFAULT_ROUTER_CAP, ToolRouter
        from backend.core.tool_selector import ToolSelector, max_tools_limit

        self.tools = get_tool_definitions()  # built-in only (MCP servers not started)
        self.router = ToolRouter(GROUP_SETS)
        groups = self.router.extended_groups(self.tools)
        self.selector = ToolSelector()
        self.selector.build_index(self.tools, groups)
        self.classifier = QueryClassifier()
        cap = max_tools_limit(load_config(), default=DEFAULT_ROUTER_CAP)
        self.cap = cap if cap and cap > 0 else DEFAULT_ROUTER_CAP

    def route(self, text: str) -> dict:
        t0 = time.perf_counter()
        intent = self.classifier.classify(text)
        if intent.tool_choice == "none":
            names: list[str] = []
        else:
            from backend.api.chat import GENERAL_MAX_SELECTOR_GROUPS
            sel = self.selector.select_tool_names(
                text, max_groups=GENERAL_MAX_SELECTOR_GROUPS if intent.intent == "general" else None)
            ordered = self.router.route_names(intent.active_groups, sel,
                                              intent.intent, intent.confidence)
            routed = self.router.route_tools(self.tools, ordered, cap=self.cap)
            # Brain V2 P5: same planner as chat.py (relevance order + max_tools + tool_search)
            from backend.brain import tools as bt
            exempt = set((load_config().get("brain", {}) or {}).get("tools", {}).get(
                "exempt_intents", ["build"]))
            if bt._cfg()["enabled"] and intent.intent not in exempt:
                from backend.api.chat import GROUP_SETS
                from backend.core.tool_router import ESSENTIAL_TOOL_NAMES
                inames: set[str] = set()
                if intent.intent != "general":
                    for g in intent.active_groups:
                        if g in GROUP_SETS and g != "core":
                            inames.update(GROUP_SETS[g])
                routed = bt.plan_tools(routed, text, bt.index_for(self.tools),
                                       set(ESSENTIAL_TOOL_NAMES), inames)
            names = [t.get("function", t).get("name", "") for t in routed]
        return {"intent": intent.intent, "tools": names,
                "ms": (time.perf_counter() - t0) * 1000}


# ---------- capture: mirrors the post-reply awareness observer ----------
def capture(text: str) -> list[dict]:
    from backend.core.awareness_observer import extract_candidates
    return [{"slot": c["slot"], "value": c["value"]} for c in extract_candidates(text)]


# ---------- capture (Brain V2 P3): gate + reflector + validator, nothing written ----------
def capture_reflector(text: str, llm=None) -> list[dict]:
    """What the P3 pipeline would write (auto + ask decisions), as {slot, value}."""
    from backend.brain import capture as cap
    if not cap.gate(text):
        return []
    if llm is None:
        from backend.assistant.llm_client import get_worker_client
        llm = get_worker_client()
    out = []
    for op in cap.validate(cap.reflect(llm, text), text):
        if op["decision"] == "drop":
            continue
        if op["kind"] == "fact":
            out.append({"slot": f"{op.get('subject', 'user')} {op['predicate']}", "value": op["object"]})
        elif op["kind"] in ("commitment", "idea"):
            out.append({"slot": op["kind"], "value": op["text"]})
        else:
            out.append({"slot": "alias", "value": f"{op['alias']} = {op['canonical']}"})
    return out
