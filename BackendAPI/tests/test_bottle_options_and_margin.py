"""Three bottle transactions, one deduction from the delivery fee, no fee the platform eats.

Three separate defects, all of them arithmetic the customer or the rider could
have checked and found wrong:

* **A deposit on the customer's own property.** `keep_my_bottle` was named for
  the hygiene option — the rider collects *your* bottle, refills it, brings it
  back — and implemented as "you are keeping the bottle we brought, so pay
  KSH 300". A household that did not want to drink from a stranger's bottle was
  charged a deposit on a bottle they already owned.

* **Two cuts from one pot.** The stated rule is a single 10% rider commission on
  the delivery fee. A 15% platform markup was taken from the same fee, so a
  KSH 50 short hop left the rider KSH 37.50 rather than KSH 45 — and no rider
  reading the rule could reproduce their own payout.

* **A withdrawal fee the platform paid.** A flat KSH 15 waived above KSH 1,000
  charged nothing at exactly the amounts where Safaricom's tariff is highest.
  Every large withdrawal lost money, and the loss grew with the amount.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings — any "must not appear" needs it, because the
    note explaining a removal has to name what was removed."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── Three transactions, and only one of them takes a deposit ──────────────


def test_the_three_options_exist_and_are_distinct():
    from services import delivery_types

    assert set(delivery_types.ALL) == {"exchange", "refill_mine", "new_bottle"}


@pytest.mark.parametrize(
    "delivery_type,deposit",
    [
        ("exchange", False),      # pool bottle for pool bottle
        ("refill_mine", False),   # their own bottle — nothing of ours leaves
        ("new_bottle", True),     # our bottle stays with them
    ],
)
def test_only_the_new_bottle_option_takes_a_deposit(delivery_type, deposit):
    """The whole defect in one assertion: a customer having *their own* bottle
    refilled was charged a deposit on their own property."""
    from services import delivery_types

    assert delivery_types.takes_deposit(delivery_type) is deposit


def test_the_old_names_still_price_as_what_they_meant():
    """An app in somebody's pocket does not update because the backend did.

    `keep_my_bottle` maps to `new_bottle`, **not** `refill_mine`: every historic
    order of it charged a deposit and left a platform bottle behind, which is
    what `new_bottle` means. Mapping it to `refill_mine` would assert those
    customers own bottles they do not.
    """
    from services import delivery_types

    assert delivery_types.normalise("quick_swap") == "exchange"
    assert delivery_types.normalise("keep_my_bottle") == "new_bottle"
    assert delivery_types.takes_deposit("keep_my_bottle") is True
    # Unknown values price as the ordinary case rather than refusing to price.
    assert delivery_types.normalise("something-we-retired") == "exchange"
    assert delivery_types.normalise(None) == "exchange"


def test_a_first_order_no_longer_forces_a_deposit_by_itself():
    """It used to be `keep_my_bottle or is_first_order`, and the second half was
    standing in for `new_bottle` before that type existed — so a first-time
    customer exchanging a bottle they already owned was charged for one."""
    source = _code_only(BACKEND / "services" / "pricing_service.py")

    assert "delivery_types.takes_deposit(delivery_type)" in source
    assert "or is_first_order:" not in source, (
        "the deposit is being decided by whether it is a first order again"
    )


def test_the_round_trip_is_not_priced_as_a_short_hop():
    """`refill_mine` is three legs of riding — to the customer, to the station,
    back to the customer. Pricing that at the flat short-hop fee is how a rider
    learns to decline a whole category of order."""
    from services import delivery_types

    assert delivery_types.is_round_trip("refill_mine") is True
    assert delivery_types.is_round_trip("exchange") is False

    source = _code_only(BACKEND / "services" / "dispatch_policy.py")
    assert "delivery_types.is_round_trip(delivery_type)" in source
    # The distance is a `Decimal` here — the fee schedule is money end to end,
    # and `km` is what it is multiplied by a shilling rate.
    assert "if not round_trip and km <= threshold_km:" in source


def test_no_module_still_branches_on_the_retired_names():
    """The names are accepted on the wire and normalised once. A module that
    compares against them directly has two vocabularies, which is how the
    hygiene option came to charge a deposit in the first place."""
    for module in ("pricing_service.py", "dispatch_policy.py", "order_service.py"):
        source = _code_only(BACKEND / "services" / module)
        for retired in ('== \'keep_my_bottle\'', '== \'quick_swap\''):
            assert retired not in source, f"{module} still branches on {retired}"


# ── One deduction from the delivery fee ───────────────────────────────────


def test_the_rider_keeps_the_delivery_fee_less_one_commission():
    """The stated rule is a single 10% commission. A second 15% markup from the
    same fee meant no rider reading the rule could reproduce their own payout."""
    from services import platform_config_service as config

    assert config.DEFAULTS["retail_delivery_markup_rate"] == 0.0, (
        "a second cut from the delivery fee is back; raise the rider commission "
        "instead — one number the rider can check"
    )


def test_a_short_hop_pays_the_rider_the_stated_share():
    """KSH 50 flat, 10% commission, so KSH 45 to the rider and KSH 5 to the
    platform. This is the arithmetic a rider will do in their head."""
    from services import platform_config_service as config
    from services.order_service import calculate_revenue_splits

    with config.temporarily({**config.effective(), "retail_delivery_markup_rate": 0.0}):
        splits = calculate_revenue_splits(
            product_total=0.0, delivery_fee=50.0, vendor_type="retail_refill",
        )

    assert Decimal(str(splits["rider_net"])) == Decimal("45.00")
    assert Decimal(str(splits["rider_commission"])) == Decimal("5.00")


# ── The platform never funds a disbursement ───────────────────────────────


@pytest.mark.parametrize("amount", [250, 500, 1000, 3000, 5000, 20000, 50000])
def test_a_withdrawal_never_costs_the_platform_money(amount):
    """The rule, at every amount. The previous shape charged *nothing* exactly
    where Safaricom's tariff is highest, so the platform paid KSH 40 to move
    KSH 20,000 and recovered none of it."""
    from services.settlement_service import b2c_tariff, banded_fee_for

    a = Decimal(amount)
    tariff = b2c_tariff(a)

    # Margin zero (the shipped default) and margin set — neither may lose.
    for margin in (Decimal("0"), Decimal("15")):
        fee = banded_fee_for(a, margin, Decimal("1000"))
        assert fee >= tariff, (
            f"KSH {amount}: charged {fee} against a tariff of {tariff} — "
            "the platform is funding this disbursement"
        )


def test_the_default_withdrawal_margin_is_zero():
    """Cost recovery, not a revenue line. Raising it is a deliberate decision
    taken on the console, not something that ships switched on."""
    from services import platform_config_service as config

    assert config.DEFAULTS["payout_transaction_fee"] == 0.0


def test_consolidating_withdrawals_is_still_cheaper_for_the_provider():
    """The incentive survives without anybody subsidising it: the tariff being
    per-transaction *is* the incentive."""
    from services.settlement_service import banded_fee_for

    one_big = banded_fee_for(Decimal("20000"), Decimal("0"), Decimal("1000"))
    twenty_small = 20 * banded_fee_for(Decimal("1000"), Decimal("0"), Decimal("1000"))

    assert one_big < twenty_small


# ── The figures the console owns ──────────────────────────────────────────


def test_the_customer_facing_figures_are_settings_with_the_agreed_defaults():
    from services import platform_config_service as config

    assert config.DEFAULTS["retail_service_fee"] == 35.0
    assert config.DEFAULTS["mpesa_payment_discount"] == 10.0
    assert config.DEFAULTS["short_hop_delivery_fee"] == 50.0
    assert config.DEFAULTS["short_hop_threshold_m"] == 600


def test_delivery_radius_and_fee_are_platform_settings_not_vendor_fields():
    """Both are set on the console and nowhere else. The rider is paid out of
    the delivery fee, so a vendor undercutting to win orders would be spending
    the rider's money; and the retail radius protects water temperature and
    rider time, not just query cost."""
    from services import platform_config_service as config

    for key in ("retail_delivery_base_fee", "retail_delivery_per_km",
                "short_hop_delivery_fee", "retail_max_distance_km"):
        assert key in config.SPEC_BY_KEY

    for withdrawn in ("vendor_delivery_base_floor", "vendor_delivery_per_km_floor",
                      "vendor_radius_max_km"):
        assert withdrawn not in config.SPEC_BY_KEY, (
            f"{withdrawn} would let a vendor set what the console owns"
        )
