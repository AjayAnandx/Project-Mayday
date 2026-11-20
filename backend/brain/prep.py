"""Brain V3 P12: prep packs — prepare the work before an event, exam or deadline (silent preparation).

    targets(now)           upcoming timed events within lead_hours that involve people / projects /
                           prep words, plus important tasks due within 24 h
    gather(target)         deterministic: people + what Mayday knows about them, open promises both
                           ways, waiting-on items, recent decisions/episodes, related research answers,
                           project state, related emails (read-only, optional), traffic note
    build(target, llm)     ONE worker call -> briefing / what changed / to raise / action items;
                           every line must cite [n] sources that exist (others are dropped)
    run(now, llm)          builds at most max_per_day packs, each target once; submits a silent_prep
                           candidate (logged + audited) and, near the event, a "your prep is ready" nudge
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from backend.brain.friction import PREP_WORDS, _has_time, _keywords, _t
from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)

_SCHEMA = """CREATE TABLE IF NOT EXISTS prep_packs (
    id TEXT PRIMARY KEY, target_key TEXT UNIQUE NOT NULL, target_id TEXT, title TEXT NOT NULL,
    starts_at TEXT, content TEXT NOT NULL, sources TEXT NOT NULL, created_at TEXT NOT NULL,
    opened_at TEXT, announced_at TEXT)"""


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("prep", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "lead_hours": int(c.get("lead_hours", 18)),
            "show_before_min": int(c.get("show_before_min", 30)), "max_per_day": int(c.get("max_per_day", 3)),
            "use_gmail": bool(c.get("use_gmail", True))}


def _store():
    from backend.memory.knowledge_graph import get_graph
    store = get_graph()._store
    if store is not None:
        with store._lock:
            store._conn.execute(_SCHEMA)
    return store


# ------------------------------------------------------------------ targets
def _people_in(text: str) -> list[dict]:
    out = []
    try:
        from backend.core.planner_store import get_planner
        for p in get_planner().list_people():
            first = (p.get("name") or "").split()[0] if p.get("name") else ""
            if first and len(first) >= 3 and re.search(r"\b" + re.escape(first) + r"\b", text, re.I):
                out.append({"name": p["name"], "email": p.get("email"), "planner_id": p["id"]})
    except Exception:
        pass
    try:
        from backend.memory.knowledge_graph import get_graph
        kg = get_graph()
        for n in kg.get_nodes_by_type("person"):
            name = (n.get("properties") or {}).get("name") or n["label"].split(":", 1)[-1]
            first = name.split()[0] if name else ""
            if len(first) >= 3 and re.search(r"\b" + re.escape(first) + r"\b", text, re.I) \
                    and not any(o["name"].lower() == name.lower() for o in out):
                out.append({"name": name, "node_id": n["id"]})
    except Exception:
        pass
    return out


def targets(now: datetime) -> list[dict]:
    from backend.core.planner_store import get_planner
    p = get_planner()
    hi = now + timedelta(hours=_cfg()["lead_hours"])
    out = []
    for i in p.all_items():
        if i.get("status") != "open":
            continue
        text = f"{i.get('title', '')} {i.get('notes', '')}"
        if i["kind"] == "event":
            for inst in p.expand(i, now, hi):
                if not _has_time(inst.get("start_at")):
                    continue
                people = _people_in(text)
                if people or PREP_WORDS.search(text):
                    out.append({"key": f"{i['id']}:{inst['start_at']}", "id": i["id"], "kind": "event",
                                "title": i.get("title", ""), "notes": i.get("notes", ""),
                                "starts_at": inst["start_at"], "people": people})
        elif i["kind"] == "task" and int(i.get("priority") or 4) <= 2:
            due = _t(i.get("due_at"))
            if due and now <= due <= now + timedelta(hours=24):
                out.append({"key": f"{i['id']}:{i.get('due_at')}", "id": i["id"], "kind": "deadline",
                            "title": i.get("title", ""), "notes": i.get("notes", ""),
                            "starts_at": i.get("due_at"), "people": _people_in(text)})
    return out


# ------------------------------------------------------------------ gather (deterministic)
def gather(target: dict) -> list[dict]:
    """Numbered sources: [{"n", "kind", "ref", "text"}] — only facts that exist."""
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    store = kg._store
    src: list[dict] = []

    def add(kind: str, ref: str, text: str) -> None:
        text = redact(" ".join(str(text).split()))[:300]
        if text and not any(s["text"] == text for s in src):
            src.append({"n": len(src) + 1, "kind": kind, "ref": ref, "text": text})

    add("planner", f"p:{target['id']}", f"{target['kind']}: {target['title']} at {target['starts_at']}"
        + (f" — notes: {target['notes']}" if target.get("notes") else ""))
    words = _keywords(target["title"] + " " + (target.get("notes") or ""))
    names = [p["name"] for p in target.get("people", [])]
    # people: what Mayday knows + promises both ways
    for person in target.get("people", []):
        nid = person.get("node_id")
        if not nid:
            n = kg.get_node_by_label(f"person:{person['name']}") or kg.get_node_by_label(person["name"])
            nid = n["id"] if n else None
        if nid:
            from backend.brain.context import _facts_for
            for f in _facts_for(kg, nid, limit=5):
                add("memory", nid, f.strip("- ").strip())
        try:
            from backend.core.planner_store import get_planner
            pl = get_planner()
            if person.get("planner_id"):
                led = pl.person_ledger(person["planner_id"])
                for it in led.get("they_owe", [])[:3]:
                    add("planner", f"p:{it['id']}", f"{person['name']} owes you: {it['title']}")
                for it in led.get("i_owe", [])[:3]:
                    add("planner", f"p:{it['id']}", f"You owe {person['name']}: {it['title']}")
        except Exception:
            pass
    if store is not None:
        for c in store.list_commitments("open", limit=30):
            if any(nm.split()[0].lower() in c["text"].lower() for nm in names) or (words & _keywords(c["text"])):
                add("commitment", c["id"], f"You promised: {c['text']}" + (f" (by {c['due']})" if c.get("due") else ""))
        for e in store.list_episodes("decision", limit=100) + store.list_episodes("day", limit=14):
            text = e["summary"] + " " + (e.get("data") or "")
            if (words and len(words & _keywords(text)) >= 2) or any(nm.split()[0].lower() in text.lower()
                                                                     for nm in names):
                label = "Past decision" if e["kind"] == "decision" else f"On {e['day']}"
                add("episode", e["id"], f"{label}: {e['summary']}")
    # project state
    try:
        from backend.core.project_store import get_project_store
        ps = get_project_store()
        for proj in ps.list_projects()[:50]:
            pname = str(proj.get("name", ""))
            if pname and pname.lower() in (target["title"] + " " + (target.get("notes") or "")).lower():
                tasks = [t for t in (proj.get("tasks") or []) if t.get("status") in ("pending", "in_progress", "blocked")]
                add("project", f"project:{pname}", f"Project {pname}: {len(tasks)} open tasks"
                    + (f"; blocked: {', '.join(t.get('title', '') for t in tasks if t.get('status') == 'blocked')[:120]}"
                       if any(t.get('status') == 'blocked' for t in tasks) else ""))
    except Exception:
        pass
    # research answers on the topic
    try:
        from backend.core.research_index import get_research_index
        for hit in get_research_index().search(" ".join(sorted(words))[:80], limit=3):
            add("research", f"research:{hit.get('topic')}", f"Research ({hit.get('topic')}): {hit.get('snippet', '')}")
    except Exception:
        pass
    # related emails (read-only metadata)
    if _cfg()["use_gmail"]:
        try:
            from backend.core.gmail_service import get_message, is_authenticated, list_messages
            if is_authenticated("agent"):
                q = " OR ".join(f'"{p.get("email") or p["name"]}"' for p in target.get("people", [])[:3])
                if q:
                    ids = (list_messages(query=f"({q}) newer_than:14d", max_results=3) or {}).get("messages") or []
                    for m in ids[:3]:
                        meta = get_message(m["id"], fmt="metadata", metadata_headers=["Subject"])
                        subj = next((h.get("value") for h in (meta.get("payload") or {}).get("headers", [])
                                     if h.get("name") == "Subject"), "")
                        add("email", f"gmail:{m['id']}", f"Email: {subj} — {meta.get('snippet', '')}")
        except Exception as e:
            logger.debug("prep gmail: %s", e)
    return src


# ------------------------------------------------------------------ build (one model call)
_PROMPT = """Prepare a short prep pack for the user's upcoming {kind}: "{title}" at {starts}.
Use ONLY the numbered sources. Every line must end with the source numbers it relies on, like [2] or [1][4].

Return JSON only:
{{"briefing": ["<up to 5 lines: what this is about and the key context>"],
  "changed": ["<what changed recently, if anything>"],
  "raise": ["<open items or promises to bring up>"],
  "action_items": ["<concrete next steps for the user, short imperative>"]}}
Empty lists are fine. No line without a [n] citation.

Sources:
{sources}
JSON:"""
_CITE = re.compile(r"\[(\d+)\]")


def _keep_cited(lines, valid: set[int]) -> list[str]:
    out = []
    for ln in lines or []:
        ln = str(ln).strip()
        cites = {int(x) for x in _CITE.findall(ln)}
        if cites and cites <= valid:
            out.append(redact(ln)[:300])
    return out


def build(target: dict, llm, sources: list[dict]) -> dict | None:
    if len(sources) < 2:
        return None
    prompt = _PROMPT.format(kind=target["kind"], title=target["title"], starts=target["starts_at"],
                            sources="\n".join(f"[{s['n']}] {s['text']}" for s in sources))
    resp = llm.chat(messages=[{"role": "user", "content": prompt}], stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    valid = {s["n"] for s in sources}
    pack = {k: _keep_cited(data.get(k), valid) for k in ("briefing", "changed", "raise", "action_items")}
    if not pack["briefing"]:
        return None
    return pack


# ------------------------------------------------------------------ run
def _built_today(store) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return store._rows("SELECT COUNT(*) n FROM prep_packs WHERE created_at >= ?", (since,))[0]["n"]


def run(now: datetime | None = None, llm=None) -> list[dict]:
    """Build due prep packs (silently), and announce ready packs shortly before their event."""
    from backend.brain.proactive import submit
    cfg = _cfg()
    store = _store()
    if not cfg["enabled"] or store is None:
        return []
    now = now or datetime.now()
    results = []
    for t in targets(now):
        if store._rows("SELECT 1 FROM prep_packs WHERE target_key=?", (t["key"],)):
            continue
        if _built_today(store) >= cfg["max_per_day"]:
            break
        sources = gather(t)
        if llm is None:
            from backend.assistant.llm_client import get_worker_client
            llm = get_worker_client()
        try:
            pack = build(t, llm, sources)
        except Exception as e:
            logger.warning("prep pack failed for %s: %s", t["title"], e)
            continue
        if not pack:
            continue
        pid = "pp_" + uuid.uuid4().hex[:10]
        store._insert("prep_packs", {"id": pid, "target_key": t["key"], "target_id": t["id"], "title": t["title"],
                                     "starts_at": t["starts_at"], "content": json.dumps(pack, ensure_ascii=False),
                                     "sources": json.dumps(sources, ensure_ascii=False),
                                     "created_at": datetime.now(timezone.utc).isoformat(), "opened_at": None,
                                     "announced_at": None})
        res = submit({"type": "prep_pack", "source": "prep.run", "dedupe": t["key"],
                      "text": f"Prepared a prep pack for \"{t['title']}\"",
                      "why": f"\"{t['title']}\" starts at {t['starts_at'][11:16] or t['starts_at']} and I found "
                             f"{len(sources)} related notes.",
                      "evidence": [f"p:{t['id']}"], "value": 0.7, "urgency": "low", "confidence": 0.9,
                      "mode": "silent_prep", "action": {"kind": "prepare_note", "payload": {"title": t["title"],
                                                                                            "pack_id": pid}}})
        results.append({"pack_id": pid, **res})
    results += announce(now)
    return results


def announce(now: datetime) -> list[dict]:
    """Shortly before the event (or for deadlines, in the morning), nudge that the pack is ready."""
    from backend.brain.proactive import submit
    store = _store()
    out = []
    for r in store._rows("SELECT * FROM prep_packs WHERE announced_at IS NULL AND opened_at IS NULL"):
        start = _t(r["starts_at"])
        if not start:
            continue
        minutes = (start - now).total_seconds() / 60
        if not -15 <= minutes <= max(_cfg()["show_before_min"], 120):
            continue
        res = submit({"type": "prep_ready", "source": "prep.announce", "dedupe": r["id"],
                      "text": f"Your prep for \"{r['title']}\" is ready (Brain → Thoughts).",
                      "why": f"\"{r['title']}\" starts at {r['starts_at'][11:16]} and the pack has "
                             f"{len(json.loads(r['content'])['briefing'])} key points.",
                      "evidence": [f"p:{r['target_id']}"], "value": 0.75,
                      "urgency": "urgent" if minutes <= _cfg()["show_before_min"] else "timely",
                      "confidence": 0.9, "mode": "nudge", "expires_in_min": max(30, int(minutes) + 30)})
        with store._lock:
            store._conn.execute("UPDATE prep_packs SET announced_at=? WHERE id=?",
                                (datetime.now(timezone.utc).isoformat(), r["id"]))
        out.append({"announced": r["id"], **res})
    return out


def list_packs(limit: int = 20) -> list[dict]:
    store = _store()
    rows = store._rows("SELECT * FROM prep_packs ORDER BY starts_at DESC LIMIT ?", (limit,))
    for r in rows:
        r["content"] = json.loads(r["content"])
        r["sources"] = json.loads(r["sources"])
    return rows


def open_pack(pid: str) -> dict | None:
    store = _store()
    rows = store._rows("SELECT * FROM prep_packs WHERE id=?", (pid,))
    if not rows:
        return None
    if not rows[0]["opened_at"]:
        with store._lock:
            store._conn.execute("UPDATE prep_packs SET opened_at=? WHERE id=?",
                                (datetime.now(timezone.utc).isoformat(), pid))
    r = rows[0]
    r["content"] = json.loads(r["content"])
    r["sources"] = json.loads(r["sources"])
    return r
