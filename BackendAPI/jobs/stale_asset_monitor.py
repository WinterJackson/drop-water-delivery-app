import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.sql.expression import text
from dependencies.dependencies import get_db_session
from models.user_model import User
from services.notification_service import queue_push
from services.notification_service import create_notification

logger = logging.getLogger(__name__)

async def run_stale_asset_monitor():
    """
    Cronjob to flag users who have unreturned empty bottles for over 21 days.
    """
    logger.info("Running stale asset monitor...")
    
    async with get_db_session() as session:
        # Find users with empty bottles strictly > 0 and last_order_date > 21 days
        query = select(User).where(
            and_(
                User.empty_bottles_held > 0,
                User.last_order_date != None,
                func.now() - User.last_order_date > text("INTERVAL '21 days'")
            )
        )
        result = await session.execute(query)
        stale_users = result.scalars().all()
        
        for user in stale_users:
            logger.info(f"Flagging stale asset for user {user.id} ({user.full_name}) holding {user.empty_bottles_held} bottles.")
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
