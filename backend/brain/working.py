"""Brain V3 P9: working memory — what is true *right now*. In-process, never persisted.

Fed by the signal bus. Holds:
  * the active conversation and its topic (last user message, short)
  * the Planner item in progress (a time block covering now, else the last item touched)
  * activity: focus / away / device (from timing), active app category
  * notable signals of the last 30 minutes (urgent mail, traffic, dismissals, frustration)
  * slots for the state estimate and latent goals (filled in P13)

get_working().render() is the compact line injected into the prompt ("Right now: …").
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta, timezone

NOTABLE = {"urgent_message", "traffic_delay", "ui_dismiss", "dissatisfaction", "transition",
           "location_place", "focus_start", "focus_end", "idle_end"}


class WorkingContext:
    def __init__(self):
        self._lock = threading.Lock()
        self.conversation_id: str | None = None
        self.topic: str = ""
        self.channel: str = ""
        self.last_planner_item: str | None = None
        self.app_category: str | None = None
        self.place: str | None = None
        self.notable: deque = deque(maxlen=30)
        self.state: dict = {}            # P13: {focus, load, fatigue, stress}
        self.intents: list[dict] = []    # P13: latent goal hypotheses

    # ---------------- bus subscriber
    def on_signal(self, sig: dict) -> None:
        k, v = sig["kind"], sig.get("value") or {}
        with self._lock:
            if k == "message":
                self.conversation_id = sig.get("subject") or self.conversation_id
                self.channel = v.get("channel") or self.channel
            elif k == "planner_change":
                self.last_planner_item = sig.get("subject")
            elif k == "desktop_window":
                cats = v.get("cat") or {}
                if cats:
                    self.app_category = max(cats.items(), key=lambda x: x[1])[0]
            elif k == "location_place":
                self.place = v.get("place")
            if k in NOTABLE:
                self.notable.append({"ts": sig["ts"], "kind": k, "value": v, "subject": sig.get("subject")})

    def set_topic(self, text: str) -> None:
        with self._lock:
            self.topic = " ".join((text or "").split())[:120]

    # ---------------- read
    def _current_block(self) -> dict | None:
        try:
            from backend.core.planner_store import get_planner, now_local
            now = now_local()
            for i in get_planner().list_items(view="today"):
                blk = i.get("scheduled_block") or {}
                start, end = blk.get("start") or i.get("start_at"), blk.get("end") or i.get("end_at")
                if start and end and len(start) > 10 and start <= now.strftime("%Y-%m-%dT%H:%M") <= end:
                    return {"id": i["id"], "title": i.get("title", ""), "until": end[11:16]}
        except Exception:
            pass
        return None

    def snapshot(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        try:
            from backend.brain.timing import get_timing
            timing = get_timing().snapshot(now)
        except Exception:
            timing = {}
        with self._lock:
            since = now - timedelta(minutes=30)
            recent = [n for n in self.notable if _parse(n["ts"]) >= since]
            return {"conversation_id": self.conversation_id, "topic": self.topic, "channel": self.channel,
                    "current_block": self._current_block(), "last_planner_item": self.last_planner_item,
                    "app_category": self.app_category, "place": self.place, "timing": timing,
                    "recent": recent, "state": dict(self.state), "intents": list(self.intents)}

    def render(self, now: datetime | None = None) -> str:
        """One or two short lines for the prompt; '' when nothing useful is known."""
        s = self.snapshot(now)
        parts = []
        t = s["timing"] or {}
        if t.get("focus"):
            parts.append(f"in deep focus ({t['focus']['category']}, {int(t['focus']['minutes'])} min)")
        elif t.get("away"):
            parts.append("away from the laptop")
        if s["current_block"]:
            parts.append(f"time-blocked on \"{s['current_block']['title']}\" until {s['current_block']['until']}")
        if s["channel"] == "telegram" or (t.get("device") or {}).get("locked"):
            parts.append("on the phone")
        if s["place"] and s["place"] not in ("home",):
            parts.append(f"at {s['place']}")
        notes = []
        for n in s["recent"][-5:]:
            if n["kind"] == "urgent_message":
                notes.append("an urgent email just arrived")
            elif n["kind"] == "traffic_delay":
                notes.append(f"traffic: {n['value'].get('travel_min')} min to the next event")
            elif n["kind"] == "dissatisfaction":
                notes.append("the user seemed unhappy with the last answer")
        line = ("Right now the user is " + "; ".join(parts) + ".") if parts else ""
        if notes:
            line += (" " if line else "") + "Recently: " + "; ".join(dict.fromkeys(notes)) + "."
        return line


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.now(timezone.utc)


_WORKING = WorkingContext()


def get_working() -> WorkingContext:
    return _WORKING
