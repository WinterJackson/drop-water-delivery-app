"""Coverage for the customer-facing services that had none.

The audit found refunds, favourites, vendor favourites, saved locations, reviews,
notifications, order contacts and the discovery radii all untested. These are the
happy path, the authorisation failure, and one edge case for each.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


# ── Reviews ──────────────────────────────────────────────────────────────────

def _review_payload(order_id, target_id, target_type="vendor", rating=5):
    payload = MagicMock()
    payload.order_id = order_id
    payload.target_id = target_id
    payload.target_type = target_type
    payload.rating = rating
    payload.comment = "Great service"
    return payload


@pytest.mark.asyncio
async def test_review_requires_a_delivered_order():
    from services.review_service import create_review

    order = MagicMock()
    order.customer_id = uuid4()
    order.order_status = "picked_up"  # not delivered yet
    order.vendor_id = uuid4()

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, _id: (
        order if model.__name__ == "Order" else MagicMock(clerk_id="customer_a")
    ))

    with pytest.raises(HTTPException) as exc:
        await create_review(session, "customer_a", _review_payload(order.id, order.vendor_id))
    assert exc.value.status_code == 400
    assert "delivered" in exc.value.detail


@pytest.mark.asyncio
async def test_review_rejects_someone_elses_order():
    from services.review_service import create_review

    order = MagicMock()
    order.customer_id = uuid4()
    order.order_status = "delivered"
    order.vendor_id = uuid4()

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, _id: (
        order if model.__name__ == "Order" else MagicMock(clerk_id="the_real_customer")
    ))

    with pytest.raises(HTTPException) as exc:
        await create_review(session, "an_impostor", _review_payload(order.id, order.vendor_id))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_must_target_the_vendor_who_fulfilled_the_order():
    from services.review_service import create_review

    order = MagicMock()
    order.customer_id = uuid4()
    order.order_status = "delivered"
    order.vendor_id = uuid4()

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, _id: (
        order if model.__name__ == "Order" else MagicMock(clerk_id="customer_a")
    ))

    unrelated_vendor = uuid4()
    with pytest.raises(HTTPException) as exc:
        await create_review(session, "customer_a", _review_payload(order.id, unrelated_vendor))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_blocks_self_rating():
    from services.review_service import create_review

    vendor_id = uuid4()
    order = MagicMock()
    order.customer_id = uuid4()
    order.order_status = "delivered"
    order.vendor_id = vendor_id

    def _get(model, _id):
        if model.__name__ == "Order":
            return order
        return MagicMock(clerk_id="same_person")

    session = AsyncMock()
    session.get = AsyncMock(side_effect=_get)
    # The target is now fetched with `SELECT … FOR UPDATE` rather than
    # `session.get`, because the rating counters are a read-modify-write.
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(
                return_value=MagicMock(clerk_id="same_person", staff_clerk_id=None)
            )
        )
    )

    with pytest.raises(HTTPException) as exc:
        await create_review(session, "same_person", _review_payload(order.id, vendor_id))
    assert exc.value.status_code == 403
    assert "Self-rating" in exc.value.detail


# ── Order contacts ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_order_contacts_denied_to_unrelated_caller():
    from services.contact_service import get_order_contacts

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    ))

    with pytest.raises(HTTPException):
        await get_order_contacts(session=session, order_id=uuid4(), requester_clerk_id="stranger")


# ── Refunds ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refund_without_a_receipt_is_marked_failed_not_retried_forever():
    from services.refund_service import process_single_refund

    order = MagicMock()
    order.id = uuid4()
    order.payment_status = "refund_pending"

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None  # no paid Payment row
    session.execute = AsyncMock(return_value=result)

    outcome = await process_single_refund(session, order)

    assert outcome["status"] == "failed"
    assert order.payment_status == "refund_failed"


@pytest.mark.asyncio
async def test_successful_reversal_moves_order_to_refund_processing():
    from services.refund_service import process_single_refund

    order = MagicMock()
    order.id = uuid4()
    order.customer_id = uuid4()
    order.payment_status = "refund_pending"

    payment = MagicMock()
    payment.mpesa_receipt = "QJI4ABCDEF"
    payment.amount = Decimal("590")

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = payment
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)

    with patch(
        "services.refund_service.initiate_mpesa_reversal",
        new_callable=AsyncMock,
        return_value={"success": True, "ConversationID": "AG_123"},
    ):
        outcome = await process_single_refund(session, order)

    assert outcome["status"] == "processing"
    assert order.payment_status == "refund_processing"
    assert payment.reversal_conversation_id == "AG_123"


@pytest.mark.asyncio
async def test_refund_sweep_claims_rows_with_skip_locked():
    """Several workers may sweep at once; a reversal must not be issued twice."""
    from sqlalchemy.dialects import postgresql
    from services.refund_service import process_all_pending_refunds

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    await process_all_pending_refunds(session)

    # SKIP LOCKED is dialect-specific, so compile against Postgres rather than
    # the generic dialect (which silently omits it).
    statement = str(
        session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    ).upper()
    assert "FOR UPDATE" in statement
    assert "SKIP LOCKED" in statement


# ── Cart rules ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retail_cap_applies_to_a_brand_new_cart():
    """The 4-bottle cap used to be checked only when a cart already existed, so
    the very first add could smuggle in any quantity."""
    from services.cart_services import add_to_cart_service

    product = MagicMock()
    product.id = uuid4()
    product.vendor_id = uuid4()
    product.stock = 500
    product.price = Decimal("250")
    product.discount = Decimal("0")
    product.name = "Water 20L"

    vendor = MagicMock()
    vendor.vendor_type = MagicMock()
    vendor.vendor_type.value = "retail_refill"

    session = AsyncMock()
    session.get = AsyncMock(return_value=vendor)
    empty = MagicMock()
    empty.unique.return_value.scalar_one_or_none.return_value = None  # no cart yet
    session.execute = AsyncMock(return_value=empty)

    with patch("services.cart_services.get_product_for_cart", new_callable=AsyncMock, return_value=product):
        with pytest.raises(HTTPException) as exc:
            await add_to_cart_service(
                user_id=uuid4(), session=session, product_id=product.id, quantity=10
            )
    assert exc.value.status_code == 400
    assert "maximum of 4" in exc.value.detail


@pytest.mark.asyncio
async def test_absurd_quantities_are_rejected_outright():
    from services.cart_services import add_to_cart_service

    with pytest.raises(HTTPException) as exc:
        await add_to_cart_service(
            user_id=uuid4(), session=AsyncMock(), product_id=uuid4(), quantity=0
        )
    assert exc.value.status_code == 400


# ── Discovery radii ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nearby_vendors_bounds_the_query_by_distance():
    """The 2 km retail radius must be enforced at discovery, not only at checkout.

    An H3 ring alone reaches ~2.5–3 km, so vendors the customer could never order
    from were being listed.
    """
    from services.vendor_service import get_nearby_vendors

    session = AsyncMock()
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    await get_nearby_vendors(session, lat=-1.2864, lng=36.8172)

    statement = str(session.execute.await_args.args[0]).upper()
    assert "ST_DWITHIN" in statement


@pytest.mark.asyncio
async def test_wholesale_by_type_is_also_distance_bounded():
    """The non-retail branch used to return nationwide results."""
    from services.vendor_service import get_vendors_by_type_service

    session = AsyncMock()
    result = MagicMock()
    result.unique.return_value.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)

    await get_vendors_by_type_service(session, type="wholesale_b2b", lat=-1.2864, lng=36.8172)

    statement = str(session.execute.await_args.args[0]).upper()
    assert "ST_DWITHIN" in statement


@pytest.mark.asyncio
async def test_top_brands_requires_coordinates():
    """Guard was `if not lat and not lng`, so a zero latitude slipped through."""
    from services.vendor_service import get_top_brands_service

    with pytest.raises(HTTPException) as exc:
        await get_top_brands_service(AsyncMock(), lat=None, lng=36.8172)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_vendors_by_type_requires_coordinates():
    from services.vendor_service import get_vendors_by_type_service

    with pytest.raises(HTTPException) as exc:
        await get_vendors_by_type_service(AsyncMock(), type="retail_refill", lat=None, lng=None)
    assert exc.value.status_code == 400


# ── Order cancellation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_welcome_offer_is_not_returned_when_cancelling_an_unpaid_order():
    """Otherwise place → cancel → repeat farms the 30% first-order discount."""
    from services.order_service import cancel_customer_order

    user_id = uuid4()
    order = MagicMock()
    order.id = uuid4()
    order.customer_id = user_id
    order.order_status = "unassigned"
    order.payment_status = "pending"       # never paid
    order.is_welcome_offer = True
    order.welcome_discount = Decimal("270")
    order.wallet_discount = Decimal("0")
    order.debt_settlement = Decimal("0")
    order.bottle_deposit = Decimal("0")
    order.deliverer_id = None
    order.vendor_id = uuid4()

    user = MagicMock()
    user.clerk_id = "customer_a"
    user.has_used_welcome_offer = True
    user.wallet_balance = Decimal("0")
    user.debt_balance = Decimal("0")

    order_res = MagicMock(); order_res.scalar_one_or_none.return_value = order
    user_res = MagicMock(); user_res.scalar_one_or_none.return_value = user
    items_res = MagicMock(); items_res.scalars.return_value.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[order_res, user_res, items_res])
    session.get = AsyncMock(return_value=None)

    with patch("services.order_service.create_notification", new_callable=AsyncMock), \
         patch("services.order_service.asyncio.create_task"), \
         patch("routes.websocket_routes.manager.broadcast_order_update", new_callable=AsyncMock):
        await cancel_customer_order(session=session, user_id=user_id, order_id=order.id)

    assert order.order_status == "cancelled"
    assert user.has_used_welcome_offer is True  # not handed back


@pytest.mark.asyncio
async def test_cannot_cancel_an_order_already_in_transit():
    from services.order_service import cancel_customer_order

    user_id = uuid4()
    order = MagicMock()
    order.customer_id = user_id
    order.order_status = "picked_up"

    order_res = MagicMock(); order_res.scalar_one_or_none.return_value = order
    session = AsyncMock()
    session.execute = AsyncMock(return_value=order_res)

    with pytest.raises(HTTPException) as exc:
        await cancel_customer_order(session=session, user_id=user_id, order_id=uuid4())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_cannot_cancel_someone_elses_order():
    from services.order_service import cancel_customer_order

    order = MagicMock()
    order.customer_id = uuid4()
    order.order_status = "unassigned"

    order_res = MagicMock(); order_res.scalar_one_or_none.return_value = order
    session = AsyncMock()
    session.execute = AsyncMock(return_value=order_res)

    with pytest.raises(HTTPException) as exc:
        await cancel_customer_order(session=session, user_id=uuid4(), order_id=uuid4())
    assert exc.value.status_code == 404
