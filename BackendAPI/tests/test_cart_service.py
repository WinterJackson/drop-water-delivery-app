import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from decimal import Decimal
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_add_to_cart_rejects_insufficient_stock():
    """Adding to cart should raise HTTPException when stock is insufficient."""
    from services.cart_services import add_to_cart_service

    product = MagicMock()
    product.stock = 2
    product.name = "Water 5L"

    with patch("services.cart_services.get_product_for_cart", return_value=product):
        with pytest.raises(HTTPException) as exc_info:
            await add_to_cart_service(
                user_id=uuid4(),
                session=AsyncMock(),
                product_id=uuid4(),
                quantity=5,  # More than stock of 2
            )
        assert exc_info.value.status_code == 400
        assert "Insufficient stock" in str(exc_info.value.detail)


# ── The cart re-prices itself against the live catalogue ───────────────────
#
# `CartItem.price` and `Subtotal` were written once, when the item was added,
# and nothing anywhere updated them again. A cart row has no expiry, so a
# customer could add a bottle at KSH 430, the vendor could put it on offer at
# KSH 370, and the shelf, the product page and the Offers grid would all say 370
# while the cart said 430 — and `compute_order_quote` reads `Subtotal`, so 430
# was also what M-Pesa took. Two prices for one bottle, in one app, at one
# moment.

def _cart(*items, locked=False):
    cart = MagicMock()
    cart.is_locked = locked
    cart.cart_item = list(items)
    cart.total_amount = sum((Decimal(i.Subtotal) for i in items), Decimal(0))
    cart.items_count = len(items)
    return cart


def _line(*, quantity, added_at, live_price, live_discount=0):
    """A cart line added at `added_at`, whose product now costs `live_price`."""
    item = MagicMock()
    item.quantity = quantity
    item.price = Decimal(str(added_at))
    item.Subtotal = Decimal(str(added_at)) * quantity
    item.product = MagicMock(
        price=Decimal(str(live_price)), discount=Decimal(str(live_discount))
    )
    return item


@pytest.mark.asyncio
async def test_a_price_drop_reaches_the_cart():
    """The customer is charged the price the shelf is showing them."""
    from services.cart_services import _resync_cart_prices

    item = _line(quantity=2, added_at="430.00", live_price="430.00", live_discount="60.00")
    cart = _cart(item)
    session = AsyncMock()

    assert await _resync_cart_prices(cart, session) is True
    assert item.price == Decimal("370.00")
    assert item.Subtotal == Decimal("740.00")
    assert cart.total_amount == Decimal("740.00")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_price_rise_reaches_the_cart_too():
    """The store is paid today's price, and its commission computed off it."""
    from services.cart_services import _resync_cart_prices

    item = _line(quantity=3, added_at="200.00", live_price="250.00")
    cart = _cart(item)

    assert await _resync_cart_prices(cart, AsyncMock()) is True
    assert item.price == Decimal("250.00")
    assert item.Subtotal == Decimal("750.00")


@pytest.mark.asyncio
async def test_an_unchanged_cart_is_not_written():
    """No commit on the read path when there is nothing to say."""
    from services.cart_services import _resync_cart_prices

    item = _line(quantity=2, added_at="250.00", live_price="250.00")
    session = AsyncMock()

    assert await _resync_cart_prices(_cart(item), session) is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_cart_mid_checkout_is_left_alone():
    """`is_locked` means an STK push is out with a figure already on somebody's
    phone. Re-pricing underneath it is how charged and recorded come apart."""
    from services.cart_services import _resync_cart_prices

    item = _line(quantity=1, added_at="430.00", live_price="370.00")
    session = AsyncMock()

    assert await _resync_cart_prices(_cart(item, locked=True), session) is False
    assert item.price == Decimal("430.00")
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_discount_larger_than_the_price_never_goes_negative():
    from services.cart_services import _resync_cart_prices

    item = _line(quantity=1, added_at="100.00", live_price="100.00", live_discount="150.00")
    await _resync_cart_prices(_cart(item), AsyncMock())
    assert item.price == Decimal("0")
