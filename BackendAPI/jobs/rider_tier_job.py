import asyncio
import logging
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
from db.session import AsyncSessionLocal
from models.deliverer_model import Deliverer
from models.order_model import Order

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def evaluate_platinum_riders():
    """
    Cron job to evaluate if a gig rider qualifies for Platinum status, which
    lowers their commission to `gig_platinum_rider_commission_rate`.

    Both halves of the rule are rows in `Platform_Settings`:
    `platinum_min_deliveries` completed deliveries inside the trailing
    `platinum_window_days`. They were literals here — `>= 20` over `days=7` —
    while the *reward* was already editable from the console, so the business
    could change what qualifying paid and not what it took. The rider app stated
    the threshold as a literal of its own, which is how the two drift.
    """
    from services import platform_config_service as config

    logger.info("Starting Platinum Rider evaluation...")

    async with AsyncSessionLocal() as session:
        await config.ensure_fresh(session)
        minimum = config.get_int("platinum_min_deliveries")
        window_days = config.get_int("platinum_window_days")

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        # Get all gig economy riders
        riders_result = await session.execute(
            select(Deliverer).where(Deliverer.employment_model == "gig_economy")
        )
        riders = riders_result.scalars().all()
        
        platinum_count = 0
        demoted_count = 0
        
        for rider in riders:
            # Count delivered orders inside the configured window
            order_count_result = await session.execute(
                select(func.count(Order.id)).where(
                    and_(
                        Order.deliverer_id == rider.id,
                        Order.order_status == "delivered",
                        Order.updated_at >= cutoff
                    )
                )
            )
            order_count = order_count_result.scalar() or 0
            
            if order_count >= minimum:
                if not rider.is_platinum:
                    rider.is_platinum = True
                    platinum_count += 1
            else:
                if rider.is_platinum:
                    rider.is_platinum = False
                    demoted_count += 1
                    
        await session.commit()
        
    logger.info(
        "Evaluation complete (%d+ deliveries in %d days). Promoted %d, demoted %d.",
        minimum, window_days, platinum_count, demoted_count,
    )

if __name__ == "__main__":
    asyncio.run(evaluate_platinum_riders())
