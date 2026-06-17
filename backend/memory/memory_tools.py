from backend.memory.knowledge_graph import get_graph, extract_keywords

_PREFIXES = ("project:", "tag:", "date:", "concept:")


def _check_tombstone(kg, name: str) -> dict | None:
    record = kg.is_deleted(name)
    if record:
        return record
    stripped = name
    for p in _PREFIXES:
        if stripped.startswith(p):
            stripped = stripped[len(p):]
            break
    if stripped != name:
        record = kg.is_deleted(stripped)
        if record:
            return record
    for p in _PREFIXES:
        prefixed = p + name
        record = kg.is_deleted(prefixed)
        if record:
            return record
    return None


def _find_exact_node(kg, name: str) -> dict | None:
    for r in kg.search(name):
        if r["label"].strip().lower() == name.strip().lower():
            return r
    for p in _PREFIXES:
        prefixed = p + name
        for r in kg.search(prefixed):
            if r["label"].strip().lower() == prefixed.strip().lower():
                return r
    return None


def remember(entity: str, relation: str, value: str, context: str = "", node_type: str = "concept") -> str:
    kg = get_graph()
    entity = entity.strip()
    value = value.strip()
    tombstone = _check_tombstone(kg, entity)
    if tombstone:
        return f"Entity '{entity}' was previously deleted on {tombstone['deleted_on']}. Not recreating it."
    found = _find_exact_node(kg, entity)
    source_id = found["id"] if found else None
    if not source_id:
        source_id = kg.add_node(node_type, entity, {"context": context})
    target_id = None
    for r in kg.search(value):
        if r["label"].strip().lower() == value.lower():
            target_id = r["id"]
            break
    if not target_id:
        target_id = kg.add_node("concept", value, {})
    edge_id = kg.add_edge_if_missing(source_id, target_id, relation)
    if edge_id:
        return f"Remembered: {entity} --[{relation}]--> {value}"
    return f"Already remembered: {entity} --[{relation}]--> {value}"


def recall(query: str) -> str:
    kg = get_graph()
    results = kg.search(query)
    if not results:
        return f"No memories found for: {query}"
    lines = []
    for node in results[:10]:
        lines.append(f"- {node['type']}: {node['label']}")
        props = node.get("properties", {})
        if props:
            for k, v in props.items():
                if v:
                    lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def recall_entity(name: str) -> str:
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


def delete_entity(name: str) -> str:
    kg = get_graph()
    exact = _find_exact_node(kg, name)
    if not exact:
        return f"No entity found: {name}"
    kg.remove_node(exact["id"])
    kg.add_tombstone(exact["label"])
    return f"Deleted entity: {name} (type: {exact['type']})"


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
        return f"Forgot: {entity} --[{relation}]--> {value} ({removed} edge(s) removed)"
    return f"No matching memory found to forget: {entity} --[{relation}]--> {value}"
