import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.core.config import load_config
from backend.memory.knowledge_graph import get_graph


_UTC = timezone.utc

# Ontology slots. Each slot is a set of beliefs about the user.
SLOTS = (
    "identity",   # name, role, work/study, routine, timezone/location
    "relations",  # people: family/friend/colleague
    "favorites",  # foods, music, movies, sports, places, brands
    "belongings", # pets, vehicles, devices, assets
    "goals",      # short/long term
    "problems",   # stress, health, financial, worries
    "context",    # phase of life, schedule pattern
    "state",      # transient mood/availability (fast decay)
)

# Slots whose beliefs are Tier-1 sensitive (health/finances/relationships).
SENSITIVE_SLOTS = {"relations", "problems", "goals"}

# Provenance -> baseline confidence (heuristic; replaced by DSPy UA-2 once compiled).
PROVENANCE_CONFIDENCE = {
    "explicit": 0.9,
    "repeated": 0.75,
    "inference": 0.55,
    "stereotype": 0.3,
}

# Slots with fast-decaying "state" semantics.
FAST_DECAY_SLOTS = {"state"}

CONSEQUENTIAL_ACTIONS = {
    "create_todo", "create_event", "create_reminder",
    "create_personal_note", "add_project_task", "create_research",
}

_NEGATION_RE = re.compile(r"\b(not|no longer|don'?t|doesn'?t|didn'?t|never|unlike|dislike|hate|stopped?|quit)\b", re.I)


def _utcnow() -> str:
    return datetime.now(_UTC).isoformat()


def _days_since(iso_ts: Optional[str]) -> float:
    if not iso_ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return (datetime.now(_UTC) - dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0


def _add_days(date_str: str, days: int) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        dt = datetime.now(_UTC)
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _norm_phone(value: str) -> str:
    """Digits-only canonical form of a phone number for comparison."""
    return re.sub(r"\D", "", value or "")


def _is_phone(value: str) -> bool:
    """True if ``value`` looks like a phone number (7-15 digits, no letters)."""
    if not value:
        return False
    v = value.strip()
    if any(c.isalpha() for c in v):
        return False
    digits = _norm_phone(v)
    return 7 <= len(digits) <= 15


class AwarenessStore:
    """Dual-store world model: user_profile.json + mirrored belief nodes in the graph.

    All mutations are thread-safe and flag-gated by the caller (awareness.enabled).
    """

    def __init__(self):
        cfg = load_config()
        path = cfg.get("awareness", {}).get("profile_path", "user_profile.json")
        if not Path(path).is_absolute():
            path = str(Path(__file__).resolve().parent.parent.parent / path)
        self._path = Path(path)
        self._lock = threading.RLock()
        self._beliefs: dict[str, dict] = {}
        self._questions: list[dict] = []     # onboarding queue
        self._tombstones: list[dict] = []    # deleted entities (never recreate)
        self._followups: list[dict] = []     # proactive relationship check-ins
        self._consented_tiers: set[str] = set(
            cfg.get("awareness", {}).get("consented_tiers", ["T0"])
        )
        self._decay_lambda = float(cfg.get("awareness", {}).get("decay_lambda", 0.02))
        self._proactive_followups = bool(cfg.get("awareness", {}).get("proactive_followups", False))
        self._followup_cadence_days = int(cfg.get("awareness", {}).get("followup_cadence_days", 7))
        self._brief_enabled = bool(cfg.get("awareness", {}).get("brief_enabled", True))
        self._user_node_id: Optional[str] = None
        self._user_name: Optional[str] = None
        self._load()

    # ----- persistence -----
    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._beliefs = {b["id"]: b for b in data.get("beliefs", [])}
                self._questions = data.get("questions", [])
                self._tombstones = data.get("tombstones", [])
                self._followups = data.get("followups", [])
                self._consented_tiers = set(data.get("consented_tiers", self._consented_tiers))
                self._user_name = data.get("user_name")
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "beliefs": list(self._beliefs.values()),
            "questions": self._questions,
            "tombstones": self._tombstones,
            "followups": self._followups,
            "consented_tiers": sorted(self._consented_tiers),
            "user_name": self._user_name,
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ----- consent -----
    def grant_consent(self, tier: str) -> bool:
        with self._lock:
            self._consented_tiers.add(tier)
            self._save()
            return True

    def is_consented(self, tier: str) -> bool:
        return tier in self._consented_tiers

    # ----- canonical user name (reliable, observer-captured) -----
    def set_user_name(self, name: str) -> None:
        """Store the user's name (Title-cased) as a first-class, always-available fact."""
        name = (name or "").strip()
        if not name:
            return
        # Normalize: "ajay" -> "Ajay", "john doe" -> "John Doe"
        norm = " ".join(w[:1].upper() + w[1:] for w in name.split() if w)
        if not norm:
            return
        with self._lock:
            if self._user_name and self._user_name.lower() == norm.lower():
                return
            self._user_name = norm
            self._save()

    def get_user_name(self) -> Optional[str]:
        return self._user_name

    # ----- graph sync -----
    def _ensure_user_node(self) -> str:
        kg = get_graph()
        node = kg.get_node_by_label("user:Mayday-user")
        if node:
            self._user_node_id = node["id"]
            return node["id"]
        uid = kg.add_node("user", "user:Mayday-user", {"kind": "user"})
        self._user_node_id = uid
        return uid

    def _slot_tier(self, slot: str, override: Optional[str]) -> str:
        if override:
            return override
        return "T1" if slot in SENSITIVE_SLOTS else "T0"

    def _sync_belief_to_graph(self, belief: dict):
        kg = get_graph()
        self._ensure_user_node()
        label = f"belief:{belief['slot']}:{belief['value']}"
        node = kg.get_node_by_label(label)
        if node:
            self._unindex_belief_node(node)
            node["properties"].update({
                "slot": belief["slot"],
                "value": belief["value"],
                "confidence": belief["confidence"],
                "consent_tier": belief["consent_tier"],
            })
            kg._index_node(node)
            kg._save()
            nid = node["id"]
        else:
            nid = kg.add_node("belief", label, {
                "slot": belief["slot"],
                "value": belief["value"],
                "confidence": belief["confidence"],
                "consent_tier": belief["consent_tier"],
                "belief_id": belief["id"],
            })
        kg.add_edge_if_missing(self._user_node_id, nid, "believes")

        # relations create person nodes for entity linking
        if belief["slot"] == "relations":
            brief = self.person_brief(belief["value"])[:280] if self._brief_enabled else ""
            person = kg.get_node_by_label(f"person:{belief['value']}")
            if not person:
                pid = kg.add_node("person", f"person:{belief['value']}", {
                    "name": belief["value"],
                    "relation_type": belief.get("relation_type", ""),
                    "brief": brief,
                })
                kg.add_edge_if_missing(nid, pid, "refers_to")
            else:
                person["properties"]["relation_type"] = belief.get("relation_type", "")
                if self._brief_enabled:
                    person["properties"]["brief"] = brief
                kg._index_node(person)
                kg._save()

        # Share the person into MAGMA's entity graph using the SAME raw label
        # MAGMA/consolidation use (type "person", label = value), so the entity
        # subgraph and the awareness store reference one shared person node.
        if belief["slot"] == "relations":
            try:
                from backend.memory.multigraph import get_multigraph
                mg = get_multigraph()
                ent = mg._kg.get_node_by_label(belief["value"])
                if not ent:
                    mg._kg.add_node("person", belief["value"],
                                    {"consolidated": True, "source": "awareness"})
            except Exception:
                pass

    def _unindex_belief_node(self, node: dict):
        # mirror KnowledgeGraph._unindex_node without re-importing internals
        from backend.memory.knowledge_graph import _tokenize
        nid = node["id"]
        label_lower = node["label"].strip().lower()
        g = get_graph()
        g._label_idx.pop(label_lower, None)
        tset = g._type_idx.get(node["type"])
        if tset:
            tset.discard(nid)
        parts = [node["label"], node["type"]] + [
            v for v in node.get("properties", {}).values() if isinstance(v, str)
        ]
        for tok in _tokenize(" ".join(parts)):
            g._text_idx.get(tok, set()).discard(nid)

    # ----- belief CRUD -----
    def add_belief(self, slot: str, value: str, provenance: str = "inference",
                   confidence: Optional[float] = None, consent_tier: Optional[str] = None,
                   source_refs: Optional[list[str]] = None, relation_type: Optional[str] = None) -> dict:
        with self._lock:
            slot = slot.strip().lower()
            value = value.strip()
            if slot not in SLOTS:
                return {"error": f"Unknown slot '{slot}'. Valid: {', '.join(SLOTS)}"}
            if not value:
                return {"error": "Belief value cannot be empty"}
            if self.is_tombstoned(slot, value):
                return {"error": f"'{value}' in slot '{slot}' was previously deleted and will not be relearned."}

            existing = self.find_belief(slot, value)
            if existing:
                # reinforce: bump observed_count, possibly upgrade confidence
                existing["observed_count"] = existing.get("observed_count", 1) + 1
                if existing["observed_count"] >= 3 and existing["provenance"] == "inference":
                    existing["provenance"] = "repeated"
                    existing["confidence"] = max(existing["confidence"], PROVENANCE_CONFIDENCE["repeated"])
                existing["last_verified"] = _utcnow()
                if relation_type and not existing.get("relation_type"):
                    existing["relation_type"] = relation_type
                # talking about them again pushes the next gentle check-in forward
                if slot == "relations":
                    self._touch_followup(value)
                self._sync_belief_to_graph(existing)
                self._save()
                return existing

            # A phone number is a single, mutable fact — keep only the latest one
            # so Mayday doesn't remember both an old and a new number.
            if _is_phone(value):
                self._retire_other_phones(value)

            if confidence is None:
                confidence = PROVENANCE_CONFIDENCE.get(provenance, PROVENANCE_CONFIDENCE["inference"])
            tier = self._slot_tier(slot, consent_tier)
            belief = {
                "id": "blf_" + uuid.uuid4().hex[:12],
                "slot": slot,
                "value": value,
                "confidence": round(confidence, 3),
                "provenance": provenance,
                "consent_tier": tier,
                "last_verified": _utcnow(),
                "created_at": _utcnow(),
                "observed_count": 1,
                "source_refs": source_refs or [],
                "relation_type": relation_type or "",
            }
            self._beliefs[belief["id"]] = belief
            self._sync_belief_to_graph(belief)
            if slot == "relations" and self._proactive_followups:
                self.create_followup(value, relation_type or "relation")
            self._save()
            return belief

    def _retire_other_phones(self, new_value: str) -> None:
        """Remove any stored phone number that differs from ``new_value``.

        Prevents Mayday from remembering both an old and a new number when the
        user changes their number. Safe to call inside an existing lock (RLock).
        """
        new_digits = _norm_phone(new_value)
        stale = [
            b["id"] for b in self._beliefs.values()
            if _is_phone(b["value"]) and _norm_phone(b["value"]) != new_digits
        ]
        for bid in stale:
            self.delete_belief(bid)

    def confirm_belief(self, belief_id: str, value: Optional[str] = None) -> dict:
        """User explicitly confirmed a belief (or answered a question)."""
        with self._lock:
            b = self._beliefs.get(belief_id)
            if b is None and value:
                # match by value across slots
                for cand in self._beliefs.values():
                    if cand["value"].lower() == value.lower():
                        b = cand
                        break
            if b is None:
                return {"error": "Belief not found"}
            b["confidence"] = 0.95
            b["provenance"] = "explicit"
            b["last_verified"] = _utcnow()
            self._sync_belief_to_graph(b)
            self._save()
            return b

    def update_belief(self, belief_id: str, **fields) -> dict:
        with self._lock:
            b = self._beliefs.get(belief_id)
            if b is None:
                return {"error": "Belief not found"}
            allowed = {"value", "confidence", "provenance", "consent_tier", "slot"}
            for k, v in fields.items():
                if k in allowed:
                    b[k] = v
            if "value" in fields:
                b["last_verified"] = _utcnow()
            self._sync_belief_to_graph(b)
            self._save()
            return b

    def get_belief(self, belief_id: str) -> Optional[dict]:
        return self._beliefs.get(belief_id)

    def find_belief(self, slot: str, value: str) -> Optional[dict]:
        slot = slot.strip().lower()
        nv = _norm(value)
        for b in self._beliefs.values():
            if b["slot"] == slot and _norm(b["value"]) == nv:
                return b
        return None

    def list_beliefs(self, slot: Optional[str] = None, min_confidence: Optional[float] = None,
                     consent_tier: Optional[str] = None) -> list[dict]:
        with self._lock:
            results = []
            for b in self._beliefs.values():
                if slot and b["slot"] != slot.strip().lower():
                    continue
                if min_confidence is not None and b["confidence"] < min_confidence:
                    continue
                if consent_tier and b["consent_tier"] != consent_tier:
                    continue
                results.append(dict(b))
            results.sort(key=lambda x: -x["confidence"])
            return results

    def search_beliefs(self, query: str) -> list[dict]:
        q = _norm(query)
        out = []
        for b in self._beliefs.values():
            if q in b["slot"] or q in _norm(b["value"]):
                out.append(dict(b))
        return out

    def delete_belief(self, belief_id: str) -> bool:
        with self._lock:
            b = self._beliefs.pop(belief_id, None)
            if b is None:
                return False
            self.tombstone(b["slot"], b["value"])
            kg = get_graph()
            label = f"belief:{b['slot']}:{b['value']}"
            node = kg.get_node_by_label(label)
            if node:
                kg.remove_node(node["id"])
            self._save()
            return True

    # ----- tombstones -----
    def tombstone(self, slot: str, value: str):
        with self._lock:
            slot = slot.strip().lower()
            value = value.strip()
            if not self.is_tombstoned(slot, value):
                self._tombstones.append({
                    "slot": slot,
                    "value": value,
                    "deleted_at": _utcnow(),
                })

    def is_tombstoned(self, slot: str, value: str) -> bool:
        slot = slot.strip().lower()
        nv = _norm(value)
        return any(t["slot"] == slot and _norm(t["value"]) == nv for t in self._tombstones)

    # ----- forgetting / decay -----
    def decay(self) -> int:
        """Apply exponential forgetting; demote low-confidence, stale beliefs."""
        with self._lock:
            changed = 0
            for b in self._beliefs.values():
                lam_local = self._decay_lambda * 5.0 if b["slot"] in FAST_DECAY_SLOTS else self._decay_lambda
                idle = _days_since(b.get("last_verified") or b.get("created_at"))
                factor = math.exp(-lam_local * idle)
                new_conf = round(b["confidence"] * factor, 3)
                if new_conf < b["confidence"]:
                    b["confidence"] = new_conf
                    changed += 1
                    self._sync_belief_to_graph(b)
            if changed:
                self._save()
            return changed

    # ----- reflection -----
    def run_reflection(self) -> dict:
        """Weekly consolidation: resolve duplicate/contradiction, derive traits."""
        with self._lock:
            # collapse duplicate values within a slot (keep highest confidence)
            by_slot_value: dict[tuple, list[dict]] = {}
            for b in self._beliefs.values():
                key = (b["slot"], _norm(b["value"]))
                by_slot_value.setdefault(key, []).append(b)
            merged = 0
            for group in by_slot_value.values():
                if len(group) > 1:
                    group.sort(key=lambda x: -x["confidence"])
                    keep = group[0]
                    for dup in group[1:]:
                        keep["observed_count"] += dup.get("observed_count", 1)
                        del self._beliefs[dup["id"]]
                        merged += 1
            # contradictions: same slot, different value, one newer + explicit
            contradictions = 0
            slots: dict[str, list[dict]] = {}
            for b in self._beliefs.values():
                slots.setdefault(b["slot"], []).append(b)
            for sl, items in slots.items():
                if len({_norm(i["value"]) for i in items}) > 1:
                    items.sort(key=lambda x: x.get("last_verified") or x.get("created_at"))
                    winner = items[-1]
                    if winner["provenance"] == "explicit":
                        for loser in items[:-1]:
                            loser["confidence"] = round(min(loser["confidence"], 0.2), 3)
                        contradictions += len(items) - 1
            if merged or contradictions:
                for b in self._beliefs.values():
                    self._sync_belief_to_graph(b)
                self._save()
            return {"merged": merged, "contradictions_resolved": contradictions,
                    "belief_count": len(self._beliefs)}

    # ----- onboarding question queue -----
    def queue_question(self, slot: str, question: str) -> dict:
        with self._lock:
            today = _utcnow()[:10]
            if any(q["slot"] == slot and not q.get("answered") and q.get("date") == today for q in self._questions):
                return {"error": f"A question for slot '{slot}' is already queued today."}
            q = {
                "id": "q_" + uuid.uuid4().hex[:8],
                "slot": slot,
                "question": question,
                "date": today,
                "answered": False,
            }
            self._questions.append(q)
            self._save()
            return q

    def pending_questions(self, limit: Optional[int] = None) -> list[dict]:
        with self._lock:
            pending = [q for q in self._questions if not q.get("answered")]
            pending.sort(key=lambda x: x["date"])
            return pending[:limit] if limit else pending

    def record_answer(self, question_id: str, answer: str, slot: Optional[str] = None) -> dict:
        with self._lock:
            q = next((x for x in self._questions if x["id"] == question_id), None)
            if q is None:
                return {"error": "Question not found"}
            q["answered"] = True
            q["answer"] = answer
            slot = slot or q["slot"]
            belief = self.add_belief(slot, answer, provenance="explicit", confidence=0.95)
            self._save()
            return {"question": q, "belief": belief}

    # ----- world snapshot (context injection) -----
    def snapshot(self, context: Optional[str] = None, top_k: int = 8, max_chars: int = 1500) -> str:
        """Compressed top-N beliefs by confidence * recency * relevance."""
        with self._lock:
            beliefs = list(self._beliefs.values())
            ctx_tokens = set(re.findall(r"[a-z0-9_]+", (context or "").lower()))

            def score(b: dict) -> float:
                idle = _days_since(b.get("last_verified") or b.get("created_at"))
                recency = math.exp(-0.05 * idle)
                relev = 1.0
                if ctx_tokens:
                    bt = set(re.findall(r"[a-z0-9_]+", (b["slot"] + " " + b["value"]).lower()))
                    relev = 1.0 + (len(bt & ctx_tokens) * 0.5)
                return b["confidence"] * recency * relev

            beliefs.sort(key=score, reverse=True)
            lines = []
            total = 0
            for b in beliefs[:top_k]:
                line = f"- [{b['slot']}] {b['value']} (conf {b['confidence']:.2f})"
                if b["consent_tier"] != "T0":
                    line += f" [{b['consent_tier']}]"
                if total + len(line) + 1 > max_chars:
                    break
                lines.append(line)
                total += len(line) + 1
            return "\n".join(lines) if lines else "(no beliefs yet)"

    # ----- companion profile synthesis -----
    def profile(self) -> str:
        """Synthesize a readable 'companion understanding' of the user from all
        beliefs (identity, relations, likes, stressors, situational patterns...)."""
        by_slot: dict[str, list[dict]] = {}
        for b in self._beliefs.values():
            by_slot.setdefault(b["slot"], []).append(b)

        def vals(slot: str) -> list[str]:
            return [b["value"] for b in by_slot.get(slot, []) if b["value"].strip().lower() not in ("user", "")]

        lines = []
        if vals("identity"):
            lines.append("Who they are: " + "; ".join(vals("identity")))
        if vals("relations"):
            lines.append("People in their life: " + "; ".join(vals("relations")))
            for b in by_slot.get("relations", []):
                brief = self.person_brief(b["value"])
                if brief and brief.startswith(b["value"]):
                    lines.append("  • " + brief)
        if vals("favorites"):
            lines.append("Likes / preferences: " + "; ".join(vals("favorites")))
        if vals("belongings"):
            lines.append("Owns / has: " + "; ".join(vals("belongings")))
        if vals("goals"):
            lines.append("Working toward: " + "; ".join(vals("goals")))
        if vals("problems"):
            lines.append("Stressors / challenges: " + "; ".join(vals("problems")))
        if vals("context"):
            lines.append("Situational patterns & coping: " + "; ".join(vals("context")))
        if vals("state"):
            lines.append("Current state: " + "; ".join(vals("state")))
        if not lines:
            return "(no profile yet — tell Mayday about yourself, your habits, and how you cope)"
        return "\n".join(lines)

    # ----- proactive relationship follow-ups ("what about her?") -----
    def create_followup(self, person: str, relation_type: str = "relation") -> dict:
        """Schedule a gentle check-in about a person. Idempotent per person."""
        with self._lock:
            person = person.strip()
            if not person:
                return {"error": "person cannot be empty"}
            for f in self._followups:
                if _norm(f["person"]) == _norm(person):
                    return f
            today = _utcnow()[:10]
            cadence = self._followup_cadence_days
            fu = {
                "id": "fu_" + uuid.uuid4().hex[:8],
                "person": person,
                "relation_type": relation_type,
                "created_at": today,
                "next_ask_date": _add_days(today, cadence),
                "cadence_days": cadence,
                "last_asked": "",
            }
            self._followups.append(fu)
            self._save()
            return fu

    def due_followups(self, as_of: Optional[str] = None) -> list[dict]:
        """Return follow-ups whose next_ask_date is today or in the past."""
        with self._lock:
            today = (as_of or _utcnow()[:10])
            return [dict(f) for f in self._followups if f["next_ask_date"] <= today]

    def _touch_followup(self, person: str):
        with self._lock:
            person_n = _norm(person)
            for f in self._followups:
                if _norm(f["person"]) == person_n:
                    today = _utcnow()[:10]
                    f["last_asked"] = today
                    f["next_ask_date"] = _add_days(today, f.get("cadence_days", self._followup_cadence_days))
                    self._save()
                    return

    def remove_followup(self, person: str) -> bool:
        with self._lock:
            person_n = _norm(person)
            before = len(self._followups)
            self._followups = [f for f in self._followups if _norm(f["person"]) != person_n]
            if len(self._followups) != before:
                self._save()
                return True
            return False

    # ----- per-person aggregated brief -----
    def person_brief(self, name: str, max_chars: int = 400) -> str:
        """Free, aggregated short profile of a named person from stored memory."""
        name_n = _norm(name)
        name_l = name.strip()
        relations = [b for b in self._beliefs.values()
                     if b["slot"] == "relations" and _norm(b["value"]) == name_n]
        if not relations:
            return f"No brief for '{name_l}' — Mayday hasn't learned about them yet."
        rel = relations[0]
        rtype = rel.get("relation_type") or "relation"
        lines = [f"{name_l} — your {rtype}."]
        created = (rel.get("created_at") or "")[:10]
        if created:
            lines.append(f"First mentioned: {created}.")
        refs = rel.get("source_refs", [])
        convs = [r for r in refs if r.startswith("conv:")]
        if convs:
            lines.append(f"Mentioned in {len(convs)} chat(s).")
        last = (rel.get("last_verified") or "")[:10]
        if last and last != created:
            lines.append(f"Last mentioned: {last}.")
        # situational / context beliefs that reference this person by name
        linked = []
        for b in self._beliefs.values():
            if b is rel or b["slot"] == "relations":
                continue
            if name_l.lower() in (b["value"] + " " + b.get("slot", "")).lower():
                linked.append(b["value"])
        if linked:
            lines.append("Noted: " + "; ".join(linked[:3]) + ".")
        # personal notes that mention them
        try:
            from backend.core.personal_notes import get_personal_notes_store
            notes = get_personal_notes_store().search_notes(name_l)
            if notes:
                lines.append(f"{len(notes)} personal note(s) mention them.")
        except Exception:
            pass
        text = " ".join(lines)
        return text[:max_chars]

    # ----- decision gate -----
    def can_do(self, action: str, text: str, entities: Optional[list[str]] = None,
               context: Optional[str] = None) -> dict:
        """Ask / warn / block / allow verdict for a task action.

        DSPy UA-5 can override non-safety verdicts when enabled; a hard
        consent block (T1 belief + not consented) is NEVER overridden.
        """
        with self._lock:
            text_n = _norm(text)
            referenced = self._referenced_beliefs(text_n, entities)
            unknown = self._unknown_entities(text_n, entities, referenced)

            # 1. hard consent block (safety — never overridable)
            for b in referenced:
                if b["consent_tier"] in ("T1", "T2") and not self.is_consented(b["consent_tier"]):
                    return {
                        "verdict": "block",
                        "reason": f"Action references sensitive belief '{b['value']}' "
                                  f"({b['slot']}, {b['consent_tier']}) without consent.",
                        "suggestion": "Ask the user for explicit consent before acting on this.",
                        "slot": b["slot"], "entities": [b["value"]],
                    }

            # 2. unknown entity -> ask
            if unknown:
                return {
                    "verdict": "ask",
                    "reason": "Text references an entity Mayday does not yet understand.",
                    "suggestion": f"Ask the user to confirm: who/what is '{unknown[0]}'?",
                    "slot": None, "entities": unknown,
                }

            # 3. contradiction -> warn
            for b in referenced:
                if b["confidence"] >= 0.7 and self._is_negation(text_n, b["value"]):
                    return {
                        "verdict": "warn",
                        "reason": f"Text appears to contradict known belief '{b['value']}' ({b['slot']}).",
                        "suggestion": "Confirm the change with the user before acting.",
                        "slot": b["slot"], "entities": [b["value"]],
                    }

            # 4. low confidence known belief + consequential action -> ask
            if action in CONSEQUENTIAL_ACTIONS:
                for b in referenced:
                    if b["confidence"] < 0.5:
                        return {
                            "verdict": "ask",
                            "reason": f"Belief '{b['value']}' is low-confidence ({b['confidence']:.2f}).",
                            "suggestion": "Confirm with the user before acting on it.",
                            "slot": b["slot"], "entities": [b["value"]],
                        }

            # 5. allow + enrich suggestion
            suggestion = ""
            if referenced:
                linked = ", ".join(b["value"] for b in referenced)
                suggestion = f"Consider linking this to known: {linked}."
            return {
                "verdict": "allow",
                "reason": "Known, safe, and sufficiently confident.",
                "suggestion": suggestion,
                "slot": referenced[0]["slot"] if referenced else None,
                "entities": [b["value"] for b in referenced],
            }

    def _referenced_beliefs(self, text_n: str, entities: Optional[list[str]]) -> list[dict]:
        out = []
        # explicit entity list resolution
        if entities:
            for ent in entities:
                for b in self._beliefs.values():
                    if _norm(b["value"]) == _norm(ent) or _norm(ent) in _norm(b["value"]):
                        out.append(b)
                        break
        # mention scanning by value
        for b in self._beliefs.values():
            if _norm(b["value"]) and _norm(b["value"]) in text_n:
                if b not in out:
                    out.append(b)
        return out

    def _unknown_entities(self, text_n: str, entities, referenced) -> list[str]:
        if not entities:
            return []
        ref_vals = {_norm(b["value"]) for b in referenced}
        unknown = []
        for ent in entities:
            if _norm(ent) not in ref_vals:
                unknown.append(ent)
        return unknown

    @staticmethod
    def _is_negation(text_n: str, value: str) -> bool:
        if not _NEGATION_RE.search(text_n):
            return False
        return _norm(value) in text_n


_instance: Optional[AwarenessStore] = None
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
