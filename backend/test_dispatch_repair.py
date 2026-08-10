"""Tests for LLM tool-call argument repair in dispatch_call.

Covers the three production failures:
- create_project(description=...)  → unexpected kwarg
- add_project_note() without filename
- create_research() without type
Plus alias mapping, unknown-kwarg stripping, and actionable error messages.
All stores mocked — zero repo pollution.
"""
import asyncio
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

from backend.assistant.function_registry import (
    dispatch_call,
    _repair_arguments,
    _expected_params,
)

_temp_dirs: list[Path] = []


class _NoopLog:
    def record(self, *args, **kwargs):
        return {"id": "x"}


class _FakeGraph:
    def add_node(self, *args, **kwargs):
        return "node_x"

    def get_node_by_label(self, label):
        return {"id": "node_x", "type": "concept"}

    def add_edge_if_missing(self, *args, **kwargs):
        return None


class _FakeProjectStore:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        _temp_dirs.append(self.root)
        self.projects_dir = self.root
        self.projects = []
        self.project_dir = None

    def create_project(self, name, tasks=None, description=""):
        if any(p["name"].lower() == name.lower() for p in self.projects):
            return {"error": f"Project '{name}' already exists. Use resume_project."}
        folder = name.lower().replace(" ", "-")
        project = {
            "id": "proj_x", "name": name, "status": "active",
            "description": description, "folder": folder, "tasks": tasks or [],
        }
        (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.projects.append(project)
        return project

    def find_project_by_name(self, name):
        for p in self.projects:
            if p["name"].lower() == name.lower():
                return p
        return None

    def list_projects(self, status=None):
        return [p for p in self.projects if p["status"] == status] if status else list(self.projects)

    def touch_activity(self, project_id):
        return None


class _FakeResearchStore:
    def __init__(self):
        self.records = []

    def create_research(self, topic, type, depth=2, questions=None):
        rec = {
            "topic": topic, "type": type, "depth": depth,
            "tasks": [{"title": "task1"}], "task_count": 1,
        }
        self.records.append(rec)
        return rec

    def add_research_note(self, topic, filename, content):
        return {"filename": filename, "size": len(content), "path": f"topics/{topic}/{filename}"}


@pytest.fixture(autouse=True)
def _isolate():
    pstore = _FakeProjectStore()
    rstore = _FakeResearchStore()
    noop = _NoopLog()
    fake_graph = _FakeGraph()
    with mock.patch("backend.functions.project_functions.get_project_store", return_value=pstore), \
         mock.patch("backend.functions.project_functions.get_operation_log", return_value=noop), \
         mock.patch("backend.functions.project_functions.get_graph", return_value=fake_graph), \
         mock.patch("backend.functions.research_functions.get_research_store", return_value=rstore):
        yield pstore, rstore
    while _temp_dirs:
        d = _temp_dirs.pop()
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)


def run(coro):
    return asyncio.run(coro)


class TestCreateProject:
    def test_description_kwarg_was_the_bug(self, _isolate):
        pstore, _ = _isolate
        result = run(dispatch_call("create_project", {
            "name": "Weather App", "description": "A weather dashboard",
        }))
        assert "created" in result.lower()
        assert pstore.projects[0]["description"] == "A weather dashboard"

    def test_project_alias_and_unknown_kwarg_stripped(self, _isolate):
        pstore, _ = _isolate
        result = run(dispatch_call("create_project", {
            "project": "Todo App", "goal": "organize tasks", "tasks": [{"title": "Build"}],
        }))
        assert "created" in result.lower()
        assert pstore.projects[0]["name"] == "Todo App"
        assert pstore.projects[0]["tasks"][0]["title"] == "Build"

    def test_name_only_still_works(self, _isolate):
        pstore, _ = _isolate
        result = run(dispatch_call("create_project", {"name": "Minimal"}))
        assert "created" in result.lower()
        assert pstore.projects[0]["description"] == ""


class TestAddProjectNote:
    def test_missing_filename_defaults_to_notes_md(self, _isolate):
        pstore, _ = _isolate
        pstore.create_project("Notes Project")
        result = run(dispatch_call("add_project_note", {
            "name": "Notes Project", "content": "# Hello",
        }))
        assert "notes.md" in result
        assert (pstore.root / "notes-project" / "notes.md").read_text(encoding="utf-8") == "# Hello"

    def test_file_name_alias(self, _isolate):
        pstore, _ = _isolate
        pstore.create_project("Alias Project")
        result = run(dispatch_call("add_project_note", {
            "name": "Alias Project", "file_name": "research.md", "content": "data",
        }))
        assert "research.md" in result

    def test_title_alias(self, _isolate):
        pstore, _ = _isolate
        pstore.create_project("Title Project")
        result = run(dispatch_call("add_project_note", {
            "name": "Title Project", "title": "architecture.md", "content": "data",
        }))
        assert "architecture.md" in result

    def test_missing_topic_still_errors_but_actionable(self, _isolate):
        result = run(dispatch_call("create_research", {"type": "market"}))
        assert "Error executing create_research" in result
        assert "Expected parameters" in result
        assert "Call this tool again" in result


class TestCreateResearch:
    def test_missing_type_defaults_to_market(self, _isolate):
        _, rstore = _isolate
        result = run(dispatch_call("create_research", {"topic": "AI Market"}))
        assert "market" in result.lower()
        assert rstore.records[0]["type"] == "market"

    def test_topic_alias_and_unknown_kwarg(self, _isolate):
        _, rstore = _isolate
        result = run(dispatch_call("create_research", {
            "project": "EV Charging", "goal": "understand market", "type": "market",
        }))
        assert "EV Charging" in result
        assert rstore.records[0]["topic"] == "EV Charging"

    def test_explicit_type_respected(self, _isolate):
        _, rstore = _isolate
        run(dispatch_call("create_research", {"topic": "GPU Chips", "type": "technical"}))
        assert rstore.records[0]["type"] == "technical"


class TestRepairHelpers:
    def test_expected_params_excludes_mcp_manager(self):
        from backend.functions.project_functions import create_project
        assert "mcp_manager" not in _expected_params(create_project)
        assert "name" in _expected_params(create_project)

    def test_repair_notes_recorded(self):
        from backend.functions.project_functions import add_project_note
        args, notes = _repair_arguments("add_project_note", add_project_note, {"name": "X"})
        assert args["filename"] == "notes.md"
        assert any("filename" in n for n in notes)


class TestUnknownTool:
    def test_unknown_function_message(self, _isolate):
        result = run(dispatch_call("not_a_real_tool", {}))
        assert "Unknown function" in result
