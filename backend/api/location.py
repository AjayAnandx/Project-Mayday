from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.location import resolve_location, store_location

router = APIRouter(prefix="/api/location", tags=["location"])


class LocationPayload(BaseModel):
    lat: float
    lon: float
    city: str = ""
    country: str = ""


@router.get("")
def get_location():
    loc = resolve_location()
    if loc:
        return loc
    return {"lat": None, "lon": None, "city": None, "country": None}


@router.post("")
def set_location(payload: LocationPayload):
    store_location(payload.lat, payload.lon, payload.city, payload.country)
    return {"status": "ok"}
