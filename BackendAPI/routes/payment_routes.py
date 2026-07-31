"""Customer-facing payment history.

The customer app has always had a Payment History screen pointed at
`GET /api/payments/history`, but the endpoint did not exist — every visit was a
404. This is the missing half of that contract.

Distinct from `/api/wallet/transactions`: that is the wallet ledger (top-ups,
withdrawals, credit applied), this is the record of what was charged for orders.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from dependencies.auth_dependencies import get_current_customer
from dependencies.dependencies import get_db
from models.order_model import Order
from models.payment_model import Payment
from models.vendor_model import Vendor
from services.user_service import get_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/history")
async def payment_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer),
):
    """Every payment attempt against this customer's orders, newest first.

    Scoped by a join on `Orders.customer_id`, so one customer can never read
    another's payment records.
    """
    db_user = await get_user(session=db, clerk_id=user["sub"])
    if not db_user:
        raise HTTPException(status_code=403, detail="Customer profile not found.")

    stmt = (
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(Order.customer_id == db_user.id)
        .options(joinedload(Order.vendor))
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).unique().all()

    # Cash-on-delivery orders never produce a Payment row, so surface them too —
    # otherwise the screen silently omits a real transaction the customer made.
    cash_stmt = (
        select(Order)
        .where(
            Order.customer_id == db_user.id,
            Order.payment_method == "cash",
        )
        .options(joinedload(Order.vendor))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    cash_orders = (await db.execute(cash_stmt)).unique().scalars().all()

    def _vendor_name(vendor: Vendor | None) -> str | None:
        return vendor.business_name if vendor is not None else None

    entries = [
        {
            "id": str(payment.id),
            "order_id": str(order.id),
            "order_reference": str(order.id)[:8].upper(),
            "vendor_name": _vendor_name(order.vendor),
            "amount": float(payment.amount or 0),
            "status": payment.status,
            "payment_method": order.payment_method or "mpesa",
            "mpesa_receipt": payment.mpesa_receipt,
            "failure_reason": payment.failure_reason,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
        }
        for payment, order in rows
    ]

    entries.extend(
        {
            "id": f"cash-{order.id}",
            "order_id": str(order.id),
            "order_reference": str(order.id)[:8].upper(),
            "vendor_name": _vendor_name(order.vendor),
            "amount": float(order.total_amount or 0),
            "status": "paid" if order.order_status == "delivered" else "pending",
            "payment_method": "cash",
            "mpesa_receipt": None,
            "failure_reason": None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order in cash_orders
    )

    entries.sort(key=lambda e: e["created_at"] or "", reverse=True)
    return entries[:limit]
