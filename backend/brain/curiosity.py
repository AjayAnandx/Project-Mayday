"""Brain V3 P14: curiosity — when a new topic keeps coming up, learn about it before being asked.

    discover(llm, now)      ONE worker call (nightly): from the user's last 14 days of messages and
                            the topics Mayday already knows (research topics, projects), propose topics
                            the user RETURNS to (≥ 2 different conversations) that Mayday knows little
                            about, each with one concrete question. Evidence = real conversation ids.
    learn(now)              starts quick, budget-capped research runs (max_per_day) for queued topics
    on_research_finished()  called by research_flow for these runs: no direct announcement — a
                            low-urgency candidate goes through the decision gate (usually the digest)

Inspired by Voyager's automatic curriculum ("what to learn next") and "Into the Unknown"
(detect what you don't know, search, store). Nothing is fine-tuned: the result is an
evidence-checked research topic Mayday can recall from.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)

_SCHEMA = """CREATE TABLE IF NOT EXISTS curiosity (
    id TEXT PRIMARY KEY, topic TEXT NOT NULL, question TEXT NOT NULL, evidence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued', run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("curiosity", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "max_per_day": int(c.get("max_per_day", 2)),
            "lookback_days": int(c.get("lookback_days", 14))}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store():
    from backend.memory.knowledge_graph import get_graph
    store = get_graph()._store
    if store is not None:
        with store._lock:
            store._conn.execute(_SCHEMA)
    return store


def _known_topics() -> list[str]:
    out = []
    try:
        from backend.core.research_store import get_research_store
        out += [r.get("topic", "") for r in get_research_store().list_projects()][:60]
    except Exception:
        pass
    try:
        from backend.core.project_store import get_project_store
        out += [p.get("name", "") for p in get_project_store().list_projects()][:40]
    except Exception:
        pass
    store = _store()
    if store is not None:
        out += [r["topic"] for r in store._rows("SELECT topic FROM curiosity")]
    return [t for t in out if t]


_PROMPT = """You help a personal assistant decide what to LEARN about next for its user.
Below are things the user said in different conversations (with ids), and topics the assistant
already knows. Find up to 2 topics the user keeps coming back to (in at least 2 DIFFERENT
conversations) that are NOT already among the known topics and where a short, factual research
brief would genuinely help them. Skip small talk, requests already fully answered, and anything
private (health details of others, finances, passwords).

Return JSON only: {{"topics": [{{"topic": "<short name>", "question": "<one concrete question to research>",
"evidence": ["<conversation ids>"]}}]}}  or {{"topics": []}}.

Known topics: {known}

What the user said:
{lines}
JSON:"""


def discover(llm, now: datetime | None = None) -> list[dict]:
    from backend.brain.intents import activity
    now = now or datetime.now()
    items = [i for i in activity(now, hours=24 * _cfg()["lookback_days"]) if i["ref"].startswith("conv:")]
    if len(items) < 2:
        return []
    known = _known_topics()
    lines = "\n".join(f"[{i['ref'][5:]}] {i['text'].removeprefix('Asked Mayday: ')}" for i in items[:40])
    resp = llm.chat(messages=[{"role": "user", "content": _PROMPT.format(known=", ".join(known[:80]) or "none",
                                                                         lines=lines)}],
                    stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    valid_ids = {i["ref"][5:] for i in items}
    known_l = [k.lower() for k in known]
    store = _store()
    added = []
    for t in (data.get("topics") or [])[:2]:
        if not isinstance(t, dict) or not t.get("topic") or not t.get("question"):
            continue
        ev = sorted({str(e).removeprefix("conv:") for e in (t.get("evidence") or [])} & valid_ids)
        if len(ev) < 2:
            continue                                         # must recur across conversations
        topic = redact(str(t["topic"]))[:80]
        if any(topic.lower() in k or k in topic.lower() for k in known_l if len(k) > 3):
            continue                                         # already known
        row = {"id": "cu_" + uuid.uuid4().hex[:10], "topic": topic, "question": redact(str(t["question"]))[:200],
               "evidence": json.dumps([f"conv:{e}" for e in ev]), "status": "queued", "run_id": None,
               "created_at": _now(), "updated_at": _now()}
        store._insert("curiosity", row)
        added.append(row)
    return added


def _started_today(store) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return store._rows("SELECT COUNT(*) n FROM curiosity WHERE status IN ('researching','done') AND updated_at >= ?",
                       (since,))[0]["n"]


def learn(now: datetime | None = None, start=None) -> list[dict]:
    """Start quick research runs for queued topics (capped per day)."""
    cfg = _cfg()
    store = _store()
    if not cfg["enabled"] or store is None:
        return []
    if start is None:
        from backend.core.research_flow import start_research_run as start
    from backend.functions.research_flow_functions import BUDGET_PRESETS
    started = []
    for row in store._rows("SELECT * FROM curiosity WHERE status='queued' ORDER BY created_at"):
        if _started_today(store) >= cfg["max_per_day"]:
            break
        res = start(row["topic"], request=row["question"], questions=[row["question"]], research_type="domain",
                    budget=dict(BUDGET_PRESETS["quick"]), options={"brain_curiosity": True})
        status = "skipped" if "error" in res else "researching"
        with store._lock:
            store._conn.execute("UPDATE curiosity SET status=?, run_id=?, updated_at=? WHERE id=?",
                                (status, res.get("run_id") or res.get("id"), _now(), row["id"]))
        started.append({"topic": row["topic"], "status": status, "error": res.get("error")})
    return started


def on_research_finished(topic: str, final: dict) -> None:
    """A self-started run ended: mark it, and let the decision gate decide whether to mention it."""
    store = _store()
    rows = store._rows("SELECT * FROM curiosity WHERE topic=? ORDER BY created_at DESC LIMIT 1", (topic,))
    if not rows:
        return
    row = rows[0]
    ok = final.get("status") in ("completed", "done") and (final.get("answers") or final.get("outputs"))
    with store._lock:
        store._conn.execute("UPDATE curiosity SET status=?, updated_at=? WHERE id=?",
                            ("done" if ok else "failed", _now(), row["id"]))
    if not ok:
        return
    from backend.brain.proactive import submit
    ev = json.loads(row["evidence"])
    submit({"type": "curiosity_brief", "source": "curiosity", "dedupe": row["id"],
            "text": f"You've brought up \"{row['topic']}\" a few times, so I read up on it: "
                    f"{row['question']} (Research tab).",
            "why": f"\"{row['topic']}\" came up in {len(ev)} separate conversations recently.",
            "evidence": ev[:3], "value": 0.5, "urgency": "low", "confidence": 0.8, "mode": "nudge",
            "expires_in_min": 48 * 60})


def run_nightly(now: datetime | None = None, llm=None) -> dict:
    if not _cfg()["enabled"]:
        return {"skipped": True}
    if llm is None:
        from backend.assistant.llm_client import get_worker_client
        llm = get_worker_client()
    try:
        found = discover(llm, now)
    except Exception as e:
        logger.warning("curiosity discover failed: %s", e)
        found = []
    return {"discovered": [f["topic"] for f in found], "started": learn(now)}
