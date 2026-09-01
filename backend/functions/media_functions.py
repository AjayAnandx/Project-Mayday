"""6 music LLM tools (ytmusicapi + yt-dlp) — Playback, Vibe Engine, History & Trending.

Each tool returns a human-readable string AND, when it triggers playback,
a JSON blob with a `music` key that chat.py intercepts to emit a WS
`{type:"music", action:"play", track, queue}` message. Tool result text
doubles as TTS via _make_voice_text.
"""
import json
import logging
from typing import Any

from backend.core.youtube_client import (
    search_song as _search,
    resolve_stream as _resolve,
    get_radio as _radio,
    get_moods as _moods,
    get_mood_tracks as _mood_tracks,
    get_chart_trending as _trending,
    search_advanced as _search_advanced,
)
from backend.core.music_history import get_music_history

logger = logging.getLogger(__name__)

# Knowledge-graph helpers (lazy import to avoid cycle)
def _get_graph():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


def _find_favorite_node(video_id: str):
    vid = (video_id or "").strip()
    if not vid:
        return None
    graph = _get_graph()
    for n in graph.get_nodes_by_type("favorite_song"):
        if (n.get("properties", {}).get("video_id") or "").strip() == vid:
            return n
    return None


def _find_trusted_node(channel: str):
    ch = (channel or "").strip().lower()
    if not ch:
        return None
    # normalize: strip @ and url parts
    norm = ch
    # if youtube url, extract handle
    import re
    m = re.search(r'youtube\.com/(?:@|c/|channel/|user/)([^/?&]+)', ch)
    if m:
        norm = m.group(1).lower()
    norm = norm.lstrip('@').strip()
    graph = _get_graph()
    for n in graph.get_nodes_by_type("trusted_channel"):
        props = n.get("properties", {}) or {}
        cand = (props.get("channel_id") or props.get("channel_handle") or n.get("label") or "").strip().lower().lstrip('@')
        if cand == norm or cand == ch or norm in cand or cand in norm:
            return n
        # also check label contains
        if norm and norm in n.get("label", "").lower():
            return n
    return None


def _track_to_music(track: dict, stream_url: str = "", is_audio_only: bool = False, kind: str = "song") -> dict:
    d: dict = {
        "video_id": track.get("video_id", ""),
        "title": track.get("title", "Unknown"),
        "artist": track.get("artist", "Unknown"),
        "thumb": track.get("thumb", ""),
        "duration": track.get("duration", ""),
        "language": track.get("language", "other"),
        "stream_url": stream_url,
        "kind": kind if kind in ("song", "video") else "song",
    }
    if is_audio_only:
        d["is_audio_only"] = True
    return d


def _music_payload(track: dict, stream_url: str, queue: list[dict] | None = None, is_audio_only: bool = False, kind: str = "song") -> str:
    """Encode music WS payload as JSON in tool result for chat.py to intercept."""
    music_track = _track_to_music(track, stream_url, is_audio_only=is_audio_only, kind=kind)
    payload = {
        "music": {
            "action": "play",
            "track": music_track,
            "queue": [_track_to_music(t, kind=kind) for t in (queue or [])],
        }
    }
    return json.dumps(payload, ensure_ascii=False)


def _popup_payload(track: dict, stream_url: str = "", is_audio_only: bool = False) -> str:
    """Encode popup WS payload — opens YouTube in separate window/popup, NOT the bottom PlayerBar (songs-only bar)."""
    music_track = _track_to_music(track, stream_url, is_audio_only=is_audio_only, kind="video")
    payload = {"music": {"action": "open_popup", "track": music_track, "queue": []}}
    return json.dumps(payload, ensure_ascii=False)


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------

def play_song(artist: str = "", track: str = "", song: str = "", query: str = "") -> str:
    """Play a song by artist + track (or free-form song/query). Searches, resolves stream, emits music WS."""
    q = (query or song or "").strip()
    a = (artist or "").strip()
    t = (track or "").strip()
    # favorites shorthand: "play my favorites", "play favorite song", "play song from favorites"
    fav_kw = ("favorite", "favourite", "fav ")
    hay = f"{q} {a} {t}".lower()
    if any(k in hay for k in fav_kw):
        # if query is purely favorites request, delegate (preserve language filter if present)
        # check for Tamil/English hint
        lang = ""
        for L in ("ta", "tamil", "hi", "hindi", "en", "english"):
            if L in hay:
                lang = "ta" if L in ("ta","tamil") else "hi" if L in ("hi","hindi") else "en"
                break
        return play_favorites(count=15, shuffle=True, language=lang)
    if not q and not t:
        return "Missing required parameter: provide track (song title) or query"
    # If q provided, search with query; else artist+track
    if q and not a and not t:
        res = _search(query=q, max_results=3)
        label = q
    else:
        # build query from artist+track or q
        if q and (a or t):
            # q overrides track if provided
            t = q
        res = _search(artist=a, track=t or q, max_results=3)
        label = f"{a} - {t or q}".strip(" -")

    if res.get("error") and not res.get("tracks"):
        return res["error"]
    tracks = res.get("tracks") or []
    if not tracks:
        return f"No songs found for '{label}'"

    chosen = tracks[0]
    vid = chosen.get("video_id") or ""
    if not vid:
        return f"Found '{chosen.get('title')}' but no playable video id"

    stream = _resolve(vid)
    if stream.get("error"):
        # still return track with error so frontend can show message
        return f"Found '{chosen.get('title')}' by {chosen.get('artist')} [{chosen.get('language')}] but couldn't resolve stream: {stream['error']}"

    is_audio = bool(stream.get("is_audio_only"))
    music_json = _music_payload(chosen, stream["stream_url"], is_audio_only=is_audio)
    # human summary + machine payload (chat.py extracts music key) — surface audio-only fallback per user acceptance
    audio_hint = " (audio-only — video progressive unavailable, playing audio stream)" if is_audio else ""
    summary = f"Playing '{chosen.get('title')}' by {chosen.get('artist')} [{chosen.get('language')}]" + audio_hint
    return f"{summary}\n{music_json}"


def play_radio(seed_track: str = "", seed: str = "", query: str = "", artist: str = "") -> str:
    """Play radio mix seeded by a track (search seed → get_radio → queue 20 → play first)."""
    q = (seed_track or seed or query or "").strip()
    if artist:
        q = f"{artist.strip()} {q}".strip()
    if not q:
        return "Missing required parameter: seed_track (song to base radio on)"
    # search seed
    res = _search(query=q, max_results=3)
    if res.get("error") and not res.get("tracks"):
        return res["error"]
    tracks = res.get("tracks") or []
    if not tracks:
        return f"No seed found for '{q}'"
    seed_chosen = tracks[0]
    vid = seed_chosen.get("video_id") or ""
    if not vid:
        return f"Found seed '{seed_chosen.get('title')}' but no playable video id"
    radio = _radio(vid, n=20)
    if radio.get("error") and not radio.get("tracks"):
        return radio["error"]
    radio_tracks = radio.get("tracks") or []
    if not radio_tracks:
        return f"No radio mix for '{q}'"

    # play first radio track, queue rest
    first = radio_tracks[0]
    rest = radio_tracks[1:]
    fv = first.get("video_id") or ""
    stream = _resolve(fv) if fv else {"error": "no video id for radio first track"}
    if stream.get("error"):
        return f"Radio for '{q}' found {len(radio_tracks)} tracks but couldn't resolve first: {stream['error']}"
    is_audio = bool(stream.get("is_audio_only"))
    music_json = _music_payload(first, stream["stream_url"], queue=rest, is_audio_only=is_audio)
    audio_hint = " (audio-only)" if is_audio else ""
    summary = f"Radio for '{seed_chosen.get('title')}' — {len(radio_tracks)} tracks, now playing '{first.get('title')}' by {first.get('artist')}" + audio_hint
    return f"{summary}\n{music_json}"


def play_mood(mood: str = "", count: int = 15) -> str:
    """Play a mood/genre playlist (mood catalog → playlist tracks → queue → play first)."""
    m = (mood or "").strip()
    if not m:
        m = "chill"
    # mood may be friendly name like "chill" — map to catalog via get_moods
    moods_res = _moods()
    target_id = m
    if moods_res.get("moods"):
        # fuzzy match by title
        lower = m.lower()
        for it in moods_res["moods"]:
            if lower in it.get("title", "").lower() or it.get("title", "").lower() in lower:
                target_id = it.get("id", m)
                break

    res = _mood_tracks(target_id, n=int(count or 15))
    # if direct id failed and we mapped, retry with original string
    if res.get("error") and target_id != m:
        res2 = _mood_tracks(m, n=int(count or 15))
        if not res2.get("error"):
            res = res2

    if res.get("error") and not res.get("tracks"):
        # surface catalog hint
        catalog_hint = ""
        if moods_res.get("moods"):
            sample = ", ".join(x["title"] for x in moods_res["moods"][:8])
            catalog_hint = f" Try one of: {sample}"
        return f"{res['error']}.{catalog_hint}"

    tracks = res.get("tracks") or []
    if not tracks:
        return f"No tracks for mood '{m}'"

    first = tracks[0]
    rest = tracks[1:]
    fv = first.get("video_id") or ""
    # mood playlists may return playlist pseudo-tracks without video_id — handle gracefully
    if fv and not fv.startswith("PL") and len(fv) < 20:
        stream = _resolve(fv)
        if stream.get("error"):
            # queue still usable, play first without stream (frontend will show error and skip)
            music_json = _music_payload(first, "", queue=rest)
            return f"Mood '{m}' — {len(tracks)} tracks queued, now playing '{first.get('title')}' (stream unavailable: {stream['error']})\n{music_json}"
        is_audio = bool(stream.get("is_audio_only"))
        music_json = _music_payload(first, stream["stream_url"], queue=rest, is_audio_only=is_audio)
        audio_hint = " (audio-only)" if is_audio else ""
        summary = f"Mood '{m}' — {len(tracks)} tracks, now playing '{first.get('title')}' by {first.get('artist','')}" + audio_hint
        if res.get("playlist_title"):
            summary = f"Mood '{m}' ({res['playlist_title']}) — " + summary.split(" — ",1)[-1] if " — " in summary else summary
        return f"{summary}\n{music_json}"
    else:
        # no resolvable video_id — still queue
        music_json = _music_payload(first, "", queue=rest)
        summary = f"Mood '{m}' — {len(tracks)} tracks, now playing '{first.get('title')}' by {first.get('artist','')}"
        if res.get("playlist_title"):
            summary = f"Mood '{m}' ({res['playlist_title']}) — " + summary.split(" — ",1)[-1] if " — " in summary else summary
        return f"{summary}\n{music_json}"


def queue_song(artist: str = "", track: str = "", song: str = "", query: str = "") -> str:
    """Search and append to queue without immediate play (frontend queues on music payload)."""
    q = (query or song or "").strip()
    a = (artist or "").strip()
    t = (track or "").strip()
    if not q and not t:
        return "Missing required parameter: provide track or query to queue"
    if q and not a and not t:
        res = _search(query=q, max_results=2)
        label = q
    else:
        if q and (a or t):
            t = q
        res = _search(artist=a, track=t or q, max_results=2)
        label = f"{a} - {t or q}".strip(" -")
    if res.get("error") and not res.get("tracks"):
        return res["error"]
    tracks = res.get("tracks") or []
    if not tracks:
        return f"No songs found for '{label}'"
    chosen = tracks[0]
    vid = chosen.get("video_id") or ""
    stream_url = ""
    is_audio_only = False
    if vid:
        s = _resolve(vid)
        if not s.get("error"):
            stream_url = s["stream_url"]
            is_audio_only = bool(s.get("is_audio_only"))
    # queue payload — frontend will append; use action queue
    music_track = _track_to_music(chosen, stream_url, is_audio_only=is_audio_only)
    payload = json.dumps({"music": {"action": "queue", "track": music_track}}, ensure_ascii=False)
    hint = " (audio-only)" if is_audio_only else ""
    summary = f"Queued '{chosen.get('title')}' by {chosen.get('artist')} [{chosen.get('language')}]" + hint
    return f"{summary}\n{payload}"


def discover_trending(language: str = "", count: int = 10) -> str:
    """List trending picks (charts → filter/rank by history language + artists). 'play #3' → call play_song."""
    cnt = max(1, min(int(count or 10), 20))
    lang = (language or "").strip()
    # use trending logic via music api (reuse chart + history bias)
    # call directly for tool path (no HTTP)
    from backend.core.youtube_client import get_chart_trending as _charts
    from backend.core.music_history import get_music_history as _hist

    res = _charts(country="IN", n=20)
    tracks = res.get("tracks") or []
    if not tracks and res.get("error"):
        return res["error"]
    if not tracks:
        return "No trending tracks available"

    # bias via history (same as /api/music/trending)
    try:
        h = _hist()
        stats = h.language_stats()
        dominant = max(stats, key=stats.get) if stats else None
        target = lang.lower() if lang else (dominant or "")
        top_artists = {a["artist"].lower() for a in h.most_played_artists(n=10)}
    except Exception:
        target = lang.lower() if lang else ""
        top_artists = set()

    def _score(t):
        lb = 1 if target and (t.get("language") or "").lower() == target else 0
        ab = 1 if (t.get("artist") or "").lower() in top_artists else 0
        return (lb, ab)

    if target or top_artists:
        indexed = list(enumerate(tracks))
        indexed.sort(key=lambda x: (_score(x[1]), -x[0]), reverse=True)
        tracks = [t for _, t in indexed]

    if lang:
        matching = [t for t in tracks if (t.get("language") or "").lower() == lang.lower()]
        if matching:
            rest = [t for t in tracks if t not in matching]
            tracks = matching + rest

    picks = tracks[:cnt]
    lines = []
    for i, t in enumerate(picks, 1):
        lines.append(f"{i}. {t.get('title','Unknown')} — {t.get('artist','Unknown')} [{t.get('language','other')}] (id: {t.get('video_id','')})")
    header = f"Trending in {lang or 'India'} (biased by your taste{f' [{target}]' if target else ''}):" if (lang or target) else "Trending in India:"
    footer = "Say 'play #3' or call play_song with the track to play it."
    return header + "\n" + "\n".join(lines) + f"\n{footer}"


def my_top_songs(n: int = 10, language: str = "") -> str:
    """List top played songs from history, optionally filtered by language."""
    cnt = max(1, min(int(n or 10), 50))
    lang = (language or "").strip().lower() or None
    hist = get_music_history()
    top = hist.top_played(n=cnt, language=lang, days=None)
    if not top:
        if lang:
            return f"No plays yet for language '{lang}'. Play some songs first!"
        return "No play history yet. Play some songs and they'll appear here."
    lines = []
    for i, t in enumerate(top, 1):
        lines.append(f"{i}. {t.get('title','Unknown')} — {t.get('artist','Unknown')} [{t.get('language','other')}] ×{t.get('plays',1)} (id: {t.get('video_id','')})")
    header = f"Your top {len(top)} songs" + (f" in {lang}" if lang else "") + ":"
    return header + "\n" + "\n".join(lines)


# ------------------------------------------------------------------
# Favorites (graph-backed) + Trusted channels + Advanced search + Popup
# ------------------------------------------------------------------

def add_favorite(video_id: str = "", title: str = "", artist: str = "", thumb: str = "", language: str = "", duration: str = "") -> str:
    """Add a song to favorites (stored in knowledge graph). If video_id missing, searches by title/artist."""
    vid = (video_id or "").strip()
    if not vid and (title or artist):
        # search to resolve video_id
        res = _search(query=f"{artist} {title}".strip() or title, max_results=1)
        tracks = res.get("tracks") or []
        if tracks:
            vid = tracks[0].get("video_id") or ""
            title = title or tracks[0].get("title", "")
            artist = artist or tracks[0].get("artist", "")
            thumb = thumb or tracks[0].get("thumb", "")
            language = language or tracks[0].get("language", "")
            duration = duration or tracks[0].get("duration", "")
    if not vid:
        return "Missing video_id — provide a YouTube video id or title/artist to add."
    if _find_favorite_node(vid):
        return f"Already in favorites: {vid}"
    graph = _get_graph()
    label = f"{title or vid} — {artist or 'Unknown'}".strip(" —")
    props = {
        "video_id": vid,
        "title": title or vid,
        "artist": artist or "Unknown",
        "thumb": thumb or "",
        "language": (language or "other").lower(),
        "duration": duration or "",
        "added_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    nid = graph.add_node(type="favorite_song", label=label[:80], properties=props)
    return f"Added to favorites: '{props['title']}' by {props['artist']} [{props['language']}] (id: {vid})"

def remove_favorite(video_id: str = "", title: str = "") -> str:
    """Remove a song from favorites by video_id or title."""
    vid = (video_id or "").strip()
    node = _find_favorite_node(vid) if vid else None
    if not node and title:
        # fuzzy by title
        graph = _get_graph()
        for n in graph.get_nodes_by_type("favorite_song"):
            if title.lower() in n.get("label", "").lower() or title.lower() in (n.get("properties", {}).get("title", "").lower()):
                node = n
                break
    if not node:
        return f"Not in favorites: {vid or title}"
    graph = _get_graph()
    graph.remove_node(node["id"])
    return f"Removed from favorites: '{node.get('label')}'"

def list_favorites(language: str = "", limit: int = 20) -> str:
    """List favorite songs, optionally filtered by language."""
    graph = _get_graph()
    nodes = graph.get_nodes_by_type("favorite_song")
    lang = (language or "").strip().lower()
    if lang:
        nodes = [n for n in nodes if (n.get("properties", {}).get("language") or "").lower() == lang]
    # sort by added_at desc
    nodes.sort(key=lambda n: n.get("properties", {}).get("added_at", ""), reverse=True)
    lim = max(1, min(int(limit or 20), 50))
    nodes = nodes[:lim]
    if not nodes:
        return f"No favorites yet{f' for language {lang}' if lang else ''}. Play a song and say 'add to favorites'."
    lines = []
    for i, n in enumerate(nodes, 1):
        p = n.get("properties", {})
        lines.append(f"{i}. {p.get('title','Unknown')} — {p.get('artist','Unknown')} [{p.get('language','other')}] (id: {p.get('video_id','')})")
    header = f"Your favorites{f' in {lang}' if lang else ''} ({len(nodes)}):"
    footer = "Say 'play my favorites' to queue them."
    return header + "\n" + "\n".join(lines) + f"\n{footer}"

def toggle_favorite(video_id: str = "", title: str = "", artist: str = "", thumb: str = "", language: str = "", duration: str = "") -> str:
    """Toggle favorite: if exists remove, otherwise add. Returns new state."""
    vid = (video_id or "").strip()
    if not vid and title:
        res = _search(query=f"{artist} {title}".strip() or title, max_results=1)
        tracks = res.get("tracks") or []
        if tracks:
            vid = tracks[0].get("video_id") or ""
            title = title or tracks[0].get("title", "")
            artist = artist or tracks[0].get("artist", "")
    if not vid:
        return "Missing video_id or title to toggle favorite."
    existing = _find_favorite_node(vid)
    if existing:
        return remove_favorite(video_id=vid)
    return add_favorite(video_id=vid, title=title, artist=artist, thumb=thumb, language=language, duration=duration)

def play_favorites(count: int = 15, shuffle: bool = True, language: str = "") -> str:
    """Queue and play songs from favorites (graph)."""
    graph = _get_graph()
    nodes = graph.get_nodes_by_type("favorite_song")
    lang = (language or "").strip().lower()
    if lang:
        nodes = [n for n in nodes if (n.get("properties", {}).get("language") or "").lower() == lang]
    if not nodes:
        return f"No favorites yet{f' for {lang}' if lang else ''}. Add some with 'add to favorites' first."
    # build tracks
    tracks = []
    for n in nodes:
        p = n.get("properties", {})
        tracks.append({"video_id": p.get("video_id",""), "title": p.get("title","Unknown"), "artist": p.get("artist","Unknown"), "thumb": p.get("thumb",""), "language": p.get("language","other"), "duration": p.get("duration","")})
    import random
    if shuffle:
        random.shuffle(tracks)
    cnt = max(1, min(int(count or 15), 50))
    picks = tracks[:cnt]
    if not picks:
        return "No favorite tracks to play."
    first = picks[0]
    rest = picks[1:]
    stream = _resolve(first.get("video_id") or "")
    if stream.get("error"):
        # queue without stream, frontend will lazy-resolve
        music_json = _music_payload(first, "", queue=rest)
        return f"Queued {len(picks)} favorites (first stream unavailable: {stream['error']}), now playing '{first.get('title')}'\n{music_json}"
    is_audio = bool(stream.get("is_audio_only"))
    music_json = _music_payload(first, stream["stream_url"], queue=rest, is_audio_only=is_audio)
    hint = " (audio-only)" if is_audio else ""
    return f"Playing your favorites — {len(picks)} tracks, now playing '{first.get('title')}' by {first.get('artist')}{hint}\n{music_json}"

def add_trusted_channel(channel: str = "", notes: str = "") -> str:
    """Save a trusted YouTube channel/handle to memory (graph). Channel may be @handle, url, or name."""
    ch = (channel or "").strip()
    if not ch:
        return "Missing channel — provide a YouTube handle (@name), URL, or channel name."
    if _find_trusted_node(ch):
        return f"Already trusted: {ch}"
    import re
    handle = ch
    m = re.search(r'youtube\.com/(?:@|c/|channel/|user/)([^/?&#]+)', ch)
    if m:
        handle = "@" + m.group(1).lstrip("@")
    elif ch.startswith("@"):
        handle = ch
    else:
        # plain name — keep as is but normalize handle
        handle = ch
    graph = _get_graph()
    props = {
        "channel": ch,
        "channel_handle": handle,
        "channel_id": handle.lstrip("@").lower(),
        "notes": (notes or "").strip(),
        "added_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    label = handle if handle.startswith("@") else ch
    nid = graph.add_node(type="trusted_channel", label=label[:80], properties=props)
    return f"Saved trusted channel: {label} — I'll prioritize it for new music searches."

def remove_trusted_channel(channel: str = "") -> str:
    """Remove a trusted channel from memory."""
    ch = (channel or "").strip()
    if not ch:
        return "Missing channel name/handle to remove."
    node = _find_trusted_node(ch)
    if not node:
        return f"Not found in trusted channels: {ch}"
    graph = _get_graph()
    graph.remove_node(node["id"])
    return f"Removed trusted channel: {node.get('label')}"

def list_trusted_channels() -> str:
    """List all trusted channels from memory."""
    graph = _get_graph()
    nodes = graph.get_nodes_by_type("trusted_channel")
    if not nodes:
        return "No trusted channels saved yet. Say 'add channel @TamilBeats to trusted' to add one."
    nodes.sort(key=lambda n: n.get("properties", {}).get("added_at", ""))
    lines = []
    for i, n in enumerate(nodes, 1):
        p = n.get("properties", {})
        handle = p.get("channel_handle") or n.get("label")
        notes = f" — {p['notes']}" if p.get("notes") else ""
        lines.append(f"{i}. {handle}{notes}")
    return f"Trusted channels ({len(nodes)}):\n" + "\n".join(lines)

def open_video_popup(video_id: str = "") -> str:
    """Open the currently playing video (or given video_id) in a separate popup/window.

    Frontend will attempt window.open; if blocked it shows an in-app modal with YouTube embed.
    Emits a music WS payload with action open_popup so the PlayerBar can trigger it.
    """
    vid = (video_id or "").strip()
    if vid:
        # resolve track for popup title — popup windows are for YouTube/tutorial videos (PlayerBar below chat is songs-only)
        track = {"video_id": vid, "title": vid, "artist": "Unknown", "thumb": "", "language": "other", "duration": ""}
        payload = json.dumps({"music": {"action": "open_popup", "track": _track_to_music(track, kind="video")}}, ensure_ascii=False)
        return f"Opening video {vid} in popup window (YouTube) — PlayerBar below chat stays songs-only\n{payload}"
    # caller didn't give id — ask frontend to pop current (video popup, not songs bar)
    payload = json.dumps({"music": {"action": "open_popup", "track": None}}, ensure_ascii=False)
    return f"Opening current video in popup window — PlayerBar below chat stays songs-only\n{payload}"

def search_youtube_videos(query: str = "", sort_by: str = "relevance", time_filter: str = "any", trusted_only: bool = False, max_results: int = 15) -> str:
    """Search YouTube videos with rich filters: sort by views/likes/date, filter by recency, restrict to trusted channels.

    sort_by: relevance | view_count | rating | upload_date (aliases: views, likes, newest)
    time_filter: any | today | week | month | year
    trusted_only: if true, only results whose channel/artist matches your saved trusted channels
    """
    q = (query or "").strip()
    if not q:
        return "Missing query — what topic should I search? e.g. 'Tamil melody 2024'"
    max_results = max(1, min(int(max_results or 15), 30))
    res = _search_advanced(query=q, max_results=max_results if not trusted_only else max_results * 2, sort_by=sort_by, time_filter=time_filter)
    tracks = res.get("tracks") or []
    if not tracks and res.get("error"):
        return res["error"]
    if not tracks:
        return f"No results for '{q}'"

    # trusted channel filter
    if trusted_only:
        graph = _get_graph()
        trusted = graph.get_nodes_by_type("trusted_channel")
        if not trusted:
            return "trusted_only is set but you have no trusted channels saved. Add one with add_trusted_channel first."
        trusted_handles = []
        for n in trusted:
            p = n.get("properties", {}) or {}
            h = (p.get("channel_handle") or p.get("channel_id") or n.get("label") or "").lower().lstrip("@")
            if h:
                trusted_handles.append(h)
            raw = (p.get("channel") or "").lower()
            if raw and raw not in trusted_handles:
                trusted_handles.append(raw.lower())
        filtered = []
        for t in tracks:
            hay = f"{t.get('channel','')} {t.get('artist','')} {t.get('channel_id','')}".lower()
            for h in trusted_handles:
                if h and h in hay:
                    filtered.append(t)
                    break
        if not filtered:
            return f"No results for '{q}' matched your trusted channels ({', '.join(trusted_handles[:5])}). Try without trusted_only or add more channels."
        tracks = filtered[:max_results]

    # format
    header = f"Search: '{q}' — sorted by {res.get('sort_by', sort_by)} {('· ' + time_filter) if time_filter != 'any' else ''} { '(trusted only)' if trusted_only else ''}".strip()
    lines = []
    for i, t in enumerate(tracks[:max_results], 1):
        vc = t.get("view_count")
        lc = t.get("like_count")
        meta = []
        if vc is not None:
            if vc >= 1_000_000:
                meta.append(f"{vc/1_000_000:.1f}M views")
            elif vc >= 1_000:
                meta.append(f"{vc/1_000:.1f}K views")
            else:
                meta.append(f"{vc} views")
        if lc is not None and lc > 0:
            meta.append(f"{lc} likes")
        if t.get("upload_date"):
            meta.append(t["upload_date"])
        meta_str = f" — {', '.join(meta)}" if meta else ""
        chan = t.get("channel") or t.get("artist") or ""
        chan_str = f" [{chan}]" if chan else ""
        lines.append(f"{i}. {t.get('title','Unknown')} — {t.get('artist','Unknown')} [{t.get('language','other')}] (id: {t.get('video_id','')}){chan_str}{meta_str}")
    footer = "Say 'play #2' to play a result, or 'add #2 to favorites'."
    return header + "\n" + "\n".join(lines) + f"\n{footer}"


def _rank_balanced_with_llm(query: str, tracks: list[dict], trusted_handles: list[str] | None = None) -> tuple[str | None, list[dict]]:
    """Try LLM ranking for balanced understanding; fallback to heuristic.

    Returns (best_video_id, ranked_tracks_with_reason).
    ranked_tracks have added keys: _score, _reason
    """
    # heuristic fallback
    def heuristic_rank(ts: list[dict]) -> tuple[str | None, list[dict]]:
        # balanced heuristic: view log + like ratio + recency + trusted boost
        import math, time as _time
        now = int(_time.time())
        scored = []
        for t in ts:
            vc = t.get("view_count") or 0
            lc = t.get("like_count") or 0
            ts_val = t.get("timestamp") or 0
            # view score log scale
            v_score = math.log1p(vc) / 14 if vc else 0  # ~14 for 1M
            # like ratio
            l_score = (lc / vc) if vc and lc else 0
            l_score = min(l_score, 0.05) * 10  # normalize tiny ratio
            # recency: newer is better for tutorial (up to 1 year)
            r_score = 0
            if ts_val:
                age_days = (now - int(ts_val)) / 86400
                if age_days < 365:
                    r_score = (365 - age_days) / 365 * 0.2
            # trusted boost
            t_score = 0
            if trusted_handles:
                hay = f"{t.get('channel','')} {t.get('artist','')}".lower()
                for h in trusted_handles or []:
                    if h and h.lower().lstrip('@') in hay:
                        t_score = 0.25
                        break
            total = v_score * 0.3 + l_score * 0.2 + r_score + t_score
            # description presence bonus (richer tutorial)
            if t.get("description"):
                total += 0.1
            scored.append((total, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = []
        for score, tr in scored:
            tr2 = dict(tr)
            tr2["_score"] = round(score, 3)
            tr2["_reason"] = f"heuristic score {tr2['_score']} (views+likes+recency{' + trusted' if score>=0.25 else ''})"
            ranked.append(tr2)
        best = ranked[0].get("video_id") if ranked else None
        return best, ranked

    # try LLM
    try:
        from backend.assistant.llm_client import LLMClient
        # lazy load trusted handles already have
        # build compact candidate block
        cand_lines = []
        for idx, t in enumerate(tracks[:6], 1):
            desc = (t.get("description") or "")[:280].replace("\n"," ")
            tags = ", ".join(t.get("tags", [])[:5]) if t.get("tags") else ""
            cand_lines.append(
                f"{idx}. id={t.get('video_id')} | title='{t.get('title')}' | channel='{t.get('channel') or t.get('artist')}' "
                f"| views={t.get('view_count')} likes={t.get('like_count')} upload={t.get('upload_date')} duration={t.get('duration')} "
                f"| desc='{desc}' tags=[{tags}]"
            )
        trusted_str = ", ".join(trusted_handles or []) or "none"
        prompt = (
            f"You are a YouTube tutorial ranking assistant. Query: '{query}'. Balanced best means: relevance 30% + clarity 25% + depth 20% + recency 15% + trust 10%.\n"
            f"Trusted channels: {trusted_str}\n"
            f"Candidates:\n" + "\n".join(cand_lines) + "\n\n"
            f"Task: Pick exactly 3, rank them best→worst for balanced understanding. Return ONLY JSON: "
            f'{{"ranked": [{{"id": "...", "reason": "1-2 sentences why this rank"}}], "best_id": "..."}} '
            f"IDs must be from input list."
        )
        client = LLMClient()
        # short timeout via httpx already 600 but we want fast; use max_tokens 600
        resp = client.chat(
            [{"role": "user", "content": prompt}],
            stream=False,
            tools=[],
            max_tokens=600,
        )
        content, _ = client.extract_response(resp)
        if content:
            import json as _json, re as _re
            # extract JSON block
            m = _re.search(r"\{[\s\S]*\}", content)
            if m:
                data = _json.loads(m.group(0))
                ranked_info = data.get("ranked") or []
                best_id = data.get("best_id")
                # map back to tracks, attach reasons
                id_to_reason = {r.get("id"): r.get("reason","") for r in ranked_info if r.get("id")}
                # build ranked tracks in LLM order
                llm_order = []
                for r in ranked_info:
                    vid = r.get("id")
                    tr = next((x for x in tracks if x.get("video_id")==vid), None)
                    if tr:
                        tr2 = dict(tr)
                        tr2["_reason"] = r.get("reason","")
                        tr2["_score"] = 9 - len(llm_order)  # pseudo
                        llm_order.append(tr2)
                # add any missing candidates not in LLM list (should not happen)
                if llm_order and best_id in [x.get("video_id") for x in llm_order]:
                    return best_id, llm_order
                # fallback if LLM didn't respect IDs
    except Exception as e:
        logger.debug("LLM rank failed, fallback heuristic: %s", e)
    return heuristic_rank(tracks)


def recommend_best_video(query: str = "", trusted_only: bool = False, max_results: int = 8) -> str:
    """Compare top 3 videos for a query and autoplay the best for balanced understanding.

    - Searches YouTube (view/like/recency enriched) — uses general YouTube for tutorial queries, YTMusic for music
    - Enriches top 3 with description/tags via yt-dlp
    - Ranks 3 with balanced LLM reasoning (fallback heuristic)
    - Autoplays #1 via music payload + lists comparison

    Use when user says 'which is best', 'LLM evaluation tutorial', 'recommend a video'.
    """
    q = (query or "").strip()
    if not q:
        return "Missing query — what topic should I search? e.g. 'LLM evaluation tutorial'"
    max_results = max(1, min(int(max_results or 8), 15))
    # Detect tutorial/video vs music to choose search backend — music queries use ytmusicapi (filter=songs), video/tutorial use general YouTube
    # Bug fix: old list missed "engineering fact latest video" etc -> went to ytmusicapi and gave music results. Broadened to reuse youtube_client VIDEO keywords.
    try:
        from backend.core.youtube_client import _VIDEO_QUERY_KEYWORDS as _VIDEO_KW  # single source of truth
        _tutorial_kw = tuple(_VIDEO_KW)
    except Exception:
        _tutorial_kw = ("tutorial","how to","explained","course","lecture","evaluation","benchmark","llm","rag","transformer","attention","engineering","fact","facts","science","technology","tech","research","study","latest","newest","recent","video")
    is_tutorial = any(kw in q.lower() for kw in _tutorial_kw)
    # explicit fallback: if query contains video/engineering/fact/latest, treat as tutorial even if keyword missed
    _ql = q.lower()
    if not is_tutorial and any(w in _ql for w in ("engineering","fact","latest","video","science","technology","research")):
        is_tutorial = True
    if is_tutorial:
        # Use general YouTube search (yt-dlp flat) — bypass ytmusicapi music-only bias
        from backend.core.youtube_client import _yt_dlp_search as _yt_search
        res = _yt_search(q, max_results if not trusted_only else max_results * 2)
        # normalize to same shape as search_advanced
        if not res.get("tracks"):
            # fallback to advanced search if yt-dlp returned nothing
            res = _search_advanced(query=q, max_results=max_results if not trusted_only else max_results * 2, sort_by="relevance", time_filter="any")
        else:
            # mimic search_advanced return shape
            res = {"tracks": res["tracks"], "query": q, "sort_by": "relevance", "time_filter": "any"}
    else:
        res = _search_advanced(query=q, max_results=max_results if not trusted_only else max_results * 2, sort_by="relevance", time_filter="any")
    tracks = res.get("tracks") or []
    if not tracks and res.get("error"):
        return res["error"]
    if not tracks:
        return f"No results for '{q}'"

    # trusted filter first
    trusted_handles: list[str] = []
    if trusted_only:
        graph = _get_graph()
        trusted = graph.get_nodes_by_type("trusted_channel")
        if not trusted:
            return "trusted_only is set but you have no trusted channels saved. Add one with add_trusted_channel first."
        for n in trusted:
            p = n.get("properties", {}) or {}
            h = (p.get("channel_handle") or p.get("channel_id") or n.get("label") or "").lower().lstrip("@")
            if h:
                trusted_handles.append(h)
            raw = (p.get("channel") or "").lower()
            if raw and raw not in trusted_handles:
                trusted_handles.append(raw.lower())
        filtered = []
        for t in tracks:
            hay = f"{t.get('channel','')} {t.get('artist','')} {t.get('channel_id','')}".lower()
            for h in trusted_handles:
                if h and h in hay:
                    filtered.append(t)
                    break
        if not filtered:
            return f"No results for '{q}' matched your trusted channels ({', '.join(trusted_handles[:5])}). Try without trusted_only or add more channels."
        tracks = filtered[:max_results]
    else:
        # also load trusted for ranking boost even when not strictly filtered
        try:
            graph = _get_graph()
            for n in graph.get_nodes_by_type("trusted_channel"):
                p = n.get("properties", {}) or {}
                h = (p.get("channel_handle") or n.get("label") or "").lower().lstrip("@")
                if h:
                    trusted_handles.append(h)
        except Exception:
            pass

    # enrich top 3 for richer ranking
    try:
        from backend.core.youtube_client import enrich_tracks
        enrich_tracks(tracks, max_enrich=3)
    except Exception as e:
        logger.debug("enrich failed: %s", e)

    best_id, ranked = _rank_balanced_with_llm(q, tracks, trusted_handles)
    if not ranked:
        return f"No rankable results for '{q}'"
    if not best_id:
        best_id = ranked[0].get("video_id")
    # ensure ranked is exactly 3 for display (or fewer if less candidates)
    ranked_display = ranked[:3]
    best_track = next((t for t in ranked if t.get("video_id") == best_id), ranked_display[0] if ranked_display else None)
    if not best_track:
        return f"Could not pick best for '{q}'"

    # autoplay best in popup (NOT the songs-only PlayerBar) — bottom bar is for songs only per user
    vid = best_track.get("video_id") or ""
    stream = _resolve(vid) if vid else {"error": "no video id"}
    if stream.get("error"):
        music_json = _popup_payload(best_track, "")
        autoplay_note = f"(stream unavailable: {stream['error']})"
    else:
        is_audio = bool(stream.get("is_audio_only"))
        music_json = _popup_payload(best_track, stream["stream_url"], is_audio_only=is_audio)
        autoplay_note = " (audio-only)" if is_audio else ""

    # format comparison
    header = f"Compared 3 videos for '{q}' -- best for balanced understanding is #1:"
    lines = []
    for i, t in enumerate(ranked_display, 1):
        marker = " -- BEST -- autoplaying" if t.get("video_id") == best_id else ""
        vc = t.get("view_count")
        meta = ""
        if vc is not None:
            if vc >= 1_000_000:
                meta = f" {vc/1_000_000:.1f}M views"
            elif vc >= 1_000:
                meta = f" {vc/1_000:.1f}K views"
            else:
                meta = f" {vc} views"
        chan = t.get("channel") or t.get("artist") or ""
        reason = t.get("_reason") or ""
        lines.append(f"{i}. {t.get('title','Unknown')} — {chan} [{t.get('duration','')}] (id: {t.get('video_id','')}){meta}{marker}\n   Why: {reason}")
    summary = f"Opening best in popup: '{best_track.get('title')}' by {best_track.get('channel') or best_track.get('artist','')}{autoplay_note} — check popup window (PlayerBar below chat is songs-only)"
    return header + "\n" + "\n".join(lines) + f"\n{summary}\n{music_json}"


# ------------------------------------------------------------------
# Multi-tab popout control — LLM can open multiple tutorial/video tabs
# and pause/play each independently. Frontend syncs registry via
# /api/music/popouts/* ; these tools operate on that registry and emit
# WS music actions (popout_toggle/close/focus) so the frontend actually
# controls the window via BroadcastChannel.
# ------------------------------------------------------------------
def list_popout_tabs() -> str:
    """List all currently open popout video tabs (multi-tab).

    Use to see open tutorial/video windows before closing or toggling one.
    """
    try:
        from backend.api.music import _popout_registry
    except Exception:
        return "No popout registry available"
    if not _popout_registry:
        return "No popout tabs open — open one with open_video_popup (each call opens a new tab)"
    lines = []
    for i, (tid, entry) in enumerate(_popout_registry.items(), 1):
        state = "▶ playing" if entry.get("is_playing") else "⏸ paused"
        lines.append(f"{i}. tab_id={tid} — '{entry.get('title','Unknown')}' — {entry.get('artist','')} [{entry.get('video_id','')}] {state}")
    return f"Open popout tabs ({len(_popout_registry)}):\n" + "\n".join(lines) + "\nUse toggle_popout_tab / close_popout_tab / focus_popout_tab with tab_id"


def close_popout_tab(tab_id: str = "") -> str:
    """Close a specific popout video tab by tab_id (from list_popout_tabs)."""
    tid = (tab_id or "").strip()
    if not tid:
        return "Missing tab_id — call list_popout_tabs to see open tab_ids"
    try:
        from backend.api.music import _popout_registry
    except Exception:
        return "No popout registry"
    if tid not in _popout_registry:
        return f"Tab {tid} not found — open tabs: {', '.join(_popout_registry.keys()) or 'none'}"
    title = _popout_registry[tid].get("title","")
    del _popout_registry[tid]
    payload = json.dumps({"music": {"action": "popout_close", "tab_id": tid}}, ensure_ascii=False)
    return f"Closed tab {tid} ('{title}')\n{payload}"


def focus_popout_tab(tab_id: str = "") -> str:
    """Bring a popout tab window to front (focus)."""
    tid = (tab_id or "").strip()
    if not tid:
        return "Missing tab_id — call list_popout_tabs first"
    try:
        from backend.api.music import _popout_registry
    except Exception:
        return "No popout registry"
    if tid not in _popout_registry:
        return f"Tab {tid} not found"
    payload = json.dumps({"music": {"action": "popout_focus", "tab_id": tid}}, ensure_ascii=False)
    return f"Focusing tab {tid} ('{_popout_registry[tid].get('title','')}')\n{payload}"


def toggle_popout_tab(tab_id: str = "") -> str:
    """Toggle play/pause for a specific popout tab (each tab independent)."""
    tid = (tab_id or "").strip()
    if not tid:
        return "Missing tab_id — call list_popout_tabs to see ids"
    try:
        from backend.api.music import _popout_registry
    except Exception:
        return "No popout registry"
    if tid not in _popout_registry:
        return f"Tab {tid} not found — open tabs: {', '.join(_popout_registry.keys()) or 'none'}"
    cur = _popout_registry[tid].get("is_playing", True)
    _popout_registry[tid]["is_playing"] = not cur
    _popout_registry[tid]["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    nxt = "playing" if not cur else "paused"
    payload = json.dumps({"music": {"action": "popout_toggle", "tab_id": tid, "is_playing": not cur}}, ensure_ascii=False)
    return f"Toggled tab {tid} to {nxt} ('{_popout_registry[tid].get('title','')}')\n{payload}"
