"""Support, from the three apps' side.

The console has the queue; this is where a ticket comes from. Without it the
support feature is an inbox nobody can write to.

Identity comes from the token, never from the body — the same rule the rest of
the platform follows. The caller says which *kind* of account they are acting
as (one Clerk identity can legitimately be a customer and a rider), and the
account is then resolved from the token: by `clerk_id` for customers and riders,
and through the store resolver for vendors, since a `Vendor` row is a store and
its staff hold no `clerk_id` on it. A ticket can only ever be filed against an
account the token actually reaches.
"""
import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.redis_client import redis_limiter as limiter
from dependencies.auth_dependencies import _resolve_access
from dependencies.dependencies import get_db
from models.deliverer_model import Deliverer
from models.order_model import Order
from models.platform_setting_model import SupportTicket
from models.user_model import User
from models.vendor_model import Vendor
from services import support_service
from utils.verify_user_token import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

AccountKind = Literal["customer", "rider", "vendor"]

MODELS = {"customer": User, "rider": Deliverer, "vendor": Vendor}


async def _resolve_account(
    db: AsyncSession,
    kind: AccountKind,
    clerk_id: str,
    store_id: Optional[str] = None,
):
    """The caller's account of this kind, or a 404.

    **Vendors go through the store resolver**, not a `clerk_id` lookup, for two
    reasons that both bite in production:

    * A `Vendor` row is a *store*, not an account. An owner with two branches
      would otherwise always file against whichever was created first, however
      the app's store switcher was set. `_resolve_access` honours the same
      `X-Store-Id` header every other vendor route does.
    * Staff are `Vendor_Staff` rows and hold no `Vendor.clerk_id` at all, so a
      plain lookup answers "you don't have a vendor account" to the person
      actually standing in the shop. Support with no route for staff is support
      that is missing for most of the people using the app.

    A staff member therefore sees the store's support thread, exactly as they see
    its orders. That is the store's business, and the alternative — a support
    channel only the owner can reach — is what this is fixing.

    For customers and riders it stays a `clerk_id` lookup, with `scalars().first()`
    rather than `scalar_one_or_none()`: the latter raises `MultipleResultsFound`
    on a second row, which is exactly how a vendor opening a branch turned app
    startup into a 500 elsewhere on this platform.
    """
    if kind == "vendor":
        # Raises 404 for a store the caller neither owns nor staffs, and 403 when
        # they are not a vendor at all — the same answers as every other vendor
        # route, from the same code.
        access = await _resolve_access(db, clerk_id, store_id, owner_only=False)
        return access.vendor

    model = MODELS[kind]
    account = (
        await db.execute(select(model).where(model.clerk_id == clerk_id).order_by(model.created_at.asc()))
    ).scalars().first()

    if account is None:
        raise HTTPException(
            status_code=404,
            detail=f"You don't have a {kind} account on Drop.",
        )
    return account


class TicketRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=10, max_length=5000)
    category: str = Field("other", max_length=32)
    related_order_id: Optional[UUID] = None


@router.post("/support/tickets", summary="Raise a support ticket")
# A person with a problem writes a handful of messages, not a hundred. The limit
# is what stops the queue being flooded from one device.
@limiter.limit("10/hour")
async def create_ticket(
    request: Request,
    body: TicketRequest,
    user_type: AccountKind = Query(..., description="Which of your accounts this is about"),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """File a ticket against your own account.

    If an order is referenced it is checked against the caller — a ticket id is
    a poor place to learn about someone else's delivery, and accepting an
    arbitrary order id would make this endpoint a way to probe which ones exist.
    """
    account = await _resolve_account(db, user_type, user["sub"], x_store_id)

    if body.related_order_id is not None:
        column = {
            "customer": Order.customer_id,
            "rider": Order.deliverer_id,
            "vendor": Order.vendor_id,
        }[user_type]
        owns = (
            await db.execute(
                select(Order.id).where(
                    Order.id == body.related_order_id, column == account.id
                )
            )
        ).scalar_one_or_none()
        if owns is None:
            # 404 rather than 403: confirming the id exists is itself a leak.
            raise HTTPException(status_code=404, detail="Order not found.")

    ticket = await support_service.create_ticket(
        db,
        requester_type=user_type,
        requester_id=account.id,
        subject=body.subject,
        body=body.body,
        category=body.category,
        related_order_id=body.related_order_id,
    )
    await db.commit()
    await db.refresh(ticket)

    return {
        "id": str(ticket.id),
        "status": ticket.status,
        "message": "Thanks — we've got this and will reply in the app.",
    }


@router.get("/support/tickets", summary="Your tickets")
async def my_tickets(
    user_type: AccountKind = Query(...),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    account = await _resolve_account(db, user_type, user["sub"], x_store_id)
    return {
        "items": await support_service.tickets_for_account(
            db, requester_type=user_type, requester_id=account.id
        )
    }


@router.get("/support/tickets/{ticket_id}", summary="One of your tickets")
async def my_ticket(
    ticket_id: UUID,
    user_type: AccountKind = Query(...),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Internal notes are stripped.

    Support staff write "checking the rider's GPS, customer sounds confused" in
    the same thread. Those entries are for the console and must never be served
    here — filtering them at the boundary rather than relying on the client not
    to render them.
    """
    account = await _resolve_account(db, user_type, user["sub"], x_store_id)
    ticket = await db.get(SupportTicket, ticket_id)

    if ticket is None or ticket.requester_id != account.id or ticket.requester_type != user_type:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    return {
        "id": str(ticket.id),
        "subject": ticket.subject,
        "body": ticket.body,
        "status": ticket.status,
        "category": ticket.category,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "messages": [
            {
                "author": message.get("author"),
                "body": message.get("body"),
                "at": message.get("at"),
            }
            for message in (ticket.messages or [])
            if not message.get("internal")
        ],
        "resolution": ticket.resolution,
    }


class FollowUp(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


@router.post("/support/tickets/{ticket_id}/reply", summary="Add to your ticket")
@limiter.limit("30/hour")
async def reply_to_own_ticket(
    request: Request,
    ticket_id: UUID,
    body: FollowUp,
    user_type: AccountKind = Query(...),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """A follow-up reopens the ticket. **Always** — including from `pending`.

    A requester replying to something marked resolved is saying it is not
    resolved, and leaving it closed would lose them in the queue — which is the
    most common way a support system quietly fails the people using it.

    `pending` used to be excluded, and that was the same bug wearing a different
    hat. An administrator's reply moves a ticket to `pending`, meaning "waiting
    on them"; the moment they answer it is waiting on *us* again. Leaving it
    `pending` kept it labelled as somebody else's turn, and — because the nav
    badge counts only `open` — meant the console was never told at all. The
    person who replied within a minute became invisible.
    """
    account = await _resolve_account(db, user_type, user["sub"], x_store_id)
    ticket = await db.get(SupportTicket, ticket_id)

    if ticket is None or ticket.requester_id != account.id or ticket.requester_type != user_type:
        raise HTTPException(status_code=404, detail="Ticket not found.")

    from datetime import datetime, timezone

    ticket.messages = [
        *(ticket.messages or []),
        {
            "author": user_type,
            "body": body.body.strip(),
            "at": datetime.now(timezone.utc).isoformat(),
            "internal": False,
        },
    ]
    # A JSONB list mutated in place is invisible to the ORM without this.
    flag_modified(ticket, "messages")

    if ticket.status != "open":
        ticket.status = "open"
        ticket.resolved_at = None

    await db.commit()
    return {"ok": True, "status": ticket.status}


@router.get("/support/categories", summary="What a ticket can be about")
async def categories():
    return {"categories": list(support_service.CATEGORIES)}
