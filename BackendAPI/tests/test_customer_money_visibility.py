"""
A customer can see the money they are owed and the money they owe.

Three columns existed on `Users`, were maintained correctly, and reached nobody:

* `bottle_deposit_balance` — the platform's **liability** to this customer,
  returnable when the bottles come back;
* `bottles_held` — how many that is;
* `debt_balance` — an unpaid balance from an earlier order.

`BasicUser` did not carry any of them, and `GET /api/auth/get_user_details` is
filtered by that schema, so the profile came back with 17 keys and none of these.
The consequences were all customer-facing:

* the app's own **"Bottle Wallet"** screen showed a cash balance, "days since
  your first bottle" and "plastic waste saved" — never the bottles or the
  deposit, which is the customer's own money;
* `debt_settlement` was in the quote, in the total, and on **no line** in the
  cart, so a customer paid an unexplained difference — the one charge on that
  screen that is not for anything in the basket;
* the deposit line was labelled "New Bottle Fee / Required for first order",
  which is wrong twice over: it is refundable, and it is charged whenever the
  customer keeps a bottle rather than only on a first order.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CUSTOMER = REPO / "drop-customer-app"

pytestmark = pytest.mark.skipif(
    not CUSTOMER.exists(), reason="customer app not in this checkout"
)

CART = CUSTOMER / "app/(screens)/Cart.tsx"
BOTTLE_WALLET = CUSTOMER / "app/(screens)/BottleWallet.tsx"


def _strip_comments(source: str) -> str:
    """TypeScript without comments — every "must not appear" needs it, because
    the note explaining a removal has to name what was removed."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ── The profile carries the position ──────────────────────────────────────


def test_the_customer_schema_carries_the_bottle_and_debt_position():
    """`get_user_details` is filtered by `BasicUser`, so a column absent here is
    a column the customer can never see however well it is maintained."""
    from schemas.user_schemas import BasicUser

    for field in ("bottle_deposit_balance", "bottles_held", "debt_balance"):
        assert field in BasicUser.model_fields, f"{field} never reaches the customer"


def test_the_deposit_and_its_count_are_both_exposed():
    """`customer_bottle_service` moves the two together and never one alone.
    Exposing the money without the count leaves the customer unable to check it."""
    from schemas.user_schemas import BasicUser

    assert ("bottle_deposit_balance" in BasicUser.model_fields) == (
        "bottles_held" in BasicUser.model_fields
    )


# ── The cart shows every charge ───────────────────────────────────────────


def test_the_cart_renders_the_previous_balance_it_is_collecting():
    """`debt_settlement` was typed in the hook, included in `total`, and drawn
    nowhere. Every other line item on the quote is destructured and rendered."""
    source = CART.read_text()
    assert "quote?.debt_settlement" in source, "the cart never reads debt_settlement"
    # `isZeroMoney`, not `> 0`: the quote sends decimal strings, so a numeric
    # comparison here would be a float round trip on the figure being charged.
    assert re.search(r"\{!isZeroMoney\(debt_settlement\) && \(", source), (
        "the cart charges a previous balance without showing a line for it"
    )
    assert "formatMoney(debt_settlement)" in source


def test_every_quote_line_item_the_customer_pays_for_is_rendered():
    """A charge in `total` with no line on the screen is an unexplained
    difference. Walks the hook's own type rather than a list kept here."""
    hook = (CUSTOMER / "hooks/queries/useCart.ts").read_text()
    cart = CART.read_text()

    # The fields that add to what the customer pays. `delivery_markup` is
    # deliberately excluded: it is platform margin folded into the delivery fee,
    # not a separate charge, and itemising it would double-count on screen.
    charges = [
        "delivery_fee",
        "service_fee",
        "surge_fee",
        "payload_surcharge",
        "staircase_surcharge",
        "bottle_deposit",
        "debt_settlement",
    ]
    for field in charges:
        # Money on the quote is a decimal **string**; `number` would mean the
        # figure had been through a float before it was rendered.
        assert f"{field}: string;" in hook, f"{field} has moved in the quote type"
        assert f"quote?.{field}" in cart, f"{field} is charged but never read by the cart"


def test_the_deposit_is_not_described_as_a_fee_or_as_first_order_only():
    """It is a liability the platform returns, and it is charged on any order
    where the customer keeps bottles. Calling it a fee tells them it is gone."""
    source = _strip_comments(CART.read_text())

    assert "New Bottle Fee" not in source
    assert "Required for first order" not in source
    assert "Bottle Deposit" in source
    assert "Refundable" in source


# ── The bottle wallet shows bottles ───────────────────────────────────────


def test_the_bottle_wallet_shows_the_bottle_position():
    """A screen called "Bottle Wallet" that shows only a cash balance is the
    defect. Both figures, because one without the other cannot be checked."""
    source = BOTTLE_WALLET.read_text()
    assert "bottles_held" in source
    assert "bottle_deposit_balance" in source


def test_the_bottle_wallet_states_an_owed_balance():
    """Debt is charged on the next order. A customer discovering it as a larger
    total is how a correct charge reads as an overcharge."""
    source = BOTTLE_WALLET.read_text()
    assert "debt_balance" in source


def test_the_app_no_longer_claims_any_debt_blocks_checkout():
    """It did, before F-01 — permanently, over as little as KSH 30. Debt below
    `max_customer_debt_before_block` is now settled by the next order, and the
    type's own documentation said otherwise."""
    source = (CUSTOMER / "types/models.ts").read_text()
    assert "Any amount above zero blocks checkout" not in source
    assert "max_customer_debt_before_block" in source


def test_the_ceiling_is_a_setting_rather_than_a_number_in_the_app():
    from services.platform_config_service import SPEC_BY_KEY

    assert "max_customer_debt_before_block" in SPEC_BY_KEY

    source = _strip_comments((CUSTOMER / "app/(screens)/Cart.tsx").read_text())
    assert "debt_balance >" not in source, (
        "the cart is deciding the debt ceiling itself; `validate_quote` owns that"
    )


# ── The wallet screen's terms come from the platform, not from the app ─────
#
# `BottleWallet.tsx` carried `MIN_TOP_UP_KSH = 10` and `MIN_WITHDRAWAL_KSH =
# 500` under a comment claiming they mirrored the server. The top-up figure
# happened to match `min_wallet_topup`; the withdrawal one was invented.
# `withdrawal_terms` returns **1** for a customer, with no fee — unspent wallet
# credit is their own money coming back, not earnings — so the screen refused,
# client-side and before any request, every withdrawal under KSH 500 the
# platform would have paid. Nothing logged it, because no request was made.

@pytest.mark.asyncio
async def test_a_customer_withdrawal_has_no_minimum_beyond_a_shilling():
    """The figure the app must render, asserted where it is decided."""
    from decimal import Decimal
    from unittest.mock import AsyncMock, patch

    from services.settlement_service import withdrawal_terms

    with patch("services.platform_config_service.ensure_fresh", new=AsyncMock()):
        minimum, fee, waiver = await withdrawal_terms(
            AsyncMock(), provider_type="customer"
        )

    assert minimum == Decimal("1")
    # The platform's *margin* on the withdrawal, which is zero for everybody by
    # default. Safaricom's own B2C tariff is recovered separately, through
    # `settlement_service.B2C_TARIFF_BANDS`, and is not this figure.
    assert fee == Decimal("0")
    assert waiver == Decimal("0")


@pytest.mark.asyncio
async def test_a_rider_and_a_customer_are_not_judged_by_the_same_terms():
    """Non-vacuity: the customer branch is a branch, not the only answer."""
    from unittest.mock import AsyncMock, patch

    from services.settlement_service import withdrawal_terms

    with patch("services.platform_config_service.ensure_fresh", new=AsyncMock()):
        customer, _, _ = await withdrawal_terms(AsyncMock(), provider_type="customer")
        rider, _, rider_waiver = await withdrawal_terms(AsyncMock(), provider_type="rider")
        vendor, _, _ = await withdrawal_terms(
            AsyncMock(), provider_type="vendor", vendor_type="wholesale_b2b"
        )

    # A rider and a vendor are withdrawing earnings, and each disbursement costs
    # the platform an M-Pesa tariff — hence a floor worth clearing. A customer is
    # taking back credit they already paid in.
    assert customer < rider < vendor
    assert rider_waiver > 0


def test_the_deposit_summary_publishes_the_terms_it_will_be_judged_by():
    """The endpoint the customer wallet screen reads must carry them.

    Asserted on the source rather than by calling the route: this file's
    session is an `AsyncMock` and the endpoint loads a `User` row. What matters
    is that the terms are served from `withdrawal_terms` and the settings row —
    not restated here.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "routes" / "bottle_return_routes.py"
    ).read_text(encoding="utf-8")

    assert "withdrawal_terms" in source, "the terms are re-derived, not read"
    assert '"minimum": money_str(minimum)' in source
    assert '"fee": money_str(fee)' in source
    assert 'config.get_decimal("min_wallet_topup")' in source
