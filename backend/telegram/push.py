"""Unprompted Telegram pushes (research finished while you were away) via the Bot HTTP API.

Goes only to the chats in telegram.allowed_chat_ids — the owner's own chat. Sync on purpose:
called from the research worker thread, independent of the bot's event loop.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


def _targets() -> tuple[str, list[int]]:
    from backend.core.config import load_config
    cfg = load_config().get("telegram", {}) or {}
    if not cfg.get("enabled"):
        return "", []
    token = (cfg.get("token") or "").strip()
    chats = []
    for c in cfg.get("allowed_chat_ids") or []:
        try:
            chats.append(int(c))
        except (TypeError, ValueError):
            pass
    return token, chats


def push_research(title: str, summary: str, reports: list[str] | None = None) -> bool:
    """Send the summary (+ report files) to the owner's chat(s). True if at least one chat got it."""
    token, chats = _targets()
    if not token or not chats:
        logger.info("telegram push skipped: bot disabled or telegram.allowed_chat_ids empty")
        return False
    ok = False
    with httpx.Client(timeout=30) as client:
        for chat in chats:
            try:
                r = client.post(API.format(token=token, method="sendMessage"),
                                json={"chat_id": chat, "text": f"{title}\n\n{summary}"[:4000]})
                r.raise_for_status()
                ok = True
                for rep in (reports or [])[:3]:
                    p = Path(rep)
                    if p.is_file() and p.stat().st_size < 45_000_000:
                        with p.open("rb") as fh:
                            client.post(API.format(token=token, method="sendDocument"),
                                        data={"chat_id": str(chat)}, files={"document": (p.name, fh)}).raise_for_status()
            except Exception as e:
                logger.warning("telegram push to %s failed: %s", chat, e)
    return ok
