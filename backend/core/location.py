import httpx

from backend.core.config import load_config
from backend.memory.knowledge_graph import get_graph

_IPGEO_URL = "http://ip-api.com/json"


def resolve_location() -> dict | None:
    """Resolve user location in order: memory graph → config → IP geolocation.
    Returns {lat, lon, city, country} or None."""
    kg = get_graph()
    memories = kg.search("user_location")
    for m in memories:
        props = m.get("properties", {})
        lat_s = props.get("lat")
        lon_s = props.get("lon")
        if lat_s and lon_s:
            try:
                return {
                    "lat": float(lat_s),
                    "lon": float(lon_s),
                    "city": props.get("city", ""),
                    "country": props.get("country", ""),
                }
            except (ValueError, TypeError):
                pass

    cfg = load_config()
    loc = cfg.get("location", {}).get("default_location", "")
    if loc:
        from backend.core.weather import geocode
        geo = geocode(loc)
        if geo:
            return geo

    try:
        resp = httpx.get(_IPGEO_URL, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return {
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "city": data.get("city", ""),
                    "country": data.get("country", ""),
                }
    except (httpx.HTTPError, ValueError):
        pass

    return None


def store_location(lat: float, lon: float, city: str = "", country: str = ""):
    kg = get_graph()
    label = city or f"{lat},{lon}"
    nid = kg._label_idx.get(label.strip().lower())
    if nid and nid in kg._nodes:
        with kg._lock:
            kg._unindex_node(kg._nodes[nid])
            kg._nodes[nid]["properties"].update({
                "lat": str(lat), "lon": str(lon),
                "city": city, "country": country,
            })
            kg._index_node(kg._nodes[nid])
            kg._save()
    else:
        kg.add_node("preference", label, {
            "lat": str(lat), "lon": str(lon),
            "city": city, "country": country,
        })
