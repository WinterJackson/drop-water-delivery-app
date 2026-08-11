"""Money leaves this API as a decimal string, on every path, from every schema.

`test_money_movement_integrity.py` guards how a balance *moves*. This guards how
a figure is *rendered* — the other half, and the one that had two conventions
running side by side for the same values.

Newer code returned strings. Older code returned `float(...)`: the wallet
balance shown to a rider and to a vendor, the customer's payment history, the
reorder totals, and `order_snapshot` — which is the frozen record a delivery
dispute is settled from weeks later. A `Decimal` that has been through a JSON
number is no longer the figure the ledger holds, and `float(Decimal("0.1") +
Decimal("0.2"))` is not `0.3` in any of the four clients either.

Two failure modes, so two kinds of test here:

* an explicit `float(...)` on the serialisation path — caught by walking the AST
  of `routes/` and `services/`;
* a money field annotated `float` on a Pydantic schema, which is the quiet
  version of the same thing: Pydantic coerces the `Decimal` coming off the
  column and nobody sees a cast anywhere.

Adding a money field is therefore adding it to `MONEY_FIELDS` below. That list
is the specification, and `test_every_money_field_in_the_list_still_exists`
fails when a name in it goes away, so it cannot quietly rot into a list of
fields nobody has any more.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCHEMAS = BACKEND / "schemas"
SOURCE_DIRS = ("routes", "services", "jobs")

#: Every response key that carries money.
#:
#: Deliberately a literal list rather than a pattern: `rating`, `distance_km`,
#: `weight_kg`, `capacity`, `completion_rate` and `moq_kg` are all numbers on
#: these same responses and none of them is money. A regex over "amount|fee|
#: balance" would sweep up `delivery_time` and miss `Subtotal`.
MONEY_FIELDS = frozenset(
    {
        # Order and its financial breakdown
        "total_amount", "delivery_fee", "product_subtotal", "platform_total",
        "rider_net", "rider_commission", "vendor_net", "vendor_commission",
        "service_fee", "surge_fee", "delivery_markup", "payload_surcharge",
        "staircase_surcharge", "wallet_discount", "welcome_discount",
        "debt_settlement", "Subtotal", "subtotal", "price", "discount",
        "price_at_order", "subtotal_at_order",
        # Cart
        "welcome_discount_amount", "delivery_fee_quick_swap",
        "delivery_fee_keep_my_bottle",
        # Wallet, payout and settlement
        "wallet_balance", "committed_cash_float", "available_for_withdrawal",
        "non_withdrawable_balance", "available_balance", "lifetime_earnings",
        "pending_payouts", "completed_payouts", "minimum_threshold",
        "transaction_fee", "fee_waiver_threshold",
        # Cash on delivery
        "max_order_value", "taken_today", "daily_cap",
        # Bottles
        "bottle_deposit_balance", "deposit_balance", "deposit_fee",
        "amount_refunded", "debt_balance", "wallet_not_withdrawable",
        # Vendor storefront
        "min_order_value", "wholesale_base_delivery_fee",
        # Quote and delivery-fee preview
        "total", "bottle_deposit", "mpesa_discount", "platform_cost",
        "platform_net", "exchange_fee", "new_bottle_fee", "refill_mine_fee",
        "quick_swap_fee", "keep_my_bottle_fee",
    }
)


def _schema_modules() -> list[pathlib.Path]:
    return sorted(p for p in SCHEMAS.glob("*.py") if p.name != "__init__.py")


def _source_modules() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for directory in SOURCE_DIRS:
        out.extend(sorted((BACKEND / directory).rglob("*.py")))
    return out


def _annotation_text(node: ast.AST | None) -> str:
    return "" if node is None else ast.unparse(node)


# ── Schemas ───────────────────────────────────────────────────────────────


def test_no_money_field_on_any_schema_is_annotated_float():
    """A money column annotated `float` is a money column serialised as a float.

    There is no cast to grep for — Pydantic does the coercion — which is why
    `wallet_balance: float | None = 0.0` survived on three schemas while the
    route-level `float(...)` calls beside it were being found and argued about.
    """
    offenders: list[str] = []

    for path in _schema_modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            name = node.target.id
            if name not in MONEY_FIELDS:
                continue
            annotation = _annotation_text(node.annotation)
            if "float" in annotation:
                offenders.append(f"{path.name}:{node.lineno} {name}: {annotation}")

    assert not offenders, (
        "Money fields annotated `float` — use `MoneyField` / `OptionalMoneyField` "
        "from `utils.money`:\n  " + "\n  ".join(offenders)
    )


def test_every_money_schema_field_uses_the_shared_alias():
    """…and uses *the* alias, not a hand-rolled `Decimal` with its own serializer.

    Two schemas quantizing money two ways is the same class of defect one step
    further along: both are strings, and one of them is `1234.5`.
    """
    allowed = {"MoneyField", "OptionalMoneyField"}
    offenders: list[str] = []

    for path in _schema_modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id not in MONEY_FIELDS:
                continue
            if _annotation_text(node.annotation) not in allowed:
                offenders.append(
                    f"{path.name}:{node.lineno} {node.target.id}: "
                    f"{_annotation_text(node.annotation)}"
                )

    assert not offenders, (
        "Money fields not using the shared alias:\n  " + "\n  ".join(offenders)
    )


# ── Routes, services and jobs ─────────────────────────────────────────────


def test_no_money_key_is_built_with_float_in_a_response_dict():
    """`{"wallet_balance": float(balance)}` — the explicit version.

    Walks every dict literal in `routes/`, `services/` and `jobs/` and fails on
    a money key whose value is a `float(...)` call. This is what the rider's
    and the vendor's wallet summaries did, and what `order_snapshot` did to the
    evidence a dispute is decided on.
    """
    offenders: list[str] = []

    for path in _source_modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or key.value not in MONEY_FIELDS:
                    continue
                # `float(x)`, and `float(x) if … else …` on either branch.
                candidates = (
                    [value.body, value.orelse] if isinstance(value, ast.IfExp) else [value]
                )
                for candidate in candidates:
                    if (
                        isinstance(candidate, ast.Call)
                        and isinstance(candidate.func, ast.Name)
                        and candidate.func.id == "float"
                    ):
                        offenders.append(
                            f"{path.relative_to(BACKEND)}:{key.lineno} "
                            f'"{key.value}": {ast.unparse(candidate)}'
                        )

    assert not offenders, (
        "Money serialised as a float — use `utils.money.money_str`:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_fires_on_a_reintroduced_float_cast():
    """The negative case, on a synthetic module.

    A structural test that has never been shown to fail is a test that passes
    because it matches nothing.
    """
    source = 'def summary():\n    return {"wallet_balance": float(balance)}\n'

    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value in MONEY_FIELDS
                and isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "float"
            ):
                found.append(key.value)

    assert found == ["wallet_balance"]


def test_every_money_field_in_the_list_still_exists():
    """The list is a specification, so it must not outlive what it describes.

    A name that no schema and no response dict mentions any more is a line
    protecting nothing, and the next person reads the list as current.
    """
    corpus = "\n".join(
        path.read_text() for path in _schema_modules() + _source_modules()
    )
    stale = sorted(field for field in MONEY_FIELDS if f'"{field}"' not in corpus
                   and f"'{field}'" not in corpus and f"{field}:" not in corpus)

    assert not stale, (
        "MONEY_FIELDS names fields that no longer appear anywhere in the "
        f"backend — remove them from the list: {stale}"
    )


# ── The serialiser itself ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("0.1"), "0.10"),
        (Decimal("1234.5"), "1234.50"),
        (Decimal("-15.50"), "-15.50"),
        (Decimal("0"), "0.00"),
        (0, "0.00"),
        ("300", "300.00"),
        (None, "0.00"),
        ("", "0.00"),
        # Quantized, not truncated: a half-shilling fee is a real settings value.
        (Decimal("15.505"), "15.51"),
    ],
)
def test_money_str_renders_two_places(value, expected):
    from utils.money import money_str

    assert money_str(value) == expected


def test_money_str_never_raises_on_a_malformed_value():
    """A broken money field must not 500 a screen — nor render as a real figure.

    `"0.00"` is wrong, but it is visibly wrong beside the rest of the row, which
    an exception in the middle of a list response is not.
    """
    from utils.money import money_str

    assert money_str("not a number") == "0.00"
    assert money_str(object()) == "0.00"


def test_money_or_none_keeps_the_difference_between_unset_and_zero():
    from utils.money import money_or_none

    assert money_or_none(None) is None
    assert money_or_none(Decimal("0")) == "0.00"


def test_the_pydantic_alias_serialises_as_a_string_in_both_modes():
    """`model_dump()` and `model_dump(mode="json")` must agree.

    `when_used="json"` would make a test reading `model_dump()` see a `Decimal`
    and pass while the client received something else.
    """
    from pydantic import BaseModel

    from utils.money import MoneyField, OptionalMoneyField

    class Sample(BaseModel):
        total: MoneyField
        fee: OptionalMoneyField = None

    sample = Sample(total=Decimal("1234.5"))
    assert sample.model_dump() == {"total": "1234.50", "fee": None}
    assert sample.model_dump(mode="json") == {"total": "1234.50", "fee": None}
