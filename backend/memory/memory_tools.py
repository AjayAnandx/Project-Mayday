from backend.memory.knowledge_graph import get_graph, extract_keywords


def remember(entity: str, relation: str, value: str, context: str = "") -> str:
    kg = get_graph()
    results = kg.search(entity)
    source_id = None
    for r in results:
        if r["label"].lower() == entity.lower():
            source_id = r["id"]
            break
    if not source_id:
        source_id = kg.add_node("concept", entity, {"context": context})
    target_results = kg.search(value)
    target_id = None
    for r in target_results:
        if r["label"].lower() == value.lower():
            target_id = r["id"]
            break
    if not target_id:
        target_id = kg.add_node("concept", value, {})
    kg.add_edge(source_id, target_id, relation)
    return f"Remembered: {entity} --[{relation}]--> {value}"


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
    kg.add_node("concept", query, {"search_result": "true"})
    return "\n".join(lines)


def recall_entity(name: str) -> str:
    kg = get_graph()
    results = kg.search(name)
    exact = None
    for r in results:
        if r["label"].lower() == name.lower():
            exact = r
            break
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


def forget(entity: str, relation: str, value: str) -> str:
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
