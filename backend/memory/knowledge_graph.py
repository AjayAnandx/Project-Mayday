import json
import uuid
import re
import threading
from pathlib import Path

from backend.core.config import load_config


_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
    "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself",
    "she", "her", "hers", "herself", "it", "its", "itself", "they", "them",
    "their", "theirs", "themselves", "this", "that", "these", "those",
    "and", "but", "or", "nor", "not", "so", "yet", "if", "because",
    "as", "until", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "to", "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "any", "both", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "too", "very",
    "please", "can", "will", "just", "also", "now", "what", "which", "who",
})


def extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) > 2 and t not in _STOP_WORDS]


class KnowledgeGraph:
    def __init__(self):
        cfg = load_config()
        path = cfg.get("memory", {}).get("graph_path", "memory_graph.json")
        self._path = Path(__file__).resolve().parent.parent.parent / path
        self._lock = threading.Lock()
        self._nodes: dict[str, dict] = {}
        self._edges: list[dict] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._nodes = {n["id"]: n for n in data.get("nodes", [])}
                self._edges = data.get("edges", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        data = {
            "nodes": list(self._nodes.values()),
            "edges": self._edges,
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_node(self, type: str, label: str, properties: dict | None = None) -> str:
        with self._lock:
            node_id = uuid.uuid4().hex[:12]
            self._nodes[node_id] = {
                "id": node_id,
                "type": type,
                "label": label,
                "properties": properties or {},
            }
            self._save()
            return node_id

    def add_edge(self, source: str, target: str, relation: str, properties: dict | None = None) -> str:
        with self._lock:
            edge_id = uuid.uuid4().hex[:12]
            self._edges.append({
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "properties": properties or {},
            })
            self._save()
            return edge_id

    def search(self, query: str) -> list[dict]:
        with self._lock:
            q = query.lower()
            results = []
            for node in self._nodes.values():
                if q in node["label"].lower():
                    results.append(node)
                    continue
                for v in node.get("properties", {}).values():
                    if isinstance(v, str) and q in v.lower():
                        results.append(node)
                        break
            return results

    def get_subgraph(self, node_id: str, depth: int = 2) -> dict:
        with self._lock:
            if node_id not in self._nodes:
                return {"nodes": [], "edges": []}
            visited = {node_id}
            queue = [(node_id, 0)]
            sub_nodes = []
            sub_edges = []
            while queue:
                nid, d = queue.pop(0)
                sub_nodes.append(self._nodes[nid])
                if d >= depth:
                    continue
                for edge in self._edges:
                    if edge["source"] == nid and edge["target"] not in visited:
                        visited.add(edge["target"])
                        queue.append((edge["target"], d + 1))
                        sub_edges.append(edge)
                    elif edge["target"] == nid and edge["source"] not in visited:
                        visited.add(edge["source"])
                        queue.append((edge["source"], d + 1))
                        sub_edges.append(edge)
            return {"nodes": sub_nodes, "edges": sub_edges}

    def get_full_graph(self) -> dict:
        with self._lock:
            return {
                "nodes": list(self._nodes.values()),
                "edges": list(self._edges),
            }

    def remove_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self._nodes:
                return False
            del self._nodes[node_id]
            self._edges = [e for e in self._edges if e["source"] != node_id and e["target"] != node_id]
            self._save()
            return True

    def remove_edge(self, source: str, target: str, relation: str) -> bool:
        with self._lock:
            before = len(self._edges)
            self._edges = [e for e in self._edges if not (e["source"] == source and e["target"] == target and e["relation"] == relation)]
            if len(self._edges) != before:
                self._save()
                return True
            return False

    def stats(self) -> dict:
        with self._lock:
            node_types = {}
            for n in self._nodes.values():
                t = n["type"]
                node_types[t] = node_types.get(t, 0) + 1
            return {
                "nodes": len(self._nodes),
                "edges": len(self._edges),
                "node_types": node_types,
            }

    def get_node(self, node_id: str) -> dict | None:
        with self._lock:
            return self._nodes.get(node_id)

    def sync_todo(self, todo: dict):
        with self._lock:
            existing = None
            for n in self._nodes.values():
                if n["type"] == "todo" and n["properties"].get("todo_id") == todo["id"]:
                    existing = n
                    break
            if existing:
                existing["label"] = todo["title"]
                existing["properties"].update({
                    "description": todo.get("description", ""),
                    "due_date": todo.get("due_date"),
                    "priority": todo.get("priority"),
                    "completed": todo.get("completed", False),
                    "tags": todo.get("tags", []),
                })
            else:
                node_id = uuid.uuid4().hex[:12]
                self._nodes[node_id] = {
                    "id": node_id,
                    "type": "todo",
                    "label": todo["title"],
                    "properties": {
                        "todo_id": todo["id"],
                        "description": todo.get("description", ""),
                        "due_date": todo.get("due_date"),
                        "priority": todo.get("priority"),
                        "completed": todo.get("completed", False),
                        "tags": todo.get("tags", []),
                    },
                }
                for tag in todo.get("tags", []):
                    tag_node_id = self._ensure_tag_node(tag)
                    self._edges.append({
                        "id": uuid.uuid4().hex[:12],
                        "source": node_id,
                        "target": tag_node_id,
                        "relation": "has_tag",
                        "properties": {},
                    })
            self._save()

    def sync_event(self, event: dict):
        with self._lock:
            existing = None
            for n in self._nodes.values():
                if n["type"] == "event" and n["properties"].get("event_id") == event["id"]:
                    existing = n
                    break
            if existing:
                existing["label"] = event["title"]
                existing["properties"].update({
                    "description": event.get("description", ""),
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "all_day": event.get("all_day", False),
                })
            else:
                node_id = uuid.uuid4().hex[:12]
                self._nodes[node_id] = {
                    "id": node_id,
                    "type": "event",
                    "label": event["title"],
                    "properties": {
                        "event_id": event["id"],
                        "description": event.get("description", ""),
                        "start_time": event.get("start_time"),
                        "end_time": event.get("end_time"),
                        "all_day": event.get("all_day", False),
                    },
                }
            self._save()

    def sync_conversation(self, conv: dict):
        with self._lock:
            existing = None
            for n in self._nodes.values():
                if n["type"] == "conversation" and n["properties"].get("conv_id") == conv["id"]:
                    existing = n
                    break
            if existing:
                existing["label"] = conv.get("title", "Conversation")
                existing["properties"]["message_count"] = len(conv.get("messages", []))
            else:
                node_id = uuid.uuid4().hex[:12]
                self._nodes[node_id] = {
                    "id": node_id,
                    "type": "conversation",
                    "label": conv.get("title", "Conversation"),
                    "properties": {
                        "conv_id": conv["id"],
                        "message_count": len(conv.get("messages", [])),
                    },
                }
            self._save()

    def _ensure_tag_node(self, tag: str) -> str:
        for n in self._nodes.values():
            if n["type"] == "tag" and n["label"] == tag:
                return n["id"]
        node_id = uuid.uuid4().hex[:12]
        self._nodes[node_id] = {
            "id": node_id,
            "type": "tag",
            "label": tag,
            "properties": {},
        }
        return node_id

    def delete_todo_node(self, todo_id: str):
        with self._lock:
            to_remove = [nid for nid, n in self._nodes.items() if n["type"] == "todo" and n["properties"].get("todo_id") == todo_id]
            for nid in to_remove:
                self.remove_node(nid)

    def delete_event_node(self, event_id: str):
        with self._lock:
            to_remove = [nid for nid, n in self._nodes.items() if n["type"] == "event" and n["properties"].get("event_id") == event_id]
            for nid in to_remove:
                self.remove_node(nid)


_graph: KnowledgeGraph | None = None


def get_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
    return _graph
