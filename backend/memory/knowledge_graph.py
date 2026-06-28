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


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


class KnowledgeGraph:
    def __init__(self):
        cfg = load_config()
        path = Path(cfg.get("memory", {}).get("graph_path", "memory_graph.json"))
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent.parent / path
        self._path = path
        self._lock = threading.RLock()
        self._nodes: dict[str, dict] = {}
        self._edges: list[dict] = []

        self._label_idx: dict[str, str] = {}
        self._type_idx: dict[str, set[str]] = {}
        self._adj_idx: dict[str, dict[str, list[dict]]] = {}
        self._edge_fp: set[tuple[str, str, str]] = set()
        self._prop_idx: dict[tuple[str, str, str], str] = {}
        self._text_idx: dict[str, set[str]] = {}

        self._load()

    def _rebuild_indexes(self):
        self._label_idx.clear()
        self._type_idx.clear()
        self._adj_idx.clear()
        self._edge_fp.clear()
        self._prop_idx.clear()
        self._text_idx.clear()

        for node in self._nodes.values():
            self._index_node(node)
        for edge in self._edges:
            self._index_edge(edge)

    def _index_node(self, node: dict):
        nid = node["id"]
        label_lower = node["label"].strip().lower()
        self._label_idx[label_lower] = nid

        self._type_idx.setdefault(node["type"], set()).add(nid)

        text_parts = [node["label"], node["type"]]
        for v in node.get("properties", {}).values():
            if isinstance(v, str):
                text_parts.append(v)
        for token in _tokenize(" ".join(text_parts)):
            self._text_idx.setdefault(token, set()).add(nid)

        if node["type"] in ("todo", "event", "conversation"):
            props = node.get("properties", {})
            for key in ("todo_id", "event_id", "conv_id"):
                val = props.get(key)
                if val:
                    self._prop_idx[(node["type"], key, val)] = nid

    def _unindex_node(self, node: dict):
        nid = node["id"]
        label_lower = node["label"].strip().lower()
        self._label_idx.pop(label_lower, None)

        type_set = self._type_idx.get(node["type"])
        if type_set:
            type_set.discard(nid)

        text_parts = [node["label"], node["type"]]
        for v in node.get("properties", {}).values():
            if isinstance(v, str):
                text_parts.append(v)
        for token in _tokenize(" ".join(text_parts)):
            token_set = self._text_idx.get(token)
            if token_set:
                token_set.discard(nid)

        if node["type"] in ("todo", "event", "conversation"):
            props = node.get("properties", {})
            for key in ("todo_id", "event_id", "conv_id"):
                val = props.get(key)
                if val:
                    self._prop_idx.pop((node["type"], key, val), None)

    def _index_edge(self, edge: dict):
        self._adj_idx.setdefault(edge["source"], {"out": [], "in": []})
        self._adj_idx.setdefault(edge["target"], {"out": [], "in": []})
        self._adj_idx[edge["source"]]["out"].append(edge)
        self._adj_idx[edge["target"]]["in"].append(edge)
        self._edge_fp.add((edge["source"], edge["target"], edge["relation"]))

    def _unindex_edge(self, edge: dict):
        out_list = self._adj_idx.get(edge["source"], {}).get("out")
        if out_list:
            out_list[:] = [e for e in out_list if e["id"] != edge["id"]]
        in_list = self._adj_idx.get(edge["target"], {}).get("in")
        if in_list:
            in_list[:] = [e for e in in_list if e["id"] != edge["id"]]
        self._edge_fp.discard((edge["source"], edge["target"], edge["relation"]))

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._nodes = {n["id"]: n for n in data.get("nodes", [])}
                self._edges = data.get("edges", [])
                self._rebuild_indexes()
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
            props = properties or {}
            if "status" not in props:
                props["status"] = "active"
            node = {
                "id": node_id,
                "type": type,
                "label": label.strip(),
                "properties": props,
            }
            self._nodes[node_id] = node
            self._index_node(node)
            self._save()
            return node_id

    def add_edge(self, source: str, target: str, relation: str, properties: dict | None = None) -> str:
        with self._lock:
            edge_id = uuid.uuid4().hex[:12]
            edge = {
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "properties": properties or {},
            }
            self._edges.append(edge)
            self._index_edge(edge)
            self._save()
            return edge_id

    def add_edge_if_missing(self, source: str, target: str, relation: str, properties: dict | None = None) -> str | None:
        with self._lock:
            if (source, target, relation) in self._edge_fp:
                return None
            edge_id = uuid.uuid4().hex[:12]
            edge = {
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "properties": properties or {},
            }
            self._edges.append(edge)
            self._index_edge(edge)
            self._save()
            return edge_id

    def search(self, query: str) -> list[dict]:
        with self._lock:
            q = query.lower()
            tokens = _tokenize(q)
            matching_ids: set[str] | None = None

            if tokens:
                for t in tokens:
                    s = self._text_idx.get(t, set())
                    if matching_ids is None:
                        matching_ids = set(s)
                    else:
                        matching_ids &= s
                        if not matching_ids:
                            break

            if matching_ids is None:
                matching_ids = set()

            results = [self._nodes[nid] for nid in matching_ids if nid in self._nodes]

            seen = set(matching_ids)
            for node in self._nodes.values():
                if node["id"] in seen:
                    continue
                if q in node["label"].lower():
                    results.append(node)
                    seen.add(node["id"])
                    continue
                for v in node.get("properties", {}).values():
                    if isinstance(v, str) and q in v.lower():
                        results.append(node)
                        seen.add(node["id"])
                        break

            return results

    def get_node_by_label(self, label: str) -> dict | None:
        nid = self._label_idx.get(label.strip().lower())
        if nid:
            return self._nodes.get(nid)
        return None

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
                adj = self._adj_idx.get(nid)
                if adj:
                    for edge in adj["out"]:
                        if edge["target"] not in visited:
                            visited.add(edge["target"])
                            queue.append((edge["target"], d + 1))
                            sub_edges.append(edge)
                    for edge in adj["in"]:
                        if edge["source"] not in visited:
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

    def get_clean_graph(self, include_scraped: bool = False) -> dict:
        with self._lock:
            junk_ids = set()
            for nid, n in self._nodes.items():
                props = n.get("properties", {})
                if props.get("search_result") == "true":
                    junk_ids.add(nid)
                if not include_scraped and props.get("status") == "scraped":
                    junk_ids.add(nid)
            nodes = [n for n in self._nodes.values() if n["id"] not in junk_ids]
            edges = [e for e in self._edges if e["source"] not in junk_ids and e["target"] not in junk_ids]
            return {"nodes": nodes, "edges": edges}

    def remove_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self._nodes:
                return False
            node = self._nodes.pop(node_id)
            self._unindex_node(node)

            remaining_edges = []
            for edge in self._edges:
                if edge["source"] == node_id or edge["target"] == node_id:
                    self._unindex_edge(edge)
                else:
                    remaining_edges.append(edge)
            self._edges = remaining_edges
            self._save()
            return True

    def remove_edge(self, source: str, target: str, relation: str) -> bool:
        with self._lock:
            before = len(self._edges)
            removed = [e for e in self._edges if e["source"] == source and e["target"] == target and e["relation"] == relation]
            self._edges = [e for e in self._edges if not (e["source"] == source and e["target"] == target and e["relation"] == relation)]
            if removed:
                for e in removed:
                    self._unindex_edge(e)
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
            key = ("todo", "todo_id", todo["id"])
            existing_id = self._prop_idx.get(key)
            if existing_id:
                existing = self._nodes.get(existing_id)
                if existing:
                    self._unindex_node(existing)
                    existing["label"] = todo["title"]
                    existing["properties"].update({
                        "description": todo.get("description", ""),
                        "due_date": todo.get("due_date"),
                        "priority": todo.get("priority"),
                        "completed": todo.get("completed", False),
                        "tags": todo.get("tags", []),
                        "recurrence": todo.get("recurrence"),
                    })
                    self._index_node(existing)
                    self._save()
                    return
            node_id = uuid.uuid4().hex[:12]
            node = {
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
                    "recurrence": todo.get("recurrence"),
                },
            }
            self._nodes[node_id] = node
            self._index_node(node)
            for tag in todo.get("tags", []):
                tag_node_id = self._ensure_tag_node(tag)
                edge = {
                    "id": uuid.uuid4().hex[:12],
                    "source": node_id,
                    "target": tag_node_id,
                    "relation": "has_tag",
                    "properties": {},
                }
                self._edges.append(edge)
                self._index_edge(edge)
            self._save()

    def sync_event(self, event: dict):
        with self._lock:
            key = ("event", "event_id", event["id"])
            existing_id = self._prop_idx.get(key)
            if existing_id:
                existing = self._nodes.get(existing_id)
                if existing:
                    self._unindex_node(existing)
                    existing["label"] = event["title"]
                    existing["properties"].update({
                        "description": event.get("description", ""),
                        "start_time": event.get("start_time"),
                        "end_time": event.get("end_time"),
                        "all_day": event.get("all_day", False),
                        "recurrence": event.get("recurrence"),
                    })
                    self._index_node(existing)
                    self._save()
                    return
            node_id = uuid.uuid4().hex[:12]
            node = {
                "id": node_id,
                "type": "event",
                "label": event["title"],
                "properties": {
                    "event_id": event["id"],
                    "description": event.get("description", ""),
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "all_day": event.get("all_day", False),
                    "recurrence": event.get("recurrence"),
                },
            }
            self._nodes[node_id] = node
            self._index_node(node)
            self._save()

    def sync_conversation(self, conv: dict) -> str:
        with self._lock:
            key = ("conversation", "conv_id", conv["id"])
            existing_id = self._prop_idx.get(key)
            if existing_id:
                existing = self._nodes.get(existing_id)
                if existing:
                    self._unindex_node(existing)
                    existing["label"] = conv["id"]
                    existing["properties"]["message_count"] = len(conv.get("messages", []))
                    existing["properties"]["title"] = conv.get("title", "Conversation")
                    self._index_node(existing)
                    self._save()
                    return existing["id"]
            node_id = uuid.uuid4().hex[:12]
            node = {
                "id": node_id,
                "type": "conversation",
                "label": conv["id"],
                "properties": {
                    "conv_id": conv["id"],
                    "title": conv.get("title", "Conversation"),
                    "message_count": len(conv.get("messages", [])),
                },
            }
            self._nodes[node_id] = node
            self._index_node(node)
            self._save()
            return node_id

    def _ensure_tag_node(self, tag: str) -> str:
        nid = self._label_idx.get(tag.strip().lower())
        if nid and nid in self._nodes and self._nodes[nid]["type"] == "tag":
            return nid
        node_id = uuid.uuid4().hex[:12]
        node = {
            "id": node_id,
            "type": "tag",
            "label": tag,
            "properties": {},
        }
        self._nodes[node_id] = node
        self._index_node(node)
        return node_id

    def delete_todo_node(self, todo_id: str):
        with self._lock:
            key = ("todo", "todo_id", todo_id)
            nid = self._prop_idx.get(key)
            if nid:
                self.remove_node(nid)

    def delete_event_node(self, event_id: str):
        with self._lock:
            key = ("event", "event_id", event_id)
            nid = self._prop_idx.get(key)
            if nid:
                self.remove_node(nid)

    def delete_conversation_node(self, conv_id: str):
        with self._lock:
            key = ("conversation", "conv_id", conv_id)
            nid = self._prop_idx.get(key)
            if nid:
                self.remove_node(nid)

    def set_status(self, label: str, status: str) -> dict | None:
        with self._lock:
            nid = self._label_idx.get(label.strip().lower())
            if nid and nid in self._nodes:
                self._unindex_node(self._nodes[nid])
                self._nodes[nid]["properties"]["status"] = status
                self._index_node(self._nodes[nid])
                self._save()
                return self._nodes[nid]
            return None

    def repair_graph(self) -> dict:
        with self._lock:
            report = {"junk_scraped": 0, "projects_scraped": [], "errors": []}
            scraped_ids = set()
            for nid, n in self._nodes.items():
                if n["type"] == "concept" and n.get("properties", {}).get("search_result") == "true":
                    scraped_ids.add(nid)
                    report["junk_scraped"] += 1
            project_labels = ["project:AGI Personal Assistant", "project:Personal Development"]
            for nid, n in self._nodes.items():
                if n["type"] == "project" and n["label"] in project_labels:
                    scraped_ids.add(nid)
                    report["projects_scraped"].append(n["label"])
            for nid in scraped_ids:
                self._unindex_node(self._nodes[nid])
                self._nodes[nid]["properties"]["status"] = "scraped"
                self._index_node(self._nodes[nid])
            self._save()
            report["total_scraped"] = len(scraped_ids)
            return report


_graph: KnowledgeGraph | None = None


def get_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
    return _graph
