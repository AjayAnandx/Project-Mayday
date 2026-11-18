"""Google Maps service + tools — mocked httpx, zero quota burn.

Covers: key gate, geocode parse+cache, places parse, route traffic delta,
matrix parse, handler formatting, classifier intent, registry wiring.
"""
import json


class _Resp:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text or json.dumps(payload)

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _patch_cfg(monkeypatch, **over):
    import backend.core.maps_service as ms

    base = {"api_key": "test-key", "default_modes": ["drive", "two-wheeler"],
            "cache_ttl_hours": 24}
    base.update(over)
    monkeypatch.setattr(ms, "_maps_cfg", lambda: dict(base))
    ms._geocode_cache.clear()
    return ms


def _patch_http(monkeypatch, post=None, get=None):
    import httpx

    calls = {"post": [], "get": []}

    def fake_post(url, json=None, headers=None, timeout=25):
        calls["post"].append(url)
        return _Resp(post(url, json) if callable(post) else post)

    def fake_get(url, params=None, timeout=25):
        calls["get"].append(url)
        return _Resp(get(url, params) if callable(get) else get)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_missing_key_raises(monkeypatch):
    import backend.core.maps_service as ms

    monkeypatch.setattr(ms, "_maps_cfg", lambda: {"api_key": ""})
    try:
        ms.ensure_key()
    except ms.NeedsKey:
        return
    raise AssertionError("expected NeedsKey")


def test_errors_never_leak_key(monkeypatch):
    """Regression: a 403 error string echoed the full ?key= value into logs
    and LLM context. Sanitized paths must say REDACTED, never the key."""
    import httpx
    import backend.core.maps_service as ms

    ms = _patch_cfg(monkeypatch, api_key="SECRETKEY123")

    class _Boom:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "403 Client Error for url 'https://x.test/v1/p?key=SECRETKEY123'",
                request=None, response=None)

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Boom())
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Boom())
    for fn in (lambda: ms.search_places("x"),
               lambda: ms.geocode("Ambattur, Chennai")):
        try:
            fn()
        except RuntimeError as e:
            assert "SECRETKEY123" not in str(e), str(e)[:200]
            assert "REDACTED" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


def test_geocode_parses_and_caches(monkeypatch):
    ms = _patch_cfg(monkeypatch)
    calls = _patch_http(monkeypatch, get=lambda url, params: {
        "status": "OK", "results": [{
            "formatted_address": "Ambattur, Chennai",
            "geometry": {"location": {"lat": 13.11, "lng": 80.16}}}]})

    first = ms.geocode("Ambattur, Chennai")
    assert (first["lat"], first["lng"]) == (13.11, 80.16)
    second = ms.geocode("ambattur, CHENNAI")
    assert second.get("cached") is True
    assert len(calls["get"]) == 1


def test_geocode_failure_surfaces_status(monkeypatch):
    ms = _patch_cfg(monkeypatch)
    _patch_http(monkeypatch, get=lambda url, params: {
        "status": "REQUEST_DENIED", "error_message": "billing off"})
    try:
        ms.geocode("Nowhere")
    except RuntimeError as e:
        assert "REQUEST_DENIED" in str(e)
        return
    raise AssertionError("expected RuntimeError")


def test_search_places_parses(monkeypatch):
    ms = _patch_cfg(monkeypatch)
    _patch_http(monkeypatch, post=lambda url, body: {"places": [{
        "id": "p1", "displayName": {"text": "Writes Cafe"},
        "formattedAddress": "Anna Nagar", "rating": 4.3,
        "userRatingCount": 120, "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
        "location": {"latitude": 13.08, "longitude": 80.21}}]})
    out = ms.search_places("Writes Cafe", 13.0, 80.2)
    assert len(out) == 1
    assert out[0]["name"] == "Writes Cafe"
    assert out[0]["open_now"] is True
    assert out[0]["place_id"] == "p1"


def test_compute_route_traffic_delta(monkeypatch):
    ms = _patch_cfg(monkeypatch)
    _patch_http(monkeypatch, post=lambda url, body: {"routes": [{
        "duration": "2100s", "staticDuration": "1500s",
        "distanceMeters": 12000, "description": "via Mount Rd", "legs": []}]})
    r = ms.compute_route({"lat": 1, "lng": 1, "label": "A"},
                         {"lat": 2, "lng": 2, "label": "B"}, mode="drive")
    assert r["best"]["duration_s"] == 2100
    assert r["best"]["traffic_s"] == 600
    assert ms.fmt_duration(2100) == "35 min"
    assert ms.fmt_distance(12500) == "12.5 km"


def test_eta_matrix_parses_stream(monkeypatch):
    import httpx

    ms = _patch_cfg(monkeypatch)

    class _Stream(_Resp):
        def __init__(self):
            self.text = ('{"originIndex": 0, "destinationIndex": 1, "duration": "900s", '
                         '"distanceMeters": 5000}\n'
                         '{"originIndex": 0, "destinationIndex": 0, "duration": "300s", '
                         '"distanceMeters": 1000}\n')

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Stream())
    rows = ms.eta_matrix([{"lat": 1, "lng": 1}], [{"lat": 2, "lng": 2}] * 2)
    assert len(rows) == 2
    assert rows[0]["duration_s"] == 900


def test_resolve_point_aliases(monkeypatch):
    ms = _patch_cfg(monkeypatch, home_latlng="13.0,80.2", home="Home addr")
    pt = ms.resolve_point("home")
    assert (pt["lat"], pt["lng"]) == (13.0, 80.2)
    pt2 = ms.resolve_point("13.5,80.1")
    assert (pt2["lat"], pt2["lng"]) == (13.5, 80.1)


def test_maps_search_handler_formats(monkeypatch):
    import backend.functions.maps_functions as mf

    monkeypatch.setattr(mf, "_here", lambda: (13.0, 80.2))
    import backend.core.maps_service as ms
    monkeypatch.setattr(ms, "resolve_point", lambda *a, **k: {"lat": 1, "lng": 1, "label": "x"})
    monkeypatch.setattr(ms, "search_places", lambda *a, **k: [
        {"place_id": "p1", "name": "Writes Cafe", "address": "Anna Nagar",
         "rating": 4.3, "ratings_total": 100, "price_level": None, "open_now": True,
         "lat": 1, "lng": 1}])
    out = mf.maps_search_places("Writes Cafe")
    assert "Writes Cafe" in out and "4.3" in out and "p1" in out


def test_maps_handler_without_key(monkeypatch):
    import backend.functions.maps_functions as mf
    import backend.core.maps_service as ms

    monkeypatch.setattr(ms, "_maps_cfg", lambda: {"api_key": ""})
    assert "GOOGLE_MAPS_API_KEY" in mf.maps_search_places("x")
    assert "GOOGLE_MAPS_API_KEY" in mf.maps_route("a", "b")


def test_classifier_routes_places_intent():
    from backend.core.query_classifier import QueryClassifier

    for text in ("traffic to the airport", "i need to go to ambattur",
                 "cafes near me", "best route home"):
        intent = QueryClassifier().classify(text)
        assert intent.intent == "places", (text, intent.intent)
        assert "maps" in intent.active_groups


def test_maps_tools_registered():
    from backend.assistant.function_registry import (
        FUNCTION_MAP, LOCAL_TOOL_DEFINITIONS, _PARAM_ALIASES,
        _validate_tool_definitions,
    )
    from backend.api.chat import GROUP_SETS

    names = ["maps_search_places", "maps_place_details", "maps_autocomplete",
             "maps_route", "maps_traffic", "maps_eta_matrix",
             "maps_optimize_trip", "maps_geocode", "maps_save_place"]
    for n in names:
        assert n in FUNCTION_MAP, n
        assert n in GROUP_SETS["maps"], n
    defs = [t for t in LOCAL_TOOL_DEFINITIONS if t["function"]["name"] in names]
    assert len(defs) == 9
    assert len(_validate_tool_definitions(defs)) == 9
    assert _PARAM_ALIASES["maps_route"]["from"] == "origin"
