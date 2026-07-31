import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from dependencies.dependencies import get_db_session
from models.bottle_rejection_model import BottleRejectionTicket, RejectionStatus
from models.order_model import Order
from services.vendor_management_service import _restore_order_stock
from routes.websocket_routes import manager

logger = logging.getLogger(__name__)

async def run_auto_resolve_bottle_rejections(batch_size: int = 100):
    """Cronjob: auto-approve any bottle-rejection ticket still PENDING_REVIEW after 3 minutes.

    Safe to run from several worker instances simultaneously:
      * `FOR UPDATE SKIP LOCKED` gives each instance a disjoint batch, so an order
        can never be cancelled — and its stock restored — twice.
      * each ticket is handled in its own try/except, so one bad row no longer
        aborts the sweep for every ticket behind it (the commit used to sit
        outside the loop, so a single exception discarded the whole batch).
    """
    logger.info("Running bottle-rejection timeout sweep...")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)

    async with get_db_session() as session:
        query = (
            select(BottleRejectionTicket)
            .where(
                and_(
                    BottleRejectionTicket.status == RejectionStatus.PENDING_REVIEW,
                    BottleRejectionTicket.created_at <= cutoff,
                )
            )
            .order_by(BottleRejectionTicket.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        stale_tickets = (await session.execute(query)).scalars().all()
        if not stale_tickets:
            return

        resolved = 0
        broadcasts: list[dict] = []

        for rejection in stale_tickets:
            try:
                # Re-check under the lock: another instance may have resolved this
                # ticket between our SELECT and now.
                if rejection.status != RejectionStatus.PENDING_REVIEW:
                    continue

                rejection.status = RejectionStatus.APPROVED
                rejection.admin_notes = "Auto-approved due to timeout. Order cancelled."

                order = await session.get(Order, rejection.order_id)
                if order and order.order_status == "pending_review":
                    order.order_status = "cancelled"
                    order.cancellation_reason = "bottle_rejection_timeout"
                    if order.payment_status == "paid":
                        order.payment_status = "refund_pending"
                        order.commission_lost = order.platform_total
                    await _restore_order_stock(session, order)

                    broadcasts.append({
                        "vendor_id": str(order.vendor_id),
                        "customer_id": str(order.customer_id),
                        "deliverer_id": str(order.deliverer_id) if order.deliverer_id else "",
                        "payload": {
                            "action": "ORDER_STATUS_UPDATE",
                            "order_id": str(order.id),
                            "status": "cancelled",
                            "message": "Order cancelled because your empty bottle did not pass inspection.",
                        },
                    })

                await session.commit()
                resolved += 1
            except Exception as e:
                logger.error(
                    "Failed to auto-resolve bottle-rejection ticket %s: %s", rejection.id, e, exc_info=True
                )
                await session.rollback()

        # Broadcast only what actually committed.
        for message in broadcasts:
            try:
                await manager.broadcast_order_update(**message)
            except Exception as e:
                logger.error(f"WS broadcast fail in bottle-rejection sweep: {e}")

        logger.info("Auto-resolved %s stale bottle-rejection ticket(s).", resolved)
