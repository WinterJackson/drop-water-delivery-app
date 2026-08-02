"""
Background position reporting.

The rider app used to broadcast location only over the WebSocket, from an effect
inside `ActiveDelivery`. Both halves failed in the normal case: the effect stops
when the rider switches to their navigation app — which is the whole delivery —
and a socket send with no socket was swallowed by a `try/except` that only
logged. So the customer's live map, which the customer app builds a full
WebSocket + REST fallback to *read*, froze at whatever position the rider
happened to be looking at their screen for.

`record_location_pings` is the durable write that replaces it. These pin the
properties that make it safe to expose: it cannot be used to forge another
rider's trail, it does not treat "no GPS fix" as a position off the coast of
Africa, and one rider's ping storm cannot become one database write per ping.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services import deliverer_service as svc


RIDER_ID = uuid4()


def _session(owned_order_ids=()):
    """AsyncSession stub whose one `execute` answers the order-ownership probe."""
    session = AsyncMock()
    session.added = []
    session.add_all = MagicMock(side_effect=session.added.extend)

    result = MagicMock()
    result.scalars.return_value.all.return_value = list(owned_order_ids)
    session.execute = AsyncMock(return_value=result)
    return session


def _ping(lat=-1.2921, lng=36.8219, **kw):
    base = {"lat": lat, "lng": lng, "heading": None, "speed": None, "order_id": None, "timestamp": 1.0}
    base.update(kw)
    return base


def _patched(session, redis=None, owned=()):
    """Patch the three collaborators the function reaches for by import."""
    rider = SimpleNamespace(id=RIDER_ID)
    return (
        patch.object(svc, "get_deliverer_by_clerk_id", AsyncMock(return_value=rider)),
        patch.object(svc, "update_deliverer_location_by_id", AsyncMock()),
        patch("core.redis_client.get_redis", return_value=redis),
    )


async def _run(session, pings, redis=None, clerk_id="user_rider"):
    a, b, c = _patched(session, redis=redis)
    with a, b as write, c:
        result = await svc.record_location_pings(session, clerk_id, pings)
    return result, write


# ── Rejection of nonsense coordinates ────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_island_is_rejected_not_recorded():
    """(0,0) means "no fix", not the Gulf of Guinea.

    A rider reporting it would teleport the customer's map 5,000 km and, worse,
    move the rider's dispatch position into an H3 cell nobody orders from.
    """
    session = _session()
    result, write = await _run(session, [_ping(lat=0.0, lng=0.0)])
    assert result == {"accepted": 0, "rejected": 1}
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_out_of_range_coordinates_are_rejected():
    session = _session()
    result, _ = await _run(session, [_ping(lat=91.0), _ping(lng=181.0)])
    assert result["accepted"] == 0
    assert result["rejected"] == 2


@pytest.mark.asyncio
async def test_good_pings_survive_alongside_bad_ones():
    """One bad sample in a flushed batch must not discard the whole batch."""
    session = _session()
    result, write = await _run(session, [_ping(), _ping(lat=0.0, lng=0.0), _ping()])
    assert result == {"accepted": 2, "rejected": 1}
    write.assert_awaited_once()


# ── Order ownership ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_ping_naming_someone_elses_order_keeps_the_position_but_drops_the_order():
    """Anything else lets any rider write into another rider's delivery trail.

    The coordinate itself is the caller's own and is still legitimate, so it is
    recorded — it just does not become evidence about an order they are not on.
    """
    other_order = uuid4()
    session = _session(owned_order_ids=[])  # the ownership query returns nothing
    result, _ = await _run(session, [_ping(order_id=other_order)])

    assert result["accepted"] == 1
    # No Redis in this run, so the per-order rows are written here — and there
    # are none, because the order was disowned.
    assert session.added == []


@pytest.mark.asyncio
async def test_a_ping_on_the_riders_own_order_is_recorded_against_it():
    own_order = uuid4()
    session = _session(owned_order_ids=[own_order])
    result, _ = await _run(session, [_ping(order_id=own_order)])

    assert result["accepted"] == 1
    assert len(session.added) == 1
    assert session.added[0].order_id == own_order


# ── Write throttling ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_row_write_is_throttled_but_the_history_is_not():
    """A batch is one row write at most, and every sample still reaches Redis.

    Writing `Deliverer.current_lat/lng` recomputes the PostGIS point and the H3
    dispatch cell. Doing that per ping, per rider, is the expensive part; the
    individual samples are cheap because the GPS flush job drains them in bulk.
    """
    redis = AsyncMock()
    redis.set.return_value = False  # another ping already claimed this window
    session = _session()

    result, write = await _run(session, [_ping(), _ping(), _ping()], redis=redis)

    assert result["accepted"] == 3
    write.assert_not_awaited()
    # All three samples pushed in one call.
    redis.rpush.assert_awaited_once()
    assert len(redis.rpush.await_args.args) == 1 + 3


@pytest.mark.asyncio
async def test_the_first_ping_of_a_window_does_write_through():
    redis = AsyncMock()
    redis.set.return_value = True
    session = _session()

    _, write = await _run(session, [_ping(), _ping()], redis=redis)
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_newest_ping_wins_regardless_of_arrival_order():
    """A flushed backlog arrives in one request; the rider is at its *last*
    position, not whichever sample happens to be last in the list."""
    redis = AsyncMock()
    redis.set.return_value = True
    session = _session()

    _, write = await _run(
        session,
        [_ping(lat=-1.30, timestamp=200.0), _ping(lat=-1.20, timestamp=100.0)],
        redis=redis,
    )
    assert write.await_args.kwargs["lat"] == -1.30


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_writing_through():
    """A broken queue must degrade to slower, not to losing the position."""
    redis = AsyncMock()
    redis.rpush.side_effect = RuntimeError("connection reset")
    session = _session()

    result, write = await _run(session, [_ping()], redis=redis)
    assert result["accepted"] == 1
    write.assert_awaited_once()


# ── Limits and error paths ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_oversized_batch_is_refused():
    session = _session()
    pings = [_ping() for _ in range(svc.MAX_LOCATION_PINGS_PER_BATCH + 1)]
    with pytest.raises(HTTPException) as exc:
        await _run(session, pings)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_an_empty_batch_is_a_no_op_not_an_error():
    session = _session()
    result, write = await _run(session, [])
    assert result == {"accepted": 0, "rejected": 0}
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_rider_is_refused():
    session = _session()
    with patch.object(svc, "get_deliverer_by_clerk_id", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await svc.record_location_pings(session, "nobody", [_ping()])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_dead_tracking_socket_does_not_fail_the_write():
    """The fan-out is an optimisation. Losing it must not lose the history."""
    redis = AsyncMock()
    redis.set.return_value = True
    session = _session()

    a, b, c = _patched(session, redis=redis)
    with a, b as write, c, patch(
        "routes.websocket_routes.manager.update_rider_location",
        AsyncMock(side_effect=RuntimeError("socket closed")),
    ):
        result = await svc.record_location_pings(session, "user_rider", [_ping()])

    assert result["accepted"] == 1
    write.assert_awaited_once()
