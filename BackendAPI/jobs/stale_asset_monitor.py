import asyncio
import logging
from sqlalchemy import select, and_, func
from sqlalchemy.sql.expression import text
from dependencies.dependencies import get_db_session
from models.user_model import User
from services.notification_service import queue_push
from services.notification_service import create_notification

logger = logging.getLogger(__name__)

#: A customer holding a deposit-bearing bottle this long without ordering has
#: stopped using the platform, and the bottle is a real asset sitting in their
#: kitchen. Long enough not to nag someone who is simply on holiday.
STALE_AFTER_DAYS = 21


async def run_stale_asset_monitor():
    """Nudge customers who are still holding a bottle the platform paid for.

    This job read `User.empty_bottles_held`, a column migration `3ba669eb21f3`
    had already dropped. It therefore raised `AttributeError` on every run — not
    "matched nothing", which is how it looked from the outside: it had never
    sent a single message and never could. It now reads `bottles_held`, which
    `customer_bottle_service` maintains in lockstep with the deposit balance.
    """
    logger.info("Running stale asset monitor...")

    async with get_db_session() as session:
        query = select(User).where(
            and_(
                User.bottles_held > 0,
                User.last_order_date != None,
                func.now() - User.last_order_date
                > text("make_interval(days => :stale_days)").bindparams(
                    stale_days=STALE_AFTER_DAYS
                ),
            )
        )
        result = await session.execute(query)
        stale_users = result.scalars().all()

        for user in stale_users:
            logger.info(
                "Flagging stale asset for user %s (%s) holding %s bottle(s) on a KSH %s deposit.",
                user.id, user.full_name, user.bottles_held, user.bottle_deposit_balance,
            )
            title = "We Miss You! 🚰"
            body = f"Hi {user.full_name}, it's been a while! Ready for a refill? Or would you like us to pick up your empty bottles?"
            
            await create_notification(
                session=session,
                user_id=user.id,
                user_type="customer",
                title=title,
                message=body,
                message_type="system_alert",
                action_url="/(screens)/index"
            )
            
            queue_push(session, to=user.push_token, title=title, body=body)
        
        await session.commit()
    logger.info(f"Stale asset monitor finished. Flagged {len(stale_users)} users.")

if __name__ == "__main__":
    asyncio.run(run_stale_asset_monitor())
