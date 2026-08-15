"""Review moderation.

Reading is gated on `disputes.read` and hiding on `disputes.resolve`. A review
is a public claim one party makes about another, and deciding whether it stands
is the same judgement as deciding a bottle rejection — it belongs with the people
who already make that call, not with everyone who can look at a vendor.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_DISPUTES_READ, PERM_DISPUTES_RESOLVE
from services import admin_review_service, admin_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/reviews", summary="Reviews, and the ones worth reading")
@limiter.limit("60/minute")
async def reviews(
    request: Request,
    view: str = Query("flagged", pattern="^(all|flagged|low|hidden)$"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DISPUTES_READ)),
):
    """`flagged` is the default view because `all` is not a queue.

    Nothing here is user-reported — no app has a report button — so `flagged` is
    a heuristic and the console labels it as one. See the module docstring on
    `admin_review_service` for what it matches and why.
    """
    page = await admin_review_service.listing(
        db, view=view, search=search, limit=limit, cursor=cursor
    )
    return {
        **page,
        "summary": await admin_review_service.summary(db),
        "worst_rated": await admin_review_service.worst_rated(db),
    }


class Moderate(BaseModel):
    hidden: bool
    reason: str = Field(min_length=8, max_length=500)


@router.post("/reviews/{review_id}/moderate", summary="Hide or restore a review")
async def moderate(
    review_id: UUID,
    body: Moderate,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DISPUTES_RESOLVE)),
):
    """Hide, never delete.

    A delete loses the fact the review existed, releases the unique constraint so
    the customer can simply leave another, and strands the target's rating
    counters on a row that is gone.

    The target's rating is rebuilt from the visible reviews in the same
    transaction. Taking a one-star review out of the list and leaving it in the
    average would be moderation that changes nothing anybody can see.
    """
    result = await admin_review_service.set_hidden(
        db,
        review_id,
        hidden=body.hidden,
        reason=body.reason,
        actor_clerk_id=access.clerk_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No such review.")

    if result.get("changed"):
        admin_service.record_audit(
            db,
            access=access,
            action="reviews.moderate",
            target_type="review",
            target_id=str(review_id),
            before={"hidden": not body.hidden},
            after={
                "hidden": body.hidden,
                "reason": body.reason.strip(),
                "target_rating": result.get("target_rating"),
            },
        )
    await db.commit()

    return result
