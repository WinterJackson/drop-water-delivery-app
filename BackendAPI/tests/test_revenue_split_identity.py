"""
The revenue split must add up.

`calculate_revenue_splits` divides an order between three parties. If those
three do not sum to what the customer was charged, the platform is either
inventing money or losing it, and nothing in the system notices — the columns
are written once at creation and read forever afterwards.

The identity, for every vendor type, delivery type and surcharge combination:

    vendor_net + rider_net + platform_total
        == gross_before_discounts − welcome_discount

This is where F-02 was caught: wholesale orders put the payload and staircase
surcharges into `rider_net`, on a settlement path that never credits a wholesale
rider. The customer was charged for them, nobody was paid, and `platform_total`
did not include them either — so the platform's own books understated what it
had actually retained, by exactly the surcharge, on every wholesale order.
"""
from decimal import Decimal

import pytest

from services import platform_config_service as config
from services.order_service import calculate_revenue_splits


def _d(value) -> Decimal:
    return Decimal(str(value))


def _gross(product_total, delivery_fee, splits, bottle_deposit, surcharges, debt_settlement):
    """What the customer is charged before the welcome discount.

    Built from the same components `compute_order_quote` sums, so the assertion
    is against the customer-facing total rather than against a restatement of
    the split itself.
    """
    return (
        _d(product_total)
        + _d(delivery_fee)
        + _d(splits["service_fee"])
        + _d(splits["surge_fee"])
        + _d(splits["delivery_markup"])
        + _d(surcharges)
        + _d(bottle_deposit)
        + _d(debt_settlement)
    )


CASES = [
    # (label, vendor_type, delivery_type, product_total, delivery_fee,
    #  bottle_deposit, surcharges, welcome_discount, debt_settlement)
    ("retail plain",            "retail_refill",  "quick_swap",     400, 68,   0,   0,  0,  0),
    ("retail with surcharges",  "retail_refill",  "quick_swap",     400, 68,   0,  80,  0,  0),
    ("retail keep-my-bottle",   "retail_refill",  "keep_my_bottle", 200, 107.5, 300, 0,  0,  0),
    ("retail welcome offer",    "retail_refill",  "quick_swap",     200, 68,  300,  0, 90,  0),
    ("retail debt settled",     "retail_refill",  "quick_swap",     400, 68,   0,   0,  0, 50),
    ("retail everything",       "retail_refill",  "keep_my_bottle", 260, 107.5, 300, 130, 90, 30),
    ("wholesale plain",         "wholesale_b2b",  "quick_swap",    5000, 950,  0,   0,  0,  0),
    ("wholesale surcharges",    "wholesale_b2b",  "quick_swap",    5000, 950,  0,  80,  0,  0),
    ("wholesale everything",    "wholesale_b2b",  "quick_swap",    5000, 950, 300, 230,  0, 50),
]


@pytest.mark.parametrize(
    "label,vendor_type,delivery_type,product_total,delivery_fee,bottle_deposit,surcharges,welcome_discount,debt_settlement",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_the_three_shares_sum_to_what_the_customer_paid(
    label, vendor_type, delivery_type, product_total, delivery_fee,
    bottle_deposit, surcharges, welcome_discount, debt_settlement,
):
    splits = calculate_revenue_splits(
        product_total=product_total,
        delivery_fee=delivery_fee,
        vendor_type=vendor_type,
        bottle_deposit=bottle_deposit,
        rider_surcharges=surcharges,
        delivery_type=delivery_type,
        welcome_discount=welcome_discount,
        debt_settlement=debt_settlement,
    )

    paid = _gross(product_total, delivery_fee, splits, bottle_deposit, surcharges, debt_settlement) - _d(welcome_discount)
    shared = _d(splits["vendor_net"]) + _d(splits["rider_net"]) + _d(splits["platform_total"])

    assert shared == paid, (
        f"{label}: the split does not add up.\n"
        f"  customer paid : {paid}\n"
        f"  vendor_net    : {splits['vendor_net']}\n"
        f"  rider_net     : {splits['rider_net']}\n"
        f"  platform_total: {splits['platform_total']}\n"
        f"  difference    : {paid - shared}"
    )


def test_a_wholesale_order_pays_no_rider_from_the_platform():
    """`rider_net` is zero on wholesale, because nothing ever credits it.

    `update_delivery_status` skips the rider entirely when the vendor is
    wholesale — the rider is the vendor's own employee, paid off-platform. A
    non-zero `rider_net` on that order is money the column claims is owed to
    somebody the settlement path will never pay.
    """
    splits = calculate_revenue_splits(
        product_total=5000,
        delivery_fee=950,
        vendor_type="wholesale_b2b",
        rider_surcharges=230,
    )
    assert splits["rider_net"] == 0
    assert splits["rider_commission"] == 0


def test_wholesale_surcharges_reach_the_vendor():
    """The vendor employs the rider who did the carrying, so the vendor is paid.

    Charging the customer a payload surcharge and allocating it to nobody is the
    defect this asserts against; it must land somewhere, and the vendor is where
    the delivery fee already goes for the same reason.
    """
    without = calculate_revenue_splits(
        product_total=5000, delivery_fee=950, vendor_type="wholesale_b2b", rider_surcharges=0
    )
    with_surcharge = calculate_revenue_splits(
        product_total=5000, delivery_fee=950, vendor_type="wholesale_b2b", rider_surcharges=230
    )
    assert _d(with_surcharge["vendor_net"]) - _d(without["vendor_net"]) == Decimal("230")


def test_retail_surcharges_still_reach_the_rider():
    """The counterpart: on retail a gig rider did the work and keeps all of it."""
    without = calculate_revenue_splits(
        product_total=400, delivery_fee=68, vendor_type="retail_refill", rider_surcharges=0
    )
    with_surcharge = calculate_revenue_splits(
        product_total=400, delivery_fee=68, vendor_type="retail_refill", rider_surcharges=80
    )
    assert _d(with_surcharge["rider_net"]) - _d(without["rider_net"]) == Decimal("80")
    assert with_surcharge["vendor_net"] == without["vendor_net"]


def test_settled_debt_is_platform_revenue():
    """Debt collected on an order belongs to the platform, which fronted it.

    A cancellation penalty and an approved staircase charge were both already
    paid out — the penalty is pure platform revenue, and the staircase charge was
    credited to the rider on the order where it was incurred. Recovering it later
    must not credit anybody a second time.
    """
    without = calculate_revenue_splits(product_total=400, delivery_fee=68)
    with_debt = calculate_revenue_splits(product_total=400, delivery_fee=68, debt_settlement=50)

    assert _d(with_debt["platform_total"]) - _d(without["platform_total"]) == Decimal("50")
    assert with_debt["vendor_net"] == without["vendor_net"]
    assert with_debt["rider_net"] == without["rider_net"]


def test_the_welcome_discount_comes_out_of_platform_margin_only():
    """It is an acquisition cost, never charged back to the vendor or the rider.

    `platform_total` goes negative on a first order and that is correct — the
    vendor is made whole including the full deposit and the rider earns their
    whole fee. A test asserts it rather than leaving the negative figure looking
    like a bug to whoever next reads the ledger.
    """
    without = calculate_revenue_splits(
        product_total=200, delivery_fee=107.5, bottle_deposit=300, delivery_type="keep_my_bottle"
    )
    with_offer = calculate_revenue_splits(
        product_total=200, delivery_fee=107.5, bottle_deposit=300,
        delivery_type="keep_my_bottle", welcome_discount=90,
    )

    assert with_offer["vendor_net"] == without["vendor_net"]
    assert with_offer["rider_net"] == without["rider_net"]
    assert _d(without["platform_total"]) - _d(with_offer["platform_total"]) == Decimal("90")
    assert _d(with_offer["platform_total"]) < 0


def test_the_bottle_deposit_is_paid_to_the_vendor_untaxed():
    """The platform takes no commission on a refundable deposit.

    It is the customer's money held against a bottle, not revenue, so
    commissioning it would be charging a fee on a liability.
    """
    without = calculate_revenue_splits(product_total=200, delivery_fee=68)
    with_deposit = calculate_revenue_splits(product_total=200, delivery_fee=68, bottle_deposit=300)

    assert _d(with_deposit["vendor_net"]) - _d(without["vendor_net"]) == Decimal("300")
    assert with_deposit["vendor_commission"] == without["vendor_commission"]
    assert with_deposit["platform_total"] == without["platform_total"]


def test_the_keep_my_bottle_premium_raises_only_the_rider_commission():
    """The premium pays for extra bottle handling, so it moves the rider's rate.

    Asserted against the configured figures rather than the literals, so a rate
    change in the console does not silently make this test meaningless.
    """
    standard = calculate_revenue_splits(
        product_total=200, delivery_fee=100, delivery_type="quick_swap"
    )
    premium = calculate_revenue_splits(
        product_total=200, delivery_fee=100, delivery_type="keep_my_bottle"
    )

    expected_gap = Decimal("100") * config.get_decimal("keep_my_bottle_commission_premium")
    assert _d(premium["rider_commission"]) - _d(standard["rider_commission"]) == expected_gap
    # Whatever the rider pays extra, the platform receives.
    assert _d(premium["platform_total"]) - _d(standard["platform_total"]) == expected_gap
