"""The live order board and the disputes queue.

The board's job is not to list orders — the vendor and rider apps already do
that. It is to surface the ones that are **stuck**: accepted but never
dispatched, paid but never delivered, or paused in `mismatch_pending` /
`pending_review` waiting for somebody to decide. Those are invisible to
everyone except the customer who is waiting.

Intervention is deliberately narrow. Cancelling and reassigning are here;
refunding is not, because `refund_service` owns the M-Pesa reversal and its
idempotency key, and a second path to move money is how money moves twice.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, current_admin, require_admin
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_DISPUTES_READ,
    PERM_DISPUTES_RESOLVE,
    PERM_ORDERS_INTERVENE,
    PERM_ORDERS_READ,
)
from models.bottle_rejection_model import BottleRejectionTicket, RejectionStatus
from models.deliverer_model import Deliverer
from models.order_model import Order
from models.user_model import User
from models.vendor_model import Vendor
from services import admin_service
from services.notification_service import create_notification
from utils.s3_utils import generate_presigned_url

logger = logging.getLogger(__name__)

router = APIRouter()

#: An order accepted this long ago and still not dispatched is stuck, not busy.
STALE_AFTER_MINUTES = 45

#: Statuses that mean "a human has to decide something".
PAUSED_STATUSES = ("mismatch_pending", "pending_review")

#: Terminal states. Cancelling one of these is meaningless and the refusal says so.
TERMINAL_STATUSES = ("delivered", "cancelled", "refunded")


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _serialise(order: Order, *, vendor_name=None, rider_name=None, customer_name=None) -> dict:
    return {
        "id": str(order.id),
        "status": order.order_status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total": _money(order.total_amount),
        "delivery_fee": _money(order.delivery_fee),
        "delivery_type": order.delivery_type,
        "distance_km": float(order.distance_km) if order.distance_km is not None else None,
        "vendor": {"id": str(order.vendor_id) if order.vendor_id else None, "name": vendor_name},
        "rider": {"id": str(order.deliverer_id) if order.deliverer_id else None, "name": rider_name},
        "customer": {"id": str(order.customer_id) if order.customer_id else None, "name": customer_name},
        "cancellation_reason": order.cancellation_reason,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.get("/orders", summary="The order board")
@limiter.limit("120/minute")
async def list_orders(
    request: Request,
    view: Literal["all", "stuck", "paused", "active", "cancelled"] = "stuck",
    search: Optional[str] = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ORDERS_READ)),
):
    """Defaults to `stuck`, not `all`.

    A list of every order is a report; the console exists to show the ones
    nobody else will notice. Opening the board on "all" buries four stuck
    orders under four hundred healthy ones.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=STALE_AFTER_MINUTES)

    query = (
        select(Order, Vendor.business_name, Deliverer.name, User.full_name)
        .outerjoin(Vendor, Order.vendor_id == Vendor.id)
        .outerjoin(Deliverer, Order.deliverer_id == Deliverer.id)
        .outerjoin(User, Order.customer_id == User.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )

    if view == "stuck":
        # Accepted-but-undispatched past the threshold, or paid and still not
        # delivered after a day. Both are invisible without this query.
        query = query.where(
            or_(
                (Order.order_status.in_(("pending", "accepted", "ready")))
                & (Order.created_at < stale_before),
                (Order.payment_status == "paid")
                & (Order.order_status.notin_(TERMINAL_STATUSES))
                & (Order.created_at < now - timedelta(days=1)),
                Order.order_status.in_(PAUSED_STATUSES),
            )
        )
    elif view == "paused":
        query = query.where(Order.order_status.in_(PAUSED_STATUSES))
    elif view == "active":
        query = query.where(Order.order_status.notin_(TERMINAL_STATUSES))
    elif view == "cancelled":
        query = query.where(Order.order_status == "cancelled")

    if search and search.strip():
        term = search.strip()
        clauses = [Order.phone.ilike(f"%{term}%")]
        try:
            clauses.append(Order.id == UUID(term))
        except ValueError:
            pass
        query = query.where(or_(*clauses))

    if cursor:
        anchor = await db.get(Order, cursor)
        if anchor is not None:
            query = query.where(
                (Order.created_at < anchor.created_at)
                | ((Order.created_at == anchor.created_at) & (Order.id < anchor.id))
            )

    rows = (await db.execute(query.limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "view": view,
        "items": [
            {
                **_serialise(order, vendor_name=vendor, rider_name=rider, customer_name=customer),
                "waiting_minutes": (
                    round((now - order.created_at).total_seconds() / 60)
                    if order.created_at
                    else None
                ),
            }
            for order, vendor, rider, customer in rows
        ],
        "next_cursor": str(rows[-1][0].id) if has_more and rows else None,
    }


@router.get("/orders/counts", summary="Board badge counts")
@limiter.limit("120/minute")
async def order_counts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ORDERS_READ)),
):
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=STALE_AFTER_MINUTES)

    async def count(*where):
        query = select(func.count(Order.id))
        for clause in where:
            query = query.where(clause)
        return int((await db.execute(query)).scalar() or 0)

    day_ago = now - timedelta(hours=24)

    async def money(*where):
        query = select(func.coalesce(func.sum(Order.total_amount), 0))
        for clause in where:
            query = query.where(clause)
        return str(Decimal((await db.execute(query)).scalar() or 0).quantize(Decimal("0.01")))

    # Age of the oldest thing still waiting. A count says "twelve are stuck";
    # this says whether the worst has been stuck for nine minutes or nine hours,
    # which is the difference between a queue and an incident.
    oldest = (
        await db.execute(
            select(func.min(Order.created_at)).where(
                Order.order_status.in_(("pending", "accepted", "ready")),
                Order.created_at < stale_before,
            )
        )
    ).scalar()

    unassigned = await count(
        Order.order_status == "unassigned", Order.deliverer_id.is_(None)
    )

    return {
        "paused": await count(Order.order_status.in_(PAUSED_STATUSES)),
        "stale": await count(
            Order.order_status.in_(("pending", "accepted", "ready")),
            Order.created_at < stale_before,
        ),
        "active": await count(Order.order_status.notin_(TERMINAL_STATUSES)),
        # Paid and nobody is carrying it. The one number a dispatcher acts on.
        "unassigned": unassigned,
        "oldest_stale_minutes": (
            round((now - oldest).total_seconds() / 60) if oldest else None
        ),
        # Value in flight, so "twelve stuck orders" can be weighed against what
        # they are worth. Money is summed in the database as Decimal and
        # serialised as a string — never through float.
        "active_value": await money(Order.order_status.notin_(TERMINAL_STATUSES)),
        "stale_threshold_minutes": STALE_AFTER_MINUTES,
        "delivered_24h": await count(
            Order.order_status == "delivered", Order.updated_at >= day_ago
        ),
        "cancelled_24h": await count(
            Order.order_status == "cancelled", Order.updated_at >= day_ago
        ),
    }


@router.get("/orders/{order_id}", summary="One order, in full")
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ORDERS_READ)),
):
    row = (
        await db.execute(
            select(Order, Vendor.business_name, Deliverer.name, User.full_name)
            .outerjoin(Vendor, Order.vendor_id == Vendor.id)
            .outerjoin(Deliverer, Order.deliverer_id == Deliverer.id)
            .outerjoin(User, Order.customer_id == User.id)
            .where(Order.id == order_id)
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Order not found.")

    order, vendor, rider, customer = row
    return {
        **_serialise(order, vendor_name=vendor, rider_name=rider, customer_name=customer),
        "delivery_address": order.delivery_address,
        "customer_note": order.customer_note,
        "actual_floor_level": order.actual_floor_level,
        # Proof of delivery is a stored S3 key; presigned briefly, like every
        # other document in this console.
        "proof_url": generate_presigned_url(order.proof_url, expires_in=300)
        if order.proof_url
        else None,
        "ledger": {
            "product_subtotal": _money(order.product_subtotal),
            "delivery_fee": _money(order.delivery_fee),
            "surge_fee": _money(order.surge_fee),
            "staircase_surcharge": _money(order.staircase_surcharge),
            "payload_surcharge": _money(order.payload_surcharge),
            "wallet_discount": _money(order.wallet_discount),
            "welcome_discount": _money(order.welcome_discount),
            "platform_total": _money(order.platform_total),
            "vendor_net": _money(order.vendor_net),
            "rider_net": _money(order.rider_net),
        },
    }


class InterveneRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/orders/{order_id}/cancel", summary="Cancel an order")
async def cancel_order(
    order_id: UUID,
    body: InterveneRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ORDERS_INTERVENE)),
):
    """Cancels the order and tells the customer why.

    Deliberately does **not** issue the refund. `refund_service` owns the M-Pesa
    reversal and its idempotency key; a second path to move money is how a
    refund gets sent twice. A paid order cancelled here is flagged in the
    response so the operator knows a refund still has to be raised.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.order_status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"This order is already {order.order_status}."
        )

    before = {"order_status": order.order_status}
    order.order_status = "cancelled"
    order.cancellation_reason = f"Cancelled by support: {body.reason}"

    admin_service.record_audit(
        db,
        access=access,
        action="order.cancel",
        target_type="order",
        target_id=order_id,
        before=before,
        after={"order_status": "cancelled", "payment_status": order.payment_status},
        reason=body.reason,
    )

    if order.customer_id:
        await create_notification(
            session=db,
            user_id=order.customer_id,
            user_type="customer",
            title="Your order was cancelled",
            message=body.reason,
            message_type="order_update",
            related_order_id=order.id,
        )

    await db.commit()

    return {
        "id": str(order.id),
        "status": order.order_status,
        # The operator must be told, not left to infer it from `payment_status`.
        "refund_required": order.payment_status == "paid",
    }


@router.post("/orders/{order_id}/reassign", summary="Move an order to another rider")
async def reassign_order(
    order_id: UUID,
    body: InterveneRequest,
    rider_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ORDERS_INTERVENE)),
):
    """For the rider who accepted and then went dark.

    The replacement must be someone who can actually take it: KYC-approved and
    not suspended. Assigning to a blocked rider produces an order that looks
    dispatched and never moves — which is the state being fixed.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.order_status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"This order is already {order.order_status}.")

    rider = await db.get(Deliverer, rider_id)
    if rider is None:
        raise HTTPException(status_code=404, detail="Rider not found.")
    if rider.suspended_at is not None:
        raise HTTPException(status_code=400, detail="That rider is suspended.")
    if getattr(rider.kyc_status, "value", rider.kyc_status) != "approved":
        raise HTTPException(status_code=400, detail="That rider has not passed verification.")

    before = {"deliverer_id": str(order.deliverer_id) if order.deliverer_id else None}
    order.deliverer_id = rider.id

    admin_service.record_audit(
        db,
        access=access,
        action="order.reassign",
        target_type="order",
        target_id=order_id,
        before=before,
        after={"deliverer_id": str(rider.id)},
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=rider.id,
        user_type="rider",
        title="An order was assigned to you",
        message=body.reason,
        message_type="order_update",
        related_order_id=order.id,
    )

    await db.commit()
    return {"id": str(order.id), "rider_id": str(rider.id)}


# ── Disputes ──────────────────────────────────────────────────────────────


@router.get("/disputes", summary="Bottle rejection tickets")
async def list_disputes(
    # These must be `RejectionStatus` *values*. They were "resolved"/"rejected",
    # which the enum does not define — `RejectionStatus("resolved")` raises
    # ValueError, so two of the three tabs on the disputes screen returned 500.
    status: Literal["pending_review", "approved", "denied", "all"] = "pending_review",
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DISPUTES_READ)),
):
    """A rider says the empties were short or damaged; the vendor disagrees.

    Photo URLs are **not** minted here — same reasoning as the KYC queue. The
    detail endpoint presigns them when somebody actually opens a ticket.
    """
    query = (
        select(BottleRejectionTicket, Deliverer.name, Order.id)
        .outerjoin(Deliverer, BottleRejectionTicket.rider_id == Deliverer.id)
        .outerjoin(Order, BottleRejectionTicket.order_id == Order.id)
        .order_by(BottleRejectionTicket.created_at.asc())
        .limit(limit)
    )
    if status != "all":
        query = query.where(BottleRejectionTicket.status == RejectionStatus(status))

    rows = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(ticket.id),
                "order_id": str(ticket.order_id),
                "rider": {"id": str(ticket.rider_id), "name": rider_name},
                "status": getattr(ticket.status, "value", ticket.status),
                "reason_text": ticket.reason_text,
                "photo_count": len(ticket.photo_urls or []),
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            }
            for ticket, rider_name, _ in rows
        ]
    }


@router.get("/disputes/{ticket_id}", summary="One dispute, with the rider's photos")
@limiter.limit("60/minute")
async def get_dispute(
    request: Request,
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DISPUTES_READ)),
):
    ticket = await db.get(BottleRejectionTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Dispute not found.")

    return {
        "id": str(ticket.id),
        "order_id": str(ticket.order_id),
        "rider_id": str(ticket.rider_id),
        "status": getattr(ticket.status, "value", ticket.status),
        "reason_text": ticket.reason_text,
        "photos": [
            generate_presigned_url(key, expires_in=300)
            for key in (ticket.photo_urls or [])
            if key
        ],
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    }


class ResolveDisputeRequest(BaseModel):
    """The outcome names are the ledger's, not the console's.

    A ticket is a rider's *rejection* of what they were given, so `approved`
    means the rejection stands — the rider was right and the bottles were short
    or damaged — and `denied` means it does not. The console labels them
    "Uphold the rider" and "Reject the report", which is the same decision in
    words an operator can act on.

    This previously accepted "resolved"/"rejected", neither of which is a
    `RejectionStatus` value, so **every** dispute decision raised ValueError and
    returned 500.
    """

    outcome: Literal["approved", "denied"]
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/disputes/{ticket_id}/resolve", summary="Decide a dispute")
async def resolve_dispute(
    ticket_id: UUID,
    body: ResolveDisputeRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DISPUTES_RESOLVE)),
):
    """Records the decision and tells the rider.

    The bottle-ledger adjustment stays in `bottle_ledger_service`, which owns
    the double-entry invariants. This endpoint decides; it does not do
    arithmetic on inventory.
    """
    ticket = await db.get(BottleRejectionTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Dispute not found.")

    current = getattr(ticket.status, "value", ticket.status)
    if current != "pending_review":
        raise HTTPException(status_code=409, detail=f"This dispute is already {current}.")

    before = {"status": current}
    ticket.status = RejectionStatus(body.outcome)

    admin_service.record_audit(
        db,
        access=access,
        action=f"dispute.{body.outcome}",
        target_type="dispute",
        target_id=ticket_id,
        before=before,
        after={"status": body.outcome},
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=ticket.rider_id,
        user_type="rider",
        title="Your bottle report was reviewed",
        message=body.reason,
        message_type="dispute_update",
        related_order_id=ticket.order_id,
    )

    await db.commit()
    return {"id": str(ticket.id), "status": body.outcome}
