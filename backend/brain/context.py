"""Brain V2 P4: recall. Builds what the model is told about the user each turn.

    now_block()            today's plan, overdue items, waiting-on, open commitments (always, short)
    retrieve(text, recent) hybrid retrieval -> "Relevant memories" lines with memory ids

Hybrid retrieval, no model call on the hot path:
  1. query expansion: pronouns / "that project" are resolved to people and projects
     named in the last few user messages (cheap coreference) and to known aliases
  2. three rankers over graph nodes:
       FTS5 BM25 (SQLite)   - exact words, stemmed
       in-memory IDF search - partial matches
       embeddings (Ollama nomic-embed-text, cached in the db) - meaning ("satay" ~ "peanuts")
  3. reciprocal-rank fusion, then a re-rank by node type and recency
  4. pack: each memory with its relations (facts), within a token budget, ids cited

Embeddings are optional: if Ollama or the model is missing, the other rankers still work.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import struct
import threading
import time
from collections import defaultdict
from datetime import datetime

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)

# Node types that are bookkeeping, not memories about the user.
_SKIP_TYPES = {"conversation", "build_lesson", "build_preference", "email", "question", "tag", "date"}
_TYPE_WEIGHT = {"user": 1.3, "person": 1.25, "idea": 1.15, "event": 1.1, "todo": 1.05, "project": 1.0,
                "research": 0.9, "document": 0.9, "concept": 1.0, "place": 1.1, "organization": 1.0}
_PRONOUN = re.compile(r"\b(he|him|his|she|her|hers|they|them|their|that (project|guy|girl|person|idea)|"
                      r"it|this project)\b", re.I)


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("recall", {}) or {}
    return {"enabled": bool(c.get("enabled", True)),
            "token_budget": int(c.get("token_budget", 1200)),
            "max_items": int(c.get("max_items", 8)),
            "embed_model": c.get("embed_model", "nomic-embed-text"),
            "embed_url": c.get("embed_url", "http://localhost:11434/api/embed"),
            "embed_timeout": float(c.get("embed_timeout", 3.0)),
            "use_embeddings": bool(c.get("use_embeddings", True))}


# ------------------------------------------------------------------ embeddings
class Embedder:
    """Ollama embeddings with a cache in the brain db (embeddings table).

    Node vectors are computed in the background (``warm``) so the chat path only
    embeds the query (one short request). Any failure disables embeddings for a
    minute instead of slowing every turn.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._vecs: dict[str, list[float]] = {}       # node_id -> unit vector
        self._down_until = 0.0
        self._warming = False
        self._qcache: dict[str, list[float]] = {}     # query text -> unit vector (LRU-ish)

    def _post(self, texts: list[str]) -> list[list[float]] | None:
        import httpx
        cfg = _cfg()
        if not cfg["use_embeddings"] or time.time() < self._down_until:
            return None
        try:
            r = httpx.post(cfg["embed_url"], json={"model": cfg["embed_model"], "input": texts,
                                                   "keep_alive": "30m"},
                           timeout=cfg["embed_timeout"] if len(texts) == 1 else 120)
            r.raise_for_status()
            vecs = r.json().get("embeddings") or []
            return vecs if len(vecs) == len(texts) else None
        except Exception as e:
            logger.info("embeddings unavailable (%s); continuing without them", e)
            self._down_until = time.time() + 60
            return None

    @staticmethod
    def _unit(v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    @staticmethod
    def node_text(node: dict) -> str:
        props = node.get("properties", {}) or {}
        extra = " ".join(str(v) for k, v in props.items()
                         if isinstance(v, str) and k not in ("status", "subgraph", "context") and len(v) < 300)
        return f"{node.get('label', '')} {extra}".strip()[:800]

    def load_cache(self, store, model: str) -> None:
        rows = store._rows("SELECT item_id, dim, vec FROM embeddings WHERE item_kind='node' AND model=?",
                           (model,))
        with self._lock:
            for r in rows:
                self._vecs[r["item_id"]] = list(struct.unpack(f"{r['dim']}f", r["vec"]))

    def warm(self, kg, batch: int = 64) -> int:
        """Embed every node whose text changed since it was last embedded."""
        store = kg._store
        if store is None:
            return 0
        model = _cfg()["embed_model"]
        if not self._vecs:
            self.load_cache(store, model)
        hashes = {r["item_id"]: r["text_hash"] for r in store._rows(
            "SELECT item_id, text_hash FROM embeddings WHERE item_kind='node' AND model=?", (model,))}
        todo = []
        for nid, n in list(kg._nodes.items()):
            if n["type"] in _SKIP_TYPES:
                continue
            text = self.node_text(n)
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            if hashes.get(nid) != h:
                todo.append((nid, text, h))
        done = 0
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            vecs = self._post([t for _, t, _ in chunk])
            if vecs is None:
                break
            with store._lock:
                for (nid, _, h), v in zip(chunk, vecs):
                    u = self._unit(v)
                    store._conn.execute(
                        "INSERT OR REPLACE INTO embeddings(item_kind, item_id, model, dim, vec, text_hash) "
                        "VALUES ('node', ?, ?, ?, ?, ?)",
                        (nid, model, len(u), struct.pack(f"{len(u)}f", *u), h))
                    with self._lock:
                        self._vecs[nid] = u
            done += len(chunk)
        return done

    def warm_async(self, kg) -> None:
        if self._warming:
            return
        self._warming = True

        def run():
            try:
                n = self.warm(kg)
                if n:
                    logger.info("brain: embedded %d memory nodes", n)
            finally:
                self._warming = False
        threading.Thread(target=run, daemon=True, name="brain-embed").start()

    def search(self, query: str, live_ids: set[str], top_k: int = 30) -> list[tuple[str, float]]:
        if not self._vecs:
            return []
        qv = self._qcache.get(query)
        if qv is None:
            q = self._post([query])
            if not q:
                return []
            qv = self._unit(q[0])
            if len(self._qcache) > 256:
                self._qcache.pop(next(iter(self._qcache)))
            self._qcache[query] = qv
        import numpy as np
        with self._lock:
            ids = [nid for nid in self._vecs if nid in live_ids]
            if not ids:
                return []
            mat = np.asarray([self._vecs[i] for i in ids], dtype=np.float32)
        sims = mat @ np.asarray(qv, dtype=np.float32)
        scored = sorted(zip(ids, sims.tolist()), key=lambda x: -x[1])
        return [s for s in scored[:top_k] if s[1] > 0.45]


_EMBEDDER = Embedder()


def get_embedder() -> Embedder:
    return _EMBEDDER


# ------------------------------------------------------------------ query expansion
def expand_query(kg, text: str, recent_user_texts: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (expanded query, resolved entity labels)."""
    resolved: list[str] = []
    store = kg._store
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
    if store is not None:
        for w in words:
            nid = store.resolve_alias(w)
            if nid and kg.get_node(nid):
                resolved.append(kg.get_node(nid)["label"].split(":", 1)[-1])
    if _PRONOUN.search(text) and recent_user_texts:
        names = []
        for n in kg.get_nodes_by_type("person") + kg.get_nodes_by_type("project"):
            label = (n.get("properties", {}) or {}).get("name") or n["label"].split(":", 1)[-1]
            if len(label) >= 3:
                names.append(label)
        for past in reversed(recent_user_texts[-3:]):
            hits = [nm for nm in names if re.search(r"\b" + re.escape(nm.split()[0]) + r"\b", past, re.I)]
            if hits:
                resolved.extend(hits[:2])
                break
    query = text + (" " + " ".join(resolved) if resolved else "")
    return query, resolved


# ------------------------------------------------------------------ retrieval
def _rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, nid in enumerate(ranking):
            scores[nid] += 1.0 / (k + rank + 1)
    return scores


def _recency(node: dict) -> float:
    props = node.get("properties", {}) or {}
    for key in ("updated_at", "created_at", "date", "start_time", "due_date"):
        v = props.get(key)
        if isinstance(v, str) and len(v) >= 10:
            try:
                days = (datetime.now() - datetime.fromisoformat(v[:10])).days
                return 1.0 + 0.15 * math.exp(-max(days, 0) / 30)
            except ValueError:
                continue
    return 1.0


def rank(kg, query: str, top_k: int = 8) -> list[tuple[str, float]]:
    live = {nid for nid, n in kg._nodes.items()
            if n["type"] not in _SKIP_TYPES and n.get("properties", {}).get("search_result") != "true"}
    rankings = []
    if kg._store is not None:
        rankings.append([nid for nid, _ in kg._store.fts_search(query, 30) if nid in live])
    rankings.append([n["id"] for n in kg.search(query)[:30] if n["id"] in live])
    # Embeddings cost ~0.6 s per query on a CPU-only machine, so they are used only
    # when the two keyword rankers do not agree on a strong hit (top 3 of both).
    lexical_agree = len(rankings) == 2 and bool(set(rankings[0][:3]) & set(rankings[1][:3]))
    if kg._store is not None and _cfg()["use_embeddings"] and not lexical_agree:
        rankings.append([nid for nid, _ in get_embedder().search(query, live)])
    fused = _rrf([r for r in rankings if r])
    # graph expansion: neighbours of strong hits get a share of their score
    for nid, s in sorted(fused.items(), key=lambda x: -x[1])[:5]:
        for e in kg._adj_idx.get(nid, {}).get("out", []) + kg._adj_idx.get(nid, {}).get("in", []):
            other = e["target"] if e["source"] == nid else e["source"]
            if other in live and e.get("relation") not in ("precedes", "has_task_result", "references"):
                fused[other] = fused.get(other, 0.0) + 0.35 * s
    final = {nid: s * _TYPE_WEIGHT.get(kg._nodes[nid]["type"], 1.0) * _recency(kg._nodes[nid])
             for nid, s in fused.items() if nid in kg._nodes}
    return sorted(final.items(), key=lambda x: -x[1])[:top_k]


def _facts_for(kg, nid: str, limit: int = 5) -> list[str]:
    from backend.memory.sensitivity import is_sensitive
    out = []
    adj = kg._adj_idx.get(nid, {})
    for e in adj.get("out", []) + adj.get("in", []):
        rel = e.get("relation", "")
        if rel in ("precedes", "has_task_result", "references", "has_note", "has_conversation"):
            continue
        src, tgt = kg.get_node(e["source"]), kg.get_node(e["target"])
        if not src or not tgt or tgt["type"] in _SKIP_TYPES or src["type"] in _SKIP_TYPES:
            continue
        s_label = "you" if src["type"] == "user" else src["label"].split(":", 1)[-1]
        t_label = "you" if tgt["type"] == "user" else tgt["label"].split(":", 1)[-1]
        if is_sensitive(rel, t_label):
            continue
        out.append(f"  - {s_label} {rel.replace('_', ' ')} {t_label}")
        if len(out) >= limit:
            break
    return out


def retrieve(text: str, recent_user_texts: list[str] | None = None) -> str:
    """The "Relevant memories" block for this turn ('' when nothing relevant)."""
    from backend.memory.knowledge_graph import get_graph
    cfg = _cfg()
    kg = get_graph()
    if kg._store is not None:
        get_embedder().warm_async(kg)   # no-op when up to date or already running
    query, _resolved = expand_query(kg, text, recent_user_texts)
    budget_chars = cfg["token_budget"] * 4
    lines: list[str] = []
    used = 0
    seen_facts: set[str] = set()
    used_ids: list[str] = []
    for nid, _score in rank(kg, query, top_k=cfg["max_items"]):
        n = kg._nodes[nid]
        label = "you" if n["type"] == "user" else n["label"].split(":", 1)[-1]
        facts = [f for f in _facts_for(kg, nid) if f not in seen_facts]
        if n["type"] == "concept" and not facts and len(label) < 4:
            continue
        seen_facts.update(facts)
        block = "\n".join([f"- [m:{nid}] {label} ({n['type']})"] + facts)
        if used + len(block) > budget_chars:
            break
        lines.append(block)
        used_ids.append(nid)
        used += len(block) + 1
    # Brain V3 P9: how the user handled similar situations before (decision episodes)
    if kg._store is not None:
        try:
            from backend.brain.reflection import similar_decisions
            import json as _json
            for e in similar_decisions(kg._store, query):
                d = _json.loads(e.get("data") or "{}")
                line = (f"- [e:{e['id']}] Past decision ({e['day']}): {e['summary']} → chose "
                        f"{d.get('chosen', '?')}" + (f"; outcome: {e['outcome']}" if e.get("outcome") else ""))
                if used + len(line) <= budget_chars:
                    lines.append(line)
                    used_ids.append(e["id"])
                    used += len(line) + 1
        except Exception as exc:
            logger.debug("similar decisions: %s", exc)
        if used_ids:
            try:
                kg._store.touch(used_ids)          # recall is reinforcement (decay.py)
            except Exception:
                pass
    return redact("\n".join(lines))


def now_block() -> str:
    """Short always-on 'now' context: today's plan, overdue, waiting-on, open commitments."""
    parts = []
    try:  # Brain V3 P9: working memory (focus/away/time-block/recent notable signals)
        from backend.brain.working import get_working
        line = get_working().render()
        if line:
            parts.append(line)
    except Exception as e:
        logger.debug("working memory render: %s", e)
    try:  # Brain V3 P13: what the user seems to be working towards (inferred, evidence-backed)
        from backend.brain.intents import working
        goals = working(2)
        if goals:
            parts.append("Working towards: " + "; ".join(
                g["goal"] + (f" (by {g['horizon']})" if g.get("horizon") else "") for g in goals))
    except Exception as e:
        logger.debug("intents in now block: %s", e)
    try:
        from backend.core.planner_store import get_planner
        p = get_planner()
        today = p.list_items(view="today")[:6]
        if today:
            parts.append("Today: " + "; ".join(
                (i.get("title", "") + (f" ({str(i.get('due_at') or i.get('start_at') or '')[11:16]})"
                                       if len(str(i.get('due_at') or i.get('start_at') or '')) > 10 else ""))
                for i in today))
        waiting = p.list_items(view="waiting")[:3]
        if waiting:
            parts.append("Waiting on others: " + "; ".join(i.get("title", "") for i in waiting))
    except Exception as e:
        logger.debug("now_block planner: %s", e)
    try:
        from backend.memory.knowledge_graph import get_graph
        store = get_graph()._store
        if store is not None:
            open_c = [c for c in store.list_commitments("open", limit=5) if not c.get("planner_item_id")]
            if open_c:
                parts.append("You said you would: " + "; ".join(c["text"] for c in open_c[:3]))
    except Exception:
        pass
    return redact("\n".join(parts))
