"""Run brain code against a throw-away graph so the live brain is never touched."""
from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import backend.core.config as cfgmod
import backend.core.user_awareness as uamod
import backend.memory.knowledge_graph as kgmod
import backend.memory.multigraph as mgmod

REPO = Path(__file__).resolve().parents[2]
LIVE_GRAPH = REPO / "memory_graph.json"
LIVE_DB = REPO / "brain.db"


class _NoopLog:
    def record(self, *a, **k):
        return {"id": "eval"}

    def query(self, *a, **k):
        return []


@contextmanager
def isolated_brain(background: Path | None = None):
    """Yield a fresh KnowledgeGraph in a temp dir.

    ``background``: optional graph JSON copied in first (e.g. the live graph as
    realistic noise). The source file is only read, never written.
    """
    tmp = Path(tempfile.mkdtemp(prefix="brain_eval_"))
    graph_path = tmp / "memory_graph.json"
    if background is not None and background == LIVE_GRAPH and LIVE_DB.exists():
        # Live data is in brain.db: take a read-only, consistent snapshot of it.
        import sqlite3
        src = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(str(tmp / "brain.db"))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    elif background and background.exists():
        shutil.copy2(background, graph_path)
    cfg = cfgmod.load_config()
    cfg = {**cfg, "memory": {**cfg.get("memory", {}), "graph_path": str(graph_path),
                             "db_path": str(tmp / "brain.db")}}
    saved = (kgmod._graph, mgmod._multigraph, uamod._instance)
    patches = [
        mock.patch.object(kgmod, "load_config", lambda: cfg),
        mock.patch("backend.memory.memory_tools.get_operation_log", lambda: _NoopLog()),
    ]
    for p in patches:
        p.start()
    kgmod._graph, mgmod._multigraph, uamod._instance = None, None, None
    try:
        yield kgmod.get_graph()
    finally:
        for p in patches:
            p.stop()
        kgmod._graph, mgmod._multigraph, uamod._instance = saved
        shutil.rmtree(tmp, ignore_errors=True)
