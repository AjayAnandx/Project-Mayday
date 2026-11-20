"""Brain store maintenance.

    python -m backend.brain.cli status                 # counts, schema, where it came from
    python -m backend.brain.cli backup [dest.db]       # consistent copy (safe while running)
    python -m backend.brain.cli export [dest.json]     # JSON snapshot (also for backend: json rollback)
    python -m backend.brain.cli import src.json --yes  # replace graph rows from a JSON file (stop backend first)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from backend.brain.store import BrainStore
from backend.core.config import load_config

REPO = Path(__file__).resolve().parents[2]


def db_path() -> Path:
    """Same rule as KnowledgeGraph: a relative db_path sits next to graph_path."""
    mem = load_config().get("memory", {}) or {}
    g = Path(mem.get("graph_path", "memory_graph.json"))
    g = g if g.is_absolute() else REPO / g
    p = Path(mem.get("db_path") or "brain.db")
    return p if p.is_absolute() else g.parent / p


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args.pop(0) if args else "status"
    store = BrainStore(db_path())
    out = sys.stdout.write
    if cmd == "status":
        out(json.dumps({"db": str(store.path), **store.counts(),
                        "schema_version": store.get_meta("schema_version"),
                        "imported_from": store.get_meta("imported_from"),
                        "imported_at": store.get_meta("imported_at")}, indent=2) + "\n")
    elif cmd == "backup":
        dest = Path(args[0]) if args else store.path.with_name(f"brain.{datetime.now():%Y%m%d-%H%M%S}.db")
        out(f"backup written: {store.backup(dest)}\n")
    elif cmd == "export":
        dest = Path(args[0]) if args else REPO / "memory_graph.export.json"
        dest.write_text(json.dumps(store.export_graph(), indent=2, ensure_ascii=False), encoding="utf-8")
        out(f"exported: {dest}\n")
    elif cmd == "import":
        if not args or "--yes" not in args:
            out("usage: import <src.json> --yes   (replaces the graph; stop the backend first)\n")
            return 2
        src = Path([a for a in args if a != "--yes"][0])
        store.load()  # prime the sync cache so rows missing from src are deleted
        bak = store.backup(store.path.with_name(f"brain.pre-import-{datetime.now():%Y%m%d-%H%M%S}.db"))
        stats = store.import_graph(json.loads(src.read_text(encoding="utf-8")), source=str(src))
        out(f"imported {stats} from {src}; previous db backed up to {bak}\n")
    else:
        out(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
