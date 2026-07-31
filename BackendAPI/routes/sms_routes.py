import hmac
import logging
import os

from fastapi import APIRouter, Form, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.future import select

from db.session import AsyncSessionLocal
from models.deliverer_model import Deliverer
from models.order_model import Order

logger = logging.getLogger(__name__)

router = APIRouter()

from core.redis_client import redis_limiter as limiter

#: Shared secret configured on the SMS provider's webhook. Without it this
#: endpoint is world-writable, and it completes deliveries — which credits the
#: vendor, settles the rider's float and closes the customer's order. The sender
#: phone number is not authentication: it travels in the request body and anyone
#: can type a rider's number into it.
SMS_WEBHOOK_SECRET = os.getenv("SMS_WEBHOOK_SECRET")


@router.post("/webhook")
@limiter.limit("5/minute")
async def process_sms_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Parses incoming SMS payloads from telecommunication hooks.
    Format expected: "DELIVERED <order_id_first_8_chars>"
    """
    # Fail closed. An unset secret in production would leave delivery completion
    # open to anyone who can reach the URL.
    if not SMS_WEBHOOK_SECRET:
        if os.getenv("ENV", "development") != "development":
            logger.error("SMS webhook called but SMS_WEBHOOK_SECRET is not configured")
            return JSONResponse(status_code=503, content={"message": "Webhook not configured"})
    elif not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, SMS_WEBHOOK_SECRET):
        logger.warning("SMS webhook rejected: bad or missing shared secret")
        return JSONResponse(status_code=403, content={"message": "Forbidden"})

    logger.info(f"Received SMS Webhook from {From}: {Body}")
    body_clean = Body.strip().upper()
    
    if not body_clean.startswith("DELIVERED"):
        return {"status": "ignored", "message": "unrecognized command"}
    
    parts = body_clean.split()
    if len(parts) < 2:
        return {"status": "error", "message": "invalid format"}
        
    order_suffix = parts[1].lower()
    
    # Open isolated database session natively specifically for external webhooks
    async with AsyncSessionLocal() as session:
        # Match Deliverer globally based on generic phone suffix bounds preventing country code clashes
        # Anchor on the suffix. `LIKE %digits%` can match a different rider whose
        # number merely contains these digits, and `.first()` would then pick one
        # arbitrarily — completing a stranger's delivery.
        phone_suffix = From[-9:]
        stmt = select(Deliverer).where(Deliverer.phone_number.like(f"%{phone_suffix}"))
        result = await session.execute(stmt)
        matches = result.scalars().all()
        if len(matches) > 1:
            logger.error("SMS webhook: phone suffix %s matched %d riders; refusing", phone_suffix, len(matches))
            return {"status": "error", "message": "ambiguous sender"}
        deliverer = matches[0] if matches else None
        
        if not deliverer:
            logger.warning(f"SMS Webhook: Unrecognized deliverer phone {From}")
            return {"status": "error", "message": "unauthorized sender"}

        # BUG-SMS-02 FIX: Match active string identifiers on order UUIDs utilizing text() for correct index usage
        from sqlalchemy import text
        stmt_order = select(Order).where(
            Order.deliverer_id == deliverer.id,
            Order.order_status == "picked_up",
            text("CAST(id AS TEXT) LIKE :prefix")
        ).params(prefix=f"{order_suffix}%")
        result_order = await session.execute(stmt_order)
        order = result_order.scalars().first()
        
        if not order:
            logger.warning(f"SMS Webhook: Unrecognized order {order_suffix} for {deliverer.name}")
            return {"status": "error", "message": "order not found"}
            
        # BUG-SMS-01 FIX: Apply validate_status_transition state machine guard
        from services.order_service import validate_status_transition
        if not validate_status_transition(order.order_status, "delivered"):
            logger.warning(f"SMS Webhook: Invalid state transition for {order.id} from {order.order_status} to delivered")
            return {"status": "error", "message": "invalid state transition"}

        order.order_status = "delivered"
        await session.commit()
        
        # Broadcast real-time order status update via WebSocket for SMS completion
        try:
            from routes.websocket_routes import manager
            await manager.broadcast_order_update(
                vendor_id=str(order.vendor_id),
                customer_id=str(order.customer_id),
                deliverer_id=str(order.deliverer_id) if order.deliverer_id else "",
                payload={"action": "ORDER_STATUS_UPDATE", "order_id": str(order.id), "status": "delivered"}
            )
        except Exception as e:
            logger.error(f"WS Broadcast fail in SMS webhook: {e}")
        
        logger.info(f"SMS Webhook: Order {order.id} delivered via pure GSM fallback logic successfully!")
        
        return {"status": "success", "message": f"Order {order_suffix} marked as delivered"}
