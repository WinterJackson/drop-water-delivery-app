"""The empty-bottle float.

Read is gated on `riders.read`: the float is a rider-side liability and anyone
allowed to look at riders may look at what they are holding.

Adjusting a balance by hand is gated on `finance.adjust` — the same capability
as crediting a wallet, and for the same reason. A written-off 20L bottle is a
refundable deposit the platform collected and will not return, so this is money
being moved by an assertion rather than by an event. No preset but super admin
holds it.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_FINANCE_ADJUST, PERM_FINANCE_READ, PERM_RIDERS_READ
from services import admin_bottle_service, admin_service
from utils import keyset

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/bottles", summary="The empty-bottle float")
@limiter.limit("60/minute")
async def bottles(
    request: Request,
    view: str = Query("all", pattern="^(all|stale|drift|movements)$"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    """One screen for the whole float.

    `drift` is served on every view rather than only its own tab: a registry
    counter that disagrees with the ledger makes every other figure on the page
    suspect, and burying that behind a tab nobody clicks defeats the purpose of
    computing it.
    """
    # Only the list the current view actually renders is paged; the other is
    # not fetched at all. Both were fetched on every view, so opening the float
    # ran the movement feed as well and vice versa.
    holders = {"items": [], "next_cursor": None, "total": 0}
    movements = {"items": [], "next_cursor": None}
    if view == "movements":
        movements = await admin_bottle_service.entries(
            db, search=search, limit=limit, cursor=cursor
        )
    else:
        holders = await admin_bottle_service.holders(
            db, limit=limit, stale_only=view == "stale", search=search, cursor=cursor
        )

    return {
        "summary": await admin_bottle_service.overview(db),
        "holders": holders["items"],
        "holders_total": holders["total"],
        "movements": movements["items"],
        # One cursor for whichever list this view is showing — they are never
        # both on screen, so a second would page the list nobody is looking at.
        "next_cursor": (movements if view == "movements" else holders)["next_cursor"],
        "drift": await admin_bottle_service.drift(db),
    }


@router.get("/bottles/movements", summary="Ledger movements for one rider or store")
@limiter.limit("60/minute")
async def movements(
    request: Request,
    rider_id: UUID | None = None,
    vendor_id: UUID | None = None,
    entry_type: str | None = Query(
        None, pattern="^(delivery_accrual|vendor_receipt|adjustment)$"
    ),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    return {
        **await admin_bottle_service.entries(
            db,
            rider_id=rider_id,
            vendor_id=vendor_id,
            entry_type=entry_type,
            search=search,
            limit=limit,
            cursor=cursor,
        )
    }


class Reseat(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


@router.post("/bottles/reseat", summary="Rewrite drifted counters from the ledger")
async def reseat(
    body: Reseat,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Repair `VendorRiderRegistry` counters that disagree with the ledger.

    One direction only: the ledger is append-only and attributed, the counter is
    a denormalisation of it, so the ledger wins by construction. It is a button
    rather than something the read path does quietly, because drift means
    *something wrote a counter without a ledger row* and that is a bug worth
    finding rather than a nuisance worth hiding.
    """
    repaired = await admin_bottle_service.reseat_counters(db)
    if not repaired:
        return {"repaired": 0, "rows": []}

    admin_service.record_audit(
        db,
        access=access,
        action="bottles.reseat",
        target_type="vendor_rider_registry",
        target_id=None,
        before={"drifted": repaired},
        after={"repaired": len(repaired), "reason": body.reason.strip()},
    )
    await db.commit()

    return {"repaired": len(repaired), "rows": repaired}


class Adjustment(BaseModel):
    rider_id: UUID
    vendor_id: UUID
    capacity: int = Field(gt=0, le=1000)
    #: Signed. Negative forgives what the rider owes; positive records bottles
    #: the ledger missed. Bounded because a slipped keystroke here rewrites a
    #: balance two businesses have agreed on.
    quantity: int = Field(ge=-500, le=500)
    reason: str = Field(min_length=8, max_length=500)


@router.post("/bottles/adjust", summary="Correct a bottle balance by hand")
async def adjust(
    body: Adjustment,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Write off, or write on, a rider's bottle debt.

    Goes through the ledger, never the counter. Editing
    `VendorRiderRegistry.pending_*_empties` directly — which is what people did
    before this existed — breaks the invariant the ledger maintains, leaves no
    reason and no author, and shows up afterwards as an unexplained drift row.

    The reason is mandatory and is the entry's `note`, so it travels with the
    movement into both apps' history rather than living only in the audit log.
    """
    try:
        result = await admin_bottle_service.adjust(
            db,
            rider_id=body.rider_id,
            vendor_id=body.vendor_id,
            capacity=body.capacity,
            quantity=body.quantity,
            note=body.reason,
            actor_clerk_id=access.clerk_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    admin_service.record_audit(
        db,
        access=access,
        action="bottles.adjust",
        target_type="bottle_ledger",
        target_id=result["id"],
        before={"outstanding": result["before"]},
        after={
            "outstanding": result["after"],
            "capacity": result["capacity"],
            "quantity": result["quantity"],
            "rider_id": str(body.rider_id),
            "vendor_id": str(body.vendor_id),
            "reason": body.reason.strip(),
        },
    )
    await db.commit()

    return result


# ── The deposit book ──────────────────────────────────────────────────────
#
# The rider-side float above is one bottle relationship. This is the third one:
# customers who paid a deposit and are holding a bottle against it. It was
# maintained correctly and shown on no screen, so the platform could not state
# its own largest customer-facing liability without opening a database client.


@router.get("/bottles/deposits", summary="What the platform owes customers, aged")
@limiter.limit("60/minute")
async def deposit_liability(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Total deposit liability, split by how long it has sat untouched.

    One number is not enough to act on. "KSH 400,000 outstanding" cannot
    distinguish a healthy circulating pool of bottles from four hundred sold at
    cost to people who are never coming back, and those want opposite responses.
    """
    from services import customer_bottle_service

    return await customer_bottle_service.liability_summary(db)


@router.get("/bottles/returns", summary="Bottle collections needing a decision")
@limiter.limit("60/minute")
async def bottle_returns(
    request: Request,
    status: str = Query("disputed", max_length=24),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """The dispute queue, and any other status on request.

    Defaults to `disputed` because that is the only status with a person
    waiting on it: the two sides gave different counts, or a customer confirmed
    a handover no rider ever confirmed. Nothing has moved in either case.
    """
    from sqlalchemy import select

    from models.bottle_return_model import BottleReturnRequest

    rows = (
        await db.execute(
            select(BottleReturnRequest)
            .where(BottleReturnRequest.status == status)
            .order_by(BottleReturnRequest.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(row.id),
                "customer_id": str(row.customer_id),
                "rider_id": str(row.rider_id) if row.rider_id else None,
                "status": row.status,
                "bottles_requested": row.bottles_requested,
                "bottles_stated_by_customer": row.bottles_stated_by_customer,
                "bottles_stated_by_rider": row.bottles_stated_by_rider,
                "resolution_note": row.resolution_note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


class ResolveReturn(BaseModel):
    """Settle a disputed collection at a count a human has decided."""

    bottles: int = Field(..., ge=0, le=100)
    reason: str = Field(..., min_length=10, max_length=500)


@router.post("/bottles/returns/{request_id}/resolve", summary="Decide a disputed collection")
@limiter.limit("20/minute")
async def resolve_bottle_return(
    request: Request,
    request_id: UUID,
    body: ResolveReturn,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Pay out a disputed collection at the count an administrator has decided.

    `finance.adjust`, not `finance.read`: this moves money on the strength of a
    judgement rather than of two matching confirmations, which is exactly the
    kind of decision that grant exists to fence off.

    `bottles: 0` closes the dispute without paying — the collection did not
    happen — and still records who decided that and why.
    """
    from sqlalchemy import select

    from models.bottle_return_model import BottleReturnRequest, BottleReturnStatus
    from services import customer_bottle_service

    row = (
        await db.execute(
            select(BottleReturnRequest)
            .where(BottleReturnRequest.id == request_id)
            .with_for_update()
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    if row.status != BottleReturnStatus.DISPUTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"This collection is {row.status}, not disputed; there is nothing to decide.",
        )

    before = {
        "status": row.status,
        "customer_said": row.bottles_stated_by_customer,
        "rider_said": row.bottles_stated_by_rider,
    }

    if body.bottles == 0:
        row.status = BottleReturnStatus.CANCELLED.value
        row.bottles_settled = 0
        row.resolution_note = body.reason
        row.resolved_by_email = access.email
        result = {"status": row.status, "request_id": str(row.id), "bottles_returned": 0}
    else:
        result = await customer_bottle_service.settle_return(
            db, request=row, bottles=body.bottles,
            reason=f"resolved by {access.email}",
        )
        row.resolution_note = body.reason
        row.resolved_by_email = access.email

    admin_service.record_audit(
        db,
        access=access,
        action="finance.bottle_return_resolve",
        target_type="bottle_return",
        target_id=request_id,
        before=before,
        after=result,
        reason=body.reason,
    )

    await db.commit()
    return result
