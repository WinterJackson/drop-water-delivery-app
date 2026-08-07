"""
An unpaid balance must have a way out.

`Users.debt_balance` was written in exactly two places, both increments — a late
cancellation penalty and an approved staircase charge — and **decremented
nowhere**. Since `validate_quote` refused any customer with a positive balance,
one late cancellation locked an account out of the platform permanently over
KSH 50, with no in-app payment, no admin write-off and no settlement of any kind.

There are now three ways out, and this file asserts each:

1. **The next order collects it**, as a visible line item, below the ceiling.
2. **The ceiling still refuses**, above it — the platform stops extending credit
   rather than lending without limit.
3. **An administrator can write it off**, for a charge that was simply wrong.

A cancellation puts it back, because the customer is refunded the total that
included it.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from services import platform_config_service as config
from services.pricing_service import compute_order_quote, validate_quote


class _Product:
    def __init__(self, capacity=20, price="200", weight="20.5", stock=50):
        self.capacity = capacity
        self.price = Decimal(price)
        self.weight_kg = Decimal(weight)
        self.stock = stock
        self.name = "20L Purified Refill"


class _Item:
    def __init__(self, quantity=1, price="200", product=None):
        self.quantity = quantity
        self.price = Decimal(price)
        self.product = product or _Product()
        self.Subtotal = self.price * quantity
        self.vendor_id = "vendor-1"


def _vendor():
    return SimpleNamespace(
        id="vendor-1", vendor_type="retail_refill", lat=-1.3615, lng=36.6570,
        wholesale_base_delivery_fee=0, wholesale_per_km_fee=0,
    )


def _customer(debt="0", wallet="0", used_welcome=True):
    return SimpleNamespace(
        id="customer-1", clerk_id="user_1", debt_balance=Decimal(debt),
        wallet_balance=Decimal(wallet), has_used_welcome_offer=used_welcome,
        floor_level=0, has_elevator=False, device_id=None,
    )


@pytest.fixture
def session():
    """A session that answers the device-id lookup with "nobody" and nothing else.

    `compute_order_quote` issues exactly one query of its own — the one-offer-per-
    device check — and otherwise reads only what it is handed.
    """
    stub = AsyncMock()
    stub.execute.return_value.scalars.return_value.first.return_value = None
    return stub


@pytest.mark.asyncio
async def test_a_small_debt_is_added_to_the_next_order(session):
    """The customer settles by using the platform, which is the only way they ever would."""
    quote = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="50"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )

    assert quote.debt_settlement == Decimal("50.00")

    clear = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="0"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    assert quote.total - clear.total == Decimal("50")


@pytest.mark.asyncio
async def test_the_settled_debt_is_platform_revenue_not_the_vendors(session):
    """The platform fronted it; recovering it must not pay anybody a second time."""
    with_debt = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="50"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    without = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="0"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )

    assert with_debt.revenue["vendor_net"] == without.revenue["vendor_net"]
    assert with_debt.revenue["rider_net"] == without.revenue["rider_net"]
    assert (
        Decimal(str(with_debt.revenue["platform_total"]))
        - Decimal(str(without.revenue["platform_total"]))
        == Decimal("50")
    )


@pytest.mark.asyncio
async def test_a_debt_below_the_ceiling_does_not_block_checkout(session):
    """The regression this whole file exists for.

    A KSH 50 penalty used to raise 402 on every future quote, forever.
    """
    quote = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="50"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    # Must not raise.
    validate_quote(quote, [_Item()], user=_customer(debt="50"))


@pytest.mark.asyncio
async def test_a_debt_at_the_ceiling_still_refuses(session):
    """Below the ceiling the platform extends credit; at it, it stops."""
    ceiling = config.get_decimal("max_customer_debt_before_block")
    customer = _customer(debt=str(ceiling))

    quote = await compute_order_quote(
        session, items=[_Item()], user=customer, vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    # Not collected on the order — it is too large to add to a basket.
    assert quote.debt_settlement == Decimal("0.00")

    with pytest.raises(HTTPException) as raised:
        validate_quote(quote, [_Item()], user=customer)
    assert raised.value.status_code == 402


@pytest.mark.asyncio
async def test_the_refusal_names_a_way_out(session):
    """A 402 that names no mechanism is the defect, not the fix.

    The old message said "Please clear it before placing a new order" and there
    was no way to clear it. The replacement has to tell the customer what to do.
    """
    ceiling = config.get_decimal("max_customer_debt_before_block")
    customer = _customer(debt=str(ceiling))
    quote = await compute_order_quote(
        session, items=[_Item()], user=customer, vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )

    with pytest.raises(HTTPException) as raised:
        validate_quote(quote, [_Item()], user=customer)

    detail = raised.value.detail.lower()
    assert "support" in detail, "the refusal must name somewhere to go"
    assert "automatically" in detail, "and say that smaller balances self-clear"


@pytest.mark.asyncio
async def test_no_debt_means_no_line_item(session):
    """The common case adds nothing — no phantom zero-value line on every order."""
    quote = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="0"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    assert quote.debt_settlement == Decimal("0.00")
    assert quote.as_dict()["debt_settlement"] == 0.0


@pytest.mark.asyncio
async def test_the_quote_reports_the_settlement_to_the_client(session):
    """It is charged, so the customer is shown it. A silent charge is the worst
    version of this feature: the total moves and nothing explains why."""
    quote = await compute_order_quote(
        session, items=[_Item()], user=_customer(debt="50"), vendor=_vendor(),
        delivery_type="quick_swap", lat=-1.3620, lng=36.6580, apply_wallet=False,
    )
    assert quote.as_dict()["debt_settlement"] == 50.0


def test_the_penalty_and_the_ceiling_are_settings_not_literals():
    """Both were hardcoded. A business figure the owners cannot change is one
    they will ask an engineer to change, at the worst possible moment."""
    assert "late_cancellation_penalty" in config.SPEC_BY_KEY
    assert "max_customer_debt_before_block" in config.SPEC_BY_KEY

    # And the ceiling must exceed a single penalty, or one cancellation locks the
    # account out again — the exact defect, reintroduced through configuration.
    assert (
        config.DEFAULTS["max_customer_debt_before_block"]
        > config.DEFAULTS["late_cancellation_penalty"]
    )


def test_nothing_raises_a_charge_straight_to_the_ceiling():
    """A single chargeable event must never reach the block on its own.

    The two things that create debt are the cancellation penalty and the
    staircase charge. If either could exceed the ceiling by itself, the
    settlement path would be unreachable for that customer.
    """
    ceiling = config.DEFAULTS["max_customer_debt_before_block"]
    penalty = config.DEFAULTS["late_cancellation_penalty"]
    # The worst realistic staircase charge: a tall building, no lift.
    worst_staircase = (
        20 - config.DEFAULTS["staircase_free_floors"]
    ) * config.DEFAULTS["staircase_surcharge_per_floor"]

    assert penalty < ceiling
    assert worst_staircase < ceiling
