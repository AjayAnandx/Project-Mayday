"""Thread-safe JSON store for play history (music_history.json).

Pattern: same as DataStore / OperationLog / ResearchStore — file-backed,
in-memory indexes, RLock, lazy load. Each play records video_id, title,
artist, language, timestamp. History is persistent; queue is session-only.

Used by:
  - media_functions (indirectly via record_play on stream resolve)
  - api/music (REST: POST /api/music/history, GET stats/trending)
  - dashboard (top played + language mix)
"""
import json
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.core.config import load_config

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class MusicHistory:
    def __init__(self, path: Path | None = None):
        cfg = load_config()
        # allow test injection via explicit path
        if path is not None:
            self._path = Path(path)
        else:
            raw = cfg.get("music", {}).get("history_path", "music_history.json") if isinstance(cfg.get("music"), dict) else "music_history.json"
            p = Path(str(raw))
            if not p.is_absolute():
                p = Path(__file__).resolve().parent.parent.parent / p
            self._path = p
        self._lock = threading.RLock()
        self._plays: list[dict] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._plays = data
                elif isinstance(data, dict):
                    self._plays = data.get("plays", []) or data.get("history", []) or []
            except (json.JSONDecodeError, OSError):
                self._plays = []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._plays, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_play(self, track: dict) -> dict:
        """Record a play. track should have video_id, title, artist, language, thumb?.

        Returns the stored entry.
        """
        with self._lock:
            vid = (track.get("video_id") or track.get("videoId") or "").strip()
            title = (track.get("title") or "").strip() or "Unknown"
            artist = (track.get("artist") or "").strip() or "Unknown"
            language = (track.get("language") or "").strip() or "other"
            thumb = track.get("thumb") or track.get("thumbnail") or ""
            duration = track.get("duration") or ""
            entry = {
                "id": uuid.uuid4().hex[:10],
                "video_id": vid,
                "title": title,
                "artist": artist,
                "language": language,
                "thumb": thumb,
                "duration": str(duration) if duration else "",
                "played_at": _utcnow(),
                "date": _today(),
            }
            self._plays.append(entry)
            self._save()
            return entry

    def total_plays(self) -> int:
        with self._lock:
            return len(self._plays)

    def language_stats(self) -> dict[str, int]:
        with self._lock:
            c = Counter(p.get("language", "other") or "other" for p in self._plays)
            return dict(c)

    def most_played_artists(self, n: int = 10) -> list[dict]:
        with self._lock:
            c = Counter(p.get("artist", "Unknown") for p in self._plays if p.get("artist"))
            top = c.most_common(max(1, min(int(n or 10), 50)))
            return [{"artist": artist, "plays": count} for artist, count in top]

    def top_played(self, n: int = 10, language: str | None = None, days: int | None = None) -> list[dict]:
        """Most played tracks, aggregated by video_id.

        language filter: exact match on stored language (ta/hi/en/other)
        days filter: only plays within last `days` days
        Returns list of {video_id, title, artist, language, thumb, plays, last_played}
        ranked by plays desc.
        """
        with self._lock:
            n = max(1, min(int(n or 10), 100))
            lang = (language or "").strip().lower() or None
            cutoff = None
            if days is not None:
                try:
                    d = int(days)
                    if d > 0:
                        cutoff = datetime.now(timezone.utc) - timedelta(days=d)
                except (ValueError, TypeError):
                    pass

            filtered = self._plays
            if lang:
                filtered = [p for p in filtered if (p.get("language", "") or "").lower() == lang]
            if cutoff is not None:
                filtered = [p for p in filtered if _parse_dt(p.get("played_at", "")) and _parse_dt(p["played_at"]) >= cutoff]

            # aggregate by video_id (fallback title+artist)
            agg: dict[str, dict] = {}
            for p in filtered:
                key = p.get("video_id") or f"{p.get('title','')}|{p.get('artist','')}"
                if not key or key == "|":
                    continue
                if key not in agg:
                    agg[key] = {
                        "video_id": p.get("video_id", ""),
                        "title": p.get("title", "Unknown"),
                        "artist": p.get("artist", "Unknown"),
                        "language": p.get("language", "other"),
                        "thumb": p.get("thumb", ""),
                        "plays": 0,
                        "last_played": p.get("played_at", ""),
                    }
                agg[key]["plays"] += 1
                # keep latest last_played and thumb
                if p.get("played_at", "") > agg[key]["last_played"]:
                    agg[key]["last_played"] = p["played_at"]
                    if p.get("thumb"):
                        agg[key]["thumb"] = p["thumb"]

            ranked = sorted(agg.values(), key=lambda x: (x["plays"], x["last_played"]), reverse=True)
            return ranked[:n]

    def recent(self, n: int = 20) -> list[dict]:
        with self._lock:
            n = max(1, min(int(n or 20), 100))
            return list(reversed(self._plays[-n:]))

    def clear(self):
        """Test helper — wipe history."""
        with self._lock:
            self._plays = []
            self._save()


def _parse_dt(s: str):
    if not s:
        return None
    try:
        # isoformat with Z or +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


_instance: MusicHistory | None = None
_lock = threading.Lock()

def get_music_history(path: Path | None = None) -> MusicHistory:
    global _instance
    if path is not None:
        # test injection — bypass singleton
        return MusicHistory(path=path)
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MusicHistory()
    return _instance
