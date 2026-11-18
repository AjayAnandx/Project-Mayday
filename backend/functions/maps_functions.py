"""LLM tool handlers for Google Maps (maps_* group).

Origin aliases: 'home'/'work' (config), 'me' (stored location), 'lat,lng',
or free text (geocoded). All Google calls stay server-side; the key never
reaches the frontend.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _need_key_error() -> str:
    return ("Google Maps is not set up. Tell the user to add GOOGLE_MAPS_API_KEY "
            "to .env (restricted key + billing enabled on the GCP project).")


def _here() -> tuple[float | None, float | None]:
    try:
        from backend.core.location import resolve_location
        loc = resolve_location() or {}
        return loc.get("lat"), loc.get("lon")
    except Exception:
        return None, None


def _modes(requested: str = "") -> list[str]:
    from backend.core.maps_service import _maps_cfg

    if requested and requested.strip():
        return [requested.strip()]
    cfg = _maps_cfg()
    modes = cfg.get("default_modes") or ["drive"]
    return [str(m) for m in modes][:2]


def _fmt_place(p: dict) -> str:
    bits = [f"**{p.get('name', '?')}**"]
    if p.get("rating") is not None:
        bits.append(f"{p['rating']}★ ({p.get('ratings_total', '?')} reviews)")
    if p.get("price_level"):
        bits.append(f"price {p['price_level']}")
    if p.get("open_now") is True:
        bits.append("open now")
    elif p.get("open_now") is False:
        bits.append("closed now")
    head = " ".join(bits)
    addr = p.get("address", "")
    return f"  - {head}\n    {addr} [id: {p.get('place_id', '')}]"


def maps_search_places(query: str, near: str = "", radius_m: int = 5000, limit: int = 5) -> str:
    from backend.core.maps_service import NeedsKey, resolve_point, search_places

    if not query or not query.strip():
        return "Missing required parameter: query (e.g. 'Writes Cafe')"
    try:
        lat = lng = None
        if near and near.strip():
            lat0, lng0 = _here()
            pt = resolve_point(near.strip(), lat0, lng0)
            lat, lng = pt["lat"], pt["lng"]
        else:
            lat, lng = _here()
        results = search_places(query.strip(), lat, lng, radius_m, limit)
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error searching places: {e}"
    if not results:
        return (f"No places found for '{query}'. It may be new/renamed — "
                f"try a web search for details.")
    lines = [f"Places matching '{query}' ({len(results)}):"]
    lines += [_fmt_place(p) for p in results]
    if len(results) > 1:
        lines.append("Ask which one they mean if the request needs a single destination.")
    return "\n".join(lines)


def maps_place_details(place_id: str) -> str:
    from backend.core.maps_service import NeedsKey, place_details

    if not place_id or not place_id.strip():
        return "Missing required parameter: place_id (from maps_search_places)"
    try:
        d = place_details(place_id.strip())
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error loading place details: {e}"
    lines = [f"**{d.get('name', '?')}**",
             f"{d.get('address', '')}"]
    if d.get("rating") is not None:
        lines.append(f"Rating: {d['rating']}★ ({d.get('ratings_total', '?')} reviews)")
    if d.get("price_level"):
        lines.append(f"Price: {d['price_level']}")
    if d.get("hours"):
        lines.append("Hours: " + "; ".join(d["hours"][:7]))
    if d.get("summary"):
        lines.append(f"About: {d['summary'][:400]}")
    for r in d.get("reviews", []) or []:
        lines.append(f"  - review {r.get('rating', '?')}★ by {r.get('author', '?')}: "
                     f"{(r.get('text') or '')[:200]}")
    return "\n".join(lines)


def maps_autocomplete(text: str) -> str:
    from backend.core.maps_service import NeedsKey, autocomplete

    if not text or not text.strip():
        return "Missing required parameter: text (partial place name)"
    try:
        lat, lng = _here()
        suggestions = autocomplete(text.strip(), lat, lng)
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error with autocomplete: {e}"
    if not suggestions:
        return f"No suggestions for '{text}'."
    return "Suggestions:\n" + "\n".join(
        f"  - {s['text']} [id: {s['place_id']}]" for s in suggestions)


def _route_lines(origin: str, destination: str, modes: list[str]) -> list[str]:
    from backend.core.maps_service import compute_route, fmt_distance, fmt_duration, resolve_point

    lat, lng = _here()
    o = resolve_point(origin, lat, lng)
    d = resolve_point(destination, lat, lng)
    lines = []
    for mode in modes:
        try:
            r = compute_route(o, d, mode=mode)
        except Exception as e:
            lines.append(f"  - {mode}: failed ({e})")
            continue
        best = r["best"]
        traffic = ""
        if best.get("traffic_s"):
            traffic = f" (+{fmt_duration(best['traffic_s'])} traffic)"
        lines.append(f"  - {mode}: {fmt_distance(best.get('distance_m'))}, "
                     f"{fmt_duration(best.get('duration_s'))}{traffic}")
        if best.get("description"):
            lines.append(f"    via {best['description']}")
    return lines


def maps_route(origin: str, destination: str, mode: str = "") -> str:
    from backend.core.maps_service import NeedsKey

    if not origin or not destination:
        return "Missing required parameters: origin and destination (names, 'home', 'me', or lat,lng)"
    try:
        lines = _route_lines(origin.strip(), destination.strip(), _modes(mode))
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error computing route: {e}"
    return f"Route {origin} → {destination}:\n" + "\n".join(lines)


def maps_traffic(origin: str, destination: str) -> str:
    from backend.core.maps_service import NeedsKey

    if not origin or not destination:
        return "Missing required parameters: origin and destination"
    try:
        lines = _route_lines(origin.strip(), destination.strip(), ["drive"])
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error checking traffic: {e}"
    verdict = "Check the numbers above — if in-traffic time is much higher, leave now."
    return f"Traffic {origin} → {destination}:\n" + "\n".join(lines) + f"\n{verdict}"


def maps_eta_matrix(places: list[str], origin: str = "home", mode: str = "drive") -> str:
    """Which of several destinations is quickest right now?"""
    from backend.core.maps_service import (NeedsKey, eta_matrix, fmt_duration,
                                           resolve_point, search_places)

    if not places:
        return "Missing required parameter: places (list of destination names)"
    try:
        lat, lng = _here()
        o = resolve_point(origin or "home", lat, lng)
        dests, labels = [], []
        for p in places[:10]:
            hits = search_places(p, lat, lng, max_results=1)
            if not hits:
                return f"Could not locate '{p}' — refine the name first."
            h = hits[0]
            dests.append({"lat": h["lat"], "lng": h["lng"], "label": h["name"]})
            labels.append(h["name"])
        rows = eta_matrix([o], dests, mode=mode or "drive")
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error computing ETAs: {e}"
    if not rows:
        return "No ETAs returned."
    rows.sort(key=lambda r: (r["duration_s"] is None, r["duration_s"]))
    lines = [f"Quickest from {origin} ({mode or 'drive'}):"]
    for r in rows:
        lines.append(f"  - {labels[r['to']]}: {fmt_duration(r['duration_s'])}")
    return "\n".join(lines)


def maps_optimize_trip(stops: list[str], origin: str = "home", mode: str = "drive") -> str:
    """Best visiting order for multiple stops."""
    from backend.core.maps_service import (NeedsKey, fmt_distance, fmt_duration,
                                           optimize_trip, resolve_point, search_places)

    if not stops or len(stops) < 2:
        return "Missing required parameter: stops (2+ place names)"
    try:
        lat, lng = _here()
        o = resolve_point(origin or "home", lat, lng)
        pts = []
        for s in stops[:8]:
            hits = search_places(s, lat, lng, max_results=1)
            if not hits:
                return f"Could not locate '{s}' — refine the name first."
            h = hits[0]
            pts.append({"lat": h["lat"], "lng": h["lng"], "label": h["name"]})
        trip = optimize_trip(o, pts, mode=mode or "drive")
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error optimizing trip: {e}"
    lines = [f"Best order from {origin} ({fmt_distance(trip.get('distance_m'))}, "
             f"{fmt_duration(trip.get('total_s'))} total):"]
    lines += [f"  {i + 1}. {name}" for i, name in enumerate(trip.get("order", []))]
    return "\n".join(lines)


def maps_geocode(address: str) -> str:
    from backend.core.maps_service import NeedsKey, geocode

    if not address or not address.strip():
        return "Missing required parameter: address"
    try:
        g = geocode(address.strip())
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error geocoding: {e}"
    return (f"{g['formatted']} → {g['lat']},{g['lng']}"
            + (" (cached)" if g.get("cached") else ""))


def maps_save_place(place_id: str, note: str = "") -> str:
    """Remember a liked/visited spot (personalization for future suggestions)."""
    from backend.core.maps_service import NeedsKey, place_details

    if not place_id or not place_id.strip():
        return "Missing required parameter: place_id (from maps_search_places)"
    try:
        d = place_details(place_id.strip())
    except NeedsKey:
        return _need_key_error()
    except Exception as e:
        return f"Error loading place: {e}"
    name = d.get("name", place_id)
    try:
        from backend.memory.knowledge_graph import get_graph
        get_graph().add_node("place", f"place:{place_id.strip()}",
                             {"name": name, "address": d.get("address", ""),
                              "rating": d.get("rating"), "note": note or ""})
    except Exception as e:
        return f"Place '{name}' loaded but memory save failed: {e}"
    extra = f" Note kept: {note}." if note else ""
    return f"Saved '{name}' to your places.{extra} Future food/outing suggestions will bias toward spots like it."
