from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from sqlalchemy import select, desc, update
from models.notification_model import Notification
from models.user_model import User
from models.deliverer_model import Deliverer
import logging

logger = logging.getLogger(__name__)


# ── Notification preferences ─────────────────────────────────────────────
# Mirrors the server_default on User.preferences and the toggles rendered by
# the customer app's settings/NotificationPreferences screen.
DEFAULT_NOTIFICATION_PREFERENCES = {
    "order_updates": True,
    "promotions": False,
    "delivery_reminders": True,
    "analytics": True,
}

# Which toggle governs which message_type. Anything unmapped is treated as
# transactional and always delivered — a customer who silences promotions must
# still be told their payment failed.
_MESSAGE_TYPE_PREFERENCE = {
    "order_update": "order_updates",
    "order_updates": "order_updates",
    "order_assigned": "order_updates",
    "order_cancelled": "order_updates",
    "mismatch_resolved": "order_updates",
    "delivery_update": "delivery_reminders",
    "delivery_assigned": "delivery_reminders",
    "delivery_cancelled": "delivery_reminders",
    "promotion": "promotions",
    "promotions": "promotions",
    "offer": "promotions",
}


def push_allowed(recipient, message_type: str) -> bool:
    """
    Whether `recipient` has opted in to a push of this category.

    The settings screen has always written these toggles to User.preferences,
    but nothing read them, so switching "Promotions" off changed nothing. Call
    this alongside the `push_token` check at every push site; the in-app
    notification record is still written either way, so muting a category hides
    the interruption without losing the history.
    """
    if recipient is None:
        return False
    preferences = getattr(recipient, "preferences", None)
    if not isinstance(preferences, dict):
        preferences = {}

    key = _MESSAGE_TYPE_PREFERENCE.get(message_type)
    if key is None:
        return True  # transactional: payment, refund, KYC, account

    return bool(preferences.get(key, DEFAULT_NOTIFICATION_PREFERENCES.get(key, True)))


# Notifications are addressed by (user_id, user_type) because `user_id` holds
# ids from three different tables and carries no foreign key. Every read *and*
# write must therefore scope on both — filtering on `user_id` alone relies on
# UUIDs never colliding across tables, which is not a guarantee to build on.
VALID_USER_TYPES = ("customer", "vendor", "rider")


def _normalise_user_type(user_type: str | None) -> str:
    """Reject anything outside the known set rather than silently reading as a customer."""
    if user_type is None:
        return "customer"
    if user_type not in VALID_USER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"user_type must be one of {', '.join(VALID_USER_TYPES)}.",
        )
    return user_type


def _as_uuid(value) -> UUID:
    """Parse a notification id, 404-ing on a malformed one.

    Comparing a non-UUID string against a UUID column makes asyncpg raise, which
    surfaced as a 500 for what is really "no such notification".
    """
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Notification not found")


# ── NOTIF-09 FIX: User ID resolution per entity type ──────────────────────
async def _resolve_user_id(session: AsyncSession, clerk_id: str, user_type: str = "customer"):
    """Resolve database user ID from clerk_id based on entity type."""
    user_type = _normalise_user_type(user_type)
    if user_type == "vendor":
        # A staff member signs in with their own Clerk id against the same
        # store, so a vendor notification addressed to them must resolve to the
        # store row. Ordered `.first()`, never `scalar_one_or_none()`: an owner
        # may hold several stores and that raises on the second one.
        from services.vendor_management_service import get_vendor_by_clerk_id

        entity = await get_vendor_by_clerk_id(session, clerk_id)
    elif user_type == "rider":
        result = await session.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
        entity = result.scalar_one_or_none()
    else:
        result = await session.execute(select(User).where(User.clerk_id == clerk_id))
        entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(status_code=404, detail=f"{user_type.capitalize()} not found")
    return entity.id


async def get_notifications(session: AsyncSession, clerk_id: str, user_type: str = "customer", skip: int = 0, limit: int = 50):
    """Fetch notifications for any user type (customer, vendor, rider)."""
    user_id = await _resolve_user_id(session, clerk_id, user_type)
    query = (
        select(Notification)
        .where(Notification.user_id == user_id, Notification.user_type == user_type)
        .order_by(desc(Notification.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(query)
    notifications = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "title": n.title,
            "message": n.message,
            "message_type": n.message_type,
            "related_order_id": str(n.related_order_id) if n.related_order_id else None,
            "is_read": n.is_read,
            "delivered_via": n.delivered_via,
            "action_url": n.action_url,
            "data": n.data,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications
    ]


async def get_unread_count(session: AsyncSession, clerk_id: str, user_type: str = "customer") -> int:
    """Get count of unread notifications for badge display."""
    user_id = await _resolve_user_id(session, clerk_id, user_type)
    from sqlalchemy import func
    result = await session.execute(
        select(func.count(Notification.id))
        .where(Notification.user_id == user_id, Notification.user_type == user_type, ~Notification.is_read)
    )
    return result.scalar() or 0


async def mark_notification_read(session: AsyncSession, clerk_id: str, notification_id: str, user_type: str = "customer"):
    user_type = _normalise_user_type(user_type)
    user_id = await _resolve_user_id(session, clerk_id, user_type)
    result = await session.execute(
        select(Notification).where(
            Notification.id == _as_uuid(notification_id),
            Notification.user_id == user_id,
            Notification.user_type == user_type,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    await session.commit()
    return {"message": "Marked as read"}


async def mark_all_read(session: AsyncSession, clerk_id: str, user_type: str = "customer"):
    user_id = await _resolve_user_id(session, clerk_id, user_type)
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.user_type == user_type, ~Notification.is_read)
        .values(is_read=True)
    )
    await session.commit()
    return {"message": "Notifications marked as read"}

async def delete_notification(session: AsyncSession, clerk_id: str, notification_id: str, user_type: str = "customer"):
    user_type = _normalise_user_type(user_type)
    user_id = await _resolve_user_id(session, clerk_id, user_type)
    result = await session.execute(
        select(Notification).where(
            Notification.id == _as_uuid(notification_id),
            Notification.user_id == user_id,
            Notification.user_type == user_type,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.delete(notification)
    await session.commit()
    return {"message": "Notification deleted"}


# ── Deferring pushes until the transaction commits ────────────────────────
# Every push site used to be `asyncio.create_task(send_push_message(...))` fired
# inline, several lines before the `await session.commit()` that made the change
# real. `create_task` schedules immediately and the very next `await` lets it
# run, so the push raced the commit: a rolled-back order still told the customer
# it was confirmed, and the in-app record backing the push was never written.
#
# `queue_push` stashes the message on the session instead, and `flush_pending_pushes`
# sends whatever is queued *after* the caller commits.

_PUSH_QUEUE_KEY = "pending_pushes"


def queue_push(session, *, to: str | None, title: str, body: str, data: dict | None = None):
    """Hold a push until the current transaction commits. No-op without a token.

    Accepts an `AsyncSession` or a plain `Session`; the queue lives on
    `session.info`, which both expose and which the `after_commit` hook below
    reads back.
    """
    if not to:
        return
    info = getattr(session, "info", None)
    if info is None:  # pragma: no cover — defensive
        return
    info.setdefault(_PUSH_QUEUE_KEY, []).append(
        {"to": to, "title": title, "body": body, "data": data or {}}
    )


def _drain_and_dispatch(sync_session) -> int:
    """Send everything queued on this session. Returns how many were dispatched."""
    pending = sync_session.info.pop(_PUSH_QUEUE_KEY, None)
    if not pending:
        return 0

    from services.expo_push_service import dispatch_background, send_push_message

    dispatched = 0
    for message in pending:
        try:
            dispatch_background(
                send_push_message(
                    to=message["to"], title=message["title"],
                    body=message["body"], data=message["data"],
                )
            )
            dispatched += 1
        except Exception as e:
            # A push failure must never undo a committed state change.
            logger.error("Failed to dispatch queued push: %s", e)
    return dispatched


def _discard_pending(sync_session) -> None:
    """Drop queued pushes for a transaction that did not survive."""
    if sync_session.info.pop(_PUSH_QUEUE_KEY, None):
        logger.info("Transaction rolled back — queued push notifications discarded.")


def register_push_dispatch_hooks() -> None:
    """Wire `queue_push` to the session lifecycle, once, at import time.

    Doing this with SQLAlchemy events rather than an explicit
    `await flush_pending_pushes()` after every commit is deliberate: there are
    eight commit sites across four services, and the defect being fixed here is
    precisely that one of them is easy to miss. A hook cannot be forgotten, and
    it also covers the rollback case, where the push must be dropped rather than
    sent for a change that never happened.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    if getattr(register_push_dispatch_hooks, "_registered", False):
        return

    event.listen(Session, "after_commit", _drain_and_dispatch)
    event.listen(Session, "after_soft_rollback", lambda s, ctx: _discard_pending(s))
    register_push_dispatch_hooks._registered = True


register_push_dispatch_hooks()


async def create_notification(
    session: AsyncSession,
    user_id,
    user_type: str,
    title: str,
    message: str,
    message_type: str,
    related_order_id=None,
    delivered_via: str = "push",
    action_url: str = None,
    data: dict = None,
):
    """Create an in-app notification record. Called alongside send_push_message()."""
    try:
        notification = Notification(
            user_id=user_id,
            user_type=user_type,
            title=title,
            message=message,
            message_type=message_type,
            related_order_id=related_order_id,
            delivered_via=delivered_via,
            action_url=action_url,
            data=data,
        )
        session.add(notification)
        # Don't commit here — let the caller's transaction commit handle it
        # This ensures atomicity with the order status update
        await session.flush()
        return notification
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        return None
