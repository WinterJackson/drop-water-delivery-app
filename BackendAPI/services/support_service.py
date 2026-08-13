"""Support tickets, and replying to them.

A ticket is raised by a customer, rider or vendor from their own app, and worked
in the admin console. Two things about the design are deliberate:

**A reply is a notification, not an email that hopes to arrive.** Every response
writes a `Notification` row for the requester, **pushes** to their device, and
additionally emails them when an address is known. The row is what makes the
history survive; the push is what makes it arrive; the email is best-effort.

Only the row and the push existed as an intention for a long time — the row was
written and nothing was ever pushed, so the one message on this platform a
person is actively waiting for was the only one that never interrupted them.
`_notify_requester` is now the single place that fans a reply out, and a
structural test fails the build if `reply` stops calling it.

**Internal notes never leave the building.** A thread entry marked `internal` is
visible to administrators and is not sent anywhere. Support staff need somewhere
to write "the rider says the customer wasn't there, checking GPS" without it
becoming a message to the customer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset
from sqlalchemy.orm.attributes import flag_modified

from models.deliverer_model import Deliverer
from models.platform_setting_model import SupportTicket
from models.user_model import User
from models.vendor_model import Vendor
from services.notification_service import create_notification, push_allowed, queue_push

logger = logging.getLogger(__name__)

REQUESTER_MODELS = {"customer": User, "rider": Deliverer, "vendor": Vendor}

#: Where a support notification points **in the apps**. Every other `action_url`
#: on this platform is an Expo Router path; this one was `/support/{id}`, which
#: is the admin console's route. The customer app's deep-link whitelist blocked
#: it silently and the other two pushed an unmatched route, so the reply was
#: unreachable even once you found it in the list.
def ticket_deep_link(ticket_id) -> str:
    return f"/(screens)/SupportTicket?id={ticket_id}"

CATEGORIES = (
    "order",
    "payment",
    "delivery",
    "bottles",
    "account",
    "app",
    "other",
)

#: Anything above `normal` should be rare. A queue where everything is urgent is
#: a queue with no priority at all.
PRIORITIES = ("low", "normal", "high", "urgent")

OPEN_STATUSES = ("open", "pending")


def _awaiting_us(ticket) -> bool:
    """True when the last thing said on an unfinished ticket came from them.

    Internal notes are ignored: a colleague writing "checking the GPS trail" is
    not an answer to the customer, and counting it as one is how a ticket gets
    marked as handled while the person who raised it is still waiting.
    """
    if ticket.status in ("resolved", "closed"):
        return False
    for message in reversed(ticket.messages or []):
        if message.get("internal"):
            continue
        return message.get("author") != "admin"
    # Nothing but the opening body — which is theirs.
    return True


def _requester_name(row) -> Optional[str]:
    for attribute in ("full_name", "business_name", "name"):
        value = getattr(row, attribute, None)
        if value:
            return value
    return None


async def create_ticket(
    session: AsyncSession,
    *,
    requester_type: Literal["customer", "rider", "vendor"],
    requester_id: UUID,
    subject: str,
    body: str,
    category: str = "other",
    related_order_id: Optional[UUID] = None,
) -> SupportTicket:
    """Raise a ticket. Called by the apps, never by the console.

    The requester's email is captured **now** rather than joined at read time:
    an account can change its address, be anonymised on deletion, or be
    suspended, and a ticket nobody can reply to six weeks later is not a ticket.
    """
    model = REQUESTER_MODELS.get(requester_type)
    if model is None:
        raise HTTPException(status_code=400, detail="Unknown requester type.")

    account = await session.get(model, requester_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    if category not in CATEGORIES:
        category = "other"

    ticket = SupportTicket(
        requester_type=requester_type,
        requester_id=requester_id,
        requester_email=getattr(account, "email", None),
        subject=subject.strip()[:200],
        body=body.strip(),
        category=category,
        related_order_id=related_order_id,
        messages=[],
    )
    session.add(ticket)
    return ticket


async def list_tickets(
    session: AsyncSession,
    *,
    status: str = "open",
    priority: Optional[str] = None,
    category: Optional[str] = None,
    requester_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> dict:
    """The queue. Oldest first, because the point is that nothing rots.

    Newest-first is the wrong default for a work queue: it buries the ticket
    that has been waiting three days under the one raised a minute ago. The
    paging runs in the same direction, so "next" is older-still rather than a
    jump back to the top of a list sorted the other way.
    """
    query = select(SupportTicket)

    if status == "open":
        query = query.where(SupportTicket.status.in_(OPEN_STATUSES))
    elif status != "all":
        query = query.where(SupportTicket.status == status)

    if priority:
        query = query.where(SupportTicket.priority == priority)
    if category:
        query = query.where(SupportTicket.category == category)
    if requester_type:
        query = query.where(SupportTicket.requester_type == requester_type)
    if search and search.strip():
        like = f"%{search.strip()}%"
        # The subject, plus whoever it was handed to — "everything assigned to
        # me" is the query a support lead runs most and there was no filter for
        # it. The ticket id matters because that is what a customer quotes back.
        clauses = [
            SupportTicket.subject.ilike(like),
            SupportTicket.assigned_admin_email.ilike(like),
        ]
        try:
            clauses.append(SupportTicket.id == UUID(search.strip()))
        except ValueError:
            pass
        query = query.where(or_(*clauses))

    order = keyset.Order(SupportTicket.created_at, SupportTicket.id, descending=False)
    result = await session.execute(keyset.seek(query, order, cursor).limit(limit + 1))
    rows, next_cursor = keyset.split(result.scalars().all(), limit, order)
    now = datetime.now(timezone.utc)

    return {
        "items": [
            {
                "id": str(ticket.id),
                "subject": ticket.subject,
                "requester_type": ticket.requester_type,
                "requester_id": str(ticket.requester_id),
                "category": ticket.category,
                "priority": ticket.priority,
                "status": ticket.status,
                "assigned_to": ticket.assigned_admin_email,
                "reply_count": len(ticket.messages or []),
                "related_order_id": str(ticket.related_order_id) if ticket.related_order_id else None,
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                "age_hours": (
                    round((now - ticket.created_at).total_seconds() / 3600, 1)
                    if ticket.created_at
                    else None
                ),
                # The number that tells you the queue is failing, rather than
                # merely long: nobody has said anything to this person yet.
                "awaiting_first_reply": not any(
                    message.get("author") == "admin" and not message.get("internal")
                    for message in (ticket.messages or [])
                ),
                # Who spoke last. A ticket where they replied after our answer
                # is waiting on *us*, and was previously indistinguishable from
                # one where we are legitimately waiting on them.
                "awaiting_us": _awaiting_us(ticket),
            }
            for ticket in rows
        ],
        "next_cursor": next_cursor,
    }


async def counts(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(SupportTicket.status, func.count(SupportTicket.id)).group_by(
                SupportTicket.status
            )
        )
    ).all()
    by_status = {status: int(count) for status, count in rows}
    return {
        **by_status,
        "open_total": sum(by_status.get(status, 0) for status in OPEN_STATUSES),
    }


async def get_ticket(session: AsyncSession, ticket_id: UUID) -> dict:
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    model = REQUESTER_MODELS[ticket.requester_type]
    account = await session.get(model, ticket.requester_id)

    return {
        "id": str(ticket.id),
        "subject": ticket.subject,
        "body": ticket.body,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "requester": {
            "type": ticket.requester_type,
            "id": str(ticket.requester_id),
            "name": _requester_name(account) if account else None,
            # Masked, like everywhere else. The full address is on the account
            # page behind `pii.view`, and replying does not require reading it.
            "email_masked": _mask_email(ticket.requester_email),
            "exists": account is not None,
        },
        "related_order_id": str(ticket.related_order_id) if ticket.related_order_id else None,
        "assigned_to": ticket.assigned_admin_email,
        "messages": ticket.messages or [],
        "resolution": ticket.resolution,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


def _mask_email(value: Optional[str]) -> Optional[str]:
    if not value or "@" not in value:
        return None
    local, _, domain = value.partition("@")
    return f"{local[0] if local else ''}••••@{domain}"


async def reply(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    admin_email: str,
    body: str,
    internal: bool = False,
    new_status: Optional[str] = None,
) -> SupportTicket:
    """Append to the thread, and tell the requester unless the note is internal.

    Does not commit — the route owns the transaction so the audit row and the
    reply land together or not at all.
    """
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    if ticket.status == "closed":
        raise HTTPException(
            status_code=409,
            detail="This ticket is closed. Reopen it before replying.",
        )

    entry = {
        "author": "admin",
        "author_email": admin_email,
        "body": body.strip(),
        "at": datetime.now(timezone.utc).isoformat(),
        "internal": bool(internal),
    }
    # A JSONB list mutated in place is not seen by the ORM without this — the
    # reply would be silently dropped at flush.
    ticket.messages = [*(ticket.messages or []), entry]
    flag_modified(ticket, "messages")

    if new_status:
        ticket.status = new_status
        if new_status == "resolved":
            ticket.resolved_at = datetime.now(timezone.utc)
    elif not internal:
        # A reply moves an open ticket to "pending" — waiting on them, not on us.
        ticket.status = "pending"

    if not ticket.assigned_admin_email:
        ticket.assigned_admin_email = admin_email

    if not internal:
        await _notify_requester(session, ticket, body.strip())

    return ticket


async def _notify_requester(session: AsyncSession, ticket, body: str) -> None:
    """Write the in-app row and queue the push. The one place a reply goes out.

    `queue_push` rather than `dispatch_background`: the route commits *after*
    this returns, and telling somebody we replied to a reply that then rolled
    back is the exact failure the two-path rule exists to prevent.

    A vendor ticket reaches the store's staff as well as its owner. Staff raise
    and read the store's tickets — a reply only the owner is interrupted by is
    a reply the person actually standing in the shop never sees. No capability
    is required: support is not one of the four staff permissions, and gating it
    on one would silence whoever happens to hold none of them.
    """
    action_url = ticket_deep_link(ticket.id)
    title = f"Re: {ticket.subject}"

    await create_notification(
        session=session,
        user_id=ticket.requester_id,
        user_type=ticket.requester_type,
        title=title,
        message=body,
        message_type="support_reply",
        action_url=action_url,
    )

    account = await session.get(REQUESTER_MODELS[ticket.requester_type], ticket.requester_id)
    if account is None:
        # The account was deleted after raising the ticket. The row above is
        # still written — the thread is evidence — but there is nobody to push to.
        return

    tokens = [getattr(account, "push_token", None)]
    if ticket.requester_type == "vendor":
        from services.vendor_staff_service import push_tokens_for_store

        tokens += await push_tokens_for_store(session, account.id)

    # `support_reply` is unmapped in `_MESSAGE_TYPE_PREFERENCE`, so `push_allowed`
    # treats it as transactional. Asked anyway rather than assumed: the mapping is
    # data and someone may reasonably decide to add a key for it later.
    for token in tokens:
        if token and push_allowed(account, "support_reply"):
            queue_push(
                session,
                to=token,
                title=title,
                body=body,
                data={"url": action_url, "ticket_id": str(ticket.id)},
            )


async def set_status(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    status: str,
    resolution: Optional[str] = None,
    admin_email: str,
) -> SupportTicket:
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    if status not in ("open", "pending", "resolved", "closed"):
        raise HTTPException(status_code=400, detail="Unknown status.")

    ticket.status = status
    if status == "resolved":
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.resolution = (resolution or "").strip() or ticket.resolution
    if status == "open":
        ticket.resolved_at = None

    if not ticket.assigned_admin_email:
        ticket.assigned_admin_email = admin_email

    return ticket


async def set_priority(
    session: AsyncSession, *, ticket_id: UUID, priority: str, admin_email: str
) -> SupportTicket:
    """Escalate or de-escalate a ticket.

    Nothing could write this column, so every ticket ever raised was `normal`
    for its whole life while the queue offered a priority filter and the console
    coloured a badge from it — a control that could only ever return everything
    or nothing.

    Deliberately an **administrator's** judgement, not the requester's. A field
    on the intake form marked "urgent" is a field everybody ticks, and a queue
    where everything is urgent has no priority at all.
    """
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    if priority not in PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Priority must be one of {', '.join(PRIORITIES)}.",
        )

    ticket.priority = priority
    if not ticket.assigned_admin_email:
        ticket.assigned_admin_email = admin_email
    return ticket


async def assign(
    session: AsyncSession, *, ticket_id: UUID, admin_id: UUID, admin_email: str
) -> SupportTicket:
    ticket = await session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    ticket.assigned_admin_id = admin_id
    ticket.assigned_admin_email = admin_email
    return ticket


async def tickets_for_account(
    session: AsyncSession, *, requester_type: str, requester_id: UUID, limit: int = 20
) -> list[dict]:
    """Every ticket this account has raised, for their detail page.

    Someone on their fourth ticket about the same thing is a different
    conversation from someone on their first.
    """
    rows = (
        await session.execute(
            select(SupportTicket)
            .where(
                SupportTicket.requester_type == requester_type,
                SupportTicket.requester_id == requester_id,
            )
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return [
        {
            "id": str(ticket.id),
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }
        for ticket in rows
    ]
