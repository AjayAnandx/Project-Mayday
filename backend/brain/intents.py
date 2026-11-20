"""Brain V3 P13: latent goal tracking — *why* is the user doing what they're doing?

    activity(now)          deterministic summary of the last 48 h as numbered evidence items:
                           conversations (first user line), tools used, upcoming Planner items,
                           focus sessions, recent sessions/decisions, captured goals
    infer(llm, now)        ONE worker call -> up to 3 hypotheses {goal, evidence [n], p, implies,
                           horizon}; evidence must point at real items (others are dropped)
    update(hyps)           belief update on the `intents` table:
                             matched (word overlap) -> p = 0.5·old + 0.5·new (+0.05 per new evidence)
                             not seen this round   -> p × decay (0.85)
                             p ≥ 0.8 or user-confirmed -> "working";  p < 0.2 -> "dropped"
    maybe_run(now)         throttled (min_interval_h, max_per_day) — called by the generators
    working()              active working goals (for the prompt, recall, prep and candidates)
    candidates(now)        for a working goal with a horizon: implied prerequisites that aren't in
                           the Planner yet -> one framing candidate ("For Thursday's pitch: …")
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)
_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "for", "with", "user", "their", "this", "that", "from", "into", "about", "prep",
         "preparing", "working", "towards", "toward", "upcoming", "plan", "planning"}

_SCHEMA = """CREATE TABLE IF NOT EXISTS intents (
    id TEXT PRIMARY KEY, goal TEXT NOT NULL, p REAL NOT NULL, status TEXT NOT NULL DEFAULT 'hypothesis',
    evidence TEXT NOT NULL DEFAULT '[]', implies TEXT NOT NULL DEFAULT '[]', horizon TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_supported TEXT)"""


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("intents", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "min_interval_h": float(c.get("min_interval_h", 2)),
            "max_per_day": int(c.get("max_per_day", 4)), "decay": float(c.get("decay", 0.85)),
            "working_p": float(c.get("working_p", 0.8)), "drop_p": float(c.get("drop_p", 0.2))}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store():
    from backend.memory.knowledge_graph import get_graph
    store = get_graph()._store
    if store is not None:
        with store._lock:
            store._conn.execute(_SCHEMA)
    return store


def _words(t: str) -> set[str]:
    return {w for w in _WORD.findall((t or "").lower()) if w not in _STOP}


# ------------------------------------------------------------------ activity summary
def activity(now: datetime | None = None, hours: int = 48) -> list[dict]:
    """Numbered evidence items [{"n", "ref", "text"}] — every ref resolves (ledger.evidence_exists)."""
    now = now or datetime.now()
    items: list[dict] = []

    def add(ref: str, text: str) -> None:
        text = redact(" ".join(str(text).split()))[:200]
        if text and not any(i["text"] == text for i in items):
            items.append({"n": len(items) + 1, "ref": ref, "text": text})

    # conversations of the last 2 days (first user message of each)
    try:
        from backend.core.data_store import get_store
        from backend.brain.reflection import _cfg as rcfg
        skip = re.compile(rcfg().get("skip_pattern") or r"\bZZTEST", re.I)
        ds = get_store()
        kept = 0
        days = sorted({(now - timedelta(days=k)).date().isoformat() for k in range(0, hours // 24 + 1)},
                      reverse=True)
        for day in days:
            # many conversations are empty or scripted tests: scan them all, keep up to 25 real ones
            for c in ds.list_conversations(date=day):
                if kept >= 25:
                    break
                conv = ds.get_conversation(c["id"]) or {}
                first = next((m.get("content") for m in conv.get("messages", []) if m.get("role") == "user"), "")
                if first and not (skip and skip.search(str(first))):
                    add(f"conv:{c['id']}", f"Asked Mayday: {first}")
                    kept += 1
    except Exception as e:
        logger.debug("intent activity (conversations): %s", e)
    store = _store()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    if store is not None:
        # tools used
        try:
            rows = store._rows("SELECT used, ts, id FROM tool_log WHERE ts >= ? ORDER BY id DESC LIMIT 200", (since,))
            counts = Counter(t for r in rows for t in json.loads(r["used"] or "[]"))
            if counts:                    # context only: tool usage has no citable row (ref "")
                tools_line = ", ".join(f"{t}×{n}" for t, n in counts.most_common(8))
                items.append({"n": len(items) + 1, "ref": "", "text": f"Tools used recently: {tools_line}"})
        except Exception:
            pass
        # focus sessions (desktop sensor)
        try:
            for r in store._rows("SELECT id, value FROM signals WHERE kind='focus_end' AND ts >= ? "
                                 "ORDER BY id DESC LIMIT 10", (since,)):
                v = json.loads(r["value"] or "{}")
                add(f"s:{r['id']}", f"Deep-focus session: {v.get('category')} for {int(v.get('minutes') or 0)} min")
        except Exception:
            pass
        # recent sessions / decisions
        for e in store.list_episodes("session", limit=8) + store.list_episodes("decision", limit=4):
            add(e["id"], f"{'Session' if e['kind'] == 'session' else 'Decision'} ({e['day']}): {e['summary']}")
        # stated goals
        for f in store._rows("SELECT id, object FROM facts WHERE status='active' AND (category='goal' OR "
                             "predicate='goal') ORDER BY created_at DESC LIMIT 5"):
            add(f["id"], f"Stated goal: {f['object']}")
    # upcoming planner items (next 7 days)
    try:
        from backend.core.planner_store import get_planner
        for i in get_planner().list_items(view="upcoming", days=7)[:20]:
            add(f"p:{i['id']}", f"Planner {i['kind']}: {i.get('title', '')} at "
                                f"{i.get('occurrence_at') or i.get('due_at') or i.get('start_at') or '?'}")
    except Exception as e:
        logger.debug("intent activity (planner): %s", e)
    return items


# ------------------------------------------------------------------ inference (one model call)
_PROMPT = """From the user's recent activity, infer what they are working TOWARDS (the goal behind the
actions), e.g. "flight search + slide deck edits + investor meeting Thursday" -> "pitch prep for the
investor meeting on Thursday", not "a vacation". Today is {today}.

Return JSON only: {{"hypotheses": [
  {{"goal": "<the goal, specific, max 15 words>", "evidence": [<item numbers that support it>],
    "p": <0..1 how likely>, "implies": ["<prerequisites this goal needs, max 4>"],
    "horizon": "<YYYY-MM-DD when it is due, or null>"}}]}}
At most 3 hypotheses, best first. Every hypothesis needs at least 2 evidence items. Don't invent
goals the items don't support; if nothing coherent, return {{"hypotheses": []}}.

Activity:
{items}
JSON:"""


def infer(llm, items: list[dict], now: datetime) -> list[dict]:
    if len(items) < 2:
        return []
    prompt = _PROMPT.format(today=now.date().isoformat(), items="\n".join(f"[{i['n']}] {i['text']}" for i in items))
    resp = llm.chat(messages=[{"role": "user", "content": prompt}], stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    by_n = {i["n"]: i for i in items}
    out = []
    for h in (data.get("hypotheses") or [])[:3]:
        if not isinstance(h, dict) or not h.get("goal"):
            continue
        nums = [int(x) for x in (h.get("evidence") or []) if str(x).isdigit() and int(x) in by_n]
        refs = [by_n[n]["ref"] for n in nums if by_n[n]["ref"]]
        if len(nums) < 2 or not refs:
            continue                     # unsupported: dropped
        horizon = str(h.get("horizon") or "")[:10]
        out.append({"goal": redact(str(h["goal"]))[:160], "p": max(0.0, min(1.0, float(h.get("p") or 0.5))),
                    "evidence": refs, "implies": [redact(str(x))[:80] for x in (h.get("implies") or [])][:4],
                    "horizon": horizon if re.fullmatch(r"\d{4}-\d{2}-\d{2}", horizon) else None})
    return out


# ------------------------------------------------------------------ belief update
def _similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def update(hyps: list[dict]) -> dict:
    cfg = _cfg()
    store = _store()
    now = _now_iso()
    existing = store._rows("SELECT * FROM intents WHERE status IN ('hypothesis','working')")
    # user-confirmed goals ('confirmed') are matched for new evidence but never decay
    confirmed = store._rows("SELECT * FROM intents WHERE status='confirmed'")
    touched = set()
    created = updated = 0
    for h in hyps:
        best = max(existing + confirmed, key=lambda r: _similar(h["goal"], r["goal"]), default=None)
        if best and _similar(h["goal"], best["goal"]) >= 0.4 and best["id"] not in touched:
            old_ev = json.loads(best["evidence"] or "[]")
            new_ev = [e for e in h["evidence"] if e not in old_ev]
            p = min(1.0, 0.5 * best["p"] + 0.5 * h["p"] + 0.05 * len(new_ev))
            if best["status"] in ("working", "confirmed"):
                status = best["status"]
            else:
                status = "working" if p >= cfg["working_p"] else "hypothesis"
            with store._lock:
                store._conn.execute(
                    "UPDATE intents SET p=?, status=?, evidence=?, implies=?, horizon=COALESCE(?, horizon), "
                    "updated_at=?, last_supported=? WHERE id=?",
                    (p, status, json.dumps((old_ev + new_ev)[-15:]), json.dumps(h["implies"] or json.loads(best["implies"])),
                     h["horizon"], now, now, best["id"]))
            touched.add(best["id"])
            updated += 1
        else:
            iid = "it_" + uuid.uuid4().hex[:10]
            status = "working" if h["p"] >= cfg["working_p"] else "hypothesis"
            store._insert("intents", {"id": iid, "goal": h["goal"], "p": h["p"], "status": status,
                                      "evidence": json.dumps(h["evidence"]), "implies": json.dumps(h["implies"]),
                                      "horizon": h["horizon"], "created_at": now, "updated_at": now,
                                      "last_supported": now})
            touched.add(iid)
            created += 1
    decayed = dropped = 0
    for r in existing:
        if r["id"] in touched:
            continue
        p = r["p"] * cfg["decay"]
        status = "dropped" if p < cfg["drop_p"] else r["status"]
        with store._lock:
            store._conn.execute("UPDATE intents SET p=?, status=?, updated_at=? WHERE id=?", (p, status, now, r["id"]))
        decayed += 1
        dropped += status == "dropped"
    return {"created": created, "updated": updated, "decayed": decayed, "dropped": dropped}


def confirm(iid: str, correct: bool) -> bool:
    """User feedback: confirmed -> working (p=1); 'not right' -> rejected (never resurrected by decay)."""
    store = _store()
    if not store._rows("SELECT 1 FROM intents WHERE id=?", (iid,)):
        return False
    with store._lock:
        if correct:
            store._conn.execute("UPDATE intents SET p=1.0, status='confirmed', updated_at=? WHERE id=?",
                                (_now_iso(), iid))
        else:
            store._conn.execute("UPDATE intents SET p=0, status='rejected', updated_at=? WHERE id=?", (_now_iso(), iid))
    from backend.brain.feedback import update_type
    update_type("intent", "accepted" if correct else "dismissed")
    return True


def working(limit: int = 3) -> list[dict]:
    store = _store()
    if store is None:
        return []
    today = datetime.now().date().isoformat()
    rows = store._rows("SELECT * FROM intents WHERE status IN ('working','confirmed') AND "
                       "(horizon IS NULL OR horizon >= ?) ORDER BY p DESC, updated_at DESC LIMIT ?", (today, limit))
    for r in rows:
        r["evidence"] = json.loads(r["evidence"] or "[]")
        r["implies"] = json.loads(r["implies"] or "[]")
    return rows


def _runs_today(store) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return len([1 for r in store._rows("SELECT value FROM meta WHERE key LIKE 'intent_run:%'")
                if r["value"] >= since])


def maybe_run(now: datetime | None = None, llm=None, force: bool = False) -> dict:
    cfg = _cfg()
    store = _store()
    if not cfg["enabled"] or store is None:
        return {"skipped": "disabled"}
    last = store.get_meta("intent_last_run")
    if not force:
        if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < timedelta(hours=cfg["min_interval_h"]):
            return {"skipped": "too soon"}
        if _runs_today(store) >= cfg["max_per_day"]:
            return {"skipped": "daily cap"}
    now = now or datetime.now()
    items = activity(now)
    stamp = _now_iso()
    store._set_meta("intent_last_run", stamp)
    store._set_meta(f"intent_run:{stamp}", stamp)
    if llm is None:
        from backend.assistant.llm_client import get_worker_client
        llm = get_worker_client()
    try:
        hyps = infer(llm, items, now)
    except Exception as e:
        logger.warning("intent inference failed: %s", e)
        return {"error": str(e)[:200]}
    res = update(hyps)
    _refresh_working_memory()
    return {"items": len(items), "hypotheses": len(hyps), **res}


def _refresh_working_memory() -> None:
    try:
        from backend.brain.working import get_working
        w = get_working()
        w.intents = [{"goal": r["goal"], "p": round(r["p"], 2), "horizon": r.get("horizon")} for r in working()]
    except Exception:
        pass


# ------------------------------------------------------------------ candidates
def candidates(now: datetime | None = None) -> list[dict]:
    """Working goal with a horizon: prerequisites that no open Planner item mentions -> one framing card."""
    now = now or datetime.now()
    out = []
    try:
        from backend.core.planner_store import get_planner
        open_titles = [i.get("title", "") for i in get_planner().all_items() if i.get("status") == "open"]
    except Exception:
        open_titles = []
    for r in working():
        if not r.get("horizon") or not r["implies"]:
            continue
        try:
            days = (datetime.fromisoformat(r["horizon"]).date() - now.date()).days
        except ValueError:
            continue
        if not 0 <= days <= 7:
            continue
        missing = [x for x in r["implies"] if not any(_similar(x, t) >= 0.34 for t in open_titles)]
        if not missing:
            continue
        due = r["horizon"]
        out.append({
            "type": "intent_prereqs", "source": "intents", "dedupe": f"{r['id']}:{','.join(missing)}",
            "text": f"For \"{r['goal']}\": {', '.join(missing[:3])} — add {'these' if len(missing) > 1 else 'it'} "
                    f"to your Planner?",
            "why": f"You seem to be working towards \"{r['goal'][:80]}\" by {due}, and nothing is planned for "
                   f"{missing[0]}.",
            "evidence": [f"i:{r['id']}"] + r["evidence"][:3], "value": 0.65 if days <= 3 else 0.5,
            "urgency": "timely", "confidence": min(0.9, r["p"]), "mode": "framing",
            "options": [{"label": f"Add {len(missing[:3])} task{'s' if len(missing[:3]) > 1 else ''}",
                         "action": {"kind": "planner_create_task",
                                    "payload": {"title": "; ".join(missing[:3]), "due_at": due}}},
                        {"label": "Not needed", "action": None}],
            "expires_in_min": 24 * 60})
    return out
