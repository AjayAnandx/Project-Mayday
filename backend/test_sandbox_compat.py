import tempfile
import json
from pathlib import Path

import pytest

from backend.core.sandbox import (
    sandbox_start, sandbox_exec, sandbox_stop, sandbox_status,
    sandbox_write_file, sandbox_read_file, sandbox_delete_file, sandbox_list_files,
    sandbox_sync_from_host, sandbox_sync_to_host, list_host_projects,
)
from backend.core.project_runner import _instances as project_runner_instances


class TestSandboxCompat:
    """Backward compatibility tests for the 11 sandbox functions"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        project_runner_instances.clear()
        yield
        project_runner_instances.clear()

    def test_start_returns_success_message(self):
        result = sandbox_start("compat-test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_start_idempotent(self):
        sandbox_start("idem-test")
        result = sandbox_start("idem-test")
        assert isinstance(result, str)

    def test_exec_simple_command(self):
        sandbox_start("exec-test")
        result = sandbox_exec("exec-test", "echo hello world")
        assert "hello world" in result

    def test_exec_background_false_default(self):
        sandbox_start("fg-test")
        result = sandbox_exec("fg-test", "echo test")
        assert "test" in result

    def test_status_after_start(self):
        sandbox_start("status-test")
        result = sandbox_status("status-test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_status_nonexistent(self):
        result = sandbox_status("nonexistent-project-xyz")
        assert "not" in result.lower() or "found" in result.lower()

    def test_write_file(self):
        sandbox_start("write-test")
        result = sandbox_write_file("write-test", "newfile.txt", "test content")
        assert "written" in result.lower() or "created" in result.lower()

    def test_read_file(self):
        sandbox_start("read-test")
        sandbox_write_file("read-test", "readme.txt", "hello there")
        result = sandbox_read_file("read-test", "readme.txt")
        assert "hello there" in result

    def test_read_nonexistent(self):
        sandbox_start("read-none")
        result = sandbox_read_file("read-none", "missing.txt")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_delete_file(self):
        sandbox_start("del-test")
        sandbox_write_file("del-test", "todelete.txt", "x")
        result = sandbox_delete_file("del-test", "todelete.txt")
        assert "deleted" in result.lower()

    def test_delete_nonexistent(self):
        sandbox_start("del-none")
        result = sandbox_delete_file("del-none", "missing.txt")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_list_files(self):
        sandbox_start("list-test")
        sandbox_write_file("list-test", "a.txt", "1")
        sandbox_write_file("list-test", "sub/b.txt", "2")
        result = sandbox_list_files("list-test", ".")
        assert "a.txt" in result
        assert "sub" in result

    def test_list_files_subdir(self):
        sandbox_start("list-sub")
        sandbox_write_file("list-sub", "sub/c.txt", "3")
        result = sandbox_list_files("list-sub", "sub")
        assert "c.txt" in result

    def test_sync_from_host_noop(self):
        sandbox_start("sync-test")
        result = sandbox_sync_from_host("sync-test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sync_to_host_noop(self):
        sandbox_start("sync-test")
        result = sandbox_sync_to_host("sync-test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_stop(self):
        sandbox_start("stop-test")
        result = sandbox_stop("stop-test")
        assert "stopped" in result.lower() or "cleaned" in result.lower() or "no sandbox" in result.lower()

    def test_stop_nonexistent(self):
        result = sandbox_stop("never-started-xyz")
        assert "not" in result.lower() or "found" in result.lower()

    def test_list_host_projects(self):
        sandbox_start("proj-a")
        sandbox_start("proj-b")
        result = list_host_projects()
        assert "proj-a" in result
        assert "proj-b" in result

    def test_full_workflow(self):
        """Test a complete build workflow: start -> write -> exec -> status -> stop"""
        sandbox_start("workflow-test")

        # Write package.json
        pkg = {"name": "test", "scripts": {"build": "echo built"}}
        sandbox_write_file("workflow-test", "package.json", json.dumps(pkg))

        # Run build - use type on Windows
        result = sandbox_exec("workflow-test", "type package.json")
        assert "test" in result

        # Check status
        status = sandbox_status("workflow-test")
        assert isinstance(status, str)

        # Stop
        sandbox_stop("workflow-test")
        status = sandbox_status("workflow-test")
        assert "no sandbox" in status.lower() or "not found" in status.lower()