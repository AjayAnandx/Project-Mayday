"""Regression tests for the MAGMA MultiGraph data-structure layer.

Runs against a throwaway graph file (unique per test) and resets the
KnowledgeGraph + MultiGraph singletons so the REAL memory_graph.json is never
touched. Validates: typed edge subspaces, temporal backbone derivation, vector
index + RRF fusion, and sparse semantic-edge building.
"""
import os
import tempfile
import uuid

import backend.core.config as cfgmod
import backend.memory.knowledge_graph as kgmod
import backend.memory.multigraph as mgmod
from backend.memory.multigraph import (
    MultiGraph,
    SUBGRAPHS,
    get_multigraph,
)


def _temp_config(monkeypatch):
    tmp = os.path.join(tempfile.gettempdir(), f"mayday_test_graph_{uuid.uuid4().hex}.json")
    cfg = cfgmod.load_config()
    cfg["memory"] = {"graph_path": tmp}
    # KnowledgeGraph imported load_config directly, so patch the reference it uses.
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    kgmod._graph = None          # force reload from tmp path
    mgmod._multigraph = None     # force fresh MultiGraph
    return mgmod


def test_typed_edges_and_subgraph_filtering(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    kg = mg._kg
    assert len(kg._nodes) == 0, "test graph must start empty"
    a = kg.add_node("event", "TCS exam on Aug 10")
    b = kg.add_node("event", "Missed exam prep due to illness")
    c = kg.add_node("person", "Arjun")

    mg.add_causal_edge(a, b)
    mg.add_entity_edge(b, c)

    assert len(mg.edges_by_subgraph("causal")) == 1
    assert len(mg.edges_by_subgraph("entity")) == 1
    assert all(e["properties"]["subgraph"] in SUBGRAPHS for e in kg._edges)
    for nid in (a, b, c):
        kg.remove_node(nid)


def test_temporal_backbone_derived_and_idempotent(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    kg = mg._kg
    ids = [kg.add_node("event", f"event {i}") for i in range(4)]

    mg.ensure_temporal_backbone()
    first = len(mg.edges_by_subgraph("temporal"))
    assert first == 3, first  # n-1 edges for n nodes

    mg.ensure_temporal_backbone()  # idempotent
    assert len(mg.edges_by_subgraph("temporal")) == 3

    chain = mg.temporal_chain()
    assert chain[0] == (ids[0], ids[1])
    assert chain[-1] == (ids[-2], ids[-1])
    for nid in ids:
        kg.remove_node(nid)


def test_vector_search_and_rrf(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    kg = mg._kg
    a = kg.add_node("concept", "machine learning model training")
    b = kg.add_node("concept", "neural network optimization")
    c = kg.add_node("concept", "dentist appointment schedule")
    mg._rebuild_vector_index()

    res = mg.vector_search("model training neural", top_k=3)
    assert res and res[0][0] in (a, b)
    anchors = mg.rrf_anchors("neural network training", top_k=3)
    assert set(anchors[:2]) <= {a, b}

    for nid in (a, b, c):
        kg.remove_node(nid)


def test_semantic_edges_sparse(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    kg = mg._kg
    for i in range(10):
        kg.add_node("concept", f"shared topic word number {i}")
    added = mg.build_semantic_edges(threshold=0.4, max_per_node=3)
    # sparse: at most 3 per node across 10 nodes => <= 30 directed edges
    assert 0 <= added <= 30, added
    for nid in list(kg._nodes.keys()):
        kg.remove_node(nid)
