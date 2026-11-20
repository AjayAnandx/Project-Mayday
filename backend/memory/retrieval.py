"""MAGMA Query Process: adaptive, intent-aware graph retrieval.

Replaces the flat ``kg.search()`` memory lookup in chat.py with MAGMA's
policy-guided retrieval pipeline:

  Stage 1  Query intent detection  (WHY / WHEN / ENTITY / SEMANTIC) - deterministic,
           no LLM call, maps to a preferred ordered set of relation graphs.
  Stage 2  RRF anchor fusion       (dense vector + sparse keyword) via MultiGraph.
  Stage 3  Beam traversal          expand anchors, biased toward intent-preferred
           subgraphs (causal / temporal / entity / semantic).
  Stage 4  Provenance linearization + token budget, producing the "Relevant
           memories" block injected into the system prompt.

Deterministic and fast (no model call) so it can run on every engine turn.
Falls back to "" on any error so the caller can use its legacy path.
"""
import re

from backend.core.config import load_config
from backend.memory.multigraph import get_multigraph

# Deterministic intent -> ordered preference of relation graphs.
INTENT_SUBGRAPH_PREF = {
    "WHY": ["causal", "temporal", "semantic"],
    "WHEN": ["temporal", "semantic"],
    "ENTITY": ["entity", "semantic"],
    "SEMANTIC": ["semantic", "entity"],
}

_WHY_RE = re.compile(r"\b(why|because|cause|reason|how come|what led|root cause)\b", re.I)
_WHEN_RE = re.compile(r"\b(when|what time|what date|schedule|appointment|deadline|due|calendar|tomorrow|yesterday|last week|this month)\b", re.I)
_ENTITY_RE = re.compile(r"\b(who|about|tell me about|my (brother|sister|mom|dad|friend|boss|team)|person|where is)\b", re.I)


def detect_intent(user_text: str) -> str:
    if _WHY_RE.search(user_text):
        return "WHY"
    if _WHEN_RE.search(user_text):
        return "WHEN"
    if _ENTITY_RE.search(user_text):
        return "ENTITY"
    return "SEMANTIC"


def _node_timestamp(node: dict) -> str:
    props = node.get("properties", {})
    for key in ("start_time", "due_date", "timestamp", "created_at", "date"):
        v = props.get(key)
        if v:
            return str(v)
    return ""


def _traverse(mg, anchors, preferred, beam_width=20, max_nodes=12, max_depth=2):
    """Heuristic beam search over typed subgraphs (MAGMA Eq.5 approximation)."""
    visited: set[str] = set()
    scored: dict[str, float] = {}
    for rank, nid in enumerate(anchors):
        scored[nid] = 1.0 / (60 + rank + 1)
        visited.add(nid)

    frontier = list(anchors)
    for _ in range(max_depth):
        if len(visited) >= max_nodes:
            break
        candidates = []
        for nid in frontier:
            for e in mg.neighbors(nid):
                other = e["target"] if e["source"] == nid else e["source"]
                if other in visited:
                    continue
                sg = e.get("properties", {}).get("subgraph")
                pref_weight = 1.0 if sg in preferred else 0.3
                base = scored.get(nid, 0.0)
                candidates.append((base * 0.7 + pref_weight * 0.3, other))
        candidates.sort(reverse=True)
        next_frontier = []
        for score, other in candidates[:beam_width]:
            if other in visited or len(visited) >= max_nodes:
                continue
            visited.add(other)
            scored[other] = score
            next_frontier.append(other)
        if not next_frontier:
            break
        frontier = next_frontier
    return sorted(visited, key=lambda n: -scored.get(n, 0.0))


# Bookkeeping relations that say nothing about the user.
_NOISE_RELATIONS = {"precedes", "has_task_result", "references", "has_note"}


def _relation_facts(kg, nid: str, limit: int = 4) -> list[str]:
    """Direct relations of a node as readable facts: 'Kiran Rao -lives_in-> Bengaluru'."""
    adj = kg._adj_idx.get(nid, {})
    facts = []
    for e in adj.get("out", []) + adj.get("in", []):
        rel = e.get("relation", "")
        if rel in _NOISE_RELATIONS:
            continue
        src, tgt = kg.get_node(e["source"]), kg.get_node(e["target"])
        if not src or not tgt:
            continue
        facts.append(f"    {src['label']} -{rel}-> {tgt['label']}")
        if len(facts) >= limit:
            break
    return facts


def _linearize(mg, node_ids, intent, token_budget=4000):
    kg = mg._kg
    # node_ids arrive best-first; WHEN questions are re-ordered chronologically.
    nodes = [kg.get_node(nid) for nid in node_ids if kg.get_node(nid)]
    if intent == "WHEN":
        nodes.sort(key=lambda n: _node_timestamp(n) or "9999")
    nodes = nodes[:12]

    lines = []
    total = 0
    shown_facts: set[str] = set()
    for n in nodes:
        ts = _node_timestamp(n)
        label = n.get("label", "")
        ntype = n.get("type", "")
        extra = ""
        for k, v in n.get("properties", {}).items():
            if k in ("subgraph", "status", "search_result", "message_count", "context"):
                continue
            if isinstance(v, (str, int, float)) and v not in (None, ""):
                extra = f" ({k}: {v})"
                break
        facts = [f for f in _relation_facts(kg, n["id"]) if f not in shown_facts]
        shown_facts.update(facts)
        header = f"<t:{ts}> [{ntype}] {label}{extra}"
        while facts and total + len(header) + sum(len(f) + 1 for f in facts) + 1 > token_budget:
            facts.pop()
        block = "\n".join([header] + facts)
        if total + len(block) + 1 > token_budget and lines:
            lines.append(f"...{len(nodes) - len(lines)} more relevant memories (truncated)")
            break
        lines.append(block)
        total += len(block) + 1
    return "\n".join(lines)


def magma_retrieve(user_text: str, token_budget: int = 4000, beam_width: int = 20) -> str:
    """Return the assembled "Relevant memories" block for ``user_text``."""
    mg = get_multigraph()
    intent = detect_intent(user_text)
    preferred = INTENT_SUBGRAPH_PREF.get(intent, ["semantic"])

    anchors = mg.rrf_anchors(user_text, top_k=20)
    # Filter junk nodes (search_result scaffolding) from anchors.
    anchors = [
        a for a in anchors
        if mg._kg.get_node(a)
        and mg._kg.get_node(a).get("properties", {}).get("search_result") != "true"
    ]
    if not anchors:
        return ""

    # Only the strongest anchors; leave room in max_nodes for their neighbours.
    anchors = anchors[:6]
    selected = _traverse(mg, anchors, preferred, beam_width=beam_width, max_nodes=12)
    return _linearize(mg, selected, intent, token_budget=token_budget)
