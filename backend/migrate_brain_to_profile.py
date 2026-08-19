"""One-time backfill: reconcile the Knowledge Graph 'Brain' (including MAGMA's
entity subgraph) into the AwarenessStore (user_profile.json).

MAGMA is a typed-edge wrapper over the SAME KnowledgeGraph, so its entity graph
lives in the same store (nodes typed person/object/place with RAW labels, linked
by `subgraph:"entity"` edges). We import the genuinely user-relevant parts:

  - every `belief:*` node (the awareness mirror) -> belief
  - MAGMA `person` nodes -> relations   (the core "entity graph" value)
  - MAGMA `object` nodes -> belongings
  - user-node edges whose target is a person/object/place node -> same mapping

We deliberately SKIP generic concept/entity nodes, project tasks, and document
files — those are not user-profile facts and would just add noise.

Duplicate prevention:
  - awareness (slot, value) is deduped in-memory and via add_belief/find_belief
  - pre-existing `belief:{slot}:{value}` graph nodes are not re-created
  - tombstones block previously-deleted values from re-importing
Idempotent: re-running adds nothing new.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.memory.knowledge_graph import get_graph
from backend.core.user_awareness import get_awareness_store, SLOTS
from backend.memory.memory_tools import _classify_user_fact, _looks_like_name

_INTERNAL_TYPES = {
    "project", "research", "todo", "event", "conversation", "document",
    "tag", "date", "build_lesson", "skill", "component", "note", "reminder",
    "task",
}
# Only these entity kinds are meaningful as user-profile facts.
_ENTITY_SLOT = {"person": "relations", "object": "belongings"}


def _is_junk(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if v.startswith("belief:") or v.startswith("person:"):
        return True
    if v.lower() in ("user", "the user", "ajay"):
        return True
    if "/" in v or v.endswith(".md") or v.endswith(".txt"):  # task:/file paths
        return True
    return False


def _parse_belief_label(label: str):
    if not label.startswith("belief:"):
        return None, None
    parts = label.split(":", 2)
    if len(parts) != 3:
        return None, None
    slot, value = parts[1], parts[2]
    if not value.strip() or value.startswith("belief:") or slot not in SLOTS:
        return None, None
    return slot, value


def main():
    kg = get_graph()
    store = get_awareness_store()
    graph = kg.get_full_graph()
    label_by_id = {n["id"]: n for n in graph["nodes"]}

    existing = {(b["slot"], b["value"].lower()) for b in store.list_beliefs()}
    added = 0
    skipped = 0

    def _add(slot, value, provenance="inference", confidence=0.7):
        nonlocal added, skipped
        if not slot or not value or slot not in SLOTS or _is_junk(value):
            return
        if (slot, value.lower()) in existing:
            skipped += 1
            return
        if kg.get_node_by_label(f"belief:{slot}:{value}"):
            skipped += 1
            return
        res = store.add_belief(slot, value, provenance=provenance,
                               confidence=confidence)
        if isinstance(res, dict) and "error" in res:
            skipped += 1
            return
        existing.add((slot, value.lower()))
        added += 1

    # 1. belief:* nodes already in the graph
    for node in graph["nodes"]:
        slot, value = _parse_belief_label(node.get("label", ""))
        if slot:
            props = node.get("properties", {})
            conf = float(props.get("confidence", 0.7))
            prov = props.get("provenance", "inference")
            _add(slot, value, provenance=prov, confidence=conf)

    # 2. user:Mayday-user edges to person/object/place nodes
    user_node = kg.get_node_by_label("user:Mayday-user")
    if user_node:
        user_id = user_node["id"]
        for edge in graph["edges"]:
            if edge["source"] != user_id:
                continue
            target = label_by_id.get(edge["target"])
            if not target or target.get("type") not in _ENTITY_SLOT:
                continue
            value = target.get("label", "")
            if _is_junk(value):
                continue
            _add(_ENTITY_SLOT[target["type"]], value, provenance="explicit", confidence=0.9)

    # 3. MAGMA entity-graph nodes (person/object) -> relations / belongings
    user_name = store.get_user_name()
    for node in graph["nodes"]:
        ntype = node.get("type")
        if ntype not in _ENTITY_SLOT:
            continue
        value = node.get("properties", {}).get("name") or node.get("label", "")
        value = value.replace("person:", "", 1).strip()
        if _is_junk(value):
            continue
        if user_name and value.lower() == user_name.lower():
            continue
        _add(_ENTITY_SLOT[ntype], value, provenance="inference", confidence=0.7)

    # 4. set canonical user name from identity beliefs
    for b in store.list_beliefs(slot="identity"):
        if _looks_like_name(b["value"]):
            store.set_user_name(b["value"])
            break

    print(f"Backfill complete: {added} belief(s) added, {skipped} skipped (already present).")
    print(f"User name: {store.get_user_name()}")
    by_slot = {}
    for b in store.list_beliefs():
        by_slot[b["slot"]] = by_slot.get(b["slot"], 0) + 1
    for s in SLOTS:
        if by_slot.get(s):
            print(f"  {s}: {by_slot[s]}")


if __name__ == "__main__":
    main()
