"""LLM tool handlers for the dedicated consumer mailbox (gmail_* group).

Approval gate (per plan): gmail_send / gmail_reply transmit immediately when
called — the gate is the chat-loop flow enforced by GMAIL_INSTRUCTIONS:
draft with gmail_draft first, show the user, call send/reply ONLY after the
user says approve/send/reply. Sends are recorded to the operation log and the
local idempotency cache prevents double-send on LLM retry.
"""
from __future__ import annotations

import base64
import logging
import uuid

logger = logging.getLogger(__name__)


def _headers_of(msg: dict) -> dict:
    try:
        hdrs = (msg.get("payload", {}) or {}).get("headers", []) or []
        return {h.get("name", ""): h.get("value", "") for h in hdrs}
    except Exception:
        return {}


def _extract_body(payload: dict) -> str:
    """Best-effort text/plain extraction from a Gmail payload tree."""
    if not isinstance(payload, dict):
        return ""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data", "")
    if data and mime.startswith("text/plain"):
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        except Exception:
            return ""
    if data and mime.startswith("text/html") and not payload.get("parts"):
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        except Exception:
            return ""
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


def _attachment_list(payload: dict) -> list[str]:
    names: list[str] = []

    def _walk(p: dict):
        if not isinstance(p, dict):
            return
        filename = p.get("filename", "")
        body = p.get("body", {}) or {}
        if filename and body.get("attachmentId"):
            size = body.get("size", 0)
            names.append(f"{filename} ({size} bytes)")
        for part in p.get("parts", []) or []:
            _walk(part)

    _walk(payload or {})
    return names


def _need_auth_error() -> str:
    return ("Gmail is not connected. Tell the user to click 'Connect Gmail for Mayday' "
            "on the Dashboard, pick the Mayday mailbox, and grant access.")


def gmail_list(query: str = "is:unread", limit: int = 10) -> str:
    from backend.core.gmail_service import NeedsOAuth, get_message, list_messages

    try:
        data = list_messages(query=query, max_results=max(1, min(limit, 50)))
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error listing Gmail messages: {e}"
    msgs = data.get("messages", []) or []
    if not msgs:
        return f"No Gmail messages for query '{query}'."
    lines = [f"Gmail messages for '{query}' ({data.get('resultSizeEstimate', len(msgs))} estimated):"]
    for m in msgs[:limit]:
        try:
            meta = get_message(m["id"], fmt="metadata")
        except Exception as e:
            lines.append(f"  - {m['id']} (metadata failed: {e})")
            continue
        h = _headers_of(meta)
        labels = ",".join(meta.get("labelIds", []) or [])
        lines.append(f"  - From: {h.get('From', '?')} | Subject: {h.get('Subject', '(no subject)')} "
                     f"| Date: {h.get('Date', '?')} | id: {m['id']} [{labels}]")
        if meta.get("snippet"):
            lines.append(f"    {meta['snippet'][:150]}")
    return "\n".join(lines)


def gmail_search(query: str, limit: int = 10) -> str:
    if not query or not query.strip():
        return "Missing required parameter: query (Gmail search syntax, e.g. 'from:alice subject:invoice has:attachment')"
    return gmail_list(query=query.strip(), limit=limit)


def gmail_read(message_id: str) -> str:
    from backend.core.gmail_service import NeedsOAuth, get_message

    if not message_id or not message_id.strip():
        return "Missing required parameter: message_id"
    try:
        msg = get_message(message_id.strip(), fmt="full")
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error reading Gmail message: {e}"
    h = _headers_of(msg)
    body = _extract_body(msg.get("payload", {}) or {})
    atts = _attachment_list(msg.get("payload", {}) or {})
    lines = [
        f"From: {h.get('From', '?')}",
        f"To: {h.get('To', '?')}",
        f"Date: {h.get('Date', '?')}",
        f"Subject: {h.get('Subject', '(no subject)')}",
        f"Labels: {','.join(msg.get('labelIds', []) or [])}",
        "",
        (body[:6000] + ("… [truncated]" if len(body) > 6000 else "")) or "(no text body)",
    ]
    if atts:
        lines.append("")
        lines.append("Attachments: " + "; ".join(atts))
    return "\n".join(lines)


def gmail_thread(thread_id: str) -> str:
    from backend.core.gmail_service import NeedsOAuth, get_thread

    if not thread_id or not thread_id.strip():
        return "Missing required parameter: thread_id"
    try:
        th = get_thread(thread_id.strip())
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error reading Gmail thread: {e}"
    msgs = th.get("messages", []) or []
    lines = [f"Thread {thread_id} ({len(msgs)} messages):"]
    for m in msgs:
        h = _headers_of(m)
        lines.append(f"  - {h.get('From', '?')}: {h.get('Subject', '')} [{m.get('id', '')}]")
        if m.get("snippet"):
            lines.append(f"    {m['snippet'][:120]}")
    return "\n".join(lines)


def gmail_draft(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Create a Gmail draft for user review (approval gate step 1)."""
    from backend.core.gmail_service import NeedsOAuth, create_draft
    from backend.core.operation_log import get_operation_log

    if not to or not str(to).strip():
        return "Missing required parameter: to"
    if subject is None or text is None:
        return "Missing required parameter: subject and text"
    try:
        d = create_draft(to, subject or "", text or "", html=html)
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error creating Gmail draft: {e}"
    draft_id = d.get("id", "")
    try:
        get_operation_log().record("create", "email_draft", draft_id, subject or "")
    except Exception:
        pass
    return (f"Draft created (id: {draft_id}) to {to} — subject '{subject}'. "
            f"Show it to the user and send ONLY after they say approve/send.")


def gmail_send(to: str, subject: str, text: str, html: str | None = None,
               cc: list | None = None, bcc: list | None = None,
               idempotency_key: str | None = None) -> str:
    """Send email. CALL ONLY AFTER the user explicitly approved a shown draft."""
    from backend.core.gmail_service import NeedsOAuth, send_message
    from backend.core.operation_log import get_operation_log

    if not to or not str(to).strip():
        return "Missing required parameter: to"
    if subject is None or text is None:
        return "Missing required parameter: subject and text"
    key = idempotency_key or f"mayday-{uuid.uuid4().hex[:12]}"
    try:
        sent = send_message(to, subject or "", text or "", html=html, cc=cc,
                            account="agent", idempotency_key=key)
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error sending Gmail message: {e}"
    mid = sent.get("id", "")
    cached = " (deduplicated — same idempotency_key, not re-sent)" if sent.get("cached") else ""
    try:
        get_operation_log().record("create", "email", mid, subject or "")
    except Exception:
        pass
    return f"Email sent{cached} to {to} — subject '{subject}' (id: {mid})."


def gmail_reply(message_id: str, text: str, html: str | None = None) -> str:
    """Reply in-thread. CALL ONLY AFTER the user explicitly approved the reply text."""
    from backend.core.gmail_service import NeedsOAuth, get_message, send_message
    from backend.core.operation_log import get_operation_log

    if not message_id or not message_id.strip():
        return "Missing required parameter: message_id"
    if text is None:
        return "Missing required parameter: text"
    try:
        parent = get_message(message_id.strip(), fmt="metadata",
                             metadata_headers=["From", "Subject", "Message-ID", "To"])
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error loading parent message for reply: {e}"
    h = _headers_of(parent)
    parent_mid = h.get("Message-ID", "")
    thread_id = parent.get("threadId", "")
    to = h.get("From", "")
    subject = h.get("Subject", "")
    if subject and not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    try:
        sent = send_message(to, subject, text or "", html=html, thread_id=thread_id or None,
                            in_reply_to=parent_mid or None, account="agent",
                            idempotency_key=f"mayday-reply-{message_id.strip()}-{abs(hash(text or '')) % 10**8}")
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error sending Gmail reply: {e}"
    mid = sent.get("id", "")
    try:
        get_operation_log().record("create", "email", mid, subject)
    except Exception:
        pass
    return f"Reply sent to {to} — subject '{subject}' (id: {mid})."


def gmail_modify(message_id: str, add_labels: list | None = None,
                 remove_labels: list | None = None) -> str:
    from backend.core.gmail_service import NeedsOAuth, modify_labels

    if not message_id or not message_id.strip():
        return "Missing required parameter: message_id"
    if not add_labels and not remove_labels:
        return "Nothing to do: pass add_labels and/or remove_labels (e.g. remove_labels=['UNREAD'])"
    try:
        res = modify_labels(message_id.strip(), add_labels=add_labels, remove_labels=remove_labels)
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error modifying Gmail labels: {e}"
    return f"Message {message_id} updated. Labels now: {','.join(res.get('labelIds', []) or [])}."


def gmail_create_label(name: str) -> str:
    from backend.core.gmail_service import NeedsOAuth, create_label

    if not name or not name.strip():
        return "Missing required parameter: name (e.g. 'Mayday/Processed')"
    try:
        res = create_label(name.strip())
    except NeedsOAuth:
        return _need_auth_error()
    except Exception as e:
        return f"Error creating Gmail label: {e}"
    return f"Label '{name}' created (id: {res.get('id', '')})."
