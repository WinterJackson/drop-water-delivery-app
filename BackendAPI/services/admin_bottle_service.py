"""The empty-bottle float, from the platform's side.

`bottle_ledger_entries` is written on every quick_swap delivery and every vendor
receipt, and until now it was read only by the rider app ("what am I holding?")
and the vendor app ("who is holding mine?"). Nobody could see the whole float,
and the whole float is a real asset: a 20L bottle carries a refundable deposit
the platform has already collected from the customer, so a bottle that never
comes back is money the platform owes and cannot recover.

## Three things this exists to answer

1. **How much is out, and what is it worth.** Priced from
   `bottle_deposit_by_capacity` in `Platform_Settings`, the same figure the
   customer was charged — not a constant invented here.
2. **Which pairs have gone stale.** A rider who accrued bottles three weeks ago
   and has returned none is either owed a conversation or has left. Age is the
   signal; the balance alone never expires.
3. **Whether the ledger and the counters still agree.**
   `bottle_ledger_service` declares an invariant:

       SUM(bottle_ledger_entries.quantity) == VendorRiderRegistry.pending_{n}L_empties

   An invariant nobody checks is a comment. `drift()` is the check, and it is on
   the page rather than in a test because the ways it breaks — a hand-edited row,
   a half-applied migration, a crash between the ledger write and the counter —
   all happen in production and never in CI.

## Why a balance is netted per pair before it is totalled

A rider can hold Vendor A's bottles while Vendor B holds a credit against them
from an over-recorded return. Summing the raw `quantity` column platform-wide
would let B's negative cancel A's positive and report less float than exists.
Every total here nets per (rider, vendor, capacity) first and counts only the
positive side.

## Data honesty

`bottle_ledger_entries` is empty on this deployment — quick_swap deliveries have
not started. Every aggregate below is derived from the same signed-sum shape the
rider and vendor apps already use in production, but the platform-level figures
have not yet been observed against real movement volume. Treat the arithmetic as
reviewed and the calibration (`STALE_AFTER_DAYS` in particular) as a first
estimate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bottle_ledger_model import BottleLedgerEntry, BottleLedgerEntryType
from models.deliverer_model import Deliverer
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry
from services import platform_config_service

#: An accrual older than this with the pair still in debt is worth chasing. A
#: rider on a normal round returns empties within a day or two; a fortnight
#: means they have stopped coming back to that vendor, and the platform would
#: rather find that out from a screen than from a vendor's phone call.
STALE_AFTER_DAYS = 14

#: The registry only has counter columns for these. Other capacities still get
#: ledger rows — the trail must be complete — so they cannot drift by definition.
COUNTER_CAPACITIES = (10, 20)

_COUNTER_COLUMN = {
    10: VendorRiderRegistry.pending_10L_empties,
    20: VendorRiderRegistry.pending_20L_empties,
}


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


async def _deposits(db: AsyncSession) -> dict[int, Decimal]:
    """Refundable deposit per capacity, from `Platform_Settings`.

    Read through the config service rather than hardcoded, so the value here is
    the same one the customer was charged. A bottle valued at a number this
    module invented is a number nobody can reconcile against a receipt.
    """
    await platform_config_service.ensure_fresh(db)
    raw = platform_config_service.get("bottle_deposit_by_capacity") or {}
    out: dict[int, Decimal] = {}
    for key, value in raw.items():
        try:
            out[int(key)] = Decimal(str(value))
        except (TypeError, ValueError):
            continue
    return out


async def _pair_balances(db: AsyncSession) -> list[tuple[UUID, UUID, int, int, datetime | None]]:
    """Net outstanding per (rider, vendor, capacity), positives only.

    Also carries the oldest entry in the group, which is what makes staleness
    answerable — the balance on its own has no age.
    """
    rows = (
        await db.execute(
            select(
                BottleLedgerEntry.rider_id,
                BottleLedgerEntry.vendor_id,
                BottleLedgerEntry.capacity_litres,
                func.coalesce(func.sum(BottleLedgerEntry.quantity), 0).label("net"),
                func.min(BottleLedgerEntry.created_at).label("since"),
            )
            .group_by(
                BottleLedgerEntry.rider_id,
                BottleLedgerEntry.vendor_id,
                BottleLedgerEntry.capacity_litres,
            )
            .having(func.coalesce(func.sum(BottleLedgerEntry.quantity), 0) > 0)
        )
    ).all()
    return [(r, v, int(c), int(n), s) for r, v, c, n, s in rows]


def _age_days(moment: datetime | None) -> int | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - moment).days)


async def overview(db: AsyncSession) -> dict[str, Any]:
    """The float as one screen: how much is out, what it is worth, what is stale."""
    balances = await _pair_balances(db)
    deposits = await _deposits(db)

    by_capacity: dict[int, int] = {}
    value = Decimal("0")
    riders: set[UUID] = set()
    vendors: set[UUID] = set()
    stale_pairs = 0
    stale_bottles = 0
    oldest_days: int | None = None

    for rider_id, vendor_id, capacity, net, since in balances:
        by_capacity[capacity] = by_capacity.get(capacity, 0) + net
        value += deposits.get(capacity, Decimal("0")) * net
        riders.add(rider_id)
        vendors.add(vendor_id)

        age = _age_days(since)
        if age is not None:
            oldest_days = age if oldest_days is None else max(oldest_days, age)
            if age >= STALE_AFTER_DAYS:
                stale_pairs += 1
                stale_bottles += net

    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    movements_24h = int(
        (
            await db.execute(
                select(func.count())
                .select_from(BottleLedgerEntry)
                .where(BottleLedgerEntry.created_at >= day_ago)
            )
        ).scalar()
        or 0
    )

    entries_total = int(
        (await db.execute(select(func.count()).select_from(BottleLedgerEntry))).scalar() or 0
    )

    drifted = await drift(db)

    return {
        "bottles_out": sum(by_capacity.values()),
        "by_capacity": [
            {
                "capacity": capacity,
                "bottles": count,
                "deposit": _money(deposits.get(capacity)),
                "value": _money(deposits.get(capacity, Decimal("0")) * count),
                # A capacity with no configured deposit cannot be valued, and
                # saying so beats quietly pricing it at zero.
                "priced": capacity in deposits,
            }
            for capacity, count in sorted(by_capacity.items())
        ],
        "value_at_risk": _money(value),
        "unpriced_capacities": sorted(c for c in by_capacity if c not in deposits),
        "riders_holding": len(riders),
        "vendors_awaiting": len(vendors),
        "pairs": len(balances),
        "stale_pairs": stale_pairs,
        "stale_bottles": stale_bottles,
        "stale_after_days": STALE_AFTER_DAYS,
        "oldest_debt_days": oldest_days,
        "movements_24h": movements_24h,
        "entries_total": entries_total,
        "drift_count": len(drifted),
    }


async def holders(db: AsyncSession, *, limit: int = 100, stale_only: bool = False) -> list[dict]:
    """Every rider/vendor pair with bottles outstanding, worst first.

    "Worst" is deposit value, not bottle count: twelve 10L bottles are a smaller
    problem than eight 20L ones, and the person deciding whether to chase this
    is deciding about money.
    """
    balances = await _pair_balances(db)
    if not balances:
        return []

    deposits = await _deposits(db)

    rider_ids = {rider_id for rider_id, _, _, _, _ in balances}
    vendor_ids = {vendor_id for _, vendor_id, _, _, _ in balances}

    rider_rows = (
        await db.execute(
            select(Deliverer.id, Deliverer.name, Deliverer.suspended_at).where(
                Deliverer.id.in_(rider_ids)
            )
        )
    ).all()
    vendor_rows = (
        await db.execute(
            select(Vendor.id, Vendor.business_name).where(Vendor.id.in_(vendor_ids))
        )
    ).all()
    rider_by_id = {rid: (name, suspended) for rid, name, suspended in rider_rows}
    vendor_by_id = {vid: name for vid, name in vendor_rows}

    grouped: dict[tuple[UUID, UUID], dict[str, Any]] = {}
    for rider_id, vendor_id, capacity, net, since in balances:
        key = (rider_id, vendor_id)
        name, suspended = rider_by_id.get(rider_id, (None, None))
        pair = grouped.setdefault(
            key,
            {
                "rider_id": str(rider_id),
                "rider_name": name,
                "rider_suspended": suspended is not None,
                "vendor_id": str(vendor_id),
                "vendor_name": vendor_by_id.get(vendor_id),
                "bottles": 0,
                "by_capacity": {},
                "_value": Decimal("0"),
                "_since": since,
            },
        )
        pair["bottles"] += net
        pair["by_capacity"][str(capacity)] = net
        pair["_value"] += deposits.get(capacity, Decimal("0")) * net
        if since and (pair["_since"] is None or since < pair["_since"]):
            pair["_since"] = since

    out: list[dict[str, Any]] = []
    for pair in grouped.values():
        age = _age_days(pair.pop("_since"))
        value = pair.pop("_value")
        pair["age_days"] = age
        pair["stale"] = age is not None and age >= STALE_AFTER_DAYS
        pair["value"] = _money(value)
        pair["_sort"] = value
        out.append(pair)

    if stale_only:
        out = [pair for pair in out if pair["stale"]]

    out.sort(key=lambda pair: pair.pop("_sort"), reverse=True)
    return out[:limit]


async def drift(db: AsyncSession) -> list[dict]:
    """Registry counters that disagree with the ledger they denormalise.

    Only the pairs that *have* a registry row can drift. A radar rider with no
    registry row has ledger entries and no counter, which is the documented
    design and not a discrepancy — so those are excluded rather than reported as
    a mismatch against zero.
    """
    ledger = {
        (rider_id, vendor_id, capacity): net
        for rider_id, vendor_id, capacity, net, _ in await _pair_balances(db)
        if capacity in COUNTER_CAPACITIES
    }

    registry_rows = (
        await db.execute(
            select(
                VendorRiderRegistry.rider_id,
                VendorRiderRegistry.vendor_id,
                VendorRiderRegistry.pending_10L_empties,
                VendorRiderRegistry.pending_20L_empties,
                Deliverer.name,
                Vendor.business_name,
            )
            .outerjoin(Deliverer, Deliverer.id == VendorRiderRegistry.rider_id)
            .outerjoin(Vendor, Vendor.id == VendorRiderRegistry.vendor_id)
        )
    ).all()

    out: list[dict] = []
    for rider_id, vendor_id, ten, twenty, rider_name, vendor_name in registry_rows:
        for capacity, counter in ((10, int(ten or 0)), (20, int(twenty or 0))):
            expected = ledger.get((rider_id, vendor_id, capacity), 0)
            if counter == expected:
                continue
            out.append(
                {
                    "rider_id": str(rider_id),
                    "rider_name": rider_name,
                    "vendor_id": str(vendor_id),
                    "vendor_name": vendor_name,
                    "capacity": capacity,
                    "ledger": expected,
                    "counter": counter,
                    "difference": counter - expected,
                }
            )

    out.sort(key=lambda row: abs(row["difference"]), reverse=True)
    return out


async def reseat_counters(db: AsyncSession) -> list[dict]:
    """Rewrite every drifted registry counter from the ledger.

    Safe in one direction only, and that is the direction it goes. The ledger is
    append-only and every row records who caused it and when; the counter is a
    denormalisation with none of that. When they disagree, the ledger is right by
    construction, so the repair is always "make the counter match" and never the
    reverse.

    Deliberately *not* automatic. Silently correcting drift on read would hide
    the fact that something wrote a counter without a ledger row — which is a bug
    worth finding, not a nuisance worth papering over. An administrator presses
    this, and the audit log records that they did.
    """
    drifted = await drift(db)
    if not drifted:
        return []

    for row in drifted:
        registry = (
            await db.execute(
                select(VendorRiderRegistry)
                .where(
                    and_(
                        VendorRiderRegistry.rider_id == UUID(row["rider_id"]),
                        VendorRiderRegistry.vendor_id == UUID(row["vendor_id"]),
                    )
                )
                .with_for_update()
            )
        ).scalars().first()
        if registry is None:
            continue
        column = "pending_10L_empties" if row["capacity"] == 10 else "pending_20L_empties"
        setattr(registry, column, max(0, row["ledger"]))

    await db.flush()
    return drifted


async def entries(
    db: AsyncSession,
    *,
    rider_id: UUID | None = None,
    vendor_id: UUID | None = None,
    entry_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """The movement feed — the evidence a counter could never provide."""
    query = (
        select(
            BottleLedgerEntry,
            Deliverer.name,
            Vendor.business_name,
        )
        .outerjoin(Deliverer, Deliverer.id == BottleLedgerEntry.rider_id)
        .outerjoin(Vendor, Vendor.id == BottleLedgerEntry.vendor_id)
        .order_by(BottleLedgerEntry.created_at.desc())
    )

    if rider_id is not None:
        query = query.where(BottleLedgerEntry.rider_id == rider_id)
    if vendor_id is not None:
        query = query.where(BottleLedgerEntry.vendor_id == vendor_id)
    if entry_type:
        try:
            query = query.where(BottleLedgerEntry.entry_type == BottleLedgerEntryType(entry_type))
        except ValueError:
            return []

    rows = (await db.execute(query.limit(limit))).all()

    return [
        {
            "id": str(entry.id),
            "rider_id": str(entry.rider_id),
            "rider_name": rider_name,
            "vendor_id": str(entry.vendor_id),
            "vendor_name": vendor_name,
            "order_id": str(entry.order_id) if entry.order_id else None,
            "capacity": entry.capacity_litres,
            "quantity": entry.quantity,
            "entry_type": entry.entry_type.value
            if hasattr(entry.entry_type, "value")
            else str(entry.entry_type),
            "note": entry.note,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry, rider_name, vendor_name in rows
    ]


async def adjust(
    db: AsyncSession,
    *,
    rider_id: UUID,
    vendor_id: UUID,
    capacity: int,
    quantity: int,
    note: str,
    actor_clerk_id: str | None,
) -> dict[str, Any]:
    """Write off, or write on, a bottle balance by hand.

    This exists because the alternative is worse. A rider who leaves the platform
    holding eight bottles otherwise sits on the vendor's screen for ever, and the
    only way anyone found to clear it was editing the counter directly — which
    breaks the invariant, leaves no reason and no author, and is exactly what the
    ledger was built to stop.

    So the correction goes through the ledger like every other movement: signed,
    attributed, with a mandatory note, and the counter follows. `drift()` stays
    clean afterwards, which is the whole point.

    Raises `ValueError` for anything the caller got wrong, so the route can turn
    it into a 400 without this module importing FastAPI.
    """
    if quantity == 0:
        raise ValueError("An adjustment of zero bottles changes nothing.")
    if capacity <= 0:
        raise ValueError("Capacity must be a positive number of litres.")
    if not note or not note.strip():
        raise ValueError("An adjustment needs a reason.")

    outstanding = {
        capacity_litres: net
        for r, v, capacity_litres, net, _ in await _pair_balances(db)
        if r == rider_id and v == vendor_id
    }
    held = outstanding.get(capacity, 0)

    # A negative adjustment forgives debt; it cannot forgive more than exists.
    # Without this the ledger goes negative and every total that nets positives
    # starts disagreeing with the vendor's own screen.
    if quantity < 0 and abs(quantity) > held:
        raise ValueError(
            f"This rider holds {held} × {capacity}L for this store; "
            f"cannot write off {abs(quantity)}."
        )

    registry = (
        await db.execute(
            select(VendorRiderRegistry)
            .where(
                and_(
                    VendorRiderRegistry.rider_id == rider_id,
                    VendorRiderRegistry.vendor_id == vendor_id,
                )
            )
            .with_for_update()
        )
    ).scalars().first()

    entry = BottleLedgerEntry(
        rider_id=rider_id,
        vendor_id=vendor_id,
        order_id=None,
        capacity_litres=capacity,
        quantity=quantity,
        entry_type=BottleLedgerEntryType.ADJUSTMENT,
        actor_clerk_id=actor_clerk_id,
        note=note.strip(),
    )
    db.add(entry)

    # The counter is a denormalisation of the ledger and must move with it, or
    # this correction becomes the next drift row.
    if registry is not None and capacity in COUNTER_CAPACITIES:
        column = "pending_10L_empties" if capacity == 10 else "pending_20L_empties"
        setattr(registry, column, max(0, (getattr(registry, column) or 0) + quantity))

    await db.flush()

    return {
        "id": str(entry.id),
        "before": held,
        "after": held + quantity,
        "capacity": capacity,
        "quantity": quantity,
    }
