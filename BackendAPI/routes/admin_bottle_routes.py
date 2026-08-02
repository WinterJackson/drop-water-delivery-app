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
from models.admin_model import PERM_FINANCE_ADJUST, PERM_RIDERS_READ
from services import admin_bottle_service, admin_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/bottles", summary="The empty-bottle float")
@limiter.limit("60/minute")
async def bottles(
    request: Request,
    view: str = Query("all", pattern="^(all|stale|drift|movements)$"),
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    """One screen for the whole float.

    `drift` is served on every view rather than only its own tab: a registry
    counter that disagrees with the ledger makes every other figure on the page
    suspect, and burying that behind a tab nobody clicks defeats the purpose of
    computing it.
    """
    return {
        "summary": await admin_bottle_service.overview(db),
        "holders": await admin_bottle_service.holders(
            db, limit=limit, stale_only=view == "stale"
        ),
        "drift": await admin_bottle_service.drift(db),
        "movements": await admin_bottle_service.entries(db, limit=limit)
        if view == "movements"
        else [],
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
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    return {
        "items": await admin_bottle_service.entries(
            db,
            rider_id=rider_id,
            vendor_id=vendor_id,
            entry_type=entry_type,
            limit=limit,
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
