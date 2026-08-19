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

Two rules, because the defect has two halves and either alone is survivable:

* **No `* 100 … / 100` round trip.** It has no legitimate use on money — that is
  what `multiplyMoney`, `sumMoney` and `subtractMoney` are for, and they work in
  integer cents via `BigInt`. A bare `* 100` is fine: that is a percentage.
* **No hand-written `KSH ` in front of an interpolation.** `formatMoney` is the
  one thing that puts a currency in front of a figure, and it is also what
  groups the thousands and pads the cents. A hand-prefixed one does neither, so
  it is visibly a different rendering of the same money on the same screen.

The second rule is what makes the first enforceable in practice: a figure that
has to reach `formatMoney` to get its currency cannot easily be a raw float on
the way there.
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
