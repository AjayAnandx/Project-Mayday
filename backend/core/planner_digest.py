"""Morning plan + evening review email digests for the Planner.

Config (config.yaml):
    planner:
      digest:
        enabled: true
        morning: "07:30"
        evening: "21:00"
        to: ""            # falls back to gmail.user_email
      app_url: "http://localhost:8771"

Sent from the Mayday agent mailbox to the user's own address, once per day per
kind (state in planner/digest_state.json + Gmail idempotency key).
"""
from __future__ import annotations

import html as _html
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RETRY_AFTER = timedelta(minutes=30)


def _cfg() -> dict:
    try:
        from backend.core.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _digest_cfg(cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else _cfg()
    d = dict((cfg.get("planner", {}) or {}).get("digest", {}) or {})
    d.setdefault("enabled", True)
    d.setdefault("morning", "07:30")
    d.setdefault("evening", "21:00")
    d["to"] = d.get("to") or (cfg.get("gmail", {}) or {}).get("user_email") or ""
    return d


def _when(item: dict) -> str:
    v = item.get("occurrence_at") or item.get("start_at") or item.get("due_at") or ""
    if len(v) >= 16:
        return datetime.fromisoformat(v).strftime("%I:%M %p").lstrip("0")
    return "All day" if item["kind"] == "event" else ""


def _rank(item: dict):
    return (item.get("priority", 4), item.get("due_at") or "9999")


def build_digest(kind: str, now: datetime | None = None) -> dict:
    """Return {"subject", "text", "html", "sections": [(heading, [lines])]}."""
    from backend.core.planner_store import get_planner, now_local
    p = get_planner()
    now = now or now_local()
    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    open_items = [i for i in p.all_items() if i["status"] == "open"]
    people = {x["id"]: x["name"] for x in p.list_people()}

    def line(i: dict) -> str:
        text = i["title"]
        who = people.get(i.get("person_id") or "")
        if who and i["kind"] == "waiting":
            text += f" ({who})"
        w = _when(i)
        return f"{w} — {text}" if w else text

    sections: list[tuple[str, list[str]]] = []
    if kind == "morning":
        day_start = datetime.combine(now.date(), datetime.min.time())
        events = []
        for i in open_items:
            if i["kind"] == "event":
                events.extend(p.expand(i, day_start, day_start + timedelta(days=1, minutes=-1)))
        events.sort(key=lambda e: e.get("occurrence_at") or "")
        tasks = [i for i in open_items if i["kind"] in ("task", "reminder")]
        overdue = sorted([i for i in tasks if i.get("due_at") and i["due_at"][:10] < today], key=_rank)
        due_today = sorted([i for i in tasks if (i.get("due_at") or "")[:10] == today], key=_rank)
        follow = [i for i in open_items if i["kind"] == "waiting" and (i.get("follow_up_at") or "9")[:10] <= today]
        top3 = (overdue + due_today)[:3]
        subject = f"Your plan for {now.strftime('%A, %d %b')}"
        if top3:
            sections.append(("Focus on these first", [i["title"] for i in top3]))
        sections.append(("Today's schedule", [line(e) for e in events] or ["No events — a clear day."]))
        if due_today:
            sections.append((f"Due today ({len(due_today)})", [line(i) for i in due_today]))
        if overdue:
            sections.append((f"Overdue ({len(overdue)})", [f"{i['title']} — was due {i['due_at'][:10]}" for i in overdue]))
        if follow:
            sections.append((f"Follow up today ({len(follow)})",
                             [f"{people.get(i.get('person_id') or '', 'Someone')}: {i['title']}" for i in follow]))
        # Brain V2 P6: open loops from recent conversations (episodes + promises not in Planner)
        try:
            from backend.memory.knowledge_graph import get_graph
            store = get_graph()._store
            if store is not None:
                from backend.brain.reflection import open_loops
                loops = open_loops(store)
                if loops:
                    sections.append(("From your conversations", loops))
                # Brain V3 P11: suggestions batched by the interruption budget / quiet hours
                from backend.brain.proactive import digest_items
                batched = digest_items(5)
                if batched:
                    sections.append(("Mayday suggests", [f"{b['text']} ({b['why']})" for b in batched]))
        except Exception:
            pass
    else:
        done_today = []
        for i in p.all_items():
            if (i.get("completed_at") or "")[:10] == today:
                done_today.append(i["title"])
            for c in i.get("completions") or []:
                if (c.get("at") or "")[:10] == today:
                    done_today.append(i["title"])
        slipped = sorted([i for i in open_items if i["kind"] in ("task", "reminder")
                          and i.get("due_at") and i["due_at"][:10] <= today], key=_rank)
        t_start = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        tomorrow_items = []
        for i in open_items:
            if i["kind"] == "event":
                tomorrow_items.extend(p.expand(i, t_start, t_start + timedelta(days=1, minutes=-1)))
            elif (i.get("due_at") or "")[:10] == tomorrow:
                tomorrow_items.append(i)
        tomorrow_items.sort(key=lambda e: e.get("occurrence_at") or e.get("due_at") or "")
        waiting = [i for i in open_items if i["kind"] == "waiting"]
        subject = f"Day review — {len(done_today)} done, {len(slipped)} carried over"
        sections.append((f"Done today ({len(done_today)})", done_today or ["Nothing checked off today."]))
        if slipped:
            sections.append((f"Still open ({len(slipped)}) — move to tomorrow?", [i["title"] for i in slipped]))
        sections.append(("Tomorrow", [line(i) for i in tomorrow_items] or ["Nothing scheduled yet."]))
        if waiting:
            sections.append((f"Waiting on others ({len(waiting)})",
                             [f"{people.get(i.get('person_id') or '', 'Someone')}: {i['title']}" for i in waiting]))

    app_url = ((_cfg().get("planner", {}) or {}).get("app_url") or "http://localhost:8771").rstrip("/")
    text = subject + "\n\n" + "\n\n".join(
        h + "\n" + "\n".join(f"  • {l}" for l in lines) for h, lines in sections
    ) + f"\n\nOpen Planner: {app_url}/\n— Mayday"
    html_parts = [
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:auto;color:#111\">",
        f"<h2 style=\"margin:0 0 16px;font-weight:600\">{_html.escape(subject)}</h2>",
    ]
    for h, lines in sections:
        html_parts.append(f"<h3 style=\"margin:20px 0 6px;font-size:14px;color:#15803d\">{_html.escape(h)}</h3><ul style=\"margin:0;padding-left:18px\">")
        html_parts.extend(f"<li style=\"margin:3px 0\">{_html.escape(l)}</li>" for l in lines)
        html_parts.append("</ul>")
    html_parts.append(f"<p style=\"margin-top:24px\"><a href=\"{app_url}/\" style=\"background:#22c55e;color:#000;padding:8px 14px;border-radius:8px;text-decoration:none;font-weight:600\">Open Planner</a></p></div>")
    return {"subject": subject, "text": text, "html": "".join(html_parts), "sections": sections}


def _state_path() -> Path:
    from backend.core.planner_store import get_planner
    return get_planner()._dir / "digest_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def send_digest(kind: str, now: datetime | None = None, to: str | None = None) -> dict:
    from backend.core.gmail_service import is_authenticated, send_message
    from backend.core.planner_store import now_local
    now = now or now_local()
    to = to or _digest_cfg()["to"]
    if not to:
        return {"sent": False, "reason": "no recipient: set planner.digest.to or gmail.user_email"}
    if not is_authenticated("agent"):
        return {"sent": False, "reason": "Gmail (Mayday mailbox) not connected"}
    d = build_digest(kind, now)
    res = send_message(to, d["subject"], d["text"], html=d["html"],
                       idempotency_key=f"planner-digest-{kind}-{now.date().isoformat()}")
    return {"sent": True, "id": res.get("id", ""), "subject": d["subject"]}


def maybe_send_digests(now: datetime | None = None) -> list[str]:
    """Called every scheduler tick. Sends each due digest at most once per day."""
    from backend.core.planner_store import now_local
    cfg = _digest_cfg()
    if not cfg.get("enabled") or not cfg.get("to"):
        return []
    now = now or now_local()
    today = now.date().isoformat()
    state = _load_state()
    sent = []
    for kind in ("morning", "evening"):
        try:
            hh, mm = (int(x) for x in str(cfg[kind]).split(":"))
        except (ValueError, KeyError):
            continue
        if (now.hour, now.minute) < (hh, mm):
            continue
        entry = state.get(kind, {})
        if entry.get("sent_date") == today:
            continue
        last_try = entry.get("last_attempt")
        if last_try and now - datetime.fromisoformat(last_try) < RETRY_AFTER:
            continue
        entry["last_attempt"] = now.isoformat()
        try:
            res = send_digest(kind, now, cfg["to"])
            if res.get("sent"):
                entry["sent_date"] = today
                sent.append(kind)
            else:
                logger.info("planner digest %s skipped: %s", kind, res.get("reason"))
        except Exception as e:
            logger.warning("planner digest %s failed: %s", kind, e)
        state[kind] = entry
        _save_state(state)
    return sent
