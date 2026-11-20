"""SQLite persistence for the knowledge graph (Brain V2, P2).

One file (default ``brain.db`` next to memory_graph.json), WAL mode, written
incrementally: ``sync()`` compares each node/edge with what was last written and
only upserts/deletes the rows that changed, in one transaction. This replaces
rewriting the whole JSON file on every change.

Tables
  nodes, edges          the graph (properties as JSON); same shape KnowledgeGraph uses
  nodes_fts             FTS5 over label + string properties (BM25 keyword search)
  facts, episodes, entity_aliases, commitments, ideas, profile_versions, embeddings
                        Brain V2 memory model, filled by P3 (capture) / P4 (recall)
  meta                  schema version, import provenance

All access to the database goes through this module, so a later move to another
engine (e.g. PostgreSQL for multi-device) stays local to this file.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(lower(label));

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    seq INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED, label, body, tokenize = 'porter unicode61'
);

-- Brain V2 memory model (P3/P4). Facts carry provenance and validity.
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    subject_id TEXT,              -- node id (person/project/user) the fact is about
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    sensitivity TEXT NOT NULL DEFAULT 'normal',   -- normal | private | secret
    source_ref TEXT,              -- conversation/message id
    quote TEXT,                   -- verbatim evidence from the source
    valid_from TEXT, valid_to TEXT,
    supersedes TEXT,              -- fact id this replaces
    status TEXT NOT NULL DEFAULT 'active',        -- active | superseded | rejected
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_id, status);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY, conversation_id TEXT, day TEXT,
    summary TEXT NOT NULL, decisions TEXT, open_loops TEXT, mood TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_day ON episodes(day);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias TEXT PRIMARY KEY,       -- lower-case ("mom", "jon smith")
    node_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, who TEXT, due TEXT,
    planner_item_id TEXT, source_ref TEXT, quote TEXT,
    status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, source_ref TEXT, quote TEXT,
    linked_node_id TEXT, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_versions (
    version INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL,
    reason TEXT, created_at TEXT NOT NULL
);

-- Brain V3 P9: memory strength (decay/reinforcement), archive, procedural memory
CREATE TABLE IF NOT EXISTS memory_stats (
    item_id TEXT PRIMARY KEY, importance REAL NOT NULL DEFAULT 0.5,
    reinforcements INTEGER NOT NULL DEFAULT 0, last_used TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archive (
    item_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, reason TEXT,
    archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY, trigger TEXT NOT NULL, lesson TEXT NOT NULL, scope TEXT,
    votes INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'candidate',
    evidence TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, steps TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'candidate',
    evidence TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prefs_calibrated (
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, preference TEXT NOT NULL,
    evidence TEXT, votes INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

-- Brain V3 P10: meta-cognition ledger (everything considered / shown / done) + per-type learning
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL, source TEXT, text TEXT NOT NULL,
    why TEXT, evidence TEXT, gates TEXT, decision TEXT NOT NULL, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_ts ON candidates(ts);
CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY, candidate_id TEXT, ts TEXT NOT NULL, type TEXT NOT NULL, mode TEXT NOT NULL,
    channel TEXT, text TEXT NOT NULL, why TEXT, expires_at TEXT,
    outcome TEXT, outcome_at TEXT, latency_s REAL
);
CREATE INDEX IF NOT EXISTS idx_suggestions_type ON suggestions(type, outcome);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY, ts TEXT NOT NULL, mode TEXT NOT NULL, type TEXT NOT NULL, payload TEXT,
    why TEXT, evidence TEXT, undo_payload TEXT, outcome TEXT, undone_at TEXT
);
CREATE TABLE IF NOT EXISTS type_stats (
    type TEXT PRIMARY KEY, accepts REAL NOT NULL DEFAULT 0, dismisses REAL NOT NULL DEFAULT 0,
    ignores REAL NOT NULL DEFAULT 0, edits REAL NOT NULL DEFAULT 0, undos REAL NOT NULL DEFAULT 0,
    later REAL NOT NULL DEFAULT 0, threshold_offset REAL NOT NULL DEFAULT 0, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    item_kind TEXT NOT NULL, item_id TEXT NOT NULL, model TEXT NOT NULL,
    dim INTEGER NOT NULL, vec BLOB NOT NULL, text_hash TEXT NOT NULL,
    PRIMARY KEY (item_kind, item_id, model)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fts_body(props: dict) -> str:
    return " ".join(str(v) for k, v in (props or {}).items()
                    if isinstance(v, str) and k not in ("status", "subgraph"))


class BrainStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=OFF")
        self._conn.executescript(_SCHEMA)
        # Tables owned by Brain V3 modules: created here too, so a reader never meets a missing table
        from backend.brain.signals import _SCHEMA as _SIGNALS_SCHEMA
        self._conn.executescript(_SIGNALS_SCHEMA)
        for mod in ("friction", "prep", "intents", "state", "curiosity"):
            try:
                schema = __import__(f"backend.brain.{mod}", fromlist=["_SCHEMA"])._SCHEMA
                self._conn.executescript(schema)
            except ImportError:
                pass
        self._migrate()
        self._set_meta("schema_version", str(SCHEMA_VERSION))
        # Serialized form of every row as last written, for incremental sync.
        self._node_cache: dict[str, str] = {}
        self._edge_cache: dict[str, str] = {}

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _migrate(self) -> None:
        """Additive schema changes (idempotent)."""
        self._ensure_column("episodes", "kind", "TEXT NOT NULL DEFAULT 'day'")
        self._ensure_column("episodes", "outcome", "TEXT")
        self._ensure_column("episodes", "data", "TEXT")
        self._ensure_column("facts", "category", "TEXT")
        self._ensure_column("lessons", "uses", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("lessons", "last_used", "TEXT")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_kind_day ON episodes(kind, day)")

    # ---------------- meta ----------------
    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # ---------------- graph ----------------
    def is_empty(self) -> bool:
        return self._conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone() is None

    def load(self) -> tuple[dict[str, dict], list[dict]]:
        """Return (nodes by id, edges in insertion order) and prime the sync cache."""
        with self._lock:
            nodes: dict[str, dict] = {}
            for r in self._conn.execute("SELECT id, type, label, properties FROM nodes ORDER BY rowid"):
                nodes[r["id"]] = {"id": r["id"], "type": r["type"], "label": r["label"],
                                  "properties": json.loads(r["properties"] or "{}")}
            edges: list[dict] = []
            for r in self._conn.execute(
                    "SELECT id, source, target, relation, properties FROM edges ORDER BY seq, rowid"):
                edges.append({"id": r["id"], "source": r["source"], "target": r["target"],
                              "relation": r["relation"],
                              "properties": json.loads(r["properties"] or "{}")})
            self._node_cache = {nid: self._ser_node(n) for nid, n in nodes.items()}
            self._edge_cache = {e["id"]: self._ser_edge(e, i) for i, e in enumerate(edges)}
            return nodes, edges

    @staticmethod
    def _ser_node(n: dict) -> str:
        return json.dumps([n["type"], n["label"], n.get("properties", {})],
                          ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _ser_edge(e: dict, seq: int) -> str:
        return json.dumps([e["source"], e["target"], e["relation"], e.get("properties", {}), seq],
                          ensure_ascii=False, sort_keys=True, default=str)

    def sync(self, nodes: dict[str, dict], edges: list[dict]) -> dict:
        """Write only what changed since the last load/sync, in one transaction."""
        with self._lock:
            now = _now()
            node_ser = {nid: self._ser_node(n) for nid, n in nodes.items()}
            edge_ser = {}
            for i, e in enumerate(edges):
                edge_ser[e["id"]] = self._ser_edge(e, i)
            up_nodes = [nid for nid, s in node_ser.items() if self._node_cache.get(nid) != s]
            del_nodes = [nid for nid in self._node_cache if nid not in node_ser]
            up_edges = [eid for eid, s in edge_ser.items() if self._edge_cache.get(eid) != s]
            del_edges = [eid for eid in self._edge_cache if eid not in edge_ser]
            if not (up_nodes or del_nodes or up_edges or del_edges):
                return {"nodes": 0, "edges": 0}
            edge_by_id = {e["id"]: (i, e) for i, e in enumerate(edges)}
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                for nid in del_nodes:
                    c.execute("DELETE FROM nodes WHERE id = ?", (nid,))
                    c.execute("DELETE FROM nodes_fts WHERE node_id = ?", (nid,))
                for nid in up_nodes:
                    n = nodes[nid]
                    props = n.get("properties", {})
                    c.execute(
                        "INSERT INTO nodes(id, type, label, properties, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET type=excluded.type, label=excluded.label, "
                        "properties=excluded.properties, updated_at=excluded.updated_at",
                        (nid, n["type"], n["label"], json.dumps(props, ensure_ascii=False, default=str), now))
                    c.execute("DELETE FROM nodes_fts WHERE node_id = ?", (nid,))
                    c.execute("INSERT INTO nodes_fts(node_id, label, body) VALUES (?,?,?)",
                              (nid, n["label"], _fts_body(props)))
                for eid in del_edges:
                    c.execute("DELETE FROM edges WHERE id = ?", (eid,))
                for eid in up_edges:
                    seq, e = edge_by_id[eid]
                    c.execute(
                        "INSERT INTO edges(id, source, target, relation, properties, seq) VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET source=excluded.source, target=excluded.target, "
                        "relation=excluded.relation, properties=excluded.properties, seq=excluded.seq",
                        (eid, e["source"], e["target"], e["relation"],
                         json.dumps(e.get("properties", {}), ensure_ascii=False, default=str), seq))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            for nid in del_nodes:
                self._node_cache.pop(nid, None)
            for nid in up_nodes:
                self._node_cache[nid] = node_ser[nid]
            for eid in del_edges:
                self._edge_cache.pop(eid, None)
            for eid in up_edges:
                self._edge_cache[eid] = edge_ser[eid]
            return {"nodes": len(up_nodes) + len(del_nodes), "edges": len(up_edges) + len(del_edges)}

    def fts_search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        """BM25 keyword search over node label + string properties: [(node_id, score)]
        (lower score = better, SQLite convention). Each word is matched as a prefix."""
        import re
        words = [w for w in re.findall(r"[A-Za-z0-9]+", query or "") if len(w) > 1]
        if not words:
            return []
        expr = " OR ".join(f'"{w}"*' for w in words)
        rows = self._conn.execute(
            "SELECT node_id, bm25(nodes_fts, 2.0, 1.0) AS s FROM nodes_fts "
            "WHERE nodes_fts MATCH ? ORDER BY s LIMIT ?", (expr, limit)).fetchall()
        return [(r["node_id"], r["s"]) for r in rows]

    # ---------------- Brain V2 memory model (P3) ----------------
    def _insert(self, table: str, row: dict) -> dict:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock:
            self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        return row

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def add_fact(self, *, subject_id: str | None, predicate: str, object: str, confidence: float,
                 quote: str, source_ref: str = "", sensitivity: str = "normal",
                 status: str = "active", supersedes: str | None = None, fact_id: str | None = None,
                 category: str | None = None) -> dict:
        import uuid
        now = _now()
        return self._insert("facts", {
            "id": fact_id or "f_" + uuid.uuid4().hex[:12], "subject_id": subject_id,
            "predicate": predicate, "object": object, "confidence": float(confidence),
            "sensitivity": sensitivity, "source_ref": source_ref, "quote": quote,
            "valid_from": now, "valid_to": None, "supersedes": supersedes, "status": status,
            "created_at": now, "updated_at": now, "category": category})

    def get_fact(self, fact_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM facts WHERE id = ?", (fact_id,))
        return rows[0] if rows else None

    def find_facts(self, subject_id: str | None, predicate: str, status: str = "active") -> list[dict]:
        return self._rows("SELECT * FROM facts WHERE subject_id IS ? AND predicate = ? AND status = ? "
                          "ORDER BY created_at", (subject_id, predicate, status))

    def update_fact(self, fact_id: str, **fields) -> dict | None:
        allowed = {"status", "object", "confidence", "valid_to", "sensitivity", "subject_id", "supersedes"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            sets["updated_at"] = _now()
            assign = ", ".join(f"{k} = ?" for k in sets)
            with self._lock:
                self._conn.execute(f"UPDATE facts SET {assign} WHERE id = ?", (*sets.values(), fact_id))
        return self.get_fact(fact_id)

    def list_facts(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
        if status:
            return self._rows("SELECT * FROM facts WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                              (status, limit, offset))
        return self._rows("SELECT * FROM facts ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))

    def add_commitment(self, *, text: str, who: str = "user", due: str | None = None,
                       quote: str = "", source_ref: str = "", status: str = "open",
                       planner_item_id: str | None = None) -> dict:
        import uuid
        return self._insert("commitments", {
            "id": "c_" + uuid.uuid4().hex[:12], "text": text, "who": who, "due": due,
            "planner_item_id": planner_item_id, "source_ref": source_ref, "quote": quote,
            "status": status, "created_at": _now()})

    def update_commitment(self, cid: str, **fields) -> None:
        sets = {k: v for k, v in fields.items() if k in {"status", "planner_item_id", "text", "due"}}
        if sets:
            assign = ", ".join(f"{k} = ?" for k in sets)
            with self._lock:
                self._conn.execute(f"UPDATE commitments SET {assign} WHERE id = ?", (*sets.values(), cid))

    def get_commitment(self, cid: str) -> dict | None:
        rows = self._rows("SELECT * FROM commitments WHERE id = ?", (cid,))
        return rows[0] if rows else None

    def list_commitments(self, status: str | None = None, limit: int = 50) -> list[dict]:
        if status:
            return self._rows("SELECT * FROM commitments WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                              (status, limit))
        return self._rows("SELECT * FROM commitments ORDER BY created_at DESC LIMIT ?", (limit,))

    def add_idea(self, *, text: str, quote: str = "", source_ref: str = "",
                 linked_node_id: str | None = None) -> dict:
        import uuid
        return self._insert("ideas", {
            "id": "i_" + uuid.uuid4().hex[:12], "text": text, "source_ref": source_ref,
            "quote": quote, "linked_node_id": linked_node_id, "created_at": _now()})

    def delete_idea(self, iid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM ideas WHERE id = ?", (iid,))

    def list_ideas(self, limit: int = 50) -> list[dict]:
        return self._rows("SELECT * FROM ideas ORDER BY created_at DESC LIMIT ?", (limit,))

    def set_alias(self, alias: str, node_id: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO entity_aliases(alias, node_id) VALUES (?, ?)",
                               (alias.strip().lower(), node_id))

    def resolve_alias(self, alias: str) -> str | None:
        rows = self._rows("SELECT node_id FROM entity_aliases WHERE alias = ?", (alias.strip().lower(),))
        return rows[0]["node_id"] if rows else None

    # ---------------- Brain V3 P9: episodes by kind, memory strength, archive ----------------
    def add_episode(self, *, kind: str, day: str, summary: str, conversation_id: str | None = None,
                    decisions: list | None = None, open_loops: list | None = None, mood: str = "",
                    outcome: str | None = None, data: dict | None = None) -> dict:
        import uuid
        return self._insert("episodes", {
            "id": "e_" + uuid.uuid4().hex[:12], "conversation_id": conversation_id, "day": day,
            "summary": summary, "decisions": json.dumps(decisions or []),
            "open_loops": json.dumps(open_loops or []), "mood": mood, "created_at": _now(),
            "kind": kind, "outcome": outcome, "data": json.dumps(data or {}, ensure_ascii=False)})

    def list_episodes(self, kind: str = "day", limit: int = 30, since_day: str | None = None) -> list[dict]:
        if since_day:
            return self._rows("SELECT * FROM episodes WHERE kind=? AND day>=? ORDER BY day DESC LIMIT ?",
                              (kind, since_day, limit))
        return self._rows("SELECT * FROM episodes WHERE kind=? ORDER BY day DESC LIMIT ?", (kind, limit))

    def touch(self, item_ids: list[str], importance: float | None = None) -> None:
        """Reinforce memory items (used in recall, re-mentioned, confirmed)."""
        now = _now()
        with self._lock:
            for iid in item_ids:
                self._conn.execute(
                    "INSERT INTO memory_stats(item_id, importance, reinforcements, last_used, created_at) "
                    "VALUES (?, ?, 1, ?, ?) ON CONFLICT(item_id) DO UPDATE SET "
                    "reinforcements = reinforcements + 1, last_used = excluded.last_used"
                    + (", importance = MAX(importance, excluded.importance)" if importance is not None else ""),
                    (iid, importance if importance is not None else 0.5, now, now))

    def memory_stat(self, item_id: str) -> dict | None:
        rows = self._rows("SELECT * FROM memory_stats WHERE item_id=?", (item_id,))
        return rows[0] if rows else None

    def archive_item(self, item_id: str, kind: str, payload: dict, reason: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO archive(item_id, kind, payload, reason, archived_at) "
                               "VALUES (?,?,?,?,?)", (item_id, kind, json.dumps(payload, ensure_ascii=False),
                                                      reason, _now()))

    def purge_archive(self, days: int = 90) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            return self._conn.execute("DELETE FROM archive WHERE archived_at < ?", (cutoff,)).rowcount or 0

    # ---------------- import / export ----------------
    def import_graph(self, data: dict, source: str = "") -> dict:
        """Idempotent import of a {"nodes", "edges"} graph (replaces graph rows)."""
        nodes = {n["id"]: {"id": n["id"], "type": n["type"], "label": n["label"],
                           "properties": n.get("properties", {}) or {}}
                 for n in data.get("nodes", [])}
        edges = [e for e in data.get("edges", []) if e.get("id")]
        stats = self.sync(nodes, edges)
        if source:
            self._set_meta("imported_from", source)
            self._set_meta("imported_at", _now())
        return stats

    def export_graph(self) -> dict:
        nodes, edges = self.load()
        return {"nodes": list(nodes.values()), "edges": edges}

    def backup(self, dest: Path | str) -> Path:
        """Consistent single-file copy (safe while in use)."""
        dest = Path(dest)
        if dest.exists():
            dest.unlink()
        with self._lock:
            self._conn.execute("VACUUM INTO ?", (str(dest),))
        return dest

    def counts(self) -> dict:
        q = lambda t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
        return {"nodes": q("nodes"), "edges": q("edges"), "facts": q("facts")}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
