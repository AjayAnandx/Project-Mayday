"""Autopilot for spoken/typed research requests.

route → one run (single category) or a *group* of runs (one per category) → when the last run
finishes, ONE completion announcement with a spoken-length summary. Also remembers the latest
research so follow-ups ("what did you find?") need no topic, and keeps announcements nobody
heard (no live voice session) for the next voice session.

State lives in research_state.json beside research.json (small, rewritten atomically).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from backend.core import research_router

logger = logging.getLogger(__name__)
_lock = threading.RLock()
MAX_PENDING = 10


# ── state ───────────────────────────────────────────────────────────────────

def _state_path() -> Path:
    from backend.core.research_store import get_research_store
    return Path(get_research_store()._path).with_name("research_state.json")


def _load() -> dict:
    p = _state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("groups", {})
    data.setdefault("last", None)
    data.setdefault("pending", [])
    return data


def _save(data: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def latest() -> dict | None:
    """{'kind': 'run'|'group', 'topics': [...], 'group_id'?, 'request', 'at'} of the newest research."""
    with _lock:
        return _load()["last"]


def latest_topic() -> str:
    last = latest()
    return (last or {}).get("topics", [""])[0] if last else ""


def group(group_id: str) -> dict | None:
    with _lock:
        return _load()["groups"].get(group_id)


def take_pending() -> list[dict]:
    """Announcements nobody heard yet; cleared once taken."""
    with _lock:
        data = _load()
        items, data["pending"] = data["pending"], []
        if items:
            _save(data)
        return items


def add_pending(item: dict) -> None:
    with _lock:
        data = _load()
        data["pending"] = (data["pending"] + [item])[-MAX_PENDING:]
        _save(data)


# ── launch ──────────────────────────────────────────────────────────────────

def _split_budget(budget: dict, n: int) -> dict:
    """Parallel runs: each gets the full time, an equal share of sources and money."""
    if n <= 1:
        return dict(budget)
    b = dict(budget)
    if b.get("max_sources"):
        b["max_sources"] = max(8, int(b["max_sources"]) // n)
    if b.get("max_cost_usd"):
        b["max_cost_usd"] = round(float(b["max_cost_usd"]) / n, 3)
    return b


def launch(user_text: str, topic: str = "", model_type: str | None = None, budget: dict | None = None,
           questions: list[str] | None = None, options: dict | None = None, start=None) -> dict:
    """Route and start. Returns {'explanation', 'runs': [{topic, run_id, category, field}], 'group_id'?,
    'errors': [...]}. `start` defaults to research_flow.start_research_run (injectable for tests)."""
    if start is None:
        from backend.core.research_flow import start_research_run as start
    plan = research_router.route(user_text or topic, topic, model_type)
    gid = f"grp_{uuid.uuid4().hex[:10]}" if plan.multi else ""
    seg_budget = _split_budget(budget or {}, len(plan.segments))
    runs, errors = [], []
    for seg in plan.segments:
        opts = dict(options or {})
        if seg.category != "academic":
            for k in ("field", "hypotheses", "snowball"):
                opts.pop(k, None)
        elif seg.field and not opts.get("field"):
            opts["field"] = seg.field
        if gid:
            opts["group_id"] = gid
        res = start(seg.topic, request=seg.request if plan.multi else (user_text or seg.request),
                    questions=None if plan.multi else questions, research_type=seg.category,
                    budget=dict(seg_budget), options=opts)
        if "error" in res:
            errors.append(f"{seg.topic}: {res['error']}")
            continue
        runs.append({"topic": seg.topic, "run_id": res.get("run_id") or res.get("id"),
                     "category": seg.category, "field": seg.field, "status": "running"})
    if runs:
        with _lock:
            data = _load()
            if gid:
                data["groups"][gid] = {"id": gid, "request": user_text, "runs": runs, "status": "running",
                                       "at": time.time()}
                # keep the state file small: last 30 groups
                for old in sorted(data["groups"], key=lambda g: data["groups"][g].get("at", 0))[:-30]:
                    data["groups"].pop(old, None)
            data["last"] = {"kind": "group" if gid else "run", "group_id": gid,
                            "topics": [r["topic"] for r in runs], "request": user_text, "at": time.time()}
            _save(data)
    return {"explanation": plan.explanation, "runs": runs, "group_id": gid, "errors": errors,
            "guessed": plan.guessed, "reasons": plan.reasons}


# ── completion ──────────────────────────────────────────────────────────────

def on_run_finished(topic: str, final: dict) -> dict | None:
    """Called by the flow launcher when a run ends. Returns the announcement it delivered (or None
    while other runs of the same group are still going)."""
    from backend.core import research_report as rr
    from backend.core.research_store import get_research_store
    store = get_research_store()
    gid = (final.get("brief") or {}).get("group_id", "")
    if not gid:
        record = store._get_by_topic(topic) or {"topic": topic, "claims": []}
        return announce(f"Research {final.get('status', 'done')}: {topic}", rr.voice_summary(record, final),
                        reports=[_report_path(final)], topics=[topic])
    with _lock:
        data = _load()
        grp = data["groups"].get(gid)
        if not grp:
            return None
        for r in grp["runs"]:
            if r["run_id"] == final.get("id"):
                r["status"] = final.get("status", "done")
        if any(r["status"] == "running" for r in grp["runs"]) or grp["status"] == "announced":
            _save(data)
            return None
        grp["status"] = "announced"
        _save(data)
    parts = []
    for r in grp["runs"]:
        record = store._get_by_topic(r["topic"])
        run = store.get_run(r["topic"], r["run_id"]) if record else None
        if record and run:
            parts.append((research_router.LABELS.get(r["category"], r["category"]), record, run))
    summary = rr.group_voice_summary(parts, grp.get("request", ""))
    base = grp["runs"][0]["topic"].split(" — ")[0]
    return announce(f"Research done: {base}", summary,
                    reports=[_report_path(run) for _, _, run in parts], topics=[r["topic"] for r in grp["runs"]])


def _report_path(run: dict) -> str:
    outs = run.get("outputs") or []
    md = [o for o in outs if str(o).endswith(".md")]
    return (md or outs or [""])[-1]


# Delivery hooks: (title, summary, reports) -> bool "someone heard it by voice".
# voice/router registers the realtime speaker; telegram is added by the announcer below.
_voice_hooks: list = []


def register_voice_hook(fn) -> None:
    if fn not in _voice_hooks:
        _voice_hooks.append(fn)


def announce(title: str, summary: str, reports: list[str] | None = None, topics: list[str] | None = None) -> dict:
    """Deliver a finished-research announcement: live voice if anyone is listening, the on-screen
    notification (which also speaks in classic voice mode), and Telegram when nobody heard it."""
    reports = [r for r in (reports or []) if r]
    item = {"title": title, "summary": summary, "reports": reports, "topics": topics or [], "at": time.time()}
    spoken = False
    for hook in list(_voice_hooks):
        try:
            spoken = bool(hook(title, summary)) or spoken
        except Exception as e:
            logger.warning("research voice hook failed: %s", e)
    try:
        from backend.core.scheduler import get_scheduler
        get_scheduler().fire_notification(title, summary, category="research", action_page="research",
                                          extra={"speak": "" if spoken else summary})
    except Exception as e:
        logger.debug("research notification failed: %s", e)
    if not spoken:
        sent = False
        try:
            from backend.telegram.push import push_research
            sent = push_research(title, summary, reports)
        except Exception as e:
            logger.info("telegram research push skipped: %s", e)
        item["telegram"] = sent
        add_pending(item)
    item["spoken"] = spoken
    return item
