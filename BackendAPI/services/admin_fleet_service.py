"""Who is registered to deliver for whom.

`VendorRiderRegistry` decides dispatch priority: an approved in-house rider is
offered an order before the radar goes out to any nearby gig rider. No admin
screen showed these links, so a vendor saying "no riders are being assigned to
me" could not be checked — and the answer is usually visible in one number.

## The number that answers it

**Stores with no approved rider.** Every order they take falls straight through
to the gig radar, which is slower, costs the platform more commission, and fails
outright outside radar range. It is the single most useful figure here and
nothing computed it.

The second is **requests left waiting**. A rider asks a store to register them
and the store has to approve it; a store that never opens the app leaves riders
in `pending` for ever, and neither side has any way to see that the request is
simply sitting there.

## `Deliverer_Vendors` is dead

There are two tables for this relationship. `Deliverer_Vendors` is declared in
`models/deliverer_vendor_model.py` and created by migration `3ba669eb21f3`, and
**nothing reads or writes it** — no service, no route. `VendorRiderRegistry` is
the live one, and it is what dispatch, the rider app and the vendor app all use.

This module deliberately reports the dead table's row count rather than joining
it in. Silently using both would make the console the only place in the platform
where the two disagree, and the honest thing is to say the second table exists
and is empty.

## Data honesty

The registry has rows on this deployment, so the counts here are real. The
"waiting" thresholds are not tuned against anything — no store has yet been
observed leaving a request unanswered, so `STALE_REQUEST_DAYS` is an estimate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset

from models.deliverer_model import Deliverer, KYCStatus, RiderEmploymentType
from models.deliverer_vendor_model import DelivererVendor
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry

#: A registration request older than this is not being considered, it is being
#: ignored. The rider is waiting on a store that is not looking.
STALE_REQUEST_DAYS = 3


def _days_since(moment: datetime | None) -> int | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - moment).days)


async def summary(db: AsyncSession) -> dict[str, Any]:
    async def count(model, *where) -> int:
        query = select(func.count()).select_from(model)
        for clause in where:
            query = query.where(clause)
        return int((await db.execute(query)).scalar() or 0)

    approved = await count(VendorRiderRegistry, VendorRiderRegistry.status == "approved")
    pending = await count(VendorRiderRegistry, VendorRiderRegistry.status == "pending")

    vendors_total = await count(Vendor)
    vendors_with_rider = int(
        (
            await db.execute(
                select(func.count(func.distinct(VendorRiderRegistry.vendor_id))).where(
                    VendorRiderRegistry.status == "approved"
                )
            )
        ).scalar()
        or 0
    )

    riders_total = await count(Deliverer)
    riders_registered = int(
        (
            await db.execute(
                select(func.count(func.distinct(VendorRiderRegistry.rider_id))).where(
                    VendorRiderRegistry.status == "approved"
                )
            )
        ).scalar()
        or 0
    )

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_REQUEST_DAYS)
    stale = int(
        (
            await db.execute(
                select(func.count())
                .select_from(VendorRiderRegistry)
                .where(
                    VendorRiderRegistry.status == "pending",
                    VendorRiderRegistry.requested_at < stale_cutoff,
                )
            )
        ).scalar()
        or 0
    )

    in_house = await count(
        Deliverer, Deliverer.employment_model == RiderEmploymentType.in_house
    )

    return {
        "approved_links": approved,
        "pending_requests": pending,
        "stale_requests": stale,
        "stale_request_days": STALE_REQUEST_DAYS,
        "vendors_total": vendors_total,
        "vendors_with_rider": vendors_with_rider,
        # Every order these stores take falls through to the gig radar: slower,
        # more commission, and nothing at all outside radar range.
        "vendors_without_rider": vendors_total - vendors_with_rider,
        "riders_total": riders_total,
        "riders_registered": riders_registered,
        "riders_unattached": riders_total - riders_registered,
        "riders_in_house": in_house,
        # Reported, not used. See the module docstring: this table is declared,
        # migrated, and read by nothing.
        "legacy_table_rows": await count(DelivererVendor),
    }


async def vendors_without_riders(db: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    """Stores whose orders always go to the radar, worst first by how long."""
    linked = (
        select(VendorRiderRegistry.vendor_id)
        .where(VendorRiderRegistry.status == "approved")
        .distinct()
        .subquery()
    )

    rows = (
        await db.execute(
            select(Vendor.id, Vendor.business_name, Vendor.is_active, Vendor.created_at)
            .outerjoin(linked, linked.c.vendor_id == Vendor.id)
            .where(linked.c.vendor_id.is_(None))
            .order_by(Vendor.created_at.asc())
            .limit(limit)
        )
    ).all()

    return [
        {
            "id": str(vendor_id),
            "name": name,
            "active": bool(is_active),
            "days_trading": _days_since(created_at),
        }
        for vendor_id, name, is_active, created_at in rows
    ]


async def pending_requests(db: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    """Riders waiting on a store to say yes, oldest first."""
    rows = (
        await db.execute(
            select(
                VendorRiderRegistry,
                Deliverer.name,
                Deliverer.kyc_status,
                Vendor.business_name,
            )
            .outerjoin(Deliverer, Deliverer.id == VendorRiderRegistry.rider_id)
            .outerjoin(Vendor, Vendor.id == VendorRiderRegistry.vendor_id)
            .where(VendorRiderRegistry.status == "pending")
            .order_by(VendorRiderRegistry.requested_at.asc())
            .limit(limit)
        )
    ).all()

    return [
        {
            "rider_id": str(link.rider_id),
            "rider_name": rider_name,
            # A store cannot usefully approve somebody who is not allowed to
            # deliver yet, so the console shows the reason the request is moot.
            "rider_kyc": kyc.value if hasattr(kyc, "value") else kyc,
            "vendor_id": str(link.vendor_id),
            "vendor_name": vendor_name,
            "distance_km": round(link.distance_km, 1) if link.distance_km else None,
            "days_waiting": _days_since(link.requested_at),
            "stale": (_days_since(link.requested_at) or 0) >= STALE_REQUEST_DAYS,
        }
        for link, rider_name, kyc, vendor_name in rows
    ]


async def links(
    db: AsyncSession,
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Every rider/store registration, with what dispatch reads off it."""
    query = (
        select(
            VendorRiderRegistry,
            Deliverer.name,
            Deliverer.kyc_status,
            Deliverer.employment_model,
            Deliverer.suspended_at,
            Vendor.business_name,
        )
        .outerjoin(Deliverer, Deliverer.id == VendorRiderRegistry.rider_id)
        .outerjoin(Vendor, Vendor.id == VendorRiderRegistry.vendor_id)
    )
    if status:
        query = query.where(VendorRiderRegistry.status == status)

    # Either side of the pairing. This table is read to answer "who delivers for
    # this store" and "which stores has this rider signed up with", and both are
    # a name typed into a box.
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.where(
            or_(Deliverer.name.ilike(like), Vendor.business_name.ilike(like))
        )

    order = keyset.Order(VendorRiderRegistry.requested_at, VendorRiderRegistry.rider_id)
    result = await db.execute(keyset.seek(query, order, cursor).limit(limit + 1))
    rows, next_cursor = keyset.split(result.all(), limit, order)

    items = [
        {
            "rider_id": str(link.rider_id),
            "rider_name": rider_name,
            "rider_kyc": kyc.value if hasattr(kyc, "value") else kyc,
            "rider_suspended": suspended_at is not None,
            "employment": employment.value if hasattr(employment, "value") else employment,
            "vendor_id": str(link.vendor_id),
            "vendor_name": vendor_name,
            "status": link.status,
            "priority": link.priority,
            "distance_km": round(link.distance_km, 1) if link.distance_km else None,
            # The bottle counters live on this row; the ledger is the truth and
            # `/operations/bottles` is where a disagreement between them shows up.
            "pending_10L": link.pending_10L_empties or 0,
            "pending_20L": link.pending_20L_empties or 0,
            "requested_at": link.requested_at.isoformat() if link.requested_at else None,
            "approved_at": link.approved_at.isoformat() if link.approved_at else None,
        }
        for link, rider_name, kyc, employment, suspended_at, vendor_name in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


async def unattached_riders(db: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    """Riders registered with nobody.

    Not a problem for a gig rider — the radar is how they work. It *is* a problem
    for an `in_house` rider, who is meant to be somebody's own fleet and will
    never be given priority for anyone, so those are surfaced first.
    """
    linked = (
        select(VendorRiderRegistry.rider_id)
        .where(VendorRiderRegistry.status == "approved")
        .distinct()
        .subquery()
    )

    rows = (
        await db.execute(
            select(
                Deliverer.id,
                Deliverer.name,
                Deliverer.employment_model,
                Deliverer.kyc_status,
            )
            .outerjoin(linked, linked.c.rider_id == Deliverer.id)
            .where(linked.c.rider_id.is_(None))
            .order_by(
                (Deliverer.employment_model == RiderEmploymentType.in_house).desc(),
                Deliverer.created_at.desc(),
            )
            .limit(limit)
        )
    ).all()

    return [
        {
            "id": str(rider_id),
            "name": name,
            "employment": employment.value if hasattr(employment, "value") else employment,
            "kyc": kyc.value if hasattr(kyc, "value") else kyc,
            # An in-house rider with no store is a contradiction: they are
            # somebody's own fleet and belong to nobody.
            "misconfigured": employment == RiderEmploymentType.in_house,
            "can_work": kyc == KYCStatus.approved,
        }
        for rider_id, name, employment, kyc in rows
    ]
