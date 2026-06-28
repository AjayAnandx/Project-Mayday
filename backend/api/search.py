from fastapi import APIRouter, Query

from backend.core.data_store import get_store
from backend.core.operation_log import get_operation_log
from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/search", tags=["search"])


def _snippet(text: str, query: str, max_len: int = 100) -> str:
    if not text or not query:
        return (text or "")[:max_len]
    q = query.lower()
    text_lower = text.lower()
    idx = text_lower.find(q)
    if idx == -1:
        return text[:max_len]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(q) + 40)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet[:max_len]


@router.get("")
def unified_search(q: str = Query("", min_length=1), limit: int = 20):
    store = get_store()
    kg = get_graph()
    olog = get_operation_log()

    todos = store.list_todos(query=q)

    events = store.list_events(query=q)

    store._ensure_conv_text_index()
    conv_ids = {doc_id for doc_id, _ in store._conv_text_idx.search(q, limit * 5)}
    conversations = []
    for c in store._conv_idx.values():
        if c["id"] not in conv_ids:
            continue
        if len(conversations) >= limit:
            break
        conv = store.get_conversation(c["id"])
        if not conv:
            continue
        text = conv.get("title", "")
        for m in conv.get("messages", []):
            text += " " + m.get("content", "")
        snippet = _snippet(text, q)
        conversations.append({
            "id": conv["id"],
            "title": conv.get("title", "Untitled"),
            "date": c.get("date", conv.get("created_at", ""))[:10],
            "snippet": snippet,
        })

    graph_nodes = []
    for node in kg.search(q):
        if len(graph_nodes) >= limit:
            break
        graph_nodes.append({
            "id": node["id"],
            "label": node["label"],
            "type": node["type"],
            "snippet": _snippet(str(node.get("properties", {})), q),
        })

    operations = olog.query(query=q, limit=limit)

    return {
        "todos": [
            {
                "id": t["id"],
                "title": t["title"],
                "snippet": _snippet(t.get("description", ""), q) or t["title"],
            }
            for t in todos[:limit]
        ],
        "events": [
            {
                "id": e["id"],
                "title": e["title"],
                "snippet": f"{e['start_time'][:10]} — {e.get('description', '')[:60]}" if e.get("description") else e["start_time"][:10],
            }
            for e in events[:limit]
        ],
        "conversations": conversations[:limit],
        "graph_nodes": graph_nodes[:limit],
        "operations": [
            {
                "id": op.get("id", ""),
                "action": op.get("action", ""),
                "entity_type": op.get("entity_type", ""),
                "entity_name": op.get("entity_name", ""),
                "timestamp": op.get("timestamp", ""),
            }
            for op in operations[:limit]
        ],
    }


@router.get("/prefix")
def prefix_search(q: str = Query("", min_length=1), limit: int = 20):
    store = get_store()
    ids = store._trie.search(q)
    todos = []
    events = []
    for t in store._todos:
        if f"todo:{t['id']}" in ids:
            if len(todos) >= limit:
                break
            todos.append({"id": t["id"], "title": t["title"]})
    for e in store._events:
        key = f"event:{e['id']}"
        if key in ids:
            if len(events) >= limit:
                break
            events.append({"id": e["id"], "title": e["title"]})
    return {"todos": todos, "events": events, "conversations": []}
