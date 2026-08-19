"""Money is never arithmetic'd or currency-prefixed inline in an app.

`utils/money.ts` exists in all three apps because every money field crosses the
wire as a **decimal string**. The moment one is used as a JS number the string
becomes a float, and the platform's whole `Decimal` discipline — database,
service, schema, serialiser — is undone at the last step, in the one place the
customer is actually reading.

The guide already forbids the inline discount round trip, and six screens had it
removed once. But nothing failed the build on it: the money half of that fix was
left to `test_no_implicit_any.py`'s ratchet and `money.test.ts`, neither of which
can see a *correctly typed* expression that multiplies a string. So it came
back, and stayed, on the two lines where it does the most damage —

    // drop-customer-app/components/common/CartItem.tsx
    KSH {Math.round((data?.price * data?.quantity) * 100) / 100}

    // drop-vendor-app/app/(screens)/OrderDetail/[id].tsx
    KSH {item.price * item.quantity}

— the customer's cart line and the vendor's copy of the same line. Both rendered
`KSH 748.5` for three bottles at 249.50: a float result, one decimal place, and
two screens that could disagree about one order.

Three rules. The first two are about mangling a figure the server sent; the
third is about inventing one it did not.

* **No `* 100 … / 100` round trip.** It has no legitimate use on money — that is
  what `multiplyMoney`, `sumMoney` and `subtractMoney` are for, and they work in
  integer cents via `BigInt`. A bare `* 100` is fine: that is a percentage.
* **No hand-written `KSH ` in front of an interpolation.** `formatMoney` is the
  one thing that puts a currency in front of a figure, and it is also what
  groups the thousands and pads the cents. A hand-prefixed one does neither, so
  it is visibly a different rendering of the same money on the same screen.

* **No business money value written as a literal.** Every figure the platform
  charges or requires is a `Platform_Settings` row an administrator edits from
  the console, and an app that states its own contradicts the platform the
  moment somebody moves it. `BottleWallet.tsx` carried

      /** Mirrors the server-side minimums so the UI rejects before the round trip. */
      const MIN_TOP_UP_KSH = 10;
      const MIN_WITHDRAWAL_KSH = 500;

  and the comment was wrong: `settlement_service.withdrawal_terms` returns a
  minimum of **1** and a fee of **0** for a customer, because unspent wallet
  credit is their own money coming back rather than earnings. The screen was
  therefore refusing — client-side, before any request was sent — every
  withdrawal under KSH 500 that the platform would have paid, and no server log
  recorded a refusal because none happened. The rider and vendor wallets had
  exactly this removed already; the customer's was missed because there was no
  customer wallet-summary to read the terms from. There is now: they ride on
  `GET /api/bottle-returns/summary`, which already served that screen's balance.

The second rule is what makes the first enforceable in practice: a figure that
has to reach `formatMoney` to get its currency cannot easily be a raw float on
the way there. The third is what stops the app answering a money question the
server is the only thing entitled to answer.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")
SKIP_PARTS = {"node_modules", ".expo", "android", "ios", "dist", "__tests__", "build"}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)

#: `… * 100) / 100` in any spacing — the float round trip.
_ROUND_TRIP = re.compile(r"\*\s*100\s*\)\s*/\s*100")

#: A currency literal written directly in front of an interpolation, in JSX
#: (`KSH {…}`) or a template literal (`KSH ${…}`).
_HAND_PREFIX = re.compile(r"KSH\s+\$?\{")

#: A constant whose *name* says it holds a business money figure, assigned a
#: number. Deliberately keyed on money words rather than on `MIN`/`MAX` alone:
#: `MAX_RECONNECT_ATTEMPTS`, `MIN_BODY` and `MIN_FLUSH_INTERVAL_MS` are limits
#: on this app's own behaviour, not terms of trade, and belong in the source.
_MONEY_WORDS = (
    "KSH", "WITHDRAW", "TOPUP", "TOP_UP", "PAYOUT", "DEPOSIT", "CASHBACK",
    "COMMISSION", "SURCHARGE", "DISCOUNT", "TARIFF", "SERVICE_FEE",
)
#: A shilling figure written into a sentence — "Minimum amount is KSH 500",
#: "a KSH 50 cancellation penalty". The constant rule below cannot see these,
#: because there is no constant: the number is inside the copy.
_MONEY_IN_COPY = re.compile(r"KSH\s*[0-9]")

_MONEY_LITERAL = re.compile(
    r"\b(?:const|let|var)\s+(\w*(?:" + "|".join(_MONEY_WORDS) + r")\w*)\s*"
    r"(?::\s*number\s*)?=\s*-?\d",
    re.I,
)


def _sources() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for app in APPS:
        root = REPO / app
        if not root.is_dir():
            continue
        for path in root.rglob("*.ts*"):
            if path.suffix not in (".ts", ".tsx"):
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            files.append(path)
    return files


def _code_only(source: str) -> str:
    """Source minus comments — this file and the fixes quote the defective lines."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


SOURCES = _sources()


def test_the_scan_reaches_the_apps() -> None:
    """Non-vacuity: a guard over an empty file list passes for the wrong reason."""
    assert len(SOURCES) > 200, f"only {len(SOURCES)} app sources found — the walk is broken"
    names = {p.name for p in SOURCES}
    assert "Cart.tsx" in names and "money.ts" in names


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_float_round_trip_on_money(path: pathlib.Path) -> None:
    code = _code_only(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip()
        for line in code.splitlines()
        if _ROUND_TRIP.search(line)
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)} does the `* 100 … / 100` float round trip on money:\n  "
        + "\n  ".join(offenders)
        + "\nUse multiplyMoney / sumMoney / subtractMoney from utils/money."
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_hand_written_currency_prefix(path: pathlib.Path) -> None:
    code = _code_only(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip()
        for line in code.splitlines()
        if _HAND_PREFIX.search(line)
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)} writes 'KSH' in front of an interpolation:\n  "
        + "\n  ".join(offenders)
        + "\nUse formatMoney(), which supplies the currency, the grouping and the cents."
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_business_money_value_is_a_literal(path: pathlib.Path) -> None:
    """A figure the platform charges is a settings row, never a constant here.

    `utils/money.ts` is exempt: its constants are about the *representation* of
    money — how many cents in a shilling — not about what anything costs.
    """
    if path.name == "money.ts":
        return
    code = _code_only(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip() for line in code.splitlines() if _MONEY_LITERAL.search(line)
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)} states a business money value as a literal:\n  "
        + "\n  ".join(offenders)
        + "\nThese are Platform_Settings rows — read them from the server."
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_business_money_value_is_written_into_copy(path: pathlib.Path) -> None:
    """The same rule, for the figures that live inside a sentence.

    `MIN_WITHDRAWAL_KSH` was at least a named constant somebody could find.
    These were not:

        "Withdraw your float balance directly to your M-Pesa. Minimum amount is KSH 500."
        "…a KSH 50 cancellation penalty will apply to your account."

    The first was wrong for a wholesale vendor, whose minimum is 1,000. The
    second was wrong after pickup, where the penalty is 150, and wrong again for
    anybody with a free cancellation left, where it is nothing at all. Comments
    are stripped before the scan — these fixes quote the lines they removed.
    """
    code = _code_only(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip() for line in code.splitlines() if _MONEY_IN_COPY.search(line)
    ]
    assert not offenders, (
        f"{path.relative_to(REPO)} states a shilling figure in its copy:\n  "
        + "\n  ".join(offenders)
        + "\nRender the server's figure with formatMoney(), or say nothing."
    )
