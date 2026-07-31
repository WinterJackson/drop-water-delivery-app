"""
Refund Engine Service
─────────────────────
Processes M-Pesa reversals for cancelled orders with payment_status = 'refund_pending'.
Finds the original MpesaReceiptNumber from the payments table and initiates a Safaricom
Transaction Reversal to return funds to the customer.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
from models.order_model import Order
from models.payment_model import Payment
from services.payment_service import initiate_mpesa_reversal
from services.notification_service import create_notification, queue_push
from services.expo_push_service import send_push_message
from models.user_model import User
import asyncio

logger = logging.getLogger(__name__)


async def process_single_refund(session: AsyncSession, order: Order) -> dict:
    """
    Process a refund for a single order.
    
    1. Look up the original Payment record to get the MpesaReceiptNumber.
    2. Initiate M-Pesa Reversal API call.
    3. Update order payment_status to 'refunded' or 'refund_failed'.
    4. Notify the customer about the refund outcome.
    """
    order_id = str(order.id)

    # Find the original successful payment
    payment_stmt = select(Payment).where(
        and_(
            Payment.order_id == order.id,
            Payment.status == "paid",
            Payment.mpesa_receipt.isnot(None),
        )
    )
    result = await session.execute(payment_stmt)
    payment = result.scalars().first()

    if not payment or not payment.mpesa_receipt:
        logger.error(f"Refund: No valid payment receipt found for order {order_id}")
        order.payment_status = "refund_failed"
        await session.commit()
        return {
            "order_id": order_id,
            "status": "failed",
            "reason": "No M-Pesa receipt found for this order",
        }

    # Initiate the reversal
    reversal_result = await initiate_mpesa_reversal(
        transaction_id=payment.mpesa_receipt,
        amount=float(payment.amount),
    )

    if reversal_result.get("success"):
        order.payment_status = "refund_processing"
        payment.status = "refund_processing"
        payment.reversal_conversation_id = reversal_result.get("ConversationID")
        await session.commit()

        # Notify customer
        customer = await session.get(User, order.customer_id)
        if customer:
            title = "Refund Initiated 💸"
            body = f"A refund of KSH {payment.amount} is being processed for your cancelled order."
            action_url = "/(screens)/Orders"
            await create_notification(
                session=session,
                user_id=customer.id,
                user_type="customer",
                title=title,
                message=body,
                message_type="refund_update",
                action_url=action_url,
                related_order_id=order.id,
            )
            queue_push(session, to=customer.push_token, title=title, body=body,
                       data={"url": action_url})

        logger.info(f"Refund initiated for order {order_id}, receipt {payment.mpesa_receipt}")
        return {
            "order_id": order_id,
            "status": "processing",
            "conversation_id": reversal_result.get("ConversationID"),
        }
    else:
        error_reason = reversal_result.get("error", "Reversal API call failed")
        order.payment_status = "refund_failed"
        await session.commit()

        logger.error(f"Refund failed for order {order_id}: {error_reason}")
        return {
            "order_id": order_id,
            "status": "failed",
            "reason": error_reason,
        }


async def process_all_pending_refunds(session: AsyncSession, limit: int = 50) -> dict:
    """
    Batch-process all orders with payment_status = 'refund_pending'.
    Returns a summary of processed, succeeded, and failed refunds.

    `FOR UPDATE SKIP LOCKED` makes this safe to run from several worker
    instances at once: each claims a disjoint slice of the queue, so a reversal
    is never issued twice for the same order.
    """
    stmt = (
        select(Order)
        .where(Order.payment_status == "refund_pending")
        .order_by(Order.updated_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    pending_orders = result.scalars().all()

    if not pending_orders:
        return {"message": "No refunds pending", "processed": 0}

    results = []
    succeeded = 0
    failed = 0

    for order in pending_orders:
        try:
            refund_result = await process_single_refund(session, order)
            results.append(refund_result)
            if refund_result["status"] == "processing":
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Unexpected error processing refund for order {order.id}: {e}")
            results.append({
                "order_id": str(order.id),
                "status": "error",
                "reason": str(e),
            })
            failed += 1

    return {
        "message": f"Processed {len(pending_orders)} refunds",
        "processed": len(pending_orders),
        "succeeded": succeeded,
        "failed": failed,
        "details": results,
    }
