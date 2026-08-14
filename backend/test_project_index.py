"""Tests for ProjectIndex: content + filename search across project folders."""
import tempfile
from pathlib import Path
from unittest import mock

import pytest

_temp_dirs: list[Path] = []


def make_index():
    from backend.core.project_index import ProjectIndex
    temp_dir = Path(tempfile.mkdtemp())
    _temp_dirs.append(temp_dir)
    projects_dir = temp_dir / "projects"
    (projects_dir / "my-app").mkdir(parents=True)
    (projects_dir / "my-app" / "notes").mkdir()
    (projects_dir / "my-app" / "notes" / "meeting.md").write_text(
        "Quarterly planning notes about the quantumscripts roadmap", encoding="utf-8"
    )
    (projects_dir / "my-app" / "README.md").write_text(
        "My app uses the epsilon retrieval engine", encoding="utf-8"
    )
    (projects_dir / "my-app" / "src").mkdir()
    (projects_dir / "my-app" / "src" / "utils.ts").write_text(
        "export function buildIndex() { return nebulous; }", encoding="utf-8"
    )
    (projects_dir / "my-app" / "logo.png").write_bytes(b"\x89PNG\x0d\x0a")
    (projects_dir / "my-app" / "node_modules").mkdir()
    (projects_dir / "my-app" / "node_modules" / "junk.js").write_text(
        "zqybulclisk ipqkzxjvfl", encoding="utf-8"
    )
    (projects_dir / "my-app" / ".git").mkdir()
    (projects_dir / "my-app" / ".git" / "config").write_text(
        "zqybulclisk ipqkzxjvfl", encoding="utf-8"
    )
    (projects_dir / "second-app").mkdir()
    (projects_dir / "second-app" / "plan.md").write_text(
        "Brainstorm: goblin mode for calendar UX", encoding="utf-8"
    )
    cfg = {"data": {"projects_dir": str(projects_dir)}}
    with mock.patch("backend.core.project_index.load_config", return_value=cfg):
        idx = ProjectIndex()
    return idx, projects_dir


@pytest.fixture(autouse=True)
def cleanup():
    yield
    while _temp_dirs:
        d = _temp_dirs.pop()
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)


def test_search_content():
    idx, _projects = make_index()
    results = idx.search("quantumscripts")
    assert any(r["filename"] == "meeting.md" for r in results)


def test_search_filename():
    idx, _projects = make_index()
    results = idx.search("meeting.md")
    assert results and results[0]["filename"] == "meeting.md"


def test_search_relative_path_and_folder():
    idx, _projects = make_index()
    results = idx.search("utils.ts")
    assert results
    r = results[0]
    assert r["rel_path"] == "my-app/src/utils.ts"
    assert r["folder"] == "my-app"


def test_skips_node_modules_and_git():
    idx, _projects = make_index()
    assert idx.search("zqybulclisk") == []


def test_non_text_file_indexed_by_filename():
    idx, _projects = make_index()
    results = idx.search("logo")
    assert any(r["filename"] == "logo.png" for r in results)


def test_search_other_project():
    idx, _projects = make_index()
    results = idx.search("plan.md")
    assert results and results[0]["folder"] == "second-app"


def test_no_query_returns_empty():
    idx, _projects = make_index()
    assert idx.search("") == []