"""Tests for duplicate guards: research/project notes, project tasks, fuzzy name matching."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

_temp_dirs: list[Path] = []


class _NoopLog:
    def record(self, *args, **kwargs):
        return {"id": "x"}


@pytest.fixture(autouse=True)
def cleanup():
    from backend.core.research_store import _instance as _r
    from backend.memory.knowledge_graph import _graph
    from backend.core.project_store import _instance as _p
    noop = _NoopLog()
    with mock.patch("backend.core.research_store.get_operation_log", return_value=noop), \
         mock.patch("backend.core.project_store.get_operation_log", return_value=noop):
        globals()["_r"], globals()["_p"], globals()["_g"] = _r, _p, _graph
        yield
        import backend.core.research_store
        import backend.memory.knowledge_graph
        import backend.core.project_store
        backend.core.project_store._instance = None
        backend.memory.knowledge_graph._graph = None
        backend.core.research_store._instance = None
        while _temp_dirs:
            d = _temp_dirs.pop()
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)


def make_fresh():
    """Isolated ResearchStore + ProjectStore backed by temp files."""
    from backend.core.research_store import ResearchStore
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
         mock.patch("backend.core.project_store.load_config", return_value=config):
        store = ResearchStore()
        import backend.core.project_store as _ps_mod
        _ps_mod._instance = ProjectStore()
    return store


def make_project_store():
    """Isolated ProjectStore backed by a fresh temp dir (never touches real config)."""
    from backend.core.project_store import ProjectStore

    temp_dir = Path(tempfile.mkdtemp())
    _temp_dirs.append(temp_dir)
    graph_file = temp_dir / "memory_graph.json"
    projects_dir = temp_dir / "projects"
    projects_file = temp_dir / "projects.json"
    graph_file.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    projects_file.write_text(json.dumps({"projects": []}), encoding="utf-8")

    config = {
        "data": {
            "projects_dir": str(projects_dir),
            "projects_path": str(projects_file),
        },
        "memory": {"graph_path": str(graph_file)},
    }

    import backend.core.project_store as _ps_mod
    with mock.patch("backend.core.project_store.load_config", return_value=config), \
         mock.patch("backend.memory.knowledge_graph.load_config", return_value=config):
        _ps_mod._instance = None
        inst = ProjectStore()
        _ps_mod._instance = inst
        return inst


def test_research_note_duplicate_blocked():
    store = make_fresh()
    store.create_research("Test Topic", "market")
    first = store.add_research_note("Test Topic", "findings.md", "original content")
    assert "error" not in first

    dup = store.add_research_note("Test Topic", "findings.md", "clobbered content")
    assert "error" in dup and "force=True" in dup["error"]

    notes_dir = store.get_notes_dir(store._find_by_topic("Test Topic"))
    assert (notes_dir / "findings.md").read_text(encoding="utf-8") == "original content"

    forced = store.add_research_note("Test Topic", "findings.md", "new content", force=True)
    assert "error" not in forced
    assert (notes_dir / "findings.md").read_text(encoding="utf-8") == "new content"


def test_project_note_duplicate_blocked():
    pstore = make_project_store()
    pstore.create_project("Website")
    from backend.functions.project_functions import add_project_note

    first = add_project_note(filename="plan.md", content="v1", name="Website")
    assert "already exists" not in first

    dup = add_project_note(filename="plan.md", content="v2", name="Website")
    assert "already exists" in dup and "force=True" in dup

    folder = pstore.projects_dir / "website"
    assert (folder / "plan.md").read_text(encoding="utf-8") == "v1"

    forced = add_project_note(filename="plan.md", content="v3", name="Website", force=True)
    assert "already exists" not in forced
    assert (folder / "plan.md").read_text(encoding="utf-8") == "v3"


def test_project_task_duplicate_blocked():
    pstore = make_project_store()
    proj = pstore.create_project("TaskApp")

    first = pstore.add_task(proj["id"], "Build Login", "build")
    assert "error" not in first

    dup = pstore.add_task(proj["id"], "Build Login", "build")
    assert "error" in dup and "force=True" in dup["error"]

    dup_lower = pstore.add_task(proj["id"], "build login", "general")
    assert "error" in dup_lower

    forced = pstore.add_task(proj["id"], "Build Login", "build", force=True)
    assert "error" not in forced
    assert len(pstore.list_tasks(proj["id"])) == 2


def test_project_fuzzy_near_duplicate_blocked():
    pstore = make_project_store()
    pstore.create_project("QuantumScripts Competitor Analysis")

    dup = pstore.create_project("QuantumScripts Competitive Analysis")
    assert "error" in dup and "similar project already exists" in dup["error"]

    ok = pstore.create_project("Totally Different Name")
    assert "error" not in ok


def test_research_fuzzy_near_duplicate_blocked():
    store = make_fresh()
    store.create_research("QuantumScripts Competitor Analysis", "market")

    dup = store.create_research("QuantumScripts Competitive Analysis", "market")
    assert "error" in dup and "similar research topic already exists" in dup["error"]

    ok = store.create_research("Totally Different Topic", "market")
    assert "error" not in ok


def test_exact_duplicates_still_blocked():
    store = make_fresh()
    store.create_research("Exact Topic", "market")
    dup = store.create_research("Exact Topic", "market")
    assert "error" in dup and "already exists" in dup["error"]

    pstore = make_project_store()
    pstore.create_project("Exact Project")
    dup_p = pstore.create_project("Exact Project")
    assert "error" in dup_p and "already exists" in dup_p["error"]


def test_research_and_project_exact_crosscheck_not_blocked():
    """A project and a research topic with the same name must not block each other."""
    store = make_fresh()
    store.create_research("Shared Name", "market")
    pstore = make_project_store()
    proj = pstore.create_project("Shared Name")
    assert "error" not in proj