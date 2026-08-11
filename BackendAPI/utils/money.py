"""How money leaves this API.

Money is `Decimal` from the database through the service layer, and it reaches a
client as a **decimal string** — never a JSON number. `float(Decimal("0.1")) +
float(Decimal("0.2"))` is not `0.3`, and once a balance has been through a JSON
number it is no longer the figure the ledger holds.

This module is the only conversion. It exists because there were two conventions
in one API: newer code (`/cart/quote`, `wallet-summary`, `growth/cohorts`) sent
strings and older code sent `float(...)` — including the balances shown to a
rider and a vendor, and the frozen order snapshot that a dispute is settled
from. `test_money_serialisation.py` fails the build if a money key is emitted
any other way.

The client counterpart is `formatMoney`/`sumMoney`: `lib/utils/format.ts` on the
console, `utils/money.ts` in each of the three apps. Neither side ever parses a
money string into a number to do arithmetic on it.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Optional, Union

from pydantic import PlainSerializer

#: Two places, matching the `Numeric(10, 2)` columns the figures come off.
CENTS = Decimal("0.01")

Money = Union[Decimal, int, str, float, None]

#: A money *argument* — anything `Decimal(str(...))` accepts, no `None`.
#:
#: Pricing helpers take this and return `Decimal`. Annotating them `float` is
#: what made every caller wrap the result back up in `Decimal(str(...))`, a
#: float round trip in the middle of the money path.
MoneyIn = Union[Decimal, int, str, float]


def money_str(value: Money) -> str:
    """A money value as the string a client renders. `None` is `"0.00"`.

    Accepts `float` because some call sites still hold one, and quantizing it
    here is strictly better than letting it reach the wire — but a `float` in a
    money *column* is a defect this function cannot fix.
    """
    if value is None or value == "":
        return "0.00"
    try:
        # HALF_UP, not the default HALF_EVEN. Banker's rounding is the right
        # answer for a long series of sums and the wrong one for a single figure
        # shown to a person: a fee of 15.505 rendering as 15.50 on one screen
        # and 15.51 on another is a discrepancy nobody can explain.
        return str(Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        # A money field that cannot be parsed is not a reason to 500 a screen,
        # but it must never render as a plausible-looking figure either.
        return "0.00"


def money_or_none(value: Money) -> Optional[str]:
    """Like `money_str`, but preserves `None`.

    For fields where "no figure" and "zero" are different facts — an unset
    minimum, a fee that does not apply. Rendering the first as the second is how
    a missing value becomes a confident wrong one.
    """
    return None if value is None else money_str(value)


#: A money field on a Pydantic schema. Validates as `Decimal`, serialises as the
#: decimal string.
#:
#: Annotating a money column `float` is the quiet version of the same defect the
#: route-level `float(...)` calls were: Pydantic coerces the `Decimal` coming off
#: the column and the figure is a JSON number by the time anybody notices. Every
#: money field on every schema is one of these two aliases.
#:
#: `when_used="always"` rather than `"json"`, so a test reading `model_dump()`
#: sees exactly what the client will.
MoneyField = Annotated[
    Decimal, PlainSerializer(money_str, return_type=str, when_used="always")
]

#: The same, where absent and zero are different facts. `model_dump()` gives
#: `None`, not `"0.00"`.
OptionalMoneyField = Annotated[
    Optional[Decimal],
    PlainSerializer(money_or_none, return_type=Optional[str], when_used="always"),
]
