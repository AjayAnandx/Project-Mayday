"""Brain V3 P8: sensory layer. One store and one bus for every signal Mayday perceives.

    publish(kind, source, value, subject=None, sensitivity="normal")
        non-blocking; rows are buffered and written every few seconds by a background
        thread (the chat path never waits on the database). Subscribers are called inline.
    subscribe(fn)            fn(signal: dict) for every published signal (working memory, timing, …)
    recent(kind, minutes)    read back recent signals
    prune(now)               retention: raw rows older than brain.sensors.retention_days are
                             rolled into signal_stats (hourly counts/sums) and deleted
    collectors_status()      last time each collector reported (for "sensor offline")

Privacy is enforced here, at the single entry point (sanitize):
  * keys that could carry window titles, URLs, raw text or coordinates are dropped
  * string values are length-capped and redacted (phone numbers, e-mail addresses)
  * a kind must be in KINDS; unknown kinds are rejected
  * brain.sensors.pause / per-collector toggles stop collection entirely
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from backend.core.config import load_config
from backend.memory.sensitivity import redact

logger = logging.getLogger(__name__)

# kind -> collector toggle that must be on for it to be accepted
KINDS: dict[str, str] = {
    # explicit
    "message": "backend", "planner_change": "backend", "suggestion_feedback": "ui",
    # implicit / behavioural
    "desktop_window": "desktop",       # 15 s aggregate: category seconds, switches, idle, locked
    "focus_start": "desktop", "focus_end": "desktop",
    "idle_start": "desktop", "idle_end": "desktop",
    "transition": "backend",           # natural break detected (session start, focus ended, …)
    "response_latency": "ui", "ui_visibility": "ui", "ui_dismiss": "ui", "ui_edit": "ui",
    "dissatisfaction": "backend",
    # environmental / temporal
    "device_state": "desktop", "location_place": "location", "traffic_delay": "backend",
    "urgent_message": "backend", "weather_change": "backend",
}

_FORBIDDEN_KEYS = {"title", "window_title", "url", "path", "text", "content", "body", "lat", "lon",
                   "latitude", "longitude", "coords", "address", "email", "phone"}
_MAX_STR = 120

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
    subject TEXT, value TEXT NOT NULL DEFAULT '{}', sensitivity TEXT NOT NULL DEFAULT 'normal');
CREATE INDEX IF NOT EXISTS idx_signals_kind_ts ON signals(kind, ts);
CREATE TABLE IF NOT EXISTS signal_stats (
    hour TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    sums TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (hour, kind));
"""


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("sensors", {}) or {}
    return {"enabled": bool(c.get("enabled", True)), "pause": bool(c.get("pause", False)),
            "desktop": bool(c.get("desktop", True)), "ui": bool(c.get("ui", True)),
            "location": bool(c.get("location", False)), "backend": True,
            "retention_days": int(c.get("retention_days", 14)),
            "flush_seconds": float(c.get("flush_seconds", 5.0))}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize(value: dict) -> dict:
    """Drop privacy-risky keys, cap and redact strings, keep numbers/bools/small dicts."""
    out = {}
    for k, v in (value or {}).items():
        key = str(k)[:40]
        if key.lower() in _FORBIDDEN_KEYS:
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)) or v is None:
            out[key] = v
        elif isinstance(v, str):
            out[key] = redact(v)[:_MAX_STR]
        elif isinstance(v, dict):
            out[key] = {str(a)[:40]: b for a, b in list(v.items())[:20]
                        if str(a).lower() not in _FORBIDDEN_KEYS and isinstance(b, (int, float, bool))}
        elif isinstance(v, list):
            out[key] = [x if isinstance(x, (int, float, bool)) else redact(str(x))[:_MAX_STR]
                        for x in v[:20]]
    return out


class SignalBus:
    def __init__(self):
        self._buf: list[tuple] = []
        self._lock = threading.Lock()
        self._subs: list[Callable[[dict], None]] = []
        self._last_seen: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._schema_ready_for: int | None = None

    # ---------------- store
    def _store(self):
        from backend.memory.knowledge_graph import get_graph
        store = get_graph()._store
        if store is not None and self._schema_ready_for != id(store):
            with store._lock:
                store._conn.executescript(_SCHEMA)
            self._schema_ready_for = id(store)
        return store

    # ---------------- publish / subscribe
    def subscribe(self, fn: Callable[[dict], None]) -> None:
        if fn not in self._subs:
            self._subs.append(fn)

    def publish(self, kind: str, source: str, value: dict | None = None, subject: str | None = None,
                sensitivity: str = "normal", ts: str | None = None) -> dict | None:
        cfg = _cfg()
        if not cfg["enabled"] or cfg["pause"]:
            return None
        collector = KINDS.get(kind)
        if collector is None:
            logger.debug("signal kind %r rejected", kind)
            return None
        if not cfg.get(collector, True):
            return None
        sig = {"ts": ts or _now_iso(), "kind": kind, "source": source[:20],
               "subject": (str(subject)[:60] if subject else None),
               "value": sanitize(value or {}), "sensitivity": sensitivity}
        with self._lock:
            self._buf.append((sig["ts"], kind, sig["source"], sig["subject"],
                              json.dumps(sig["value"], ensure_ascii=False), sensitivity))
            self._last_seen[collector] = sig["ts"]
        for fn in list(self._subs):
            try:
                fn(sig)
            except Exception as e:     # a bad subscriber never breaks sensing
                logger.warning("signal subscriber %s failed: %s", getattr(fn, "__name__", fn), e)
        self._ensure_writer()
        return sig

    # ---------------- writer
    def _ensure_writer(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="brain-signals")
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self._stop.wait(_cfg()["flush_seconds"])
            try:
                self.flush()
            except Exception as e:
                logger.warning("signal flush failed: %s", e)

    def flush(self) -> int:
        with self._lock:
            rows, self._buf = self._buf, []
        if not rows:
            return 0
        store = self._store()
        if store is None:
            return 0
        with store._lock:
            store._conn.executemany(
                "INSERT INTO signals(ts, kind, source, subject, value, sensitivity) VALUES (?,?,?,?,?,?)", rows)
        return len(rows)

    # ---------------- read
    def recent(self, kind: str | None = None, minutes: int = 60, limit: int = 500) -> list[dict]:
        self.flush()
        store = self._store()
        if store is None:
            return []
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        if kind:
            rows = store._rows("SELECT * FROM signals WHERE kind=? AND ts>=? ORDER BY id DESC LIMIT ?",
                               (kind, since, limit))
        else:
            rows = store._rows("SELECT * FROM signals WHERE ts>=? ORDER BY id DESC LIMIT ?", (since, limit))
        for r in rows:
            r["value"] = json.loads(r["value"] or "{}")
        return rows

    def collectors_status(self) -> dict:
        store = self._store()
        last = dict(self._last_seen)
        if store is not None:
            for coll in set(KINDS.values()):
                kinds = [k for k, c in KINDS.items() if c == coll]
                marks = ",".join("?" for _ in kinds)
                row = store._rows(f"SELECT MAX(ts) AS t FROM signals WHERE kind IN ({marks})", tuple(kinds))
                t = row[0]["t"] if row else None
                if t and (coll not in last or t > last[coll]):
                    last[coll] = t
        cfg = _cfg()
        now = datetime.now(timezone.utc)
        out = {}
        for coll in ("backend", "desktop", "ui", "location"):
            t = last.get(coll)
            age = (now - datetime.fromisoformat(t)).total_seconds() if t else None
            out[coll] = {"enabled": cfg.get(coll, True) and not cfg["pause"], "last_seen": t,
                         "online": age is not None and age < (120 if coll == "desktop" else 86400)}
        return out

    # ---------------- retention
    def prune(self, now: datetime | None = None) -> dict:
        """Roll raw rows older than retention into hourly stats, then delete them."""
        self.flush()
        store = self._store()
        if store is None:
            return {}
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=_cfg()["retention_days"])).isoformat()
        rows = store._rows("SELECT ts, kind, value FROM signals WHERE ts < ?", (cutoff,))
        agg: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "sums": defaultdict(float)})
        for r in rows:
            a = agg[(r["ts"][:13], r["kind"])]
            a["n"] += 1
            for k, v in json.loads(r["value"] or "{}").items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    a["sums"][k] += v
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, (int, float)):
                            a["sums"][f"{k}.{k2}"] += v2
        with store._lock:
            for (hour, kind), a in agg.items():
                old = store._rows("SELECT n, sums FROM signal_stats WHERE hour=? AND kind=?", (hour, kind))
                sums = defaultdict(float, json.loads(old[0]["sums"]) if old else {})
                for k, v in a["sums"].items():
                    sums[k] += v
                store._conn.execute("INSERT OR REPLACE INTO signal_stats(hour, kind, n, sums) VALUES (?,?,?,?)",
                                    (hour, kind, (old[0]["n"] if old else 0) + a["n"], json.dumps(sums)))
            deleted = store._conn.execute("DELETE FROM signals WHERE ts < ?", (cutoff,)).rowcount
        return {"rolled_up": len(rows), "deleted": deleted or 0, "hours": len(agg)}


_BUS = SignalBus()


def get_bus() -> SignalBus:
    return _BUS


def publish(kind: str, source: str, value: dict | None = None, **kw) -> dict | None:
    try:
        return _BUS.publish(kind, source, value, **kw)
    except Exception as e:
        logger.debug("publish failed: %s", e)
        return None
