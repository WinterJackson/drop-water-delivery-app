"""The rider/store registry, and notification delivery.

Two read-only screens over data the platform already had and never showed.

`/fleet` is gated on `riders.read` — the registry is a rider-side relationship
and anyone allowed to look at riders may look at who they work for.

`/notifications` is gated on `analytics.read` and returns **no recipient
identity**: audience type, message type, channel, and the opening of the body.
Who was told what is a support question and belongs on the ticket, not on a
platform-wide feed that every analyst can read.
"""
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_ANALYTICS_READ, PERM_RIDERS_READ
from services import admin_fleet_service, admin_notification_service
from utils import keyset

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/fleet", summary="Who is registered to deliver for whom")
@limiter.limit("60/minute")
async def fleet(
    request: Request,
    status: str | None = Query(None, pattern="^(pending|approved|rejected|suspended)$"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(200, ge=1, le=400),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_RIDERS_READ)),
):
    """`VendorRiderRegistry` decides dispatch priority and had no admin reader.

    A store with no approved rider sends every order to the gig radar — slower,
    more commission, and nothing at all outside radar range. That count is the
    reason this screen exists.
    """
    return {
        "summary": await admin_fleet_service.summary(db),
        "vendors_without_riders": await admin_fleet_service.vendors_without_riders(db),
        "pending": await admin_fleet_service.pending_requests(db),
        "links": await admin_fleet_service.links(
            db, status=status, search=search, limit=limit, cursor=cursor
        ),
        "unattached": await admin_fleet_service.unattached_riders(db),
    }


@router.get("/notifications", summary="What the platform has been telling people")
@limiter.limit("60/minute")
async def notifications(
    request: Request,
    days: int = Query(30, ge=1, le=180),
    audience: str | None = Query(None, pattern="^(customer|rider|vendor)$"),
    search: str | None = Query(None, max_length=120),
    message_type: str | None = Query(None, max_length=60),
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """Volume, read rate and — the point of the screen — reachability.

    A `Notification` row is always written; the push needs a `push_token` and the
    recipient's own preference. An account with no token gets every row and no
    interruption, which is fine for a promotion and close to fatal for "your
    order has been assigned to you".
    """
    return {
        "summary": await admin_notification_service.summary(db, days=days),
        "reachability": await admin_notification_service.reachability(db),
        "by_type": await admin_notification_service.by_type(db, days=days),
        "by_audience": await admin_notification_service.by_audience(db, days=days),
        "by_channel": await admin_notification_service.by_channel(db, days=days),
        "recent": await admin_notification_service.recent(
            db,
            limit=limit,
            audience=audience,
            search=search,
            message_type=message_type,
            cursor=cursor,
        ),
    }
