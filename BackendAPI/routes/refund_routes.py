"""
Refund Routes
─────────────
Admin endpoint to trigger batch refund processing,
plus Safaricom M-Pesa Reversal callback handlers.
"""

import logging
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from services.refund_service import process_all_pending_refunds
from services.payment_service import reject_mpesa_callback

logger = logging.getLogger(__name__)

router = APIRouter()

import os


@router.post("/process-refunds")
async def trigger_refund_processing(
    session: AsyncSession = Depends(get_db),
    admin_id: str = Depends(get_current_user),
):
    """
    Process all orders with payment_status = 'refund_pending'.
    Initiates M-Pesa Reversals for each and updates their status.
    SEC-06 FIX: Protected by admin guard — only admin Clerk IDs may trigger batch refunds.
    """
    clerk_id = admin_id["sub"]
    allowed_ids = os.getenv("ADMIN_CLERK_IDS", "").split(",")
    if clerk_id not in [aid.strip() for aid in allowed_ids if aid.strip()]:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Unauthorized. Admin access required.")
    result = await process_all_pending_refunds(session)
    return result


# ── M-Pesa Reversal Callback Endpoints ─────────────────────────────────────────

@router.post("/mpesa/reversal_result")
async def reversal_result_callback(request: Request, session: AsyncSession = Depends(get_db), secret: str | None = Query(default=None)):
    """
    Safaricom Reversal Result callback.
    Updates the order payment_status to 'refunded' or 'refund_failed'.
    """
    rejected = reject_mpesa_callback(request, secret, "Reversal result callback")
    if rejected:
        return rejected

    try:
        data = await request.json()
        result = data.get("Result", {})
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc", "")
        conversation_id = result.get("ConversationID")

        if not conversation_id:
            logger.error("Reversal result callback missing ConversationID")
            return JSONResponse(status_code=400, content={"message": "Missing ConversationID"})

        # EDGE-04 FIX: Find the exact Payment record using reversal_conversation_id
        from sqlalchemy.future import select
        from models.order_model import Order
        from models.payment_model import Payment

        pay_stmt = select(Payment).where(Payment.reversal_conversation_id == conversation_id)
        pay_result = await session.execute(pay_stmt)
        matched_payment = pay_result.scalars().first()

        if not matched_payment:
            logger.warning(f"Reversal result: No matching payment found for ConversationID {conversation_id}")
            return {"message": "No matching payment found"}

        order_stmt = select(Order).where(Order.id == matched_payment.order_id)
        order_result = await session.execute(order_stmt)
        matched_order = order_result.scalars().first()

        if not matched_order:
            logger.error(f"Reversal result: Found payment but missing Order ID {matched_payment.order_id}")
            return {"message": "Matching order not found"}

        if result_code == 0:
            matched_order.payment_status = "refunded"
            matched_payment.status = "refunded"

            # Notify customer about successful refund
            try:
                from services.notification_service import create_notification, queue_push
                from models.user_model import User

                customer = await session.get(User, matched_order.customer_id)
                if customer:
                    title = "Refund Complete ✅"
                    body = f"KSH {matched_payment.amount} has been refunded to your M-Pesa."
                    action_url = "/(screens)/Orders"
                    await create_notification(
                        session=session,
                        user_id=customer.id,
                        user_type="customer",
                        title=title,
                        message=body,
                        message_type="refund_update",
                        action_url=action_url,
                        related_order_id=matched_order.id,
                    )
                    # `session`, not `db` — this handler's session parameter is
                    # named `session`. The old `db` raised NameError straight
                    # into the except below, so "Refund Complete" was written to
                    # the notification table but never actually pushed.
                    queue_push(session, to=customer.push_token, title=title, body=body,
                               data={"url": action_url})
            except Exception as e:
                logger.error(f"Refund success notification error: {e}")

            logger.info(f"Reversal completed for order {matched_order.id}")
        else:
            matched_order.payment_status = "refund_failed"
            matched_payment.status = "refund_failed"
            logger.warning(f"Reversal failed for order {matched_order.id}: {result_desc}")

        await session.commit()
        return {"message": "Reversal result processed"}

    except Exception as e:
        logger.error(f"Error processing reversal result callback: {e}")
        return JSONResponse(status_code=500, content={"message": "Processing error"})


@router.post("/mpesa/reversal_timeout")
async def reversal_timeout_callback(request: Request, session: AsyncSession = Depends(get_db), secret: str | None = Query(default=None)):
    """
    Safaricom Reversal Timeout callback.
    Marks the refund as failed due to timeout for targeted retry.
    """
    rejected = reject_mpesa_callback(request, secret, "Reversal timeout callback")
    if rejected:
        return rejected

    try:
        data = await request.json()
        logger.warning(f"Reversal timeout received: {data}")

        # Extract ConversationID to scope the timeout to a specific order
        conversation_id = data.get("Result", {}).get("ConversationID")

        if not conversation_id:
            return JSONResponse(status_code=400, content={"message": "Missing ConversationID"})

        # EDGE-04 FIX: Find only the specific timed-out order back to refund_pending for retry
        from sqlalchemy.future import select
        from models.order_model import Order
        from models.payment_model import Payment

        pay_stmt = select(Payment).where(Payment.reversal_conversation_id == conversation_id)
        pay_result = await session.execute(pay_stmt)
        payment = pay_result.scalars().first()

        if payment and payment.status == "refund_processing":
            payment.status = "refund_pending"  # Allow retry
            
            order = await session.get(Order, payment.order_id)
            if order and order.payment_status == "refund_processing":
                order.payment_status = "refund_pending"
                
            await session.commit()
            logger.info(f"Reversal timeout: Order {payment.order_id} queued for retry")
            return {"message": "Timeout processed, refund queued for retry"}

        return {"message": "Timeout processed, no matching active refund found"}

    except Exception as e:
        logger.error(f"Error processing reversal timeout callback: {e}")
        return JSONResponse(status_code=500, content={"message": "Processing error"})
