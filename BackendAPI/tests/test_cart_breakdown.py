"""The cart's breakdown adds up to the total it sits above.

`compute_order_quote` is the one place an order total is computed, and the
customer's cart renders its fields verbatim. That rule protects the *figures*;
it says nothing about how many times a screen prints one, or which of two
similarly-named fields it reaches for — and both of those are how a correct
total ends up under a column of lines that contradicts it.

Three failures, all of them invisible to `tsc` and to every existing suite,
because each one is valid TSX rendering a correctly-formatted decimal string:

- **A field rendered twice.** `bottle_deposit` and `welcome_discount` each had
  two blocks in `Cart.tsx`, ~100 lines apart, with different copy — one pair
  written beside the goods and one beside the fees. Nothing summed wrongly: the
  server's `total` was right and was displayed. But a customer adding up what
  was in front of them counted the deposit twice and the discount twice, and
  the arithmetic on screen missed the total by exactly one deposit less one
  discount. A breakdown that does not reconcile reads as the platform
  overcharging, and it is checked against an M-Pesa message that agrees with
  the total and not with the lines.

- **The subtotal taken from the cart instead of the quote.** `Cart.total_amount`
  is a stored `Numeric` column written when the basket changes;
  `quote.product_subtotal` is summed from the items the total was actually
  built from. The screen computed the right value into a `subtotal` local and
  then rendered the stored column anyway, leaving the local unread — the
  "computed and never used" defect `test_no_undefined_names.py` catches on the
  Python side, here on the one line a customer checks first.

- **A settings row quoted as a literal.** `welcome_discount_rate` is one of the
  85 rows an administrator edits from the console, and it applies to *one*
  bottle's deposit rather than the whole one. "Welcome Offer (30% off deposit)"
  was therefore wrong about the base on any multi-bottle order, and wrong about
  the rate the moment anybody moved it — on both the customer's cart and the
  vendor's copy of the same order, which is where a disagreement gets argued.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CART = ROOT / "drop-customer-app" / "app" / "(screens)" / "Cart.tsx"

# Every money field the breakdown renders. Each is one charge or one credit, so
# each gets exactly one line.
QUOTE_FIELDS = (
    "subtotal",
    "deliveryFee",
    "serviceFee",
    "surgeFee",
    "deliveryMarkup",
    "payload_surcharge",
    "staircase_surcharge",
    "bottle_fee_total",
    "debt_settlement",
    "welcome_discount",
    "mpesa_discount",
    "wallet_discount",
    "finalTotal",
)

# Quote fields that move the total but are deliberately not their own line, with
# the reason. Anything else the quote sends must be rendered.
NOT_A_LINE = {
    # Platform margin *inside* the delivery fee, not a separate charge. Adding
    # it as a line would bill the customer twice on screen for one figure.
    "delivery_markup",
    # The total is the sum, not a component of it.
    "total",
}


def _strip_comments(source: str) -> str:
    """Drop JSX and block comments so prose about a field is not a render of it."""
    source = re.sub(r"\{/\*.*?\*/\}", "", source, flags=re.DOTALL)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


@pytest.fixture(scope="module")
def cart_source() -> str:
    assert CART.exists(), f"{CART} has moved; this guard is measuring nothing."
    return _strip_comments(CART.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", QUOTE_FIELDS)
def test_each_money_field_has_exactly_one_line(cart_source: str, field: str) -> None:
    """One charge, one line. Twice is a breakdown that will not reconcile."""
    # `finalTotal` is deliberately allowed more than one render: the total also
    # appears on the checkout button and in the cash-on-delivery confirmation,
    # which are restatements of the same figure rather than extra lines.
    count = len(re.findall(rf"formatMoney\(\s*{re.escape(field)}\s*\)", cart_source))
    if field == "finalTotal":
        assert count >= 1, "the total is not rendered at all"
        return
    assert count <= 1, (
        f"`{field}` is rendered {count} times in Cart.tsx. Every charge in a "
        f"quote is rendered as its own line — exactly once. A second block for "
        f"the same field double-counts it for anybody adding up the screen."
    )


def test_the_subtotal_line_comes_from_the_quote(cart_source: str) -> None:
    """The stored cart column is not the figure the total was built from."""
    assert not re.search(r"formatMoney\(\s*Cart\?\.total_amount\s*\)", cart_source), (
        "The Subtotal line renders `Cart.total_amount`, a stored column written "
        "when the basket changes. `quote.product_subtotal` is summed from the "
        "same items as the total below it; render that (the `subtotal` local "
        "already resolves it, falling back to the cart)."
    )


def test_the_subtotal_local_is_actually_read(cart_source: str) -> None:
    """A value computed correctly and then not rendered is the whole defect."""
    if "const subtotal" not in cart_source:
        pytest.skip("no `subtotal` local to check")
    assert re.search(r"formatMoney\(\s*subtotal\s*\)", cart_source), (
        "`subtotal` is computed from the quote and never rendered."
    )


# The customer's cart and the vendor's copy of the same order. A rate stated on
# one and not the other is an argument nobody can settle from the screens.
RATE_SURFACES = (
    CART,
    ROOT / "drop-vendor-app" / "app" / "(screens)" / "OrderDetail" / "[id].tsx",
)


@pytest.mark.parametrize("path", RATE_SURFACES, ids=lambda p: p.parent.name)
def test_no_screen_states_the_welcome_rate(path: pathlib.Path) -> None:
    """`welcome_discount_rate` is a row. A literal beside money contradicts it."""
    assert path.exists(), f"{path} has moved; this guard is measuring nothing."
    source = _strip_comments(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"\d+\s*%", line) and re.search(r"welcome|discount|offer", line, re.I)
    ]
    assert not offenders, (
        "A welcome-offer percentage is written into the source: "
        + "; ".join(offenders)
        + ". The rate is a Platform_Settings row and it applies to one bottle's "
        "deposit; the amount rendered beside the label is already the truth."
    )


def _quote_money_fields() -> set[str]:
    """Every money field `compute_order_quote` serialises to the cart."""
    source = (ROOT / "BackendAPI" / "services" / "pricing_service.py").read_text(encoding="utf-8")
    return set(re.findall(r'"([a-z_]+)":\s*money_str', source))


def test_the_quote_field_scan_still_works() -> None:
    """If this stops matching, the assertion below passes vacuously."""
    fields = _quote_money_fields()
    assert {"product_subtotal", "delivery_fee", "welcome_discount"} <= fields
    assert len(fields) >= 10, sorted(fields)


def test_every_figure_in_the_total_has_a_line_on_the_cart(cart_source: str) -> None:
    """A charge or credit the customer cannot see is a difference they cannot check.

    `debt_settlement` sat inside `total` with no line, so the customer paid an
    unexplained amount. `mpesa_discount` was the same defect pointing the other
    way — money *off* the total, applied by the server, rendered nowhere. That
    one is self-defeating as well as opaque: the reason it is framed as a
    discount for paying by M-Pesa rather than a surcharge for paying cash is so
    the customer sees they are being rewarded, and a reward nobody is shown
    steers nobody.

    Discovered from the quote rather than listed here, so a new component of the
    total is covered the day somebody adds it.
    """
    missing = sorted(
        field
        for field in _quote_money_fields() - NOT_A_LINE
        # `bottle_deposit` reaches the screen through the `bottle_fee_total`
        # local; the others are read under their own name.
        if field != "bottle_deposit"
        and not re.search(rf"quote\?\.{re.escape(field)}\b", cart_source)
    )
    assert not missing, (
        "These figures are part of the total the customer is charged and appear "
        "nowhere on the cart: " + ", ".join(missing) + ". Every charge in a "
        "quote is rendered as its own line."
    )
