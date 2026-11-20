"""Brain V2 P2: SQLite store + KnowledgeGraph adapter (backend=sqlite)."""
import json
from unittest.mock import patch

from backend.brain.store import BrainStore
from backend.memory.knowledge_graph import KnowledgeGraph


def _kg(tmp_path, backend="sqlite"):
    cfg = {"memory": {"graph_path": str(tmp_path / "memory_graph.json"),
                      "db_path": str(tmp_path / "brain.db"), "backend": backend}}
    with patch("backend.memory.knowledge_graph.load_config", return_value=cfg):
        return KnowledgeGraph()


def _seed_json(tmp_path):
    g = {"nodes": [{"id": "a", "type": "person", "label": "Kiran Rao", "properties": {"city": "Bengaluru"}},
                   {"id": "b", "type": "concept", "label": "college friend", "properties": {}}],
         "edges": [{"id": "e1", "source": "a", "target": "b", "relation": "is", "properties": {}}]}
    (tmp_path / "memory_graph.json").write_text(json.dumps(g), encoding="utf-8")
    return g


def test_migrates_json_once_and_leaves_it_untouched(tmp_path):
    g = _seed_json(tmp_path)
    before = (tmp_path / "memory_graph.json").read_bytes()
    kg = _kg(tmp_path)
    assert kg.get_node_by_label("Kiran Rao")["properties"]["city"] == "Bengaluru"
    assert kg.get_subgraph("a")["edges"][0]["relation"] == "is"
    assert (tmp_path / "memory_graph.json").read_bytes() == before
    # second start: store already filled, JSON changes are NOT re-imported
    g["nodes"].append({"id": "c", "type": "concept", "label": "late json edit", "properties": {}})
    (tmp_path / "memory_graph.json").write_text(json.dumps(g), encoding="utf-8")
    kg2 = _kg(tmp_path)
    assert kg2.get_node_by_label("late json edit") is None
    assert len(kg2._nodes) == 2


def test_writes_persist_across_restart(tmp_path):
    kg = _kg(tmp_path)
    a = kg.add_node("person", "Meera", {"relation": "sister"})
    b = kg.add_node("concept", "March 14")
    kg.add_edge(a, b, "birthday")
    node = kg.get_node(a)
    node["properties"]["city"] = "Chennai"      # in-place mutation + _save(), as callers do
    kg._save()
    kg.remove_node(b)
    kg2 = _kg(tmp_path)
    assert kg2.get_node(a)["properties"] == {"relation": "sister", "city": "Chennai", "status": "active"}
    assert kg2.get_node(b) is None and kg2._edges == []
    assert kg2.search("meera")[0]["id"] == a
    assert not (tmp_path / "memory_graph.json").exists()   # sqlite never writes the JSON


def test_sync_writes_only_changes(tmp_path):
    s = BrainStore(tmp_path / "b.db")
    nodes = {str(i): {"id": str(i), "type": "concept", "label": f"n{i}", "properties": {}} for i in range(50)}
    assert s.sync(nodes, [])["nodes"] == 50
    assert s.sync(nodes, []) == {"nodes": 0, "edges": 0}
    nodes["7"]["label"] = "changed"
    del nodes["8"]
    assert s.sync(nodes, [])["nodes"] == 2
    s2 = BrainStore(tmp_path / "b.db")
    loaded, _ = s2.load()
    assert loaded["7"]["label"] == "changed" and "8" not in loaded and len(loaded) == 49


def test_fts_bm25_prefix(tmp_path):
    s = BrainStore(tmp_path / "b.db")
    s.sync({"x": {"id": "x", "type": "concept", "label": "Coorg trip",
                  "properties": {"note": "moved to December"}},
            "y": {"id": "y", "type": "concept", "label": "gym routine", "properties": {}}}, [])
    ids = [i for i, _ in s.fts_search("trips in december")]
    assert ids and ids[0] == "x" and "y" not in ids


def test_backup_and_export(tmp_path):
    kg = _kg(tmp_path)
    kg.add_node("concept", "alpha")
    dest = kg._store.backup(tmp_path / "copy.db")
    assert BrainStore(dest).counts()["nodes"] == 1
    out = kg.export_json(tmp_path / "export.json")
    assert json.loads(out.read_text(encoding="utf-8"))["nodes"][0]["label"] == "alpha"


def test_json_backend_still_default(tmp_path):
    cfg = {"memory": {"graph_path": str(tmp_path / "memory_graph.json")}}
    with patch("backend.memory.knowledge_graph.load_config", return_value=cfg):
        kg = KnowledgeGraph()
    kg.add_node("concept", "x")
    assert kg._store is None and (tmp_path / "memory_graph.json").exists()


def test_cleanup_applies_to_sqlite_store(tmp_path, monkeypatch):
    import backend.memory.cleanup_graph as cg
    _seed_json(tmp_path)
    kg = _kg(tmp_path)                      # migrates into brain.db
    kg.add_node("email", "email:123")
    cfg = {"memory": {"graph_path": str(tmp_path / "memory_graph.json"),
                      "db_path": str(tmp_path / "brain.db"), "backend": "sqlite"},
           "data": {"projects_path": str(tmp_path / "none.json")}}
    monkeypatch.setattr("backend.core.config.load_config", lambda: cfg)
    monkeypatch.setattr(cg, "_backend_running", lambda: [])
    assert cg.main(["--apply"]) == 0
    kg2 = _kg(tmp_path)
    assert kg2.get_node_by_label("email:123") is None and kg2.get_node_by_label("Kiran Rao")
    assert list(tmp_path.glob("brain.pre-cleanup-*.db"))
