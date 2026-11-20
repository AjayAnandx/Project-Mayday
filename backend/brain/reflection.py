"""Brain V2 P6: reflection. Keeps the brain clean and builds the user model offline.

    nightly(now, llm)  ~03:00, once a day:
        1. contradictions: several active values for a single-valued predicate -> keep the
           newest, supersede the rest (and unlink them in the graph)
        2. expire pending items nobody reviewed for `pending_days` (default 14)
        3. merge duplicate entities (same rules as cleanup_graph, applied to the live graph)
        4. episode for yesterday: ONE model call summarises the day's conversations into
           summary / decisions / open loops / mood (episodes table)
    weekly(now, llm)   Sunday, once a week: ONE model call writes a short persona of the user
                       from active facts + the last 7 episodes; every line cites its evidence
                       ids; stored in profile_versions and shown in the always-on profile
    maybe_reflect(now) what the scheduler calls every minute (cheap when nothing is due)

Model calls go to the worker model. If a call fails, the deterministic steps still run
and the step is retried the next night.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from backend.core.config import load_config

logger = logging.getLogger(__name__)


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("reflection", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "nightly_at": str(c.get("nightly_at", "03:00")),
            "weekly_day": int(c.get("weekly_day", 6)),          # 0=Mon … 6=Sun
            "pending_days": int(c.get("pending_days", 14)),
            "max_day_chars": int(c.get("max_day_chars", 12000))}


def _kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


# ------------------------------------------------------------------ deterministic steps
def resolve_contradictions(kg) -> int:
    from backend.brain.capture import SINGLE_VALUED, _unmirror_fact
    store = kg._store
    rows = store._rows("SELECT subject_id, predicate FROM facts WHERE status='active' "
                       "GROUP BY subject_id, predicate HAVING COUNT(*) > 1")
    fixed = 0
    for r in rows:
        if r["predicate"] not in SINGLE_VALUED:
            continue
        facts = store.find_facts(r["subject_id"], r["predicate"])     # oldest first
        newest = facts[-1]
        for old in facts[:-1]:
            store.update_fact(old["id"], status="superseded", valid_to=newest["created_at"])
            if not newest.get("supersedes"):
                newest = store.update_fact(newest["id"], supersedes=old["id"])
            _unmirror_fact(kg, old)
            fixed += 1
    return fixed


def expire_pending(kg, days: int, now: datetime) -> int:
    cutoff = (now - timedelta(days=days)).isoformat()
    store = kg._store
    with store._lock:
        n1 = store._conn.execute("UPDATE facts SET status='expired' WHERE status='pending' AND created_at < ?",
                                 (cutoff,)).rowcount
        n2 = store._conn.execute("UPDATE commitments SET status='expired' WHERE status='pending' "
                                 "AND created_at < ?", (cutoff,)).rowcount
    return (n1 or 0) + (n2 or 0)


def merge_duplicates(kg) -> int:
    """Apply the cleanup_graph merge rules to the live in-memory graph (projects untouched)."""
    from backend.memory.cleanup_graph import plan_cleanup
    with kg._lock:
        res = plan_cleanup({"nodes": list(kg._nodes.values()), "edges": kg._edges}, set())
        merged = res["report"].get("2 duplicate merged", {}).get("count", 0)
        if res["before"] == res["after"]:
            return 0
        kg._nodes = {n["id"]: n for n in res["graph"]["nodes"]}
        kg._edges = res["graph"]["edges"]
        kg._rebuild_indexes()
        kg._save()
    return merged


# ------------------------------------------------------------------ episodes
_EPISODE_PROMPT = """Summarise the user's day from their conversations with their assistant.
Date: {day}. Write about the USER (second person is fine), not about the assistant.

Return JSON only:
{{"summary": "<3-5 sentences: what the user did, worked on, talked about>",
  "decisions": ["<decisions the user made>"],
  "open_loops": ["<things left unfinished or promised, with who/when if stated>"],
  "mood": "<one or two words, or empty if unclear>",
  "sessions": [{{"ref": "<conversation ref like c1>", "goal": "<what the user tried to get done>",
                "outcome": "done|partial|blocked|abandoned|unclear", "blockers": "<short or empty>"}}],
  "decision_episodes": [{{"situation": "<the problem or choice, in general terms>",
                         "options": ["<options that were considered>"], "chosen": "<what the user chose>",
                         "reason": "<why, if stated>", "outcome": "<how it turned out, if known, else empty>",
                         "refs": ["<conversation refs>"]}}]}}
Only include what the conversations support. Empty lists are fine. A decision episode is a real
choice the user made between alternatives (e.g. cutting scope vs working late), not routine actions.

Conversations:
{text}
JSON:"""


def day_transcript(day: str, max_chars: int) -> tuple[str, list[str]]:
    from backend.core.data_store import get_store
    ds = get_store()
    parts, ids = [], []
    skip = (load_config().get("brain", {}) or {}).get("reflection", {}).get("skip_pattern", r"\bZZTEST|\bZZTester")
    skip_re = re.compile(skip, re.I) if skip else None
    for c in ds.list_conversations(date=day):
        conv = ds.get_conversation(c["id"])
        if not conv:
            continue
        if skip_re and any(skip_re.search(str(m.get("content") or "")) for m in conv.get("messages", [])
                           if m.get("role") == "user"):
            continue    # scripted test traffic is not part of the user's day
        lines = []
        for m in conv.get("messages", []):
            role, content = m.get("role"), str(m.get("content") or "").strip()
            if role == "user" and content:
                lines.append(f"User: {content[:600]}")
            elif role == "assistant" and content:
                lines.append(f"Assistant: {content[:200]}")
        if lines:
            ids.append(conv["id"])
            parts.append(f"## [c{len(ids)}] {conv.get('title', '')}\n" + "\n".join(lines))
    text = "\n\n".join(parts)
    return text[:max_chars], ids


def _json(content: str) -> dict | None:
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _ask(llm, prompt: str) -> dict | None:
    resp = llm.chat(messages=[{"role": "user", "content": prompt}], stream=False, tools=[], temperature=0)
    content, _ = llm.extract_response(resp)
    return _json(content or "")


def write_episode(kg, llm, day: str) -> dict | None:
    store = kg._store
    if store._rows("SELECT id FROM episodes WHERE day = ? AND kind = 'day'", (day,)):
        return None                                   # already done
    text, conv_ids = day_transcript(day, _cfg()["max_day_chars"])
    if not text.strip():
        return None
    data = _ask(llm, _EPISODE_PROMPT.format(day=day, text=text))
    if not data or not data.get("summary"):
        raise RuntimeError("episode summary failed")
    import uuid
    from backend.brain.store import _now
    from backend.memory.sensitivity import redact
    row = {"id": "e_" + uuid.uuid4().hex[:12], "conversation_id": None, "day": day,
           "summary": redact(str(data["summary"]))[:2000],
           "decisions": json.dumps([redact(str(x)) for x in data.get("decisions") or []][:10]),
           "open_loops": json.dumps([redact(str(x)) for x in data.get("open_loops") or []][:10]),
           "mood": str(data.get("mood") or "")[:40], "created_at": _now()}
    store._insert("episodes", row)
    row["source_conversations"] = conv_ids
    # Brain V3 P9: session and decision episodes from the same call (no extra model cost)
    ref = {f"c{i + 1}": cid for i, cid in enumerate(conv_ids)}
    for sess in (data.get("sessions") or [])[:20]:
        if not isinstance(sess, dict) or not sess.get("goal"):
            continue
        store.add_episode(kind="session", day=day, conversation_id=ref.get(str(sess.get("ref"))),
                          summary=redact(str(sess["goal"]))[:400],
                          outcome=str(sess.get("outcome") or "unclear")[:20],
                          data={"blockers": redact(str(sess.get("blockers") or ""))[:200]})
    for dec in (data.get("decision_episodes") or [])[:10]:
        if not isinstance(dec, dict) or not dec.get("situation") or not dec.get("chosen"):
            continue
        store.add_episode(kind="decision", day=day, summary=redact(str(dec["situation"]))[:300],
                          outcome=redact(str(dec.get("outcome") or ""))[:300] or None,
                          data={"options": [redact(str(o))[:120] for o in (dec.get("options") or [])][:5],
                                "chosen": redact(str(dec["chosen"]))[:200],
                                "reason": redact(str(dec.get("reason") or ""))[:200],
                                "conversations": [ref[r] for r in (dec.get("refs") or []) if r in ref]})
    return row


_ROLLUP_PROMPT = """Below are {n} daily summaries of one user's {period}. Summarise the {period} for their
personal assistant. Return JSON only:
{{"summary": "<4-6 sentences: main themes, progress, what took time>",
  "decisions": ["<important decisions>"], "open_loops": ["<still open at the end>"],
  "mood": "<overall, one or two words>"}}
Use only what the summaries say.

{text}
JSON:"""


def rollup(kg, llm, now: datetime) -> list[str]:
    """Week (previous ISO week) and month (previous month) summaries of the day episodes.
    One model call each, at most once per period; skipped when there are < 2 day episodes."""
    store = kg._store
    done = []
    today = now.date()
    prev_week_start = today - timedelta(days=today.weekday() + 7)
    prev_week_end = prev_week_start + timedelta(days=6)
    first_this_month = today.replace(day=1)
    prev_month_end = first_this_month - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    for kind, start, end, label in (
            ("week", prev_week_start, prev_week_end, f"week of {prev_week_start.isoformat()}"),
            ("month", prev_month_start, prev_month_end, prev_month_start.strftime("%B %Y"))):
        day = start.isoformat()
        if store._rows("SELECT id FROM episodes WHERE kind=? AND day=?", (kind, day)):
            continue
        days = store._rows("SELECT day, summary, open_loops, mood FROM episodes WHERE kind='day' "
                           "AND day BETWEEN ? AND ? ORDER BY day", (start.isoformat(), end.isoformat()))
        if len(days) < 2:
            continue
        text = "\n".join(f"{d['day']} ({d['mood']}): {d['summary']} Open: "
                         f"{', '.join(json.loads(d['open_loops'] or '[]'))}" for d in days)[:12000]
        data = _ask(llm, _ROLLUP_PROMPT.format(n=len(days), period=label, text=text))
        if not data or not data.get("summary"):
            raise RuntimeError(f"{kind} roll-up failed")
        from backend.memory.sensitivity import redact
        store.add_episode(kind=kind, day=day, summary=redact(str(data["summary"]))[:3000],
                          decisions=[redact(str(x)) for x in data.get("decisions") or []][:10],
                          open_loops=[redact(str(x)) for x in data.get("open_loops") or []][:10],
                          mood=str(data.get("mood") or "")[:40], data={"period": label, "days": len(days)})
        done.append(kind)
    return done


def similar_decisions(store, text: str, limit: int = 2) -> list[dict]:
    """Past decision episodes whose situation shares words with `text` (for framing options)."""
    words = {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())}
    if not words:
        return []
    scored = []
    for e in store.list_episodes("decision", limit=200):
        sit = set(re.findall(r"[a-z]{4,}", (e["summary"] + " " + (e.get("data") or "")).lower()))
        overlap = len(words & sit)
        if overlap >= 2:
            scored.append((overlap, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def recent_episodes(store, days: int = 7) -> list[dict]:
    return store._rows("SELECT * FROM episodes WHERE kind = 'day' ORDER BY day DESC LIMIT ?",
                       (days,))


# ------------------------------------------------------------------ weekly persona
_PERSONA_PROMPT = """You are building a short, accurate picture of ONE user for their personal
assistant, from evidence only. Evidence items have ids in brackets.

Write JSON only: {{"lines": [{{"text": "<one sentence about the user>", "evidence": ["<ids>"]}}]}}
Cover, where the evidence supports it: who they are and what they do; current goals and focus;
routines; how they like to be helped (style, format, timing); people who matter; what stresses
or annoys them. 4-10 lines. Every line MUST cite at least one id from the evidence. No guesses.

Evidence:
{evidence}
JSON:"""


def build_persona(kg, llm) -> dict | None:
    from backend.memory.sensitivity import is_sensitive
    store = kg._store
    ev, valid = [], set()
    for f in store.list_facts("active", limit=200):
        if f["sensitivity"] != "normal" or is_sensitive(f["predicate"], f["object"]):
            continue
        subj = kg.get_node(f["subject_id"]) if f["subject_id"] else None
        who = "user" if not subj or subj["type"] == "user" else subj["label"].split(":", 1)[-1]
        ev.append(f"[{f['id']}] {who} {f['predicate'].replace('_', ' ')} {f['object']}")
        valid.add(f["id"])
    for e in recent_episodes(store, 7):
        ev.append(f"[{e['id']}] {e['day']}: {e['summary']} Open: {', '.join(json.loads(e['open_loops'] or '[]'))}")
        valid.add(e["id"])
    if len(ev) < 3:
        return None
    data = _ask(llm, _PERSONA_PROMPT.format(evidence="\n".join(ev)[:14000]))
    lines = []
    for ln in (data or {}).get("lines") or []:
        cites = [c for c in (ln.get("evidence") or []) if c in valid]
        text = str(ln.get("text") or "").strip()
        if text and cites and not is_sensitive("", text):
            lines.append({"text": text, "evidence": cites})
    if not lines:
        raise RuntimeError("persona produced no supported lines")
    from backend.brain.store import _now
    profile = json.dumps({"lines": lines}, ensure_ascii=False)
    with store._lock:
        store._conn.execute("INSERT INTO profile_versions(profile, reason, created_at) VALUES (?,?,?)",
                            (profile, "weekly persona pass", _now()))
    return {"lines": lines}


def latest_persona(store) -> list[dict]:
    rows = store._rows("SELECT profile FROM profile_versions ORDER BY version DESC LIMIT 1")
    if not rows:
        return []
    try:
        return json.loads(rows[0]["profile"]).get("lines", [])
    except (json.JSONDecodeError, AttributeError):
        return []


# ------------------------------------------------------------------ orchestration
def nightly(now: datetime, llm=None) -> dict:
    kg = _kg()
    if kg._store is None:
        return {"skipped": "needs sqlite"}
    out = {"contradictions": resolve_contradictions(kg),
           "expired": expire_pending(kg, _cfg()["pending_days"], now),
           "merged": merge_duplicates(kg)}
    try:  # Brain V3 P8: raw signals -> hourly stats after the retention window
        from backend.brain.signals import get_bus
        out["signals"] = get_bus().prune()
    except Exception as e:
        logger.warning("signal prune failed: %s", e)
    # Episodes for the last 3 days (oldest first): backfills a night whose call failed.
    out["episodes"] = []
    try:
        if llm is None:
            from backend.assistant.llm_client import get_worker_client
            llm = get_worker_client()
        for back in (3, 2, 1):
            day = (now.date() - timedelta(days=back)).isoformat()
            if write_episode(kg, llm, day):
                out["episodes"].append(day)
    except Exception as e:
        logger.warning("brain nightly episode failed: %s", e)
        out["episode_error"] = str(e)[:200]
    # Brain V3 P9: week/month roll-ups, habit mining, decay (each independent)
    try:
        if llm is not None:
            out["rollups"] = rollup(kg, llm, now)
    except Exception as e:
        logger.warning("brain roll-up failed: %s", e)
        out["rollup_error"] = str(e)[:200]
    # Brain V3 P14: preference drift, routine induction, curiosity (each independent)
    for name, fn in (("drift", lambda: __import__("backend.brain.drift", fromlist=["run"]).run()),
                     ("routines", lambda: __import__("backend.brain.routines", fromlist=["run"]).run(now, llm)),
                     ("curiosity", lambda: __import__("backend.brain.curiosity", fromlist=["run_nightly"])
                      .run_nightly(now, llm))):
        try:
            out[name] = fn()
        except Exception as e:
            logger.warning("nightly %s failed: %s", name, e)
            out[f"{name}_error"] = str(e)[:200]
    try:
        from backend.brain.lessons import maintain as lessons_maintain
        out["lessons"] = lessons_maintain()
    except Exception as e:
        logger.warning("lesson maintenance failed: %s", e)
    try:
        from backend.brain.habits import mine
        out["habits"] = mine(kg, now)
    except Exception as e:
        logger.warning("habit mining failed: %s", e)
    try:
        from backend.brain.decay import run as decay_run
        out["decay"] = decay_run(kg)
    except Exception as e:
        logger.warning("decay failed: %s", e)
    return out


def weekly(now: datetime, llm=None) -> dict:
    kg = _kg()
    if kg._store is None:
        return {"skipped": "needs sqlite"}
    if llm is None:
        from backend.assistant.llm_client import get_worker_client
        llm = get_worker_client()
    p = build_persona(kg, llm)
    return {"persona_lines": len(p["lines"]) if p else 0}


def maybe_reflect(now: datetime | None = None, llm=None) -> list[str]:
    """Called every scheduler tick; runs each job at most once per day/week."""
    cfg = _cfg()
    if not cfg["enabled"]:
        return []
    kg = _kg()
    store = kg._store
    if store is None:
        return []
    now = now or datetime.now()
    try:  # Brain V3 P10: expired suggestions with no reaction -> "ignored" (every tick, cheap)
        from backend.brain.ledger import expire_suggestions
        expire_suggestions()
    except Exception as e:
        logger.debug("expire suggestions: %s", e)
    try:  # Brain V3 P11: generators every ~30 min (internally throttled)
        from backend.brain.generators import run_all
        run_all()
    except Exception as e:
        logger.debug("generators: %s", e)
    hh, mm = (int(x) for x in cfg["nightly_at"].split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return []
    ran = []
    today = now.date().isoformat()
    if store.get_meta("reflect_nightly_date") != today:
        res = nightly(now, llm)
        store._set_meta("reflect_nightly_date", today)
        store._set_meta("reflect_nightly_result", json.dumps(res))
        logger.info("brain nightly reflection: %s", res)
        ran.append("nightly")
    week = now.strftime("%G-W%V")
    last_try = store.get_meta("reflect_weekly_attempt")
    recently_tried = bool(last_try) and now - datetime.fromisoformat(last_try) < timedelta(hours=1)
    weekly_due = now.weekday() == cfg["weekly_day"] and store.get_meta("reflect_weekly_week") != week
    if weekly_due and not recently_tried:
        store._set_meta("reflect_weekly_attempt", now.isoformat())
        try:
            res = weekly(now, llm)
            store._set_meta("reflect_weekly_week", week)
            logger.info("brain weekly persona: %s", res)
            ran.append("weekly")
        except Exception as e:
            logger.warning("brain weekly persona failed, retrying in an hour: %s", e)
    return ran


# ------------------------------------------------------------------ proactive
def open_loops(store, days: int = 3) -> list[str]:
    """Open loops for the morning digest: recent episode loops + promises not in the Planner."""
    out: list[str] = []
    for e in recent_episodes(store, days):
        for loop in json.loads(e["open_loops"] or "[]"):
            if loop not in out:
                out.append(loop)
    for c in store.list_commitments("open", limit=10):
        if not c.get("planner_item_id") and c["text"] not in out:
            out.append(c["text"] + (f" (by {c['due']})" if c.get("due") else ""))
    return out[:6]
