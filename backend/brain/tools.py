"""Brain V2 P5: tool planner.

    ToolIndex          per-tool relevance (BM25-ish over name + description) - orders tools
                       inside the routed set, and powers tool_search
    TOOL_SEARCH_DEF    a meta-tool: the model asks for tools it doesn't see; the engine adds
                       the matches to the tool list for the rest of the turn
    plan_tools()       routed tools -> at most `max_tools` (default 30), best first,
                       tool_search always included
    resolve_args()     memory-aware arguments: "email him" -> the address of the person named
                       in recent messages; "Kiran" -> kiran@... from Planner people / graph
    log_turn()         selected / used tools per turn (brain.db tool_log) so routing can be
                       measured on real use
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone

from backend.core.config import load_config

logger = logging.getLogger(__name__)

TOOL_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "tool_search",
        "description": (
            "Find tools you do not currently have. Use when the user asks for something none of your "
            "tools can do (e.g. git, GitHub, browser automation, PDFs, music, maps, research, files). "
            "Describe the capability in a few words; matching tools become available on your next step. "
            "Don't use it for tools you already have."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What you need to do, e.g. 'send an email', 'git commit'"}},
            "required": ["query"]},
    },
}

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with", "by", "is", "it", "this", "that",
         "use", "when", "user", "you", "your", "from", "as", "be", "are", "can", "will", "if", "not", "do",
         "me", "my", "i", "what", "how", "any", "all", "get", "set"}
# A few everyday words -> tool vocabulary
_SYN = {"mail": "email", "inbox": "email", "emails": "email", "reminder": "remind", "todo": "task",
        "todos": "task", "loud": "volume", "quiet": "volume", "song": "music", "songs": "music",
        "commute": "route", "traffic": "route", "drive": "route", "commit": "git", "repo": "github",
        "pdf": "pdf", "doc": "document", "weather": "weather", "umbrella": "weather", "rain": "weather"}


def _tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall((text or "").lower().replace("_", " ")):
        if w in _STOP or len(w) < 2:
            continue
        w = _SYN.get(w, w)
        for suf in ("ing", "es", "s", "ed"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _name(t: dict) -> str:
    return t.get("function", t).get("name", "")


class ToolIndex:
    def __init__(self, tools: list[dict]):
        self.tools = {_name(t): t for t in tools if _name(t)}
        self.docs: dict[str, Counter] = {}
        df: Counter = Counter()
        for name, t in self.tools.items():
            fn = t.get("function", t)
            # the name counts twice: it is the most precise signal
            toks = _tokens(name) * 2 + _tokens(fn.get("description", ""))[:80]
            c = Counter(toks)
            self.docs[name] = c
            df.update(set(c))
        n = max(len(self.docs), 1)
        self.idf = {w: math.log(1 + n / (1 + d)) for w, d in df.items()}
        self.avg = sum(sum(c.values()) for c in self.docs.values()) / n

    def score(self, query: str, name: str) -> float:
        doc = self.docs.get(name)
        if not doc:
            return 0.0
        length = sum(doc.values())
        s = 0.0
        for w in set(_tokens(query)):
            tf = doc.get(w, 0)
            if tf:
                s += self.idf.get(w, 0) * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self.avg))
        return s

    def search(self, query: str, k: int = 6, exclude: set[str] | None = None) -> list[str]:
        exclude = exclude or set()
        scored = [(self.score(query, n), n) for n in self.docs if n not in exclude]
        scored = [x for x in scored if x[0] > 0]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [n for _, n in scored[:k]]


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("tools", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "max_tools": int(c.get("max_tools", 30)),
            "search_k": int(c.get("search_k", 6)), "log": bool(c.get("log", True))}


def plan_tools(routed: list[dict], query: str, index: ToolIndex, essentials: set[str],
               intent_names: set[str], max_tools: int | None = None) -> list[dict]:
    """Order the routed tools by (tier, relevance) and keep at most ``max_tools``.

    tier 0: intent-group tools that match the query words, 1: essentials,
    2: other intent-group tools, 3: selector extras. tool_search is always added.
    """
    max_tools = max_tools or _cfg()["max_tools"]

    def tier(name: str, rel: float) -> int:
        if name in intent_names:
            return 0 if rel > 0 else 2
        if name in essentials:
            return 1
        return 3

    scored = []
    for i, t in enumerate(routed):
        n = _name(t)
        rel = index.score(query, n)
        scored.append((tier(n, rel), -rel, i, t))
    scored.sort(key=lambda x: x[:3])
    out = [t for *_, t in scored if _name(t) != "tool_search"][: max(max_tools - 1, 1)]
    out.append(TOOL_SEARCH_DEF)
    return out


def handle_tool_search(query: str, index: ToolIndex, current: list[dict]) -> tuple[str, list[dict]]:
    """Run tool_search: returns (result text for the model, tool defs to add)."""
    have = {_name(t) for t in current}
    names = index.search(query or "", k=_cfg()["search_k"], exclude=have)
    if not names:
        return ("No other tools match. Answer with the tools you have, or tell the user it isn't "
                "possible."), []
    added = [index.tools[n] for n in names]
    lines = []
    for n in names:
        desc = (index.tools[n].get("function", {}).get("description", "") or "").split(". ")[0][:140]
        lines.append(f"- {n}: {desc}")
    return "These tools are now available, call the one you need:\n" + "\n".join(lines), added


# ------------------------------------------------------------------ memory-aware args
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PRONOUN = re.compile(r"^(him|her|them|he|she|they)$", re.I)
_RECIPIENT_ARGS = {"gmail_send": "to", "gmail_draft": "to", "plan_delegate": "email"}


def _email_for(name: str) -> str | None:
    name = (name or "").strip()
    if not name:
        return None
    try:
        from backend.core.planner_store import get_planner
        p = get_planner().find_person(name)
        if p and p.get("email"):
            return p["email"]
    except Exception:
        pass
    try:
        from backend.memory.knowledge_graph import get_graph
        kg = get_graph()
        nid = kg._store.resolve_alias(name) if kg._store is not None else None
        node = (kg.get_node(nid) if nid else None) or kg.get_node_by_label(f"person:{name}") \
            or kg.get_node_by_label(name)
        if node:
            for k in ("email", "email_address"):
                if _EMAIL.match(str(node.get("properties", {}).get(k, ""))):
                    return node["properties"][k]
            for e in kg._adj_idx.get(node["id"], {}).get("out", []):
                tgt = kg.get_node(e["target"])
                if tgt and "email" in e.get("relation", "") and _EMAIL.match(tgt["label"]):
                    return tgt["label"]
    except Exception:
        pass
    return None


def resolve_args(fn_name: str, args: dict, recent_user_texts: list[str] | None = None) -> tuple[dict, str]:
    """Fill a recipient from memory when the model passed a name or pronoun.

    Returns (args, note). Never invents an address: if nothing is found the args are
    returned unchanged and the tool reports its own error.
    """
    key = _RECIPIENT_ARGS.get(fn_name)
    if not key or not isinstance(args, dict):
        return args, ""
    raw = str(args.get(key) or "").strip()
    if fn_name == "plan_delegate" and not raw:
        raw = str(args.get("person") or "").strip()
    if not raw or _EMAIL.match(raw):
        return args, ""
    name = raw
    if _PRONOUN.match(raw) and recent_user_texts:
        from backend.brain.context import expand_query
        from backend.memory.knowledge_graph import get_graph
        _, resolved = expand_query(get_graph(), f"email {raw}", recent_user_texts)
        name = resolved[0] if resolved else ""
    email = _email_for(name) if name else None
    if not email:
        return args, ""
    new = dict(args)
    new[key] = email
    return new, f"resolved '{raw}' to {name} <{email}> from memory"


# ------------------------------------------------------------------ selection log
_LOG_SCHEMA = """CREATE TABLE IF NOT EXISTS tool_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, conv_id TEXT, intent TEXT,
    query TEXT, sent TEXT, used TEXT, searched TEXT, n_sent INTEGER)"""


def log_turn(conv_id: str, intent: str, query: str, sent: list[str], used: list[str],
             searched: list[str] | None = None) -> None:
    if not _cfg()["log"]:
        return
    try:
        from backend.memory.knowledge_graph import get_graph
        store = get_graph()._store
        if store is None:
            return
        with store._lock:
            store._conn.execute(_LOG_SCHEMA)
            store._conn.execute(
                "INSERT INTO tool_log(ts, conv_id, intent, query, sent, used, searched, n_sent) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), conv_id, intent, (query or "")[:300],
                 json.dumps(sent), json.dumps(used), json.dumps(searched or []), len(sent)))
    except Exception as e:
        logger.debug("tool_log failed: %s", e)


def tool_stats(days: int = 30) -> dict:
    """Usage summary from tool_log: how often tools were used, searched for, or sent unused."""
    from backend.memory.knowledge_graph import get_graph
    store = get_graph()._store
    if store is None:
        return {}
    with store._lock:
        store._conn.execute(_LOG_SCHEMA)
    rows = store._rows("SELECT * FROM tool_log ORDER BY id DESC LIMIT 5000")
    used, searched, sent = Counter(), Counter(), []
    for r in rows:
        used.update(json.loads(r["used"] or "[]"))
        searched.update(json.loads(r["searched"] or "[]"))
        sent.append(r["n_sent"] or 0)
    return {"turns": len(rows), "avg_sent": round(sum(sent) / len(sent), 1) if sent else 0,
            "most_used": used.most_common(15), "found_via_search": searched.most_common(15)}


_INDEX_CACHE: dict[tuple, ToolIndex] = {}


def index_for(tools: list[dict]) -> ToolIndex:
    """ToolIndex for this tool list, cached (rebuilt only when the set of names changes)."""
    key = tuple(sorted(_name(t) for t in tools))
    idx = _INDEX_CACHE.get(key)
    if idx is None:
        _INDEX_CACHE.clear()
        idx = _INDEX_CACHE[key] = ToolIndex(tools)
    return idx
