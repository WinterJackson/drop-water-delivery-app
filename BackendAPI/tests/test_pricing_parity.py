"""Pricing parity — the regression guard for findings B1, B2, B3 and H10.

Before `pricing_service` existed, the order total was computed independently in
four places (cart preview, STK-push route, order ledger, mobile client) using
three different formulas. The retail service fee was 10 in one and 12 in another;
surge and the wholesale markup were in one and not the others. The customer was
shown one number, charged a second, and had a third recorded — which made the
M-Pesa callback's ±1 KSH amount check fail on every retail order.

These tests assert the property that makes that class of bug impossible: for every
combination of business inputs, the amount pushed to M-Pesa equals the amount
persisted on the order, exactly.
"""

import itertools
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services import order_service
from services.pricing_service import compute_order_quote, service_fee_for, required_vehicle_class


def _item(vendor_id, *, quantity, price, capacity=20, weight=20.0, stock=500):
    item = MagicMock()
    item.vendor_id = vendor_id
    item.product_id = uuid4()
    item.quantity = quantity
    item.price = Decimal(str(price))
    item.Subtotal = Decimal(str(price)) * quantity
    item.product = MagicMock(
        stock=stock, name="Water", weight_kg=weight, capacity=capacity, vendor_id=vendor_id
    )
    return item


def _vendor(vendor_type):
    vendor = MagicMock()
    vendor.id = uuid4()
    vendor.lat = -1.2864
    vendor.lng = 36.8172
    vendor.vendor_type = vendor_type
    vendor.wholesale_base_delivery_fee = 0
    vendor.wholesale_per_km_fee = 0
    return vendor


def _user(*, wallet=0, first_order=False, floor=0, elevator=False):
    user = MagicMock()
    user.id = uuid4()
    user.clerk_id = "customer_clerk"
    user.wallet_balance = Decimal(str(wallet))
    user.debt_balance = Decimal("0")
    user.has_used_welcome_offer = not first_order
    user.floor_level = floor
    user.has_elevator = elevator
    return user


# Retail is capped at 4 bottles, wholesale needs ≥100 kg, so the two branches use
# different quantities to stay inside their own rules.
_CASES = list(itertools.product(
    ["retail_refill", "wholesale_b2b"],   # vendor type
    [False, True],                        # surge window active
    [False, True],                        # first order (welcome offer)
    [0, 250],                             # wallet balance
    ["quick_swap", "keep_my_bottle"],     # delivery type
))


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor_type,surge,first_order,wallet,delivery_type", _CASES)
async def test_stk_amount_equals_persisted_total(vendor_type, surge, first_order, wallet, delivery_type):
    """32 combinations, zero drift between what we charge and what we record."""
    quantity = 4 if vendor_type == "retail_refill" else 6  # 6 × 20 kg = 120 kg ≥ MOQ
    vendor = _vendor(vendor_type)
    items = [_item(vendor.id, quantity=quantity, price="250.00")]
    user = _user(wallet=wallet, first_order=first_order)

    with patch.object(order_service, "is_surge_active", return_value=surge):
        quote = await compute_order_quote(
            AsyncMock(), items=items, user=user, vendor=vendor,
            delivery_type=delivery_type, lat=-1.2804, lng=36.8165,
        )

    # The whole point: the integer we push is the decimal we store.
    assert Decimal(quote.stk_amount) == quote.total
    assert quote.total == quote.total.to_integral_value()

    # Surge must be visible in the total exactly when the window is open.
    expected_surge = Decimal(str(order_service.SURGE_FEE_KSH)) if surge else Decimal("0.00")
    assert quote.surge_fee == expected_surge

    # And the service fee comes from the single shared definition.
    assert quote.service_fee == service_fee_for(vendor_type)


@pytest.mark.asyncio
async def test_surge_adds_exactly_the_surge_fee():
    """Freezing the clock inside a peak window moves the total by SURGE_FEE_KSH."""
    vendor = _vendor("retail_refill")
    items = [_item(vendor.id, quantity=2, price="200.00")]
    user = _user()

    with patch.object(order_service, "is_surge_active", return_value=False):
        off_peak = await compute_order_quote(
            AsyncMock(), items=items, user=user, vendor=vendor,
            delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
        )
    with patch.object(order_service, "is_surge_active", return_value=True):
        peak = await compute_order_quote(
            AsyncMock(), items=items, user=user, vendor=vendor,
            delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
        )

    assert peak.total - off_peak.total == Decimal(str(order_service.SURGE_FEE_KSH))


def test_surge_window_matches_the_documented_hours():
    """06:00–08:00 and 17:00–19:00 East Africa Time."""
    from datetime import datetime, timedelta, timezone

    eat = timezone(timedelta(hours=3))
    inside = [6, 7, 17, 18]
    outside = [5, 8, 9, 12, 16, 19, 20, 23]

    for hour in inside + outside:
        moment = datetime(2026, 7, 30, hour, 30, tzinfo=eat)
        assert order_service.is_surge_active(now=moment) is (hour in inside), f"hour {hour}"


def test_surge_window_is_evaluated_in_eat_not_utc():
    """A UTC timestamp is converted before the window is checked.

    18:30 EAT is 15:30 UTC — inside the evening window. Comparing the raw UTC hour
    would miss it.
    """
    from datetime import datetime, timezone

    utc_moment = datetime(2026, 7, 30, 15, 30, tzinfo=timezone.utc)  # = 18:30 EAT
    assert order_service.is_surge_active(now=utc_moment) is True


@pytest.mark.asyncio
async def test_welcome_discount_is_30_percent_of_the_whole_deposit():
    """Not 30% of the single most expensive bottle.

    The checkout route used `highest_bottle_price * 0.30` while the order ledger
    used `bottle_deposit * 0.30`, so a first order of three bottles diverged by
    180 KSH between the amount charged and the amount recorded.
    """
    vendor = _vendor("retail_refill")
    items = [_item(vendor.id, quantity=3, price="250.00", capacity=20)]
    user = _user(first_order=True)

    quote = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
    )

    assert quote.bottle_deposit == Decimal("900.00")   # 3 × 300
    assert quote.welcome_discount == Decimal("270.00")  # 30% of 900, not of 300
    assert quote.is_welcome_offer is True


@pytest.mark.asyncio
async def test_deposit_charged_for_keep_my_bottle_even_on_repeat_orders():
    """Keeping the bottle always incurs the deposit; only the discount is one-shot."""
    vendor = _vendor("retail_refill")
    items = [_item(vendor.id, quantity=2, price="250.00")]
    user = _user(first_order=False)

    keep = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="keep_my_bottle", lat=-1.2804, lng=36.8165,
    )
    swap = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
    )

    assert keep.bottle_deposit == Decimal("600.00")
    assert keep.welcome_discount == Decimal("0.00")
    assert swap.bottle_deposit == Decimal("0.00")
    assert keep.total > swap.total


@pytest.mark.asyncio
async def test_wallet_never_discounts_the_total_below_one_shilling():
    """An STK push for zero is rejected by Safaricom."""
    vendor = _vendor("retail_refill")
    items = [_item(vendor.id, quantity=1, price="20.00")]
    user = _user(wallet=100_000)

    quote = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
    )

    assert quote.total >= Decimal("1")
    assert quote.wallet_discount <= Decimal(str(user.wallet_balance))


@pytest.mark.asyncio
async def test_welcome_discount_applies_before_wallet_credit():
    """Ordering matters: reversed, the wallet over-discounts when both apply."""
    vendor = _vendor("retail_refill")
    items = [_item(vendor.id, quantity=2, price="250.00")]
    user = _user(wallet=10_000, first_order=True)

    quote = await compute_order_quote(
        AsyncMock(), items=items, user=user, vendor=vendor,
        delivery_type="quick_swap", lat=-1.2804, lng=36.8165,
    )

    gross = quote.gross_before_discounts
    assert quote.wallet_discount == (gross - quote.welcome_discount - Decimal("1")).quantize(Decimal("0.01"))
    assert quote.total == Decimal("1")


@pytest.mark.asyncio
async def test_empty_cart_is_rejected_by_the_pricer():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await compute_order_quote(
            AsyncMock(), items=[], user=_user(), vendor=_vendor("retail_refill"),
            delivery_type="quick_swap", lat=-1.28, lng=36.82,
        )
    assert exc.value.status_code == 400


class TestVehicleClass:
    """The vehicle class must satisfy *both* the unit count and the weight.

    The checkout route classified purely by unit count while the order ledger
    classified purely by weight, and for wholesale they disagree — 6 × 20 L is
    "motorbike" by weight but "tuktuk" by count. Since the two classes have
    different per-km pricing, that disagreement changed the delivery fee.
    """

    def test_takes_the_larger_of_the_two_classifications(self):
        assert required_vehicle_class(6, Decimal("120")) == "tuktuk"     # count wins
        assert required_vehicle_class(2, Decimal("450")) == "truck"      # weight wins
        assert required_vehicle_class(4, Decimal("80")) == "motorbike"   # both agree

    def test_retail_load_stays_on_a_motorbike(self):
        assert required_vehicle_class(4, Decimal("80")) == "motorbike"

    def test_impossible_payload_is_rejected(self):
        from fastapi import HTTPException

        with pytest.raises((ValueError, HTTPException)):
            required_vehicle_class(5000, Decimal("100000"))
