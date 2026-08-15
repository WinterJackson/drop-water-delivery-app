"""
Empty-bottle debt between riders and vendors.

On a `quick_swap` order the rider hands the customer full bottles and takes their
empties. Those empties belong to the vendor, so from the moment the delivery
completes the rider is holding vendor property. This module is the accounting for
that: accrual on delivery, settlement when the vendor physically receives them, and
the balances both sides read.

Invariant this module maintains
-------------------------------
For every (rider, vendor, capacity):

    SUM(bottle_ledger_entries.quantity) == VendorRiderRegistry.pending_{n}L_empties

The ledger is the evidence; the counter is the index. Never write one without the
other — `_apply_movement` is the only place either is touched.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.bottle_ledger_model import BottleLedgerEntry, BottleLedgerEntryType
from models.vendor_rider_model import VendorRiderRegistry
from typing import Iterable
from utils.paging import stable

logger = logging.getLogger(__name__)

#: Capacities the registry keeps a counter column for. A product of any other size
#: still gets a ledger row — the audit trail must be complete — but has no counter.
TRACKED_CAPACITIES = (10, 20)

_COUNTER_COLUMN = {10: "pending_10L_empties", 20: "pending_20L_empties"}


async def _locked_registry(
    session: AsyncSession, rider_id: UUID, vendor_id: UUID
) -> VendorRiderRegistry | None:
    """
    The registry row for this pair, locked FOR UPDATE.

    Settlement is read-modify-write on a counter. Without the lock, a vendor
    confirming receipt on two devices — or one retrying — interleaves and loses a
    decrement, quietly forgiving debt.
    """
    result = await session.execute(
        select(VendorRiderRegistry)
        .where(
            and_(
                VendorRiderRegistry.rider_id == rider_id,
                VendorRiderRegistry.vendor_id == vendor_id,
            )
        )
        .with_for_update()
    )
    return result.scalars().first()


def _bump_counter(registry: VendorRiderRegistry, capacity: int, delta: int) -> None:
    column = _COUNTER_COLUMN.get(capacity)
    if not column:
        return
    current = getattr(registry, column) or 0
    # Clamp at zero: the ledger keeps the true signed history, but a negative
    # "owed" counter would render as nonsense in both apps.
    setattr(registry, column, max(0, current + delta))


async def _apply_movement(
    session: AsyncSession,
    *,
    rider_id: UUID,
    vendor_id: UUID,
    capacity: int,
    quantity: int,
    entry_type: BottleLedgerEntryType,
    registry: VendorRiderRegistry | None,
    order_id: UUID | None = None,
    actor_clerk_id: str | None = None,
    note: str | None = None,
) -> BottleLedgerEntry | None:
    """Write one ledger row and move the matching counter. Never call one alone."""
    if quantity == 0:
        return None

    entry = BottleLedgerEntry(
        rider_id=rider_id,
        vendor_id=vendor_id,
        order_id=order_id,
        capacity_litres=capacity,
        quantity=quantity,
        entry_type=entry_type,
        actor_clerk_id=actor_clerk_id,
        note=note,
    )
    session.add(entry)

    if registry is not None:
        _bump_counter(registry, capacity, quantity)

    return entry


async def accrue_delivery_empties(
    session: AsyncSession,
    *,
    rider_id: UUID,
    vendor_id: UUID,
    order_id: UUID,
    quantities_by_capacity: dict[int, int],
    actor_clerk_id: str | None = None,
) -> list[BottleLedgerEntry]:
    """
    Record that a rider now holds the vendor's empties from a completed delivery.

    Two behaviours that the previous inline implementation got wrong:

    * **No registry row is required.** Tier-2 radar dispatch offers orders to any
      nearby gig rider, so a rider can legitimately deliver for a vendor they have
      never registered with. The old code skipped the accrual entirely when the
      registry lookup came back empty, so those bottles left with no record and the
      rider never appeared on the vendor's reconciliation screen. The ledger row is
      always written; the counter is updated only if there is a row to hold it.

    * **Idempotent.** Delivery completion is retried from the rider app's offline
      queue. `uq_bottle_ledger_order_accrual` turns a repeat into an IntegrityError,
      which we treat as "already recorded" rather than double-charging.
    """
    quantities = {
        capacity: qty for capacity, qty in quantities_by_capacity.items() if qty and qty > 0
    }
    if not quantities:
        return []

    existing = await session.execute(
        select(BottleLedgerEntry.capacity_litres).where(
            and_(
                BottleLedgerEntry.order_id == order_id,
                BottleLedgerEntry.entry_type == BottleLedgerEntryType.DELIVERY_ACCRUAL,
            )
        )
    )
    already = set(existing.scalars().all())
    pending = {c: q for c, q in quantities.items() if c not in already}
    if not pending:
        logger.info("Bottle accrual for order %s already recorded; skipping", order_id)
        return []

    registry = await _locked_registry(session, rider_id, vendor_id)
    if registry is None:
        logger.info(
            "Accruing bottle debt for rider %s / vendor %s with no registry row "
            "(radar delivery); ledger holds the record",
            rider_id,
            vendor_id,
        )

    entries: list[BottleLedgerEntry] = []
    for capacity, qty in sorted(pending.items()):
        entry = await _apply_movement(
            session,
            rider_id=rider_id,
            vendor_id=vendor_id,
            capacity=capacity,
            quantity=qty,
            entry_type=BottleLedgerEntryType.DELIVERY_ACCRUAL,
            registry=registry,
            order_id=order_id,
            actor_clerk_id=actor_clerk_id,
            note="Empties collected on quick_swap delivery",
        )
        if entry:
            entries.append(entry)

    try:
        await session.flush()
    except IntegrityError:
        # Lost a race with a concurrent retry of the same delivery. The other
        # writer recorded it; ours is the duplicate.
        await session.rollback()
        logger.info("Concurrent bottle accrual for order %s; the other write won", order_id)
        return []

    return entries


async def settle_empties(
    session: AsyncSession,
    *,
    rider_id: UUID,
    vendor_id: UUID,
    received_by_capacity: dict[int, int],
    actor_clerk_id: str | None = None,
    note: str | None = None,
) -> dict:
    """
    Vendor confirms physical receipt of empties, reducing what the rider owes.

    Validates against the outstanding balance instead of silently clamping. The
    previous implementation did `max(0, current - received)`, so a client sending
    999 zeroed the debt and the API reported success — the vendor app's own limit
    check was the only thing standing between a typo and wiping a real balance.
    """
    cleaned: dict[int, int] = {}
    for capacity, qty in received_by_capacity.items():
        if qty is None or qty == 0:
            continue
        if qty < 0:
            raise HTTPException(
                status_code=400, detail=f"Received {capacity}L bottles cannot be negative."
            )
        cleaned[capacity] = int(qty)

    if not cleaned:
        raise HTTPException(status_code=400, detail="Enter at least one bottle to record a return.")

    registry = await _locked_registry(session, rider_id, vendor_id)
    outstanding = await get_outstanding_for_pair(session, rider_id=rider_id, vendor_id=vendor_id)

    for capacity, qty in cleaned.items():
        owed = outstanding.get(capacity, 0)
        if qty > owed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Rider owes {owed} × {capacity}L bottle(s); "
                    f"cannot record {qty} as returned."
                ),
            )

    for capacity, qty in sorted(cleaned.items()):
        await _apply_movement(
            session,
            rider_id=rider_id,
            vendor_id=vendor_id,
            capacity=capacity,
            quantity=-qty,
            entry_type=BottleLedgerEntryType.VENDOR_RECEIPT,
            registry=registry,
            actor_clerk_id=actor_clerk_id,
            note=note or "Vendor confirmed receipt of empties",
        )

    await session.commit()

    remaining = await get_outstanding_for_pair(session, rider_id=rider_id, vendor_id=vendor_id)
    return {
        "message": "Bottles received and rider debt updated.",
        "received": {f"{c}L": q for c, q in sorted(cleaned.items())},
        "pending_10L_empties": remaining.get(10, 0),
        "pending_20L_empties": remaining.get(20, 0),
    }


async def get_outstanding_for_pair(
    session: AsyncSession, *, rider_id: UUID, vendor_id: UUID
) -> dict[int, int]:
    """Outstanding per capacity for one rider/vendor pair, summed from the ledger."""
    result = await session.execute(
        select(
            BottleLedgerEntry.capacity_litres,
            func.coalesce(func.sum(BottleLedgerEntry.quantity), 0),
        )
        .where(
            and_(
                BottleLedgerEntry.rider_id == rider_id,
                BottleLedgerEntry.vendor_id == vendor_id,
            )
        )
        .group_by(BottleLedgerEntry.capacity_litres)
    )
    return {int(cap): int(total) for cap, total in result.all() if int(total) > 0}


async def get_rider_outstanding(session: AsyncSession, rider_id: UUID) -> list[dict]:
    """
    Every vendor this rider owes bottles to. Powers the rider app's debt screen —
    until now a rider had no way to see what they were holding.

    Carries `held_days` and `is_stale` as well as the counts. The platform judges
    a rider on **age**: `admin_bottle_service.STALE_AFTER_DAYS` flags a pair at 14
    days and `stale_asset_monitor` sweeps nightly. The rider was shown the
    quantity and never the clock, so the first they knew of the threshold was
    being flagged against it. Same `min(created_at)` per group and same
    `STALE_AFTER_DAYS` the console reads, so the two cannot disagree.
    """
    from datetime import datetime, timezone

    from models.vendor_model import Vendor
    from services.admin_bottle_service import STALE_AFTER_DAYS

    result = await session.execute(
        select(
            BottleLedgerEntry.vendor_id,
            Vendor.business_name,
            BottleLedgerEntry.capacity_litres,
            func.coalesce(func.sum(BottleLedgerEntry.quantity), 0).label("outstanding"),
            func.min(BottleLedgerEntry.created_at).label("since"),
        )
        .join(Vendor, Vendor.id == BottleLedgerEntry.vendor_id)
        .where(BottleLedgerEntry.rider_id == rider_id)
        .group_by(BottleLedgerEntry.vendor_id, Vendor.business_name, BottleLedgerEntry.capacity_litres)
    )

    now = datetime.now(timezone.utc)

    by_vendor: dict[UUID, dict] = {}
    for vendor_id, business_name, capacity, outstanding, since in result.all():
        if int(outstanding) <= 0:
            continue
        entry = by_vendor.setdefault(
            vendor_id,
            {
                "vendor_id": str(vendor_id),
                "business_name": business_name,
                "pending_10L_empties": 0,
                "pending_20L_empties": 0,
                "other_capacities": {},
                "total_bottles": 0,
                "held_days": None,
                "is_stale": False,
            },
        )
        capacity = int(capacity)
        outstanding = int(outstanding)
        if capacity in _COUNTER_COLUMN:
            entry[_COUNTER_COLUMN[capacity]] = outstanding
        else:
            entry["other_capacities"][f"{capacity}L"] = outstanding
        entry["total_bottles"] += outstanding

        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            age = max(0, (now - since).days)
            # The oldest capacity in this pair sets the vendor's age — that is
            # the one the console's staleness check will trip on first.
            if entry["held_days"] is None or age > entry["held_days"]:
                entry["held_days"] = age
            entry["is_stale"] = (entry["held_days"] or 0) >= STALE_AFTER_DAYS

    # Oldest first. A debt sorted by size buries the one about to be escalated
    # under the one that happens to be largest.
    return sorted(
        by_vendor.values(),
        key=lambda v: (v["held_days"] if v["held_days"] is not None else -1, v["total_bottles"]),
        reverse=True,
    )


async def get_vendor_outstanding(session: AsyncSession, vendor_id: UUID) -> list[dict]:
    """
    Every rider holding this vendor's bottles — including riders with no registry
    row, who were invisible to the vendor before the ledger existed.
    """
    from models.deliverer_model import Deliverer

    result = await session.execute(
        select(
            BottleLedgerEntry.rider_id,
            Deliverer.name,
            Deliverer.phone_number,
            BottleLedgerEntry.capacity_litres,
            func.coalesce(func.sum(BottleLedgerEntry.quantity), 0).label("outstanding"),
        )
        .join(Deliverer, Deliverer.id == BottleLedgerEntry.rider_id)
        .where(BottleLedgerEntry.vendor_id == vendor_id)
        .group_by(
            BottleLedgerEntry.rider_id,
            Deliverer.name,
            Deliverer.phone_number,
            BottleLedgerEntry.capacity_litres,
        )
    )

    by_rider: dict[UUID, dict] = {}
    for rider_id, name, phone, capacity, outstanding in result.all():
        if int(outstanding) <= 0:
            continue
        entry = by_rider.setdefault(
            rider_id,
            {
                "rider_id": str(rider_id),
                "name": name,
                "phone_number": phone,
                "pending_10L_empties": 0,
                "pending_20L_empties": 0,
                "other_capacities": {},
                "total_bottles": 0,
            },
        )
        capacity = int(capacity)
        outstanding = int(outstanding)
        if capacity in _COUNTER_COLUMN:
            entry[_COUNTER_COLUMN[capacity]] = outstanding
        else:
            entry["other_capacities"][f"{capacity}L"] = outstanding
        entry["total_bottles"] += outstanding

    return sorted(by_rider.values(), key=lambda r: r["total_bottles"], reverse=True)


async def get_ledger_history(
    session: AsyncSession,
    *,
    rider_id: UUID | None = None,
    vendor_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    The evidence trail. This is what a bare counter could never provide: when a
    debt was incurred, against which order, and who confirmed the return.
    """
    if rider_id is None and vendor_id is None:
        raise HTTPException(status_code=400, detail="A rider or vendor must be specified.")

    query = select(BottleLedgerEntry)
    conditions = []
    if rider_id is not None:
        conditions.append(BottleLedgerEntry.rider_id == rider_id)
    if vendor_id is not None:
        conditions.append(BottleLedgerEntry.vendor_id == vendor_id)
    query = (
        query.where(and_(*conditions))
        .order_by(*stable(BottleLedgerEntry.created_at.desc(), key=BottleLedgerEntry.id))
        # 201, not 200: the route's ceiling is 200 rows *per page* and it asks
        # for `limit + 1` to learn whether another page exists. Clamping at 200
        # would swallow that extra row at the maximum page size and report the
        # last full page as the end of the ledger.
        .limit(min(limit, 201))
        .offset(offset)
    )

    entries = (await session.execute(query)).scalars().all()
    return [
        {
            "id": str(e.id),
            "rider_id": str(e.rider_id),
            "vendor_id": str(e.vendor_id),
            "order_id": str(e.order_id) if e.order_id else None,
            "capacity_litres": e.capacity_litres,
            "quantity": e.quantity,
            "entry_type": e.entry_type.value
            if hasattr(e.entry_type, "value")
            else str(e.entry_type),
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


def quantities_from_order_items(items: Iterable) -> dict[int, int]:
    """
    Bottle counts per capacity for a set of order items.

    Items whose product has no usable capacity are skipped — but logged, because
    silently dropping them is how debt goes missing.
    """
    quantities: dict[int, int] = {}
    for item in items:
        product = getattr(item, "product", None)
        raw_capacity = getattr(product, "capacity", None) if product else None
        try:
            capacity = int(raw_capacity or 0)
        except (TypeError, ValueError):
            capacity = 0
        if capacity <= 0:
            logger.warning(
                "Order item %s has no usable product capacity; excluded from bottle ledger",
                getattr(item, "id", "<unknown>"),
            )
            continue
        quantities[capacity] = quantities.get(capacity, 0) + int(item.quantity or 0)
    return quantities
