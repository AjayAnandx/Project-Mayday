"""Brain V3 P8: perception detectors on top of the signal bus.

    TimingState (bus subscriber)
        desktop_window aggregates (15 s) -> focus_start / focus_end, idle_start / idle_end,
        and `transition` signals (natural breaks: focus ended, back after a break, task done,
        event ended). get_timing().snapshot() is what working memory and the decision gate read.
    dissatisfaction(text, previous_user_texts) -> score 0..1 (+ reasons): "no, I meant…",
        "that's wrong", repeating / rephrasing the last request
    urgency(sender, subject, snippet, important_senders) -> score 0..1 (+ reasons)

Everything here is deterministic and cheap: no model calls.
"""
from __future__ import annotations

import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

from backend.brain.signals import publish
from backend.core.config import load_config

WORK_CATEGORIES = {"code", "docs", "design", "data", "terminal"}


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("timing", {}) or {}
    return {"focus_minutes": float(c.get("focus_minutes", 20)),
            "focus_share": float(c.get("focus_share", 0.75)),
            "max_switches_per_min": float(c.get("max_switches_per_min", 1.5)),
            "focus_exit_minutes": float(c.get("focus_exit_minutes", 2)),
            "idle_minutes": float(c.get("idle_minutes", 5)),
            "session_gap_minutes": float(c.get("session_gap_minutes", 15))}


def _ts(sig: dict) -> datetime:
    try:
        return datetime.fromisoformat(sig["ts"])
    except Exception:
        return datetime.now(timezone.utc)


class TimingState:
    def __init__(self):
        self._lock = threading.Lock()
        self.windows: deque = deque()            # (ts, value) of desktop_window aggregates
        self.focus: dict | None = None           # {"category", "since"}
        self.focus_candidate_off_since: datetime | None = None
        self.idle_since: datetime | None = None
        self.idle_emitted = False
        self.last_active: datetime | None = None
        self.device: dict = {}

    # ---------------- bus subscriber
    def on_signal(self, sig: dict) -> None:
        kind = sig["kind"]
        if kind == "desktop_window":
            self._on_window(_ts(sig), sig["value"])
        elif kind == "planner_change" and sig["value"].get("action") == "complete":
            publish("transition", "backend", {"reason": "task_completed"}, subject=sig.get("subject"))
        elif kind == "message":
            with self._lock:
                self.last_active = _ts(sig)

    def _on_window(self, ts: datetime, v: dict) -> None:
        cfg = _cfg()
        window_s = float(v.get("window_s") or 15)
        idle_s = float(v.get("idle_s") or 0)
        locked = bool(v.get("locked"))
        emits: list[tuple] = []
        with self._lock:
            self.device = {"battery": v.get("on_battery"), "locked": locked}
            self.windows.append((ts, v))
            horizon = ts - timedelta(minutes=cfg["focus_minutes"])
            while self.windows and self.windows[0][0] < horizon:
                self.windows.popleft()

            # ---- idle / away
            inactive = locked or idle_s >= window_s * 0.9
            if inactive:
                if self.idle_since is None:
                    self.idle_since = ts - timedelta(seconds=idle_s or window_s)
                if not self.idle_emitted and ts - self.idle_since >= timedelta(minutes=cfg["idle_minutes"]):
                    self.idle_emitted = True
                    emits.append(("idle_start", {"locked": locked}, None))
            else:
                if self.idle_since is not None:
                    away_min = (ts - self.idle_since).total_seconds() / 60
                    if self.idle_emitted:
                        emits.append(("idle_end", {"away_minutes": round(away_min, 1)}, None))
                        if away_min >= cfg["session_gap_minutes"]:
                            emits.append(("transition", {"reason": "back_after_break",
                                                         "away_minutes": round(away_min, 1)}, None))
                self.idle_since, self.idle_emitted = None, False
                self.last_active = ts

            # ---- focus: one work category dominates, few switches, mostly active
            span_min = ((ts - self.windows[0][0]).total_seconds() + window_s) / 60 if self.windows else 0
            totals: dict[str, float] = {}
            switches = 0.0
            active = 0.0
            for _, w in self.windows:
                for cat, sec in (w.get("cat") or {}).items():
                    totals[cat] = totals.get(cat, 0.0) + float(sec)
                switches += float(w.get("switches") or 0)
                active += max(0.0, float(w.get("window_s") or 15) - float(w.get("idle_s") or 0))
            top_cat, top_s = max(totals.items(), key=lambda x: x[1]) if totals else (None, 0.0)
            in_focus = (span_min >= cfg["focus_minutes"] * 0.95 and top_cat in WORK_CATEGORIES
                        and active > 0 and top_s / max(active, 1) >= cfg["focus_share"]
                        and switches / max(span_min, 1) <= cfg["max_switches_per_min"]
                        and not inactive)
            if self.focus is not None and not inactive:
                # Staying in focus is judged on the last couple of minutes, not the whole
                # window: 4 minutes in chat after 20 in code means focus has ended.
                recent_from = ts - timedelta(minutes=cfg["focus_exit_minutes"])
                rec_tot = rec_focus = 0.0
                for wts, w in self.windows:
                    if wts >= recent_from:
                        for cat, sec in (w.get("cat") or {}).items():
                            rec_tot += float(sec)
                            if cat == self.focus["category"]:
                                rec_focus += float(sec)
                in_focus = rec_tot > 0 and rec_focus / rec_tot >= 0.5
            if in_focus:
                self.focus_candidate_off_since = None
                if self.focus is None:
                    self.focus = {"category": top_cat, "since": self.windows[0][0]}
                    emits.append(("focus_start", {"category": top_cat}, None))
            elif self.focus is not None:
                if self.focus_candidate_off_since is None:
                    self.focus_candidate_off_since = ts
                if inactive or ts - self.focus_candidate_off_since >= timedelta(minutes=cfg["focus_exit_minutes"]):
                    dur = (ts - self.focus["since"]).total_seconds() / 60
                    emits.append(("focus_end", {"category": self.focus["category"],
                                                "minutes": round(dur, 1)}, None))
                    emits.append(("transition", {"reason": "focus_ended", "minutes": round(dur, 1)}, None))
                    self.focus, self.focus_candidate_off_since = None, None
        for kind, value, subject in emits:      # publish outside the lock
            publish(kind, "backend" if kind == "transition" else "desktop", value, subject=subject)

    # ---------------- read
    def snapshot(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            last_window = self.windows[-1][0] if self.windows else None
            sensor_online = bool(last_window and now - last_window < timedelta(minutes=2))
            return {
                "sensor_online": sensor_online,
                "focus": ({"category": self.focus["category"],
                           "minutes": round((now - self.focus["since"]).total_seconds() / 60, 1)}
                          if self.focus else None),
                "away": bool(self.idle_emitted),
                "away_minutes": (round((now - self.idle_since).total_seconds() / 60, 1)
                                 if self.idle_since and self.idle_emitted else 0),
                "last_active": self.last_active.isoformat() if self.last_active else None,
                "device": dict(self.device),
            }


_TIMING = TimingState()


def get_timing() -> TimingState:
    return _TIMING


# ------------------------------------------------------------------ dissatisfaction
_DISSAT_PATTERNS = [
    (re.compile(r"^\s*(no|nope|nah)\b(?!\s+(worries|problem|prob|need|thanks|thank you|rush|issues?)\b)[,.!\s]",
                re.I), 0.35, "starts with no"),
    (re.compile(r"\b(that'?s|this is|you'?re|it'?s) (the |a )?(wrong|not right|incorrect|not what i)", re.I), 0.6, "says it's wrong"),
    (re.compile(r"\b(i meant|i said|not that|i asked (for|you))\b", re.I), 0.5, "correction"),
    (re.compile(r"\b(again|still (not|wrong|doesn'?t)|doesn'?t work|didn'?t work|useless|stop)\b", re.I), 0.3,
     "frustration word"),
    (re.compile(r"\?\?+|!!+", re.I), 0.15, "repeated punctuation"),
]
_WORD = re.compile(r"[a-z0-9]+")


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    if len(sa) < 3 or len(sb) < 3:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def dissatisfaction(text: str, previous_user_texts: list[str] | None = None) -> tuple[float, list[str]]:
    """Heuristic dissatisfaction score for one user turn (noisy by design: a hint, not a verdict)."""
    score, reasons = 0.0, []
    for rx, w, why in _DISSAT_PATTERNS:
        if rx.search(text or ""):
            score += w
            reasons.append(why)
    for prev in (previous_user_texts or [])[-3:]:
        sim = _jaccard(text or "", prev)
        if sim >= 0.6:
            score += 0.4
            reasons.append(f"repeats an earlier request ({sim:.0%} overlap)")
            break
    return min(score, 1.0), reasons


# ------------------------------------------------------------------ urgency
_URGENT_WORDS = re.compile(r"\b(urgent|asap|immediately|today|tonight|eod|by tomorrow|deadline|overdue|"
                           r"action required|reminder|final notice|important|call me)\b", re.I)
_BULK = re.compile(r"\b(newsletter|unsubscribe|digest|promo|offer|sale|jobs? alert|no-?reply|noreply)\b", re.I)


def urgency(sender: str, subject: str, snippet: str = "",
            important_senders: set[str] | None = None) -> tuple[float, list[str]]:
    s, reasons = 0.0, []
    sender_l = (sender or "").lower()
    if important_senders and any(x and x.lower() in sender_l for x in important_senders):
        s += 0.5
        reasons.append("from someone you know")
    text = f"{subject} {snippet}"
    if _URGENT_WORDS.search(text):
        s += 0.35
        reasons.append("urgent wording")
    if "?" in (subject or ""):
        s += 0.1
        reasons.append("asks a question")
    if _BULK.search(f"{sender} {text}"):
        s -= 0.6
        reasons.append("looks automated")
    return max(0.0, min(s, 1.0)), reasons


def important_senders() -> set[str]:
    """Names and e-mails of people the user knows (Planner people + graph persons)."""
    out: set[str] = set()
    try:
        from backend.core.planner_store import get_planner
        for p in get_planner().list_people():
            out.update(x for x in (p.get("email"), p.get("name")) if x)
    except Exception:
        pass
    try:
        from backend.memory.knowledge_graph import get_graph
        for n in get_graph().get_nodes_by_type("person"):
            name = (n.get("properties", {}) or {}).get("name") or n["label"].split(":", 1)[-1]
            if len(name) >= 3:
                out.add(name)
            em = (n.get("properties", {}) or {}).get("email")
            if em:
                out.add(em)
    except Exception:
        pass
    return out
