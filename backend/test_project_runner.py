import tempfile
import json
import os
from pathlib import Path

import pytest

from backend.core.project_runner import ProjectRunner, _instances as project_runner_instances
from backend.core.sandbox import _to_slug


class TestToSlug:
    def test_basic_slug(self):
        assert _to_slug("My Project") == "my-project"

    def test_special_chars(self):
        # non-alphanumeric chars are stripped
        assert _to_slug("Test@#$%^&*()") == "test"

    def test_unicode_stripped(self):
        # unicode is stripped by the regex [^a-z0-9-]
        result = _to_slug("项目")
        assert result == ""  # all unicode chars stripped

    def test_empty_returns_empty(self):
        assert _to_slug("") == ""

    def test_whitespace_only(self):
        # spaces are replaced with hyphens
        result = _to_slug("   ")
        assert result == "---"

    def test_multiple_spaces(self):
        # each space becomes a hyphen
        assert _to_slug("My  Project   Name") == "my--project---name"


class TestProjectRunner:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        project_runner_instances.clear()
        yield
        project_runner_instances.clear()

    def test_get_or_create(self):
        runner = ProjectRunner.get_or_create("test-project")
        assert runner is not None
        assert runner.slug == "test-project"

    def test_singleton_per_slug(self):
        r1 = ProjectRunner.get_or_create("same-project")
        r2 = ProjectRunner.get_or_create("same-project")
        assert r1 is r2

    def test_different_slugs_different_instances(self):
        r1 = ProjectRunner.get_or_create("project-a")
        r2 = ProjectRunner.get_or_create("project-b")
        assert r1 is not r2

    def test_project_dir_exists(self):
        runner = ProjectRunner.get_or_create("my-proj")
        runner.prepare()
        assert runner.project_dir.exists()

    def test_is_running_false_initially(self):
        runner = ProjectRunner.get_or_create("test")
        assert runner.is_running is False

    def test_exec_foreground(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.exec("echo hello")
        assert "hello" in result

    def test_exec_background_starts_process(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.exec_background("python -c \"import time; time.sleep(10)\"")
        assert "pid" in result
        assert runner.is_running is True

    def test_exec_background_tracks_pid(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.exec_background("python -c \"import time; time.sleep(10)\"")
        assert "pid" in result
        pid = result["pid"]
        from backend.core.project_runner import _background_processes
        assert pid in _background_processes.get("test", [])

    def test_write_file(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.write_file("src/main.py", "print('hello')")
        assert "Written" in result
        assert (runner.project_dir / "src" / "main.py").read_text() == "print('hello')"

    def test_write_file_creates_parents(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        runner.write_file("deep/nested/path/file.txt", "content")
        assert (runner.project_dir / "deep" / "nested" / "path" / "file.txt").read_text() == "content"

    def test_write_file_blocks_path_escape(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        try:
            runner.write_file("../../../etc/passwd", "hack")
            assert False, "Should have raised PermissionError"
        except PermissionError as e:
            assert "Path escape" in str(e)

    def test_read_file(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        runner.write_file("file.txt", "hello world")
        content = runner.read_file("file.txt")
        assert content == "hello world"

    def test_read_file_not_found(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        content = runner.read_file("nonexistent.txt")
        assert "not found" in content.lower() or "file not found" in content.lower()

    def test_list_files(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        runner.write_file("a.txt", "1")
        runner.write_file("sub/b.txt", "2")
        files = runner.list_files(".")
        # Returns Windows dir output
        assert "a.txt" in files
        assert "sub" in files

    def test_list_files_subdir(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        runner.write_file("sub/a.txt", "1")
        files = runner.list_files("sub")
        assert "a.txt" in files

    def test_delete_file(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        runner.write_file("todelete.txt", "x")
        result = runner.delete_file("todelete.txt")
        assert "Deleted" in result
        assert not (runner.project_dir / "todelete.txt").exists()

    def test_delete_file_not_found(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.delete_file("nonexistent.txt")
        assert "Not found" in result

    def test_delete_file_blocks_path_escape(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        try:
            runner.delete_file("../../../etc/passwd")
            assert False, "Should have raised PermissionError"
        except PermissionError as e:
            assert "Path escape" in str(e)

    def test_cleanup_orphans_classmethod(self):
        runner = ProjectRunner.get_or_create("test")
        runner.prepare()
        result = runner.exec_background("python -c \"import time; time.sleep(10)\"")
        assert "pid" in result
        ProjectRunner.cleanup_orphans()  # returns None, just verify no error

    def test_get_non_existent_returns_none(self):
        ProjectRunner.get_or_create("exists")
        assert ProjectRunner.get("does-not-exist") is None


from backend.core.project_runner import _background_processes


class TestSandboxCompat:
    """Backward compatibility tests for the 11 sandbox functions"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        project_runner_instances.clear()
        _background_processes.clear()
        yield
        project_runner_instances.clear()
        _background_processes.clear()

    def test_sandbox_start(self):
        from backend.core.sandbox import sandbox_start
        result = sandbox_start("my-project")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sandbox_exec(self):
        from backend.core.sandbox import sandbox_start, sandbox_exec
        sandbox_start("exec-test")
        result = sandbox_exec("exec-test", "echo hello")
        assert "hello" in result

    def test_sandbox_status(self):
        from backend.core.sandbox import sandbox_start, sandbox_status
        sandbox_start("status-test")
        result = sandbox_status("status-test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_sandbox_write_read(self):
        from backend.core.sandbox import sandbox_start, sandbox_write_file, sandbox_read_file
        sandbox_start("write-test")
        sandbox_write_file("write-test", "test.txt", "content123")
        result = sandbox_read_file("write-test", "test.txt")
        assert "content123" in result

    def test_sandbox_delete(self):
        from backend.core.sandbox import sandbox_start, sandbox_write_file, sandbox_delete_file, sandbox_list_files
        sandbox_start("del-test")
        sandbox_write_file("del-test", "todelete.txt", "x")
        sandbox_delete_file("del-test", "todelete.txt")
        files = sandbox_list_files("del-test", ".")
        assert "todelete.txt" not in files

    def test_sandbox_list_files(self):
        from backend.core.sandbox import sandbox_start, sandbox_write_file, sandbox_list_files
        sandbox_start("list-test")
        sandbox_write_file("list-test", "a.txt", "1")
        sandbox_write_file("list-test", "sub/b.txt", "2")
        files = sandbox_list_files("list-test", ".")
        assert "a.txt" in files
        assert "sub" in files

    def test_sandbox_sync_from_host_noop(self):
        from backend.core.sandbox import sandbox_start, sandbox_sync_from_host
        sandbox_start("sync-test")
        result = sandbox_sync_from_host("sync-test")
        assert "no-op" in result.lower() or "already" in result.lower()

    def test_sandbox_sync_to_host_noop(self):
        from backend.core.sandbox import sandbox_start, sandbox_sync_to_host
        sandbox_start("sync-test")
        result = sandbox_sync_to_host("sync-test")
        assert "no-op" in result.lower() or "already" in result.lower()

    def test_sandbox_stop(self):
        from backend.core.sandbox import sandbox_start, sandbox_stop, sandbox_status
        sandbox_start("stop-test")
        result = sandbox_stop("stop-test")
        assert "stopped" in result.lower() or "cleaned" in result.lower() or "no sandbox" in result.lower()

    def test_sandbox_stop_nonexistent(self):
        from backend.core.sandbox import sandbox_stop
        result = sandbox_stop("never-started-xyz")
        assert "not" in result.lower() or "found" in result.lower()

    def test_list_host_projects(self):
        from backend.core.sandbox import sandbox_start, list_host_projects
        sandbox_start("proj1")
        sandbox_start("proj2")
        result = list_host_projects()
        assert "proj1" in result
        assert "proj2" in result

    def test_full_workflow(self):
        """Test a complete build workflow: start -> write -> exec -> status -> stop"""
        from backend.core.sandbox import sandbox_start, sandbox_write_file, sandbox_exec, sandbox_status, sandbox_stop
        sandbox_start("workflow-test")

        # Write package.json
        pkg = {"name": "test", "scripts": {"build": "echo built"}}
        sandbox_write_file("workflow-test", "package.json", json.dumps(pkg))

        # Run build - use type command on Windows
        result = sandbox_exec("workflow-test", "type package.json")
        assert "test" in result

        # Check status
        status = sandbox_status("workflow-test")
        assert isinstance(status, str)

        # Stop - instance is removed after stop
        sandbox_stop("workflow-test")
        status = sandbox_status("workflow-test")
        assert "no sandbox" in status.lower() or "not found" in status.lower()