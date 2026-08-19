"""Every line the cart shows adds up to the figure on the button.

`test_cart_breakdown.py` guards the *rendering* — that each field has exactly
one line and comes from the quote. This file guards the arithmetic underneath
it: that the lines the quote publishes actually sum to the total it charges, for
every combination of the platform's costs and discounts.

**What was wrong.** `total` is quantized to a whole shilling because M-Pesa's STK
push accepts nothing finer. Every line above it is exact to the cent, and the
delivery fee is `base + per_km × distance` with distance to two decimal places —
so at KSH 20/km, four retail deliveries in five beyond the short hop land on a
fraction of a shilling. Nothing published that difference. A customer adding up
their own cart got a number up to 50 cents away from the one on the button, in
either direction, with no line accounting for it, and then checked the whole
thing against an M-Pesa message that agreed with the total and not the lines.

That is the same complaint the itemised breakdown exists to answer, and being
small made it quieter rather than smaller: an overcharge you can prove is a
support ticket, and a discrepancy nobody can explain is a review.

`rounding_adjustment` is the fix — the residue, published as its own signed
figure, never folded into another line. Folding it into the delivery fee would
make the column reconcile by telling the customer a delivery fee different from
the one the rider is paid out of.

The gates below are the other half of "the cart is correct": a basket whose
arithmetic is perfect but whose goods have been withdrawn, or whose store has no
location, is not a checkout anybody should reach.
"""
from __future__ import annotations

import itertools
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.pricing_service import compute_order_quote, validate_quote

#: Everything the customer is charged, and everything taken off. The two lists
#: together are the complete itemisation — `delivery_markup` is deliberately in
#: neither, because it is platform margin *inside* `delivery_fee`.
CHARGES = (
    "product_subtotal", "delivery_fee", "service_fee", "surge_fee",
    "payload_surcharge", "staircase_surcharge", "bottle_deposit",
    "debt_settlement", "rounding_adjustment",
)
CREDITS = ("welcome_discount", "mpesa_discount", "wallet_discount")


def _item(vendor_id, *, quantity, price, capacity=20, weight=20.0, stock=500):
    item = MagicMock()
    item.vendor_id = vendor_id
    item.product_id = uuid4()
    item.quantity = quantity
    item.price = Decimal(str(price))
    item.Subtotal = Decimal(str(price)) * quantity
    item.product = MagicMock(
        stock=stock, name="Water", weight_kg=weight, capacity=capacity,
        vendor_id=vendor_id, deleted_at=None, is_available=True,
    )
    return item


def _vendor(vendor_type="retail_refill", *, lat=-1.2864, lng=36.8172):
    vendor = MagicMock()
    vendor.id = uuid4()
    vendor.lat, vendor.lng = lat, lng
    vendor.vendor_type = vendor_type
    vendor.wholesale_base_delivery_fee = 0
    vendor.wholesale_per_km_fee = 0
    return vendor


def _user(*, wallet=0, first_order=False, floor=0, elevator=False, debt=0):
    user = MagicMock()
    user.id = uuid4()
    user.clerk_id = "customer_clerk"
    user.wallet_balance = Decimal(str(wallet))
    user.debt_balance = Decimal(str(debt))
    user.has_used_welcome_offer = not first_order
    user.floor_level = floor
    user.has_elevator = elevator
    user.device_id = f"test-device-{user.id}"
    return user


def _session():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result)
    return session


async def _quote(**kw):
    vendor = kw.pop("vendor", None) or _vendor(kw.pop("vendor_type", "retail_refill"))
    items = kw.pop("items", None) or [
        _item(vendor.id, quantity=kw.pop("quantity", 2), price=kw.pop("price", 250))
    ]
    surge = kw.pop("surge", False)
    user = kw.pop("user", None) or _user(
        wallet=kw.pop("wallet", 0), first_order=kw.pop("first_order", False),
        floor=kw.pop("floor", 0), elevator=kw.pop("elevator", False),
        debt=kw.pop("debt", 0),
    )
    with patch("services.order_service.is_surge_active", return_value=surge), \
         patch("services.pricing_service.config.ensure_fresh", new=AsyncMock()), \
         patch("services.customer_bottle_service.assert_can_hold", new=AsyncMock()):
        return await compute_order_quote(
            _session(), items=items, user=user, vendor=vendor,
            delivery_type=kw.pop("delivery_type", "exchange"),
            lat=kw.pop("lat", -1.2900), lng=kw.pop("lng", 36.8200),
            payment_method=kw.pop("payment_method", "mpesa"),
            **kw,
        )


def _column(quote) -> Decimal:
    """What a customer gets by adding up the lines in front of them."""
    payload = quote.as_dict()
    return (
        sum(Decimal(payload[f]) for f in CHARGES)
        - sum(Decimal(payload[f]) for f in CREDITS)
    )


# Latitudes chosen to land the vendor at a spread of distances — inside the
# short hop, and beyond it where `base + per_km × distance` produces cents.
_VENDOR_LATS = (-1.2870, -1.2960, -1.2975, -1.3000, -1.3020)

_CASES = list(itertools.product(
    _VENDOR_LATS,
    ("exchange", "refill_mine", "new_bottle"),
    (False, True),      # first order
    (0, 100, 100_000),  # wallet balance
    ("mpesa", "cash"),
))


@pytest.mark.asyncio
@pytest.mark.parametrize("vlat,delivery_type,first_order,wallet,payment_method", _CASES)
async def test_the_lines_sum_to_the_total(vlat, delivery_type, first_order, wallet, payment_method):
    """The identity, over 180 combinations of the platform's whole cost model."""
    quote = await _quote(
        vendor=_vendor(lat=vlat), delivery_type=delivery_type,
        first_order=first_order, wallet=wallet, payment_method=payment_method,
        floor=5, debt=200, quantity=4, price=249.50, surge=True,
    )
    assert _column(quote) == quote.total, (
        f"column {_column(quote)} != total {quote.total}\n{quote.as_dict()}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("vlat", _VENDOR_LATS)
async def test_the_rounding_is_only_ever_rounding(vlat):
    """Under half a shilling, always. Anything larger is a fee in disguise."""
    quote = await _quote(vendor=_vendor(lat=vlat), quantity=3, price=249.50)
    assert abs(quote.rounding_adjustment) <= Decimal("0.50")


@pytest.mark.asyncio
async def test_a_whole_shilling_basket_shows_no_rounding_line():
    """Nothing to explain, so nothing is said. The line is not decoration."""
    quote = await _quote(quantity=2, price=250, lat=-1.2870, lng=36.8175)
    assert quote.rounding_adjustment == Decimal("0.00")


@pytest.mark.asyncio
async def test_the_wholesale_markup_is_not_a_line_of_its_own():
    """It is margin *inside* the delivery fee. Counting it would double-charge."""
    quote = await _quote(
        vendor=_vendor("wholesale_b2b"), quantity=6, price=2000,
    )
    assert quote.delivery_markup > 0          # it exists
    assert _column(quote) == quote.total      # and it is not in the column


# ── The gates ─────────────────────────────────────────────────────────────
#
# `live_product()` runs when an item enters the cart and never again, and a cart
# has no expiry. Everything below is a state the basket can reach *after* it was
# assembled — which is the only kind of state a re-check exists for.

@pytest.mark.asyncio
async def test_a_withdrawn_product_cannot_be_checked_out():
    quote = await _quote()
    items = [_item(uuid4(), quantity=1, price=250)]
    items[0].product.deleted_at = "2026-01-01T00:00:00Z"
    with pytest.raises(HTTPException) as exc:
        validate_quote(quote, items, user=_user(), vendor=None)
    assert exc.value.status_code == 400
    assert "no longer sold" in exc.value.detail


@pytest.mark.asyncio
async def test_a_product_the_store_switched_off_cannot_be_checked_out():
    quote = await _quote()
    items = [_item(uuid4(), quantity=1, price=250)]
    items[0].product.is_available = False
    with pytest.raises(HTTPException) as exc:
        validate_quote(quote, items, user=_user(), vendor=None)
    assert "unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_a_store_with_no_location_cannot_be_checked_out():
    """`calculate_delivery_fee` falls back to 0.0 km for an unmeasurable store,
    which then prices as a short hop and passes the radius check — a shop
    nobody can find reading as a shop next door."""
    quote = await _quote(vendor=_vendor(lat=None, lng=None))
    assert quote.distance_km == 0.0          # the fallback, still there
    with pytest.raises(HTTPException) as exc:
        validate_quote(quote, [_item(uuid4(), quantity=1, price=250)],
                       user=_user(), vendor=None)
    assert "location" in exc.value.detail


@pytest.mark.asyncio
async def test_an_ordinary_basket_still_passes_every_gate():
    """Non-vacuity: the gates above must not be refusing everything."""
    vendor = _vendor()
    items = [_item(vendor.id, quantity=2, price=250)]
    quote = await _quote(vendor=vendor, items=items)
    validate_quote(quote, items, user=_user(), vendor=None)
