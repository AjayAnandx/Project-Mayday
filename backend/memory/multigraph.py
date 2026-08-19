"""MAGMA Data Structure Layer (additive wrapper over KnowledgeGraph).

Implements MAGMA's unified multi-graph memory substrate G_t = (N_t, E_t) where
edges are partitioned into four orthogonal subspaces:

  - temporal : n_{i-1} -> n_i  (strict chronological backbone, derived from node order)
  - causal   : logical entailment ("why"), inferred by the slow-path consolidation worker
  - semantic : conceptual similarity (cosine over the vector index)
  - entity   : event <-> entity (person/object) nodes

Every typed edge carries a ``subgraph`` property so the existing flat retrieval
(kg.search) is unchanged, while MAGMA query code can filter/traverse by view.
Nothing here mutates KnowledgeGraph's storage format, so the 212-test suite and
all REST/LLM paths keep working.
"""
import math
import re
import threading
import zlib
from collections import defaultdict

from backend.core.config import load_config
from backend.memory.knowledge_graph import get_graph

SUBGRAPHS = ("semantic", "temporal", "causal", "entity")
RELATION_BY_SUBGRAPH = {
    "temporal": "precedes",
    "causal": "causes",
    "semantic": "similar_to",
    "entity": "references",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


class _LocalEmbedder:
    """Lightweight, dependency-free dense embedder (TF over hashed token buckets).

    A stand-in for a real embedding model. Produces L2-normalized vectors so
    cosine similarity is a plain dot product. Swap `_embed` for an Ollama
    embedding call later without changing any caller.
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _hash(self, tok: str) -> int:
        # Stable across processes (Python's built-in hash() is salted per run,
        # which made vector similarities and the RRF test flaky).
        return (zlib.crc32(tok.encode("utf-8")) & 0x7FFFFFFF) % self.dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = _tokens(text)
        if not toks:
            return vec
        for t in toks:
            vec[self._hash(t)] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))


class MultiGraph:
    def __init__(self):
        self._kg = get_graph()
        self._lock = threading.RLock()
        cfg = load_config().get("magma", {})
        self.vector_dim = int(cfg.get("vector_dim", 1024))
        self.semantic_threshold = float(cfg.get("semantic_threshold", 0.30))
        self._embedder = _LocalEmbedder(self.vector_dim)
        self._vectors: dict[str, list[float]] = {}
        self._index_dirty = True
        self._temporal_cache: list[tuple[str, str]] | None = None

    # ------------------------------------------------------------------ #
    # Typed edge writers (MAGMA relation graphs)
    # ------------------------------------------------------------------ #
    def add_typed_edge(self, source: str, target: str, subgraph: str,
                       relation: str | None = None, properties: dict | None = None) -> str:
        if subgraph not in SUBGRAPHS:
            raise ValueError(f"unknown subgraph {subgraph!r}; expected one of {SUBGRAPHS}")
        props = dict(properties or {})
        props["subgraph"] = subgraph
        rel = relation or RELATION_BY_SUBGRAPH.get(subgraph, "related")
        return self._kg.add_edge(source, target, rel, props)

    def has_typed_edge(self, source: str, target: str, subgraph: str) -> bool:
        return any(
            e["source"] == source and e["target"] == target
            and e.get("properties", {}).get("subgraph") == subgraph
            for e in self._kg._edges
        )

    def add_typed_edge_if_missing(self, source: str, target: str, subgraph: str,
                                  relation: str | None = None, properties: dict | None = None) -> str | None:
        if self.has_typed_edge(source, target, subgraph):
            return None
        return self.add_typed_edge(source, target, subgraph, relation, properties)

    def add_causal_edge(self, source: str, target: str, properties: dict | None = None) -> str:
        return self.add_typed_edge(source, target, "causal", "causes", properties)

    def add_entity_edge(self, source: str, target: str, properties: dict | None = None) -> str:
        return self.add_typed_edge(source, target, "entity", "references", properties)

    def add_semantic_edge(self, source: str, target: str, score: float = 0.0) -> str:
        return self.add_typed_edge(source, target, "semantic", "similar_to", {"score": score})

    # ------------------------------------------------------------------ #
    # Typed edge readers
    # ------------------------------------------------------------------ #
    def edges_by_subgraph(self, subgraph: str) -> list[dict]:
        return [e for e in self._kg._edges if e.get("properties", {}).get("subgraph") == subgraph]

    def neighbors(self, node_id: str, subgraph: str | None = None) -> list[dict]:
        out = []
        for e in self._kg._edges:
            if e["source"] == node_id or e["target"] == node_id:
                if subgraph is None or e.get("properties", {}).get("subgraph") == subgraph:
                    out.append(e)
        return out

    def stats(self) -> dict:
        by_sub = defaultdict(int)
        for e in self._kg._edges:
            sg = e.get("properties", {}).get("subgraph")
            if sg:
                by_sub[sg] += 1
        base = self._kg.stats()
        base["subgraphs"] = dict(by_sub)
        return base

    # ------------------------------------------------------------------ #
    # Temporal backbone (Fast Path) — derived from node order, not written
    # at ingest, so no ingestion path is touched (fully additive).
    # ------------------------------------------------------------------ #
    def _ordered_nodes(self) -> list[dict]:
        return list(self._kg._nodes.values())

    def temporal_chain(self) -> list[tuple[str, str]]:
        """Return (prev_id, curr_id) pairs forming the chronological backbone."""
        nodes = self._ordered_nodes()
        chain = []
        prev = None
        for n in nodes:
            if prev is not None:
                chain.append((prev, n["id"]))
            prev = n["id"]
        return chain

    def ensure_temporal_backbone(self):
        """Materialize the temporal backbone as typed edges (idempotent)."""
        with self._lock:
            existing = {(e["source"], e["target"])
                        for e in self.edges_by_subgraph("temporal")}
            for prev, curr in self.temporal_chain():
                if (prev, curr) not in existing:
                    self.add_typed_edge(prev, curr, "temporal", "precedes")
                    existing.add((prev, curr))

    # ------------------------------------------------------------------ #
    # Vector index (dense retrieval for MAGMA RRF anchor fusion)
    # ------------------------------------------------------------------ #
    def _node_text(self, node: dict) -> str:
        parts = [node.get("label", ""), node.get("type", "")]
        for v in node.get("properties", {}).values():
            if isinstance(v, str):
                parts.append(v)
        return " ".join(parts)

    def _rebuild_vector_index(self):
        self._vectors.clear()
        for n in self._kg._nodes.values():
            self._vectors[n["id"]] = self._embedder.embed(self._node_text(n))
        self._index_dirty = False

    def index_node(self, node_id: str):
        n = self._kg.get_node(node_id)
        if n:
            self._vectors[node_id] = self._embedder.embed(self._node_text(n))

    def vector_search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        if self._index_dirty or len(self._vectors) != len(self._kg._nodes):
            self._rebuild_vector_index()
        qv = self._embedder.embed(query)
        scored = [(nid, self._embedder.cosine(qv, vec)) for nid, vec in self._vectors.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------ #
    # RRF fusion (MAGMA Stage 2): blend dense vector + sparse keyword
    # ------------------------------------------------------------------ #
    def rrf_anchors(self, query: str, top_k: int = 20, k: int = 60) -> list[str]:
        vec = self.vector_search(query, top_k=top_k)
        kw = self._kg.search(query)[:top_k]
        scores: dict[str, float] = defaultdict(float)
        for rank, (nid, _) in enumerate(vec):
            scores[nid] += 1.0 / (k + rank + 1)
        for rank, node in enumerate(kw):
            scores[node["id"]] += 1.0 / (k + rank + 1)
        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [nid for nid, _ in ordered[:top_k]]

    # ------------------------------------------------------------------ #
    # Semantic graph builder (MAGMA E_sem): link similar nodes by cosine
    # ------------------------------------------------------------------ #
    def build_semantic_edges(self, threshold: float | None = None, max_per_node: int = 8) -> int:
        """Link conceptually similar nodes by cosine. Kept sparse: only the top
        ``max_per_node`` most-similar partners per node, above ``threshold``."""
        thr = threshold if threshold is not None else self.semantic_threshold
        self._rebuild_vector_index()
        ids = list(self._vectors.keys())
        # Precompute similarity partners per node, keep top-K above threshold.
        partners: dict[str, list[tuple[str, float]]] = {nid: [] for nid in ids}
        with self._lock:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    sim = self._embedder.cosine(self._vectors[ids[i]], self._vectors[ids[j]])
                    if sim >= thr:
                        partners[ids[i]].append((ids[j], sim))
                        partners[ids[j]].append((ids[i], sim))
            added = 0
            for nid, plist in partners.items():
                plist.sort(key=lambda x: x[1], reverse=True)
                for other, sim in plist[:max_per_node]:
                    self.add_semantic_edge(nid, other, round(sim, 4))
                    added += 1
        return added


_multigraph: "MultiGraph | None" = None


def get_multigraph() -> MultiGraph:
    global _multigraph
    if _multigraph is None:
        _multigraph = MultiGraph()
    return _multigraph
