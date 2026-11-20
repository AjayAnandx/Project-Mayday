"""Test-wide safety net: no test may write the live knowledge graph.

Before this existed, tests that went through ProjectStore/ResearchStore synced
nodes into the real memory_graph.json (≈600 "project:Seed…/Bench…" nodes).
Every test now gets its own temp graph; tests that set up their own isolation
(monkeypatching load_config, assigning _graph) still override this.
A session check fails the run if the live file changed anyway.
"""
import hashlib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LIVE = _ROOT / "memory_graph.json"
_LIVE_DB = _ROOT / "brain.db"


def _digest():
    return tuple(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                 for p in (_LIVE, _LIVE_DB))


@pytest.fixture(autouse=True)
def _isolated_knowledge_graph(tmp_path, monkeypatch):
    import backend.core.config as cfgmod
    import backend.memory.knowledge_graph as kgmod
    import backend.memory.multigraph as mgmod

    cfg = dict(cfgmod.load_config())
    cfg["memory"] = {**cfg.get("memory", {}), "graph_path": str(tmp_path / "memory_graph.json"),
                     "db_path": str(tmp_path / "brain.db")}
    # MAYDAY_TEST_BACKEND=sqlite runs every graph test on the SQLite store.
    import os
    if os.environ.get("MAYDAY_TEST_BACKEND"):
        cfg["memory"]["backend"] = os.environ["MAYDAY_TEST_BACKEND"]
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    # No real Ollama embedding calls from tests (tests that want them fake _post).
    import backend.brain.context as ctxmod
    bcfg = dict(cfg.get("brain", {}) or {})
    bcfg["recall"] = {**(bcfg.get("recall", {}) or {}), "use_embeddings": False}
    monkeypatch.setattr(ctxmod, "load_config", lambda: {**cfg, "brain": bcfg})
    monkeypatch.setattr(kgmod, "_graph", None)
    monkeypatch.setattr(mgmod, "_multigraph", None)
    # Brain V3: no real model calls and no stray background threads from tests. Code that needs
    # a model gets a null model unless the test passes its own fake; transition handling runs
    # only when a test calls it directly.
    import backend.assistant.llm_client as llmmod
    monkeypatch.setattr(llmmod, "get_worker_client", lambda: _NullLLM())
    import backend.brain.generators as genmod
    monkeypatch.setattr(genmod, "on_transition_async", lambda: None)
    import backend.brain.lessons as lesmod
    monkeypatch.setattr(lesmod.LessonQueue, "process_async", lambda self: None)
    # Conversations / todos: a temp store, so brain code under test never reads (or writes) the
    # user's real conversations/ folder and data.json.
    import backend.core.data_store as dsmod
    ds_cfg = {**cfg, "data": {**cfg.get("data", {}), "storage_path": str(tmp_path / "data.json")}}
    monkeypatch.setattr(dsmod, "load_config", lambda: ds_cfg)
    _orig_init_dir = dsmod.DataStore._init_conv_dir

    def _tmp_conv_dir(self):
        self._conv_dir = tmp_path / "conversations"
        self._conv_idx = {}
        return _orig_init_dir(self)
    monkeypatch.setattr(dsmod.DataStore, "_init_conv_dir", _tmp_conv_dir)
    monkeypatch.setattr(dsmod, "_store", None)
    yield


class _NullLLM:
    """Stands in for the worker model in tests: always answers with an empty JSON object."""

    def chat(self, *a, **k):
        return {"content": "{}"}

    def extract_response(self, resp):
        return "{}", None


@pytest.fixture(autouse=True, scope="session")
def _live_graph_untouched():
    before = _digest()
    yield
    after = _digest()
    if before != after:
        pytest.fail("a test modified the live memory_graph.json / brain.db", pytrace=False)
