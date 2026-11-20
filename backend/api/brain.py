"""Brain V2 "Learned" feed: what Mayday captured, with the evidence, and one-tap
confirm / wrong / edit. Corrections are the strongest signal the brain gets."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.memory.knowledge_graph import get_graph

router = APIRouter(prefix="/api/brain", tags=["brain"])


def _store():
    store = get_graph()._store
    if store is None:
        raise HTTPException(409, "Brain capture needs memory.backend: sqlite")
    return store


def _subject_label(kg, sid: str | None) -> str:
    n = kg.get_node(sid) if sid else None
    if not n:
        return "?"
    if n["type"] == "user":
        return "you"
    return n.get("properties", {}).get("name") or n["label"].split(":", 1)[-1]


@router.get("/learned")
def learned(status: str | None = None, limit: int = 50):
    """Recent captured items, newest first. status: active | pending | superseded | rejected."""
    kg = get_graph()
    store = _store()
    items = []
    for f in store.list_facts(status, limit=limit):
        items.append({"kind": "fact", "id": f["id"], "status": f["status"],
                      "subject": _subject_label(kg, f["subject_id"]), "predicate": f["predicate"],
                      "object": f["object"], "text": f"{_subject_label(kg, f['subject_id'])} "
                                                    f"{f['predicate'].replace('_', ' ')} {f['object']}",
                      "confidence": f["confidence"], "quote": f["quote"], "source_ref": f["source_ref"],
                      "sensitivity": f["sensitivity"], "supersedes": f["supersedes"],
                      "created_at": f["created_at"]})
    if status in (None, "pending", "open", "active"):
        cstatus = {"active": "open"}.get(status or "", status)
        for c in store.list_commitments(cstatus, limit=limit):
            items.append({"kind": "commitment", "id": c["id"], "status": c["status"], "text": c["text"],
                          "due": c["due"], "who": c["who"], "quote": c["quote"],
                          "planner_item_id": c["planner_item_id"], "source_ref": c["source_ref"],
                          "created_at": c["created_at"]})
    if status in (None, "active"):
        for i in store.list_ideas(limit=limit):
            items.append({"kind": "idea", "id": i["id"], "status": "active", "text": i["text"],
                          "quote": i["quote"], "source_ref": i["source_ref"], "created_at": i["created_at"]})
    # Brain V3 P10: lessons learned from mistakes (candidate = needs a look)
    lstatus = {"pending": ("candidate",), "active": ("active",), None: ("candidate", "active")}.get(status, ())
    if lstatus:
        marks = ",".join("?" for _ in lstatus)
        for le in store._rows(f"SELECT * FROM lessons WHERE status IN ({marks}) ORDER BY updated_at DESC "
                              "LIMIT ?", (*lstatus, limit)):
            items.append({"kind": "lesson", "id": le["id"],
                          "status": "pending" if le["status"] == "candidate" else "active",
                          "text": f"When {le['trigger'].removeprefix('when ').removeprefix('When ')}: {le['lesson']}",
                          "quote": "", "scope": le["scope"], "votes": le["votes"], "uses": le.get("uses", 0),
                          "created_at": le["created_at"]})
    items.sort(key=lambda x: x["created_at"], reverse=True)
    counts = {s: len(store.list_facts(s, limit=10000)) for s in ("active", "pending")}
    counts["pending"] += store._rows("SELECT COUNT(*) n FROM lessons WHERE status='candidate'")[0]["n"]
    counts["pending"] += len(store.list_commitments("pending", limit=10000))
    return {"items": items[:limit], "counts": counts}


def _feedback(action: str, kind: str, item_id: str, **extra) -> None:
    try:
        from backend.brain.signals import publish
        publish("suggestion_feedback", "backend", {"surface": "learned", "action": action, "kind": kind, **extra},
                subject=item_id)
    except Exception:
        pass


@router.post("/learned/{kind}/{item_id}/confirm")
def confirm(kind: str, item_id: str):
    from backend.brain import capture as cap
    _feedback("confirm", kind, item_id)
    kg = get_graph()
    store = _store()
    if kind == "fact":
        f = store.get_fact(item_id)
        if not f:
            raise HTTPException(404, "not found")
        if f["status"] != "active":
            # re-run the write path so supersede + graph mirror apply
            store.update_fact(item_id, status="rejected")
            op = {"kind": "fact", "predicate": f["predicate"], "object": f["object"],
                  "confidence": max(f["confidence"], 0.9), "quote": f["quote"],
                  "sensitivity": f["sensitivity"], "category": f.get("category")}
            subj = kg.get_node(f["subject_id"]) if f["subject_id"] else None
            op["subject"] = "user" if (not subj or subj["type"] == "user") else \
                (subj.get("properties", {}).get("name") or subj["label"].split(":", 1)[-1])
            new = cap.write_fact(kg, op, f["source_ref"], "active")
            store.update_fact(new["id"], confidence=1.0)
            return {"ok": True, "id": new["id"]}
        store.update_fact(item_id, confidence=1.0)
        return {"ok": True, "id": item_id}
    if kind == "lesson":
        from backend.brain.lessons import set_status, vote
        vote(item_id, 1)
        set_status(item_id, "active")
        return {"ok": True, "id": item_id}
    if kind == "commitment":
        c = store.get_commitment(item_id)
        if not c:
            raise HTTPException(404, "not found")
        if c["status"] == "pending":
            op = {"text": c["text"], "who": c["who"], "due": c["due"], "quote": c["quote"]}
            new = cap.write_commitment(kg, op, c["source_ref"], "open")
            store.update_commitment(item_id, status="rejected")
            return {"ok": True, "id": new["id"]}
        return {"ok": True, "id": item_id}
    raise HTTPException(400, "unknown kind")


@router.post("/learned/{kind}/{item_id}/reject")
def reject(kind: str, item_id: str):
    """'Wrong' / 'forget': removes it from memory (kept as rejected so it is not re-learned)."""
    _feedback("reject", kind, item_id)
    from backend.brain.capture import _unmirror_fact
    kg = get_graph()
    store = _store()
    if kind == "fact":
        f = store.get_fact(item_id)
        if not f:
            raise HTTPException(404, "not found")
        if f["status"] == "active":
            _unmirror_fact(kg, f)
        store.update_fact(item_id, status="rejected")
        # restore what it had superseded, if that is still the latest value
        if f.get("supersedes"):
            old = store.get_fact(f["supersedes"])
            if old and old["status"] == "superseded":
                store.update_fact(old["id"], status="active", valid_to=None)
                from backend.brain.capture import _mirror_fact
                _mirror_fact(kg, old["subject_id"], old["predicate"], old["object"], old["id"],
                             old.get("category") or "fact")
        return {"ok": True}
    if kind == "commitment":
        store.update_commitment(item_id, status="rejected")
        return {"ok": True}
    if kind == "lesson":
        from backend.brain.lessons import set_status
        set_status(item_id, "rejected")
        return {"ok": True}
    if kind == "idea":
        ideas = {i["id"]: i for i in store.list_ideas(limit=100000)}
        i = ideas.get(item_id)
        if i and i.get("linked_node_id"):
            kg.remove_node(i["linked_node_id"])
        store.delete_idea(item_id)
        return {"ok": True}
    raise HTTPException(400, "unknown kind")


class FactEdit(BaseModel):
    object: str


@router.put("/learned/fact/{item_id}")
def edit_fact(item_id: str, body: FactEdit):
    """Correct a fact's value: the old one is rejected, the corrected one is written as confirmed."""
    from backend.brain.capture import _mirror_fact, _unmirror_fact
    kg = get_graph()
    store = _store()
    f = store.get_fact(item_id)
    if not f:
        raise HTTPException(404, "not found")
    value = body.object.strip()
    if not value:
        raise HTTPException(400, "empty value")
    _feedback("edit", "fact", item_id, chars_before=len(f["object"]), chars_after=len(value))
    if f["status"] == "active":
        _unmirror_fact(kg, f)
    store.update_fact(item_id, status="rejected")
    new = store.add_fact(subject_id=f["subject_id"], predicate=f["predicate"], object=value,
                         confidence=1.0, quote=f["quote"], source_ref="user-edit",
                         sensitivity=f["sensitivity"], status="active", supersedes=item_id,
                         category=f.get("category"))
    _mirror_fact(kg, f["subject_id"], f["predicate"], value, new["id"], f.get("category") or "fact")
    return {"ok": True, "id": new["id"]}


@router.get("/tools/stats")
def tools_stats():
    """How tools are used in real turns (from the Brain V2 tool log)."""
    from backend.brain.tools import tool_stats
    _store()
    return tool_stats()


# ---------------------------------------------------------------- Brain V3 P8: sensory layer
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Header, Request

_REPO = Path(__file__).resolve().parents[2]
SENSOR_TOKEN_FILE = _REPO / "brain_sensor.token"
# kinds the outside world may send, by who may send them
_API_KINDS = {
    "desktop": {"desktop_window", "device_state"},                       # token required
    "ui": {"response_latency", "ui_visibility", "ui_dismiss", "ui_edit", "suggestion_feedback"},
}


def ensure_sensor_token() -> str:
    """The desktop sensor and the backend share a random token in a local, gitignored file."""
    try:
        tok = SENSOR_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(32)
    try:
        SENSOR_TOKEN_FILE.write_text(tok, encoding="utf-8")
    except OSError:
        pass
    return tok


def _wire_bus() -> None:
    from backend.brain.signals import get_bus
    from backend.brain.timing import get_timing
    from backend.brain.working import get_working
    get_bus().subscribe(get_timing().on_signal)
    get_bus().subscribe(get_working().on_signal)
    from backend.brain.feedback import get_parser
    get_bus().subscribe(get_parser().on_signal)

    def _on_transition(sig: dict) -> None:            # Brain V3 P11: natural break -> proactive pass
        if sig["kind"] == "transition":
            from backend.brain.generators import on_transition_async
            on_transition_async()
    _on_transition.__name__ = "proactive_on_transition"
    get_bus().subscribe(_on_transition)
    ensure_sensor_token()


_wire_bus()


class SignalIn(BaseModel):
    kind: str
    source: str | None = None
    value: dict = {}
    subject: str | None = None
    ts: str | None = None


def _accept_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now - timedelta(minutes=15) <= t <= now + timedelta(seconds=30):
            return t.isoformat()
    except ValueError:
        pass
    return None


@router.post("/signals")
def post_signal(body: SignalIn, x_brain_token: str | None = Header(default=None)):
    """Signals from the desktop sensor (token) and the web UI. Backend-only kinds are refused."""
    from backend.brain.signals import publish
    if body.kind in _API_KINDS["desktop"]:
        if not x_brain_token or not hmac.compare_digest(x_brain_token, ensure_sensor_token()):
            raise HTTPException(401, "bad sensor token")
        source = "desktop"
    elif body.kind in _API_KINDS["ui"]:
        source = "ui"
    else:
        raise HTTPException(403, f"kind '{body.kind}' cannot be posted")
    sig = publish(body.kind, source, body.value, subject=body.subject, ts=_accept_ts(body.ts))
    return {"accepted": sig is not None}


class LocationIn(BaseModel):
    lat: float
    lon: float


@router.post("/location")
def post_location(body: LocationIn):
    """Phone/browser location (opt-in). Converted to a place label here; coordinates are discarded."""
    from backend.brain.signals import _cfg as sensors_cfg, publish
    if not sensors_cfg()["location"]:
        raise HTTPException(403, "location sensing is off (brain.sensors.location)")
    from backend.brain.places import place_label
    label = place_label(body.lat, body.lon)
    publish("location_place", "location", {"place": label})
    return {"place": label}


@router.get("/sensors")
def sensors_status():
    """Which collectors are on and reporting, plus the live focus/idle state."""
    from backend.brain.signals import _cfg as sensors_cfg, get_bus
    from backend.brain.timing import get_timing
    cfg = sensors_cfg()
    return {"paused": cfg["pause"], "collectors": get_bus().collectors_status(),
            "timing": get_timing().snapshot()}


@router.get("/signals/recent")
def signals_recent(kind: str | None = None, minutes: int = 60, limit: int = 200):
    from backend.brain.signals import get_bus
    return {"signals": get_bus().recent(kind, minutes=min(minutes, 60 * 24 * 14), limit=min(limit, 1000))}


@router.get("/health")
def brain_health():
    """Brain V3 P9: memory tiers at a glance + what the last nightly run kept and forgot."""
    import json as _json
    from collections import Counter
    from backend.brain.working import get_working
    kg = get_graph()
    store = _store()
    q = lambda sql, args=(): store._rows(sql, args)  # noqa: E731
    habits = [{"id": n["id"], "text": (n.get("properties") or {}).get("text", n["label"]),
               "evidence": (n.get("properties") or {}).get("evidence_count"),
               "weeks": (n.get("properties") or {}).get("weeks")}
              for n in kg.get_nodes_by_type("habit")]
    last = store.get_meta("reflect_nightly_result")
    return {
        "working": get_working().snapshot(),
        "graph": dict(Counter(n["type"] for n in kg._nodes.values())),
        "facts": {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM facts GROUP BY status")},
        "facts_by_category": {(r["category"] or "fact"): r["n"]
                              for r in q("SELECT category, COUNT(*) n FROM facts WHERE status='active' "
                                         "GROUP BY category")},
        "episodes": {r["kind"]: r["n"] for r in q("SELECT kind, COUNT(*) n FROM episodes GROUP BY kind")},
        "habits": habits,
        "procedural": {t: q(f"SELECT COUNT(*) n FROM {t}")[0]["n"]
                       for t in ("lessons", "workflows", "prefs_calibrated")},
        "archive": q("SELECT COUNT(*) n FROM archive")[0]["n"],
        "last_nightly": _json.loads(last) if last else None,
        "last_nightly_date": store.get_meta("reflect_nightly_date"),
    }


@router.post("/archive/{item_id}/restore")
def restore_archived(item_id: str):
    """Undo a decay archive (within the archive window)."""
    from backend.brain.decay import restore
    if not restore(get_graph(), item_id):
        raise HTTPException(404, "not in archive")
    return {"ok": True}


# ---------------------------------------------------------------- Brain V3 P10: meta-cognition
@router.get("/why/{item_id}")
def why(item_id: str):
    """Answer 'why?' for a candidate / suggestion / action from the stored reason and evidence."""
    from backend.brain.ledger import explain
    out = explain(item_id)
    if not out:
        raise HTTPException(404, "unknown id")
    return out


@router.get("/thoughts")
def thoughts(limit: int = 50, decision: str | None = None):
    """Everything Mayday considered, including what it decided not to say (and why)."""
    import json as _json
    store = _store()
    if decision:
        rows = store._rows("SELECT * FROM candidates WHERE decision=? ORDER BY ts DESC LIMIT ?", (decision, limit))
    else:
        rows = store._rows("SELECT * FROM candidates ORDER BY ts DESC LIMIT ?", (limit,))
    for r in rows:
        r["evidence"] = _json.loads(r["evidence"] or "[]")
        r["gates"] = _json.loads(r["gates"] or "{}")
    return {"thoughts": rows}


_OUTCOMES = {"accepted", "edited", "later", "dismissed", "less", "ignored"}


@router.post("/suggestions/{sid}/{outcome}")
def suggestion_outcome(sid: str, outcome: str):
    """Do it (accepted) / Not now (later) / Less of this (less) / ✕ (dismissed) / edited."""
    from backend.brain.ledger import resolve_suggestion
    if outcome not in _OUTCOMES:
        raise HTTPException(400, f"outcome must be one of {sorted(_OUTCOMES)}")
    r = resolve_suggestion(sid, outcome)
    if not r:
        raise HTTPException(404, "unknown suggestion")
    out = {"ok": True, "outcome": r.get("outcome")}
    if outcome in ("accepted", "edited") and r.get("mode") in ("nudge", "framing"):
        from backend.brain.proactive import execute_accepted
        try:
            out["result"] = execute_accepted(sid, edited=outcome == "edited")
        except Exception as e:
            out["result"] = {"done": False, "error": str(e)[:200]}
    return out


@router.get("/learning")
def learning():
    """What the meta layer has learned: per-type acceptance/thresholds, lessons, calibrated prefs."""
    store = _store()
    return {"types": store._rows("SELECT * FROM type_stats ORDER BY updated_at DESC"),
            "lessons": store._rows("SELECT id, trigger, lesson, scope, votes, status, uses, last_used "
                                   "FROM lessons ORDER BY votes DESC, updated_at DESC LIMIT 50"),
            "prefs_calibrated": store._rows("SELECT * FROM prefs_calibrated ORDER BY votes DESC")}


# ---------------------------------------------------------------- Brain V3 P11: decision + agency
@router.post("/suggestions/{sid}/choose/{index}")
def choose_option(sid: str, index: int):
    """A framing card's option was picked: resolve as accepted and run that option's action."""
    from backend.brain.ledger import resolve_suggestion
    from backend.brain.proactive import execute_accepted
    if not resolve_suggestion(sid, "accepted"):
        raise HTTPException(404, "unknown suggestion")
    try:
        return {"ok": True, "result": execute_accepted(sid, option_index=index)}
    except (IndexError, TypeError):
        raise HTTPException(400, "no such option")


class ProactiveSettings(BaseModel):
    dial: str | None = None


@router.get("/proactive")
def proactive_settings():
    from backend.brain import proactive as pr
    d = pr.dial()
    return {"dial": d, "dials": list(pr.DIALS), "budget": pr.DIALS[d]["budget"],
            "shown_today": pr._shown_today(urgent=False), "quiet_hours": pr._cfg()["quiet_hours"],
            "preauthorized": sorted(pr.preauthorized()),
            "actions": {k: {"risk": v["risk"], "reversible": v["reversible"]} for k, v in pr.ACTIONS.items()}}


@router.put("/proactive")
def update_proactive(body: ProactiveSettings):
    from backend.brain import proactive as pr
    if body.dial is not None:
        try:
            pr.set_dial(body.dial)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return proactive_settings()


class Preauth(BaseModel):
    kind: str
    allowed: bool


@router.post("/proactive/preauthorize")
def preauthorize(body: Preauth):
    """Let Mayday do a reversible action type on its own (or stop it). Never for send/pay/book/delete."""
    from backend.brain import proactive as pr
    try:
        return {"preauthorized": sorted(pr.set_preauthorized(body.kind, body.allowed))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/actions")
def actions(limit: int = 50):
    """Audit trail of everything Mayday did silently or on its own (with Undo for 7 days)."""
    import json as _json
    rows = _store()._rows("SELECT * FROM actions ORDER BY ts DESC LIMIT ?", (limit,))
    for r in rows:
        r["payload"] = _json.loads(r["payload"] or "{}")
        r["evidence"] = _json.loads(r["evidence"] or "[]")
        r.pop("undo_payload", None)
    return {"actions": rows}


@router.post("/actions/{aid}/undo")
def undo_action(aid: str):
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from backend.brain.proactive import undo
    rows = _store()._rows("SELECT ts FROM actions WHERE id=?", (aid,))
    if not rows:
        raise HTTPException(404, "unknown action")
    if _dt.fromisoformat(rows[0]["ts"]) < _dt.now(_tz.utc) - _td(days=7):
        raise HTTPException(410, "undo window (7 days) has passed")
    if not undo(aid):
        raise HTTPException(409, "already undone")
    return {"ok": True}


@router.post("/proactive/run")
def run_generators_now():
    """Run the generators now (debug / 'check for anything')."""
    from backend.brain.generators import run_all
    return {"results": run_all(force=True)}


# ---------------------------------------------------------------- Brain V3 P12: friction + prep packs
@router.get("/frictions")
def frictions(status: str = "open"):
    """What the 72-hour look-ahead found (conflicts, overload, missing prep, …)."""
    import json as _json
    from backend.brain.friction import detect
    detect()
    rows = _store()._rows("SELECT * FROM frictions WHERE status=? ORDER BY day, severity", (status,))
    for r in rows:
        r["detail"] = _json.loads(r["detail"] or "{}")
        r["evidence"] = _json.loads(r["evidence"] or "[]")
    return {"frictions": rows}


@router.get("/prep")
def prep_list(limit: int = 20):
    from backend.brain.prep import list_packs
    return {"packs": list_packs(limit)}


@router.get("/prep/{pid}")
def prep_open(pid: str):
    """Open a prep pack (marks it opened — that's how 'used before the event' is measured)."""
    from backend.brain.prep import open_pack
    p = open_pack(pid)
    if not p:
        raise HTTPException(404, "unknown prep pack")
    return p


@router.post("/prep/{pid}/action/{index}")
def prep_add_action(pid: str, index: int):
    """Turn one of the pack's action items into a Planner task (logged, undoable)."""
    from backend.brain.prep import open_pack
    from backend.brain.proactive import execute
    p = open_pack(pid)
    if not p:
        raise HTTPException(404, "unknown prep pack")
    items = p["content"].get("action_items") or []
    if not 0 <= index < len(items):
        raise HTTPException(400, "no such action item")
    import re as _re
    title = _re.sub(r"(\[\d+\])+\s*$", "", items[index]).strip()
    act = execute("planner_create_task", {"title": title, "due_at": (p.get("starts_at") or "")[:10] or None},
                  mode="approved", why=f"Action item from the prep pack for \"{p['title']}\".",
                  evidence=[f"p:{p['target_id']}"])
    return {"ok": True, "action": act}


# ---------------------------------------------------------------- Brain V3 P13: intents + state
@router.get("/intents")
def intents_list(include_dropped: bool = False):
    """What Mayday thinks the user is working towards (with probability and evidence)."""
    import json as _json
    from backend.brain.intents import _store as intents_store
    store = intents_store()
    q = "SELECT * FROM intents" + ("" if include_dropped else " WHERE status IN ('hypothesis','working','confirmed')")
    rows = store._rows(q + " ORDER BY p DESC, updated_at DESC LIMIT 20")
    for r in rows:
        r["evidence"] = _json.loads(r["evidence"] or "[]")
        r["implies"] = _json.loads(r["implies"] or "[]")
    return {"intents": rows}


@router.post("/intents/{iid}/{verdict}")
def intent_feedback(iid: str, verdict: str):
    """'confirm' (yes, that's what I'm doing) or 'reject' (not right)."""
    from backend.brain.intents import _refresh_working_memory, confirm
    if verdict not in ("confirm", "reject"):
        raise HTTPException(400, "verdict must be confirm or reject")
    if not confirm(iid, verdict == "confirm"):
        raise HTTPException(404, "unknown intent")
    _refresh_working_memory()
    return {"ok": True}


@router.post("/intents/run")
def intents_run():
    from backend.brain.intents import maybe_run
    return maybe_run(force=True)


@router.get("/state")
def state_now():
    """Mayday's read of the user's state right now (relative to their own baseline), with reasons."""
    from backend.brain.state import corrections_last_week, estimate
    return {**estimate(use_cache=False), "corrections_last_week": corrections_last_week()}


class StateCorrection(BaseModel):
    dim: str
    value: float


@router.post("/state/correct")
def state_correct(body: StateCorrection):
    """'I'm fine, just busy': override one dimension for 24 h (and learn from it)."""
    from backend.brain.state import correct
    try:
        return correct(body.dim, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- Brain V3 P14: routines + curiosity
@router.get("/routines")
def routines_list():
    from backend.brain.routines import active
    return {"routines": active()}


@router.post("/routines/{wid}/forget")
def routine_forget(wid: str):
    store = _store()
    if not store._rows("SELECT 1 FROM workflows WHERE id=?", (wid,)):
        raise HTTPException(404, "unknown routine")
    with store._lock:
        store._conn.execute("UPDATE workflows SET status='rejected' WHERE id=?", (wid,))
    return {"ok": True}


@router.get("/curiosity")
def curiosity_list():
    """Topics Mayday decided to learn about on its own (queued / researching / done)."""
    import json as _json
    from backend.brain.curiosity import _store as cstore
    rows = cstore()._rows("SELECT * FROM curiosity ORDER BY created_at DESC LIMIT 30")
    for r in rows:
        r["evidence"] = _json.loads(r["evidence"] or "[]")
    return {"topics": rows}
