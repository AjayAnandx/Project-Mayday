"""PHF-Mini: hierarchical user modeling for Mayday personalization.

Implements the Practice->Habitus->Field hierarchy from
"Beyond Isolated Behaviors: Hierarchical User Modeling for LLM Personalization"
(Wang et al., Fudan/OPPO) in a lightweight, training-free way suitable for a
single-user local assistant.

  - Practice   : each user interaction is abstracted into a discrete semantic
                 prototype (Semantic ID) reusing the existing QueryClassifier
                 intent + a keyword bucket. Surface noise is stripped.
  - Habitus    : recent practices are temporally aggregated (sqrt-recency
                 weighting, per the paper) into a compact per-user disposition
                 summary injected into the prompt. Computed once per turn from
                 an append-only practice log; never re-serializes all history.
  - Field      : single-user local app -> cross-user clustering is N/A. Stubbed
                 as contextual clustering (work/personal) for future use.

The knowledge graph remains the single source of truth for explicit facts
(`remember`); PHF's habitus is a *derived* compact signal on top of it.
"""

import json
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.core.config import load_config
from backend.core.query_classifier import QueryClassifier
from backend.core.user_awareness import _USER_LABEL
from backend.memory.knowledge_graph import get_graph


_UTC = timezone.utc

# Coarse label for each intent (the "dominant behavioral intent" level).
_INTENT_LABELS = {
    "build": "builds websites/projects",
    "research": "researches topics deeply",
    "project": "manages projects and tasks",
    "todo": "tracks todos and reminders",
    "calendar": "schedules events and meetings",
    "memory": "relies on long-term memory",
    "system": "controls the desktop/system",
    "weather": "checks the weather",
    "simple_qa": "asks factual questions",
    "greeting": "chat socially",
    "general": "chats generally",
}

# Finer residual bucket keywords -> human label (the deeper quantization level).
_BUCKET_KEYWORDS = [
    ("exam", "exam"), ("study", "study"), ("work", "work"),
    ("code", "coding"), ("music", "music"), ("movie", "movies"),
    ("health", "health"), ("finance", "finance"), ("family", "family"),
    ("friend", "friends"), ("travel", "travel"), ("food", "food"),
    ("email", "email"), ("document", "documents"), ("pdf", "documents"),
    ("voice", "voice mode"), ("dashboard", "the dashboard"),
]

_PRACTICE_LOG_MAX = 400
_HABITUS_RECENT = 200


def _utcnow() -> str:
    return datetime.now(_UTC).isoformat()


def _days_since(iso_ts: str) -> float:
    if not iso_ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return (datetime.now(_UTC) - dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 0.0


def _practice_log_path() -> Path:
    cfg = load_config()
    p = cfg.get("phf", {}).get("practice_log", "practices.jsonl")
    if not Path(p).is_absolute():
        p = Path(__file__).resolve().parent.parent.parent / p
    return Path(p)


def _habitus_path() -> Path:
    cfg = load_config()
    p = cfg.get("phf", {}).get("habitus_path", "habitus.json")
    if not Path(p).is_absolute():
        p = Path(__file__).resolve().parent.parent.parent / p
    return Path(p)


class PracticeAbstraction:
    """Map a raw interaction to a discrete 2-level Semantic ID (coarse:intent,
    fine: keyword bucket). Deterministic, no model training."""

    def __init__(self):
        self._classifier = QueryClassifier()

    def tag(self, text: str, intent: str | None = None) -> str:
        if not intent:
            intent = self._classifier.classify(text).intent
        fine = ""
        low = (text or "").lower()
        for kw, label in _BUCKET_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                fine = label
                break
        return f"{intent}:{fine}" if fine else intent

    def label(self, code: str) -> str:
        coarse = code.split(":", 1)[0]
        fine = code.split(":", 1)[1] if ":" in code else ""
        base = _INTENT_LABELS.get(coarse, coarse)
        if not fine:
            return base
        return f"{base} (esp. {fine})"


class HabitusBuilder:
    """Temporally weighted aggregation of recent practices -> compact disposition."""

    def __init__(self):
        self._lock = threading.RLock()
        self._vec: dict[str, float] = {}
        self._summary: str = ""
        self._load()

    # ---- practice log ----
    def log_interaction(self, text: str, intent: str | None = None) -> None:
        code = _PRACTICE.tag(text, intent)
        entry = {"ts": _utcnow(), "code": code}
        path = _practice_log_path()
        try:
            with self._lock:
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
        # Incremental update of the cached habitus vector.
        self._rebuild()

    def _read_recent(self) -> list[dict]:
        path = _practice_log_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out[-_HABITUS_RECENT:]

    def _rebuild(self) -> None:
        recent = self._read_recent()
        vec: dict[str, float] = {}
        for p in recent:
            age = _days_since(p.get("ts"))
            # sqrt-recency: recent behaviors matter more, but sublinearly.
            w = 1.0 / math.sqrt(1.0 + age)
            vec[p.get("code", "general")] = vec.get(p.get("code", "general"), 0.0) + w
        total = sum(vec.values()) or 1.0
        self._vec = {k: v / total for k, v in vec.items()}
        self._summary = self._summarize()
        self._save()

    def _summarize(self) -> str:
        if not self._vec:
            return ""
        ranked = sorted(self._vec.items(), key=lambda kv: kv[1], reverse=True)
        # Keep top 4 dispositions -> a few-line compact summary (not a noisy dump).
        top = ranked[:4]
        clauses = [_PRACTICE.label(code) for code, _ in top]
        if not clauses:
            return ""
        return "Mayday's sense of you: " + "; ".join(clauses) + "."

    def disposition_summary(self) -> str:
        return self._summary

    def _load(self) -> None:
        path = _habitus_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._vec = data.get("vec", {})
                self._summary = data.get("summary", "")
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        path = _habitus_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(
                {"vec": self._vec, "summary": self._summary}, indent=2, ensure_ascii=False
            ), encoding="utf-8")
        except OSError:
            pass


class FieldBuilder:
    """Stub: cross-user clustering is N/A for a single local user. Reserved for
    contextual (work/personal) grouping later. Returns an empty signal."""

    def field_signal(self) -> str:
        return ""


# Slots whose graph edges represent explicit personal facts worth surfacing.
_PERSONAL_FACT_SLOTS = (
    "identity", "relations", "favorites", "belongings",
    "goals", "problems", "context",
)


def _personal_facts() -> str:
    """Compact 'about you' block derived from the user node's edges in the graph.

    Skips legacy belief:* mirror nodes. Prefers each node's `name` property
    (so person nodes render as 'Mom' not 'person:mom').
    """
    try:
        kg = get_graph()
        user = kg.get_node_by_label(_USER_LABEL)
        if not user:
            return ""
        uid = user["id"]
        name = user.get("properties", {}).get("name")
        by_rel: dict[str, list[str]] = {}
        edges = kg._edges
        edge_list = list(edges.values()) if isinstance(edges, dict) else edges
        for e in edge_list:
            if e.get("source") != uid:
                continue
            tgt = kg.get_node(e.get("target"))
            if not tgt:
                continue
            label = tgt["label"]
            if label.startswith("belief:"):
                continue
            text = tgt.get("properties", {}).get("name") or label
            by_rel.setdefault(e["relation"], []).append(text)
        if not by_rel and not name:
            return ""
        lines = []
        if name:
            lines.append(f"Name: {name}")
        for rel in _PERSONAL_FACT_SLOTS:
            vals = by_rel.get(rel)
            if not vals:
                continue
            seen: list[str] = []
            for v in vals:
                if v not in seen:
                    seen.append(v)
            lines.append(f"{rel.capitalize()}: " + ", ".join(seen[:6]))
        # Any other relations not in the canonical slot list (e.g. 'knows').
        for rel, vals in by_rel.items():
            if rel in _PERSONAL_FACT_SLOTS:
                continue
            seen = []
            for v in vals:
                if v not in seen:
                    seen.append(v)
            lines.append(f"{rel}: " + ", ".join(seen[:6]))
        return "\n".join(lines)
    except Exception:
        return ""


def rebuild_habitus() -> None:
    """Recompute the cached habitus vector from the full practice log."""
    try:
        _HABITUS._rebuild()
    except Exception:
        pass


# Module-level singletons (lazy).
_PRACTICE = PracticeAbstraction()
_HABITUS = HabitusBuilder()
_FIELD = FieldBuilder()


def log_interaction(text: str, intent: str | None = None) -> None:
    """Record one user interaction as a practice and refresh habitus."""
    if not load_config().get("phf", {}).get("enabled", True):
        return
    try:
        _HABITUS.log_interaction(text, intent)
    except Exception:
        pass


def disposition_summary() -> str:
    if not load_config().get("phf", {}).get("enabled", True):
        return ""
    try:
        about = _personal_facts()
        habitus = _HABITUS.disposition_summary()
        parts = []
        if about:
            parts.append("About you (personal facts):\n" + about)
        if habitus:
            parts.append(habitus)
        return "\n\n".join(parts)
    except Exception:
        return ""


def personal_facts() -> str:
    if not load_config().get("phf", {}).get("enabled", True):
        return ""
    try:
        return _personal_facts()
    except Exception:
        return ""


def field_signal() -> str:
    return _FIELD.field_signal()
