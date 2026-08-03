"""
Customer reviews of vendors and riders.

Aggregation is **incremental**. Each target carries `rating_count` and
`rating_sum`; a new review adds to both and `rating` is recomputed from them.
The previous implementation ran `AVG(rating)` across every review the target had
ever received, on every single submission — work that grows without bound for
exactly the vendors who are used most.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer
from models.order_model import Order
from models.review_model import Review
from models.vendor_model import Vendor
from schemas.review_schemas import ReviewCreate

_TARGET_MODELS = {"vendor": Vendor, "rider": Deliverer}

# What a rider's rating starts at before anybody has rated them. Vendors start
# at 0 ("no rating yet"); riders start at 5.0 so a new rider is not buried.
_DEFAULT_RATING = {"vendor": 0.0, "rider": 5.0}


async def _locked_target(session: AsyncSession, target_type: str, target_id: UUID):
    """Fetch the review target `FOR UPDATE`.

    Incremental aggregation is a read-modify-write, so two customers rating the
    same vendor at the same moment would otherwise both read the old counters and
    one increment would be lost. The lock is per-target, so it only serialises
    reviews of the same vendor or rider.
    """
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        return None
    result = await session.execute(select(model).where(model.id == target_id).with_for_update())
    return result.scalar_one_or_none()


def _apply_rating_delta(target, target_type: str, *, new_rating: float, previous_rating: float | None):
    """Fold one review into the target's counters.

    `previous_rating` is set when the customer is editing a review they already
    left: the count is unchanged and only the sum moves.
    """
    count = int(target.rating_count or 0)
    total = float(target.rating_sum or 0.0)

    if previous_rating is None:
        count += 1
        total += float(new_rating)
    else:
        total += float(new_rating) - float(previous_rating)

    target.rating_count = count
    target.rating_sum = total
    target.rating = round(total / count, 2) if count else _DEFAULT_RATING.get(target_type, 0.0)


async def create_review(session: AsyncSession, clerk_id: str, data: ReviewCreate):
    # Fetch the order to ensure it belongs to the reviewing customer
    order = await session.get(Order, data.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    from models.user_model import User
    user = await session.get(User, order.customer_id) if hasattr(order, 'customer_id') else await session.get(User, order.user_id)
    if not user or user.clerk_id != clerk_id:
        raise HTTPException(status_code=403, detail="You can only review orders you have placed.")

    if order.order_status != "delivered":
        raise HTTPException(status_code=400, detail="You can only review orders that have been delivered.")

    # Anti-Fraud: Target Match and Self-Rating Prevention
    if data.target_type == 'vendor':
        if order.vendor_id is None or str(order.vendor_id) != str(data.target_id):
            raise HTTPException(status_code=403, detail="You can only review the vendor who fulfilled this order.")
    elif data.target_type == 'rider':
        if order.deliverer_id is None or str(order.deliverer_id) != str(data.target_id):
            raise HTTPException(status_code=403, detail="You can only review the rider who delivered this order.")

    target = await _locked_target(session, data.target_type, data.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Review target not found")

    if data.target_type == 'vendor':
        from services.vendor_staff_service import is_store_member

        if await is_store_member(session, clerk_id, target):
            raise HTTPException(status_code=403, detail="Self-rating prohibited. You cannot review your own store.")
    if data.target_type == 'rider' and target.clerk_id == clerk_id:
        raise HTTPException(status_code=403, detail="Self-rating prohibited. You cannot review your own rider profile.")

    # `uq_customer_order_target_review` makes a second review for the same
    # (customer, order, target) a database error. Nothing checked for one first,
    # so the IntegrityError surfaced as a 500 — and the customer app reaches this
    # path routinely: RateOrder submits the vendor and rider ratings as two
    # requests, and if the second fails the retry re-sends the first. Treat a
    # repeat as an edit so the retry completes.
    existing = (
        await session.execute(
            select(Review).where(
                Review.customer_clerk_id == clerk_id,
                Review.order_id == data.order_id,
                Review.target_type == data.target_type,
            )
        )
    ).scalar_one_or_none()

    previous_rating = None
    if existing and existing.hidden_at is not None:
        # A moderated review is out of the target's counters. Treating a resubmit
        # as an edit would fold its rating back in without unhiding it, so the
        # average would move for a review nobody can see — and the customer would
        # have a working way round moderation.
        raise HTTPException(
            status_code=409,
            detail="This review was removed by the platform and cannot be changed.",
        )

    if existing:
        previous_rating = float(existing.rating)
        existing.rating = data.rating
        existing.comment = data.comment
        review = existing
    else:
        review = Review(
            order_id=data.order_id,
            customer_clerk_id=clerk_id,
            target_type=data.target_type,
            target_id=data.target_id,
            rating=data.rating,
            comment=data.comment,
        )
        session.add(review)

    # Counters move in the *same* transaction as the review. Previously the
    # review was committed first and the average in a second commit, so a failure
    # between them left a review that no rating reflected.
    _apply_rating_delta(target, data.target_type, new_rating=data.rating, previous_rating=previous_rating)

    await session.commit()
    await session.refresh(review)
    return review


async def get_target_rating_summary(session: AsyncSession, target_type: str, target_id: UUID) -> dict:
    """Average, total and star distribution for one vendor or rider."""
    if target_type not in _TARGET_MODELS:
        raise HTTPException(status_code=400, detail="target_type must be 'vendor' or 'rider'")

    rows = (
        await session.execute(
            select(func.round(Review.rating).label("star"), func.count(Review.id))
            .where(
                Review.target_type == target_type,
                Review.target_id == target_id,
                # A hidden review is not merely invisible in the list: it must
                # leave the average too, or moderation is theatre.
                Review.hidden_at.is_(None),
            )
            .group_by("star")
        )
    ).all()

    distribution = {star: 0 for star in range(1, 6)}
    total = 0
    weighted = 0.0
    for star, count in rows:
        bucket = max(1, min(5, int(star or 0)))
        distribution[bucket] += int(count)
        total += int(count)
        weighted += bucket * int(count)

    return {
        "target_type": target_type,
        "target_id": target_id,
        "average_rating": round(weighted / total, 2) if total else _DEFAULT_RATING.get(target_type, 0.0),
        "total_reviews": total,
        "distribution": distribution,
    }


async def recount_target_rating(session: AsyncSession, target_type: str, target_id: UUID):
    """Rebuild a target's counters from the reviews table.

    The incremental path is authoritative in normal operation; this exists for
    the migration backfill and for repairing a target by hand if one is ever
    suspected of drifting.
    """
    target = await _locked_target(session, target_type, target_id)
    if target is None:
        return None

    count, total = (
        await session.execute(
            select(func.count(Review.id), func.coalesce(func.sum(Review.rating), 0.0))
            .where(
                Review.target_type == target_type,
                Review.target_id == target_id,
                Review.hidden_at.is_(None),
            )
        )
    ).one()

    target.rating_count = int(count or 0)
    target.rating_sum = float(total or 0.0)
    target.rating = (
        round(float(total) / int(count), 2) if count else _DEFAULT_RATING.get(target_type, 0.0)
    )
    await session.commit()
    return target
