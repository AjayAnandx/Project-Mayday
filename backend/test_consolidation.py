"""Regression tests for MAGMA slow-path consolidation (backend.memory.consolidation)."""
import os
import tempfile
import uuid

import backend.core.config as cfgmod
import backend.core.user_awareness as uamod
import backend.memory.consolidation as consmod
import backend.memory.knowledge_graph as kgmod
import backend.memory.multigraph as mgmod
from backend.memory.consolidation import ConsolidationWorker, get_consolidator


def _setup(monkeypatch, awareness_enabled=False):
    tmp = os.path.join(tempfile.gettempdir(), f"mayday_test_graph_{uuid.uuid4().hex}.json")
    cfg = cfgmod.load_config()
    cfg["memory"] = {"graph_path": tmp}
    # Isolate the awareness store so consolidation's mirror never touches the
    # real user_profile.json (and defaults to disabled unless a test opts in).
    cfg["awareness"] = {
        "enabled": awareness_enabled,
        "profile_path": os.path.join(tempfile.gettempdir(), f"mayday_test_profile_{uuid.uuid4().hex}.json"),
        "consented_tiers": ["T0"],
    }
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(uamod, "load_config", lambda: cfg)
    monkeypatch.setattr(consmod, "load_config", lambda: cfg)
    kgmod._graph = None
    mgmod._multigraph = None
    uamod.reset_awareness_store()
    return mgmod.get_multigraph()


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def chat(self, messages, stream=False, tools=None):
        return self._payload

    def extract_response(self, resp):
        return (resp, None)


def test_queue_and_parse(monkeypatch):
    mg = _setup(monkeypatch)
    kg = mg._kg
    a = kg.add_node("event", "Event: TCS exam")
    b = kg.add_node("event", "Event: illness")
    c = kg.add_node("person", "Arjun")
    w = ConsolidationWorker()
    n = w.enqueue_unconsolidated(limit=10)
    assert n == 3
    # already-flagged nodes are skipped (clear queue so only flag logic is tested)
    w._queue.clear()
    kg._nodes[a].setdefault("properties", {})["consolidated"] = True
    assert w.enqueue_unconsolidated(limit=10) == 2


def test_process_one_adds_typed_edges(monkeypatch):
    mg = _setup(monkeypatch)
    kg = mg._kg
    exam = kg.add_node("event", "Event: TCS exam")
    ill = kg.add_node("event", "Event: illness")
    arjun = kg.add_node("person", "Arjun")
    payload = (
        '{"causal":[{"source":"Event: illness","target":"Event: TCS exam",'
        '"relation":"causes"}],'
        '"entity":[{"event":"Event: TCS exam","entity":"Arjun","kind":"person"},'
        '{"event":"Event: TCS exam","entity":"Mom","kind":"person"}]}'
    )
    w = ConsolidationWorker()
    w.enqueue(exam)
    ok = w.process_one(worker_client=_FakeClient(payload))
    assert ok is True
    # causal edge present
    causal = [e for e in kg._edges if e.get("properties", {}).get("subgraph") == "causal"]
    assert len(causal) == 1
    assert causal[0]["source"] == ill and causal[0]["target"] == exam
    # entity edge to existing Arjun + auto-created Mom node
    entity = [e for e in kg._edges if e.get("properties", {}).get("subgraph") == "entity"]
    assert len(entity) == 2
    labels = sorted(kg._nodes[e["target"]]["label"] for e in entity)
    assert labels == ["Arjun", "Mom"]
    # focal node flagged consolidated
    assert kg._nodes[exam].get("properties", {}).get("consolidated") is True
    # auto-created Mom node is also flagged so it isn't re-queued
    mom = [nid for nid, n in kg._nodes.items() if n["label"] == "Mom"][0]
    assert kg._nodes[mom].get("properties", {}).get("consolidated") is True


def test_process_one_idempotent(monkeypatch):
    mg = _setup(monkeypatch)
    kg = mg._kg
    a = kg.add_node("event", "Event: standalone")
    kg._nodes[a].setdefault("properties", {})["consolidated"] = True
    w = ConsolidationWorker()
    w.enqueue(a)
    # popping a consolidated node is a no-op and removes from queue
    assert w.process_one(worker_client=_FakeClient("{}")) is True
    assert w.pending() == 0


def test_bad_json_does_not_crash(monkeypatch):
    mg = _setup(monkeypatch)
    kg = mg._kg
    a = kg.add_node("event", "Event: noisy")
    w = ConsolidationWorker()
    w.enqueue(a)
    assert w.process_one(worker_client=_FakeClient("not json at all")) is True
    assert kg._nodes[a].get("properties", {}).get("consolidated") is True


def test_junk_belief_label_rejected(monkeypatch):
    # The model can regurgitate an internal mirror label (belief:identity:ajay)
    # as an "entity". It must be dropped — no node created, no edge wired.
    mg = _setup(monkeypatch)
    kg = mg._kg
    exam = kg.add_node("event", "Event: TCS exam")
    payload = (
        '{"causal":[{"source":"Event: TCS exam","target":"belief:identity:ajay",'
        '"relation":"causes"}],'
        '"entity":[{"event":"Event: TCS exam","entity":"belief:identity:ajay","kind":"person"}]}'
    )
    w = ConsolidationWorker()
    w.enqueue(exam)
    assert w.process_one(worker_client=_FakeClient(payload)) is True
    assert all(not n["label"].startswith("belief:") for n in kg._nodes.values())
    causal = [e for e in kg._edges if e.get("properties", {}).get("subgraph") == "causal"]
    assert causal == []
    assert kg._nodes[exam].get("properties", {}).get("consolidated") is True


def test_awareness_mirror_gated_and_validated(monkeypatch):
    # With awareness enabled: a genuinely person-like entity is mirrored into
    # the world model, but a junk belief: label is NOT.
    mg = _setup(monkeypatch, awareness_enabled=True)
    kg = mg._kg
    exam = kg.add_node("event", "Event: TCS exam")
    payload = (
        '{"causal":[],"entity":['
        '{"event":"Event: TCS exam","entity":"Mom","kind":"person"},'
        '{"event":"Event: TCS exam","entity":"belief:identity:ajay","kind":"person"}]}'
    )
    w = ConsolidationWorker()
    w.enqueue(exam)
    assert w.process_one(worker_client=_FakeClient(payload)) is True
    store = uamod.get_awareness_store()
    vals = [b["value"] for b in store.list_beliefs("relations")]
    assert "Mom" in vals
    assert not any(v.startswith("belief:") for v in vals)
