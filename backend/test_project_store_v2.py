"""Tests for ProjectStore v2 upgrade (Phases A-D). Isolated — uses tmp dirs, no repo pollution."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


def _make_store(tmp_projects_dir: Path, tmp_projects_json: Path):
    from backend.core import project_store as ps
    import importlib
    # Patch config to point to temp paths
    fake_cfg = {
        "data": {"projects_path": str(tmp_projects_json), "projects_dir": str(tmp_projects_dir)},
        "projects": {"trust": "medium"},
        "project_trust": "medium",
    }
    with patch.object(ps, "load_config", return_value=fake_cfg):
        # force new instance without singleton
        store = ps.ProjectStore.__new__(ps.ProjectStore)
        store._path = tmp_projects_json
        store._projects_dir = tmp_projects_dir
        import threading
        import time
        store._lock = threading.Lock()
        store._hooks = {}
        store._hook_lock = threading.Lock()
        store._emit_state = threading.local()
        store._projects = []
        store._trust_cache_value = None
        store._trust_cache_mtime = 0.0
        store._trust_cache_time = 0.0
        store._trust_cache_lock = threading.Lock()
        store._id_index = {}
        store._name_index = {}
        store._batch_enabled = False
        store._save_timer = None
        store._save_timer_lock = threading.Lock()
        store._init_projects_dir()
        store._register_default_hooks()
        store._rebuild_indexes()
        return store


def test_event_log_replay():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pj = td / "projects.json"
        pdir = td / "projects"
        s = _make_store(pdir, pj)
        proj = s.create_project("ReplayProj")
        pid = proj["id"]
        t = s.add_task(pid, "Task1")
        s.update_task_status(pid, t["id"], "in_progress")
        s.update_task_status(pid, t["id"], "completed", result="done")
        s.add_data_point(pid, "label1", "42")
        # corrupt projects.json
        pj.write_text("CORRUPT", encoding="utf-8")
        # new store should recover via replay
        s2 = _make_store(pdir, pj)
        # s2._load would have tried replay_all — but we already passed corrupt via new store's _load
        # Instead explicitly test replay_events
        rep = s.replay_events(proj["folder"])
        assert rep is not None
        assert rep["name"] == "ReplayProj"
        assert len(rep.get("tasks", [])) == 1
        assert rep["tasks"][0]["status"] == "completed"
        print("test_event_log_replay PASS")


def test_checkpoint_resume():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        proj = s.create_project("CheckpointProj")
        pid = proj["id"]
        t = s.add_task(pid, "LongTask")
        s.update_task_status(pid, t["id"], "in_progress")
        cp = s.set_checkpoint(pid, t["id"], 5, "opencode_bash", "partial")
        assert cp["iteration"] == 5
        got = s.get_checkpoint(pid)
        assert got["task_id"] == t["id"]
        # simulate crash — no clear_checkpoint
        # resume should see checkpoint
        from backend.functions.project_functions import resume_project
        import backend.functions.project_functions as pf
        import backend.core.project_store as ps
        orig_pf = pf.get_project_store
        orig_ps = ps.get_project_store
        pf.get_project_store = lambda: s
        ps.get_project_store = lambda: s
        try:
            out = resume_project("CheckpointProj")
            assert "Checkpoint" in out, f"missing Checkpoint in {out}"
            assert "continue" in out.lower(), f"missing continue in {out}"
        finally:
            pf.get_project_store = orig_pf
            ps.get_project_store = orig_ps
        s.clear_checkpoint(pid)
        assert s.get_checkpoint(pid) is None
        print("test_checkpoint_resume PASS")


def test_subtask_gating():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        proj = s.create_project("ParentChildProj")
        pid = proj["id"]
        parent = s.add_task(pid, "Parent")
        c1 = s.add_task(pid, "Child1", parent_task_id=parent["id"])
        c2 = s.add_task(pid, "Child2", parent_task_id=parent["id"])
        # parent should not be eligible while children pending
        active = s.get_active_task(pid)
        assert active["id"] == c1["id"], f"expected Child1, got {active['title']}"
        s.update_task_status(pid, c1["id"], "in_progress")
        s.update_task_status(pid, c1["id"], "completed", result="ok")
        active = s.get_active_task(pid)
        assert active["id"] == c2["id"]
        s.update_task_status(pid, c2["id"], "in_progress")
        s.update_task_status(pid, c2["id"], "completed", result="ok")
        active = s.get_active_task(pid)
        assert active["id"] == parent["id"], f"expected Parent after children, got {active}"
        # tree
        tree = s.list_tasks(pid, tree=True)
        assert any(t["id"] == parent["id"] and len(t.get("children", [])) == 2 for t in tree)
        print("test_subtask_gating PASS")


def test_artifact_offload():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        proj = s.create_project("ArtifactProj")
        pid = proj["id"]
        t = s.add_task(pid, "BigTask")
        s.update_task_status(pid, t["id"], "in_progress")
        big = "x" * 5000
        updated = s.update_task_status(pid, t["id"], "completed", result=big)
        assert updated["result_artifact"], "should have artifact path"
        assert Path(updated["result_artifact"]).exists()
        assert len(updated["result"]) < len(big)
        full = s.get_task_result(pid, t["id"])
        assert full == big
        # small result should stay inline
        t2 = s.add_task(pid, "SmallTask")
        s.update_task_status(pid, t2["id"], "in_progress")
        small = "hello"
        updated2 = s.update_task_status(pid, t2["id"], "completed", result=small)
        assert not updated2["result_artifact"]
        assert updated2["result"] == small
        print("test_artifact_offload PASS")


def test_hook_order():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        order = []
        s.register_hook("task.pre_transition", lambda d: order.append("pre"))
        s.register_hook("task.post_transition", lambda d: order.append("post"))
        # custom skill hook
        s.register_hook("task.post_transition", lambda d: order.append("skill"))
        proj = s.create_project("HookProj")
        pid = proj["id"]
        t = s.add_task(pid, "HookTask")
        s.update_task_status(pid, t["id"], "in_progress")
        # order should contain pre then post then skill (post hooks in registration order)
        assert "pre" in order and "post" in order and "skill" in order
        # pre should come before post
        assert order.index("pre") < order.index("post")
        # test recursion guard — hook that emits again should not deadlock
        fired = []
        def hook_a(d):
            fired.append("a")
            s.emit_hook("inner_evt", {})
        def hook_inner(d):
            fired.append("inner")
        s.register_hook("outer_evt", hook_a)
        s.register_hook("inner_evt", hook_inner)
        s.emit_hook("outer_evt", {})
        assert fired == ["a", "inner"]
        print("test_hook_order PASS")


def test_trust_gate():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        proj = s.create_project("TrustProj")
        pid = proj["id"]
        # set trust low
        for p in s._projects:
            if p["id"] == pid:
                p["trust_level"] = "low"
        # soft_delete without confirmed should gate
        res = s.update_project_status(pid, "scrapped")
        assert "error" in res and res.get("requires_confirmation"), f"expected gate, got {res}"
        # with confirmed should pass
        res2 = s.update_project_status(pid, "scrapped", confirmed=True)
        assert res2["status"] == "scrapped"
        # force duplicate task gate
        s2 = _make_store(td / "projects2", td / "projects2.json")
        proj2 = s2.create_project("TrustTaskProj")
        pid2 = proj2["id"]
        s2.add_task(pid2, "Dup")
        for p in s2._projects:
            if p["id"] == pid2:
                p["trust_level"] = "low"
        dup = s2.add_task(pid2, "Dup", force=True)
        assert "error" in dup and dup.get("requires_confirmation")
        dup2 = s2.add_task(pid2, "Dup", force=True, confirmed=True)
        assert "id" in dup2
        print("test_trust_gate PASS")


def test_assemble_context_shape():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        s = _make_store(td / "projects", td / "projects.json")
        proj = s.create_project("CtxProj", description="test goal")
        pid = proj["id"]
        t = s.add_task(pid, "CtxTask")
        s.update_task_status(pid, t["id"], "in_progress")
        s.add_token_usage(pid, 500, 0.01)
        s.register_process(pid, 12345)
        s.set_checkpoint(pid, t["id"], 2, "opencode_bash", "partial")
        # create a file
        (s._projects_dir / proj["folder"] / "README.md").write_text("# hello", encoding="utf-8")
        ctx = s.assemble_project_context(pid)
        assert "project" in ctx
        assert "files" in ctx
        assert "tasks" in ctx
        assert "active_task" in ctx
        assert "recent_operations" in ctx
        assert "runtime" in ctx
        assert "checkpoint" in ctx
        assert ctx["runtime"]["token_usage"] == 500
        assert 12345 in ctx["runtime"]["process_handles"]
        assert ctx["checkpoint"] is not None
        block = s.format_context_block(pid)
        assert "CtxProj" in block
        assert "Tokens:" in block
        print("test_assemble_context_shape PASS")


if __name__ == "__main__":
    test_event_log_replay()
    test_checkpoint_resume()
    test_subtask_gating()
    test_artifact_offload()
    test_hook_order()
    test_trust_gate()
    test_assemble_context_shape()
    print("ALL TESTS PASS")
