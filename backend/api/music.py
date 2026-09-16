import time
import logging
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

from backend.core.music_history import get_music_history
from backend.core.youtube_client import get_chart_trending, resolve_stream, get_radio, get_mood_tracks
from backend.memory.knowledge_graph import get_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/music", tags=["music"])

# TTL cache for trending (same pattern as dashboard.py _ai_news_cache)
_trending_cache: dict | None = None
_trending_cache_time: float = 0
_TRENDING_TTL = 3600

# Popout tabs registry — in-memory mirror of frontend openPopouts for LLM tool access
# frontend POSTs on open/update/close; LLM tools read/toggle via here and emit WS music action
_popout_registry: dict[str, dict] = {}


class HistoryIn(BaseModel):
    video_id: str = ""
    title: str = ""
    artist: str = ""
    language: str = ""
    thumb: str = ""
    duration: str = ""


@router.post("/history")
def record_history(body: HistoryIn):
    hist = get_music_history()
    entry = hist.record_play(body.model_dump())
    return entry


@router.get("/history")
def get_history(limit: int = Query(default=20, ge=1, le=100)):
    hist = get_music_history()
    return {"plays": hist.recent(n=limit), "total": hist.total_plays()}


@router.get("/history/stats")
def history_stats():
    hist = get_music_history()
    # keep payload small — dashboard only needs top 5-10
    top_all = hist.top_played(n=10)
    top_week = hist.top_played(n=10, days=7)
    return {
        "total_plays": hist.total_plays(),
        "language_stats": hist.language_stats(),
        "most_played_artists": hist.most_played_artists(n=10),
        "top_all": top_all,
        "top_week": top_week,
    }


@router.get("/trending")
def trending(language: str | None = None, count: int = Query(default=10, ge=1, le=30)):
    """Trending picks biased by dominant history language + artists.

    - Fetch IN charts via ytmusicapi
    - If user has history, rank tracks matching dominant language / top artists higher
    - Cache 1h (count/language are part of key would bust cache — keep global cache and slice)
    """
    global _trending_cache, _trending_cache_time
    now = time.time()
    hist = get_music_history()

    # Use global charts cache (language-agnostic) then re-rank
    cache_valid = _trending_cache is not None and (now - _trending_cache_time) < _TRENDING_TTL
    if not cache_valid:
        res = get_chart_trending(country="IN", n=20)
        tracks = res.get("tracks") or []
        err = res.get("error")
        if err and not tracks:
            # graceful degradation — empty trending with error
            _trending_cache = {"tracks": [], "error": err, "country": "IN"}
            _trending_cache_time = now
            return {"tracks": [], "error": err, "country": "IN"}
        _trending_cache = {"tracks": tracks, "country": res.get("country", "IN")}
        _trending_cache_time = now
    else:
        tracks = list(_trending_cache.get("tracks") or [])

    if not tracks:
        return {"tracks": [], "country": "IN"}

    # Bias by history: boost tracks whose language == dominant language or whose artist in top artists
    try:
        lang_stats = hist.language_stats()
        dominant_lang = max(lang_stats, key=lang_stats.get) if lang_stats else None
        # filter override: if caller passes explicit language, use that
        target_lang = (language or "").strip().lower() or dominant_lang
        top_artists = {a["artist"].lower() for a in hist.most_played_artists(n=10)}
    except Exception:
        target_lang = (language or "").strip().lower() or None
        top_artists = set()

    def _score(t: dict) -> tuple:
        # higher tuple wins — sort reverse
        lang_boost = 1 if (target_lang and (t.get("language") or "").lower() == target_lang) else 0
        artist_boost = 1 if (t.get("artist") or "").lower() in top_artists else 0
        return (lang_boost, artist_boost)

    # Only re-rank if there's history signal
    if target_lang or top_artists:
        # stable sort: preserve chart order within same score bucket
        indexed = list(enumerate(tracks))
        indexed.sort(key=lambda x: (_score(x[1]), -x[0]), reverse=True)
        tracks = [t for _, t in indexed]

    # explicit language filter — if caller asked for specific language with no history,
    # prefer language matches but still return chart if none match (don't return empty)
    if language and language.strip():
        lang = language.strip().lower()
        matching = [t for t in tracks if (t.get("language") or "").lower() == lang]
        if matching:
            # interleave: matching first, then rest
            rest = [t for t in tracks if t not in matching]
            tracks = matching + rest

    count = max(1, min(int(count or 10), 30))
    return {"tracks": tracks[:count], "country": _trending_cache.get("country", "IN"), "biased_by": target_lang}


@router.get("/next")
def next_track(video_id: str | None = None, language: str | None = None, mood: str | None = None, count: int = Query(default=5, ge=1, le=20)):
    """Auto-queue next track(s) in same genre/mood/language.

    Cascade: mood → get_mood_tracks, video_id → get_radio filtered by language, else trending biased.
    Used by frontend onended when queue exhausts.
    """
    mood = (mood or "").strip()
    language = (language or "").strip().lower()
    video_id = (video_id or "").strip()
    count = max(1, min(int(count or 5), 20))

    # 1) mood path
    if mood:
        res = get_mood_tracks(mood, n=count + 2)
        tracks = res.get("tracks") or []
        if tracks:
            # filter out the current video_id if present
            if video_id:
                tracks = [t for t in tracks if t.get("video_id") != video_id]
            if tracks:
                return {"track": tracks[0], "queue": tracks[1:count], "source": "mood", "mood": mood}
    # 2) radio path
    if video_id:
        res = get_radio(video_id, n=count + 5)
        tracks = res.get("tracks") or []
        if tracks:
            # filter language if caller provided one
            if language and language != "other":
                # keep matching language first
                matching = [t for t in tracks if (t.get("language") or "").lower() == language]
                others = [t for t in tracks if t not in matching]
                # prefer matching, but don't return empty if none match
                if matching:
                    tracks = matching + others
            # remove current video_id
            tracks = [t for t in tracks if t.get("video_id") != video_id]
            if tracks:
                return {"track": tracks[0], "queue": tracks[1:count], "source": "radio", "seed": video_id}
    # 3) fallback → trending biased by language
    try:
        # reuse trending logic with bias
        trend = trending(language=language or None, count=count + 2)
        tracks = trend.get("tracks") or []
        if video_id:
            tracks = [t for t in tracks if t.get("video_id") != video_id]
        if tracks:
            return {"track": tracks[0], "queue": tracks[1:count], "source": "trending", "biased_by": trend.get("biased_by")}
    except Exception as e:
        logger.warning("next_track trending fallback failed: %s", e)
    return {"track": None, "queue": [], "source": "none"}


@router.get("/stream")
def stream_proxy(video_id: str = Query(..., min_length=5), redirect: bool = True):
    """Resolve and optionally redirect to fresh stream URL (handles expiry / CORS retry).

    Frontend falls back to `/api/music/stream?video_id=XXX` when direct
    `googlevideo` URL fails with MediaError. We re-resolve via yt-dlp so
    expiry is transparent. Default is 302 redirect (zero copy); client
    follows to googlevideo. No backend byte-proxy needed (removed CORS via
    PlayerBar removing crossOrigin), but this still refreshes stale URLs.
    """
    if not video_id.strip():
        raise HTTPException(status_code=400, detail="missing video_id")
    res = resolve_stream(video_id.strip())
    if res.get("error"):
        # surface clean error as JSON, not 302, so frontend can show it
        return JSONResponse(status_code=502, content={"error": res["error"], "video_id": video_id})
    url = res.get("stream_url") or ""
    if not url:
        raise HTTPException(status_code=502, detail="empty stream url")
    # Always redirect — browser will fetch googlevideo directly (Range supported).
    # If you need true byte-proxy later, replace with StreamingResponse + httpx.
    if redirect:
        return RedirectResponse(url=url, status_code=302)
    return {"stream_url": url, "video_id": video_id, "is_audio_only": res.get("is_audio_only", False)}


@router.get("/resolve")
def resolve(video_id: str = Query(..., min_length=5)):
    """JSON-only resolve (for debugging / proxy fallback via JS)."""
    res = resolve_stream(video_id.strip())
    if res.get("error"):
        return JSONResponse(status_code=502, content=res)
    return res


# ------------------------------------------------------------------
# Favorites (graph-backed) — used by PlayerBar heart toggle
# ------------------------------------------------------------------

class FavoriteIn(BaseModel):
    video_id: str = ""
    title: str = ""
    artist: str = ""
    thumb: str = ""
    language: str = ""
    duration: str = ""


def _is_favorited(video_id: str) -> bool:
    vid = (video_id or "").strip()
    if not vid:
        return False
    graph = get_graph()
    for n in graph.get_nodes_by_type("favorite_song"):
        if (n.get("properties", {}).get("video_id") or "").strip() == vid:
            return True
    return False

@router.get("/favorites/check")
def favorites_check(video_id: str = ""):
    if not video_id or len(video_id.strip()) < 3:
        raise HTTPException(status_code=400, detail="missing video_id")
    return {"video_id": video_id.strip(), "is_favorite": _is_favorited(video_id.strip())}

@router.get("/favorites")
def list_favorites_api(language: str | None = None, limit: int = 20):
    graph = get_graph()
    nodes = graph.get_nodes_by_type("favorite_song")
    lang = (language or "").strip().lower()
    if lang:
        nodes = [n for n in nodes if (n.get("properties", {}).get("language") or "").lower() == lang]
    nodes.sort(key=lambda n: n.get("properties", {}).get("added_at", ""), reverse=True)
    nodes = nodes[:max(1, min(int(limit or 20), 100))]
    out = []
    for n in nodes:
        p = n.get("properties", {})
        out.append({"id": n["id"], "video_id": p.get("video_id",""), "title": p.get("title","Unknown"), "artist": p.get("artist","Unknown"), "thumb": p.get("thumb",""), "language": p.get("language","other"), "duration": p.get("duration",""), "added_at": p.get("added_at","")})
    return {"favorites": out, "count": len(out)}

@router.post("/favorites/toggle")
def toggle_favorite_api(body: FavoriteIn):
    vid = (body.video_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="missing video_id")
    graph = get_graph()
    # find existing
    existing_id = None
    for n in graph.get_nodes_by_type("favorite_song"):
        if (n.get("properties", {}).get("video_id") or "").strip() == vid:
            existing_id = n["id"]
            break
    if existing_id:
        graph.remove_node(existing_id)
        return {"video_id": vid, "is_favorite": False, "action": "removed"}
    label = f"{body.title or vid} — {body.artist or 'Unknown'}".strip(" —")
    props = {
        "video_id": vid,
        "title": body.title or vid,
        "artist": body.artist or "Unknown",
        "thumb": body.thumb or "",
        "language": (body.language or "other").lower(),
        "duration": body.duration or "",
        "added_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    graph.add_node(type="favorite_song", label=label[:80], properties=props)
    return {"video_id": vid, "is_favorite": True, "action": "added"}

@router.get("/trusted")
def list_trusted_api():
    graph = get_graph()
    nodes = graph.get_nodes_by_type("trusted_channel")
    out = []
    for n in nodes:
        p = n.get("properties", {})
        out.append({"id": n["id"], "label": n.get("label",""), "channel": p.get("channel",""), "handle": p.get("channel_handle",""), "notes": p.get("notes",""), "added_at": p.get("added_at","")})
    return {"trusted_channels": out, "count": len(out)}


# ------------------------------------------------------------------
# Popout tabs registry — frontend sync + LLM control
# ------------------------------------------------------------------
class PopoutIn(BaseModel):
    tab_id: str = ""
    video_id: str = ""
    title: str = ""
    artist: str = ""
    thumb: str = ""
    duration: str = ""
    is_playing: bool = True
    start_time: int = 0


@router.post("/popouts/register")
def register_popout(body: PopoutIn):
    tid = (body.tab_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="missing tab_id")
    _popout_registry[tid] = {
        "tab_id": tid,
        "video_id": (body.video_id or "").strip(),
        "title": body.title or "Unknown",
        "artist": body.artist or "",
        "thumb": body.thumb or "",
        "duration": body.duration or "",
        "is_playing": bool(body.is_playing),
        "start_time": int(body.start_time or 0),
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    return {"tab_id": tid, "action": "registered", "count": len(_popout_registry)}


@router.post("/popouts/update")
def update_popout(body: PopoutIn):
    tid = (body.tab_id or "").strip()
    if not tid or tid not in _popout_registry:
        raise HTTPException(status_code=404, detail="tab not found")
    cur = _popout_registry[tid]
    # patch only provided fields
    if body.is_playing is not None:
        cur["is_playing"] = bool(body.is_playing)
    if body.title:
        cur["title"] = body.title
    cur["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return {"tab_id": tid, "action": "updated", "entry": cur}


@router.delete("/popouts/{tab_id}")
def delete_popout(tab_id: str):
    tid = (tab_id or "").strip()
    if tid in _popout_registry:
        del _popout_registry[tid]
        return {"tab_id": tid, "action": "deleted", "count": len(_popout_registry)}
    raise HTTPException(status_code=404, detail="tab not found")


@router.get("/popouts")
def list_popouts():
    return {"popouts": list(_popout_registry.values()), "count": len(_popout_registry)}


@router.post("/popouts/clear")
def clear_popouts():
    _popout_registry.clear()
    return {"action": "cleared", "count": 0}
