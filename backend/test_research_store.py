"""Tests for ResearchStore: notes dir layout, folder search index, promote, migration."""
import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

_temp_dirs: list[Path] = []


class _NoopLog:
    def record(self, *args, **kwargs):
        return {"id": "x"}


def make_fresh():
    """Isolated ResearchStore + KnowledgeGraph + ProjectStore backed by temp files."""
    from backend.core.research_store import ResearchStore
    from backend.memory.knowledge_graph import get_graph as _get_graph
    from backend.core.project_store import ProjectStore

    temp_dir = Path(tempfile.mkdtemp())
    _temp_dirs.append(temp_dir)
    research_file = temp_dir / "research.json"
    topics_dir = temp_dir / "topics"
    graph_file = temp_dir / "memory_graph.json"
    projects_dir = temp_dir / "projects"
    projects_file = temp_dir / "projects.json"
    research_file.write_text(json.dumps({"projects": []}), encoding="utf-8")
    graph_file.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    projects_file.write_text(json.dumps({"projects": []}), encoding="utf-8")

    config = {
        "data": {
            "storage_path": str(temp_dir / "data.json"),
            "projects_dir": str(projects_dir),
            "projects_path": str(projects_file),
            "research_path": str(research_file),
            "research_outputs_dir": str(topics_dir),
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
        kg = _get_graph()
        import backend.core.project_store as _ps_mod
        _ps_mod._instance = ProjectStore()

    return store, kg


@pytest.fixture(autouse=True)
def cleanup():
    import backend.core.research_store
    import backend.memory.knowledge_graph
    import backend.core.project_store
    noop = _NoopLog()
    with mock.patch("backend.core.research_store.get_operation_log", return_value=noop), \
         mock.patch("backend.core.project_store.get_operation_log", return_value=noop):
        backend.core.project_store._instance = None
        backend.memory.knowledge_graph._graph = None
        backend.core.research_store._instance = None
        yield
        backend.core.project_store._instance = None
        backend.memory.knowledge_graph._graph = None
        backend.core.research_store._instance = None
        while _temp_dirs:
            d = _temp_dirs.pop()
            if d.exists():
                import shutil
                shutil.rmtree(d, ignore_errors=True)


class TestNotes:
    def test_add_note_writes_to_notes_dir(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis", "academic")
        result = store.add_research_note("Anaphylaxis", "triggers", "# Triggers\nEpinephrine is key.")
        assert "error" not in result
        note_file = store.get_notes_dir(store._get_by_topic("Anaphylaxis")) / "triggers.md"
        assert note_file.is_file()
        assert "Epinephrine" in note_file.read_text(encoding="utf-8")

    def test_add_note_creates_graph_node_and_edge(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis", "academic")
        store.add_research_note("Anaphylaxis", "triggers.md", "content")
        research_node = kg.get_node_by_label("research:Anaphylaxis")
        assert research_node is not None
        assert research_node["type"] == "research"
        note_node = kg.get_node_by_label("triggers.md")
        assert note_node is not None
        edges = [e for e in kg.get_full_graph()["edges"]
                 if e["source"] == research_node["id"] and e["relation"] == "has_note"]
        assert len(edges) == 1

    def test_list_notes_and_missing_topic(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis", "academic")
        store.add_research_note("Anaphylaxis", "a.md", "one")
        store.add_research_note("Anaphylaxis", "b.md", "two")
        notes = store.list_research_notes("Anaphylaxis")
        assert [n["filename"] for n in notes] == ["a.md", "b.md"]
        assert store.add_research_note("Missing Topic", "a.md", "x").get("error")


class TestIndex:
    def test_search_hits_notes_reports_and_topic(self):
        store, kg = make_fresh()
        store.create_research("Deep Sea Mining Regulation", "domain",
                              questions=["What governs cobalt extraction?"])
        store.add_research_note("Deep Sea Mining Regulation", "ecosystem.md",
                                "Cobalt nodules sit on abyssal plains 4000m deep.")
        outputs = store.get_outputs_dir(store._get_by_topic("Deep Sea Mining Regulation"))
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "report.md").write_text("# Report\nCobalt extraction regulations remain contested.", encoding="utf-8")
        (outputs / "chart_1").mkdir(exist_ok=True)
        (outputs / "chart_1" / "index.html").write_text("<html></html>", encoding="utf-8")

        from backend.core.research_index import ResearchIndex
        with mock.patch("backend.core.research_index.get_research_store", return_value=store):
            idx = ResearchIndex()
            note_hits = idx.search("cobalt nodules")
            assert any(h["kind"] == "note" and h["filename"] == "ecosystem.md" for h in note_hits)
            report_hits = idx.search("regulations remain contested")
            assert any(h["kind"] == "report" for h in report_hits)
            topic_hits = idx.search("deep sea")
            assert any(h["kind"] == "topic" for h in topic_hits)
            artifact_hits = idx.search("chart_1")
            assert any(h["kind"] == "artifact" for h in artifact_hits)


class TestPromote:
    def test_promote_copies_files_and_archives(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis Pathophysiology", "academic")
        store.add_research_note("Anaphylaxis Pathophysiology", "triggers.md", "epinephrine first line")
        outputs = store.get_outputs_dir(store._get_by_topic("Anaphylaxis Pathophysiology"))
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "report.md").write_text("# report", encoding="utf-8")

        result = store.promote_to_project("Anaphylaxis Pathophysiology")
        assert "error" not in result, result

        from backend.core.project_store import get_project_store
        pstore = get_project_store()
        target = pstore.find_project_by_name("Anaphylaxis Pathophysiology")
        assert target is not None
        folder = pstore.projects_dir / target["folder"]
        assert (folder / "notes" / "triggers.md").is_file()
        assert (folder / "outputs" / "report.md").is_file()

        archived = store._get_by_topic("Anaphylaxis Pathophysiology")
        assert archived["status"] == "completed"
        assert archived["moved_to_project"] == "Anaphylaxis Pathophysiology"
        assert archived.get("promoted_at")

        edge = [e for e in kg.get_full_graph()["edges"] if e["relation"] == "promoted_to"]
        assert len(edge) == 1

    def test_promote_transfers_conversations(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis", "academic")
        store.link_conversation("Anaphylaxis", "conv_abc")
        result = store.promote_to_project("Anaphylaxis", "Anaphylaxis Project")
        assert "error" not in result
        from backend.core.project_store import get_project_store
        target = get_project_store().find_project_by_name("Anaphylaxis Project")
        assert "conv_abc" in target["conversation_ids"]

    def test_re_promote_blocked(self):
        store, kg = make_fresh()
        store.create_research("Anaphylaxis", "academic")
        first = store.promote_to_project("Anaphylaxis")
        assert "error" not in first
        second = store.promote_to_project("Anaphylaxis")
        assert "error" in second
        assert "already promoted" in second["error"].lower()

    def test_promote_name_collision_auto_suffix(self):
        store, kg = make_fresh()
        from backend.core.project_store import get_project_store
        pstore = get_project_store()
        pstore.create_project("Anaphylaxis")
        store.create_research("Anaphylaxis", "academic")
        result = store.promote_to_project("Anaphylaxis")
        assert "error" not in result
        assert result["project"] == "Anaphylaxis (Research 2)"


class TestMigration:
    def test_legacy_storage_moves_into_new_folder(self):
        store, kg = make_fresh()
        fake_repo = Path(tempfile.mkdtemp())
        _temp_dirs.append(fake_repo)
        (fake_repo / "research").mkdir(parents=True, exist_ok=True)
        (fake_repo / "research" / "legacy-topic" / "outputs").mkdir(parents=True, exist_ok=True)
        (fake_repo / "research" / "legacy-topic" / "outputs" / "report.md").write_text("x", encoding="utf-8")
        (fake_repo / "research.json").write_text(json.dumps({"projects": []}), encoding="utf-8")

        store._repo_root = lambda: fake_repo
        store._path.unlink(missing_ok=True)
        store._migrate_legacy_storage()

        assert not (fake_repo / "research.json").exists()
        assert store._path.is_file()
        assert (store._outputs_dir / "legacy-topic" / "outputs" / "report.md").is_file()

    def test_migration_skipped_when_new_location_populated(self):
        store, kg = make_fresh()
        store._save()
        fake_repo = Path(tempfile.mkdtemp())
        _temp_dirs.append(fake_repo)
        (fake_repo / "research.json").write_text(json.dumps({"projects": [{"id": "x"}]}), encoding="utf-8")

        store._repo_root = lambda: fake_repo
        store._migrate_legacy_storage()

        assert (fake_repo / "research.json").exists()
        loaded = json.loads(store._path.read_text(encoding="utf-8"))
        assert loaded["projects"] == []
