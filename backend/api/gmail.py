"""Gmail OAuth + minimal REST proxy — dedicated consumer mailbox (local-only).

One-click flow:
  1. Frontend opens GET /api/auth/gmail/start?account=agent (new tab)
  2. User picks maydayishereatwork@gmail.com (login_hint) → Grant
  3. Google redirects to http://localhost:8772/api/auth/gmail/callback
  4. Backend exchanges code, writes tokens/agent_token.json (0600),
     verifies getProfile == agent_email, bootstraps historyId
  5. Frontend polls GET /api/gmail/status → badge replaces Connect button
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.core import gmail_store
from backend.core.gmail_service import (
    SCOPES,
    NeedsOAuth,
    get_credentials_path,
    get_profile,
    get_token_path,
    is_authenticated,
    list_messages,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gmail"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# state -> {account, expires_at} (in-memory CSRF, 10 min TTL)
_OAUTH_STATES: dict[str, dict] = {}
_STATE_TTL_S = 600


def _gmail_cfg() -> dict:
    try:
        from backend.core.config import load_config

        cfg = load_config().get("gmail", {}) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _redirect_uri() -> str:
    cfg = _gmail_cfg()
    return (cfg.get("redirect_uri") or "http://localhost:8772/api/auth/gmail/callback").strip()


def _agent_email() -> str:
    cfg = _gmail_cfg()
    email = (cfg.get("agent_email") or "").strip()
    if not email:
        email = gmail_store.get_agent_email()
    return email


def _client_pair() -> tuple[str, str]:
    cred_path = get_credentials_path()
    if not cred_path.exists():
        raise HTTPException(500, f"Gmail credentials.json missing at {cred_path} — see docs/llm-gateway.md setup")
    try:
        data = json.loads(cred_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"Gmail credentials.json unreadable: {e}")
    web = data.get("web") or data.get("installed") or {}
    client_id = web.get("client_id", "")
    client_secret = web.get("client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(500, "Gmail credentials.json has no client_id/client_secret")
    return client_id, client_secret


def _prune_states(now: float) -> None:
    for k in [k for k, v in _OAUTH_STATES.items() if v.get("expires_at", 0) <= now]:
        _OAUTH_STATES.pop(k, None)


def _persist_token(token_path: Path, token_data: dict, client_id: str, client_secret: str) -> None:
    """Write an authorized-user token file google-auth can reload.

    The raw exchange response lacks client_id/client_secret, which
    Credentials.from_authorized_user_file requires (else: "Authorized user
    info was not in the expected format"). Inject them before writing.
    """
    token_data = dict(token_data)
    token_data.setdefault("client_id", client_id)
    token_data.setdefault("client_secret", client_secret)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass


@router.get("/api/gmail/status")
def gmail_status():
    cfg = _gmail_cfg()
    account = (cfg.get("account") or "agent").strip() or "agent"
    email = _agent_email()
    authed = is_authenticated("agent")
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "account": account,
        "agent_email": email,
        "authenticated": authed,
        "history_id": gmail_store.get_history_id("agent"),
        "redirect_uri": _redirect_uri(),
        "ui_mode": cfg.get("ui_mode", "minimal"),
    }


@router.get("/api/auth/gmail/start")
def gmail_auth_start(account: str = Query("agent")):
    if account not in ("agent", "user"):
        raise HTTPException(400, "account must be agent|user")
    client_id, _ = _client_pair()
    redirect_uri = _redirect_uri()
    state = secrets.token_urlsafe(32)
    _prune_states(time.time())
    _OAUTH_STATES[state] = {"account": account, "expires_at": time.time() + _STATE_TTL_S}
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    # login_hint forces the account picker toward the Mayday mailbox
    hint = _agent_email() if account == "agent" else ""
    if hint:
        params["login_hint"] = hint
        params["prompt"] = "select_account consent"
    url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url, status_code=302)


@router.get("/api/auth/gmail/callback")
def gmail_auth_callback(code: str = Query(""), state: str = Query("")):
    _prune_states(time.time())
    saved = _OAUTH_STATES.pop(state, None)
    if not saved:
        raise HTTPException(403, "Invalid/expired OAuth state — restart Connect from Mayday")
    account = saved.get("account", "agent")
    if not code:
        raise HTTPException(400, "Google returned no code (consent denied?)")

    client_id, client_secret = _client_pair()
    redirect_uri = _redirect_uri()
    try:
        r = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Token exchange transport error: {e}")
    if r.status_code != 200:
        detail = r.text[:500]
        logger.warning("Gmail token exchange failed %s: %s", r.status_code, detail)
        raise HTTPException(502, f"Google token exchange failed ({r.status_code}): {detail}")
    token_data = r.json()

    token_path = get_token_path(account)
    # Preserve an existing refresh_token if Google omits it on re-consent
    if not token_data.get("refresh_token") and token_path.exists():
        try:
            old = json.loads(token_path.read_text(encoding="utf-8"))
            if old.get("refresh_token"):
                token_data["refresh_token"] = old["refresh_token"]
        except (json.JSONDecodeError, OSError):
            pass
    _persist_token(token_path, token_data, client_id, client_secret)

    # Verify identity: getProfile must be the Mayday mailbox, not personal
    try:
        profile = get_profile(account)
    except NeedsOAuth as e:
        raise HTTPException(502, f"Token saved but Gmail auth failed: {e}")
    except Exception as e:
        raise HTTPException(502, f"Token saved but getProfile failed: {e}")
    email = (profile.get("emailAddress") or "").strip()
    expected = _agent_email()
    if account == "agent" and expected and email.lower() != expected.lower():
        try:
            token_path.unlink()
        except OSError:
            pass
        raise HTTPException(
            400,
            f"Wrong account: connected {email} but Mayday expects {expected}. "
            "Re-click Connect and pick the Mayday account in the picker.",
        )
    gmail_store.set_agent_email(email)
    if profile.get("historyId"):
        gmail_store.set_history_id(account, str(profile["historyId"]))
    logger.info("Gmail connected: account=%s email=%s", account, email)
    return HTMLResponse(
        f"<html><body style='font-family:sans-serif;background:#050505;color:#e5e5e5;padding:40px'>"
        f"<h2 style='color:#22c55e'>Mayday Gmail connected</h2>"
        f"<p><b>{email}</b> ({account})</p>"
        f"<p>You can close this tab and return to Mayday.</p></body></html>"
    )


@router.get("/api/gmail/messages")
def gmail_messages(q: str = Query("is:unread"), limit: int = Query(10, ge=1, le=50)):
    try:
        data = list_messages(query=q, max_results=limit)
    except NeedsOAuth as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        msg = str(e)
        # Token exists but Gmail scope was unchecked on the consent screen
        # (Google granted only userinfo.email/openid). Tell user how to fix.
        if ("insufficientPermissions" in msg or "accessNotConfigured" in msg
                or "invalid_scope" in msg
                or "insufficient authentication scopes" in msg.lower()):
            raise HTTPException(
                403,
                "Gmail token lacks the gmail.modify scope (only basic profile was granted). "
                "Re-click 'Connect Gmail for Mayday' and CHECK the Gmail permission box on the consent screen.",
            )
        raise HTTPException(502, f"Gmail list failed: {e}")
    return {"q": q, "messages": data.get("messages", []),
            "resultSizeEstimate": data.get("resultSizeEstimate", 0)}
