"""
Tests for vendor_management_service: cancel_order, assign_order_rider, update_order_status.
All tests use pure AsyncMock sessions — no real DB needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException


# ── cancel_order ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_order_success():
    """cancel_order should set status to 'cancelled', restore stock, and commit."""
    from services.vendor_management_service import cancel_order

    vendor_id = uuid4()
    order_id = uuid4()
    customer_id = uuid4()

    mock_vendor = MagicMock()
    mock_vendor.id = vendor_id
    mock_vendor.clerk_id = "clerk_v1"

    mock_order = MagicMock()
    mock_order.id = order_id
    mock_order.vendor_id = vendor_id
    mock_order.customer_id = customer_id
    mock_order.order_status = "pending"
    mock_order.payment_status = "paid"
    mock_order.deliverer_id = None

    session = AsyncMock()
    # get_vendor_by_clerk_id → vendor, session.get → order
    # We patch the helper so it returns our vendor mock.
    async def mock_revert(*args, **kwargs):
        mock_order.order_status = "cancelled"
        mock_order.payment_status = "refund_pending"

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ), patch(
        "services.order_service.revert_order_side_effects",
        new_callable=AsyncMock,
        side_effect=mock_revert,
    ) as mock_restore, patch(
        "routes.websocket_routes.manager",
        MagicMock(broadcast_order_update=AsyncMock()),
    ):
        session.get = AsyncMock(return_value=mock_order)
        result = await cancel_order(session, "clerk_v1", order_id)

    assert result["message"] == "Order cancelled successfully"
    assert mock_order.order_status == "cancelled"
    assert mock_order.payment_status == "refund_pending"
    mock_restore.assert_awaited_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_cancel_order_wrong_status():
    """cancel_order should reject already-delivered orders."""
    from services.vendor_management_service import cancel_order

    vendor_id = uuid4()
    mock_vendor = MagicMock(id=vendor_id)
    mock_order = MagicMock(
        id=uuid4(), vendor_id=vendor_id, order_status="delivered"
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=mock_order)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ):
        with pytest.raises(HTTPException) as exc:
            await cancel_order(session, "clerk_v1", mock_order.id)

    assert exc.value.status_code == 400
    assert "Cannot cancel" in exc.value.detail


# ── assign_order_rider ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_order_rider_rejects_unapproved():
    """assign_order_rider must refuse a rider who isn't approved in the registry."""
    from services.vendor_management_service import assign_order_rider

    vendor_id = uuid4()
    rider_id = uuid4()
    order_id = uuid4()

    mock_vendor = MagicMock(id=vendor_id)
    mock_order = MagicMock(
        id=order_id,
        vendor_id=vendor_id,
        order_status="accepted",
        deliverer_id=None,
    )
    mock_rider = MagicMock(id=rider_id)

    session = AsyncMock()

    # session.get is called twice: first for Order, then for Deliverer
    session.get = AsyncMock(side_effect=[mock_order, mock_rider])

    # Registry query returns None → not approved
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ):
        with pytest.raises(HTTPException) as exc:
            await assign_order_rider(session, "clerk_v1", order_id, str(rider_id))

    assert exc.value.status_code == 400
    assert "not approved" in exc.value.detail.lower()


# ── update_order_status ───────────────────────────────────────────────────────
# The order is read `FOR UPDATE`. Two staff members on two devices is not a
# hypothetical — it is what the staff feature exists for — and an unlocked
# read-then-write let both accept the same order, check the cash float against a
# stale balance, and restore stock twice on a double rejection.


def _locked_order(session, order):
    """Answer the `SELECT ... FOR UPDATE` in `update_order_status` with `order`."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = order
    session.execute = AsyncMock(return_value=result)
    return session



@pytest.mark.asyncio
async def test_update_order_status_invalid_transition():
    """update_order_status should block delivered→preparing (invalid transition)."""
    from services.vendor_management_service import update_order_status

    vendor_id = uuid4()
    mock_vendor = MagicMock(id=vendor_id)
    mock_order = MagicMock(
        id=uuid4(),
        vendor_id=vendor_id,
        order_status="delivered",
        customer_id=uuid4(),
        deliverer_id=None,
    )

    session = _locked_order(AsyncMock(), mock_order)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ):
        with pytest.raises(HTTPException) as exc:
            await update_order_status(session, "clerk_v1", mock_order.id, "preparing")

    assert exc.value.status_code == 400
    # The detail says "Invalid transition ..." (comes from validate_status_transition)
    assert "invalid" in exc.value.detail.lower() or "transition" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_update_order_status_valid_transition():
    """update_order_status should succeed for pending→accepted."""
    from services.vendor_management_service import update_order_status

    vendor_id = uuid4()
    customer_id = uuid4()
    mock_vendor = MagicMock(id=vendor_id)
    mock_order = MagicMock(
        id=uuid4(),
        vendor_id=vendor_id,
        order_status="pending",
        customer_id=customer_id,
        deliverer_id=None,
        payment_status="paid",
    )
    mock_customer = MagicMock(id=customer_id, push_token=None)

    session = _locked_order(AsyncMock(), mock_order)
    # The customer is still fetched with `session.get`; only the order is locked.
    session.get = AsyncMock(return_value=mock_customer)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ), patch(
        "routes.websocket_routes.manager",
        MagicMock(broadcast_order_update=AsyncMock()),
    ), patch(
        "services.vendor_management_service.create_notification",
        new_callable=AsyncMock,
    ):
        result = await update_order_status(session, "clerk_v1", mock_order.id, "accepted")

    assert "updated" in result["message"].lower()
    assert mock_order.order_status == "accepted"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_order_status_locks_the_order_row():
    """Structural in spirit: assert the statement carries `FOR UPDATE`.

    Without it, two devices signed into the same store can both transition an
    order — the cash-float gate reads a balance the other request is about to
    spend, and a double rejection restores the same stock twice.
    """
    from services.vendor_management_service import update_order_status

    vendor_id = uuid4()
    mock_vendor = MagicMock(id=vendor_id)
    mock_order = MagicMock(
        id=uuid4(), vendor_id=vendor_id, order_status="delivered",
        customer_id=uuid4(), deliverer_id=None,
    )

    session = _locked_order(AsyncMock(), mock_order)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ):
        with pytest.raises(HTTPException):
            await update_order_status(session, "clerk_v1", mock_order.id, "preparing")

    statement = str(session.execute.await_args.args[0])
    assert "FOR UPDATE" in statement.upper(), statement


@pytest.mark.asyncio
async def test_accepting_a_cash_order_counts_committed_float():
    """The gate is `balance - committed`, not `balance`.

    Earlier accepted cash orders have already claimed part of the wallet — the
    same figure `POST /api/wallet/withdraw` refuses on. Checking the raw balance
    is how a vendor accepts an order they cannot cover and ends the day owing the
    platform. Also `Decimal`: this comparison decides whether a store can trade,
    and binary floating point cannot represent 0.10 exactly.
    """
    from decimal import Decimal

    from services.vendor_management_service import update_order_status

    vendor_id = uuid4()
    mock_vendor = MagicMock(id=vendor_id, wallet_balance=Decimal("1000"))
    mock_order = MagicMock(
        id=uuid4(), vendor_id=vendor_id, order_status="pending",
        customer_id=uuid4(), deliverer_id=None, payment_status="paid",
        payment_method="cash", platform_total=Decimal("600"),
    )

    session = _locked_order(AsyncMock(), mock_order)

    with patch(
        "services.vendor_management_service.get_vendor_by_clerk_id",
        new_callable=AsyncMock,
        return_value=mock_vendor,
    ), patch(
        "services.settlement_service.committed_cash_float_for_vendor",
        new_callable=AsyncMock,
        return_value=Decimal("500"),
    ):
        # 1000 balance − 500 committed = 500 available, against 600 required.
        with pytest.raises(HTTPException) as exc:
            await update_order_status(session, "clerk_v1", mock_order.id, "accepted")

    assert exc.value.status_code == 402
    # The vendor is told the shortfall and why part of their balance is spoken for.
    assert "100" in exc.value.detail
    assert "committed" in exc.value.detail.lower()
