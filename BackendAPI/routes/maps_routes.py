"""
Server-side proxy for Google Maps *web service* APIs.

Why this exists
---------------
The three mobile apps each ship a Google Maps key restricted to their own
package/bundle id and to the **Maps SDK** only. That restriction is what makes a
key safe to embed in an APK — but it also means those keys cannot call web
services such as Directions, and a key that *could* would be usable by anyone
who unzipped the binary.

The rider app used to call the Directions API straight from the client with the
shared, unrestricted key. That is both the vulnerability and, now that the key
is gone, the reason the route polyline stopped rendering.

So the route lookup moves here, behind:
  * authentication — only signed-in users of the platform,
  * a rate limit — one rider redrawing a route cannot burn the quota,
  * a Redis cache — identical legs are answered without touching Google,
  * a single server-side key (`GOOGLE_MAPS_SERVER_API_KEY`) that never leaves
    the server and is IP-restricted in the Cloud Console.

The response is deliberately reduced to what the client draws. Google's payload
is large and forwarding it verbatim would leak quota metadata and grow the
mobile parse cost for no benefit.
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.redis_client import cache_get, cache_set
from core.redis_client import redis_limiter as limiter
from dependencies.auth_dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# ~11 m at the equator. Two requests that round to the same grid cell get the
# same road route, so caching at this precision is safe and lifts the hit rate
# enormously while a rider's GPS jitters in place.
_COORD_PRECISION = 4

# A road layout does not change in an hour; traffic-independent geometry is the
# only thing we serve. Long enough to absorb a whole delivery's worth of
# redraws, short enough that a closure is picked up the same day.
_CACHE_TTL_SECONDS = 3600

_ALLOWED_MODES = {"driving", "walking", "bicycling", "two_wheeler"}

# ── Places ────────────────────────────────────────────────────────────────
# Address search used to run against Photon (photon.komoot.io, OpenStreetMap)
# directly from the apps. That was a stopgap: it needs no key, but it is a free
# community endpoint with no availability guarantee, thin coverage of Kenyan
# estates and informal addresses, and it puts the platform's address quality at
# the mercy of a third party nobody has a contract with. Google Places is what
# customers expect a delivery app to find.
#
# It cannot be called from the apps: their embedded keys are restricted to the
# Maps *SDK*, and a key permissive enough to call Places would be extractable
# from the APK and billable by anyone who found it.

#: Predictions for the same prefix are identical for everyone. Short, because
#: this exists to absorb a user's own backtracking (typing "kili", deleting to
#: "kil", retyping) rather than to warehouse Google's data.
_AUTOCOMPLETE_CACHE_TTL_SECONDS = 300

#: A place's coordinates do not move. Longer, but still bounded — Google's terms
#: allow caching place ids indefinitely and other fields only temporarily.
_PLACE_DETAILS_CACHE_TTL_SECONDS = 86_400

#: Below this a prefix matches half of Nairobi; the request is pure cost.
_MIN_AUTOCOMPLETE_INPUT = 2
_MAX_AUTOCOMPLETE_INPUT = 200

#: Where the platform operates. Sent to Google as a bias/restriction so a search
#: for "Westlands" cannot return a Westlands in another country.
_DEFAULT_COUNTRY = "ke"
_ALLOWED_COUNTRIES = {"ke", "ug", "tz", "rw"}

#: Only the fields the clients actually render. Places Details is billed by SKU
#: and asking for everything silently moves the request to a dearer tier, so the
#: mask is a cost control as much as a payload one.
_PLACE_DETAIL_FIELDS = "place_id,geometry/location,formatted_address,name"


def _clean_session_token(token: str | None) -> str | None:
    """Validate the client's autocomplete session token.

    Google bills a session — the keystrokes plus the one Details call — as a
    single unit when they share a token, which is materially cheaper than
    billing each keystroke. The token is opaque to us, so it is passed through;
    but it is client-supplied and ends up in an outbound URL, so it is
    constrained to a UUID-ish shape rather than forwarded blind.
    """
    if not token:
        return None
    token = token.strip()
    if not (8 <= len(token) <= 64):
        return None
    if not all(c.isalnum() or c in "-_" for c in token):
        return None
    return token


def _country_component(country: str | None) -> str:
    code = (country or _DEFAULT_COUNTRY).strip().lower()
    if code not in _ALLOWED_COUNTRIES:
        raise HTTPException(status_code=400, detail="Unsupported country.")
    return f"country:{code}"


async def _call_google(url: str, params: dict, *, what: str) -> dict:
    """One Google web-service call, with this module's error contract.

    `error_message` names the Cloud project and sometimes the key, so it is
    logged and never returned. Every upstream problem becomes a 502 so the
    clients can apply one fallback rule instead of parsing Google's statuses.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("%s upstream failure: %s", what, exc)
        raise HTTPException(status_code=502, detail=f"{what} is unavailable right now.")

    status = payload.get("status")
    if status in ("OK", "ZERO_RESULTS"):
        return payload

    logger.error(
        "%s rejected: status=%s message=%s", what, status, payload.get("error_message")
    )
    if status == "OVER_QUERY_LIMIT":
        # Distinct from a broken request: the deployment has run out of quota or
        # billing, and that is an operational alert, not a client error.
        raise HTTPException(status_code=503, detail=f"{what} is temporarily over quota.")
    raise HTTPException(status_code=502, detail=f"{what} is unavailable right now.")


def _server_key() -> str:
    key = os.getenv("GOOGLE_MAPS_SERVER_API_KEY", "").strip()
    if not key:
        # 503, not 500: the deployment is misconfigured but the client's request
        # was valid, and the apps degrade to a straight line when they see this.
        raise HTTPException(
            status_code=503,
            detail="Route lookup is not configured on this server.",
        )
    return key


def _validate_coord(value: float, *, name: str, limit: float) -> float:
    if value != value or abs(value) > limit:  # NaN or out of range
        raise HTTPException(status_code=400, detail=f"Invalid {name}.")
    return value


@router.get("/directions")
@limiter.limit("60/minute")
async def get_directions(
    request: Request,
    origin_lat: float = Query(...),
    origin_lng: float = Query(...),
    dest_lat: float = Query(...),
    dest_lng: float = Query(...),
    mode: str = Query("driving"),
    user=Depends(get_current_user),
):
    """
    Road route between two points, as an encoded polyline.

    Returns `{polyline, distance_meters, duration_seconds, cached}`. On any
    upstream failure the caller should fall back to a straight line rather than
    blocking the delivery UI — a missing route is cosmetic, a stuck screen is not.
    """
    if mode not in _ALLOWED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported travel mode. Use one of: {', '.join(sorted(_ALLOWED_MODES))}.",
        )

    for value, name in (
        (origin_lat, "origin_lat"),
        (dest_lat, "dest_lat"),
    ):
        _validate_coord(value, name=name, limit=90.0)
    for value, name in (
        (origin_lng, "origin_lng"),
        (dest_lng, "dest_lng"),
    ):
        _validate_coord(value, name=name, limit=180.0)

    o_lat = round(origin_lat, _COORD_PRECISION)
    o_lng = round(origin_lng, _COORD_PRECISION)
    d_lat = round(dest_lat, _COORD_PRECISION)
    d_lng = round(dest_lng, _COORD_PRECISION)

    cache_key = f"directions:{mode}:{o_lat},{o_lng}:{d_lat},{d_lng}"
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    key = _server_key()

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                GOOGLE_DIRECTIONS_URL,
                params={
                    "origin": f"{o_lat},{o_lng}",
                    "destination": f"{d_lat},{d_lng}",
                    "mode": mode,
                    "key": key,
                },
            )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Directions upstream failure: %s", exc)
        raise HTTPException(status_code=502, detail="Route lookup is unavailable right now.")

    status = payload.get("status")
    if status == "ZERO_RESULTS":
        raise HTTPException(status_code=404, detail="No route found between those points.")
    if status != "OK":
        # error_message can name the project or the key; log it, never return it.
        logger.error(
            "Directions rejected: status=%s message=%s", status, payload.get("error_message")
        )
        raise HTTPException(status_code=502, detail="Route lookup is unavailable right now.")

    routes = payload.get("routes") or []
    if not routes:
        raise HTTPException(status_code=404, detail="No route found between those points.")

    route = routes[0]
    legs = route.get("legs") or []
    result = {
        "polyline": (route.get("overview_polyline") or {}).get("points", ""),
        "distance_meters": sum((leg.get("distance") or {}).get("value", 0) for leg in legs),
        "duration_seconds": sum((leg.get("duration") or {}).get("value", 0) for leg in legs),
    }

    if not result["polyline"]:
        raise HTTPException(status_code=404, detail="No route found between those points.")

    await cache_set(cache_key, result, ttl_seconds=_CACHE_TTL_SECONDS)
    return {**result, "cached": False}


@router.get("/places/autocomplete")
@limiter.limit("60/minute")
async def places_autocomplete(
    request: Request,
    input: str = Query(..., min_length=_MIN_AUTOCOMPLETE_INPUT, max_length=_MAX_AUTOCOMPLETE_INPUT),
    country: str | None = Query(None),
    session_token: str | None = Query(None),
    user=Depends(get_current_user),
):
    """Address predictions for a partial query.

    Returns `{predictions: [{place_id, description, structured_formatting}]}` —
    the same shape the clients already render, reduced to the three fields they
    use. `ZERO_RESULTS` is an empty list, not an error: an unrecognised prefix
    is an ordinary state while someone is still typing.
    """
    query = input.strip()
    if len(query) < _MIN_AUTOCOMPLETE_INPUT:
        return {"predictions": [], "cached": False}

    component = _country_component(country)

    # Case-folded so "Kilimani" and "kilimani" share an entry. The session token
    # is deliberately *not* part of the key — it varies per user and would make
    # the cache useless, and predictions do not differ between sessions.
    cache_key = f"places:auto:{component}:{query.casefold()}"
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    params = {
        "input": query,
        "components": component,
        "key": _server_key(),
    }
    token = _clean_session_token(session_token)
    if token:
        params["sessiontoken"] = token

    payload = await _call_google(GOOGLE_AUTOCOMPLETE_URL, params, what="Address search")

    predictions = [
        {
            "place_id": p.get("place_id"),
            "description": p.get("description", ""),
            "structured_formatting": {
                "main_text": (p.get("structured_formatting") or {}).get("main_text", ""),
                "secondary_text": (p.get("structured_formatting") or {}).get("secondary_text", ""),
            },
        }
        for p in (payload.get("predictions") or [])
        if p.get("place_id")
    ]

    result = {"predictions": predictions}
    await cache_set(cache_key, result, ttl_seconds=_AUTOCOMPLETE_CACHE_TTL_SECONDS)
    return {**result, "cached": False}


@router.get("/places/details")
@limiter.limit("60/minute")
async def place_details(
    request: Request,
    place_id: str = Query(..., min_length=1, max_length=512),
    session_token: str | None = Query(None),
    user=Depends(get_current_user),
):
    """Coordinates and formatted address for a prediction the user picked.

    Returns `{geometry: {location: {lat, lng}}, formatted_address, name}`, which
    is the subset of Google's `result` the clients read. A place without
    coordinates is a 404 rather than a half-empty success — the callers use this
    to drop a pin, and silently returning no location would strand them.
    """
    cache_key = f"places:details:{place_id}"
    cached = await cache_get(cache_key)
    if cached:
        return {**cached, "cached": True}

    params = {
        "place_id": place_id,
        "fields": _PLACE_DETAIL_FIELDS,
        "key": _server_key(),
    }
    token = _clean_session_token(session_token)
    if token:
        params["sessiontoken"] = token

    payload = await _call_google(GOOGLE_PLACE_DETAILS_URL, params, what="Place lookup")

    detail = payload.get("result") or {}
    location = ((detail.get("geometry") or {}).get("location")) or {}
    lat, lng = location.get("lat"), location.get("lng")
    if lat is None or lng is None:
        raise HTTPException(status_code=404, detail="That place has no location.")

    result = {
        "geometry": {"location": {"lat": lat, "lng": lng}},
        "formatted_address": detail.get("formatted_address") or detail.get("name") or "",
        "name": detail.get("name") or "",
    }
    await cache_set(cache_key, result, ttl_seconds=_PLACE_DETAILS_CACHE_TTL_SECONDS)
    return {**result, "cached": False}
