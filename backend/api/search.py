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
    
    convs_raw = store.list_conversations()
    conversations = []
    for c in convs_raw:
        conv = store.get_conversation(c["id"])
        if not conv:
            continue
        title_match = q.lower() in conv.get("title", "").lower()
        msg_match = any(q.lower() in m.get("content", "").lower() for m in conv.get("messages", []))
        if not title_match and not msg_match:
            continue
        snippet = ""
        for m in conv.get("messages", []):
            if q.lower() in m.get("content", "").lower():
                snippet = _snippet(m["content"], q)
                break
        if not snippet:
            snippet = _snippet(conv.get("title", ""), q)
        conversations.append({
            "id": conv["id"],
            "title": conv.get("title", "Untitled"),
            "date": c.get("created_at", "")[:10],
            "snippet": snippet,
        })
    
    graph_nodes = []
    for node in kg.search(q):
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
