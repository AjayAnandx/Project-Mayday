"""Crash-safety of KnowledgeGraph persistence (atomic save, corrupt-file recovery)."""
import json
from unittest.mock import patch

from backend.memory.knowledge_graph import KnowledgeGraph


def _make(tmp_path):
    cfg = {"memory": {"graph_path": str(tmp_path / "memory_graph.json")}}
    with patch("backend.memory.knowledge_graph.load_config", return_value=cfg):
        return KnowledgeGraph()


def test_save_is_atomic_and_keeps_backup(tmp_path):
    g = _make(tmp_path)
    g.add_node("concept", "first")
    g.add_node("concept", "second")
    main = tmp_path / "memory_graph.json"
    assert len(json.loads(main.read_text(encoding="utf-8"))["nodes"]) == 2
    assert (tmp_path / "memory_graph.json.bak").exists()
    assert not (tmp_path / "memory_graph.json.tmp").exists()


def test_corrupt_file_is_kept_and_restored_from_backup(tmp_path):
    g = _make(tmp_path)
    g.add_node("concept", "alpha")
    g.add_node("concept", "beta")  # .bak now holds {alpha}
    main = tmp_path / "memory_graph.json"
    main.write_text('{"nodes": [ truncated', encoding="utf-8")

    g2 = _make(tmp_path)
    labels = {n["label"] for n in g2._nodes.values()}
    assert labels == {"alpha"}
    corrupt = list(tmp_path.glob("memory_graph.corrupt-*.json"))
    assert corrupt and "truncated" in corrupt[0].read_text(encoding="utf-8")


def test_corrupt_without_backup_starts_empty_but_keeps_copy(tmp_path):
    main = tmp_path / "memory_graph.json"
    main.write_text("not json", encoding="utf-8")
    g = _make(tmp_path)
    assert g._nodes == {}
    assert list(tmp_path.glob("memory_graph.corrupt-*.json"))
