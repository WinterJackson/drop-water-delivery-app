"""A ledger amount's direction comes from the amount, never from its type.

`apply_wallet_delta` says it plainly: "amount is signed: negative debits. The
stored ledger amount keeps that sign." A customer paying from their wallet is
written as `amount=-quote.wallet_discount`, and `money_str` preserves the sign
on the wire.

The customer and vendor apps ignored it and derived the sign from an allow-list
of transaction types — with `order_payment` in the *positive* list. Two things
follow. The direction is wrong for a customer, whose order payment is a debit.
And the same type carries both directions for a rider: `deliverer_service`
writes `order_payment` as `-cash_float_required(order)` when they take on a cash
order and as `+vendor_net` when they earn, so no allow-list can be right.

The rendering compounded it, because the prefix was drawn *and* the raw signed
amount printed: with the real ledger a wallet-paid order read
"+-KSH 450.00" and a withdrawal "--KSH 200.00".

Confirmed on a handset against seeded ledger rows: before, a `-450.00` order
payment rendered `+KSH 450.00`; after, `-KSH 450.00`.

The rider app already read the amount and carried a comment explaining why —
the fix existed in one app and had never been carried to the other two.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
APPS = ("drop-customer-app", "drop-vendor-app", "drop-rider-app")

#: `[...].includes(x.transaction_type)` — an allow-list of types being asked to
#: decide something about one transaction. Deliberately narrow: the filter tabs
#: on the same screens are `{ id: "top_up", label: ... }` objects and must not
#: trip this.
_TYPE_ALLOW_LIST = re.compile(r"\.includes\(\s*\w+\.transaction_type\s*\)")


def _screens(app: str):
    base = ROOT / app / "app"
    if base.exists():
        yield from base.rglob("*.tsx")
    components = ROOT / app / "components"
    if components.exists():
        yield from components.rglob("*.tsx")


@pytest.mark.parametrize("app", APPS)
def test_no_app_decides_direction_from_the_transaction_type(app):
    offences = []
    for path in _screens(app):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith(("//", "*", "/*")):
                continue
            if _TYPE_ALLOW_LIST.search(line):
                offences.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
    assert not offences, (
        "The ledger amount is signed — read the sign from it with "
        "`isNegativeMoney`, not from an allow-list of types, which cannot be "
        "right for `order_payment` in either app:\n  " + "\n  ".join(offences)
    )


@pytest.mark.parametrize("app", APPS)
def test_the_transactions_screen_reads_the_amount(app):
    """And it must positively do the right thing, not merely avoid the wrong one."""
    screen = ROOT / app / "app" / "(screens)" / "Transactions.tsx"
    if not screen.exists():
        pytest.skip(f"{app} has no Transactions screen")
    body = screen.read_text()
    assert "isNegativeMoney(" in body, (
        f"{app}'s Transactions screen no longer derives direction from the amount"
    )


@pytest.mark.parametrize("app", APPS)
def test_the_magnitude_is_not_stripped_by_hand(app):
    """`amount.replace("-", "")` is a string op on money; `absMoney` is the one."""
    offences = []
    for path in _screens(app):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith(("//", "*", "/*")):
                continue
            if re.search(r"""(amount|balance|total)\w*\.replace\(\s*["']-["']""", line):
                offences.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
    assert not offences, "Use `absMoney` rather than stripping a minus sign:\n  " + "\n  ".join(offences)


@pytest.mark.parametrize("app", APPS)
def test_every_app_has_the_abs_helper(app):
    body = (ROOT / app / "utils" / "money.ts").read_text()
    assert "export function absMoney" in body, f"{app}/utils/money.ts lost absMoney"
