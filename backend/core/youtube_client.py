"""YouTube Music client via ytmusicapi + yt-dlp.

Thin wrapper around ytmusicapi for search/radio/moods/charts and yt-dlp for
progressive stream URL resolution. Gracefully degrades when libs are missing
or Google is unreachable — callers get human-readable errors, never crashes.

Pattern: same lazy singleton + thread-safe store as data_store.py / search_index.py
"""
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from backend.core.config import load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language detection — shared with music_history
# ---------------------------------------------------------------------------

# Script ranges
_TAMIL_RE = re.compile(r"[\u0b80-\u0bff]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")
_LATIN_RE = re.compile(r"[a-zA-Z]")

# Romanized Tamil artist/title tokens — cheap heuristic for titles that are
# transliterated (no Tamil script). Curated from common Tamil artists.
_ROMANIZED_TAMIL_TOKENS = frozenset({
    "anirudh", "ilaiyaraaja", "arrahman", "arr", "rahman", "spb", "sp balasubrahmanyam",
    "sid sriram", "sidsriram", "harris jayaraj", "harris", "yuvan", "yuvan shankar",
    "gv prakash", "dhanush", "vijay", "ajith", "sivakarthikeyan", "pradeep",
    "aniruth", "thaman", "devi sri", "dsp", "santhosh narayanan", "santhosh",
    "arre", "tamil", "kollywood", "chennai", "madurai",
    "vijay antony", "karunakaran", "hiphop tamizha", "imman", "d imman",
    "shreya ghoshal", "shreya", "hariharan", "haricharan", "chinmayi",
    "swetha mohan", "sujatha", "mano", "unnikrishnan", "p susheela",
    # romanized title words that are Tamil-specific
    "kannamma", "kanamma", "kadhal", "kaadhal", "naan", "nee", "enna", "enga",
    "vaa", "po", "poda", "di", "da", "machan", "thala", "thalapathy",
})

# Video/tutorial intent — broader than old _tutorial_kw so "engineering fact latest video" routes to yt-dlp not ytmusicapi (song filter)
_VIDEO_QUERY_KEYWORDS = frozenset({
    "tutorial","how to","explained","course","lecture","evaluation","benchmark","llm","rag","transformer","attention",
    "engineering","engineer","fact","facts","science","technology","tech","research","study","studies","analysis","review","news","documentary",
    "latest","newest","recent","video","videos","explain","howto","guide","walkthrough","deep dive","overview","introduction","intro",
})

# Cache for faster lookups — pre-lowercased tokens
_ROMANIZED_TAMIL_LOWER = frozenset(t.lower() for t in _ROMANIZED_TAMIL_TOKENS)


def detect_language(title: str, artist: str = "") -> str:
    """Heuristic language tag: ta / hi / en / other.

    - Tamil script → ta
    - Devanagari → hi
    - Otherwise check romanized Tamil artist/title tokens → ta
    - Latin → en
    - Fallback → other
    """
    combined = f"{title} {artist}"
    if _TAMIL_RE.search(combined):
        return "ta"
    if _DEVANAGARI_RE.search(combined):
        return "hi"
    # romanized Tamil check — token overlap
    lc = combined.lower()
    for tok in _ROMANIZED_TAMIL_LOWER:
        if tok in lc:
            return "ta"
    if _LATIN_RE.search(combined):
        return "en"
    return "other"


def _normalize_track(raw: dict) -> dict:
    """Convert ytmusicapi / chart item into canonical MusicTrack dict."""
    video_id = raw.get("videoId") or raw.get("video_id") or raw.get("id") or ""
    title = raw.get("title", "") or raw.get("name", "") or ""
    # artists can be list[dict] or str
    artists = raw.get("artists") or raw.get("artist") or []
    if isinstance(artists, list):
        # limit to 2 artists for display
        names = []
        for a in artists[:2]:
            if isinstance(a, dict):
                names.append(a.get("name", ""))
            elif isinstance(a, str):
                names.append(a)
        artist_str = ", ".join(n for n in names if n)
    elif isinstance(artists, str):
        artist_str = artists
    else:
        artist_str = str(artists) if artists else ""

    # thumbnail — ytmusicapi returns thumbnails: [{url, width, height}]
    thumb = ""
    for key in ("thumbnails", "thumbnail", "thumbnails_small"):
        val = raw.get(key)
        if isinstance(val, list) and val:
            # prefer largest
            thumb = val[-1].get("url", "") if isinstance(val[-1], dict) else str(val[-1])
            if thumb:
                break
        elif isinstance(val, str) and val:
            thumb = val
            break
    if not thumb:
        # chart fallback
        thumb = raw.get("image") or raw.get("cover") or ""

    duration = raw.get("duration") or raw.get("duration_seconds") or ""
    # duration may be "3:45" string — keep as-is
    if isinstance(duration, int):
        m, s = divmod(duration, 60)
        duration = f"{m}:{s:02d}"

    language = detect_language(title, artist_str)
    # optional genre/mood passthrough (set by callers like play_mood)
    genre = raw.get("genre") or raw.get("mood") or ""
    mood_id = raw.get("mood_id") or raw.get("moodId") or raw.get("mood") or genre

    return {
        "video_id": video_id,
        "title": title.strip() or "Unknown",
        "artist": artist_str.strip() or "Unknown",
        "thumb": thumb,
        "duration": str(duration) if duration else "",
        "language": language,
        "genre": genre,
        "mood": genre,
        "mood_id": mood_id,
    }


# ---------------------------------------------------------------------------
# ytmusicapi singleton
# ---------------------------------------------------------------------------

_ytm = None
_ytm_error: str | None = None


def _get_ytm():
    global _ytm, _ytm_error
    if _ytm is not None:
        return _ytm
    if _ytm_error is not None and "not installed" in _ytm_error:
        return None
    try:
        from ytmusicapi import YTMusic  # type: ignore
        _ytm = YTMusic()
        logger.info("YTMusic initialized")
        return _ytm
    except ImportError as e:
        _ytm_error = f"ytmusicapi not installed: {e}"
        logger.warning(_ytm_error)
        return None
    except Exception as e:
        _ytm_error = f"YTMusic init failed: {e}"
        logger.warning(_ytm_error)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_song(artist: str = "", track: str = "", query: str = "", max_results: int = 3) -> dict:
    """Search YouTube Music for songs.

    Accepts artist+track or a free-form query. Returns {tracks: [...], error?}
    """
    ytm = _get_ytm()
    if ytm is None:
        return {"tracks": [], "error": _ytm_error or "ytmusicapi unavailable"}

    q = query.strip() if query else f"{artist.strip()} {track.strip()}".strip()
    if not q:
        return {"tracks": [], "error": "Missing artist/track/query"}
    q = q.strip()
    max_results = max(1, min(int(max_results or 3), 10))

    try:
        results = ytm.search(q, filter="songs", limit=max_results)
    except Exception as e:
        # fallback without filter
        try:
            results = ytm.search(q, limit=max_results)
            # keep only songs (has videoId + title)
            results = [r for r in results if r.get("videoId")] [:max_results]
        except Exception as e2:
            logger.warning("ytmusicapi search failed for %r: %s / %s", q, e, e2)
            return {"tracks": [], "error": f"Search failed: {e2}"}

    tracks = []
    for r in results or []:
        if not r.get("videoId"):
            continue
        tracks.append(_normalize_track(r))
        if len(tracks) >= max_results:
            break

    if not tracks:
        # include raw titles in error for debugging
        sample = ", ".join((r.get("title") or r.get("name") or "") for r in (results or [])[:3])
        return {"tracks": [], "error": f"No songs found for '{q}'" + (f" (closest: {sample})" if sample else "")}

    return {"tracks": tracks}


# Progressive first (spec ~480p mini window, capped 720p), then any progressive, then audio-only fallback (accepted per user).
_FORMAT_CHAIN = [
    "best[ext=mp4][height<=720]/best[height<=720]/best",
    "best",
    "bestaudio[ext=m4a]/bestaudio/bestaudio[ext=webm]",
]


def _clean_ytdlp_error(text: str) -> str:
    """Strip WARNING lines, keep last ERROR line for a clean user message."""
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Keep last ERROR: line if present (yt-dlp prefixes with ERROR:)
    errors = [ln for ln in lines if ln.lstrip().startswith("ERROR:")]
    if errors:
        # Strip leading "ERROR: [youtube] ..." prefix fuzzily
        last = errors[-1]
        # Remove "ERROR:" prefix and optional "[extractor]" tag
        last = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?", "", last).strip()
        return last
    # Fallback: drop WARNING: lines and return last meaningful line
    filtered = [ln for ln in lines if not ln.lstrip().startswith("WARNING:")]
    if filtered:
        return filtered[-1]
    return lines[-1] if lines else ""


def _is_rate_limited(msg: str) -> bool:
    low = msg.lower()
    return (
        "429" in msg
        or "too many requests" in low
        or "sign in to confirm" in low
        or "confirm you're not a bot" in low
        or "nsig extraction failed" in low
        or "http error 403" in low
        or "video unavailable" in low  # sometimes shown as rate-limit shadow
    )


def resolve_stream(video_id: str) -> dict:
    """Resolve a YouTube videoId to a stream URL via yt-dlp.

    Tries a format chain: progressive 720p-capped → any progressive → audio-only
    (audio-only accepted per user). Uses --no-warnings + android player client
    to bypass nsig / bot checks. Retries with backoff. Optional cookies file
    from config.yaml music.cookies_file.

    Returns {stream_url: str, video_id, is_audio_only?: bool} or {error: str}
    """
    if not video_id or not video_id.strip():
        return {"error": "Missing video_id"}
    vid = video_id.strip()

    cfg = load_config()
    cookies_file = (cfg.get("music", {}) or {}).get("cookies_file", "") or ""
    cookies_file = cookies_file.strip() if isinstance(cookies_file, str) else ""

    cookies_args: list[str] = []
    if cookies_file:
        cf = os.path.expanduser(cookies_file)
        if os.path.isfile(cf):
            cookies_args = ["--cookies", cf]
        else:
            logger.warning("music.cookies_file not found: %s", cf)

    # Use android client first (bypasses many po_token / nsig failures) then web fallback.
    # --no-warnings hides the noisy "-f best selects pre-merged" warning that previously polluted error[:500].
    url = f"https://www.youtube.com/watch?v={vid}"
    last_err = ""
    last_is_audio_only = False

    for fmt in _FORMAT_CHAIN:
        is_audio_only = fmt.startswith("bestaudio")
        # Build command per format attempt
        base_cmd = [
            "python", "-m", "yt_dlp",
            "--no-warnings",
            "--no-playlist",
            "--extractor-args", "youtube:player_client=android,web",
            "-f", fmt,
            "-g",
        ] + cookies_args

        for attempt in range(2):  # 2 tries per format (light backoff)
            try:
                cmd = base_cmd + [url]
                logger.info("yt-dlp resolve fmt=%r attempt %d for %s", fmt, attempt + 1, vid)
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if proc.returncode == 0:
                    out = (proc.stdout or "").strip().splitlines()
                    http_lines = [ln.strip() for ln in out if ln.strip().startswith("http")]
                    if not http_lines:
                        last_err = "yt-dlp returned no URL"
                        # try next format / retry
                    else:
                        # -g for progressive/audio-only returns single URL; if somehow 2 (bv+ba) pick audio (second) as fallback
                        stream_url = http_lines[0]
                        if len(http_lines) > 1:
                            # DASH split occurred despite progressive fmt — log and pick first
                            logger.warning("yt-dlp returned %d URLs for fmt %r, using first", len(http_lines), fmt)
                        result: dict = {"stream_url": stream_url, "video_id": vid}
                        if is_audio_only:
                            result["is_audio_only"] = True
                        return result
                else:
                    raw = (proc.stderr or proc.stdout or "").strip()
                    cleaned = _clean_ytdlp_error(raw)
                    last_err = cleaned or f"yt-dlp exit {proc.returncode}"
                    last_is_audio_only = is_audio_only
                    if _is_rate_limited(raw) or _is_rate_limited(last_err):
                        last_err += " — try adding a cookies.txt via config.yaml music.cookies_file (or run pip install -U yt-dlp)"
            except FileNotFoundError:
                return {"error": "yt-dlp not installed (pip install yt-dlp)"}
            except subprocess.TimeoutExpired:
                last_err = "yt-dlp timed out (15s)"
                last_is_audio_only = is_audio_only
            except Exception as e:
                last_err = str(e)
                last_is_audio_only = is_audio_only

            if attempt < 1:
                time.sleep(0.6 * (attempt + 1))

        # If progressive 720p failed, fall through to next fmt in chain silently;
        # only sleep gap between formats on real failure
        if fmt != _FORMAT_CHAIN[-1]:
            # Brief gap before next format to avoid hammering
            time.sleep(0.3)

    # Exhausted chain — surface clean error
    hint = ""
    if last_is_audio_only:
        hint = " (also tried audio-only fallback)"
    return {"error": f"Could not resolve stream for {vid}{hint}: {last_err[:400]}"}


def get_radio(seed_id: str, n: int = 20) -> dict:
    """Get radio mix for a seed videoId via get_watch_playlist.

    Returns {tracks: [...]} or {error: str}
    """
    if not seed_id or not seed_id.strip():
        return {"tracks": [], "error": "Missing seed video_id"}
    ytm = _get_ytm()
    if ytm is None:
        return {"tracks": [], "error": _ytm_error or "ytmusicapi unavailable"}
    n = max(1, min(int(n or 20), 50))
    try:
        # ytmusicapi get_watch_playlist returns {tracks, playlistId, ...}
        data = ytm.get_watch_playlist(videoId=seed_id.strip(), limit=n)
        raw_tracks = data.get("tracks") or data.get("related") or []
        # get_watch_playlist tracks already have videoId/title/artists
        tracks = []
        for r in raw_tracks[:n]:
            if not r.get("videoId"):
                continue
            tracks.append(_normalize_track(r))
        if not tracks:
            return {"tracks": [], "error": f"No radio tracks for seed {seed_id}"}
        return {"tracks": tracks}
    except Exception as e:
        logger.warning("get_radio failed for %s: %s", seed_id, e)
        return {"tracks": [], "error": f"Radio failed: {e}"}


def get_moods() -> dict:
    """Return mood/genre catalog from get_mood_categories.

    Returns {moods: [{id, title}]} or {error: str}
    """
    ytm = _get_ytm()
    if ytm is None:
        return {"moods": [], "error": _ytm_error or "ytmusicapi unavailable"}
    try:
        cats = ytm.get_mood_categories()
        # structure: {"Moods & moments": [{title, params}, ...], "Genres": [...]}
        moods = []
        if isinstance(cats, dict):
            for group, items in cats.items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    title = it.get("title", "") or it.get("name", "")
                    params = it.get("params", "") or it.get("browseId", "") or title
                    if title:
                        moods.append({"id": params, "title": title, "group": group})
        elif isinstance(cats, list):
            for it in cats:
                title = it.get("title", "") or it.get("name", "")
                params = it.get("params", "") or it.get("browseId", "") or title
                if title:
                    moods.append({"id": params, "title": title, "group": ""})
        if not moods:
            return {"moods": [], "error": "No moods found"}
        return {"moods": moods}
    except Exception as e:
        logger.warning("get_moods failed: %s", e)
        return {"moods": [], "error": f"Mood catalog failed: {e}"}


def get_mood_tracks(mood_id: str, n: int = 20) -> dict:
    """Get tracks for a mood/genre via get_mood_playlists.

    Returns {tracks: [...]} or {error: str}
    """
    if not mood_id or not mood_id.strip():
        return {"tracks": [], "error": "Missing mood id"}
    ytm = _get_ytm()
    if ytm is None:
        return {"tracks": [], "error": _ytm_error or "ytmusicapi unavailable"}
    mid = mood_id.strip()
    n = max(1, min(int(n or 20), 50))
    try:
        # get_mood_playlists expects a params string from get_mood_categories
        playlists = ytm.get_mood_playlists(mid)
        if not playlists:
            return {"tracks": [], "error": f"No playlists for mood '{mid}'"}
        # take first playlist
        first = playlists[0] if isinstance(playlists, list) else playlists
        pid = first.get("playlistId") or first.get("browseId") or first.get("id") or ""
        title = first.get("title", "") or mid
        if pid:
            try:
                pl = ytm.get_playlist(pid, limit=n)
                raw_tracks = pl.get("tracks") or []
                tracks = []
                for r in raw_tracks[:n]:
                    if not r.get("videoId"):
                        continue
                    tr = _normalize_track(r)
                    # attach mood context so frontend can continue same genre
                    tr["genre"] = mid
                    tr["mood"] = mid
                    tr["mood_id"] = mid
                    tracks.append(tr)
                if tracks:
                    return {"tracks": tracks, "playlist_title": title, "playlist_id": pid}
            except Exception as e:
                logger.warning("get_playlist %s failed: %s", pid, e)
        # fallback: return playlist metadata as pseudo-tracks
        tracks = []
        for p in (playlists if isinstance(playlists, list) else [playlists])[:n]:
            if p.get("title"):
                tracks.append({"video_id": p.get("playlistId", ""), "title": p.get("title", ""), "artist": "Playlist", "thumb": (p.get("thumbnails") or [{}])[-1].get("url", "") if p.get("thumbnails") else "", "language": "other", "duration": "", "genre": mid, "mood": mid, "mood_id": mid})
        if tracks:
            return {"tracks": tracks, "playlist_title": title, "playlist_id": pid}
        return {"tracks": [], "error": f"Could not load mood '{mid}'"}
    except Exception as e:
        logger.warning("get_mood_tracks failed for %r: %s", mid, e)
        return {"tracks": [], "error": f"Mood tracks failed: {e}"}


def get_chart_trending(country: str = "IN", n: int = 15) -> dict:
    """Get trending / top charts via get_charts.

    Returns {tracks: [...]} or {error: str}
    """
    ytm = _get_ytm()
    if ytm is None:
        return {"tracks": [], "error": _ytm_error or "ytmusicapi unavailable"}
    n = max(1, min(int(n or 15), 50))
    country = (country or "IN").strip().upper() or "IN"
    try:
        charts = ytm.get_charts(country=country)
        # structure varies: {"videos": {"items": [...]}, "trending": {"videos": ...}, etc.}
        candidates = []
        if isinstance(charts, dict):
            # try common keys
            for key in ("videos", "trending", "songs", "artists"):
                val = charts.get(key)
                if isinstance(val, dict) and "items" in val:
                    candidates.extend(val["items"])
                elif isinstance(val, list):
                    candidates.extend(val)
            # fallback: any list of items with videoId/trending
            if not candidates:
                for v in charts.values():
                    if isinstance(v, dict) and "items" in v and isinstance(v["items"], list):
                        candidates.extend(v["items"])
                    elif isinstance(v, list) and v and isinstance(v[0], dict):
                        candidates.extend(v)
        elif isinstance(charts, list):
            candidates = charts

        tracks = []
        seen = set()
        for r in candidates:
            if not isinstance(r, dict):
                continue
            # chart items may nest under 'video' / 'song'
            item = r.get("video") or r.get("song") or r
            vid = item.get("videoId") or item.get("id") or r.get("videoId") or r.get("id") or ""
            if not vid or vid in seen:
                continue
            # normalize: chart items sometimes have 'title' + 'artists' at top level
            norm = _normalize_track(item if item.get("title") else r)
            if not norm.get("video_id"):
                norm["video_id"] = vid
                norm["language"] = detect_language(norm.get("title", ""), norm.get("artist", ""))
            if norm.get("video_id") and norm["video_id"] not in seen:
                seen.add(norm["video_id"])
                tracks.append(norm)
            if len(tracks) >= n:
                break

        if not tracks:
            return {"tracks": [], "error": f"No trending tracks for country {country}"}
        return {"tracks": tracks[:n], "country": country}
    except Exception as e:
        logger.warning("get_chart_trending failed for %s: %s", country, e)
        return {"tracks": [], "error": f"Charts failed: {e}"}


# ---------------------------------------------------------------------------
# Advanced search with yt-dlp enrichment (view_count / likes / upload_date)
# ---------------------------------------------------------------------------

def _yt_dlp_search(query: str, max_results: int) -> dict:
    """Use yt-dlp flat search to get rich metadata (view_count, like_count, timestamp).

    Returns {tracks: [...]} where each track has extra keys: view_count, like_count,
    timestamp (unix), upload_date (YYYYMMDD), channel, channel_id, duration.
    Falls back to empty on failure.
    """
    max_results = max(1, min(int(max_results or 10), 30))
    q = query.strip()
    if not q:
        return {"tracks": []}
    # ytsearch prefix — flat playlist avoids downloading, fast
    search_url = f"ytsearch{max_results}:{q}"
    cmd = [
        "python", "-m", "yt_dlp",
        "--dump-single-json",
        "--flat-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=android,web",
        search_url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if proc.returncode != 0:
            logger.warning("_yt_dlp_search failed for %r: %s", q, _clean_ytdlp_error(proc.stderr or proc.stdout))
            return {"tracks": []}
        import json as _json
        data = _json.loads(proc.stdout or "{}")
        entries = data.get("entries") or []
        tracks = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            vid = e.get("id") or e.get("url") or ""
            if not vid or len(vid) < 5:
                continue
            # title
            title = e.get("title") or ""
            # uploader -> artist
            artist = e.get("uploader") or e.get("channel") or e.get("uploader_id") or "Unknown"
            thumb = ""
            ths = e.get("thumbnails")
            if isinstance(ths, list) and ths:
                thumb = ths[-1].get("url", "") if isinstance(ths[-1], dict) else ""
            if not thumb and e.get("thumbnail"):
                thumb = e.get("thumbnail", "")
            duration = e.get("duration") or e.get("duration_string") or ""
            if isinstance(duration, (int, float)):
                m, s = divmod(int(duration), 60)
                duration = f"{m}:{s:02d}"
            language = detect_language(title, artist)
            tr: dict[str, Any] = {
                "video_id": vid,
                "title": title or "Unknown",
                "artist": artist,
                "thumb": thumb,
                "duration": str(duration) if duration else "",
                "language": language,
                "view_count": e.get("view_count"),
                "like_count": e.get("like_count"),
                "channel": e.get("channel") or artist,
                "channel_id": e.get("channel_id") or e.get("uploader_id") or "",
                "timestamp": e.get("timestamp"),
                "upload_date": e.get("upload_date") or "",
            }
            tracks.append(tr)
        return {"tracks": tracks}
    except subprocess.TimeoutExpired:
        logger.warning("_yt_dlp_search timed out for %r", q)
        return {"tracks": []}
    except Exception as e:
        logger.warning("_yt_dlp_search exception for %r: %s", q, e)
        return {"tracks": []}


def search_advanced(
    query: str = "",
    max_results: int = 15,
    sort_by: str = "relevance",
    time_filter: str = "any",
) -> dict:
    """Advanced YouTube search with sorting and time filtering.

    sort_by: relevance | view_count | rating | upload_date
    time_filter: any | today | week | month | year  (filters by upload recency)
    Returns {tracks: [...], query, sort_by, time_filter} or {error}
    """
    q = (query or "").strip()
    if not q:
        return {"tracks": [], "error": "Missing query"}
    max_results = max(1, min(int(max_results or 15), 30))
    sort_by = (sort_by or "relevance").strip().lower()
    if sort_by not in ("relevance", "view_count", "rating", "upload_date", "views", "likes", "newest"):
        sort_by = "relevance"
    # aliases
    if sort_by == "views":
        sort_by = "view_count"
    if sort_by in ("likes", "rating"):
        sort_by = "rating"
    if sort_by == "newest":
        sort_by = "upload_date"
    time_filter = (time_filter or "any").strip().lower()
    if time_filter not in ("any", "today", "week", "month", "year"):
        time_filter = "any"

    # Bug fix: ytmusicapi filter="songs" was used for relevance+any, so queries like "engineering fact latest video"
    # (which don't set sort/time) returned weird music results. Detect video/tutorial intent and force yt-dlp.
    _ql = q.lower()
    _is_video_query = any(kw in _ql for kw in _VIDEO_QUERY_KEYWORDS)
    # also treat explicit "latest"/"newest"/"recent" as video recency intent -> force enriched path
    if any(w in _ql for w in ("latest","newest","recent")) and sort_by == "relevance" and time_filter == "any":
        # auto-upgrade to upload_date so latest actually sorts newest; LLM may have missed sort param
        sort_by = "upload_date"
        time_filter = "any"  # keep any, ranking will handle recency via timestamp sort
    need_enrich = sort_by != "relevance" or time_filter != "any" or _is_video_query
    if not need_enrich:
        # Use ytmusicapi fast path (max 15) — songs-only; safe only for pure music queries
        base = search_song(query=q, max_results=max_results)
        if base.get("tracks"):
            # add placeholder counts so caller can sort uniformly
            for t in base["tracks"]:
                t.setdefault("view_count", None)
                t.setdefault("like_count", None)
                t.setdefault("timestamp", None)
                t.setdefault("upload_date", "")
                t.setdefault("channel", t.get("artist", ""))
                t.setdefault("channel_id", "")
            return {"tracks": base["tracks"], "query": q, "sort_by": sort_by, "time_filter": time_filter}
        # fallback to yt-dlp if ytmusicapi returned nothing
        need_enrich = True

    # Enriched path via yt-dlp (already sorted by relevance by default, we resort)
    res = _yt_dlp_search(q, max_results * 2 if time_filter != "any" else max_results)
    tracks = res.get("tracks") or []
    if not tracks:
        # fallback to ytmusicapi if yt-dlp gave nothing
        base = search_song(query=q, max_results=max_results)
        tracks = base.get("tracks") or []
        if not tracks:
            return {"tracks": [], "error": base.get("error") or "No results", "query": q}
        for t in tracks:
            t.setdefault("view_count", None)
            t.setdefault("like_count", None)
            t.setdefault("timestamp", None)
            t.setdefault("upload_date", "")
        return {"tracks": tracks[:max_results], "query": q, "sort_by": sort_by, "time_filter": time_filter}

    # time filter
    if time_filter != "any":
        import time as _time
        now_ts = int(_time.time())
        cutoff_map = {"today": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
        cutoff = cutoff_map.get(time_filter, 0)
        if cutoff:
            filtered = []
            for t in tracks:
                ts = t.get("timestamp")
                if ts is not None:
                    try:
                        ts_int = int(ts)
                        if now_ts - ts_int <= cutoff:
                            filtered.append(t)
                    except (ValueError, TypeError):
                        filtered.append(t)
                else:
                    # no timestamp — keep but deprioritize (append at end)
                    filtered.append(t)
            # if filter eliminated everything, keep original but mark?
            if filtered:
                tracks = filtered

    # sort
    if sort_by == "view_count":
        tracks.sort(key=lambda x: (x.get("view_count") or 0), reverse=True)
    elif sort_by == "rating":
        # like_count proxy for rating; fallback view_count
        tracks.sort(key=lambda x: (x.get("like_count") or x.get("view_count") or 0), reverse=True)
    elif sort_by == "upload_date":
        tracks.sort(key=lambda x: (x.get("timestamp") or 0), reverse=True)

    return {"tracks": tracks[:max_results], "query": q, "sort_by": sort_by, "time_filter": time_filter}


def enrich_tracks(tracks: list[dict], max_enrich: int = 3) -> list[dict]:
    """Enrich up to max_enrich tracks with description/tags via yt-dlp --dump-json.

    Mutates tracks in-place (adds description, tags, categories) and returns same list.
    Best-effort — failures are ignored, original fields kept.
    Batch is sequential for simplicity; max_enrich keeps latency bounded (~3*4s).
    """
    if not tracks:
        return tracks
    enrich_n = max(0, min(int(max_enrich or 3), len(tracks)))
    for idx in range(enrich_n):
        t = tracks[idx]
        vid = (t.get("video_id") or "").strip()
        if not vid:
            continue
        # skip if already has description
        if t.get("description"):
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        cmd = [
            "python", "-m", "yt_dlp",
            "--dump-single-json",
            "--no-warnings",
            "--no-playlist",
            "--skip-download",
            "--extractor-args", "youtube:player_client=android,web",
            url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode != 0:
                continue
            import json as _json
            data = _json.loads(proc.stdout or "{}")
            # fields: description, tags, categories, like_count, view_count etc
            if data.get("description"):
                t["description"] = (data["description"] or "")[:1200]
            if data.get("tags"):
                t["tags"] = data["tags"][:12]
            if data.get("categories"):
                t["categories"] = data["categories"]
            # refresh counts if flat search missed them
            if data.get("view_count") and not t.get("view_count"):
                t["view_count"] = data["view_count"]
            if data.get("like_count") and not t.get("like_count"):
                t["like_count"] = data["like_count"]
            if data.get("duration") and not t.get("duration"):
                dur = data["duration"]
                if isinstance(dur, (int, float)):
                    m, s = divmod(int(dur), 60)
                    t["duration"] = f"{m}:{s:02d}"
            if data.get("channel") and t.get("channel") in ("Unknown", "", None):
                t["channel"] = data["channel"]
        except Exception as e:
            logger.debug("enrich track %s failed: %s", vid, e)
            continue
    return tracks
