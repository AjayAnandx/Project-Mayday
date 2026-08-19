"""MAGMA slow-path consolidation (Algorithm 3).

After an event node is added, a background worker scans the node's 2-hop
neighborhood and uses the *worker* (capable) model to infer latent causal and
entity edges, densifying the multi-graph. Runs off the critical response path.

Intended trigger (see backend/api/chat.py): after each engine turn, if
``magma.enabled`` and ``magma.consolidation_enabled`` are true, spin up a
daemon thread that enqueues un-consolidated nodes and processes the queue.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from collections import deque
from typing import Any

from backend.assistant.llm_client import get_worker_client
from backend.core.config import load_config
from backend.memory.multigraph import get_multigraph, SUBGRAPHS

logger = None
try:
    import logging
    logger = logging.getLogger("magma.consolidation")
except Exception:  # pragma: no cover
    pass


_PROMPT_HEAD = (
    "You are a memory-graph consolidation engine. Given a focal node and its "
    "2-hop neighborhood from an assistant's knowledge graph, infer latent "
    "relationships that are NOT already explicit.\n\n"
    "Return ONLY a JSON object with two keys:\n"
    "  \"causal\": list of {\"source\": <label>, \"target\": <label>, "
    "\"relation\": \"causes\"|\"caused_by\"|\"enables\"|\"precedes\"} "
    "(causal/temporal dependencies between events/todos; 'source' is the "
    "earlier/underlying cause).\n"
    "  \"entity\": list of {\"event\": <label>, \"entity\": <label>, "
    "\"kind\": \"person\"|\"object\"|\"place\"|\"concept\"} "
    "(the entity an event references).\n\n"
    "Only output relationships that are reasonably supported by the text. "
    "Use the exact labels shown below. If none are justified, return empty lists.\n\n"
)

_SYSTEM = "You output only valid minified JSON. No prose, no markdown."


def _clean_entity_label(label: str) -> str | None:
    """Reject internal node-label syntax / junk. Returns a clean label or None.

    The consolidation worker feeds the model existing graph labels, so it can
    regurgitate a mirror label like ``belief:identity:ajay`` as an "entity".
    We reject anything that looks like an internal node label (contains ':')
    or is implausibly long, so junk never lands back in the graph or profile.
    """
    if not label or not isinstance(label, str):
        return None
    s = label.strip()
    if not s or len(s) > 60:
        return None
    if ":" in s:
        return None
    return s


def _looks_like_name(value: str) -> bool:
    v = value.strip()
    if not v or len(v) > 40 or any(c.isdigit() for c in v):
        return False
    words = v.split()
    if not (1 <= len(words) <= 3):
        return False
    return all(w[:1].isupper() or not w[:1].isalpha() for w in words)


class ConsolidationWorker:
    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._cfg = load_config().get("magma", {})
        self.batch = int(self._cfg.get("consolidation_batch", 20))

    # ---- queue management -------------------------------------------------
    def enqueue(self, node_id: str) -> None:
        with self._lock:
            if node_id not in self._queue:
                self._queue.append(node_id)

    def enqueue_unconsolidated(self, limit: int | None = None) -> int:
        mg = get_multigraph()
        kg = mg._kg
        limit = limit or self.batch
        added = 0
        with self._lock:
            for nid, node in kg._nodes.items():
                if added >= limit:
                    break
                if node.get("type") == "belief":
                    continue
                if str(node.get("label", "")).startswith("belief:"):
                    continue
                if node.get("properties", {}).get("consolidated"):
                    continue
                if node.get("properties", {}).get("search_result") == "true":
                    continue
                if node.get("tombstoned") or node.get("properties", {}).get("tombstoned"):
                    continue
                if nid not in self._queue:
                    self._queue.append(nid)
                    added += 1
        return added

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    # ---- core ------------------------------------------------------------
    def _neighborhood_text(self, node_id: str) -> str | None:
        mg = get_multigraph()
        kg = mg._kg
        if node_id not in kg._nodes:
            return None
        sub = kg.get_subgraph(node_id, depth=2)
        node_lines = []
        for node in sub.get("nodes", []):
            label = node.get("label", node.get("id", node_id))
            ntype = node.get("type", "node")
            # Never feed internal mirror labels (belief:* / person:*) back into
            # the model — that is what caused it to echo them as "entities".
            if str(label).startswith("belief:") or ntype == "belief":
                continue
            node_lines.append(f"  - [{ntype}] {label}")
        labels = {n["id"]: n.get("label", n["id"]) for n in sub.get("nodes", [])}
        edge_lines = []
        for e in sub.get("edges", []):
            s = labels.get(e["source"], e["source"])
            t = labels.get(e["target"], e["target"])
            edge_lines.append(f"  - {s} --({e.get('relation','rel')})--> {t}")
        focal = kg._nodes[node_id].get("label", node_id)
        body = f"FOCAL NODE: [{kg._nodes[node_id].get('type','node')}] {focal}\n\n"
        body += "NODES (2-hop):\n" + "\n".join(node_lines) + "\n\n"
        body += "EXISTING EDGES:\n" + ("\n".join(edge_lines) or "  (none)")
        return body

    def _build_prompt(self, node_id: str) -> str | None:
        text = self._neighborhood_text(node_id)
        if not text:
            return None
        return _PROMPT_HEAD + "NEIGHBORHOOD:\n" + text + "\n\nJSON:"

    def _parse_response(self, text: str) -> dict:
        if not text:
            return {"causal": [], "entity": []}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {"causal": [], "entity": []}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"causal": [], "entity": []}
        return {
            "causal": data.get("causal", []) or [],
            "entity": data.get("entity", []) or [],
        }

    def _resolve_node(self, mg, label: str) -> str | None:
        node = mg._kg.get_node_by_label(label)
        return node["id"] if node else None

    def _apply(self, parsed: dict) -> int:
        mg = get_multigraph()
        kg = mg._kg
        created = 0
        for item in parsed.get("causal", []):
            s = self._resolve_node(mg, item.get("source", ""))
            t = self._resolve_node(mg, item.get("target", ""))
            # Don't wire causal edges into awareness mirror (belief:*) nodes.
            if s and self._is_belief_node(kg, s):
                s = None
            if t and self._is_belief_node(kg, t):
                t = None
            rel = item.get("relation", "causes")
            if s and t and s != t:
                mg.add_typed_edge_if_missing(s, t, "causal", rel)
                created += 1
        for item in parsed.get("entity", []):
            ev = self._resolve_node(mg, item.get("event", ""))
            if ev and self._is_belief_node(kg, ev):
                ev = None
            # A new entity is only created from a clean label (no internal
            # node-label syntax); junk labels are dropped, not stored.
            ent_label = _clean_entity_label(item.get("entity", ""))
            if not ev or not ent_label:
                continue
            eid = self._resolve_node(mg, ent_label)
            if not eid:
                kind = (item.get("kind") or "entity").lower()
                ntype = kind if kind in ("person", "object", "place", "concept") else "entity"
                eid = kg.add_node(ntype, ent_label, {"consolidated": True})
                created += 1
                # Mirror discovered person entities into the awareness world
                # model so the two stores share data — but ONLY genuinely
                # person-like names AND only when awareness is enabled.
                if ntype == "person" and _looks_like_name(ent_label):
                    try:
                        from backend.core.config import load_config
                        if load_config().get("awareness", {}).get("enabled", False):
                            from backend.core.user_awareness import get_awareness_store
                            get_awareness_store().add_belief(
                                "relations", ent_label, provenance="inference", confidence=0.7)
                    except Exception:
                        pass
            if eid and ev:
                mg.add_typed_edge_if_missing(ev, eid, "entity", "references")
                created += 1
        return created

    @staticmethod
    def _is_belief_node(kg, nid) -> bool:
        n = kg._nodes.get(nid)
        if not n:
            return False
        return n.get("type") == "belief" or str(n.get("label", "")).startswith("belief:")

    def process_one(self, worker_client=None) -> bool:
        with self._lock:
            if not self._queue:
                return False
            node_id = self._queue.popleft()
        mg = get_multigraph()
        kg = mg._kg
        node = kg._nodes.get(node_id)
        if not node:
            return True
        if node.get("properties", {}).get("consolidated"):
            return True
        prompt = self._build_prompt(node_id)
        if not prompt:
            node.setdefault("properties", {})["consolidated"] = True
            return True
        try:
            client = worker_client or get_worker_client()
            resp = client.chat([{"role": "user", "content": prompt}], stream=False, tools=[])
            content, _ = client.extract_response(resp)
            parsed = self._parse_response(content or "")
            self._apply(parsed)
        except Exception as exc:  # pragma: no cover - network/LLM path
            if logger:
                logger.warning("consolidation failed for %s: %s", node_id, exc)
            # re-queue with backoff by leaving it un-flagged but not re-adding now
            return False
        node.setdefault("properties", {})["consolidated"] = True
        return True

    def consolidate_pending(self, limit: int | None = None) -> int:
        limit = limit or self.batch
        processed = 0
        for _ in range(limit):
            if not self.process_one():
                break
            processed += 1
        return processed


_worker: ConsolidationWorker | None = None
_worker_lock = threading.Lock()


def get_consolidator() -> ConsolidationWorker:
    global _worker
    if _worker is None:
        with _worker_lock:
            if _worker is None:
                _worker = ConsolidationWorker()
    return _worker


def consolidate_node(node_id: str) -> None:
    get_consolidator().enqueue(node_id)
