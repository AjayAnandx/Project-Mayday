from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

_PREFIXES = ("project:", "research:", "tag:", "date:", "concept:")

# Bridges generic `remember` calls about the user into the AwarenessStore
# (user_profile.json) so the per-turn world-model snapshot and `recall` can
# surface them. Heuristics only — non-user facts stay graph-only.
_USER_SLOT_RELATIONS = {
    "name": "identity", "is": "identity", "called": "identity", "am": "identity",
    "nickname": "identity",
    "like": "favorites", "likes": "favorites", "prefer": "favorites",
    "prefers": "favorites", "favorite": "favorites", "favourite": "favorites",
    "enjoy": "favorites", "enjoys": "favorites",
    "have": "belongings", "has": "belongings", "own": "belongings",
    "owns": "belongings", "pet": "belongings", "belong": "belongings",
    "want": "goals", "wants": "goals", "goal": "goals", "goals": "goals",
    "working toward": "goals", "working towards": "goals", "aspire": "goals",
    "problem": "problems", "struggle": "problems", "struggles": "problems",
    "stress": "problems", "stressed": "problems", "worry": "problems",
    "worries": "problems", "issue": "problems", "challenge": "problems",
}
_USER_ENTITY_HINTS = {"user", "me", "i", "my", "myself", "mayday-user", "users"}
_RELATION_PERSON = {
    "friend", "friends", "brother", "sister", "mom", "mother", "dad", "father",
    "wife", "husband", "partner", "spouse", "son", "daughter", "colleague",
    "boss", "cousin", "uncle", "aunt", "grandmother", "grandfather",
    "girlfriend", "boyfriend",
}
# Transient states/emotions/conditions — these are NOT identities even when
# stated with "am"/"is" (e.g. "I am stressed"). They belong in `problems`/
# `state`, consistent with awareness_observer.py rule 67.
_STATE_WORDS = {
    "stressed", "anxious", "sick", "tired", "overwhelmed", "depressed",
    "sad", "happy", "angry", "calm", "sleepy", "hungry", "ill", "unwell",
    "exhausted", "lonely", "excited", "scared", "afraid", "nervous",
}


def _looks_like_name(value: str) -> bool:
    v = value.strip()
    if not v or len(v) > 40 or any(c.isdigit() for c in v):
        return False
    words = v.split()
    if not (1 <= len(words) <= 3):
        return False
    return all(w[:1].isupper() or not w[:1].isalpha() for w in words)


def _classify_user_fact(entity: str, relation: str, value: str):
    e = entity.strip().lower()
    r = relation.strip().lower()
    v = value.strip()
    if r in _RELATION_PERSON or e in _RELATION_PERSON:
        return "relations", v
    slot = _USER_SLOT_RELATIONS.get(r)
    # A state/emotion word stated with "am"/"is"/"are" is not an identity.
    if slot == "identity" and v.lower() in _STATE_WORDS:
        return "problems", v
    if slot:
        return slot, v
    if e in _USER_ENTITY_HINTS:
        if v.lower() in _STATE_WORDS:
            return "problems", v
        if _looks_like_name(v):
            return "identity", v
        return "context", v
    return None, None


def _maybe_learn_user_fact(entity: str, relation: str, value: str) -> None:
    """Mirror an obvious user fact from `remember` into the AwarenessStore.

    Never raises — a failure here must not break the graph write path.
    Duplicate prevention: if the same fact already lives in the awareness
    store OR is already represented as a `belief:*` node in the Brain, we skip
    creating a second copy (avoids concept-node + belief-node duplication).
    """
    try:
        from backend.core.config import load_config
        if not load_config().get("awareness", {}).get("enabled", False):
            return
        from backend.core.user_awareness import get_awareness_store
        slot, val = _classify_user_fact(entity, relation, value)
        if not slot or not val:
            return
        store = get_awareness_store()
        # Already in the profile?
        if store.find_belief(slot, val):
            return
        # Already represented as a belief node in the Brain?
        if get_graph().get_node_by_label(f"belief:{slot}:{val}"):
            return
        res = store.add_belief(slot, val, provenance="explicit", confidence=0.9)
        if isinstance(res, dict) and "error" in res:
            return
        if slot == "identity" and _looks_like_name(val):
            store.set_user_name(val)
    except Exception:
        return


def _find_exact_node(kg, name: str) -> dict | None:
    stripped = name.strip()
    node = kg.get_node_by_label(stripped)
    if node:
        return node
    for p in _PREFIXES:
        node = kg.get_node_by_label(p + stripped)
        if node:
            return node
    return None


def _get_status(kg, name: str) -> str | None:
    node = _find_exact_node(kg, name)
    if node:
        return node.get("properties", {}).get("status")
    return None


def remember(entity: str, relation: str, value: str, context: str = "", node_type: str = "concept") -> str:
    kg = get_graph()
    entity = entity.strip()
    value = value.strip()
    status = _get_status(kg, entity)
    if status == "scraped":
        return f"Entity '{entity}' already exists with status 'scraped'. Use set_status() to reactivate it first if needed."
    found = _find_exact_node(kg, entity)
    source_id = found["id"] if found else None
    if not source_id:
        source_id = kg.add_node(node_type, entity, {"context": context})
    target_node = kg.get_node_by_label(value.strip())
    target_id = target_node["id"] if target_node else None
    if not target_id:
        target_id = kg.add_node("concept", value, {})
    edge_id = kg.add_edge_if_missing(source_id, target_id, relation)
    if edge_id:
        get_operation_log().record("create", "memory", source_id, entity,
                                    details={"relation": relation, "target": value})
        _maybe_learn_user_fact(entity, relation, value)
        return f"Remembered: {entity} --[{relation}]--> {value}"
    return f"Already remembered: {entity} --[{relation}]--> {value}"


def recall(query: str = "") -> str:
    if not query or not query.strip():
        return "No query provided. Call recall(\"your search term\") with a specific term to search memories."
    kg = get_graph()
    results = kg.search(query)
    lines = []
    for node in results[:10]:
        lines.append(f"- {node['type']}: {node['label']}")
        props = node.get("properties", {})
        if props:
            for k, v in props.items():
                if v:
                    lines.append(f"  {k}: {v}")
    # Also surface user facts stored in the AwarenessStore (user_profile.json),
    # so they are recallable regardless of whether `remember` or `learn_belief` wrote them.
    try:
        from backend.core.user_awareness import get_awareness_store
        for b in get_awareness_store().search_beliefs(query):
            lines.append(f"- belief[{b['slot']}]: {b['value']} (conf {b['confidence']:.2f})")
    except Exception:
        pass
    if not lines:
        return f"No memories found for: {query}"
    return "\n".join(lines)


def recall_entity(name: str = "", entity: str = "") -> str:
    name = entity or name
    if not name:
        return "Missing required parameter: name or entity"
    kg = get_graph()
    exact = _find_exact_node(kg, name)
    if not exact:
        return f"No entity found: {name}"
    sg = kg.get_subgraph(exact["id"], depth=2)
    lines = [f"=== {exact['type']}: {exact['label']} ==="]
    props = exact.get("properties", {})
    if props:
        for k, v in props.items():
            if v:
                lines.append(f"  {k}: {v}")
    lines.append("")
    if sg["edges"]:
        lines.append("Relationships:")
        for edge in sg["edges"]:
            source_node = kg.get_node(edge["source"])
            target_node = kg.get_node(edge["target"])
            s_label = source_node["label"] if source_node else edge["source"]
            t_label = target_node["label"] if target_node else edge["target"]
            lines.append(f"  {s_label} --[{edge['relation']}]--> {t_label}")
    return "\n".join(lines)


def delete_entity(name: str = "", entity: str = "") -> str:
    name = entity or name
    if not name:
        return "Missing required parameter: name or entity"
    kg = get_graph()
    exact = _find_exact_node(kg, name)
    if not exact:
        return f"No entity found: {name}"
    kg.set_status(exact["label"], "scraped")
    get_operation_log().record("delete", exact["type"], exact["id"], name,
                                details={"status": "scraped"})
    return f"Scraped entity: {name} (type: {exact['type']}). It remains in the knowledge graph with status 'scraped' and can be reactivated with set_status()."


def forget(entity: str, relation: str | None = None, value: str | None = None) -> str:
    if relation is None or value is None:
        return delete_entity(entity)
    kg = get_graph()
    source_results = kg.search(entity)
    target_results = kg.search(value)
    removed = 0
    for s in source_results:
        for t in target_results:
            if kg.remove_edge(s["id"], t["id"], relation):
                removed += 1
    if removed:
        get_operation_log().record("delete", "memory", entity, entity,
                                    details={"relation": relation, "target": value})
        return f"Forgot: {entity} --[{relation}]--> {value} ({removed} edge(s) removed)"
    return f"No matching memory found to forget: {entity} --[{relation}]--> {value}"


def set_status(name: str = "", status: str = "", entity: str = "") -> str:
    name = entity or name
    if not name:
        return "Missing required parameter: name or entity"
    if not status:
        return "Missing required parameter: status"
    kg = get_graph()
    exact = _find_exact_node(kg, name)
    if not exact:
        return f"No entity found: {name}"
    old = exact["properties"].get("status", "active")
    kg.set_status(exact["label"], status)
    get_operation_log().record("update", exact["type"], exact["id"], name,
                                details={"status": f"{old} -> {status}"})
    return f"Updated '{name}' status: {old} → {status}"
