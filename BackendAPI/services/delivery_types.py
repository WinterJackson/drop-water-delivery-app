"""What the customer is actually asking for when they order water.

There are three distinct transactions here, and the platform used to have names
for two of them — one of which described neither.

| Type | The bottle | Deposit | Journey |
|---|---|---|---|
| `exchange` | A pool bottle, for the pool bottle they hand back | none | one way |
| `refill_mine` | **Theirs**, collected, refilled, returned | none | **round trip** |
| `new_bottle` | The platform's, and they keep it | **charged** | one way |

## Why this needed fixing

`keep_my_bottle` meant "you are keeping the bottle we brought, so pay a KSH 300
deposit". The option it was *presented* as — and the reason it exists as a
product — is hygiene: a household that does not want to drink from a bottle that
was in a stranger's kitchen last week, and wants their own one refilled and
returned.

Those are opposite transactions. The customer choosing the hygiene option owns
their bottle and takes nothing from the platform, and was charged a KSH 300
deposit for it. They paid a deposit on their own property.

`exchange` is the ordinary case and the default. `refill_mine` is the premium
one — the rider rides to the customer, to the station, and back, so it costs
more and is deliberately excluded from the short-hop flat fee: distance is
exactly what that journey costs. `new_bottle` is how somebody with no bottle at
all starts, and is the only path that takes a deposit.

## Migrating the old names

`quick_swap` → `exchange` is a rename.

`keep_my_bottle` → **`new_bottle`**, not `refill_mine`. Every historic
`keep_my_bottle` order charged a deposit and left a platform bottle with the
customer, which is what `new_bottle` means. Mapping them to `refill_mine` would
say those customers own bottles they do not, and would strand the deposit
liability the platform still owes them.

Legacy names are accepted on the wire indefinitely — an app in somebody's pocket
does not update because the backend did.
"""
from __future__ import annotations

#: A pool bottle for a pool bottle. The default, and most of the market.
EXCHANGE = "exchange"

#: The customer's own bottle, collected, refilled and returned. Round trip.
REFILL_MINE = "refill_mine"

#: A platform bottle the customer keeps. The only type that takes a deposit.
NEW_BOTTLE = "new_bottle"

ALL: tuple[str, ...] = (EXCHANGE, REFILL_MINE, NEW_BOTTLE)

#: What the old names meant, not what they sounded like. See the module
#: docstring — `keep_my_bottle` mapping to `new_bottle` is the load-bearing one.
LEGACY_ALIASES: dict[str, str] = {
    "quick_swap": EXCHANGE,
    "keep_my_bottle": NEW_BOTTLE,
}

#: Shown to the customer. Stated so the money is visible in the choice itself,
#: rather than in a footnote under it.
LABELS: dict[str, str] = {
    EXCHANGE: "Exchange my empty bottle",
    REFILL_MINE: "Refill my own bottle",
    NEW_BOTTLE: "I need a bottle",
}


def normalise(delivery_type: str | None) -> str:
    """The canonical type for anything a client might send.

    Unknown values fall back to `EXCHANGE` rather than raising: this is on the
    quote path, and refusing to price a cart because an old build sent a name we
    retired is a worse failure than pricing the ordinary case.
    """
    if not delivery_type:
        return EXCHANGE
    value = str(delivery_type).strip().lower()
    if value in ALL:
        return value
    return LEGACY_ALIASES.get(value, EXCHANGE)


def takes_deposit(delivery_type: str | None) -> bool:
    """Whether this order leaves a platform bottle with the customer.

    The **only** thing that should decide a deposit. It used to be
    `delivery_type == "keep_my_bottle" or is_first_order`, and the second half
    was doing the work of `new_bottle` before it existed — which is why a
    first-time customer exchanging a bottle they already owned was charged one.
    """
    return normalise(delivery_type) == NEW_BOTTLE


def is_round_trip(delivery_type: str | None) -> bool:
    """Whether the rider makes the journey more than once.

    Excludes the type from the short-hop flat fee: a 400 m round trip is still
    three legs of riding, and pricing it as one is how a rider learns to decline
    a whole category of order.
    """
    return normalise(delivery_type) == REFILL_MINE
