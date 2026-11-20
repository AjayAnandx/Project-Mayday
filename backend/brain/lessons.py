"""Brain V3 P10: learning from mistakes (Reflexion + ExpeL).

Mistakes come from:
  * a frustrated / correcting user turn (timing.dissatisfaction >= 0.5)
  * the same tool failing again (2nd occurrence of a tool error)
Each is queued and turned into ONE short lesson by the worker model (rate-limited per day):
    {"trigger": "when the user says 'send it to him'", "lesson": "confirm the recipient …",
     "scope": "tool:gmail_send" | "topic:<word>" | "general"}
Merging (ExpeL): a similar existing lesson gets an upvote instead of a duplicate.
A lesson becomes ACTIVE after a second occurrence or the user's confirmation; only active
lessons are injected (top 3 relevant per turn). If a lesson was injected and the user is
dissatisfied again in that conversation, it is downvoted; at 0 votes it is retired.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)
_WORD = re.compile(r"[a-z][a-z0-9_]{2,}")
_STOP = {"the", "and", "for", "that", "this", "with", "when", "user", "you", "your", "what", "then", "from",
         "about", "have", "they", "them", "should", "instead", "before", "after", "mayday"}


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("lessons", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "max_per_day": int(c.get("max_per_day", 6)),
            "min_dissatisfaction": float(c.get("min_dissatisfaction", 0.5)),
            "inject": int(c.get("inject", 3))}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


# ---------------------------------------------------------------- detection (queue)
class LessonQueue:
    def __init__(self):
        self._q: deque = deque(maxlen=50)
        self._lock = threading.Lock()
        self._tool_errors: Counter = Counter()
        self._injected: dict[str, list[str]] = {}       # conv_id -> lesson ids injected last turn
        self._running = False

    def observe_turn(self, text: str, conv_id: str, previous_user: list[str] | None,
                     previous_assistant: str, score: float, reasons: list[str]) -> None:
        if score >= _cfg()["min_dissatisfaction"]:
            for lid in self._injected.pop(conv_id, []):       # an injected lesson didn't prevent it
                vote(lid, -1, reason="mistake repeated after injection")
            self._push({"kind": "dissatisfaction", "conv_id": conv_id, "score": score, "reasons": reasons,
                        "user_now": text[:600], "user_before": (previous_user or [""])[-1][:400],
                        "assistant_before": (previous_assistant or "")[:800]})
        else:
            self._injected.pop(conv_id, None)

    def observe_tool_errors(self, user_text: str, errors: list[dict], conv_id: str = "") -> None:
        for e in errors:
            tool = e.get("tool", "?")
            key = (tool, re.sub(r"\d+", "#", str(e.get("error", ""))[:60]))
            self._tool_errors[key] += 1
            if self._tool_errors[key] == 2:                   # second time: worth a lesson
                self._push({"kind": "tool_error", "conv_id": conv_id, "tool": tool,
                            "error": str(e.get("error", ""))[:400], "args_keys": e.get("args_keys", []),
                            "user_now": user_text[:400]})

    def remember_injected(self, conv_id: str, lesson_ids: list[str]) -> None:
        if conv_id and lesson_ids:
            self._injected[conv_id] = lesson_ids

    def _push(self, item: dict) -> None:
        with self._lock:
            self._q.append({**item, "ts": _now()})

    def pending(self) -> int:
        return len(self._q)

    def process(self, llm=None) -> list[dict]:
        """Turn queued mistakes into lessons (respecting the daily cap)."""
        out = []
        while True:
            with self._lock:
                if not self._q:
                    break
                item = self._q.popleft()
            if _written_today() >= _cfg()["max_per_day"]:
                logger.info("lesson cap reached for today; dropping a queued mistake")
                continue
            if llm is None:
                from backend.assistant.llm_client import get_worker_client
                llm = get_worker_client()
            try:
                les = write_lesson(llm, item)
            except Exception as e:
                logger.warning("lesson writer failed: %s", e)
                continue
            if les:
                out.append(merge(les, evidence=item))
        return out

    def process_async(self) -> None:
        if self._running or not self._q or not _cfg()["enabled"]:
            return
        self._running = True

        def run():
            try:
                self.process()
            finally:
                self._running = False
        threading.Thread(target=run, daemon=True, name="brain-lessons").start()


_QUEUE = LessonQueue()


def get_queue() -> LessonQueue:
    return _QUEUE


def _written_today() -> int:
    store = _store()
    if store is None:
        return 0
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return store._rows("SELECT COUNT(*) n FROM lessons WHERE created_at >= ?", (since,))[0]["n"]


# ---------------------------------------------------------------- writing (Reflexion)
_PROMPT = """You are the self-reflection step of a personal assistant. Something went wrong in a
conversation. Write ONE short, reusable lesson so it does not happen again.

What happened:
{what}

Return JSON only:
{{"trigger": "<when this situation comes up again, in general terms (max 15 words)>",
  "lesson": "<what to do differently, imperative, concrete (max 30 words)>",
  "scope": "tool:<tool_name>" | "topic:<one word>" | "general",
  "confidence": 0..1}}
If the user's reply is polite, positive or neutral ("no worries", "thanks", "ok"), or they were not
actually unhappy with the assistant, or nothing reusable can be learned, return {{"none": true}}.
Never write a lesson about etiquette or tone unless the user explicitly complained about it."""


def _describe(item: dict) -> str:
    if item["kind"] == "tool_error":
        return (f"The tool '{item['tool']}' failed twice. Latest error: {item['error']}\n"
                f"Arguments given: {', '.join(item.get('args_keys') or [])}\nUser asked: {item['user_now']}")
    return (f"User earlier: {item['user_before']}\nAssistant answered: {item['assistant_before']}\n"
            f"User then said: {item['user_now']}\nSignals: {', '.join(item.get('reasons') or [])}")


def write_lesson(llm, item: dict) -> dict | None:
    resp = llm.chat(messages=[{"role": "user", "content": _PROMPT.format(what=redact(_describe(item)))}],
                    stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("none") or not data.get("lesson") or not data.get("trigger"):
        return None
    if float(data.get("confidence") or 0) < 0.5:
        return None
    scope = str(data.get("scope") or "general")[:60]
    if item["kind"] == "tool_error":
        scope = f"tool:{item['tool']}"
    return {"trigger": redact(str(data["trigger"]))[:160], "lesson": redact(str(data["lesson"]))[:240],
            "scope": scope}


# ---------------------------------------------------------------- merging (ExpeL) + votes
def _similar(a: dict, b: dict) -> float:
    wa, wb = _words(a["trigger"] + " " + a["lesson"]), _words(b["trigger"] + " " + b["lesson"])
    if not wa or not wb:
        return 0.0
    j = len(wa & wb) / len(wa | wb)
    return j + (0.2 if a.get("scope") == b.get("scope") and a.get("scope") != "general" else 0.0)


def merge(les: dict, evidence: dict | None = None) -> dict:
    store = _store()
    existing = store._rows("SELECT * FROM lessons WHERE status IN ('candidate','active')")
    best = max(existing, key=lambda r: _similar(les, r), default=None)
    ev = {"kind": (evidence or {}).get("kind"), "conv": (evidence or {}).get("conv_id"), "ts": _now()}
    if best and _similar(les, best) >= 0.45:
        evs = json.loads(best["evidence"] or "[]") + [ev]
        with store._lock:
            store._conn.execute(
                "UPDATE lessons SET votes = votes + 1, evidence = ?, updated_at = ?, "
                "status = CASE WHEN votes + 1 >= 2 THEN 'active' ELSE status END WHERE id = ?",
                (json.dumps(evs[-10:]), _now(), best["id"]))
        return {**best, "merged": True}
    row = {"id": "l_" + uuid.uuid4().hex[:12], "trigger": les["trigger"], "lesson": les["lesson"],
           "scope": les["scope"], "votes": 1, "status": "candidate", "evidence": json.dumps([ev]),
           "created_at": _now(), "updated_at": _now()}
    store._insert("lessons", row)
    return row


def vote(lid: str, delta: int, reason: str = "") -> None:
    store = _store()
    if store is None:
        return
    with store._lock:
        store._conn.execute("UPDATE lessons SET votes = votes + ?, updated_at = ? WHERE id = ?",
                            (delta, _now(), lid))
        store._conn.execute("UPDATE lessons SET status = 'retired' WHERE id = ? AND votes <= 0", (lid,))
        store._conn.execute("UPDATE lessons SET status = 'active' WHERE id = ? AND votes >= 2 "
                            "AND status = 'candidate'", (lid,))
    if reason:
        logger.info("lesson %s %+d (%s)", lid, delta, reason)


def set_status(lid: str, status: str) -> None:
    store = _store()
    with store._lock:
        store._conn.execute("UPDATE lessons SET status=?, updated_at=? WHERE id=?", (status, _now(), lid))


# ---------------------------------------------------------------- injection
def relevant(user_text: str, tool_names: list[str] | None = None, k: int | None = None) -> list[dict]:
    store = _store()
    if store is None:
        return []
    k = k or _cfg()["inject"]
    words = _words(user_text)
    tools = set(tool_names or [])
    scored = []
    for r in store._rows("SELECT * FROM lessons WHERE status = 'active'"):
        s = len(words & _words(r["trigger"])) * 1.0 + 0.3 * len(words & _words(r["lesson"]))
        scope = r.get("scope") or ""
        if scope.startswith("tool:") and scope[5:] in tools:
            s += 1.5
        elif scope.startswith("topic:") and scope[6:].lower() in words:
            s += 1.5
        if s >= 1.0:
            scored.append((s + 0.1 * r["votes"], r))
    scored.sort(key=lambda x: -x[0])
    chosen = [r for _, r in scored[:k]]
    if chosen:
        with store._lock:
            store._conn.executemany("UPDATE lessons SET uses = uses + 1, last_used = ? WHERE id = ?",
                                    [(_now(), r["id"]) for r in chosen])
    return chosen


def prompt_block(user_text: str, tool_names: list[str] | None = None, conv_id: str = "") -> str:
    """'### Lessons from past mistakes' for the system prompt ('' when none apply)."""
    from backend.brain.feedback import active_prefs
    les = relevant(user_text, tool_names)
    prefs = active_prefs(3)
    if not les and not prefs:
        return ""
    get_queue().remember_injected(conv_id, [r["id"] for r in les])
    lines = [f"- When {r['trigger'].removeprefix('when ').removeprefix('When ')}: {r['lesson']}" for r in les]
    lines += [f"- {p['preference']}" for p in prefs]
    return ("\n\n### Lessons from past mistakes (apply them; they come from this user's corrections)\n"
            + "\n".join(lines))


def maintain() -> dict:
    """Nightly: retire stale candidates (one occurrence, 30+ days) and unused actives (90+ days)."""
    store = _store()
    if store is None:
        return {}
    now = datetime.now(timezone.utc)
    with store._lock:
        a = store._conn.execute("UPDATE lessons SET status='retired' WHERE status='candidate' AND created_at < ?",
                                ((now - timedelta(days=30)).isoformat(),)).rowcount
        b = store._conn.execute("UPDATE lessons SET status='retired' WHERE status='active' AND "
                                "COALESCE(last_used, updated_at) < ?", ((now - timedelta(days=90)).isoformat(),)
                                ).rowcount
    return {"retired_candidates": a or 0, "retired_unused": b or 0}
