from fastapi import APIRouter, HTTPException, Query

from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/graph")
def get_full_graph():
    return get_graph().get_clean_graph()


@router.get("/graph/search")
def search_graph(q: str = Query("")):
    if not q:
        return get_graph().get_clean_graph()
    results = get_graph().search(q)
    return {"nodes": results, "edges": []}


@router.get("/graph/node/{node_id}")
def get_node(node_id: str):
    kg = get_graph()
    node = kg.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    subgraph = kg.get_subgraph(node_id, depth=2)
    return {"node": node, "subgraph": subgraph}


@router.delete("/graph/node/{node_id}")
def delete_node(node_id: str):
    kg = get_graph()
    if not kg.remove_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")
    return {"deleted": True}


@router.get("/stats")
def memory_stats():
    return get_graph().stats()


@router.post("/repair")
def repair_memory():
    kg = get_graph()
    report = kg.repair_graph()
    return report
