"""Managing customers, riders and vendors.

Mounted under `/api/admin`. Every handler is gated by `require_admin(...)`, and
`tests/test_admin_rbac.py` walks this module too — an endpoint here without a
gate fails the build.

The permission for each account type is checked *per type*, not once for the
module: an operator trusted with riders is not thereby trusted with the
customer table.
"""
import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.admin_dependencies import AdminAccess, current_admin, require_admin
from core.redis_client import redis_limiter as limiter
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_CUSTOMERS_READ,
    PERM_VENDORS_APPROVE,
    PERM_CUSTOMERS_SUSPEND,
    PERM_PII_VIEW,
    PERM_RIDERS_READ,
    PERM_RIDERS_SUSPEND,
    PERM_VENDORS_READ,
    PERM_VENDORS_SUSPEND,
)
from services import admin_people_service as people
from services import admin_service
from services.notification_service import create_notification

logger = logging.getLogger(__name__)

router = APIRouter()

Kind = Literal["customer", "rider", "vendor"]

#: Reading and suspending are separate grants per account type, so the gate for
#: a request depends on both the verb and the kind in the path.
READ_PERMISSION = {
    "customer": PERM_CUSTOMERS_READ,
    "rider": PERM_RIDERS_READ,
    "vendor": PERM_VENDORS_READ,
}
SUSPEND_PERMISSION = {
    "customer": PERM_CUSTOMERS_SUSPEND,
    "rider": PERM_RIDERS_SUSPEND,
    "vendor": PERM_VENDORS_SUSPEND,
}

NOTIFY_USER_TYPE = {"customer": "customer", "rider": "rider", "vendor": "vendor"}


@router.get("/people/{kind}s", summary="List customers, riders or vendors")
async def list_people(
    kind: Kind,
    search: Optional[str] = Query(None, max_length=120),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    """One endpoint for three account types.

    `current_admin` establishes *an* administrator; the capability for this
    particular type is required immediately below, because the required
    permission is not knowable until the path is parsed.
    """
    access.require(READ_PERMISSION[kind])
    return await people.list_people(
        db, kind=kind, search=search, status=status, limit=limit, cursor=cursor
    )


@router.get("/people/{kind}s/{person_id}", summary="One account, with its order history")
async def get_person(
    kind: Kind,
    person_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    access.require(READ_PERMISSION[kind])
    return await people.get_person(db, kind=kind, person_id=person_id)


@router.get("/people/{kind}s/{person_id}/contact", summary="Reveal contact details")
# Deliberately tight. Reviewing accounts legitimately means a handful of reveals
# an hour; walking the customer table one record at a time looks exactly like
# this endpoint being called in a loop.
@limiter.limit("30/minute")
async def reveal_contact(
    request: Request,
    kind: Kind,
    person_id: UUID,
    reason: str = Query(..., min_length=3, max_length=500),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_PII_VIEW)),
):
    """Unmasking somebody's phone number and address is an action, not a render.

    Lists mask contact details for every role. This endpoint requires
    `pii.view`, requires a stated reason, and writes the audit row **before**
    returning anything — so "who looked up this customer, and why" has an
    answer.
    """
    access.require(READ_PERMISSION[kind])

    admin_service.record_audit(
        db,
        access=access,
        action=f"{kind}.pii.view",
        target_type=kind,
        target_id=person_id,
        reason=reason,
    )
    await db.commit()

    return await people.reveal_contact(db, kind=kind, person_id=person_id)


class SuspendRequest(BaseModel):
    #: Required, and shown to the person suspended. A suspension nobody can
    #: explain becomes a support ticket and an appeal with nothing to appeal
    #: against.
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/people/{kind}s/{person_id}/suspend", summary="Suspend an account")
async def suspend_person(
    kind: Kind,
    person_id: UUID,
    body: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    """Takes the account out of the platform immediately.

    For a vendor this clears `is_active`, which
    `vendor_service.discoverable_vendor()` reads — so the store leaves customer
    search, the directory, "near you", product search and its own detail page in
    the same transaction. Before that predicate existed, suspending a store
    would have reported success and changed nothing a customer could see.
    """
    access.require(SUSPEND_PERMISSION[kind])

    row, before, after = await people.set_suspended(
        db,
        kind=kind,
        person_id=person_id,
        suspend=True,
        reason=body.reason,
        admin_id=access.id,
    )

    admin_service.record_audit(
        db,
        access=access,
        action=f"{kind}.suspend",
        target_type=kind,
        target_id=person_id,
        before=before,
        after=after,
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=row.id,
        user_type=NOTIFY_USER_TYPE[kind],
        title="Your account has been suspended",
        message=body.reason,
        message_type="account_status",
    )

    await db.commit()
    return {"id": str(row.id), "suspended": True}


@router.post("/people/{kind}s/{person_id}/reinstate", summary="Lift a suspension")
async def reinstate_person(
    kind: Kind,
    person_id: UUID,
    body: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    access.require(SUSPEND_PERMISSION[kind])

    row, before, after = await people.set_suspended(
        db,
        kind=kind,
        person_id=person_id,
        suspend=False,
        reason=body.reason,
        admin_id=access.id,
    )

    admin_service.record_audit(
        db,
        access=access,
        action=f"{kind}.reinstate",
        target_type=kind,
        target_id=person_id,
        before=before,
        after=after,
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=row.id,
        user_type=NOTIFY_USER_TYPE[kind],
        title="Your account is active again",
        message=body.reason,
        message_type="account_status",
    )

    await db.commit()
    return {"id": str(row.id), "suspended": False}


@router.get("/search", summary="Find anything by phone, email, name or order id")
# Three ILIKE scans per call. The palette debounces, but the endpoint must not
# depend on a well-behaved client for that.
@limiter.limit("60/minute")
async def search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=120),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    """The command palette.

    Results are scoped by the caller's capabilities — searching must not become
    a way to enumerate a table whose detail page the caller cannot open.
    """
    return await people.global_search(db, term=q, permissions=set(access.permissions))


# ── Vendor verification ───────────────────────────────────────────────────
#
# `vendors.approve` existed as a capability with nothing behind it. Every vendor
# on the platform is `pending`, and customer discovery does not check the field
# at all — so verification was a column nobody could change and nothing read.
#
# These endpoints make it a real workflow. Whether it then *gates trading* is a
# separate switch (`platform_settings.require_vendor_verification`), deliberately
# off by default: turning it on today would empty the customer app.


class VendorVerificationRequest(BaseModel):
    decision: Literal["verified", "rejected"]
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/people/vendors/{vendor_id}/verification", summary="Verify or reject a vendor")
async def review_vendor_verification(
    vendor_id: UUID,
    body: VendorVerificationRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_VENDORS_APPROVE)),
):
    """Records the verification decision and tells the vendor.

    Rejection sets `verification_status` but deliberately does **not** suspend
    the store. They are different statements — "we have not confirmed your
    paperwork" and "you may not trade" — and conflating them would take a
    working business offline for a missing document.
    """
    from models.vendor_model import Vendor

    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    if vendor.verification_status == "deleted":
        raise HTTPException(status_code=409, detail="That store has been deleted.")

    before = {"verification_status": vendor.verification_status}
    vendor.verification_status = body.decision

    admin_service.record_audit(
        db,
        access=access,
        action=f"vendor.{body.decision}",
        target_type="vendor",
        target_id=vendor_id,
        before=before,
        after={"verification_status": body.decision},
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=vendor.id,
        user_type="vendor",
        title=(
            "Your store is verified ✅"
            if body.decision == "verified"
            else "We couldn't verify your store"
        ),
        message=body.reason,
        message_type="account_status",
    )

    await db.commit()
    return {"id": str(vendor.id), "verification_status": vendor.verification_status}
