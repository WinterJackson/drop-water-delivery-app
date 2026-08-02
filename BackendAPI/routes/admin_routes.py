"""The admin console's API.

Every handler here is gated by `require_admin("<capability>")` — one gate, one
implementation. `tests/test_admin_rbac.py` walks this module's route table and
fails the build if a handler is added without one, so an unprotected endpoint
cannot arrive by omission.

Four things this replaces, all of which were live:

* `require_admin` compared the caller against a comma-separated
  `ADMIN_CLERK_IDS` environment variable. No roles, no attribution, and
  revoking someone required a redeploy.
* `/payouts` read the encrypted `account_details` column through raw `text()`
  SQL. `StringEncryptedType` decrypts in the ORM type, so raw SQL returns
  ciphertext — the payout screen would have shown `S/xQ6YBb9arO/y2vUpduxQ==`
  where the M-Pesa number belongs.
* Revenue was computed in `float`. Money is `Decimal` on this platform.
* The KYC queue presigned every document into the list response, so opening the
  page minted live URLs for identity documents nobody had asked to see, and the
  approve/reject action left no record of who decided or why.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.admin_dependencies import AdminAccess, current_admin, require_admin
from core.redis_client import redis_limiter as limiter
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_ADMINS_MANAGE,
    PERM_ANALYTICS_READ,
    PERM_DISPUTES_READ,
    PERM_FINANCE_PAYOUT_APPROVE,
    PERM_FINANCE_READ,
    PERM_ORDERS_READ,
    PERM_PII_VIEW,
    PERM_RIDERS_KYC_REVIEW,
    PERM_RIDERS_READ,
    PERM_SETTINGS_MANAGE,
    PERM_SUPPORT_READ,
    PERM_VENDORS_READ,
    PERMISSION_LABELS,
)
from models.bottle_rejection_model import BottleRejectionTicket, RejectionStatus
from models.deliverer_model import Deliverer, KYCStatus
from models.order_model import Order
from models.payout_model import Payout
from models.platform_setting_model import SupportTicket
from models.user_model import User
from models.vendor_model import Vendor
from services import admin_service
from services.notification_service import create_notification
from utils.s3_utils import generate_presigned_url

logger = logging.getLogger(__name__)

router = APIRouter()

#: Identity documents are presigned for five minutes in the admin console, not
#: the platform default of fifteen. The reviewer is looking at the document now;
#: a URL that outlives the review is a copy of somebody's national ID that keeps
#: working after the tab is closed.
KYC_URL_TTL_SECONDS = 300


# ── Helpers ───────────────────────────────────────────────────────────────


def _mask(value: str | None, keep: int = 4) -> str | None:
    """Enough to recognise a record, not enough to use it.

    Lists render masked values for everyone. The full value is a separate,
    audited request that requires `pii.view` — so the common case (finding a
    rider, checking a status) never puts personal data on screen at all.
    """
    if not value:
        return None
    tail = value[-keep:] if len(value) > keep else value
    return f"••••{tail}"


def _money(value) -> str:
    """Money crosses the wire as a decimal string.

    `float(Decimal("0.1") + Decimal("0.2"))` is not `0.3`, and a revenue figure
    that disagrees with the ledger by cents is a figure nobody trusts. JSON has
    no decimal type, so the string is the honest encoding and the frontend
    formats it.
    """
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


# ── Who am I ──────────────────────────────────────────────────────────────


@router.get("/me", summary="The signed-in administrator and their capabilities")
async def admin_me(access: AdminAccess = Depends(current_admin)):
    """The dashboard's bootstrap call.

    Deliberately requires no particular capability — its entire purpose is to
    tell the caller which ones they have, so the console can render only what
    they can actually use. Hiding a control is courtesy; the server still
    refuses the action.
    """
    return {
        "id": str(access.admin.id),
        "email": access.email,
        "name": access.admin.name,
        "role": access.admin.role,
        "permissions": sorted(access.permissions),
        "permission_labels": {p: PERMISSION_LABELS[p] for p in sorted(access.permissions)},
    }


# ── Navigation badges ─────────────────────────────────────────────────────


#: An order sitting in one of these for this long is stuck, not busy. Mirrors
#: `admin_orders_routes.STALE_AFTER_MINUTES` — a badge that disagrees with the
#: board it links to is worse than no badge.
NAV_STALE_AFTER_MINUTES = 45


@router.get("/nav/counts", summary="Queue depths for the navigation badges")
# Called on every page load of the console, so it is cheap and rate-limited
# generously. Seven `COUNT(*)`s at most, each on an indexed predicate.
@limiter.limit("240/minute")
async def nav_counts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    """What is waiting, per queue, for **this** administrator.

    Takes `current_admin` rather than a fixed capability because the answer is
    per-key: a support agent gets the dispute count and no payout count, from
    the same call. Each figure is computed only when the caller may open the
    screen it belongs to — a badge reading "3" on a page that would refuse them
    leaks the size of a table they cannot see, and invites a support ticket
    about a queue they cannot work.

    Absent keys mean "not permitted", which the console renders as no badge at
    all. It deliberately does not send zeros for those: zero is a real, useful
    answer and must not be indistinguishable from a refusal.
    """
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=NAV_STALE_AFTER_MINUTES)
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    async def _count(model, *where):
        q = select(func.count()).select_from(model)
        for clause in where:
            q = q.where(clause)
        return int((await db.execute(q)).scalar() or 0)

    counts: dict[str, int] = {}

    if access.may(PERM_RIDERS_READ):
        counts["rider_kyc"] = await _count(Deliverer, Deliverer.kyc_status == KYCStatus.pending)

    if access.may(PERM_VENDORS_READ):
        counts["vendor_verification"] = await _count(
            Vendor,
            Vendor.verification_status == "pending",
            Vendor.is_active.is_(True),
        )

    if access.may(PERM_ORDERS_READ):
        counts["orders_stuck"] = await _count(
            Order,
            or_(
                Order.order_status.in_(("mismatch_pending", "pending_review")),
                and_(
                    Order.order_status.in_(("pending", "accepted", "ready")),
                    Order.created_at < stale_before,
                ),
            ),
        )

    if access.may(PERM_DISPUTES_READ):
        counts["disputes"] = await _count(
            BottleRejectionTicket,
            BottleRejectionTicket.status == RejectionStatus.PENDING_REVIEW,
        )

    if access.may(PERM_SUPPORT_READ):
        # Only `open`. A ticket moves to `pending` the moment an administrator
        # replies, so counting that too would badge the queue with conversations
        # that are waiting on the *requester* — a number nobody can act on is
        # how people learn to ignore every badge in the console.
        counts["support"] = await _count(SupportTicket, SupportTicket.status == "open")

    if access.may(PERM_FINANCE_READ):
        counts["payouts"] = await _count(Payout, Payout.status == "pending")
        counts["payouts_stuck"] = await _count(
            Payout, Payout.status == "processing", Payout.created_at < day_ago
        )

    return counts


# ── Deployment settings ───────────────────────────────────────────────────


@router.get("/settings", summary="The switches this deployment is running with")
async def platform_settings(
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    """Read-only, and honestly labelled as such.

    These are process environment variables, so changing one means editing it on
    the host and restarting — there is no write endpoint here, and offering one
    that appeared to work but silently did nothing until the next deploy would
    be worse than offering none.

    Business values are **not** here. They are rows in `Platform_Settings`,
    served by `/api/admin/config` and editable — mixing the two on one screen is
    how somebody comes to believe a number they can change is one they cannot,
    or the reverse.

    No secrets are returned — only whether each one is configured. That
    distinction is the whole diagnostic value ("push is silent because the key
    is missing") without putting the key on a screen.
    """

    def _flag(name: str, default: str) -> bool:
        return os.getenv(name, default).strip().lower() == "true"

    def _configured(name: str) -> bool:
        return bool((os.getenv(name) or "").strip())

    return {
        "switches": [
            # "Only verified stores are discoverable" used to be listed here, as
            # an environment variable. It is a platform setting now — reporting
            # it from `os.getenv` would show "off" while the console had it on,
            # which is worse than not reporting it at all.
            {
                "key": "ADMIN_2FA_REQUIRED",
                "label": "Administrators must have two-factor enabled",
                "enabled": _flag("ADMIN_2FA_REQUIRED", "true"),
                "detail": (
                    "This console reads identity documents and approves payouts, so a "
                    "password on its own is not enough. Leave this on."
                ),
            },
        ],
        "integrations": [
            {"key": "CLERK_SECRET_KEY", "label": "Clerk server API", "configured": _configured("CLERK_SECRET_KEY")},
            {"key": "S3_BUCKET_NAME", "label": "Document storage bucket", "configured": _configured("S3_BUCKET_NAME")},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Storage credentials", "configured": _configured("AWS_ACCESS_KEY_ID")},
            {"key": "GOOGLE_MAPS_SERVER_API_KEY", "label": "Maps web services", "configured": _configured("GOOGLE_MAPS_SERVER_API_KEY")},
            {"key": "REDIS_URL", "label": "Background jobs and rate limits", "configured": _configured("REDIS_URL")},
        ],
    }


# ── Overview ──────────────────────────────────────────────────────────────


@router.get("/overview", summary="Headline numbers and anything needing attention")
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """One round trip for the landing page.

    Assembled server-side because six independent widgets meant six requests
    and six spinners, and the numbers could disagree with each other by however
    long the slowest one took.
    """
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    async def _count(model, *where):
        q = select(func.count()).select_from(model)
        for clause in where:
            q = q.where(clause)
        return int((await db.execute(q)).scalar() or 0)

    pending_kyc = await _count(Deliverer, Deliverer.kyc_status == KYCStatus.pending)
    pending_payouts = await _count(Payout, Payout.status == "pending")
    # Withdrawals Safaricom accepted into its queue and never reported on. These
    # are debited balances with no resolution, so they are surfaced on the front
    # page rather than waiting to be asked about.
    stuck_payouts = await _count(
        Payout, Payout.status == "processing", Payout.created_at < day_ago
    )

    revenue = await db.execute(
        select(
            func.coalesce(func.sum(Order.platform_total), 0),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.count(Order.id),
        ).where(Order.payment_status == "paid", Order.created_at >= week_ago)
    )
    platform_total, gmv, order_count = revenue.one()

    return {
        "needs_attention": {
            "pending_kyc": pending_kyc,
            "pending_payouts": pending_payouts,
            "stuck_payouts": stuck_payouts,
        },
        "last_7_days": {
            "revenue": _money(platform_total),
            "gmv": _money(gmv),
            "orders": int(order_count or 0),
        },
        "totals": {
            "customers": await _count(User),
            "vendors": await _count(Vendor),
            "riders": await _count(Deliverer),
            "active_vendors": await _count(Vendor, Vendor.is_active.is_(True)),
        },
    }


# ── Rider KYC ─────────────────────────────────────────────────────────────


@router.get("/kyc/queue", summary="Riders awaiting KYC review")
async def kyc_queue(
    status: Literal["pending", "approved", "rejected", "unsubmitted"] = "pending",
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    """Oldest first — this is a queue, and a rider waiting three days is what
    should be handled next, not the newest arrival.

    Personal data is masked and **no document URLs are minted here**. Presigning
    every document in the list would create live links to identity documents on
    every page load, whether or not anyone opened one.
    """
    query = (
        select(Deliverer)
        .where(Deliverer.kyc_status == KYCStatus(status))
        .order_by(Deliverer.created_at.asc(), Deliverer.id.asc())
    )

    if cursor:
        anchor = await db.get(Deliverer, cursor)
        if anchor is not None:
            query = query.where(
                (Deliverer.created_at > anchor.created_at)
                | ((Deliverer.created_at == anchor.created_at) & (Deliverer.id > anchor.id))
            )

    rows = (await db.execute(query.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    now = datetime.now(timezone.utc)
    return {
        "items": [
            {
                "id": str(r.id),
                # `Deliverer.name` — only `User` has `full_name`.
                "full_name": r.name,
                "phone_number": _mask(r.phone_number, keep=3),
                "vehicle_type": r.vehicle_type,
                "plate_number": r.plate_number,
                "kyc_status": r.kyc_status.value if r.kyc_status else None,
                "has_license": bool(r.driver_license),
                "rejection_reason": r.kyc_rejection_reason,
                "submitted_at": r.created_at.isoformat() if r.created_at else None,
                # Drives the SLA colour in the queue. Computed here so every
                # client agrees on what "waiting too long" means.
                "waiting_hours": (
                    round((now - r.created_at).total_seconds() / 3600, 1)
                    if r.created_at
                    else None
                ),
            }
            for r in rows
        ],
        "next_cursor": str(rows[-1].id) if has_more and rows else None,
    }


@router.get("/riders/{rider_id}/documents", summary="Reveal a rider's KYC documents")
# Identity documents. Reviewing the queue means opening these one at a time.
@limiter.limit("30/minute")
async def reveal_kyc_documents(
    request: Request,
    rider_id: UUID,
    reason: str = Query(..., min_length=3, max_length=500),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_PII_VIEW)),
):
    """Minting URLs for someone's identity documents is an action, not a render.

    It requires `pii.view`, it requires a stated reason, and it is written to
    the audit log before the URLs are returned. After an incident the question
    is "who looked at this person's ID, and why" — this is what answers it.
    """
    rider = await db.get(Deliverer, rider_id)
    if rider is None:
        raise HTTPException(status_code=404, detail="Rider not found.")

    admin_service.record_audit(
        db,
        access=access,
        action="rider.pii.view",
        target_type="rider",
        target_id=rider_id,
        reason=reason,
        after={"documents": ["id_card_front", "id_card_back", "driver_license"]},
    )
    await db.commit()

    def _url(key):
        return generate_presigned_url(key, expires_in=KYC_URL_TTL_SECONDS) if key else None

    return {
        "id": str(rider.id),
        "full_name": rider.name,
        "phone_number": rider.phone_number,
        "ID_number": rider.ID_number,
        "id_card_front": _url(rider.id_card_front),
        "id_card_back": _url(rider.id_card_back),
        "driver_license": _url(rider.driver_license),
        "expires_in": KYC_URL_TTL_SECONDS,
    }


class KYCReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    #: Required on rejection, validated below. A rejection with no reason sends
    #: the rider back to a prefilled form with nothing to change.
    rejection_reason: Optional[str] = Field(None, max_length=500)


@router.put("/riders/{rider_id}/kyc", summary="Approve or reject a rider")
async def review_rider_kyc(
    rider_id: UUID,
    body: KYCReviewRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_KYC_REVIEW)),
):
    rider = await db.get(Deliverer, rider_id)
    if rider is None:
        raise HTTPException(status_code=404, detail="Rider not found.")

    reason = (body.rejection_reason or "").strip()
    if body.status == "rejected" and len(reason) < 3:
        raise HTTPException(
            status_code=400,
            detail="Tell the rider what was wrong, so they can fix it and resubmit.",
        )

    if rider.kyc_status == KYCStatus.approved and body.status == "approved":
        # Idempotent: a double-click must not write a second audit record
        # implying a second decision was taken.
        return {"kyc_status": rider.kyc_status.value, "unchanged": True}

    before = {"kyc_status": rider.kyc_status.value if rider.kyc_status else None}

    approved = body.status == "approved"
    rider.kyc_status = KYCStatus.approved if approved else KYCStatus.rejected
    rider.kyc_rejection_reason = None if approved else reason
    rider.kyc_reviewed_at = datetime.now(timezone.utc)

    admin_service.record_audit(
        db,
        access=access,
        action="rider.kyc.approve" if approved else "rider.kyc.reject",
        target_type="rider",
        target_id=rider_id,
        before=before,
        after={"kyc_status": rider.kyc_status.value},
        reason=reason or None,
    )

    await create_notification(
        session=db,
        user_id=rider.id,
        user_type="rider",
        title="You're verified ✅" if approved else "We couldn't verify your documents",
        message=(
            "You can go online and start accepting deliveries now."
            if approved
            else reason
        ),
        message_type="kyc_status",
        action_url="/(screens)/VerificationWall",
    )

    # One commit: the status change, its audit record and the notification land
    # together or not at all.
    await db.commit()

    return {"kyc_status": rider.kyc_status.value, "unchanged": False}


# ── Payouts ───────────────────────────────────────────────────────────────


@router.get("/payouts", summary="Payouts, newest first")
async def list_payouts(
    status: str = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Read through the ORM, not raw SQL.

    `account_details` is a `StringEncryptedType`; decryption happens in the
    type's `process_result_value`, which only runs for a typed ORM column. The
    previous implementation used `text()` and returned base64 ciphertext where
    the destination phone number should be — which would have made the payout
    screen unusable and, worse, look like corrupted data.

    The destination is masked unless the caller holds `pii.view`, so finance
    staff can triage the queue without every M-Pesa number on screen.
    """
    query = (
        select(Payout)
        .where(Payout.status == status)
        .order_by(Payout.created_at.desc(), Payout.id.desc())
    )

    if cursor:
        anchor = await db.get(Payout, cursor)
        if anchor is not None:
            query = query.where(
                (Payout.created_at < anchor.created_at)
                | ((Payout.created_at == anchor.created_at) & (Payout.id < anchor.id))
            )

    rows = (await db.execute(query.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    may_see = access.may(PERM_PII_VIEW)
    return {
        "items": [
            {
                "id": str(p.id),
                "amount": _money(p.amount),
                "status": p.status,
                "provider_type": p.provider_type,
                "provider_id": str(p.provider_id),
                "payment_method": p.payment_method,
                "account_details": p.account_details if may_see else _mask(p.account_details),
                "mpesa_receipt": p.mpesa_receipt,
                "failure_reason": p.failure_reason,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in rows
        ],
        "next_cursor": str(rows[-1].id) if has_more and rows else None,
    }


class PayoutDecision(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/payouts/{payout_id}/approve", summary="Release a pending payout")
async def approve_payout(
    payout_id: UUID,
    body: PayoutDecision,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_PAYOUT_APPROVE)),
):
    """Records the decision to release a payout, and who made it.

    Money movement stays in `wallet_service` / `payout_service`, which own the
    B2C call and the idempotency key. Approving here does not itself disburse —
    duplicating that logic is how a payout gets sent twice.
    """
    payout = await db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found.")

    if payout.status != "pending":
        raise HTTPException(status_code=409, detail=f"This payout is already {payout.status}.")

    before = {"status": payout.status}
    payout.status = "approved"

    admin_service.record_audit(
        db,
        access=access,
        action="payout.approve",
        target_type="payout",
        target_id=payout_id,
        before=before,
        after={"status": payout.status, "amount": _money(payout.amount)},
        reason=body.reason,
    )
    await db.commit()
    return {"id": str(payout.id), "status": payout.status}


@router.post("/payouts/{payout_id}/reject", summary="Refuse a pending payout")
async def reject_payout(
    payout_id: UUID,
    body: PayoutDecision,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_PAYOUT_APPROVE)),
):
    payout = await db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found.")
    if payout.status != "pending":
        raise HTTPException(status_code=409, detail=f"This payout is already {payout.status}.")

    before = {"status": payout.status}
    payout.status = "failed"
    payout.failure_reason = body.reason

    admin_service.record_audit(
        db,
        access=access,
        action="payout.reject",
        target_type="payout",
        target_id=payout_id,
        before=before,
        after={"status": payout.status},
        reason=body.reason,
    )
    await db.commit()
    return {"id": str(payout.id), "status": payout.status}


# ── Revenue ───────────────────────────────────────────────────────────────


@router.get("/revenue", summary="Platform revenue and its components")
async def platform_revenue(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD, inclusive"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD, inclusive"),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Every figure is `Decimal`, serialised as a string.

    The previous implementation cast each sum with `float()`. Money on this
    platform is `Decimal` everywhere else, and a revenue report that disagrees
    with the ledger by fractions of a cent is one that gets argued with instead
    of used. It also built its SQL by string concatenation; this uses the ORM,
    so the date filters are bound parameters by construction.
    """
    filters = [Order.payment_status == "paid"]
    filters += _date_filters(start_date, end_date)

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.platform_total), 0),
                func.coalesce(func.sum(Order.vendor_commission), 0),
                func.coalesce(func.sum(Order.service_fee), 0),
                func.coalesce(func.sum(Order.rider_commission), 0),
                func.coalesce(func.sum(Order.delivery_markup), 0),
                func.coalesce(func.sum(Order.surge_fee), 0),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.count(Order.id),
            ).where(*filters)
        )
    ).one()

    (platform_total, vendor_comm, service_fee, rider_comm, markup, surge, gmv, orders) = totals
    orders = int(orders or 0)

    by_type = (
        await db.execute(
            select(
                Vendor.vendor_type,
                func.count(Order.id),
                func.coalesce(func.sum(Order.platform_total), 0),
            )
            .join(Vendor, Order.vendor_id == Vendor.id)
            .where(*filters)
            .group_by(Vendor.vendor_type)
        )
    ).all()

    total = Decimal(platform_total or 0)
    gmv_decimal = Decimal(gmv or 0)
    return {
        "total_platform_revenue": _money(total),
        "breakdown": {
            "vendor_commissions": _money(vendor_comm),
            "service_fees": _money(service_fee),
            "rider_commissions": _money(rider_comm),
            "delivery_markups": _money(markup),
            "surge_fees": _money(surge),
        },
        "total_orders": orders,
        "total_gmv": _money(gmv_decimal),
        # Guarded: the original divided by the order count outside its own zero
        # check, so an empty date range raised ZeroDivisionError.
        "avg_revenue_per_order": _money(total / orders) if orders else _money(0),
        "take_rate_pct": (
            str((total / gmv_decimal * 100).quantize(Decimal("0.01")))
            if gmv_decimal
            else "0.00"
        ),
        "by_vendor_type": {
            (vtype or "unknown"): {"orders": int(count or 0), "revenue": _money(rev)}
            for vtype, count, rev in by_type
        },
    }


def _date_filters(start_date: str | None, end_date: str | None) -> list:
    """Parse the range, refusing anything that is not a date.

    An unparseable string used to be concatenated straight into the SQL string.
    `end_date` is treated as inclusive by taking everything before the following
    midnight, rather than appending `23:59:59` and silently dropping the last
    second of the day.
    """
    filters = []
    for raw, which in ((start_date, "start"), (end_date, "end")):
        if not raw:
            continue
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{which}_date must be YYYY-MM-DD.")
        if which == "start":
            filters.append(Order.created_at >= parsed)
        else:
            filters.append(Order.created_at < parsed + timedelta(days=1))
    return filters


# ── Administrators ────────────────────────────────────────────────────────


@router.get("/admins", summary="The administrator roster")
async def list_admins(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ADMINS_MANAGE)),
):
    return {
        "items": await admin_service.list_admins(db),
        **admin_service.permission_catalogue(),
    }


class InviteAdminRequest(BaseModel):
    email: str
    name: Optional[str] = None
    role: str
    permissions: Optional[list[str]] = None


@router.post("/admins", summary="Grant administrator access")
async def invite_admin(
    body: InviteAdminRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ADMINS_MANAGE)),
):
    result = await admin_service.invite_admin(
        db,
        access=access,
        email=body.email,
        name=body.name,
        role=body.role,
        permissions=body.permissions,
    )
    admin_service.record_audit(
        db,
        access=access,
        action="admin.invite",
        target_type="admin",
        target_id=result["admin"]["id"],
        after={"email": result["admin"]["email"], "role": result["admin"]["role"]},
    )
    await db.commit()
    return result


class UpdateAdminRequest(BaseModel):
    role: Optional[str] = None
    permissions: Optional[list[str]] = None


@router.patch("/admins/{admin_id}", summary="Change an administrator's access")
async def update_admin(
    admin_id: UUID,
    body: UpdateAdminRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ADMINS_MANAGE)),
):
    admin, before, after = await admin_service.update_admin(
        db, access=access, admin_id=admin_id, role=body.role, permissions=body.permissions
    )
    admin_service.record_audit(
        db,
        access=access,
        action="admin.update",
        target_type="admin",
        target_id=admin_id,
        before=before,
        after=after,
    )
    await db.commit()
    return admin_service.serialize_admin(admin)


@router.delete("/admins/{admin_id}", summary="Revoke administrator access")
async def revoke_admin(
    admin_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ADMINS_MANAGE)),
):
    admin = await admin_service.revoke_admin(db, access=access, admin_id=admin_id)
    admin_service.record_audit(
        db,
        access=access,
        action="admin.revoke",
        target_type="admin",
        target_id=admin_id,
        before={"email": admin.email, "role": admin.role},
    )
    await db.commit()
    return {"id": str(admin.id), "revoked": True}


@router.get("/audit", summary="What administrators have done")
async def audit_log(
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    admin_id: Optional[UUID] = None,
    action: Optional[str] = None,
    target_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ADMINS_MANAGE)),
):
    items = await admin_service.list_audit(
        db,
        limit=limit,
        before_id=cursor,
        admin_id=admin_id,
        action=action,
        target_id=target_id,
    )
    return {
        "items": items,
        "next_cursor": items[-1]["id"] if len(items) == limit else None,
    }
