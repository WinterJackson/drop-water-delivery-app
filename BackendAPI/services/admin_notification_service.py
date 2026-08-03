"""What the platform has been telling people, and whether it reached them.

66 `Notification` rows and no view of any of it: not what was sent, not to whom,
not what could never have arrived. Push failures were invisible, which on a
platform whose entire delivery flow is push-driven is the difference between
"the rider ignored the order" and "the rider was never told".

## Reachability is the figure that matters

Every user-visible event writes a `Notification` row **and** may send a push, and
the two are not the same thing. The row is always written so the history
survives; the push needs a `push_token` and the recipient's own preference to
allow it. So the question this screen exists to answer is not "how many did we
send" but **"how many of the people we are writing to could ever have been
interrupted"**.

An account with no `push_token` gets every row and no push. That is fine for a
promotion and close to fatal for "your order has been assigned to you" — and it
is invisible in every other view on this platform.

## Read rate, per audience

`is_read` is the only outcome signal the schema carries — there are no delivery
receipts from Expo stored anywhere. A whole audience with a read rate near zero
means the channel is dead for them, whatever the send volume says. It is a weak
signal and the console labels it as one rather than dressing it up as delivery.

## Data honesty

There are real rows here, but few, and they are mostly seeded rather than
produced by live traffic. Read rate in particular is close to meaningless at this
volume and the screen says so; the reachability figures are exact, because they
are a property of the accounts rather than of the sending.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer
from models.notification_model import Notification
from models.user_model import User
from models.vendor_model import Vendor

#: `Notification.user_id` holds ids from three tables and carries no foreign
#: key, so every read has to scope on `user_type` too — filtering on `user_id`
#: alone relies on UUID collisions not happening, which is not a guarantee.
AUDIENCES = {"customer": User, "rider": Deliverer, "vendor": Vendor}


async def summary(db: AsyncSession, *, days: int = 30) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total = int(
        (await db.execute(select(func.count()).select_from(Notification))).scalar() or 0
    )
    recent = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.created_at >= since)
            )
        ).scalar()
        or 0
    )
    read = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.is_read.is_(True))
            )
        ).scalar()
        or 0
    )

    reach = await reachability(db)
    unreachable = sum(row["without_token"] for row in reach)
    accounts = sum(row["accounts"] for row in reach)

    return {
        "total": total,
        "last_n_days": recent,
        "days": days,
        "read": read,
        # None rather than 0% when nothing has been sent: "0% read" and "nothing
        # to read" are different statements and one of them is an accusation.
        "read_rate": round((read / total) * 100) if total else None,
        "accounts": accounts,
        "unreachable_accounts": unreachable,
        "reachable_rate": round(((accounts - unreachable) / accounts) * 100)
        if accounts
        else None,
    }


async def reachability(db: AsyncSession) -> list[dict[str, Any]]:
    """Per audience: how many accounts could actually receive a push.

    A row written for somebody with no token is history, not a notification.
    """
    out: list[dict[str, Any]] = []
    for audience, model in AUDIENCES.items():
        accounts = int(
            (await db.execute(select(func.count()).select_from(model))).scalar() or 0
        )
        with_token = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.push_token.isnot(None), model.push_token != "")
                )
            ).scalar()
            or 0
        )
        out.append(
            {
                "audience": audience,
                "accounts": accounts,
                "with_token": with_token,
                "without_token": accounts - with_token,
                "rate": round((with_token / accounts) * 100) if accounts else None,
            }
        )
    return out


async def by_type(db: AsyncSession, *, days: int = 30) -> list[dict[str, Any]]:
    """Volume and read rate per message type."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await db.execute(
            select(
                Notification.message_type,
                func.count(Notification.id),
                func.count(Notification.id).filter(Notification.is_read.is_(True)),
            )
            .where(Notification.created_at >= since)
            .group_by(Notification.message_type)
            .order_by(func.count(Notification.id).desc())
        )
    ).all()

    return [
        {
            "message_type": message_type,
            "sent": int(sent or 0),
            "read": int(read or 0),
            "read_rate": round((int(read or 0) / int(sent)) * 100) if sent else None,
        }
        for message_type, sent, read in rows
    ]


async def by_audience(db: AsyncSession, *, days: int = 30) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await db.execute(
            select(
                Notification.user_type,
                func.count(Notification.id),
                func.count(Notification.id).filter(Notification.is_read.is_(True)),
            )
            .where(Notification.created_at >= since)
            .group_by(Notification.user_type)
        )
    ).all()

    return [
        {
            "audience": user_type,
            "sent": int(sent or 0),
            "read": int(read or 0),
            "read_rate": round((int(read or 0) / int(sent)) * 100) if sent else None,
        }
        for user_type, sent, read in rows
    ]


async def by_channel(db: AsyncSession, *, days: int = 30) -> list[dict[str, Any]]:
    """`delivered_via` — how the platform says it sent each one."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await db.execute(
            select(Notification.delivered_via, func.count(Notification.id))
            .where(Notification.created_at >= since)
            .group_by(Notification.delivered_via)
            .order_by(func.count(Notification.id).desc())
        )
    ).all()
    return [{"channel": channel or "app", "sent": int(count or 0)} for channel, count in rows]


async def recent(db: AsyncSession, *, limit: int = 100, audience: str | None = None) -> list[dict]:
    query = select(Notification).order_by(Notification.created_at.desc())
    if audience:
        query = query.where(Notification.user_type == audience)

    rows = (await db.execute(query.limit(limit))).scalars().all()

    return [
        {
            "id": str(row.id),
            "title": row.title,
            # The body can carry an address or a phone number, so the feed shows
            # the opening of it and the detail lives with the recipient.
            "preview": (row.message or "")[:120],
            "message_type": row.message_type,
            "audience": row.user_type,
            "channel": row.delivered_via or "app",
            "read": bool(row.is_read),
            "order_id": str(row.related_order_id) if row.related_order_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
