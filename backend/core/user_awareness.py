"""Graph-backed awareness store for Mayday.

Consolidated per the PHF plan: the shared knowledge graph is now the single
source of truth. This module keeps only the two awareness features that were
explicitly retained — proactive follow-ups and the onboarding question queue —
plus a first-class user name. The old flat belief/confidence/consent/decay/
reflection/snapshot machinery and the separate `user_profile.json` file are
gone; personal facts live in the graph via `remember`.

Follow-ups and onboarding questions are persisted as graph nodes so there is
no second store and no dual-write.
"""

import re
import threading
import uuid
from datetime import datetime, timezone, timedelta

from backend.memory.knowledge_graph import get_graph


_UTC = timezone.utc

# Kept for backwards-compatible imports by other modules; no longer drive a
# second store.
SLOTS = (
    "identity", "relations", "favorites", "belongings",
    "goals", "problems", "context", "state",
)

PROVENANCE_CONFIDENCE = {
    "explicit": 0.9,
    "repeated": 0.75,
    "inference": 0.55,
    "stereotype": 0.3,
}

_FOLLOWUP_CADENCE_DAYS = 7
_USER_LABEL = "user:Mayday-user"


def _utcnow() -> str:
    return datetime.now(_UTC).isoformat()


def _today() -> str:
    return _utcnow()[:10]


def _add_days(date_str: str, days: int) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        dt = datetime.now(_UTC)
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class AwarenessStore:
    """Lightweight graph-backed store for follow-ups, onboarding, and user name."""

    def __init__(self):
        self._lock = threading.RLock()
        self._followup_cadence_days = _FOLLOWUP_CADENCE_DAYS
        self._proactive_followups = True
        # Repeat counts for soft/implicit signals before they are persisted.
        self._pending_soft: dict = {}

    # ----- user name (first-class, graph-backed) -----
    def _user_node(self) -> dict | None:
        return get_graph().get_node_by_label(_USER_LABEL)

    def set_user_name(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return
        norm = " ".join(w[:1].upper() + w[1:] for w in name.split() if w)
        if not norm:
            return
        with self._lock:
            kg = get_graph()
            node = kg.get_node_by_label(_USER_LABEL)
            if node is None:
                kg.add_node("user", _USER_LABEL, {"name": norm, "kind": "user"})
            else:
                node["properties"]["name"] = norm
                kg._index_node(node)
                kg._save()

    def get_user_name(self) -> str | None:
        node = self._user_node()
        if node:
            return node.get("properties", {}).get("name")
        return None

    # ----- onboarding question queue -----
    def queue_question(self, slot: str, question: str) -> dict:
        with self._lock:
            qid = "q_" + uuid.uuid4().hex[:8]
            node = get_graph().add_node("question", f"question:{qid}", {
                "question_id": qid,
                "slot": slot.strip().lower(),
                "question": question,
                "date": _today(),
                "answered": False,
                "answer": "",
            })
            return {"id": qid, "slot": slot, "question": question, "answered": False}

    def pending_questions(self, limit: int | None = None) -> list[dict]:
        nodes = get_graph().search("question")
        out = []
        for n in nodes:
            props = n.get("properties", {})
            if not props.get("answered"):
                out.append({
                    "id": props.get("question_id", n["id"]),
                    "slot": props.get("slot", ""),
                    "question": props.get("question", ""),
                    "date": props.get("date", ""),
                })
        out.sort(key=lambda x: x.get("date", ""))
        return out[:limit] if limit else out

    def record_answer(self, question_id: str, answer: str, slot: str = "") -> dict:
        from backend.memory.memory_tools import remember
        with self._lock:
            nodes = get_graph().search("question")
            target = None
            for n in nodes:
                if n.get("properties", {}).get("question_id") == question_id:
                    target = n
                    break
            if target is None:
                return {"error": "Question not found"}
            target["properties"]["answered"] = True
            target["properties"]["answer"] = answer
            get_graph()._index_node(target)
            get_graph()._save()
            slot = slot or target["properties"].get("slot", "")
            if answer and slot:
                remember("user", slot, answer)
            return {
                "question": {
                    "id": question_id,
                    "question": target["properties"].get("question", ""),
                    "answered": True,
                },
                "belief": {"slot": slot, "value": answer},
            }

    # ----- proactive follow-ups -----
    def create_followup(self, person: str, relation_type: str = "relation") -> dict:
        person = (person or "").strip()
        if not person:
            return {"error": "person cannot be empty"}
        with self._lock:
            kg = get_graph()
            existing = kg.get_node_by_label(f"followup:{_norm(person)}")
            if existing is not None:
                return existing["properties"]
            today = _today()
            props = {
                "person": person,
                "relation_type": relation_type or "relation",
                "created_at": today,
                "next_ask_date": _add_days(today, self._followup_cadence_days),
                "cadence_days": self._followup_cadence_days,
                "last_asked": "",
            }
            kg.add_node("followup", f"followup:{_norm(person)}", props)
            # link user -> followup
            user = kg.get_node_by_label(_USER_LABEL)
            if user is not None:
                kg.add_edge_if_missing(user["id"],
                                       kg.get_node_by_label(f"followup:{_norm(person)}")["id"],
                                       "checks_in_on")
            return props

    def due_followups(self, as_of: str | None = None) -> list[dict]:
        today = as_of or _today()
        out = []
        for n in get_graph().search("followup"):
            props = n.get("properties", {})
            if props.get("next_ask_date", "") <= today:
                out.append(dict(props))
        return out

    def remove_followup(self, person: str) -> bool:
        with self._lock:
            node = get_graph().get_node_by_label(f"followup:{_norm(person)}")
            if node is None:
                return False
            get_graph().remove_node(node["id"])
            return True

    # ----- per-person brief (graph-derived) -----
    def person_brief(self, name: str, max_chars: int = 400) -> str:
        name_l = name.strip()
        kg = get_graph()
        node = kg.get_node_by_label(f"person:{_norm(name_l)}")
        if node is None:
            # fall back to any node whose label contains the name
            hits = [n for n in kg.search(name_l) if n["type"] in ("person", "relation")]
            if not hits:
                return f"No brief for '{name_l}' — Mayday hasn't learned about them yet."
            node = hits[0]
        props = node.get("properties", {})
        rtype = props.get("relation_type") or "relation"
        lines = [f"{name_l} — your {rtype}."]
        created = (props.get("created_at") or "")[:10]
        if created:
            lines.append(f"First mentioned: {created}.")
        # linked situational notes via subgraph
        try:
            sg = kg.get_subgraph(node["id"], depth=1)
            for edge in sg.get("edges", []):
                if edge.get("relation") in ("refers_to", "knows", "is"):
                    tgt = kg.get_node(edge.get("target"))
                    if tgt:
                        lines.append(f"Noted: {tgt['label']}.")
        except Exception:
            pass
        text = " ".join(lines)
        return text[:max_chars]

    def list_people(self) -> list[dict]:
        """Return every person node in the graph with a brief each."""
        out = []
        seen = set()
        for n in get_graph().search("person"):
            props = n.get("properties", {})
            name = props.get("name") or n["label"]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name": name,
                "relation_type": props.get("relation_type") or "relation",
                "brief": self.person_brief(name),
            })
        return out


_instance = None
_instance_lock = threading.Lock()


def get_awareness_store() -> AwarenessStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AwarenessStore()
    return _instance


def reset_awareness_store():
    global _instance
    _instance = None
