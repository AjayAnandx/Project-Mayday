"""Gmail API wrapper — dedicated consumer mailbox (local-only, poll v1).

OAuth tokens: tokens/agent_token.json (Mayday) vs tokens/user_token.json
(personal, optional). userId="me" resolves to whichever credentials load —
no cross-pollution.

Auth flow lives in backend/api/gmail.py (start/callback). This module only
loads + refreshes Credentials and wraps googleapiclient calls.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CREDENTIALS_PATH = _REPO_ROOT / "backend" / "credentials" / "gmail_credentials.json"
DEFAULT_TOKEN_AGENT = _REPO_ROOT / "tokens" / "agent_token.json"
DEFAULT_TOKEN_USER = _REPO_ROOT / "tokens" / "user_token.json"

# Local idempotency cache: idempotency_key -> {message_id, thread_id, expires_at}
_IDEMPOTENCY_TTL_S = 24 * 3600
_sent_cache: dict[str, dict] = {}


class NeedsOAuth(Exception):
    """Raised when no usable token exists — frontend should show Connect."""


def _gmail_cfg() -> dict:
    try:
        from backend.core.config import load_config

        cfg = load_config().get("gmail", {}) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _resolve(path_value: str | None, default: Path) -> Path:
    if path_value:
        p = Path(path_value)
        if not p.is_absolute():
            p = _REPO_ROOT / path_value
        return p
    return default


def get_credentials_path() -> Path:
    return _resolve((_gmail_cfg().get("credentials_path") or "").strip() or None, DEFAULT_CREDENTIALS_PATH)


def get_token_path(account: str = "agent") -> Path:
    cfg = _gmail_cfg()
    if account == "user":
        return _resolve((cfg.get("token_path_user") or "").strip() or None, DEFAULT_TOKEN_USER)
    return _resolve((cfg.get("token_path_agent") or "").strip() or None, DEFAULT_TOKEN_AGENT)


def is_authenticated(account: str = "agent") -> bool:
    return get_token_path(account).exists()


def ensure_token(account: str = "agent") -> Path:
    """Return token path or raise NeedsOAuth (missing/unreadable)."""
    p = get_token_path(account)
    if not p.exists():
        raise NeedsOAuth(f"No Gmail token for account={account!r} — connect via /api/auth/gmail/start")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise NeedsOAuth(f"Gmail token unreadable for account={account!r}: {e}")
    if not data.get("refresh_token") and not data.get("access_token"):
        raise NeedsOAuth(f"Gmail token has no credentials for account={account!r} — reconnect")
    return p


def get_gmail_service(account: str = "agent"):
    """Build an authorized Gmail v1 service (transparent refresh)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = ensure_token(account)
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
    elif not creds.valid:
        raise NeedsOAuth(f"Gmail credentials invalid for account={account!r} — reconnect")
    return build("gmail", "v1", credentials=creds)


def get_profile(account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    return svc.users().getProfile(userId="me").execute()


# --- Message wrappers (used by REST proxy + future gmail_* tools) ---


def list_messages(query: str = "is:unread", label_ids: list | None = None,
                  max_results: int = 10, page_token: str | None = None,
                  account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    kwargs: dict = {"userId": "me", "q": query, "maxResults": max_results}
    if label_ids:
        kwargs["labelIds"] = label_ids
    if page_token:
        kwargs["pageToken"] = page_token
    return svc.users().messages().list(**kwargs).execute()


def get_message(message_id: str, fmt: str = "full", account: str = "agent",
                metadata_headers: list | None = None) -> dict:
    svc = get_gmail_service(account)
    kwargs: dict = {"userId": "me", "id": message_id, "format": fmt}
    if fmt == "metadata":
        kwargs["metadataHeaders"] = metadata_headers or ["From", "Subject", "Date"]
    return svc.users().messages().get(**kwargs).execute()


def get_history(start_history_id: str, history_types: list | None = None,
                account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    return svc.users().history().list(
        userId="me",
        startHistoryId=start_history_id,
        historyTypes=history_types or ["messageAdded", "labelAdded"],
    ).execute()


def _prune_cache(now: float) -> None:
    expired = [k for k, v in _sent_cache.items() if v.get("expires_at", 0) <= now]
    for k in expired:
        _sent_cache.pop(k, None)


def send_message(to, subject: str, text: str, html: str | None = None,
                 cc: list | None = None, bcc: list | None = None,
                 thread_id: str | None = None, in_reply_to: str | None = None,
                 account: str = "agent", idempotency_key: str | None = None) -> dict:
    """Send via users.messages.send. Same idempotency_key+payload returns cached id."""
    now = time.time()
    _prune_cache(now)
    if idempotency_key and idempotency_key in _sent_cache:
        cached = _sent_cache[idempotency_key]
        return {"id": cached["message_id"], "threadId": cached.get("thread_id", thread_id or ""),
                "historyId": "", "cached": True}

    msg = EmailMessage()
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    svc = get_gmail_service(account)
    sent = svc.users().messages().send(userId="me", body=body).execute()
    if idempotency_key:
        _sent_cache[idempotency_key] = {
            "message_id": sent.get("id", ""),
            "thread_id": sent.get("threadId", thread_id or ""),
            "expires_at": now + _IDEMPOTENCY_TTL_S,
        }
    return sent


def modify_labels(message_id: str, add_labels: list | None = None,
                  remove_labels: list | None = None, account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    body: dict = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    return svc.users().messages().modify(userId="me", id=message_id, body=body).execute()


def get_thread(thread_id: str, fmt: str = "full", account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    return svc.users().threads().get(userId="me", id=thread_id, format=fmt).execute()


def create_label(name: str, account: str = "agent") -> dict:
    svc = get_gmail_service(account)
    body = {"name": name, "labelListVisibility": "labelShow",
            "messageListVisibility": "show"}
    return svc.users().labels().create(userId="me", body=body).execute()


def create_draft(to, subject: str, text: str, html: str | None = None,
                 cc: list | None = None, thread_id: str | None = None,
                 account: str = "agent") -> dict:
    """Create a Gmail draft (approval gate: user reviews before send)."""
    msg = EmailMessage()
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft_body: dict = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id
    svc = get_gmail_service(account)
    return svc.users().drafts().create(userId="me", body=draft_body).execute()
