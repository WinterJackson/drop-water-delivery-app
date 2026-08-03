"""Delivery replay, and the one mistake it must never make.

`reached_destination` is three-valued. Collapsing `None` into `False` turns an
absence of evidence into evidence of absence, on the screen somebody uses to
decide whether a rider is stealing — so most of this file is about the `None`.

The geometry is checked against distances with known answers rather than against
`Order_Tracking_Logs`, which is empty on this deployment.
"""
import ast
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from services import admin_delivery_replay_service as svc

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ADMIN = BACKEND.parent / "drop-admin"

NAIROBI = (-1.2921, 36.8219)


# ── geometry ──────────────────────────────────────────────────────────────


def test_one_degree_of_latitude_is_about_111_kilometres():
    """The whole verdict rests on this function. A units slip here reads as a
    rider who was 4 metres away when they were 4 kilometres away."""
    assert svc._distance_m(0, 0, 1, 0) == pytest.approx(111_195, rel=0.001)


def test_a_hundred_metres_north_measures_a_hundred_metres():
    lat, lng = NAIROBI
    assert svc._distance_m(lat, lng, lat + 0.0008993, lng) == pytest.approx(100, abs=1)


def test_distance_is_symmetric_and_zero_at_a_point():
    a, b = NAIROBI, (-1.3000, 36.8000)
    assert svc._distance_m(*a, *a) == 0
    assert svc._distance_m(*a, *b) == pytest.approx(svc._distance_m(*b, *a))


# ── the three-valued verdict ──────────────────────────────────────────────


def _ping(lat, lng, minutes_ago=0):
    return SimpleNamespace(
        lat=lat,
        lng=lng,
        heading=None,
        speed=None,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def _db(order, pings):
    """Two executes: the order join, then the ordered pings."""
    db = AsyncMock()

    order_result = MagicMock()
    order_result.first.return_value = (order, "Customer", "Rider", "Store")

    ping_result = MagicMock()
    ping_result.scalars.return_value.all.return_value = pings

    db.execute = AsyncMock(side_effect=[order_result, ping_result])
    return db


def _order(lat=-1.3000, lng=36.8000):
    return SimpleNamespace(
        id=uuid4(),
        order_status="delivered",
        payment_status="paid",
        delivery_type="quick_swap",
        delivery_address="Ngong Road",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        deliverer_id=uuid4(),
        vendor_id=uuid4(),
        proof_url=None,
        lat=lat,
        lng=lng,
        lat_from=-1.2800,
        lng_from=36.8100,
    )


@pytest.mark.asyncio
async def test_no_pings_gives_no_verdict_rather_than_a_denial():
    """Tracking needs the app to have permission, signal and battery. Absence of
    a path is routine and says nothing about where the rider went."""
    result = await svc.replay(_db(_order(), []), uuid4())

    assert result["findings"]["reached_destination"] is None
    assert result["findings"]["no_verdict_because"] == (
        "no location was ever recorded for this delivery"
    )


@pytest.mark.asyncio
async def test_an_order_with_no_coordinates_gives_no_verdict():
    """There is nothing to be near. A path cannot be measured against an address
    the platform never geocoded."""
    result = await svc.replay(_db(_order(lat=None, lng=None), [_ping(*NAIROBI)]), uuid4())

    assert result["findings"]["reached_destination"] is None
    assert result["findings"]["no_verdict_because"] == "the order has no delivery coordinates"


@pytest.mark.asyncio
async def test_a_path_that_reaches_the_door_is_a_yes():
    order = _order()
    pings = [_ping(order.lat, order.lng, minutes_ago=m) for m in (10, 8, 6)]

    result = await svc.replay(_db(order, pings), uuid4())

    assert result["findings"]["reached_destination"] is True
    assert result["findings"]["closest_approach_m"] == 0
    assert result["findings"]["pings_at_destination"] == 3


@pytest.mark.asyncio
async def test_a_path_that_never_gets_close_is_a_no_with_the_distance_attached():
    order = _order()
    # ~4 km due north of the delivery point, the whole time.
    pings = [_ping(order.lat + 0.036, order.lng, minutes_ago=m) for m in (10, 5)]

    result = await svc.replay(_db(order, pings), uuid4())

    assert result["findings"]["reached_destination"] is False
    assert result["findings"]["closest_approach_m"] == pytest.approx(4000, abs=50)
    assert result["findings"]["pings_at_destination"] == 0


@pytest.mark.asyncio
async def test_the_proximity_threshold_is_a_block_not_a_doorstep():
    """Consumer GPS is good to tens of metres between buildings. A tight radius
    would make honest deliveries read as fraud."""
    assert svc.PROXIMITY_M >= 100

    order = _order()
    # ~110 m away — inside the threshold, outside any doorstep.
    result = await svc.replay(_db(order, [_ping(order.lat + 0.001, order.lng)]), uuid4())
    assert result["findings"]["reached_destination"] is True


@pytest.mark.asyncio
async def test_a_hole_in_the_record_is_reported_as_a_hole():
    """A path with a 30-minute gap is two paths, and what happened in between is
    not in this data."""
    order = _order()
    pings = [_ping(order.lat, order.lng, minutes_ago=m) for m in (60, 55, 20, 15)]

    result = await svc.replay(_db(order, pings), uuid4())

    assert result["findings"]["largest_gap_minutes"] == pytest.approx(35, abs=0.5)
    assert result["findings"]["has_gap"] is True


@pytest.mark.asyncio
async def test_the_photo_proof_url_never_leaves_the_backend():
    """Presigning an image of somebody's doorstep on every page load is the same
    mistake as prefetching KYC documents."""
    order = _order()
    order.proof_url = "orders/proof/abc.jpg"

    result = await svc.replay(_db(order, []), uuid4())

    assert result["order"]["has_proof"] is True
    assert "proof_url" not in result["order"]
    assert "abc.jpg" not in str(result)


# ── the console must not flatten the three values ─────────────────────────


def test_the_page_renders_all_three_verdicts():
    source = (ADMIN / "app/(dashboard)/operations/replay/page.tsx").read_text()
    assert "verdict === null" in source, "the 'no verdict' branch must exist"
    assert "No verdict" in source
    assert "reached_destination: boolean | null" in source, (
        "typing it as boolean would let `undefined` render as 'never arrived'"
    )


def test_the_replay_route_is_gated_on_geo_view():
    """A breadcrumb trail is a person's precise movements. `orders.read` is not
    the right key for that, and the coordinates being historical rather than live
    makes them no less identifying."""
    source = (BACKEND / "routes/admin_orders_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "replay_delivery":
            body = ast.get_source_segment(source, node) or ""
            assert "PERM_GEO_VIEW" in body
            return

    pytest.fail("replay_delivery route not found")
