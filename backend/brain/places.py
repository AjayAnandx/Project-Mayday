"""Turn coordinates into a coarse place label; the coordinates themselves are never stored."""
from __future__ import annotations

import math

from backend.core.config import load_config


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _parse(latlng) -> tuple[float, float] | None:
    try:
        lat, lon = (float(x) for x in str(latlng).split(","))
        return lat, lon
    except (TypeError, ValueError):
        return None


def known_places() -> list[tuple[str, tuple[float, float]]]:
    places = []
    home = _parse((load_config().get("maps", {}) or {}).get("home_latlng"))
    if home:
        places.append(("home", home))
    try:
        from backend.memory.knowledge_graph import get_graph
        for n in get_graph().get_nodes_by_type("place"):
            p = n.get("properties", {}) or {}
            ll = _parse(f"{p.get('lat')},{p.get('lon')}")
            if ll:
                places.append((p.get("name") or n["label"], ll))
    except Exception:
        pass
    return places


def place_label(lat: float, lon: float, radius_km: float = 0.4, travel_km: float = 50) -> str:
    here = (lat, lon)
    best = None
    for name, ll in known_places():
        d = _km(here, ll)
        if d <= radius_km and (best is None or d < best[1]):
            best = (name, d)
    if best:
        return best[0]
    home = next((ll for name, ll in known_places() if name == "home"), None)
    if home and _km(here, home) > travel_km:
        return "travelling"
    return "out"
