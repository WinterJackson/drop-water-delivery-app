import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from decimal import Decimal


@pytest.mark.asyncio
async def test_get_closest_deliverer_returns_none():
    """When no deliverers are available, get_closest_deliverer should return None."""
    from services.order_service import get_closest_deliverer

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await get_closest_deliverer(mock_session, lat=-1.28, lng=36.82)
    assert result is None


def _cart_item(vendor_id, *, quantity=1, price="100.00", capacity=20, weight=20.0, stock=10):
    item = MagicMock()
    item.vendor_id = vendor_id
    item.product_id = uuid4()
    item.quantity = quantity
    item.price = Decimal(price)
    item.Subtotal = Decimal(price) * quantity
    item.product = MagicMock(
        stock=stock, name="Water 20L", weight_kg=weight, capacity=capacity, vendor_id=vendor_id
    )
    return item


def _customer(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", uuid4())
    user.clerk_id = overrides.get("clerk_id", "user_clerk")
    user.debt_balance = Decimal(str(overrides.get("debt_balance", 0)))
    user.wallet_balance = Decimal(str(overrides.get("wallet_balance", 0)))
    user.has_used_welcome_offer = overrides.get("has_used_welcome_offer", True)
    user.floor_level = overrides.get("floor_level", 0)
    user.has_elevator = overrides.get("has_elevator", False)
    user.location_address = "Kilimani, Nairobi"
    user.push_token = None
    return user


def _vendor(vendor_id, vendor_type="retail_refill"):
    vendor = MagicMock()
    vendor.id = vendor_id
    vendor.clerk_id = "vendor_clerk"
    vendor.lat = -1.28
    vendor.lng = 36.82
    vendor.vendor_type = MagicMock()
    vendor.vendor_type.value = vendor_type
    vendor.wholesale_base_delivery_fee = 0
    vendor.wholesale_per_km_fee = 0
    vendor.push_token = None
    return vendor


def _build_session(user, vendor, items):
    """A session double wired for the exact call sequence `create_order` makes."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    idempotency = MagicMock()
    idempotency.scalar_one_or_none.return_value = None

    locked_user = MagicMock()
    locked_user.scalar_one_or_none.return_value = user

    cart_items = MagicMock()
    cart_items.unique.return_value.scalars.return_value.all.return_value = items

    # The self-dealing check asks whether the buyer staffs this store. Staff used
    # to be a column already loaded with the vendor row; it is a membership table
    # now, so it is a query — and a bare `AsyncMock` answers every query truthily,
    # which would make every order look self-dealt.
    not_staff = MagicMock()
    not_staff.scalars.return_value.first.return_value = None

    # `UPDATE ... RETURNING id, stock, name, vendor_id, low_stock_threshold,
    # low_stock_notified_at` — the last two drive the low-stock warning, which is
    # now per product and fires once per crossing rather than on every sale.
    stock_update = MagicMock()
    stock_update.fetchone.return_value = (uuid4(), 9, "Water 20L", vendor.id, 5, None)

    # Pricing reads `Platform_Settings` — the fees and commissions are rows an
    # administrator can change, not module constants. Empty means "everything is
    # still the shipped default", which is what the arithmetic below assumes.
    platform_settings = MagicMock()
    platform_settings.scalars.return_value.all.return_value = []

    # Dispatched on the statement rather than by position. A positional list has
    # to be re-counted every time `create_order` gains a query — and when it is
    # wrong, the *stock update* silently receives some other query's result and
    # the failure surfaces nowhere near the cause.
    def _for(statement) -> MagicMock:
        sql = str(statement)
        if "Platform_Settings" in sql:
            return platform_settings
        if sql.startswith("UPDATE"):
            return stock_update
        if "Vendor_Staff" in sql:
            return not_staff
        if "Cart_Items" in sql:
            return cart_items
        if '"Users"' in sql:
            return locked_user
        if '"Orders"' in sql:
            return idempotency
        raise AssertionError(f"unexpected query in create_order:\n{sql}")

    session.execute = AsyncMock(side_effect=lambda statement, *a, **k: _for(statement))

    async def _get(model, ident):
        if model.__name__ == "Vendor":
            return vendor
        if model.__name__ == "User":
            return user
        return None

    session.get = AsyncMock(side_effect=_get)
    return session


@pytest.mark.asyncio
async def test_create_order_with_no_deliverer_sets_unassigned():
    """A new order starts `unassigned` — no rider is force-assigned at creation."""
    from services.order_service import create_order

    vendor_id = uuid4()
    user = _customer()
    vendor = _vendor(vendor_id)
    items = [_cart_item(vendor_id)]
    session = _build_session(user, vendor, items)

    with patch("services.order_service.asyncio.create_task"), \
         patch("services.order_service.create_notification", new_callable=AsyncMock):
        order = await create_order(
            session=session,
            CheckoutRequestID="test-unique-123",
            id=uuid4(),
            user_id=user.id,
            phone="254700000000",
            type="cart",
            lat=-1.28,
            lng=36.82,
        )

    assert order is not None
    assert order.order_status == "unassigned"
    assert order.deliverer_id is None
    assert order.checkout_request_ID == "test-unique-123"


@pytest.mark.asyncio
async def test_create_order_records_the_quoted_total_verbatim():
    """`order.total_amount` must be the quote's total, to the shilling.

    This is the invariant that B1/B2/B3 violated: the route pushed one amount to
    M-Pesa while `create_order` derived a different one for the order row.
    """
    from services.order_service import create_order
    from services.pricing_service import compute_order_quote

    vendor_id = uuid4()
    user = _customer(wallet_balance=0)
    vendor = _vendor(vendor_id)
    items = [_cart_item(vendor_id, quantity=2, price="250.00")]

    quote = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.29, lng=36.83,
    )

    session = _build_session(user, vendor, items)
    with patch("services.order_service.asyncio.create_task"), \
         patch("services.order_service.create_notification", new_callable=AsyncMock):
        order = await create_order(
            session=session, CheckoutRequestID="ws_CO_PARITY", id=uuid4(),
            user_id=user.id, phone="254700000000", type="cart",
            lat=-1.29, lng=36.83, quote=quote,
        )

    assert order.total_amount == quote.total
    assert int(order.total_amount) == quote.stk_amount
    assert order.service_fee == quote.revenue["service_fee"]
    assert order.surge_fee == quote.surge_fee


@pytest.mark.asyncio
async def test_create_order_consumes_wallet_credit_and_writes_a_ledger_row():
    """Wallet credit spent on an order must leave an auditable trail.

    Balances used to move silently, so the customer's Transactions screen could
    not account for its own numbers.
    """
    from services.order_service import create_order
    from services.pricing_service import compute_order_quote

    vendor_id = uuid4()
    user = _customer(wallet_balance=100)
    vendor = _vendor(vendor_id)
    items = [_cart_item(vendor_id, quantity=2, price="250.00")]

    quote = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.29, lng=36.83,
    )
    assert quote.wallet_discount == Decimal("100.00")

    session = _build_session(user, vendor, items)
    with patch("services.order_service.asyncio.create_task"), \
         patch("services.order_service.create_notification", new_callable=AsyncMock), \
         patch("services.wallet_service.record_wallet_movement", new_callable=AsyncMock) as mock_ledger:
        await create_order(
            session=session, CheckoutRequestID="ws_CO_WALLET", id=uuid4(),
            user_id=user.id, phone="254700000000", type="cart",
            lat=-1.29, lng=36.83, quote=quote,
        )

    assert user.wallet_balance == Decimal("0.00")
    mock_ledger.assert_awaited_once()
    # Signed: spending wallet credit is money leaving, so the ledger row is
    # negative. `transaction_type` cannot carry direction — `order_payment` also
    # credits a rider their delivery earnings.
    assert mock_ledger.await_args.kwargs["amount"] == Decimal("-100.00")


@pytest.mark.asyncio
async def test_create_order_rejects_duplicate_checkout_request_id():
    """A retried STK push must not be able to create a second order."""
    from fastapi import HTTPException
    from services.order_service import create_order

    session = AsyncMock()
    existing = MagicMock()
    existing.scalar_one_or_none.return_value = MagicMock()  # an order already exists
    session.execute = AsyncMock(return_value=existing)

    with pytest.raises(HTTPException) as exc:
        await create_order(
            session=session, CheckoutRequestID="ws_CO_DUPLICATE", id=uuid4(),
            user_id=uuid4(), phone="254700000000", type="cart", lat=-1.28, lng=36.82,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_order_refuses_multi_vendor_cart():
    """One CheckoutRequestID must map to exactly one order.

    A multi-vendor cart would produce several orders sharing a payment reference,
    leaving the callback unable to tell which order it had just paid for.
    """
    from fastapi import HTTPException
    from services.order_service import create_order

    user = _customer()
    vendor_a, vendor_b = uuid4(), uuid4()
    items = [_cart_item(vendor_a), _cart_item(vendor_b)]
    session = _build_session(user, _vendor(vendor_a), items)

    with pytest.raises(HTTPException) as exc:
        await create_order(
            session=session, CheckoutRequestID="ws_CO_MULTI", id=uuid4(),
            user_id=user.id, phone="254700000000", type="cart", lat=-1.28, lng=36.82,
        )
    assert exc.value.status_code == 400
    assert "more than one vendor" in exc.value.detail


@pytest.mark.asyncio
async def test_create_order_blocks_self_dealing():
    """A vendor cannot order from their own store."""
    from fastapi import HTTPException
    from services.order_service import create_order

    vendor_id = uuid4()
    user = _customer(clerk_id="vendor_clerk")  # same clerk id as the vendor
    vendor = _vendor(vendor_id)
    items = [_cart_item(vendor_id)]
    session = _build_session(user, vendor, items)

    with pytest.raises(HTTPException) as exc:
        await create_order(
            session=session, CheckoutRequestID="ws_CO_SELF", id=uuid4(),
            user_id=user.id, phone="254700000000", type="cart", lat=-1.28, lng=36.82,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_order_blocks_customers_with_outstanding_debt():
    """An unpaid bottle deposit blocks new orders."""
    from fastapi import HTTPException
    from services.order_service import create_order

    vendor_id = uuid4()
    user = _customer(debt_balance=300)
    vendor = _vendor(vendor_id)
    items = [_cart_item(vendor_id)]
    session = _build_session(user, vendor, items)

    with pytest.raises(HTTPException) as exc:
        await create_order(
            session=session, CheckoutRequestID="ws_CO_DEBT", id=uuid4(),
            user_id=user.id, phone="254700000000", type="cart", lat=-1.28, lng=36.82,
        )
    assert exc.value.status_code == 402
