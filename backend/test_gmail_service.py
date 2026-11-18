"""Gmail service — mocked googleapiclient, zero repo pollution.

Covers: NeedsOAuth on missing token, transparent refresh rewrite,
send idempotency cache, gmail_store history/email roundtrip.
"""
import json
import sys
import types


def _install_google_stubs():
    """Stub google.* modules so tests run without real deps/network."""
    calls = {"refresh": 0, "send": 0}

    cred_mod = types.ModuleType("google.oauth2.credentials")

    class FakeCreds:
        def __init__(self, expired=False, refresh_token="rt", valid=True):
            self.expired = expired
            self.refresh_token = refresh_token
            self.valid = valid

        def refresh(self, _request):
            calls["refresh"] += 1
            self.expired = False

        def to_json(self):
            return json.dumps({"refresh_token": self.refresh_token,
                               "access_token": "new-at", "token_uri": "x"})

        @classmethod
        def from_authorized_user_file(cls, _path, _scopes):
            inst = cls.__new__(cls)
            FakeCreds.__init__(inst)
            return inst

    cred_mod.Credentials = FakeCreds

    oauth2_pkg = types.ModuleType("google.oauth2")
    oauth2_pkg.credentials = cred_mod
    transport_pkg = types.ModuleType("google.auth.transport.requests")
    transport_pkg.Request = object
    auth_pkg = types.ModuleType("google.auth.transport")
    auth_pkg.requests = transport_pkg
    auth_root = types.ModuleType("google.auth")
    auth_root.transport = auth_pkg
    google_pkg = types.ModuleType("google")
    google_pkg.oauth2 = oauth2_pkg
    google_pkg.auth = auth_root

    class _Send:
        def execute(self):
            calls["send"] += 1
            return {"id": "m1", "threadId": "t1"}

    class _Messages:
        def send(self, **_kw):
            return _Send()

    class _Users:
        def messages(self):
            return _Messages()

    class _Svc:
        def users(self):
            return _Users()

    disc_mod = types.ModuleType("googleapiclient.discovery")
    disc_mod.build = lambda *a, **k: _Svc()
    api_pkg = types.ModuleType("googleapiclient")
    api_pkg.discovery = disc_mod

    sys.modules["google"] = google_pkg
    sys.modules["google.oauth2"] = oauth2_pkg
    sys.modules["google.oauth2.credentials"] = cred_mod
    sys.modules["google.auth"] = auth_root
    sys.modules["google.auth.transport"] = auth_pkg
    sys.modules["google.auth.transport.requests"] = transport_pkg
    sys.modules["googleapiclient"] = api_pkg
    sys.modules["googleapiclient.discovery"] = disc_mod
    return calls


def _service(monkeypatch, tmp_path):
    import backend.core.gmail_service as gs

    token = tmp_path / "agent_token.json"
    monkeypatch.setattr(gs, "get_token_path", lambda account="agent": token)
    monkeypatch.setattr(gs, "_gmail_cfg", lambda: {})
    return gs


def test_ensure_token_missing_raises(monkeypatch, tmp_path):
    _install_google_stubs()
    gs = _service(monkeypatch, tmp_path)
    try:
        gs.ensure_token("agent")
    except gs.NeedsOAuth:
        return
    raise AssertionError("expected NeedsOAuth")


def test_get_service_refreshes_and_rewrites(monkeypatch, tmp_path):
    calls = _install_google_stubs()
    import backend.core.gmail_service as gs

    token = tmp_path / "agent_token.json"
    token.write_text(json.dumps({"refresh_token": "rt", "access_token": "old"}))
    monkeypatch.setattr(gs, "get_token_path", lambda account="agent": token)
    monkeypatch.setattr(gs, "_gmail_cfg", lambda: {})

    from google.oauth2.credentials import Credentials

    orig = Credentials.from_authorized_user_file

    @classmethod
    def expired_creds(cls, _path, _scopes):
        c = cls.__new__(cls)
        c.expired = True
        c.refresh_token = "rt"
        c.valid = True
        c.refresh = lambda _r: calls.__setitem__("refresh", calls["refresh"] + 1) or setattr(c, "expired", False)
        c.to_json = lambda: json.dumps({"refresh_token": "rt", "access_token": "new"})
        return c

    monkeypatch.setattr(Credentials, "from_authorized_user_file", expired_creds)
    try:
        gs.get_gmail_service("agent")
    finally:
        monkeypatch.setattr(Credentials, "from_authorized_user_file", orig)
    assert calls["refresh"] >= 1
    assert json.loads(token.read_text())["access_token"] == "new"


def test_send_idempotency_cache(monkeypatch, tmp_path):
    calls = _install_google_stubs()
    gs = _service(monkeypatch, tmp_path)
    gs._sent_cache.clear()
    (tmp_path / "agent_token.json").write_text(json.dumps({"refresh_token": "rt"}))
    first = gs.send_message("a@x.com", "s", "body", idempotency_key="k1")
    second = gs.send_message("a@x.com", "s", "body", idempotency_key="k1")
    assert first["id"] == "m1"
    assert second.get("cached") is True
    assert calls["send"] == 1
    gs._sent_cache.clear()


def test_store_roundtrip(monkeypatch, tmp_path):
    import backend.core.gmail_store as gst

    monkeypatch.setattr(gst, "STATE_PATH", tmp_path / "gmail_state.json")
    gst.set_agent_email("maydayishereatwork@gmail.com")
    gst.set_user_email("me@example.com")
    gst.set_history_id("agent", "12345")
    assert gst.get_agent_email() == "maydayishereatwork@gmail.com"
    assert gst.get_user_email() == "me@example.com"
    assert gst.get_history_id("agent") == "12345"
    assert gst.get_history_id("user") is None


def test_user_callback_keeps_agent_identity(monkeypatch, tmp_path):
    """Reconnecting the personal inbox must not overwrite the agent email."""
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.api.gmail as gmail_api
    import backend.core.gmail_store as gst

    monkeypatch.setattr(gst, "STATE_PATH", tmp_path / "gmail_state.json")
    gst.set_agent_email("maydayishereatwork@gmail.com")

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(gmail_api.httpx, "post", lambda *a, **kw: _Resp())
    monkeypatch.setattr(gmail_api, "_client_pair", lambda: ("cid", "csec"))
    monkeypatch.setattr(gmail_api, "_gmail_cfg",
                        lambda: {"user_email": "me@example.com"})
    monkeypatch.setattr(gmail_api, "get_token_path",
                        lambda account="agent": tmp_path / f"{account}.json")
    monkeypatch.setattr(gmail_api, "get_profile",
                        lambda account="agent": {"emailAddress": "me@example.com",
                                                "historyId": "777"})
    gmail_api._OAUTH_STATES["test-state"] = {
        "account": "user",
        "redirect_uri": "http://localhost:8771/api/auth/gmail/callback",
        "expires_at": time.time() + 60,
    }
    app = FastAPI()
    app.include_router(gmail_api.router)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/auth/gmail/callback?code=abc&state=test-state")
    assert r.status_code == 200, r.text
    assert gst.get_agent_email() == "maydayishereatwork@gmail.com"
    assert gst.get_user_email() == "me@example.com"
    assert (tmp_path / "user.json").exists()


def test_client_pair_reads_installed_block(monkeypatch, tmp_path):
    """Desktop-app fallback: credentials file uses `installed`, not `web`."""
    import backend.api.gmail as gmail_api

    cred = tmp_path / "creds.json"
    cred.write_text(json.dumps({"installed": {
        "client_id": "test-desktop-id",
        "client_secret": "test-desktop-secret",
        "project_id": "mayday-509414",
    }}))
    monkeypatch.setattr(gmail_api, "get_credentials_path", lambda: cred)
    client_id, client_secret = gmail_api._client_pair()
    assert client_id == "test-desktop-id"
    assert client_secret == "test-desktop-secret"


def test_messages_scope_error_maps_to_403(monkeypatch):
    """Token without gmail.modify must surface a 403 with fix instructions, not a bare 502."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.api.gmail as gmail_api

    def boom(**kw):
        raise Exception("403: insufficientPermissions — Request had insufficient authentication scopes.")

    monkeypatch.setattr(gmail_api, "list_messages", boom)
    app = FastAPI()
    app.include_router(gmail_api.router)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/gmail/messages?q=is:unread&limit=1")
    assert r.status_code == 403
    assert "CHECK the Gmail permission" in r.json()["detail"]


def test_persist_token_injects_client_fields(tmp_path):
    """Regression: raw exchange response lacks client_id/secret, which
    google-auth requires on reload ('Authorized user info was not in the
    expected format'). _persist_token must inject them."""
    import backend.api.gmail as gmail_api

    token_path = tmp_path / "agent_token.json"
    gmail_api._persist_token(token_path, {"access_token": "at", "refresh_token": "rt"},
                             "cid123", "csec456")
    saved = json.loads(token_path.read_text())
    assert saved["client_id"] == "cid123"
    assert saved["client_secret"] == "csec456"
    assert saved["refresh_token"] == "rt"


def _patch_gmail_service(monkeypatch, **fns):
    import backend.core.gmail_service as gs

    for name, fn in fns.items():
        monkeypatch.setattr(gs, name, fn)
    gs._sent_cache.clear()
    return gs


def test_gmail_list_formats_messages(monkeypatch):
    import backend.functions.gmail_functions as gf

    _patch_gmail_service(
        monkeypatch,
        list_messages=lambda query, max_results, account="agent": {
            "messages": [{"id": "m1", "threadId": "t1"}], "resultSizeEstimate": 1},
        get_message=lambda mid, fmt="full", account="agent", **kw: {
            "id": "m1", "threadId": "t1", "labelIds": ["UNREAD"],
            "snippet": "hello there",
            "payload": {"headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "Subject", "value": "Invoice"},
                {"name": "Date", "value": "Mon, 13 Oct 2026"},
            ]},
        },
    )
    out = gf.gmail_list("is:unread", 10)
    assert "alice@example.com" in out
    assert "Invoice" in out
    assert "m1" in out


def test_gmail_list_not_connected(monkeypatch):
    import backend.core.gmail_service as gs
    import backend.functions.gmail_functions as gf

    def boom(**kw):
        raise gs.NeedsOAuth("no token")

    _patch_gmail_service(monkeypatch, list_messages=boom)
    assert "Connect Gmail for Mayday" in gf.gmail_list()


def test_gmail_send_and_idempotent_retry(monkeypatch):
    import backend.functions.gmail_functions as gf

    calls = {"n": 0}
    seen_keys = []

    def fake_send(*args, **kw):
        calls["n"] += 1
        seen_keys.append(kw.get("idempotency_key"))
        return {"id": "sent1", "threadId": "t9"}

    gs = _patch_gmail_service(monkeypatch, send_message=fake_send)
    try:
        first = gf.gmail_send("bob@example.com", "Hi", "body text", idempotency_key="k-1")
        assert "sent1" in first
        assert seen_keys == ["k-1"]
        assert calls["n"] == 1
    finally:
        gs._sent_cache.clear()


def test_service_idempotency_cache_blocks_resend(monkeypatch):
    """Real send_message must not hit the network twice for the same key."""
    _install_google_stubs()
    import backend.core.gmail_service as gs

    gs._sent_cache.clear()
    gs._sent_cache["k-9"] = {"message_id": "m-cached", "thread_id": "t-cached",
                             "expires_at": 9999999999.0}
    try:
        out = gs.send_message("a@x.com", "s", "b", account="agent", idempotency_key="k-9")
        assert out.get("cached") is True
        assert out["id"] == "m-cached"
    finally:
        gs._sent_cache.clear()


def test_gmail_reply_threads_correctly(monkeypatch):
    import backend.functions.gmail_functions as gf

    seen = {}

    def fake_parent(mid, fmt="full", **kw):
        return {"id": mid, "threadId": "th1",
                "payload": {"headers": [
                    {"name": "From", "value": "carol@example.com"},
                    {"name": "Subject", "value": "Question"},
                    {"name": "Message-ID", "value": "<abc123@mail>"},
                ]}}

    def fake_send(*args, **kw):
        seen.update(kw)
        seen["args"] = args
        return {"id": "r1", "threadId": "th1"}

    gs = _patch_gmail_service(monkeypatch, get_message=fake_parent, send_message=fake_send)
    try:
        out = gf.gmail_reply("m7", "Sure, here you go")
        assert "r1" in out
        assert seen.get("thread_id") == "th1"
        assert seen.get("in_reply_to") == "<abc123@mail>"
        assert seen["args"][1].startswith("Re:")
        assert seen["args"][0] == "carol@example.com"
    finally:
        gs._sent_cache.clear()


def test_gmail_read_extracts_nested_body(monkeypatch):
    import base64
    import backend.functions.gmail_functions as gf

    body = base64.urlsafe_b64encode(b"Nested hello").decode()

    def fake_get(mid, fmt="full", **kw):
        return {"id": mid, "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "multipart/mixed",
                    "headers": [
                        {"name": "From", "value": "d@example.com"},
                        {"name": "Subject", "value": "Nested"},
                    ],
                    "parts": [{"mimeType": "text/plain",
                               "body": {"data": body}}],
                }}

    _patch_gmail_service(monkeypatch, get_message=fake_get)
    out = gf.gmail_read("mx")
    assert "Nested hello" in out
    assert "d@example.com" in out


def test_classifier_routes_email_intent():
    from backend.core.query_classifier import QueryClassifier

    intent = QueryClassifier().classify("check my email inbox for unread messages")
    assert intent.intent == "email"
    assert "gmail" in intent.active_groups


def test_gmail_tools_registered():
    from backend.assistant.function_registry import (
        FUNCTION_MAP, LOCAL_TOOL_DEFINITIONS, _PARAM_ALIASES, _TOOL_DEFAULTS,
        _validate_tool_definitions,
    )
    from backend.api.chat import GROUP_SETS

    names = ["gmail_send", "gmail_reply", "gmail_draft", "gmail_list",
             "gmail_search", "gmail_read", "gmail_thread", "gmail_modify",
             "gmail_create_label"]
    for n in names:
        assert n in FUNCTION_MAP, n
        assert n in GROUP_SETS["gmail"], n
    defs = [t for t in LOCAL_TOOL_DEFINITIONS if t["function"]["name"] in names]
    assert len(defs) == 9
    assert len(_validate_tool_definitions(defs)) == 9
    assert _TOOL_DEFAULTS["gmail_list"]["query"] == "is:unread"
    assert _PARAM_ALIASES["gmail_send"]["recipient"] == "to"


def test_user_scopes_always_readonly(monkeypatch):
    """Personal slot can never escalate: even scopes_user=modify is forced down."""
    import backend.api.gmail as gmail_api

    monkeypatch.setattr(gmail_api, "_gmail_cfg",
                        lambda: {"scopes_user": "gmail.modify", "scopes_agent": "gmail.modify"})
    user_scopes = gmail_api._scopes_for("user")
    assert "https://www.googleapis.com/auth/gmail.readonly" in user_scopes
    assert "https://www.googleapis.com/auth/gmail.modify" not in user_scopes
    agent_scopes = gmail_api._scopes_for("agent")
    assert "https://www.googleapis.com/auth/gmail.modify" in agent_scopes


def test_user_start_requests_readonly(monkeypatch):
    import urllib.parse as _u
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.api.gmail as gmail_api

    monkeypatch.setattr(gmail_api, "_gmail_cfg", lambda: {})
    monkeypatch.setattr(gmail_api, "_user_email", lambda: "me@example.com")
    monkeypatch.setattr(gmail_api, "_client_pair", lambda: ("cid", "csec"))
    app = FastAPI()
    app.include_router(gmail_api.router)
    c = TestClient(app, follow_redirects=False)
    r = c.get("/api/auth/gmail/start?account=user")
    assert r.status_code == 302
    q = dict(_u.parse_qsl(_u.urlsplit(r.headers["location"]).query))
    assert "gmail.readonly" in q.get("scope", "")
    assert "gmail.modify" not in q.get("scope", "")
    assert q.get("login_hint") == "me@example.com"


def test_user_writes_refused_without_network():
    """Send/modify/draft/label on account=user raise before any Google call."""
    import backend.core.gmail_service as gs
    import pytest as _pt

    gs._sent_cache.clear()
    with _pt.raises(PermissionError):
        gs.send_message("a@x.com", "s", "b", account="user", idempotency_key="k-x")
    with _pt.raises(PermissionError):
        gs.modify_labels("m1", remove_labels=["UNREAD"], account="user")
    with _pt.raises(PermissionError):
        gs.create_draft("a@x.com", "s", "b", account="user")
    with _pt.raises(PermissionError):
        gs.create_label("X", account="user")


def test_status_includes_user_slot(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.api.gmail as gmail_api
    import backend.core.gmail_service as gs

    monkeypatch.setattr(gmail_api, "_gmail_cfg",
                        lambda: {"enabled": True, "account": "both",
                                 "agent_email": "agent@example.com",
                                 "user_email": "me@example.com"})
    monkeypatch.setattr(gs, "get_token_path",
                        lambda account="agent": tmp_path / f"{account}.json")
    import backend.core.gmail_store as _gst
    monkeypatch.setattr(_gst, "STATE_PATH", tmp_path / "gmail_state.json")
    app = FastAPI()
    app.include_router(gmail_api.router)
    c = TestClient(app, raise_server_exceptions=False)
    body = c.get("/api/gmail/status").json()
    assert body["account"] == "both"
    assert body["user"] == {"email": "me@example.com", "authenticated": False,
                            "history_id": None}


def test_gmail_list_uses_matching_account_for_metadata(monkeypatch):
    """Regression: list(account=user) fetched metadata with the agent token,
    so every personal message 404'd. Both calls must carry the same account."""
    import backend.functions.gmail_functions as gf

    seen = {}

    def fake_list(query, max_results, account="agent"):
        seen["list"] = account
        return {"messages": [{"id": "m1", "threadId": "t1"}], "resultSizeEstimate": 1}

    def fake_get(mid, fmt="full", account="agent", **kw):
        seen["get"] = account
        return {"id": mid, "threadId": "t1", "labelIds": ["UNREAD"], "snippet": "hi",
                "payload": {"headers": [
                    {"name": "From", "value": "a@x.com"},
                    {"name": "Subject", "value": "S"},
                    {"name": "Date", "value": "today"},
                ]}}

    _patch_gmail_service(monkeypatch, list_messages=fake_list, get_message=fake_get)
    out = gf.gmail_list("is:unread", 5, account="user")
    assert seen == {"list": "user", "get": "user"}, seen
    assert "a@x.com" in out


def test_gmail_list_routes_by_account(monkeypatch):
    """account=user reaches the user token path; default stays agent; junk rejected."""
    import asyncio
    import backend.functions.gmail_functions as gf

    seen = {}

    def fake_list(query, max_results, account="agent"):
        seen["account"] = account
        if account == "user":
            from backend.core.gmail_service import NeedsOAuth
            raise NeedsOAuth("no user token")
        return {"messages": [], "resultSizeEstimate": 0}

    _patch_gmail_service(monkeypatch, list_messages=fake_list)

    out_default = gf.gmail_list("is:unread", 5)
    assert seen["account"] == "agent"
    assert "No Gmail messages" in out_default

    out_user = gf.gmail_list("is:unread", 5, account="user")
    assert seen["account"] == "user"
    assert "Watch personal inbox" in out_user

    out_bad = gf.gmail_list("is:unread", 5, account="work")
    assert "Invalid account" in out_bad

    async def _dispatch():
        from backend.assistant.function_registry import dispatch_call
        return await dispatch_call("gmail_list", {"query": "is:unread", "account": "user"})

    out_dispatch = asyncio.run(_dispatch())
    assert "Watch personal inbox" in out_dispatch


def test_user_sync_never_overwrites_agent_email(monkeypatch, tmp_path):
    """Regression: first user-slot sync called set_agent_email(personal),
    corrupting the agent identity. Only the agent slot may store it."""
    import backend.core.gmail_store as gst
    from backend.core.scheduler import Scheduler

    monkeypatch.setattr(gst, "STATE_PATH", tmp_path / "gmail_state.json")
    gst.set_agent_email("maydayishereatwork@gmail.com")

    import backend.core.gmail_service as gs

    monkeypatch.setattr(gs, "get_profile",
                        lambda account="agent": {"emailAddress": "me@example.com",
                                                "historyId": "999"})
    Scheduler()._sync_gmail_account("user")
    assert gst.get_agent_email() == "maydayishereatwork@gmail.com"
    assert gst.get_history_id("user") == "999"
