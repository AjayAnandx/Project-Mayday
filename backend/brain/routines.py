"""Brain V3 P14: routines — reusable workflows induced from what the user actually does
(Agent Workflow Memory, ICML 2025; Voyager-style verification before saving).

    mine(now)            tool_log (42 days): the same multi-tool sequence used ≥ 3 times on ≥ 2 days
                         -> a routine candidate (+ its usual weekday/hour if consistent)
    induce(llm, cand)    ONE worker call names and describes it: {name, description, trigger_phrases, steps}
    verify(wf, cand)     every step's tool exists and the steps follow the observed order -> else rejected
    prompt_block(text)   matching routines are shown to the model ("your usual way to do this")
    candidates(now)      a routine with a usual time, due now and not yet done today ->
                         "It's your usual Friday report. Start it?" (Do it sends the request to chat)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)
TRIVIAL = {"recall", "recall_entity", "unified_search", "tool_search", "get_weather", "suggest_skill",
           "remember", "get_conversations"}
_WORD = re.compile(r"[a-z]{3,}")
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("routines", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "min_count": int(c.get("min_count", 3)),
            "min_days": int(c.get("min_days", 2)), "lookback_days": int(c.get("lookback_days", 42)),
            "max_induce_per_night": int(c.get("max_induce_per_night", 2))}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def _local(ts: str) -> datetime:
    t = datetime.fromisoformat(ts)
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _sequence(used: list[str]) -> tuple[str, ...]:
    seq: list[str] = []
    for t in used:
        if t not in TRIVIAL and t not in seq:
            seq.append(t)
    return tuple(seq)


def mine(now: datetime | None = None) -> list[dict]:
    cfg = _cfg()
    store = _store()
    if store is None:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=cfg["lookback_days"])).isoformat()
    try:
        rows = store._rows("SELECT ts, query, used FROM tool_log WHERE ts >= ? ORDER BY id", (since,))
    except Exception:
        return []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        seq = _sequence(json.loads(r["used"] or "[]"))
        if len(seq) >= 2:
            groups[seq].append(r)
    out = []
    for seq, rs in groups.items():
        times = [_local(r["ts"]) for r in rs]
        days = {t.date() for t in times}
        if len(rs) < cfg["min_count"] or len(days) < cfg["min_days"]:
            continue
        wd, wn = Counter(t.weekday() for t in times).most_common(1)[0]
        hr, hn = Counter(t.hour for t in times).most_common(1)[0]
        near = sum(1 for t in times if t.weekday() == wd and abs(t.hour - hr) <= 1)
        schedule = {"weekday": wd, "hour": hr} if near >= max(3, 0.6 * len(times)) else None
        out.append({"sequence": list(seq), "count": len(rs), "days": len(days),
                    "examples": [redact(r["query"] or "")[:140] for r in rs[-5:]], "schedule": schedule,
                    "last": max(times).isoformat()})
    return out


_PROMPT = """The user has done the same multi-step task several times with their assistant.
Tools used, in order: {seq}
Example requests:
{examples}

Name this routine so it can be reused. Return JSON only:
{{"name": "<2-5 words, e.g. 'Weekly research report'>",
  "description": "<one sentence: what it produces and for whom>",
  "trigger_phrases": ["<up to 4 short ways the user asks for it>"],
  "steps": [{{"tool": "<one of the tools above>", "purpose": "<why this step>"}}]}}
Use only the listed tools, in the same order."""


def induce(llm, cand: dict) -> dict | None:
    prompt = _PROMPT.format(seq=" → ".join(cand["sequence"]), examples="\n".join(f"- {e}" for e in cand["examples"]))
    resp = llm.chat(messages=[{"role": "user", "content": prompt}], stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def verify(wf: dict | None, cand: dict, known_tools: set[str] | None = None) -> tuple[bool, str]:
    """Self-verification before saving: names real tools, follows the observed order, is described."""
    if not wf or not wf.get("name") or not wf.get("description"):
        return False, "incomplete"
    steps = [s.get("tool") for s in wf.get("steps") or [] if isinstance(s, dict)]
    if not steps:
        return False, "no steps"
    if known_tools is not None and any(t not in known_tools for t in steps):
        return False, "unknown tool"
    it = iter(cand["sequence"])
    if not all(any(t == x for x in it) for t in steps):          # steps must be a subsequence, in order
        return False, "steps don't follow what was observed"
    if set(steps) != set(cand["sequence"]):
        return False, "steps don't cover the observed tools"
    return True, ""


def _known_tools() -> set[str]:
    try:
        from backend.assistant.function_registry import get_tool_definitions
        return {t["function"]["name"] for t in get_tool_definitions()}
    except Exception:
        return set()


def run(now: datetime | None = None, llm=None) -> dict:
    """Mine + induce + verify + save (nightly). Existing routines get their counts refreshed."""
    cfg = _cfg()
    store = _store()
    if not cfg["enabled"] or store is None:
        return {"skipped": True}
    found, created, rejected = mine(now), [], []
    existing = {tuple(json.loads(r["steps"])["sequence"]): r for r in store._rows("SELECT * FROM workflows")
                if r["steps"].startswith("{")}
    tools = _known_tools()
    budget = cfg["max_induce_per_night"]
    for cand in found:
        key = tuple(cand["sequence"])
        if key in existing:
            with store._lock:
                store._conn.execute("UPDATE workflows SET successes=?, evidence=?, updated_at=? WHERE id=?",
                                    (cand["count"], json.dumps({"examples": cand["examples"], "schedule": cand["schedule"],
                                                                "last": cand["last"]}), _now(), existing[key]["id"]))
            continue
        if budget <= 0:
            break
        budget -= 1
        if llm is None:
            from backend.assistant.llm_client import get_worker_client
            llm = get_worker_client()
        wf = induce(llm, cand)
        ok, why = verify(wf, cand, tools or None)
        if not ok:
            rejected.append({"sequence": cand["sequence"], "reason": why})
            continue
        store._insert("workflows", {
            "id": "wf_" + uuid.uuid4().hex[:10], "name": redact(str(wf["name"]))[:60],
            "description": redact(str(wf["description"]))[:240],
            "steps": json.dumps({"sequence": cand["sequence"], "steps": wf["steps"][:8],
                                 "trigger_phrases": [redact(str(p))[:60] for p in (wf.get("trigger_phrases") or [])][:4]}),
            "successes": cand["count"], "status": "active",
            "evidence": json.dumps({"examples": cand["examples"], "schedule": cand["schedule"], "last": cand["last"]}),
            "created_at": _now(), "updated_at": _now()})
        created.append(wf["name"])
    return {"mined": len(found), "created": created, "rejected": rejected}


def active() -> list[dict]:
    store = _store()
    if store is None:
        return []
    out = []
    for r in store._rows("SELECT * FROM workflows WHERE status='active'"):
        if not r["steps"].startswith("{"):
            continue
        r["steps"] = json.loads(r["steps"])
        r["evidence"] = json.loads(r["evidence"] or "{}")
        out.append(r)
    return out


def prompt_block(user_text: str) -> str:
    words = set(_WORD.findall((user_text or "").lower()))
    lines = []
    for r in active():
        vocab = set(_WORD.findall((r["name"] + " " + r["description"] + " "
                                   + " ".join(r["steps"].get("trigger_phrases", []))).lower()))
        if len(words & vocab) >= 2:
            steps = " → ".join(s.get("tool", "") for s in r["steps"]["steps"])
            lines.append(f"- \"{r['name']}\": {r['description']} The user's usual steps: {steps}.")
    if not lines:
        return ""
    return "\n\n### The user's usual routines (follow these steps when they ask for it)\n" + "\n".join(lines[:2])


def candidates(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    out = []
    for r in active():
        sch = (r["evidence"] or {}).get("schedule")
        if not sch or now.weekday() != sch["weekday"] or abs(now.hour - sch["hour"]) > 1:
            continue
        last = r["evidence"].get("last")
        if last and datetime.fromisoformat(last).date() == now.date():
            continue                                               # already done today
        out.append({
            "type": "routine_due", "source": "routines", "dedupe": f"{r['id']}:{now.date()}",
            "text": f"It's about time for your usual \"{r['name']}\". Want me to start it?",
            "why": f"You've done \"{r['name']}\" {r['successes']} times, usually on {_DAYS[sch['weekday']]}s "
                   f"around {sch['hour']:02d}:00.",
            "evidence": [r["id"]], "value": 0.6, "urgency": "timely", "confidence": 0.8, "mode": "nudge",
            "chat_prompt": f"Run my usual routine \"{r['name']}\": {r['description']}",
            "expires_in_min": 120})
    return out
