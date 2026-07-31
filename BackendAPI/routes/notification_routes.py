from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from services.notification_service import get_notifications, mark_notification_read, mark_all_read, get_unread_count, delete_notification
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class NotificationReadRequest(BaseModel):
    notification_id: str


@router.get("")
@router.get("/", include_in_schema=False)
async def list_notifications(
    user_type: str = "customer",
    # Bounded deliberately: these were unvalidated, so `?limit=1000000` asked the
    # database for every notification a user has ever had, and a negative `skip`
    # made asyncpg raise, surfacing as a 500.
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    clerk_id = user["sub"]
    return await get_notifications(session=db, clerk_id=clerk_id, user_type=user_type, skip=skip, limit=limit)


@router.get("/unread-count")
async def unread_count(
    user_type: str = "customer",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    clerk_id = user["sub"]
    count = await get_unread_count(session=db, clerk_id=clerk_id, user_type=user_type)
    return {"unread_count": count}


@router.post("/read")
async def read_notification(
    body: NotificationReadRequest,
    user_type: Optional[str] = "customer",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    clerk_id = user["sub"]
    return await mark_notification_read(session=db, clerk_id=clerk_id, notification_id=body.notification_id, user_type=user_type)


@router.post("/read-all")
async def read_all_notifications(
    user_type: Optional[str] = "customer",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    clerk_id = user["sub"]
    return await mark_all_read(session=db, clerk_id=clerk_id, user_type=user_type)


@router.delete("/{notification_id}")
async def delete_notif(
    notification_id: str,
    user_type: str = "customer",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    clerk_id = user["sub"]
    return await delete_notification(session=db, clerk_id=clerk_id, notification_id=notification_id, user_type=user_type)
