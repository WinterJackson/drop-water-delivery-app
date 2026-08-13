"""Support tickets and platform-wide messaging.

Two features with very different blast radii, which is why they hold different
capabilities. `support.respond` reaches one person who asked to be reached;
`broadcast.send` reaches everybody, cannot be recalled, and is therefore not in
the support preset.
"""
import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import get_arq_pool, redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_BROADCAST_SEND,
    PERM_SUPPORT_READ,
    PERM_SUPPORT_RESPOND,
)
from services import admin_service, broadcast_service, email_service, support_service
from utils import keyset

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Tickets ───────────────────────────────────────────────────────────────


@router.get("/support/tickets", summary="The support queue")
async def list_tickets(
    status: str = Query("open"),
    priority: Optional[str] = None,
    category: Optional[str] = None,
    requester_type: Optional[str] = None,
    search: Optional[str] = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_READ)),
):
    return await support_service.list_tickets(
        db,
        status=status,
        priority=priority,
        category=category,
        requester_type=requester_type,
        search=search,
        limit=limit,
        cursor=cursor,
    )


@router.get("/support/counts", summary="Queue depths by status")
async def ticket_counts(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_READ)),
):
    return await support_service.counts(db)


@router.get("/support/meta", summary="Categories and priorities")
async def ticket_meta(
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_READ)),
):
    return {
        "categories": list(support_service.CATEGORIES),
        "priorities": list(support_service.PRIORITIES),
    }


@router.get(
    "/support/accounts/{requester_type}/{requester_id}",
    summary="Every ticket one account has raised",
)
async def account_tickets(
    requester_type: Literal["customer", "rider", "vendor"],
    requester_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_READ)),
):
    """For the account detail page.

    Someone on their fourth ticket about the same thing is a different
    conversation from someone on their first, and an administrator about to
    suspend an account should be able to see they have been asking for help.

    Scoped on `requester_type` as well as the id: the column holds ids from three
    tables and carries no foreign key.
    """
    return {
        "items": await support_service.tickets_for_account(
            db, requester_type=requester_type, requester_id=requester_id, limit=limit
        )
    }


@router.get("/support/tickets/{ticket_id}", summary="One ticket and its thread")
async def get_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_READ)),
):
    return await support_service.get_ticket(db, ticket_id)


class ReplyRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    #: An internal note is visible to administrators and sent nowhere.
    internal: bool = False
    status: Optional[Literal["open", "pending", "resolved", "closed"]] = None


@router.post("/support/tickets/{ticket_id}/reply", summary="Reply to a ticket")
@limiter.limit("120/minute")
async def reply_to_ticket(
    request: Request,
    ticket_id: UUID,
    body: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_RESPOND)),
):
    """Append to the thread, notify the requester, then email them if we can.

    The notification is written inside the transaction and the email is sent
    after the commit. That ordering is the platform's rule and it matters here
    for an ordinary reason: an email that says "we've replied" when the reply
    was rolled back is worse than a slightly late email.
    """
    ticket = await support_service.reply(
        db,
        ticket_id=ticket_id,
        admin_email=access.email,
        body=body.body,
        internal=body.internal,
        new_status=body.status,
    )

    admin_service.record_audit(
        db,
        access=access,
        action="support.reply_internal" if body.internal else "support.reply",
        target_type="support_ticket",
        target_id=ticket_id,
        after={"status": ticket.status, "internal": body.internal},
        reason=body.body[:200],
    )

    address = ticket.requester_email
    subject = ticket.subject
    await db.commit()

    if not body.internal and address:
        try:
            email_service.send_support_reply_email(
                to=address,
                name="there",
                subject=subject,
                body=body.body,
                ticket_id=str(ticket_id),
            )
        except Exception:
            # Best-effort by design: the in-app notification is the record that
            # matters and it is already committed.
            logger.warning("Support reply email failed for ticket %s", ticket_id, exc_info=True)

    return {"ok": True, "status": ticket.status}


class StatusRequest(BaseModel):
    status: Literal["open", "pending", "resolved", "closed"]
    resolution: Optional[str] = Field(None, max_length=2000)


@router.post("/support/tickets/{ticket_id}/status", summary="Change a ticket's status")
async def set_ticket_status(
    ticket_id: UUID,
    body: StatusRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_RESPOND)),
):
    ticket = await support_service.set_status(
        db,
        ticket_id=ticket_id,
        status=body.status,
        resolution=body.resolution,
        admin_email=access.email,
    )
    admin_service.record_audit(
        db,
        access=access,
        action=f"support.{body.status}",
        target_type="support_ticket",
        target_id=ticket_id,
        after={"status": body.status},
        reason=body.resolution or f"Marked {body.status}",
    )
    await db.commit()
    return {"ok": True, "status": ticket.status}


class PriorityRequest(BaseModel):
    priority: Literal["low", "normal", "high", "urgent"]


@router.post("/support/tickets/{ticket_id}/priority", summary="Escalate a ticket")
async def set_ticket_priority(
    ticket_id: UUID,
    body: PriorityRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_RESPOND)),
):
    """Audited like any other change of state.

    Escalation is a claim about someone else's workload, so it carries a name —
    the queue is sorted oldest-first and moving a ticket up it means moving
    every other one down.
    """
    ticket = await support_service.set_priority(
        db, ticket_id=ticket_id, priority=body.priority, admin_email=access.email
    )
    admin_service.record_audit(
        db,
        access=access,
        action="support.priority",
        target_type="support_ticket",
        target_id=ticket_id,
        after={"priority": body.priority},
        reason=f"Priority set to {body.priority}",
    )
    await db.commit()
    return {"ok": True, "priority": ticket.priority}


@router.post("/support/tickets/{ticket_id}/assign", summary="Take a ticket")
async def assign_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SUPPORT_RESPOND)),
):
    """Assigns to the caller. There is no "assign to someone else" here on
    purpose — a queue where work is pushed onto people is a queue where nobody
    owns anything."""
    await support_service.assign(
        db, ticket_id=ticket_id, admin_id=access.admin.id, admin_email=access.email
    )
    await db.commit()
    return {"ok": True, "assigned_to": access.email}


# ── Broadcast ─────────────────────────────────────────────────────────────


@router.get("/broadcast/audiences", summary="Segments, with how many each reaches")
async def broadcast_audiences(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_BROADCAST_SEND)),
):
    """Counted live, before anything is composed.

    "This will message 4,812 people" is the single most effective guardrail on
    the screen — far more so than a confirmation dialog, which people click.
    """
    return {
        "audiences": [
            {
                "key": key,
                "label": label,
                "recipients": await broadcast_service.estimate_recipients(db, key),
            }
            for key, label in broadcast_service.AUDIENCES.items()
        ]
    }


@router.get("/broadcast/campaigns", summary="What has been sent")
async def list_campaigns(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_BROADCAST_SEND)),
):
    return await broadcast_service.list_campaigns(db, limit=limit)


class BroadcastRequest(BaseModel):
    channel: Literal["in_app", "email", "both"]
    audience: str
    subject: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=10, max_length=5000)
    #: Bypasses the recipient's notification preferences. A claim, not a toggle.
    transactional: bool = False
    #: Must equal the audience key. Cheap, but it makes "send" a deliberate act
    #: rather than a reflex — this is the one button here that cannot be undone.
    confirm: str


@router.post("/broadcast/send", summary="Message a segment of the platform")
# Nobody legitimately starts more than a couple of campaigns a minute.
@limiter.limit("5/minute")
async def send_broadcast(
    request: Request,
    body: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_BROADCAST_SEND)),
):
    """Record the campaign, then hand it to the worker.

    Sending inline would time out somewhere around the thirtieth recipient and
    leave nobody able to say how far it got. The campaign row is written first
    so that a failure has evidence, and ARQ does the work in batches.

    If ARQ is unavailable the campaign is left `queued` rather than being run in
    the request — a half-sent campaign with no record is the outcome this whole
    design exists to avoid.
    """
    if body.confirm != body.audience:
        raise HTTPException(
            status_code=400,
            detail=(
                "Type the audience key to confirm. This cannot be recalled once "
                "it starts."
            ),
        )

    try:
        campaign = await broadcast_service.create_campaign(
            db,
            channel=body.channel,
            audience=body.audience,
            subject=body.subject,
            body=body.body,
            transactional=body.transactional,
            created_by_email=access.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    admin_service.record_audit(
        db,
        access=access,
        action="broadcast.send",
        target_type="broadcast",
        target_id=None,
        after={
            "audience": body.audience,
            "channel": body.channel,
            "recipients": campaign.recipient_count,
            # Recorded explicitly: overriding everyone's notification
            # preferences is a decision somebody made, and it should have a name
            # attached to it.
            "transactional": body.transactional,
            "subject": body.subject,
        },
        reason=f"Broadcast to {body.audience} ({campaign.recipient_count} recipients)",
    )

    await db.commit()
    await db.refresh(campaign)

    pool = await get_arq_pool()
    if pool is None:
        logger.error("ARQ unavailable; campaign %s left queued", campaign.id)
        return {
            "id": str(campaign.id),
            "status": "queued",
            "recipients": campaign.recipient_count,
            "message": (
                "Saved, but the background worker is unreachable so nothing has "
                "been sent yet. It will go out when the worker is back."
            ),
        }

    await pool.enqueue_job("run_broadcast_campaign", str(campaign.id))

    return {
        "id": str(campaign.id),
        "status": "sending",
        "recipients": campaign.recipient_count,
        "message": f"Sending to {campaign.recipient_count} recipients.",
    }
