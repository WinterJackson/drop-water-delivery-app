"""Managing customers, riders and vendors.

Mounted under `/api/admin`. Every handler is gated by `require_admin(...)`, and
`tests/test_admin_rbac.py` walks this module too — an endpoint here without a
gate fails the build.

The permission for each account type is checked *per type*, not once for the
module: an operator trusted with riders is not thereby trusted with the
customer table.
"""
import logging
from decimal import Decimal
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
    PERM_FINANCE_ADJUST,
    PERM_VENDORS_APPROVE,
    PERM_CUSTOMERS_SUSPEND,
    PERM_PII_VIEW,
    PERM_RIDERS_READ,
    PERM_RIDERS_SUSPEND,
    PERM_VENDORS_READ,
    PERM_VENDORS_SUSPEND,
)
from models.user_model import User
from services import admin_people_service as people, admin_performance_service
from services import admin_service
from utils import keyset
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
    cursor: Optional[str] = None,
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


@router.get("/performance/riders", summary="Rider throughput and reliability")
@limiter.limit("60/minute")
async def rider_performance(
    request: Request,
    search: Optional[str] = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    cursor: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    return await admin_performance_service.riders(
        db, limit=limit, cursor=cursor, search=search
    )


@router.get("/performance/vendors", summary="Store volume and fulfilment")
@limiter.limit("60/minute")
async def vendor_performance(
    request: Request,
    search: Optional[str] = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    cursor: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_VENDORS_READ)),
):
    return await admin_performance_service.vendors(
        db, limit=limit, cursor=cursor, search=search
    )


# ── A customer's balances ─────────────────────────────────────────────────
#
# Two obligations run in opposite directions and were both invisible until now:
# what the customer owes the platform (`debt_balance`) and what the platform
# owes the customer (`bottle_deposit_balance`). Neither had any way to be
# settled from the console, so a KSH 50 penalty was a permanent block on an
# account and a paid deposit could never be returned.


class DebtWriteOff(BaseModel):
    """Cancel some or all of what a customer owes."""

    amount: Optional[Decimal] = Field(
        None, description="How much to write off. Omit to clear the whole balance."
    )
    reason: str = Field(..., min_length=10, max_length=500)


class DepositReturn(BaseModel):
    """Record bottles handed back and return the deposit to the customer's wallet."""

    bottles: int = Field(..., ge=1, le=100)
    reason: str = Field(..., min_length=10, max_length=500)


class AccountKind(BaseModel):
    """Household or commercial. Decides which bottle ceiling applies."""

    is_commercial: bool
    reason: str = Field(..., min_length=10, max_length=500)


@router.get(
    "/people/customers/{customer_id}/balances",
    summary="What a customer owes, and what they are owed",
)
@limiter.limit("60/minute")
async def customer_balances(
    request: Request,
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_CUSTOMERS_READ)),
):
    customer = await db.get(User, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    ceiling = await _debt_ceiling(db)
    debt = Decimal(str(customer.debt_balance or 0))

    return {
        "customer_id": str(customer_id),
        "wallet_balance": str(Decimal(str(customer.wallet_balance or 0))),
        "debt_balance": str(debt),
        "debt_ceiling": str(ceiling),
        # Below the ceiling the debt is collected on their next order, so it is
        # not actually stopping them. Saying which is the difference between
        # "chase this" and "leave it alone".
        "debt_blocks_ordering": debt >= ceiling,
        "bottle_deposit_balance": str(Decimal(str(customer.bottle_deposit_balance or 0))),
        "bottles_held": int(customer.bottles_held or 0),
        # Which ceiling this account is held to, and the ceiling itself. An
        # office refused at six bottles needs somebody to be able to see *why*
        # before they can fix it.
        "is_commercial": bool(customer.is_commercial),
        "bottle_limit": await _bottle_ceiling_for(db, customer),
        # Spendable, not withdrawable: returned bottle deposit. Shown because
        # "your balance is 900 but you can withdraw 0" is otherwise a support
        # ticket that nobody in the console can answer.
        "wallet_not_withdrawable": str(Decimal(str(customer.non_withdrawable_balance or 0))),
    }


async def _bottle_ceiling_for(db: AsyncSession, customer: User) -> int:
    from services import customer_bottle_service

    return await customer_bottle_service.bottle_ceiling(db, customer)


async def _debt_ceiling(db: AsyncSession) -> Decimal:
    from services import platform_config_service as config

    await config.ensure_fresh(db)
    return config.get_decimal("max_customer_debt_before_block")


@router.post(
    "/people/customers/{customer_id}/debt/write-off",
    summary="Write off what a customer owes",
)
# Same limit as a manual wallet adjustment. There is no scripted use for this.
@limiter.limit("10/minute")
async def write_off_debt(
    request: Request,
    customer_id: UUID,
    body: DebtWriteOff,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Cancel a cancellation penalty or a disputed staircase charge.

    Gated on `finance.adjust` rather than `customers.read` because it forgives a
    real receivable — the same grant, held by no preset but super admin, that
    moving a balance by hand requires.

    A customer below the ceiling settles their balance automatically on their
    next order, so this exists for the two cases that cannot: a charge that was
    wrong, and a customer who has stopped ordering and is stuck at the ceiling.
    """
    customer = await db.get(User, customer_id, with_for_update=True)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    before = Decimal(str(customer.debt_balance or 0))
    if before <= 0:
        raise HTTPException(status_code=400, detail="This customer owes nothing.")

    amount = before if body.amount is None else Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="A write-off of zero does nothing.")
    if amount > before:
        raise HTTPException(
            status_code=400,
            detail=f"They owe {before}, which is less than the {amount} you asked to write off.",
        )

    customer.debt_balance = before - amount

    admin_service.record_audit(
        db,
        access=access,
        action="finance.debt_write_off",
        target_type="customer",
        target_id=customer_id,
        before={"debt_balance": str(before)},
        after={"debt_balance": str(customer.debt_balance), "written_off": str(amount)},
        reason=body.reason,
    )

    # Tell them. A balance that silently disappears is indistinguishable from a
    # bug to the person it happens to.
    await create_notification(
        session=db,
        user_id=customer.id,
        user_type="customer",
        title="Balance cleared ✅",
        message=(
            f"KSH {amount} has been cleared from your account. You can order as normal."
            if customer.debt_balance == 0
            else f"KSH {amount} has been cleared from your account. KSH {customer.debt_balance} remains."
        ),
        message_type="system_alert",
    )

    await db.commit()

    return {
        "customer_id": str(customer_id),
        "written_off": str(amount),
        "debt_balance": str(customer.debt_balance),
    }


@router.post(
    "/people/customers/{customer_id}/account-kind",
    summary="Mark a customer as a household or a commercial account",
)
@limiter.limit("20/minute")
async def set_account_kind(
    request: Request,
    customer_id: UUID,
    body: AccountKind,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_CUSTOMERS_SUSPEND)),
):
    """Which bottle ceiling this account is held to.

    `max_bottles_held_commercial` existed, was validated, and could never apply:
    the column deciding it had no way of being set, so every account on the
    platform was a household and an office ordering water was refused at six
    bottles with nothing anyone could do about it. A limit that cannot be lifted
    is not a limit, it is a wall.

    Deliberately not self-service, and not `customers.read`. It raises the
    platform's own exposure to one account — the ceiling exists to cap how many
    bottles a single party can hold on deposit — so it sits with the grant that
    already covers acting on an account rather than merely viewing one.
    """
    customer = await db.get(User, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    before = bool(customer.is_commercial)
    if before == body.is_commercial:
        return {
            "customer_id": str(customer_id),
            "is_commercial": before,
            "bottle_limit": await _bottle_ceiling_for(db, customer),
            "message": "No change — that is already how this account is set.",
        }

    customer.is_commercial = body.is_commercial

    admin_service.record_audit(
        db,
        access=access,
        action="customers.account_kind",
        target_type="customer",
        target_id=customer_id,
        before={"is_commercial": before},
        after={"is_commercial": body.is_commercial},
        reason=body.reason,
    )

    await db.commit()
    return {
        "customer_id": str(customer_id),
        "is_commercial": bool(customer.is_commercial),
        "bottle_limit": await _bottle_ceiling_for(db, customer),
    }


@router.post(
    "/people/customers/{customer_id}/deposit/return",
    summary="Return a bottle deposit",
)
@limiter.limit("30/minute")
async def return_deposit(
    request: Request,
    customer_id: UUID,
    body: DepositReturn,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Give a customer their deposit back when they hand the bottles in.

    Credits their wallet rather than disbursing cash: the money is already held
    as a liability, a wallet credit is spendable immediately and withdrawable
    through the normal payout path, and it leaves a `WalletTransaction` that
    explains itself. A second disbursement path for the same obligation is how
    money gets paid twice.

    Refuses to return more bottles than the customer holds — the bottle ledger
    learned that clamping makes a typo indistinguishable from a real return.
    """
    from services import customer_bottle_service

    customer = await db.get(User, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    before_bottles = int(customer.bottles_held or 0)
    before_balance = Decimal(str(customer.bottle_deposit_balance or 0))

    result = await customer_bottle_service.refund_deposit(
        db,
        customer_id=customer_id,
        bottles=body.bottles,
        actor=access.email,
        reason=body.reason,
    )

    admin_service.record_audit(
        db,
        access=access,
        action="finance.deposit_return",
        target_type="customer",
        target_id=customer_id,
        before={
            "bottles_held": str(before_bottles),
            "bottle_deposit_balance": str(before_balance),
        },
        after=result,
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=customer_id,
        user_type="customer",
        title="Deposit returned 🍶",
        message=(
            f"KSH {result['amount_refunded']} has been returned to your wallet for "
            f"{body.bottles} bottle(s)."
        ),
        message_type="system_alert",
    )

    await db.commit()
    return result
