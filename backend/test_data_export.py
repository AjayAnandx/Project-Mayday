"""Tests for the CSV dataset export workflow (chat-driven visualization)."""
import csv
import json
import tempfile
from pathlib import Path
from unittest import mock

from backend.core.research_store import ResearchStore
from backend.memory.knowledge_graph import get_graph as _get_graph
from backend.core.project_store import ProjectStore


def _make_fresh():
    temp_dir = Path(tempfile.mkdtemp())
    research_file = temp_dir / "research.json"
    topics_dir = temp_dir / "topics"
    graph_file = temp_dir / "memory_graph.json"
    projects_file = temp_dir / "projects.json"
    research_file.write_text(json.dumps({"projects": []}), encoding="utf-8")
    graph_file.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    projects_file.write_text(json.dumps({"projects": []}), encoding="utf-8")

    config = {
        "data": {
            "storage_path": str(temp_dir / "data.json"),
            "projects_dir": str(temp_dir / "projects"),
            "projects_path": str(projects_file),
            "research_path": str(research_file),
            "research_outputs_dir": str(topics_dir),
            "uploads_dir": str(temp_dir / "uploads"),
        },
        "memory": {"graph_path": str(graph_file)},
        "server": {"host": "0.0.0.0", "port": 8770},
        "personality": {"default_tone": "neutral", "traits": [], "rules": []},
        "mcp": {"servers": {}},
    }

    with mock.patch("backend.core.research_store.load_config", return_value=config), \
         mock.patch("backend.memory.knowledge_graph.load_config", return_value=config), \
         mock.patch("backend.core.project_store.load_config", return_value=config), \
         mock.patch.object(ResearchStore, "_repo_root", return_value=temp_dir):
        store = ResearchStore()
        _get_graph()
        import backend.core.project_store as _ps_mod
        _ps_mod._instance = ProjectStore()

    return store, config, temp_dir


def test_export_writes_csv_and_reconstructs_rows():
    store, config, temp_dir = _make_fresh()
    # Patch the module-level singletons used by the export tool.
    import backend.functions.data_export as de
    import backend.core.research_store as rs_mod
    rs_mod._instance = store

    topic = "ML vs AI Engineer Growth 2020-2026"
    store.create_research(topic, "market", 2)
    # Simulate batch_add_data_points label encoding: "series | time".
    store.add_data_point(topic, "ML Engineer | 2020", "12000", "postings")
    store.add_data_point(topic, "ML Engineer | 2026", "31000", "postings")
    store.add_data_point(topic, "AI Engineer | 2020", "8000", "postings")
    store.add_data_point(topic, "AI Engineer | 2026", "45000", "postings")

    with mock.patch.object(de, "load_config", return_value=config), \
         mock.patch.object(de, "get_research_store", return_value=store):
        result_json = de.export_research_dataset(topic)
        result = json.loads(result_json)

    assert "error" not in result, result
    assert result["files"][0]["format"] == "csv"
    file_id = result["files"][0]["file_id"]
    csv_path = temp_dir / "uploads" / file_id
    assert csv_path.exists()

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    # Reverse-encoding: category/period recovered from "series | time".
    by_key = {(r["category"], r["period"]): r["value"] for r in rows}
    assert by_key[("ML Engineer", "2020")] == "12000"
    assert by_key[("AI Engineer", "2026")] == "45000"
    assert all(r["unit"] == "postings" for r in rows)


def test_export_errors_without_data_points():
    store, config, _ = _make_fresh()
    import backend.functions.data_export as de
    import backend.core.research_store as rs_mod
    rs_mod._instance = store

    topic = "Empty Topic No Data"
    store.create_research(topic, "market", 2)
    with mock.patch.object(de, "load_config", return_value=config), \
         mock.patch.object(de, "get_research_store", return_value=store):
        result = json.loads(de.export_research_dataset(topic))
    assert "error" in result


def test_export_appears_in_imported_files_and_round_trips():
    store, config, temp_dir = _make_fresh()
    import backend.functions.data_export as de
    import backend.functions.data_import as di
    import backend.core.research_store as rs_mod
    rs_mod._instance = store

    topic = "Roundtrip Topic"
    store.create_research(topic, "market", 2)
    store.add_data_point(topic, "Series A | 2021", "5", "")
    store.add_data_point(topic, "Series B | 2021", "9", "")

    patch = mock.patch.object(de, "load_config", return_value=config)
    patch.start()
    patch_di = mock.patch.object(di, "load_config", return_value=config)
    patch_di.start()
    try:
        result = json.loads(de.export_research_dataset(topic))
        file_id = result["files"][0]["file_id"]
        files = di.list_imported_files()
        assert any(f["file_id"] == file_id for f in files)

        # Re-import the exported CSV back into the topic (the "upload" step).
        import_result = di.import_data_to_store(file_id, store_type="research", topic=topic)
        assert "error" not in import_result, import_result
        assert import_result["data_points"] == 2
    finally:
        patch.stop()
        patch_di.stop()
