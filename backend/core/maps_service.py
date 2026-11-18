"""Google Maps Platform wrapper — Places (New), Routes, Geocoding.

One restricted server-side key (GOOGLE_MAPS_API_KEY). All calls are sync
(dispatch runs them in an executor). Billing must be enabled on the GCP
project or every call returns REQUEST_DENIED.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TIMEZONE_URL = "https://maps.googleapis.com/maps/api/timezone/json"
PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTE_MATRIX_URL = "https://routes.googleapis.com/directions/v2:computeRouteMatrix"
ADDRESS_VALIDATION_URL = "https://addressvalidation.googleapis.com/v1:validateAddress"

MODE_MAP = {
    "drive": "DRIVE",
    "car": "DRIVE",
    "two-wheeler": "TWO_WHEELER",
    "two_wheeler": "TWO_WHEELER",
    "bike": "TWO_WHEELER",
    "transit": "TRANSIT",
    "walk": "WALK",
}

_geocode_cache: dict[str, tuple[float, float, str, float]] = {}


class NeedsKey(Exception):
    """Raised when no Maps key is configured — UI should guide to .env setup."""


def _maps_cfg() -> dict:
    try:
        from backend.core.config import load_config

        cfg = load_config().get("maps", {}) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def get_api_key() -> str:
    return (_maps_cfg().get("api_key") or "").strip()


def ensure_key() -> str:
    key = get_api_key()
    if not key:
        raise NeedsKey("GOOGLE_MAPS_API_KEY is not set — add it to .env "
                       "(restricted key, billing enabled on the GCP project).")
    return key


def _headers(field_mask: str = "") -> dict:
    h = {"X-Goog-Api-Key": ensure_key(), "Content-Type": "application/json"}
    if field_mask:
        h["X-Goog-FieldMask"] = field_mask
    return h


def _redact(text: object) -> str:
    """Strip key material so error strings (logs, LLM context) never leak it."""
    import re

    return re.sub(r"(key=)[^&\s'\"]+", r"\1REDACTED", str(text))


def _post(url: str, body: dict, field_mask: str = "", timeout: int = 25) -> dict | list:
    import httpx

    try:
        r = httpx.post(url, json=body, headers=_headers(field_mask), timeout=timeout)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Maps API request failed ({_redact(e)})")
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Maps API error: {data['error'].get('message', data['error'])}")
    return data


def _get(url: str, params: dict, timeout: int = 25) -> dict:
    import httpx

    safe_params = {k: ("REDACTED" if k == "key" else v) for k, v in params.items()}
    try:
        r = httpx.get(url, params=params, timeout=timeout)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Maps API request failed: {url} {_redact(safe_params)} ({_redact(e)})")
    return r.json()


def cache_ttl_hours() -> float:
    try:
        return float(_maps_cfg().get("cache_ttl_hours", 24))
    except (TypeError, ValueError):
        return 24.0


def geocode(address: str) -> dict:
    """Free-text address -> {lat, lng, formatted}. 24h cache."""
    key = ensure_key()
    norm = (address or "").strip().lower()
    if not norm:
        raise ValueError("Empty address for geocode")
    hit = _geocode_cache.get(norm)
    if hit and hit[3] > time.time():
        lat, lng, formatted, _ = hit
        return {"lat": lat, "lng": lng, "formatted": formatted, "cached": True}
    data = _get(GEOCODE_URL, {"address": address.strip(), "key": key})
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"Geocode failed for '{address}': "
                           f"{data.get('status')} {data.get('error_message', '')}".strip())
    top = data["results"][0]
    loc = top["geometry"]["location"]
    out = {"lat": loc["lat"], "lng": loc["lng"],
           "formatted": top.get("formatted_address", address), "cached": False}
    _geocode_cache[norm] = (out["lat"], out["lng"], out["formatted"],
                            time.time() + cache_ttl_hours() * 3600)
    return out


def _home_work_lng(which: str) -> tuple[float, float] | None:
    cfg = _maps_cfg()
    raw = (cfg.get(f"{which}_latlng") or "").strip()
    if "," in raw:
        try:
            lat_s, lng_s = raw.split(",", 1)
            return float(lat_s), float(lng_s)
        except ValueError:
            pass
    return None


def resolve_point(text: str, ref_lat: float | None = None,
                  ref_lng: float | None = None) -> dict:
    """Anything route-able -> {lat, lng, label}.

    Accepts 'lat,lng', 'home'/'work'/'me' aliases, or free text (geocoded).
    """
    t = (text or "").strip()
    low = t.lower()
    if low in ("home", "work"):
        ll = _home_work_lng(low)
        if ll:
            return {"lat": ll[0], "lng": ll[1], "label": low}
        cfg_text = (_maps_cfg().get(low) or "").strip()
        if cfg_text:
            g = geocode(cfg_text)
            return {"lat": g["lat"], "lng": g["lng"], "label": f"{low} ({g['formatted']})"}
        raise ValueError(f"No {low} address configured (maps.{low} in config.yaml).")
    if low in ("me", "here", "current location", "my location"):
        if ref_lat is None or ref_lng is None:
            raise ValueError("Current location unknown — set it via POST /api/location first.")
        return {"lat": ref_lat, "lng": ref_lng, "label": "current location"}
    if "," in t:
        try:
            lat_s, lng_s = t.split(",", 1)
            return {"lat": float(lat_s), "lng": float(lng_s), "label": t}
        except ValueError:
            pass
    g = geocode(t)
    return {"lat": g["lat"], "lng": g["lng"], "label": g["formatted"]}


def _latlng(p: dict) -> dict:
    return {"location": {"latLng": {"latitude": p["lat"], "longitude": p["lng"]}}}


def search_places(text: str, lat: float | None = None, lon: float | None = None,
                  radius_m: int = 5000, max_results: int = 5) -> list[dict]:
    ensure_key()
    body: dict = {"textQuery": text.strip(), "maxResultCount": max(1, min(max_results, 20))}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon},
                                           "radius": float(radius_m)}}
    data = _post(PLACES_SEARCH_URL, body,
                 "places.id,places.displayName,places.formattedAddress,"
                 "places.rating,places.userRatingCount,places.priceLevel,"
                 "places.currentOpeningHours,places.location")
    out = []
    for p in (data.get("places", []) if isinstance(data, dict) else []) or []:
        hours = p.get("currentOpeningHours") or {}
        loc = (p.get("location") or {})
        out.append({
            "place_id": p.get("id", ""),
            "name": ((p.get("displayName") or {}).get("text", "")),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "ratings_total": p.get("userRatingCount"),
            "price_level": p.get("priceLevel"),
            "open_now": hours.get("openNow"),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
        })
    return out


def place_details(place_id: str) -> dict:
    ensure_key()
    if not place_id or not place_id.strip():
        raise ValueError("Empty place_id")
    data = _get(PLACE_DETAILS_URL.format(place_id=place_id.strip()),
                {"key": ensure_key(),
                 "fields": "displayName,formattedAddress,rating,userRatingCount,"
                           "priceLevel,regularOpeningHours,editorialSummary,reviews"})
    hours = data.get("regularOpeningHours") or {}
    reviews = []
    for r in (data.get("reviews", []) or [])[:3]:
        reviews.append({"author": ((r.get("authorAttribution") or {}).get("displayName", "?")),
                        "rating": r.get("rating"), "text": (r.get("text") or {}).get("text", "")[:300]})
    return {
        "name": ((data.get("displayName") or {}).get("text", "")),
        "address": data.get("formattedAddress", ""),
        "rating": data.get("rating"),
        "ratings_total": data.get("userRatingCount"),
        "price_level": data.get("priceLevel"),
        "hours": hours.get("weekdayDescriptions", []),
        "summary": ((data.get("editorialSummary") or {}).get("text", "")),
        "reviews": reviews,
    }


def autocomplete(text: str, lat: float | None = None, lon: float | None = None) -> list[dict]:
    ensure_key()
    body: dict = {"input": text.strip()}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon},
                                           "radius": 20000.0}}
    data = _post(PLACES_AUTOCOMPLETE_URL, body,
                 "suggestions.placePrediction.placeId,"
                 "suggestions.placePrediction.text")
    out = []
    for s in (data.get("suggestions", []) if isinstance(data, dict) else []) or []:
        pred = s.get("placePrediction") or {}
        if pred.get("placeId"):
            out.append({"place_id": pred["placeId"],
                        "text": ((pred.get("text") or {}).get("text", ""))})
    return out


def _travel_mode(mode: str) -> str:
    return MODE_MAP.get((mode or "drive").strip().lower(), "DRIVE")


def _route_avoid() -> dict:
    cfg = _maps_cfg()
    avoid = cfg.get("avoid") or []
    mods: dict = {}
    if "tolls" in avoid:
        mods["avoidTolls"] = True
    if "highways" in avoid:
        mods["avoidHighways"] = True
    return mods


def compute_route(origin: dict, destination: dict, mode: str = "drive",
                  alternatives: bool = False) -> dict:
    """Route between two resolved points. Returns times incl. traffic delta."""
    ensure_key()
    travel = _travel_mode(mode)
    body: dict = {
        "origin": {"address": origin.get("label") or f"{origin['lat']},{origin['lng']}"},
        "destination": {"address": destination.get("label") or f"{destination['lat']},{destination['lng']}"},
        "travelMode": travel,
        "routingPreference": "TRAFFIC_AWARE" if travel in ("DRIVE", "TWO_WHEELER") else "TRAFFIC_UNAWARE",
        "computeAlternativeRoutes": bool(alternatives),
        "units": "METRIC",
        "languageCode": "en",
    }
    mods = _route_avoid()
    if mods:
        body["routeModifiers"] = mods
    if travel in ("DRIVE", "TWO_WHEELER"):
        import datetime as _dt
        body["departureTime"] = (_dt.datetime.now(_dt.timezone.utc)
                                 + _dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    data = _post(ROUTES_URL, body,
                 "routes.duration,routes.staticDuration,routes.distanceMeters,"
                 "routes.description,routes.legs")
    routes = data.get("routes", []) if isinstance(data, dict) else []
    if not routes:
        raise RuntimeError("No route found.")
    parsed = [_parse_route(r) for r in routes]
    return {"routes": parsed, "best": parsed[0], "mode": travel}


def _parse_route(r: dict) -> dict:
    def _secs(v) -> int | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip().rstrip("s")
        try:
            return int(float(s))
        except ValueError:
            return None

    dur, static = _secs(r.get("duration")), _secs(r.get("staticDuration"))
    dist = r.get("distanceMeters")
    legs = []
    for leg in r.get("legs", []) or []:
        steps = []
        for st in (leg.get("steps", []) or [])[:8]:
            nav = st.get("navigationInstruction") or {}
            if nav.get("instructions"):
                steps.append(nav["instructions"])
        legs.append({"summary": (leg.get("localizedValues") or {}).get("distance", {}).get("text", ""),
                     "steps": steps})
    return {"duration_s": dur, "static_s": static,
            "traffic_s": (dur - static) if dur is not None and static is not None else None,
            "distance_m": dist, "description": r.get("description", ""), "legs": legs}


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    m = max(0, int(round(seconds / 60)))
    if m < 60:
        return f"{m} min"
    return f"{m // 60}h {m % 60}m"


def fmt_distance(meters: int | None) -> str:
    if meters is None:
        return "?"
    km = meters / 1000
    return f"{km:.1f} km"


def eta_matrix(origins: list[dict], destinations: list[dict], mode: str = "drive") -> list[dict]:
    """Many-to-many ETAs (cap 10x10). Streaming response -> parsed list."""
    import httpx

    ensure_key()
    travel = _travel_mode(mode)
    body = {
        "origins": [{"waypoint": {"address": o.get("label") or f"{o['lat']},{o['lng']}"}} for o in origins[:10]],
        "destinations": [{"waypoint": {"address": d.get("label") or f"{d['lat']},{d['lng']}"}} for d in destinations[:10]],
        "travelMode": travel,
    }
    r = httpx.post(ROUTE_MATRIX_URL, json=body, headers=_headers(
        "originIndex,destinationIndex,duration,distanceMeters,condition"), timeout=40)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            import json as _json
            el = _json.loads(line)
        except ValueError:
            continue
        if "duration" not in el:
            continue
        dur_s = _parse_route({"duration": el["duration"]})["duration_s"]
        out.append({"from": el.get("originIndex"), "to": el.get("destinationIndex"),
                    "duration_s": dur_s, "distance_m": el.get("distanceMeters")})
    return out


def optimize_trip(origin: dict, stops: list[dict], destination: dict | None = None,
                  mode: str = "drive") -> dict:
    """Best visiting order for stops. Returns order + total time."""
    ensure_key()
    dest = destination or stops[-1]
    mids = stops if destination else stops[:-1]
    body = {
        "origin": {"address": origin.get("label") or f"{origin['lat']},{origin['lng']}"},
        "destination": {"address": dest.get("label") or f"{dest['lat']},{dest['lng']}"},
        "intermediates": [{"address": s.get("label") or f"{s['lat']},{s['lng']}"} for s in mids],
        "travelMode": _travel_mode(mode),
        "optimizeWaypointOrder": True,
        "units": "METRIC",
        "languageCode": "en",
    }
    data = _post(ROUTES_URL, body,
                 "routes.duration,routes.distanceMeters,"
                 "routes.optimizedIntermediateWaypointIndex")
    routes = data.get("routes", []) if isinstance(data, dict) else []
    if not routes:
        raise RuntimeError("No trip found.")
    r = routes[0]
    parsed = _parse_route(r)
    order = r.get("optimizedIntermediateWaypointIndex", list(range(len(mids))))
    ordered_stops = [mids[i] for i in order if 0 <= i < len(mids)]
    return {"order": [s.get("label", "") for s in ordered_stops],
            "total_s": parsed["duration_s"], "distance_m": parsed["distance_m"]}


def validate_address(address_lines: list[str], region: str = "IN") -> dict:
    """Clean/verify an address (setup-time for home/work)."""
    ensure_key()
    data = _post(f"{ADDRESS_VALIDATION_URL}?key={ensure_key()}",
                 {"address": {"regionCode": region, "addressLines": address_lines}}, "")
    res = (data.get("result", {}) if isinstance(data, dict) else {}) or {}
    verdict = res.get("verdict") or {}
    geo = res.get("geocode") or {}
    loc = ((geo.get("location") or {}))
    latlng = loc.get("latitude"), loc.get("longitude")
    return {
        "valid": bool(verdict.get("addressComplete", False)),
        "formatted": (res.get("address") or {}).get("formattedAddress", ""),
        "lat": latlng[0],
        "lng": latlng[1],
        "verdict": {k: v for k, v in verdict.items() if isinstance(v, bool)},
    }


def timezone_at(lat: float, lng: float) -> dict:
    data = _get(TIMEZONE_URL, {"location": f"{lat},{lng}",
                               "timestamp": int(time.time()), "key": ensure_key()})
    if data.get("status") != "OK":
        raise RuntimeError(f"Timezone lookup failed: {data.get('status')} {data.get('errorMessage', '')}")
    return {"tz_id": data.get("timeZoneId"), "tz_name": data.get("timeZoneName"),
            "offset_s": data.get("rawOffset", 0) + data.get("dstOffset", 0)}
