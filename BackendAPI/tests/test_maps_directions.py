"""
The Directions proxy exists so no client ever holds a key that can call a Google
web service. These tests pin the parts that make that safe: the upstream key
never reaches the response, upstream error text never reaches the client, and
identical legs are served from cache instead of Google.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from main import app
from routes import maps_routes


def _request():
    """slowapi rejects anything that is not a real starlette Request."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/maps/directions",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "app": app,
        }
    )


def _google_ok():
    return {
        "status": "OK",
        "routes": [
            {
                "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC"},
                "legs": [
                    {"distance": {"value": 1200}, "duration": {"value": 300}},
                    {"distance": {"value": 800}, "duration": {"value": 200}},
                ],
            }
        ],
    }


def _http_response(payload, status_code=200):
    response = MagicMock()
    response.json.return_value = payload
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    return response


def _patch_httpx(response):
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("routes.maps_routes.httpx.AsyncClient", return_value=ctx), client


async def _call(**overrides):
    kwargs = dict(
        request=_request(),
        origin_lat=-1.2921,
        origin_lng=36.8219,
        dest_lat=-1.3000,
        dest_lng=36.8000,
        mode="driving",
        user=MagicMock(),
    )
    kwargs.update(overrides)
    return await maps_routes.get_directions(**kwargs)


@pytest.mark.asyncio
async def test_returns_only_the_reduced_payload():
    """Google's response is large and names the project; we forward geometry only."""
    patcher, _ = _patch_httpx(_http_response(_google_ok()))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patch("routes.maps_routes.cache_set", AsyncMock(return_value=True)), \
         patcher:
        result = await _call()

    assert set(result) == {"polyline", "distance_meters", "duration_seconds", "cached"}
    assert result["distance_meters"] == 2000   # legs summed
    assert result["duration_seconds"] == 500
    assert "server-key" not in str(result)


@pytest.mark.asyncio
async def test_api_key_is_sent_to_google_but_never_to_the_client():
    patcher, client = _patch_httpx(_http_response(_google_ok()))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patch("routes.maps_routes.cache_set", AsyncMock(return_value=True)), \
         patcher:
        await _call()

    assert client.get.await_args.kwargs["params"]["key"] == "server-key"


@pytest.mark.asyncio
async def test_cache_hit_does_not_call_google():
    cached = {"polyline": "abc", "distance_meters": 10, "duration_seconds": 5}
    patcher, client = _patch_httpx(_http_response(_google_ok()))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=cached)), \
         patcher:
        result = await _call()

    assert result["cached"] is True
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_nearby_coordinates_share_a_cache_key():
    """Rounding to ~11m is what keeps a jittering GPS from missing the cache."""
    seen = []

    async def fake_get(key):
        seen.append(key)
        return None

    patcher, _ = _patch_httpx(_http_response(_google_ok()))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", side_effect=fake_get), \
         patch("routes.maps_routes.cache_set", AsyncMock(return_value=True)), \
         patcher:
        await _call(origin_lat=-1.292100)
        await _call(origin_lat=-1.2921004)

    assert seen[0] == seen[1]


@pytest.mark.asyncio
async def test_upstream_error_message_is_not_leaked():
    """Google's error_message can name the project or the key."""
    denied = {"status": "REQUEST_DENIED", "error_message": "API key not valid: AIzaSecret"}
    patcher, _ = _patch_httpx(_http_response(denied))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patcher, \
         pytest.raises(HTTPException) as exc:
        await _call()

    assert exc.value.status_code == 502
    assert "AIzaSecret" not in exc.value.detail
    assert "REQUEST_DENIED" not in exc.value.detail


@pytest.mark.asyncio
async def test_zero_results_is_404_not_502():
    patcher, _ = _patch_httpx(_http_response({"status": "ZERO_RESULTS", "routes": []}))
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         patcher, \
         pytest.raises(HTTPException) as exc:
        await _call()

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_missing_server_key_is_503():
    """A misconfigured deployment must not read as a bad client request; the
    apps fall back to a straight line on 503."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": ""}), \
         patch("routes.maps_routes.cache_get", AsyncMock(return_value=None)), \
         pytest.raises(HTTPException) as exc:
        await _call()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_rejects_unknown_travel_mode():
    with pytest.raises(HTTPException) as exc:
        await _call(mode="teleport")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("origin_lat", 91.0), ("dest_lat", -91.0), ("origin_lng", 181.0), ("dest_lng", -181.0)],
)
async def test_rejects_out_of_range_coordinates(field, value):
    with patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "server-key"}), \
         pytest.raises(HTTPException) as exc:
        await _call(**{field: value})
    assert exc.value.status_code == 400
