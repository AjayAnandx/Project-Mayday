from backend.memory.knowledge_graph import get_graph

_PREFIXES = ("project:", "tag:", "date:", "concept:")


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
    kg.set_status(exact["label"], "scraped")
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
        return f"Forgot: {entity} --[{relation}]--> {value} ({removed} edge(s) removed)"
    return f"No matching memory found to forget: {entity} --[{relation}]--> {value}"


def set_status(name: str, status: str) -> str:
    kg = get_graph()
    exact = _find_exact_node(kg, name)
    if not exact:
        return f"No entity found: {name}"
    old = exact["properties"].get("status", "active")
    kg.set_status(exact["label"], status)
    return f"Updated '{name}' status: {old} → {status}"
