"""
Places autocomplete/details proxy.

Address search used to run against Photon (photon.komoot.io, OpenStreetMap)
straight from the apps. Moving it to Google could not mean calling Google from
the apps: their Maps keys are restricted to the Maps *SDK* and are rejected by
Places outright, and a key permissive enough to work from JS would be
extractable from the APK and billable by whoever found it.

So the same rules as the Directions proxy apply — authenticated, rate-limited,
cached, one server-side key — plus session tokens, because Google bills a
search as one unit only when the keystrokes and the final lookup share one.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from main import app
from routes import maps_routes


def _request(path: str = "/api/maps/places/autocomplete"):
    """slowapi rejects anything that is not a real starlette Request."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "app": app,
        }
    )


# ── Session tokens ────────────────────────────────────────────────────────


def test_a_well_formed_session_token_is_passed_through():
    assert maps_routes._clean_session_token("k3n2p1-abcdef12") == "k3n2p1-abcdef12"


def test_a_missing_session_token_is_simply_absent():
    """Not an error: without one Google bills per keystroke, which still works."""
    assert maps_routes._clean_session_token(None) is None
    assert maps_routes._clean_session_token("") is None


@pytest.mark.parametrize(
    "token",
    [
        "short",                      # too short
        "x" * 65,                     # too long
        "tok&key=leaked",             # would inject a parameter into the outbound URL
        "tok en",                     # whitespace
        "../../etc/passwd",           # path traversal shape
    ],
)
def test_a_malformed_session_token_is_dropped_not_forwarded(token):
    """It is client-supplied and ends up in a URL we build, so it is constrained."""
    assert maps_routes._clean_session_token(token) is None


# ── Country restriction ───────────────────────────────────────────────────


def test_the_default_country_is_applied():
    assert maps_routes._country_component(None) == "country:ke"


def test_an_allowed_country_is_accepted_case_insensitively():
    assert maps_routes._country_component("UG") == "country:ug"


def test_an_unsupported_country_is_rejected():
    """Otherwise a search for "Westlands" can return one on another continent."""
    with pytest.raises(HTTPException) as exc:
        maps_routes._country_component("us")
    assert exc.value.status_code == 400


# ── Upstream error contract ───────────────────────────────────────────────


def _google_response(payload: dict):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    ctx = AsyncMock()
    ctx.__aenter__.return_value = client
    return ctx, client


@pytest.mark.asyncio
async def test_googles_error_message_is_never_returned_to_the_client():
    """`error_message` names the Cloud project and sometimes the key itself."""
    ctx, _ = _google_response(
        {"status": "REQUEST_DENIED", "error_message": "project drop-1234 key AIzaSyLEAK"}
    )
    with patch("httpx.AsyncClient", return_value=ctx):
        with pytest.raises(HTTPException) as exc:
            await maps_routes._call_google("https://x", {}, what="Address search")

    assert exc.value.status_code == 502
    assert "AIzaSyLEAK" not in str(exc.value.detail)
    assert "drop-1234" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_running_out_of_quota_is_a_503_not_a_502():
    """A distinct code because it is an operational alert, not a bad request."""
    ctx, _ = _google_response({"status": "OVER_QUERY_LIMIT"})
    with patch("httpx.AsyncClient", return_value=ctx):
        with pytest.raises(HTTPException) as exc:
            await maps_routes._call_google("https://x", {}, what="Address search")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_zero_results_is_a_success_not_an_error():
    """An unrecognised prefix is an ordinary state while someone is still typing."""
    ctx, _ = _google_response({"status": "ZERO_RESULTS", "predictions": []})
    with patch("httpx.AsyncClient", return_value=ctx):
        payload = await maps_routes._call_google("https://x", {}, what="Address search")
    assert payload["status"] == "ZERO_RESULTS"


# ── Endpoint behaviour ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autocomplete_reduces_the_payload_to_what_the_client_renders():
    ctx, client = _google_response(
        {
            "status": "OK",
            "predictions": [
                {
                    "place_id": "abc123",
                    "description": "Kilimani, Nairobi, Kenya",
                    "structured_formatting": {"main_text": "Kilimani", "secondary_text": "Nairobi, Kenya"},
                    "terms": [{"offset": 0, "value": "Kilimani"}],
                    "matched_substrings": [{"length": 4, "offset": 0}],
                },
                {"description": "no place_id, unusable"},
            ],
        }
    )
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patch("routes.maps_routes.cache_set", AsyncMock()):
        result = await maps_routes.places_autocomplete(
            request=_request(), input="kilimani", country=None, session_token="sess-12345678", user={}
        )

    assert len(result["predictions"]) == 1, "a prediction without a place_id is unusable"
    assert set(result["predictions"][0]) == {"place_id", "description", "structured_formatting"}

    sent = client.get.call_args.kwargs["params"]
    assert sent["sessiontoken"] == "sess-12345678"
    assert sent["components"] == "country:ke"


@pytest.mark.asyncio
async def test_autocomplete_serves_a_cache_hit_without_calling_google():
    cached = {"predictions": [{"place_id": "x", "description": "d", "structured_formatting": {}}]}
    with patch("routes.maps_routes.cache_get", AsyncMock(return_value=cached)), \
         patch("httpx.AsyncClient") as client:
        result = await maps_routes.places_autocomplete(
            request=_request(), input="kilimani", country=None, session_token=None, user={}
        )
    assert result["cached"] is True
    client.assert_not_called()


@pytest.mark.asyncio
async def test_place_details_without_coordinates_is_a_404():
    """The callers use this to drop a pin; a location-less success would strand them."""
    ctx, _ = _google_response({"status": "OK", "result": {"name": "Somewhere"}})
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patch("routes.maps_routes.cache_set", AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await maps_routes.place_details(
                request=_request("/api/maps/places/details"), place_id="abc", session_token=None, user={}
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_place_details_requests_only_the_fields_we_use():
    """Places Details is billed by SKU; an unmasked request costs a dearer tier."""
    ctx, client = _google_response(
        {
            "status": "OK",
            "result": {
                "geometry": {"location": {"lat": -1.29, "lng": 36.79}},
                "formatted_address": "Kilimani, Nairobi",
                "name": "Kilimani",
            },
        }
    )
    with patch("httpx.AsyncClient", return_value=ctx), \
         patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patch("routes.maps_routes.cache_set", AsyncMock()):
        result = await maps_routes.place_details(
            request=_request("/api/maps/places/details"), place_id="abc", session_token=None, user={}
        )

    assert result["geometry"]["location"] == {"lat": -1.29, "lng": 36.79}
    assert "fields" in client.get.call_args.kwargs["params"]


# ── The apps must not call Google directly ────────────────────────────────


def test_no_app_calls_a_google_web_service_from_the_client():
    """Structural guard.

    The embedded Maps keys are SDK-restricted, so a direct Places/Directions
    call from an app is rejected — and a key that worked would be extractable
    from the binary. Both must go through this proxy.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[2]
    pattern = re.compile(r"https://maps\.googleapis\.com/maps/api/")

    offenders = []
    for app in ("drop-customer-app", "drop-rider-app", "drop-vendor-app"):
        root = repo / app
        if not root.exists():
            continue
        for path in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
            if "node_modules" in path.parts:
                continue
            for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("//", "*", "/*")):
                    continue  # prose about the rule is not a violation of it
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(repo)}:{i}")

    assert offenders == [], (
        "these call a Google web service directly from an app; route them through "
        f"/api/maps instead: {offenders}"
    )


def test_no_app_still_geocodes_against_openstreetmap():
    """Photon/Nominatim were the stopgap this proxy replaced."""
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[2]
    pattern = re.compile(r"photon\.komoot\.io|nominatim\.openstreetmap\.org")

    offenders = []
    for app in ("drop-customer-app", "drop-rider-app", "drop-vendor-app"):
        root = repo / app
        if not root.exists():
            continue
        for path in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
            if "node_modules" in path.parts:
                continue
            for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(repo)}:{i}")

    assert offenders == [], f"still geocoding against OpenStreetMap: {offenders}"
