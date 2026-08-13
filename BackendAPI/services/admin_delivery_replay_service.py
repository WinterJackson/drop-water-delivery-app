"""Replay one delivery from the rider's own breadcrumbs.

`Order_Tracking_Logs` is written on every location ping the rider app sends and
read by nothing. "The rider says they delivered it, the customer says they
didn't" was unanswerable — the platform held the evidence and had no way to look
at it.

## The one question this answers

**Did the rider get to the door?** `closest_approach_m` is the minimum distance
between any recorded ping and the order's delivery coordinates. A rider whose
nearest approach was 4 kilometres did not deliver that order, and no amount of
argument changes that number.

## "Don't know" is a different answer from "no"

`reached_destination` is `True`, `False`, **or `None`**, and the `None` is the
important one. It is returned when the order carries no delivery coordinates, or
when there are no pings at all — which happens routinely, because tracking
depends on the rider app having permission, signal and battery.

Collapsing that into `False` would be the worst bug this module could have: an
absence of evidence rendered as evidence of absence, on the screen somebody uses
to decide whether a rider is stealing. The console prints "no tracking data" and
refuses to draw a conclusion.

`largest_gap_minutes` exists for the same reason. A path with a 40-minute hole in
it is not a path; it is two paths, and whatever happened in between is not in
this data.

## Why the arithmetic is in Python

A few hundred points per order. Haversine over that is microseconds, and doing it
here rather than in PostGIS keeps the distance definition in one readable place
next to the threshold it is compared against.

## Data honesty

`Order_Tracking_Logs` is empty on this deployment — no delivery has been tracked
yet. The geometry below was exercised against synthetic paths with known
distances rather than real ones, and `PROXIMITY_M` in particular is a first
estimate: the right value depends on how accurate the rider handsets' GPS turns
out to be in dense parts of Nairobi, which nobody knows yet.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer
from models.order_model import Order
from models.order_tracking_log_model import OrderTrackingLog
from models.user_model import User
from models.vendor_model import Vendor
from utils import keyset

#: An order a human is arguing about. Named once — it was written out twice in
#: `tracked_orders` alone, in the filter and again in the row it serialises.
DISPUTED_STATUSES = ("pending_review", "mismatch_pending")

#: Within this of the delivery coordinates counts as "at the door". Consumer GPS
#: is good to 20–50 m in the open and considerably worse between buildings, so
#: this is a city block rather than a doorstep — deliberately, because a false
#: "never arrived" is an accusation.
PROXIMITY_M = 150

#: A silence longer than this is a hole in the record, not a stationary rider.
#: The app pings far more often than this while a delivery is live.
SIGNAL_GAP_MINUTES = 5

EARTH_RADIUS_M = 6_371_000


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def replay(db: AsyncSession, order_id: UUID) -> dict[str, Any] | None:
    """One delivery, its recorded path, and what that path does and does not show."""
    row = (
        await db.execute(
            select(Order, User.full_name, Deliverer.name, Vendor.business_name)
            .outerjoin(User, User.id == Order.customer_id)
            .outerjoin(Deliverer, Deliverer.id == Order.deliverer_id)
            .outerjoin(Vendor, Vendor.id == Order.vendor_id)
            .where(Order.id == order_id)
        )
    ).first()
    if row is None:
        return None

    order, customer_name, rider_name, vendor_name = row

    pings = (
        await db.execute(
            select(OrderTrackingLog)
            .where(OrderTrackingLog.order_id == order_id)
            .order_by(OrderTrackingLog.created_at.asc())
        )
    ).scalars().all()

    destination = (
        (float(order.lat), float(order.lng))
        if order.lat is not None and order.lng is not None
        else None
    )
    pickup = (
        (float(order.lat_from), float(order.lng_from))
        if order.lat_from is not None and order.lng_from is not None
        else None
    )

    path: list[dict[str, Any]] = []
    travelled = 0.0
    closest: float | None = None
    at_destination = 0
    largest_gap = 0.0
    previous = None

    for ping in pings:
        moment = _aware(ping.created_at)
        to_destination = (
            round(_distance_m(ping.lat, ping.lng, destination[0], destination[1]))
            if destination
            else None
        )
        if to_destination is not None:
            closest = to_destination if closest is None else min(closest, to_destination)
            if to_destination <= PROXIMITY_M:
                at_destination += 1

        if previous is not None:
            travelled += _distance_m(previous.lat, previous.lng, ping.lat, ping.lng)
            previous_moment = _aware(previous.created_at)
            if previous_moment and moment:
                gap = (moment - previous_moment).total_seconds() / 60
                largest_gap = max(largest_gap, gap)

        path.append(
            {
                "lat": ping.lat,
                "lng": ping.lng,
                "heading": ping.heading,
                "speed": ping.speed,
                "at": moment.isoformat() if moment else None,
                "metres_to_destination": to_destination,
            }
        )
        previous = ping

    first = _aware(pings[0].created_at) if pings else None
    last = _aware(pings[-1].created_at) if pings else None
    tracked_minutes = (
        round((last - first).total_seconds() / 60, 1) if first and last else None
    )

    # The three-valued answer. `None` is not a failure to compute — it is the
    # honest result when the data cannot speak to the question, and the console
    # renders it as "no tracking data" rather than as "never arrived".
    if destination is None or not pings:
        reached: bool | None = None
    else:
        reached = closest is not None and closest <= PROXIMITY_M

    return {
        "order": {
            "id": str(order.id),
            "status": order.order_status,
            "payment_status": order.payment_status,
            "delivery_type": order.delivery_type,
            "delivery_address": order.delivery_address,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "customer": customer_name,
            "rider": rider_name,
            "rider_id": str(order.deliverer_id) if order.deliverer_id else None,
            "vendor": vendor_name,
            "vendor_id": str(order.vendor_id) if order.vendor_id else None,
            # Whether proof exists, not the URL: presigning an image of somebody's
            # doorstep on every page load is the same mistake as prefetching KYC
            # documents. The order detail screen reveals it deliberately.
            "has_proof": bool(order.proof_url),
            "destination": {"lat": destination[0], "lng": destination[1]} if destination else None,
            "pickup": {"lat": pickup[0], "lng": pickup[1]} if pickup else None,
        },
        "path": path,
        "findings": {
            "points": len(path),
            "first_ping": first.isoformat() if first else None,
            "last_ping": last.isoformat() if last else None,
            "tracked_minutes": tracked_minutes,
            "distance_travelled_km": round(travelled / 1000, 2) if path else None,
            "closest_approach_m": closest,
            "proximity_m": PROXIMITY_M,
            "reached_destination": reached,
            "pings_at_destination": at_destination,
            "largest_gap_minutes": round(largest_gap, 1) if path else None,
            "signal_gap_minutes": SIGNAL_GAP_MINUTES,
            "has_gap": largest_gap >= SIGNAL_GAP_MINUTES,
            # Says plainly why there is no verdict, so the screen never has to
            # guess which kind of nothing it is looking at.
            "no_verdict_because": None
            if reached is not None
            else ("the order has no delivery coordinates" if destination is None
                  else "no location was ever recorded for this delivery"),
        },
    }


async def tracked_orders(
    db: AsyncSession, *, limit: int = 50, cursor: str | None = None, search: str | None = None
) -> dict[str, Any]:
    """Orders worth replaying: the contested ones first, then anything tracked.

    A list of every order with a breadcrumb is not useful — the screen exists for
    an argument, so it opens on the orders that are in one.
    """
    counts = (
        select(
            OrderTrackingLog.order_id.label("order_id"),
            func.count().label("points"),
        )
        .group_by(OrderTrackingLog.order_id)
        .subquery()
    )

    # The rank column is *selected*, not merely ordered by, so the cursor can
    # carry it. A page boundary in a ranked list has to encode the rank as well
    # as the timestamp, or paging past the last disputed order lands back in the
    # middle of them.
    disputed = Order.order_status.in_(DISPUTED_STATUSES).label("disputed")

    query = (
            select(
                Order,
                Deliverer.name,
                User.full_name,
                func.coalesce(counts.c.points, 0).label("points"),
                disputed,
            )
            .outerjoin(counts, counts.c.order_id == Order.id)
            .outerjoin(Deliverer, Deliverer.id == Order.deliverer_id)
            .outerjoin(User, User.id == Order.customer_id)
            .where(
                or_(
                    counts.c.points.isnot(None),
                    Order.order_status.in_(DISPUTED_STATUSES),
                )
            )
    )

    if search and search.strip():
        term = search.strip()
        clauses = [
            Order.delivery_address.ilike(f"%{term}%"),
            Deliverer.name.ilike(f"%{term}%"),
            User.full_name.ilike(f"%{term}%"),
        ]
        try:
            clauses.append(Order.id == UUID(term))
        except ValueError:
            pass
        query = query.where(or_(*clauses))

    # Disputed first — that is what somebody came here to settle.
    ranking = keyset.Order(disputed, Order.created_at, Order.id)
    rows, next_cursor = keyset.split(
        (await db.execute(keyset.seek(query, ranking, cursor).limit(limit + 1))).all(),
        limit,
        ranking,
    )

    items = [
        {
            "id": str(order.id),
            "status": order.order_status,
            "delivery_address": order.delivery_address,
            "rider": rider_name,
            "customer": customer_name,
            "points": int(points or 0),
            "disputed": bool(is_disputed),
            "has_proof": bool(order.proof_url),
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order, rider_name, customer_name, points, is_disputed in rows
    ]
    return {"items": items, "next_cursor": next_cursor}
