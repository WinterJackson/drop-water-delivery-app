"""Payment settlement must be idempotent — regression guard for finding B4.

Two callers race on every single order: the client polls `/confirm_payment` every
few seconds while Safaricom POSTs (and retries) `/mpesa/callback`. Neither path
checked whether the order was already paid, so each call re-broadcast NEW_ORDER,
created another vendor notification, and spawned another `dispatch_order_to_riders`
cascade — offering the same trip to the whole rider pool several times over.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _order(payment_status="pending"):
    order = MagicMock()
    order.id = uuid4()
    order.vendor_id = uuid4()
    order.customer_id = uuid4()
    order.deliverer_id = None
    order.payment_status = payment_status
    order.total_amount = 590
    order.delivery_fee = 68.0
    order.vehicle_class = "motorbike"
    order.delivery_type = "quick_swap"
    order.lat_from = -1.28
    order.lng_from = 36.82
    return order


def _session_returning(orders):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = orders
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_replayed_paid_callback_is_a_no_op():
    """A second `paid` transition must not fire side effects again."""
    from services.order_service import update_orders_payment_status_by_checkout_id

    already_paid = _order(payment_status="paid")
    session = _session_returning([already_paid])

    with patch("services.order_service.create_notification", new_callable=AsyncMock) as notify, \
         patch("services.order_service.dispatch_order_to_riders", new_callable=AsyncMock) as dispatch, \
         patch("services.order_service.asyncio.create_task") as spawn:
        result = await update_orders_payment_status_by_checkout_id(
            session=session, checkout_request_id="ws_CO_REPLAY", new_status="paid"
        )

    assert result["code"] == "0"          # still reports success to the caller
    notify.assert_not_awaited()            # but nothing happens again
    dispatch.assert_not_awaited()
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_late_failure_cannot_unpay_a_settled_order():
    """A delayed `failed` result must never walk a paid order backwards."""
    from services.order_service import update_orders_payment_status_by_checkout_id

    already_paid = _order(payment_status="paid")
    session = _session_returning([already_paid])

    await update_orders_payment_status_by_checkout_id(
        session=session, checkout_request_id="ws_CO_LATE_FAIL", new_status="failed"
    )

    assert already_paid.payment_status == "paid"


@pytest.mark.asyncio
async def test_first_paid_transition_dispatches_exactly_once():
    """The happy path still fires its side effects — once."""
    from services.order_service import update_orders_payment_status_by_checkout_id

    pending = _order(payment_status="pending")
    session = _session_returning([pending])

    vendor = MagicMock()
    vendor.id = uuid4()
    vendor.push_token = None
    vendor.vendor_type = MagicMock()
    vendor.vendor_type.value = "retail_refill"
    vendor.business_name = "Aqua Point"
    vendor.location_address = "Kilimani"
    vendor.lat = -1.28
    vendor.lng = 36.82
    session.get = AsyncMock(return_value=vendor)

    items_result = MagicMock()
    items_result.unique.return_value.scalars.return_value.all.return_value = []
    # First execute() → the locked order SELECT; second → the order items SELECT.
    orders_result = MagicMock()
    orders_result.scalars.return_value.all.return_value = [pending]
    session.execute = AsyncMock(side_effect=[orders_result, items_result])

    with patch("services.order_service.create_notification", new_callable=AsyncMock) as notify, \
         patch("services.order_service.asyncio.create_task") as spawn, \
         patch("services.order_snapshot.build_order_snapshot", return_value={}), \
         patch("routes.websocket_routes.manager.broadcast_order_update", new_callable=AsyncMock):
        result = await update_orders_payment_status_by_checkout_id(
            session=session, checkout_request_id="ws_CO_FIRST", new_status="paid"
        )

    assert result["code"] == "0"
    assert pending.payment_status == "paid"
    notify.assert_awaited_once()
    # Exactly one dispatch task, and only after the commit.
    assert spawn.call_count == 1
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_unknown_checkout_id_is_reported_not_crashed():
    from services.order_service import update_orders_payment_status_by_checkout_id

    session = _session_returning([])
    result = await update_orders_payment_status_by_checkout_id(
        session=session, checkout_request_id="ws_CO_UNKNOWN", new_status="paid"
    )
    assert "No orders found" in result["message"]


@pytest.mark.asyncio
async def test_settlement_locks_the_order_row():
    """The guard is only safe if the read is serialised — assert FOR UPDATE."""
    from services.order_service import update_orders_payment_status_by_checkout_id

    session = _session_returning([])
    await update_orders_payment_status_by_checkout_id(
        session=session, checkout_request_id="ws_CO_LOCK", new_status="paid"
    )

    statement = str(session.execute.await_args.args[0])
    assert "FOR UPDATE" in statement.upper()
