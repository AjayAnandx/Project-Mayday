"""Brain V3 P9: memory strength, decay and archiving (nightly).

    strength = importance × sqrt(reinforcements + 1) × exp(−age_days / half_life(type))

  * importance: by node type at first sight (people/goals/values high, generic concepts low)
  * reinforcements: memory_stats.touch() — recall used it, it was re-mentioned or confirmed
  * age: days since it was last reinforced (or first seen by the decay pass)
  * half_life: by type; identity, people, values, goals, constraints never decay

Only weak, loosely connected, unconfirmed generic items are ARCHIVED (moved to the
`archive` table with their edges, restorable for 90 days). Anything a fact points at,
anything with several connections, and every protected type is kept.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.core.config import load_config

IMPORTANCE = {"user": 1.0, "person": 0.9, "goal": 0.9, "value": 0.9, "constraint": 0.85, "project": 0.8,
              "event": 0.7, "todo": 0.6, "habit": 0.7, "idea": 0.6, "place": 0.6, "organization": 0.6,
              "research": 0.6, "document": 0.6, "concept": 0.3}
HALF_LIFE_DAYS = {"habit": 60, "idea": 180, "concept": 90, "event": 120, "todo": 120, "research": 180,
                  "document": 180, "place": 365}
PROTECTED = {"user", "person", "goal", "value", "constraint", "project", "organization"}
# bookkeeping nodes handled by their own stores / rules
SKIP = {"conversation", "build_lesson", "build_preference", "question", "email", "tag", "date"}


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("decay", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "floor": float(c.get("floor", 0.08)),
            "max_archive_per_night": int(c.get("max_archive_per_night", 200)),
            "archive_days": int(c.get("archive_days", 90))}


def _days_since(ts: str | None, now: datetime) -> float:
    if not ts:
        return 0.0
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (now - t).total_seconds() / 86400)
    except ValueError:
        return 0.0


def strength(node_type: str, stat: dict | None, now: datetime) -> float:
    imp = (stat or {}).get("importance") or IMPORTANCE.get(node_type, 0.4)
    reinf = (stat or {}).get("reinforcements") or 0
    half = HALF_LIFE_DAYS.get(node_type)
    if node_type in PROTECTED or (half is None and node_type not in IMPORTANCE):
        decay = 1.0
    else:
        age = _days_since((stat or {}).get("last_used") or (stat or {}).get("created_at"), now)
        decay = math.exp(-age / (half or 90))
    return imp * math.sqrt(reinf + 1) * decay


def run(kg, now: datetime | None = None) -> dict:
    """Score every node, archive the weakest eligible ones. Returns a report for Brain health."""
    cfg = _cfg()
    store = kg._store
    if store is None or not cfg["enabled"]:
        return {"skipped": True}
    now = now or datetime.now(timezone.utc)
    stats = {r["item_id"]: r for r in store._rows("SELECT * FROM memory_stats")}
    # Never archive: fact-backed items, and anything directly attached to the user or a
    # person (older personal facts like "likes biryani" have no fact_id but matter).
    fact_targets = set()
    personal = {nid for nid, n in kg._nodes.items() if n["type"] in ("user", "person")}
    # "self" nodes the profile also reads: the node named after the user, "user", "me"
    for n in kg.get_nodes_by_type("user"):
        name = (n.get("properties") or {}).get("name")
        for lbl in (name, "user", "me"):
            node = kg.get_node_by_label(lbl) if lbl else None
            if node:
                personal.add(node["id"])
    for e in kg._edges:
        if (e.get("properties") or {}).get("fact_id"):
            fact_targets.update((e["source"], e["target"]))
        if e["source"] in personal:
            fact_targets.add(e["target"])
        if e["target"] in personal:
            fact_targets.add(e["source"])
    unseen = [nid for nid, n in kg._nodes.items() if nid not in stats and n["type"] not in SKIP]
    if unseen:   # first sight: start their clock now, with type importance
        stamp = now.isoformat()
        with store._lock:
            store._conn.executemany(
                "INSERT OR IGNORE INTO memory_stats(item_id, importance, reinforcements, last_used, created_at) "
                "VALUES (?,?,0,NULL,?)",
                [(nid, IMPORTANCE.get(kg._nodes[nid]["type"], 0.4), stamp) for nid in unseen])
        stats.update({r["item_id"]: r for r in store._rows("SELECT * FROM memory_stats")})
    weak, scored = [], 0
    for nid, n in list(kg._nodes.items()):
        if n["type"] in SKIP:
            continue
        scored += 1
        s = strength(n["type"], stats.get(nid), now)
        degree = len(kg._adj_idx.get(nid, {}).get("out", [])) + len(kg._adj_idx.get(nid, {}).get("in", []))
        confirmed = (n.get("properties") or {}).get("confirmed") in (True, "true")
        if (s < cfg["floor"] and n["type"] not in PROTECTED and nid not in fact_targets
                and degree <= 1 and not confirmed):
            weak.append((s, nid))
    weak.sort()
    archived = []
    for s, nid in weak[: cfg["max_archive_per_night"]]:
        node = kg.get_node(nid)
        adj = kg._adj_idx.get(nid, {})
        store.archive_item(nid, "node", {"node": node, "edges": adj.get("out", []) + adj.get("in", [])},
                           reason=f"strength {s:.3f} below floor")
        kg.remove_node(nid)
        archived.append(node["label"][:60])
    purged = store.purge_archive(cfg["archive_days"])
    return {"scored": scored, "archived": len(archived), "archived_examples": archived[:5],
            "purged_from_archive": purged}


def restore(kg, item_id: str) -> bool:
    """Bring an archived node (and its edges whose endpoints still exist) back."""
    import json
    store = kg._store
    rows = store._rows("SELECT * FROM archive WHERE item_id=?", (item_id,))
    if not rows:
        return False
    data = json.loads(rows[0]["payload"])
    node = data["node"]
    with kg._lock:
        kg._nodes[node["id"]] = node
        kg._index_node(node)
        for e in data.get("edges", []):
            if e["source"] in kg._nodes and e["target"] in kg._nodes:
                kg._edges.append(e)
                kg._index_edge(e)
        kg._save()
    with store._lock:
        store._conn.execute("DELETE FROM archive WHERE item_id=?", (item_id,))
    store.touch([item_id], importance=0.6)
    return True
