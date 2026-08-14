import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db_session
from models.cart_model import Cart
from models.user_model import User
from models.vendor_model import Vendor
from services.expo_push_service import send_push_message, dispatch_background
from services.notification_service import create_notification
from services.order_service import apply_status_transition, revert_order_side_effects
from services import platform_config_service
from routes.websocket_routes import manager
from sqlalchemy import select, and_, update
from models.order_model import Order, OrderItem
from models.product_model import Product

logger = logging.getLogger(__name__)

async def _release_customer_cart(session: AsyncSession, customer_id):
    """Unlock the cart left locked by an abandoned checkout.

    `mpesa_payment` locks the cart for the STK window and only deletes it once
    payment settles. If the customer simply ignores the M-Pesa prompt, no callback
    ever arrives — so without this the cart stays locked forever and every
    add/remove/quantity change returns 409 for the rest of that account's life.
    """
    result = await session.execute(select(Cart).where(Cart.customer_id == customer_id))
    cart = result.scalars().first()
    if cart is not None and cart.is_locked:
        cart.is_locked = False
        logger.info("Released locked cart %s after abandoned checkout.", cart.id)


async def run_auto_cancel_orders(batch_size: int = 100):
    """Auto-cancel orders that have sat unclaimed past the acceptance SLA.

    Covers both `pending` (created but never paid) and `unassigned` (paid but
    never picked up by a vendor/rider). The status filter used to be `pending`
    only, which no live order ever reaches — `create_order` writes `unassigned` —
    so this sweep silently matched nothing. It also referenced `User` without
    importing it, so the first matching row would have raised `NameError`.

    The age comes from `order_auto_cancel_minutes` in `Platform_Settings`. It was
    a hardcoded `INTERVAL '15 minutes'` alongside an editable console field that
    was wired to nothing, so an owner giving vendors more time saw no change.

    Claims rows with FOR UPDATE SKIP LOCKED, and commits per order, so it is safe
    to run from multiple workers and one bad row cannot discard the batch.
    """
    logger.info("Running auto-cancel pending orders job...")

    async with get_db_session() as session:
        await platform_config_service.ensure_fresh(session)
        cutoff_minutes = platform_config_service.get_int("order_auto_cancel_minutes")

        # `created_at < cutoff`, not `now() - created_at > interval`.
        #
        # The two are arithmetically identical and only one is sargable. With the
        # column wrapped in an expression, Postgres can use
        # `ix_orders_status_created_at` for the status half and must then evaluate
        # the subtraction for every row that survives it. Standing the column alone
        # on one side lets the same index seek straight to the range, so the sweep
        # reads the handful of rows it will actually cancel instead of every live
        # order on the platform.
        #
        # The cutoff is computed here rather than in SQL for the same reason it is
        # `func.now()` elsewhere and not `datetime.now()`: this is a comparison
        # against a value the database supplies, and both sides must mean UTC. The
        # timezone is explicit so a container running in local time cannot shift it.
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cutoff_minutes)

        query = (
            select(Order)
            .where(
                and_(
                    Order.order_status.in_(["pending", "unassigned"]),
                    Order.created_at < cutoff,
                )
            )
            .order_by(Order.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(query)
        stale_orders = result.scalars().all()

        if not stale_orders:
            logger.info("No stale pending orders found.")
            return

        cancelled = 0
        broadcasts: list[dict] = []
        pushes: list[dict] = []

        for order in stale_orders:
            try:
                # Re-check under the lock — another worker may have just handled it.
                if order.order_status not in ("pending", "unassigned"):
                    continue

                logger.info(
                    "Auto-cancelling order %s due to SLA breach (%s minutes).",
                    order.id, cutoff_minutes,
                )

                was_paid = order.payment_status == "paid"
                apply_status_transition(order, "cancelled")

                await revert_order_side_effects(
                    session, order, reason="acceptance_sla_breach"
                )
                await _release_customer_cart(session, order.customer_id)

                # Notify Customer
                customer = await session.get(User, order.customer_id)
                if customer:
                    c_title = "Order Cancelled 🚫"
                    c_body = (
                        f"Your order #{str(order.id)[:8]} was cancelled because it was not accepted in time."
                        + (" Your payment will be refunded automatically." if was_paid else "")
                    )
                    c_action = f"/(screens)/OrderDetail/{order.id}"

                    await create_notification(
                        session=session, user_id=customer.id, user_type="customer",
                        title=c_title, message=c_body, message_type="order_update",
                        action_url=c_action, related_order_id=order.id
                    )
                    if customer.push_token:
                        pushes.append(dict(to=customer.push_token, title=c_title, body=c_body, data={"url": c_action}))

                # Notify Vendor
                vendor = await session.get(Vendor, order.vendor_id)
                if vendor:
                    v_title = "Order Missed SLA ⚠️"
                    v_body = f"Order #{str(order.id)[:8]} was auto-cancelled for missing the 15-minute acceptance window."
                    v_action = f"/(screens)/OrderDetail/{order.id}"

                    await create_notification(
                        session=session, user_id=vendor.id, user_type="vendor",
                        title=v_title, message=v_body, message_type="system_alert",
                        action_url=v_action, related_order_id=order.id
                    )
                    if vendor.push_token:
                        pushes.append(dict(to=vendor.push_token, title=v_title, body=v_body, data={"url": v_action}))

                broadcasts.append({
                    "vendor_id": str(order.vendor_id),
                    "customer_id": str(order.customer_id),
                    "deliverer_id": str(order.deliverer_id) if order.deliverer_id else "",
                    "payload": {"action": "ORDER_STATUS_UPDATE", "order_id": str(order.id), "status": "cancelled"},
                })

                await session.commit()
                cancelled += 1
            except Exception as e:
                logger.error("Failed to auto-cancel order %s: %s", order.id, e, exc_info=True)
                await session.rollback()

        # Only announce what actually committed.
        for message in broadcasts:
            try:
                await manager.broadcast_order_update(**message)
            except Exception as e:
                logger.error(f"WS Broadcast fail in auto_cancel_orders: {e}")

        for push in pushes:
            dispatch_background(send_push_message(**push))

    logger.info("Auto-cancel job finished. Cancelled %s order(s).", cancelled)

if __name__ == "__main__":
    asyncio.run(run_auto_cancel_orders())
