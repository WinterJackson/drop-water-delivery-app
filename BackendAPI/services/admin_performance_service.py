"""Rider and vendor performance, so a suspension is evidence rather than a hunch.

Deactivating somebody's income is the most consequential thing this console
does to an individual, and until now it was done from a roster showing a name
and a phone number. This module is what the decision should rest on.

## Why every rate carries its denominator

A rider with one delivery and one cancellation has a 100% cancellation rate and
tells you nothing. Every figure here ships `orders` alongside it, and the console
refuses to rank anyone below `MIN_ORDERS_FOR_RANKING`. A league table that puts a
one-order rider at the top is worse than no league table: it is confidently
wrong, and somebody acts on it.

## Why "delivered" is not the only outcome that matters

`cancelled` counts against whoever the order was assigned to at the time, which
is deliberately imperfect — an order cancelled by the customer before the rider
moved is not the rider's fault. The figure is a starting point for a
conversation, not a verdict, and the console says so on the page rather than
implying a precision the data does not have.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset

from models.order_model import Order
from models.vendor_model import Vendor
from models.deliverer_model import Deliverer

#: Below this, a rate is noise. One delivery and one cancellation is 100%.
MIN_ORDERS_FOR_RANKING = 5

TERMINAL_DELIVERED = "delivered"
TERMINAL_CANCELLED = "cancelled"


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def _matching(items: list[dict], search: str | None) -> list[dict]:
    """Narrow a already-counted board to the rows whose name matches.

    Deliberately **not** a `WHERE` on the aggregate. Putting it there is what
    made the summary describe the search rather than the platform — the counts
    are taken off `items` before this runs, and this cannot reach back and
    change them.
    """
    if not search or not search.strip():
        return items
    needle = search.strip().casefold()
    return [item for item in items if needle in (item["name"] or "").casefold()]


def _rate(part: int, whole: int) -> int | None:
    return round((part / whole) * 100) if whole else None


async def riders(
    db: AsyncSession, *, limit: int = 100, cursor: str | None = None, search: str | None = None
) -> dict[str, Any]:
    """Per-rider throughput and reliability, from the orders assigned to them.

    The aggregate runs over **every** rider, unfiltered, and the summary counts
    come off that. Only then is the search applied and a page sliced.

    The order matters, and getting it wrong is subtle twice over. Counting off
    the *page* reported a fleet of one hundred on a platform with four hundred
    riders. Counting off the *search* is the same defect with a different
    trigger — typing a name would turn "Riders 35" into "Riders 2", which reads
    as the fleet having shrunk rather than as the list having narrowed. So
    `total` is the population and `matched` is the size of the result set; the
    console shows the first beside the board and the second in the pager.
    """
    delivered = func.count(
        case((Order.order_status == TERMINAL_DELIVERED, Order.id))
    ).label("delivered")
    cancelled = func.count(
        case((Order.order_status == TERMINAL_CANCELLED, Order.id))
    ).label("cancelled")

    rows = (
        await db.execute(
            select(
                Deliverer.id,
                Deliverer.name,
                Deliverer.kyc_status,
                Deliverer.suspended_at,
                func.count(Order.id).label("orders"),
                delivered,
                cancelled,
                func.coalesce(
                    func.sum(
                        case((Order.order_status == TERMINAL_DELIVERED, Order.total_amount))
                    ),
                    0,
                ).label("gmv"),
            )
            .outerjoin(Order, Order.deliverer_id == Deliverer.id)
            .group_by(Deliverer.id, Deliverer.name, Deliverer.kyc_status, Deliverer.suspended_at)
            .order_by(func.count(Order.id).desc(), Deliverer.id.desc())
        )
    ).all()

    items = []
    for rid, name, kyc, suspended_at, orders, done, cancels, gmv in rows:
        finished = int(done or 0) + int(cancels or 0)
        items.append(
            {
                "id": str(rid),
                "name": name,
                "kyc_status": kyc.value if hasattr(kyc, "value") else kyc,
                "suspended": suspended_at is not None,
                "orders": int(orders or 0),
                "delivered": int(done or 0),
                "cancelled": int(cancels or 0),
                # None until there is enough to say anything. The console shows
                # "not enough data" rather than a number it would have to caveat.
                "completion_rate": _rate(int(done or 0), finished)
                if finished >= MIN_ORDERS_FOR_RANKING
                else None,
                "gmv": _money(gmv),
                "ranked": finished >= MIN_ORDERS_FOR_RANKING,
            }
        )

    # Every count below is taken here, off the unfiltered population.
    summary = {
        "total": len(items),
        "ranked_count": sum(1 for item in items if item["ranked"]),
        "approved": sum(1 for item in items if item["kyc_status"] == "approved"),
        "with_any_order": sum(1 for item in items if item["orders"] > 0),
    }

    page = keyset.page_list(_matching(items, search), limit=limit, cursor=cursor)
    return {
        **page,
        **summary,
        "min_orders_for_ranking": MIN_ORDERS_FOR_RANKING,
        # `page_list` counts what it was given, which is the filtered set.
        "matched": page["total"],
        "total": summary["total"],
    }


async def vendors(
    db: AsyncSession, *, limit: int = 100, cursor: str | None = None, search: str | None = None
) -> dict[str, Any]:
    """Per-store volume and fulfilment. Counted whole, then filtered, then
    paged — see `riders` for why that order is the whole point."""
    delivered = func.count(
        case((Order.order_status == TERMINAL_DELIVERED, Order.id))
    ).label("delivered")
    cancelled = func.count(
        case((Order.order_status == TERMINAL_CANCELLED, Order.id))
    ).label("cancelled")

    rows = (
        await db.execute(
            select(
                Vendor.id,
                Vendor.business_name,
                Vendor.verification_status,
                Vendor.is_active,
                func.count(Order.id).label("orders"),
                delivered,
                cancelled,
                func.coalesce(
                    func.sum(
                        case((Order.order_status == TERMINAL_DELIVERED, Order.total_amount))
                    ),
                    0,
                ).label("gmv"),
            )
            .outerjoin(Order, Order.vendor_id == Vendor.id)
            .group_by(Vendor.id, Vendor.business_name, Vendor.verification_status, Vendor.is_active)
            .order_by(func.count(Order.id).desc(), Vendor.id.desc())
        )
    ).all()

    items = []
    for vid, name, verification, is_active, orders, done, cancels, gmv in rows:
        finished = int(done or 0) + int(cancels or 0)
        items.append(
            {
                "id": str(vid),
                "name": name,
                "verification_status": verification,
                "active": bool(is_active),
                "orders": int(orders or 0),
                "delivered": int(done or 0),
                "cancelled": int(cancels or 0),
                "fulfilment_rate": _rate(int(done or 0), finished)
                if finished >= MIN_ORDERS_FOR_RANKING
                else None,
                "gmv": _money(gmv),
                "ranked": finished >= MIN_ORDERS_FOR_RANKING,
            }
        )

    summary = {
        "total": len(items),
        "ranked_count": sum(1 for item in items if item["ranked"]),
        "selling": sum(1 for item in items if item["orders"] > 0),
        # Stores that have never taken an order. On a young platform this is the
        # single most useful vendor figure: supply acquired and not activated.
        "never_sold": sum(1 for item in items if item["orders"] == 0),
    }

    page = keyset.page_list(_matching(items, search), limit=limit, cursor=cursor)
    return {
        **page,
        **summary,
        "min_orders_for_ranking": MIN_ORDERS_FOR_RANKING,
        "matched": page["total"],
        "total": summary["total"],
    }
