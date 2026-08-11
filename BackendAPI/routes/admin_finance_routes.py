"""Money: the ledger, the collections, and adjusting a balance by hand.

The read endpoints are the reconciliation surface — where did a shilling come
from, where did it go, and what is stuck. The one write endpoint is the most
abusable action in this console and is built accordingly.
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
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_FINANCE_ADJUST,
    PERM_FINANCE_READ,
    PERM_FINANCE_REFUND_APPROVE,
    PERM_PII_VIEW,
)
from models.deliverer_model import Deliverer
from models.order_model import Order
from models.payment_model import Payment
from models.payout_model import Payout
from models.user_model import User
from models.vendor_model import Vendor
from models.wallet_transaction_model import (
    TransactionStatus,
    TransactionType,
    WalletTransaction,
)
from services import (
    admin_reconciliation_service,
    admin_service,
    admin_settlement_service,
    wallet_service,
)
from services.notification_service import create_notification

logger = logging.getLogger(__name__)

router = APIRouter()

OWNER_MODELS = {"customer": User, "rider": Deliverer, "vendor": Vendor}

#: A single manual adjustment above this is almost certainly a mistake — a
#: misplaced decimal, or a figure meant to be cents. It is a refusal rather than
#: a warning because there is no undo on a credited balance somebody has spent.
MAX_ADJUSTMENT = Decimal("100000.00")


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _mask(value: Optional[str], keep: int = 4) -> Optional[str]:
    if not value:
        return None
    tail = value[-keep:] if len(value) > keep else value
    return f"••••{tail}"


# ── The ledger ────────────────────────────────────────────────────────────


@router.get("/finance/transactions", summary="The wallet ledger")
@limiter.limit("120/minute")
async def list_transactions(
    request: Request,
    user_type: Optional[Literal["customer", "rider", "vendor"]] = None,
    transaction_type: Optional[str] = None,
    status: Optional[str] = None,
    #: The account's **Clerk id**, which is what this column holds — not the
    #: row UUID. Named `clerk_id` so a caller cannot pass the wrong one and get
    #: a silently empty result.
    clerk_id: Optional[str] = None,
    search: Optional[str] = Query(None, max_length=120),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Every balance movement on the platform, newest first.

    Keyset pagination on `(created_at, id)` rather than OFFSET: this is the
    table that grows fastest on a working platform, and OFFSET degrades exactly
    when it starts to matter.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(WalletTransaction)
        .where(WalletTransaction.created_at >= since)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
    )

    if user_type:
        query = query.where(WalletTransaction.user_type == user_type)
    if transaction_type:
        query = query.where(WalletTransaction.transaction_type == transaction_type)
    if status:
        query = query.where(WalletTransaction.status == status)
    if clerk_id:
        query = query.where(WalletTransaction.user_id == clerk_id)
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.where(
            or_(
                WalletTransaction.mpesa_receipt_number.ilike(like),
                WalletTransaction.reference_id.ilike(like),
                WalletTransaction.description.ilike(like),
            )
        )

    if cursor:
        anchor = await db.get(WalletTransaction, cursor)
        if anchor is not None:
            query = query.where(
                (WalletTransaction.created_at < anchor.created_at)
                | (
                    (WalletTransaction.created_at == anchor.created_at)
                    & (WalletTransaction.id < anchor.id)
                )
            )

    rows = (await db.execute(query.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "items": [
            {
                "id": str(row.id),
                "user_id": row.user_id,
                "user_type": getattr(row.user_type, "value", row.user_type),
                "transaction_type": getattr(row.transaction_type, "value", row.transaction_type),
                "amount": _money(row.amount),
                "status": getattr(row.status, "value", row.status),
                "description": row.description,
                # A receipt number identifies a payment, not a person, but it is
                # still a key into somebody's M-Pesa statement.
                "mpesa_receipt": (
                    row.mpesa_receipt_number
                    if access.may(PERM_PII_VIEW)
                    else _mask(row.mpesa_receipt_number)
                ),
                "reference_id": row.reference_id,
                "failure_reason": row.failure_reason,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "next_cursor": str(rows[-1].id) if has_more and rows else None,
    }


@router.get("/finance/cash-exposure", summary="Cash currently in riders' hands")
async def cash_exposure(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """How much of the platform's money is on a motorbike right now.

    The one figure nobody could produce. Each rider sees their own committed
    float on their own screen, and the platform's total existed only as a query
    somebody would have had to write — so the limits that cap it
    (`cod_max_daily_exposure`, `cod_max_concurrent_orders`) were being set
    against a number nobody had ever looked at.

    Age sits beside every amount, because the ten-minute release sweep acts on
    it: a carrier at 110 minutes is about to have their float returned and their
    order re-offered, and operations should see that before the rider calls.
    """
    from services import cod_policy

    return await cod_policy.exposure_summary(db)


@router.get("/finance/summary", summary="Money in, money out, money stuck")
async def finance_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """The reconciliation view: three questions in one round trip.

    Collections that never resolved are the important row. A `pending` payment
    older than an hour means an STK push the customer either ignored or paid
    without the callback arriving — and the second case is a customer who has
    been charged for an order the platform does not think exists.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    async def _sum(model, amount_column, *where):
        query = select(func.coalesce(func.sum(amount_column), 0), func.count()).where(*where)
        row = (await db.execute(query.select_from(model))).one()
        return {"amount": _money(row[0]), "count": int(row[1] or 0)}

    by_type = (
        await db.execute(
            select(
                WalletTransaction.transaction_type,
                func.coalesce(func.sum(WalletTransaction.amount), 0),
                func.count(),
            )
            .where(
                WalletTransaction.created_at >= since,
                WalletTransaction.status == TransactionStatus.completed,
            )
            .group_by(WalletTransaction.transaction_type)
        )
    ).all()

    return {
        "window_days": days,
        "collections": {
            "paid": await _sum(Payment, Payment.amount, Payment.status == "paid", Payment.created_at >= since),
            "failed": await _sum(Payment, Payment.amount, Payment.status == "failed", Payment.created_at >= since),
            "refunded": await _sum(Payment, Payment.amount, Payment.status == "refunded", Payment.created_at >= since),
            # Money the platform may or may not have. This is the number to
            # chase, not the headline revenue.
            "unresolved": await _sum(
                Payment, Payment.amount, Payment.status == "pending", Payment.created_at < hour_ago
            ),
        },
        "payouts": {
            "pending": await _sum(Payout, Payout.amount, Payout.status == "pending"),
            "processing": await _sum(Payout, Payout.amount, Payout.status == "processing"),
            "stuck": await _sum(
                Payout, Payout.amount, Payout.status == "processing", Payout.created_at < day_ago
            ),
            "completed": await _sum(
                Payout, Payout.amount, Payout.status == "completed", Payout.created_at >= since
            ),
            "failed": await _sum(
                Payout, Payout.amount, Payout.status == "failed", Payout.created_at >= since
            ),
        },
        "ledger": [
            {
                "transaction_type": getattr(row[0], "value", row[0]),
                "amount": _money(row[1]),
                "count": int(row[2] or 0),
            }
            for row in by_type
        ],
    }


@router.get("/finance/payments", summary="M-Pesa collections")
@limiter.limit("120/minute")
async def list_payments(
    request: Request,
    status: Optional[str] = None,
    search: Optional[str] = Query(None, max_length=120),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(Payment)
        .where(Payment.created_at >= since)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Payment.status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.where(
            or_(
                Payment.mpesa_receipt.ilike(like),
                Payment.checkout_request_id.ilike(like),
                Payment.phone.ilike(like),
            )
        )

    rows = (await db.execute(query)).scalars().all()
    now = datetime.now(timezone.utc)

    return {
        "items": [
            {
                "id": str(row.id),
                "order_id": str(row.order_id) if row.order_id else None,
                # Masked for everyone without `pii.view`, like every other phone
                # number in this console.
                "phone": row.phone if access.may(PERM_PII_VIEW) else _mask(row.phone, keep=3),
                "amount": _money(row.amount),
                "status": row.status,
                "mpesa_receipt": row.mpesa_receipt,
                "failure_reason": row.failure_reason,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "unresolved_for_minutes": (
                    int((now - row.created_at).total_seconds() // 60)
                    if row.status == "pending" and row.created_at
                    else None
                ),
            }
            for row in rows
        ]
    }


# ── Adjusting a balance ───────────────────────────────────────────────────


class AdjustmentRequest(BaseModel):
    """A manual credit or debit.

    `amount` is signed: negative debits. Explicit rather than an amount plus a
    direction dropdown, because a dropdown defaulted to "credit" is a mistake
    waiting to be made and the sign is unambiguous in the audit row.
    """

    amount: Decimal = Field(..., description="Signed. Negative debits the balance.")
    reason: str = Field(..., min_length=10, max_length=500)
    #: The exact current balance, as displayed. Refuses if it has moved.
    expected_balance: Optional[Decimal] = None


@router.post(
    "/finance/{user_type}s/{owner_id}/adjust",
    summary="Credit or debit a wallet by hand",
)
# The tightest limit in the console. There is no legitimate scripted use.
@limiter.limit("10/minute")
async def adjust_wallet(
    request: Request,
    user_type: Literal["customer", "rider", "vendor"],
    owner_id: UUID,
    body: AdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_ADJUST)),
):
    """Move a balance with no order behind it.

    This is the only endpoint on the platform that creates money from nothing,
    so it carries every guard that fits:

    * Its own capability, held by no preset except super admin. Approving a
      payout moves money the platform already owed; this creates the obligation.
    * A **ten-character** minimum reason. "fix" is not an explanation, and this
      row will be read a year later by somebody reconciling.
    * A ceiling per adjustment, refused rather than warned about — a credited
      balance that has been spent cannot be taken back.
    * An optimistic check against the balance the operator was looking at, so
      two people fixing the same complaint cannot both apply it.
    * The account holder is **told**. A silent balance change is indistinguishable
      from a bug to the person it happens to, and it generates the support ticket
      it was meant to close.

    It goes through `wallet_service.apply_wallet_delta`, which moves the balance
    and writes the ledger row as one operation — never one without the other.
    """
    amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))

    if amount == 0:
        raise HTTPException(status_code=400, detail="An adjustment of zero does nothing.")
    if abs(amount) > MAX_ADJUSTMENT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{abs(amount)} exceeds the {MAX_ADJUSTMENT} limit for a single "
                "adjustment. If that figure is right, split it and record why on "
                "each part."
            ),
        )

    model = OWNER_MODELS[user_type]
    owner = await db.get(model, owner_id, with_for_update=True)
    if owner is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    current = Decimal(str(owner.wallet_balance or 0)).quantize(Decimal("0.01"))

    if body.expected_balance is not None:
        expected = Decimal(str(body.expected_balance)).quantize(Decimal("0.01"))
        if expected != current:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The balance is now {current}, not the {expected} you were "
                    "shown. Someone else may have adjusted it, or an order settled. "
                    "Reload and check before applying this."
                ),
            )

    if current + amount < 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"That would take the balance to {current + amount}. Debiting an "
                "account into arrears through an adjustment hides a real debt in "
                "the wrong place — raise it against the order instead."
            ),
        )

    clerk_id = getattr(owner, "clerk_id", None)
    if not clerk_id:
        raise HTTPException(
            status_code=409,
            detail="That account has no Clerk identity, so its wallet cannot be moved.",
        )

    transaction = await wallet_service.apply_wallet_delta(
        db,
        owner=owner,
        clerk_id=clerk_id,
        user_type=user_type,
        amount=amount,
        transaction_type=TransactionType.refund if amount > 0 else TransactionType.commission_deduction,
        description=f"Manual adjustment by {access.email}: {body.reason}",
        status=TransactionStatus.completed,
    )

    admin_service.record_audit(
        db,
        access=access,
        action="finance.wallet_adjust",
        target_type=user_type,
        target_id=owner_id,
        before={"wallet_balance": str(current)},
        after={
            "wallet_balance": str(current + amount),
            "adjustment": str(amount),
            "transaction_id": str(transaction.id) if transaction else None,
        },
        reason=body.reason,
    )

    await create_notification(
        session=db,
        user_id=owner_id,
        user_type=user_type,
        title=(
            "Your Drop balance was credited"
            if amount > 0
            else "Your Drop balance was adjusted"
        ),
        message=(
            f"{'Credited' if amount > 0 else 'Debited'} KSH {abs(amount)}. {body.reason}"
        ),
        message_type="payment",
    )

    await db.commit()

    logger.info(
        "Wallet adjustment: %s %s %s by %s (%s)",
        user_type, owner_id, amount, access.email, body.reason,
    )

    return {
        "ok": True,
        "balance_before": str(current),
        "balance_after": str(current + amount),
        "adjustment": str(amount),
    }


@router.get(
    "/finance/{user_type}s/{owner_id}/ledger",
    summary="One account's balance history",
)
async def account_ledger(
    user_type: Literal["customer", "rider", "vendor"],
    owner_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Movements for one account, newest first.

    `WalletTransaction.user_id` holds the **Clerk id**, not the row's UUID —
    `wallet_service.record_wallet_movement` writes `user_id=clerk_id`. Filtering
    by the path's UUID would match nothing at all and quietly show every account
    an empty ledger, which reads as "no activity" rather than as a bug.

    Scoped on `user_type` as well, because the column holds ids from three
    tables and carries no foreign key.
    """
    model = OWNER_MODELS[user_type]
    owner = await db.get(model, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    clerk_id = getattr(owner, "clerk_id", None)
    if not clerk_id:
        return {"balance": _money(owner.wallet_balance), "items": []}

    rows = (
        await db.execute(
            select(WalletTransaction)
            .where(
                WalletTransaction.user_id == clerk_id,
                WalletTransaction.user_type == user_type,
            )
            .order_by(WalletTransaction.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "balance": _money(owner.wallet_balance),
        "items": [
            {
                "id": str(row.id),
                "transaction_type": getattr(row.transaction_type, "value", row.transaction_type),
                "amount": _money(row.amount),
                "status": getattr(row.status, "value", row.status),
                "description": row.description,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ── Payment-callback reconciliation ───────────────────────────────────────
#
# `failed_webhooks` had no reader. A failed M-Pesa callback meant the customer
# had paid Safaricom while the order stayed `pending`, and nothing on the
# platform could say so. See `services/admin_reconciliation_service.py` for why
# there is deliberately no replay action.


@router.get("/reconciliation/webhooks", summary="Payment callbacks that failed")
@limiter.limit("60/minute")
async def failed_webhooks(
    request: Request,
    resolved: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    items = await admin_reconciliation_service.list_failures(
        db, resolved=resolved, limit=limit
    )
    return {
        "items": items,
        "summary": await admin_reconciliation_service.summary(db),
    }


class ResolveWebhook(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


@router.post("/reconciliation/webhooks/{webhook_id}/resolve", summary="Mark one handled")
async def resolve_failed_webhook(
    webhook_id: str,
    body: ResolveWebhook,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    """Record that a human dealt with this entry.

    A reason is mandatory and not decoration: the next person needs to know
    whether this was settled in the M-Pesa portal, refunded, or dismissed as a
    duplicate. Marking it resolved with no explanation is indistinguishable from
    hiding it.

    It moves no money — the administrator does that through the ordinary
    single-path tools, and this is the note saying they did.
    """
    row = await admin_reconciliation_service.resolve(db, webhook_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such entry.")

    admin_service.record_audit(
        db,
        access=access,
        action="finance.webhook_resolve",
        target_type="failed_webhook",
        target_id=webhook_id,
        before={"resolved": False},
        after={"resolved": True, "reason": body.reason.strip()},
    )
    await db.commit()

    return {"id": webhook_id, "resolved": True}


# ── Settlement: refunds, payouts and cash exposure ────────────────────────
#
# Three things that move money without a person pressing anything, none of
# which had a reader. See `services/admin_settlement_service.py` — in
# particular for why a failed payout with no matching wallet refund is the one
# figure on this screen that means money has actually vanished.


@router.get("/settlement", summary="Refunds, payouts and cash at risk")
@limiter.limit("60/minute")
async def settlement(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_READ)),
):
    return {
        "refunds": await admin_settlement_service.refunds(db, limit=limit),
        "payouts": await admin_settlement_service.payouts(db, limit=limit),
        "cash": await admin_settlement_service.cash_exposure(db),
    }


class SettleRefund(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


@router.post("/settlement/refunds/{order_id}/settle", summary="Record a refund made by hand")
async def settle_refund(
    order_id: UUID,
    body: SettleRefund,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_FINANCE_REFUND_APPROVE)),
):
    """Mark a stuck or failed refund as settled outside the platform.

    Deliberately **not** a retry. `refund_service` initiates an M-Pesa reversal,
    and a reversal that in fact succeeded but lost its callback looks identical
    to one that failed — retrying that pays the customer twice out of the
    platform's own money, with no way to claw it back. The same reasoning as the
    webhook screen: the administrator settles it in the M-Pesa portal, and this
    is the note saying they did.

    Requires `finance.refund_approve` rather than `finance.read`, because the
    row stops being visible to anyone the moment it is marked settled.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="No such order.")
    if order.payment_status not in ("refund_pending", "refund_processing", "refund_failed"):
        raise HTTPException(
            status_code=409,
            detail=f"This order is '{order.payment_status}' and has no outstanding refund.",
        )

    before = order.payment_status
    order.payment_status = "refunded"

    admin_service.record_audit(
        db,
        access=access,
        action="finance.refund_settle",
        target_type="order",
        target_id=str(order_id),
        before={"payment_status": before},
        after={
            "payment_status": "refunded",
            "amount": _money(order.total_amount),
            "reason": body.reason.strip(),
        },
    )
    await db.commit()

    return {"order_id": str(order_id), "payment_status": "refunded"}
