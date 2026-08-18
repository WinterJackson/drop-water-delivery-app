"""Where the platform measures a customer's service radius from.

Discovery on Drop is bounded by what can actually be delivered — 2.5 km for a
refill shop, 15 km for a depot — and every bound needs an origin. This module is
the one place that decides what that origin is and what happens when there
isn't one.

**The rule: no delivery point, no discovery.**

That rule is the second half of the radius work, and it exists because the two
halves of the app had answered the question differently. With no address on the
account:

* the four vendor endpoints returned `[]`;
* the three product listings returned the **entire national catalogue**,
  because the radius clause was written as "apply the bound when coordinates are
  known" and unknown coordinates therefore meant no bound at all;
* search did the same.

So a customer with no address saw a home screen that said *"No vendors currently
deliver to your location"* directly above a grid of products from stores 400 km
away — each one tappable, addable to a basket, and refused at checkout by
`validate_cart_preflight` once the basket was full. Every screen was internally
consistent and the app as a whole told the customer two opposite things.

Serving nothing is the honest answer, and it is only a good answer because the
app now asks for the missing thing rather than rendering an empty shelf: an
unknown location is a *question*, not a result, and `LocationRequired` on the
home screen is where it gets asked. That is why this rule and that component
shipped together — either alone is worse than what it replaced.

**The origin is the saved delivery address, and never a query parameter.**

Search took `user_lat`/`user_lng` from the client — the handset's live GPS fix —
while every other read, and `validate_cart_preflight` at checkout, measured from
the address on the account. The two are routinely different places: water is
delivered to a house, and the customer searching for it is at work. So the
screen listed the shops that could reach *the phone*, the basket was refused by
the shops that could reach *the home*, and the message named a distance the
customer could not see the origin of.

Preferring the live fix was a defensible-sounding idea — somebody out on the
street is better served from where they are standing — and it is wrong here,
because the delivery does not follow the handset. A customer who has genuinely
moved changes their address, which is one tap and is the thing that has to
change anyway before an order can arrive.

It also closes a smaller hole: a client-supplied origin is a client-supplied
answer, and the radius is the rule that decides whether a store may be ordered
from at all.
"""

from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from services.user_service import get_user_coordinates


class DeliveryPoint(NamedTuple):
    """A resolved origin. Both halves are always present — see `resolve`."""

    lat: float
    lng: float


async def resolve(session: AsyncSession, clerk_id: str) -> DeliveryPoint | None:
    """The origin to measure this caller's service radius from, or `None`.

    Both halves must be present to be usable. A latitude with no longitude is
    not half a location, and letting one through would leave the radius
    unapplied — which is indistinguishable, on the wire, from the unbounded
    behaviour this module exists to remove.

    `lat` and `lng` are compared against `None` rather than tested for
    truthiness. Four vendor endpoints guarded with `if not coords.lat`, and
    latitude 0 is the equator — which Kenya straddles, about 200 km from
    Nairobi.
    """
    coords = await get_user_coordinates(session=session, clerk_id=clerk_id)
    if coords and coords.lat is not None and coords.lng is not None:
        return DeliveryPoint(coords.lat, coords.lng)

    return None
