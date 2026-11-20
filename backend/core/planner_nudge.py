"""Draft polite follow-up ("nudge") emails for waiting-on items.

Approval-gated by design: this only ever creates a Gmail *draft* in the Mayday
mailbox. Sending stays a separate, explicit user action (gmail_send after the
user approves), matching the existing Gmail approval gate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

AUTO_DRAFT_COOLDOWN = timedelta(days=2)


def _cfg() -> dict:
    try:
        from backend.core.config import load_config
        return load_config().get("planner", {}) or {}
    except Exception:
        return {}


def compose_nudge(item: dict, person: dict) -> tuple[str, str]:
    first = (person.get("name") or "there").split()[0]
    due = item.get("due_at")
    due_txt = ""
    if due:
        d = datetime.fromisoformat(due)
        due_txt = f" (due {d.strftime('%a %d %b')})"
    chases = len(item.get("chase_log") or [])
    opener = "Just following up on" if chases == 0 else "Gently circling back on"
    signature = _cfg().get("nudge_signature") or "Thanks"
    subject = f"Quick follow-up: {item['title']}"
    body = (f"Hi {first},\n\n"
            f"{opener} {item['title']}{due_txt}. Could you let me know where it stands, "
            f"or if anything is blocking it?\n\n"
            f"{signature}")
    return subject, body


def draft_nudge(item_id: str, automatic: bool = False) -> dict:
    """Create a Gmail draft chasing the person a waiting item is on.

    Returns {"drafted": bool, "draft_id": str, "reason": str, "subject": str, "to": str}.
    """
    from backend.core.planner_store import get_planner
    planner = get_planner()
    item = planner.get_item(item_id)
    if not item:
        return {"drafted": False, "reason": "item not found"}
    if item["kind"] != "waiting":
        return {"drafted": False, "reason": "only waiting-on items can be nudged"}
    person = planner.find_person(item.get("person_id") or "") or {}
    if not person.get("email"):
        return {"drafted": False, "reason": f"no email saved for {person.get('name', 'this person')}"}
    if automatic:
        last = (item.get("chase_log") or [{}])[-1].get("at")
        if last:
            try:
                if datetime.now().astimezone() - datetime.fromisoformat(last) < AUTO_DRAFT_COOLDOWN:
                    return {"drafted": False, "reason": "recently chased"}
            except ValueError:
                pass
    subject, body = compose_nudge(item, person)
    try:
        from backend.core.gmail_service import create_draft, is_authenticated
        if not is_authenticated("agent"):
            return {"drafted": False, "reason": "Gmail not connected", "subject": subject,
                    "body": body, "to": person["email"]}
        d = create_draft(person["email"], subject, body)
    except Exception as e:
        logger.warning("nudge draft failed for %s: %s", item_id, e)
        return {"drafted": False, "reason": f"Gmail error: {e}", "subject": subject,
                "body": body, "to": person["email"]}
    draft_id = d.get("id", "")
    planner.log_chase(item_id, "email_draft", note=subject, draft_id=draft_id)
    try:
        from backend.core.operation_log import get_operation_log
        get_operation_log().record("create", "email_draft", draft_id, subject,
                                   details={"planner_item": item_id, "automatic": automatic})
    except Exception:
        pass
    return {"drafted": True, "draft_id": draft_id, "reason": "", "subject": subject,
            "body": body, "to": person["email"]}
