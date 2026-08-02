"""Where everything is.

A delivery platform is a geography problem wearing a database. "Why did that
order take 50 minutes" and "why is there no rider in Kilimani" are the same
question asked from two ends, and neither can be answered from a table.

Three rules shape this module:

* **Coordinates are personal data.** A customer's home is their address. So
  customer positions are only ever returned *aggregated into H3 cells* — never
  as points — and even that is behind `geo.view`. Riders and vendors are
  returned as points because a rider's position during a shift is operational
  and a store's position is public in the customer app anyway.
* **Bounded by the viewport, always.** Every query takes a bounding box and a
  limit. An unbounded "select every rider" is a table scan that returns a blob
  no map can draw, and it gets slower exactly as the platform succeeds.
* **PostGIS does the work.** `ST_MakeEnvelope` against the existing GiST indexes
  on `Deliverers.location` and `Vendors.location`, rather than fetching
  everything and filtering in Python.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer, KYCStatus
from models.order_model import Order
from models.user_model import User
from models.vendor_model import Vendor

logger = logging.getLogger(__name__)

#: Nairobi, where the platform operates. Used when nothing has a position yet,
#: so the map opens somewhere meaningful instead of at 0°N 0°E in the Atlantic.
DEFAULT_CENTRE = {"lat": -1.2864, "lng": 36.8172}

#: Hard ceiling per layer. A map cannot usefully draw more, and the browser
#: should not be asked to.
MAX_POINTS = 2000


@dataclass(frozen=True)
class Viewport:
    """The visible rectangle. `None` means "everywhere", used for the first load."""

    min_lat: Optional[float] = None
    min_lng: Optional[float] = None
    max_lat: Optional[float] = None
    max_lng: Optional[float] = None

    @property
    def bounded(self) -> bool:
        return None not in (self.min_lat, self.min_lng, self.max_lat, self.max_lng)


def _within(column, viewport: Viewport):
    """A PostGIS envelope predicate, or nothing when the viewport is open.

    4326 explicitly: the columns are `Geography(POINT, 4326)` and an envelope
    built without an SRID compares as a bare geometry, which silently matches
    nothing.
    """
    if not viewport.bounded:
        return None
    return func.ST_Intersects(
        column,
        func.ST_MakeEnvelope(
            viewport.min_lng, viewport.min_lat, viewport.max_lng, viewport.max_lat, 4326
        ),
    )


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


async def rider_positions(
    session: AsyncSession,
    *,
    viewport: Viewport,
    only_deployable: bool = False,
    limit: int = MAX_POINTS,
) -> dict:
    """Every rider with a known position, and whether they can actually work.

    `deployable` is the field that matters operationally and the one people get
    wrong: `is_available` defaults to true at sign-up, so a map coloured by it
    shows a healthy-looking fleet on a platform where nobody has passed KYC.
    """
    query = (
        select(
            Deliverer.id,
            Deliverer.name,
            func.ST_Y(cast(Deliverer.location, Geometry)).label("lat"),
            func.ST_X(cast(Deliverer.location, Geometry)).label("lng"),
            Deliverer.is_available,
            Deliverer.kyc_status,
            Deliverer.suspended_at,
            Deliverer.vehicle_type,
            Deliverer.rating,
            Deliverer.updated_at,
        )
        .where(Deliverer.location.isnot(None))
        .limit(limit)
    )

    envelope = _within(Deliverer.location, viewport)
    if envelope is not None:
        query = query.where(envelope)

    if only_deployable:
        query = query.where(
            Deliverer.is_available.is_(True),
            Deliverer.kyc_status == KYCStatus.approved,
            Deliverer.suspended_at.is_(None),
        )

    rows = (await session.execute(query)).all()

    return {
        "points": [
            {
                "id": str(row.id),
                "name": row.name,
                "lat": float(row.lat),
                "lng": float(row.lng),
                "vehicle": row.vehicle_type,
                "rating": float(row.rating) if row.rating is not None else None,
                "kyc_status": getattr(row.kyc_status, "value", row.kyc_status),
                "suspended": row.suspended_at is not None,
                "marked_available": bool(row.is_available),
                # The only honest reading of "can this person take a job".
                "deployable": bool(
                    row.is_available
                    and getattr(row.kyc_status, "value", row.kyc_status) == "approved"
                    and row.suspended_at is None
                ),
                "last_seen": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
        "truncated": len(rows) >= limit,
    }


async def vendor_positions(
    session: AsyncSession, *, viewport: Viewport, limit: int = MAX_POINTS
) -> dict:
    """Every store, with the state that decides whether it can trade."""
    query = (
        select(
            Vendor.id,
            Vendor.business_name,
            func.ST_Y(cast(Vendor.location, Geometry)).label("lat"),
            func.ST_X(cast(Vendor.location, Geometry)).label("lng"),
            Vendor.vendor_type,
            Vendor.verification_status,
            Vendor.is_online,
            Vendor.is_active,
            Vendor.suspended_at,
            Vendor.rating,
        )
        .where(Vendor.location.isnot(None))
        .limit(limit)
    )

    envelope = _within(Vendor.location, viewport)
    if envelope is not None:
        query = query.where(envelope)

    rows = (await session.execute(query)).all()

    return {
        "points": [
            {
                "id": str(row.id),
                "name": row.business_name,
                "lat": float(row.lat),
                "lng": float(row.lng),
                "vendor_type": row.vendor_type,
                "verification_status": row.verification_status,
                "online": bool(row.is_online),
                "suspended": row.suspended_at is not None or not row.is_active,
                "rating": float(row.rating) if row.rating is not None else None,
            }
            for row in rows
        ],
        "truncated": len(rows) >= limit,
    }


async def demand_cells(
    session: AsyncSession, *, days: int = 30, limit: int = 500
) -> dict:
    """Where the orders come from, as H3 cells rather than addresses.

    This is the customer layer, and it is aggregated on purpose. Plotting every
    delivery as a point would put a pin on every customer's home in a console
    that several people can open — an operational need ("where is demand") does
    not require the ability to read off individual addresses.

    Cells with a single order are dropped for the same reason: a lone point in a
    res-8 cell is roughly somebody's building.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await session.execute(
            select(
                Order.h3_index_res8,
                func.count(Order.id).label("orders"),
                func.coalesce(func.sum(Order.total_amount), 0).label("gmv"),
                func.avg(Order.distance_km.cast(Float)).label("avg_distance"),
                # `delivery_time` is the recorded duration in minutes, the same
                # column `operations_health` averages. There is no delivered-at
                # timestamp to subtract from.
                func.avg(func.cast(Order.delivery_time, Float)).label("avg_minutes"),
            )
            .where(
                Order.h3_index_res8.isnot(None),
                Order.created_at >= since,
                Order.payment_status == "paid",
            )
            .group_by(Order.h3_index_res8)
            .having(func.count(Order.id) > 1)
            .order_by(func.count(Order.id).desc())
            .limit(limit)
        )
    ).all()

    return {
        "cells": [
            {
                "h3": row.h3_index_res8,
                "orders": int(row.orders),
                "gmv": _money(row.gmv),
                "avg_distance_km": round(float(row.avg_distance or 0), 2),
                "avg_minutes": round(float(row.avg_minutes or 0), 1),
            }
            for row in rows
        ],
        "window_days": days,
        "suppressed_note": (
            "Cells with a single order are omitted — one delivery in a 460m cell "
            "identifies a household."
        ),
    }


async def live_orders(
    session: AsyncSession, *, viewport: Viewport, limit: int = 500
) -> dict:
    """Orders currently in flight, positioned at their **vendor**.

    The vendor is the right anchor: it is where the order physically is until
    pickup, it is not personal data, and it is the position an operator needs
    when deciding which store is backing up.
    """
    active = ("pending", "accepted", "preparing", "ready", "picked_up",
              "mismatch_pending", "pending_review")

    query = (
        select(
            Order.id,
            Order.order_status,
            Order.created_at,
            Order.total_amount,
            Vendor.business_name,
            func.ST_Y(cast(Vendor.location, Geometry)).label("lat"),
            func.ST_X(cast(Vendor.location, Geometry)).label("lng"),
            Deliverer.name.label("rider_name"),
        )
        .join(Vendor, Order.vendor_id == Vendor.id)
        .outerjoin(Deliverer, Order.deliverer_id == Deliverer.id)
        .where(Order.order_status.in_(active), Vendor.location.isnot(None))
        .order_by(Order.created_at.asc())
        .limit(limit)
    )

    envelope = _within(Vendor.location, viewport)
    if envelope is not None:
        query = query.where(envelope)

    rows = (await session.execute(query)).all()
    now = datetime.now(timezone.utc)

    return {
        "points": [
            {
                "id": str(row.id),
                "status": row.order_status,
                "vendor": row.business_name,
                "rider": row.rider_name,
                "lat": float(row.lat),
                "lng": float(row.lng),
                "total": _money(row.total_amount),
                "waiting_minutes": (
                    int((now - row.created_at).total_seconds() // 60)
                    if row.created_at
                    else None
                ),
            }
            for row in rows
        ],
        "truncated": len(rows) >= limit,
    }


async def coverage_report(session: AsyncSession) -> dict:
    """Where the platform can actually serve, and where it cannot.

    The useful question is not "how many riders" but "how many *areas with
    demand* have no deployable rider near them" — a fleet of forty riders all
    parked in one suburb is a coverage failure that every headline number hides.
    """
    total_vendors = int(
        (await session.execute(select(func.count(Vendor.id)))).scalar() or 0
    )
    located_vendors = int(
        (
            await session.execute(
                select(func.count(Vendor.id)).where(Vendor.location.isnot(None))
            )
        ).scalar()
        or 0
    )
    total_riders = int(
        (await session.execute(select(func.count(Deliverer.id)))).scalar() or 0
    )
    located_riders = int(
        (
            await session.execute(
                select(func.count(Deliverer.id)).where(Deliverer.location.isnot(None))
            )
        ).scalar()
        or 0
    )
    deployable_located = int(
        (
            await session.execute(
                select(func.count(Deliverer.id)).where(
                    Deliverer.location.isnot(None),
                    Deliverer.is_available.is_(True),
                    Deliverer.kyc_status == KYCStatus.approved,
                    Deliverer.suspended_at.is_(None),
                )
            )
        ).scalar()
        or 0
    )
    located_customers = int(
        (
            await session.execute(
                select(func.count(User.id)).where(User.location.isnot(None))
            )
        ).scalar()
        or 0
    )

    # Store cells with no deployable rider within the retail radius. This is the
    # single most actionable number on the map: each one is a store taking
    # orders nobody can deliver.
    from services.dispatch_policy import DispatchPolicy

    radius_m = DispatchPolicy.retail_max_distance_km() * 1000.0

    uncovered = (
        await session.execute(
            select(Vendor.id, Vendor.business_name)
            .where(
                Vendor.location.isnot(None),
                Vendor.is_active.is_(True),
                ~select(Deliverer.id)
                .where(
                    Deliverer.location.isnot(None),
                    Deliverer.is_available.is_(True),
                    Deliverer.kyc_status == KYCStatus.approved,
                    Deliverer.suspended_at.is_(None),
                    func.ST_DWithin(Deliverer.location, Vendor.location, radius_m),
                )
                .exists(),
            )
            .limit(200)
        )
    ).all()

    return {
        "vendors": {
            "total": total_vendors,
            "located": located_vendors,
            "missing_location": total_vendors - located_vendors,
        },
        "riders": {
            "total": total_riders,
            "located": located_riders,
            "missing_location": total_riders - located_riders,
            "deployable_located": deployable_located,
        },
        "customers": {"located": located_customers},
        "uncovered_vendors": {
            "count": len(uncovered),
            "radius_km": DispatchPolicy.retail_max_distance_km(),
            "items": [
                {"id": str(row.id), "name": row.business_name} for row in uncovered[:50]
            ],
        },
    }


async def map_centre(session: AsyncSession) -> dict:
    """Where to open the map.

    The centroid of the stores, because that is where the business is. Falls
    back to Nairobi rather than to (0, 0) — a map that opens in the Gulf of
    Guinea reads as broken software on day one, when nothing has a position yet.
    """
    row = (
        await session.execute(
            select(
                func.avg(func.ST_Y(cast(Vendor.location, Geometry))),
                func.avg(func.ST_X(cast(Vendor.location, Geometry))),
                func.count(Vendor.id),
            ).where(Vendor.location.isnot(None))
        )
    ).one()

    if not row[2] or row[0] is None:
        return {**DEFAULT_CENTRE, "zoom": 11, "derived": False}

    return {"lat": float(row[0]), "lng": float(row[1]), "zoom": 12, "derived": True}
