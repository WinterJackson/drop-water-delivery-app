"""Customer-facing payment history.

The customer app has always had a Payment History screen pointed at
`GET /api/payments/history`, but the endpoint did not exist — every visit was a
404. This is the missing half of that contract.

Distinct from `/api/wallet/transactions`: that is the wallet ledger (top-ups,
withdrawals, credit applied), this is the record of what was charged for orders.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, case, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth_dependencies import get_current_customer
from dependencies.dependencies import get_db
from models.order_model import Order
from models.payment_model import Payment
from models.vendor_model import Vendor
from services.user_service import get_user
from utils.money import money_str
from utils.paging import stable

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/history")
async def payment_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer),
):
    """One page of every payment against this customer's orders, newest first.

    Scoped by a join on `Orders.customer_id`, so one customer can never read
    another's payment records.

    A cash-on-delivery order never produces a `payments` row, so the history is
    two kinds of event and has to be **one** query. It used to be two, merged in
    Python: the M-Pesa half was paged, the cash half took `limit` rows with no
    offset, and the merged list was cut back to `limit` at the end. Every page
    therefore repeated the same newest cash orders, and each cut silently
    discarded up to `limit` real M-Pesa payments that offset would never come
    back for. It was invisible while the app only ever asked for page 1.

    Unioned, both halves share one ordering and one window, so a row appears on
    exactly one page and nothing is dropped.
    """
    db_user = await get_user(session=db, clerk_id=user["sub"])
    if not db_user:
        raise HTTPException(status_code=403, detail="Customer profile not found.")

    mpesa = (
        select(
            cast(Payment.id, String).label("row_id"),
            Order.id.label("order_id"),
            Payment.amount.label("amount"),
            Payment.status.label("status"),
            func.coalesce(Order.payment_method, literal("mpesa")).label("payment_method"),
            Payment.mpesa_receipt.label("mpesa_receipt"),
            Payment.failure_reason.label("failure_reason"),
            Payment.created_at.label("created_at"),
            Vendor.business_name.label("vendor_name"),
        )
        .join(Order, Payment.order_id == Order.id)
        .outerjoin(Vendor, Order.vendor_id == Vendor.id)
        .where(Order.customer_id == db_user.id)
    )

    cash = (
        select(
            ("cash-" + cast(Order.id, String)).label("row_id"),
            Order.id.label("order_id"),
            Order.total_amount.label("amount"),
            case(
                (Order.order_status == "delivered", literal("paid")),
                else_=literal("pending"),
            ).label("status"),
            literal("cash").label("payment_method"),
            literal(None, type_=String).label("mpesa_receipt"),
            literal(None, type_=String).label("failure_reason"),
            Order.created_at.label("created_at"),
            Vendor.business_name.label("vendor_name"),
        )
        .outerjoin(Vendor, Order.vendor_id == Vendor.id)
        .where(
            Order.customer_id == db_user.id,
            Order.payment_method == "cash",
            # Disjoint by construction, not by convention. Today an order's
            # `payment_method` is written once at creation and never reassigned,
            # so a cash order has no `payments` row and the two halves cannot
            # overlap. That is a property of code elsewhere, and this is the
            # screen a customer opens to find the receipt for a disputed order:
            # an entry appearing twice reads as having been charged twice.
            ~select(Payment.id).where(Payment.order_id == Order.id).exists(),
        )
    )

    history = union_all(mpesa, cash).subquery()
    rows = (
        await db.execute(
            select(history)
            # `row_id` is unique across both halves — a payment id and a
            # "cash-<order id>" can never collide — so it is a valid tiebreaker
            # even though it is not a table's primary key.
            .order_by(*stable(history.c.created_at.desc(), key=history.c.row_id))
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return [
        {
            "id": row.row_id,
            "order_id": str(row.order_id),
            "order_reference": str(row.order_id)[:8].upper(),
            "vendor_name": row.vendor_name,
            "amount": money_str(row.amount),
            "status": row.status,
            "payment_method": row.payment_method,
            "mpesa_receipt": row.mpesa_receipt,
            "failure_reason": row.failure_reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
