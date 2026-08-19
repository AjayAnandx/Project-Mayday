"""Regression tests for the MAGMA Query Process (backend.memory.retrieval)."""
import os
import tempfile
import uuid

import backend.core.config as cfgmod
import backend.memory.knowledge_graph as kgmod
import backend.memory.multigraph as mgmod
from backend.memory.retrieval import detect_intent, magma_retrieve


def _temp_config(monkeypatch):
    tmp = os.path.join(tempfile.gettempdir(), f"mayday_test_graph_{uuid.uuid4().hex}.json")
    cfg = cfgmod.load_config()
    cfg["memory"] = {"graph_path": tmp}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    kgmod._graph = None
    mgmod._multigraph = None
    return mgmod


def test_intent_detection():
    assert detect_intent("why did I miss the exam") == "WHY"
    assert detect_intent("when is the exam") == "WHEN"
    assert detect_intent("tell me about my brother") == "ENTITY"
    assert detect_intent("what should I study") == "SEMANTIC"


def test_retrieve_empty_graph_returns_empty(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    assert len(mg._kg._nodes) == 0
    out = magma_retrieve("anything at all", token_budget=500)
    assert out == ""  # no anchors -> empty, no crash


def test_retrieve_intent_biased_and_budgeted(monkeypatch):
    mgmod = _temp_config(monkeypatch)
    mg = mgmod.get_multigraph()
    kg = mg._kg
    exam = kg.add_node("event", "TCS exam on Aug 10 2026")
    ill = kg.add_node("event", "Missed exam prep due to illness")
    arjun = kg.add_node("person", "Arjun")
    mg.add_causal_edge(ill, exam)
    mg.add_entity_edge(exam, arjun)
    mg.build_semantic_edges(threshold=0.4, max_per_node=3)

    out = magma_retrieve("why did I miss the exam", token_budget=2000)
    assert out.strip(), "expected a non-empty provenance block"
    # provenance scaffolding present
    assert "<t:" in out
    assert "[event]" in out

    # token budget is respected (hard cap + truncation marker when exceeded)
    small = magma_retrieve("why did I miss the exam", token_budget=40)
    assert "truncated" in small
    assert len(small) <= 120  # 40 budget + slack for truncation message

    for nid in (exam, ill, arjun):
        kg.remove_node(nid)
