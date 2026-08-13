"""Review moderation.

`reviews` had no moderation state and no admin reader. A review naming a rider's
home address, or one left on the wrong order, could only be removed with a
DELETE — which loses the fact it existed, frees
`uq_customer_order_target_review` so the customer can leave another, and strands
the target's `rating_sum`/`rating_count` on a row that is gone.

## Hiding is not enough on its own

Taking a one-star review out of the list and leaving it in the average is
theatre. `hide()` rebuilds the target's counters from the visible rows in the
same transaction, so the rating a customer sees changes the moment the review
comes down.

## There is no report button

Nothing in the three apps lets a customer, rider or vendor report a review, so
nothing here is user-flagged. What `flagged` returns is a **heuristic** and is
labelled as one on the page:

* a comment containing what looks like a phone number or an email address —
  reviews are public, and a rider's number ending up in one is a safety problem
  before it is a moderation problem;
* a one- or two-star review carrying a comment, which is the population a human
  should skim rather than a verdict about any single review in it.

A heuristic presented as a queue of confirmed problems is how moderators learn
to clear a screen without reading it. The console says which is which.

## Data honesty

`reviews` is empty on this deployment. The aggregates below are ordinary
`GROUP BY` over one table and were exercised against fixtures rather than
observed volume; the flag patterns in particular have never been run against
real customer prose and will need tuning once there is some.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset

from models.deliverer_model import Deliverer
from models.review_model import Review
from models.vendor_model import Vendor

#: Rating at or below which a comment is worth a human skim.
LOW_RATING = 2.0

#: A target needs at least this many visible reviews before its average is worth
#: reporting. One angry customer is not a rating.
MIN_REVIEWS_FOR_RANKING = 3

#: Deliberately loose. A false positive costs a moderator two seconds; a missed
#: phone number sits in public on a rider's profile. Kenyan mobile numbers are
#: 07xx/01xx or +2547xx, but the pattern is not country-specific on purpose —
#: any run of 9+ digits in a review comment is worth a look.
_CONTACT_PATTERNS = (
    re.compile(r"\+?\d[\d\s().-]{8,}\d"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
)


def _has_contact(comment: str | None) -> bool:
    if not comment:
        return False
    return any(pattern.search(comment) for pattern in _CONTACT_PATTERNS)


def _flags(review: Review) -> list[str]:
    """Why this review is being shown, in the words the console prints."""
    out: list[str] = []
    if _has_contact(review.comment):
        out.append("contact_details")
    if review.rating <= LOW_RATING and (review.comment or "").strip():
        out.append("low_rating_with_comment")
    return out


async def _names(db: AsyncSession, reviews: list[Review]) -> dict[tuple[str, UUID], str | None]:
    """Resolve vendor and rider names in two queries rather than one per row."""
    vendor_ids = {r.target_id for r in reviews if r.target_type == "vendor"}
    rider_ids = {r.target_id for r in reviews if r.target_type == "rider"}

    out: dict[tuple[str, UUID], str | None] = {}
    if vendor_ids:
        for vid, name in (
            await db.execute(
                select(Vendor.id, Vendor.business_name).where(Vendor.id.in_(vendor_ids))
            )
        ).all():
            out[("vendor", vid)] = name
    if rider_ids:
        for rid, name in (
            await db.execute(select(Deliverer.id, Deliverer.name).where(Deliverer.id.in_(rider_ids)))
        ).all():
            out[("rider", rid)] = name
    return out


def _serialise(review: Review, name: str | None) -> dict[str, Any]:
    return {
        "id": str(review.id),
        "order_id": str(review.order_id),
        "target_type": review.target_type,
        "target_id": str(review.target_id),
        "target_name": name,
        "rating": float(review.rating),
        "comment": review.comment,
        "flags": _flags(review),
        "hidden": review.hidden_at is not None,
        "hidden_at": review.hidden_at.isoformat() if review.hidden_at else None,
        "hidden_reason": review.hidden_reason,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


async def summary(db: AsyncSession) -> dict[str, Any]:
    async def count(*where) -> int:
        query = select(func.count()).select_from(Review)
        for clause in where:
            query = query.where(clause)
        return int((await db.execute(query)).scalar() or 0)

    visible = Review.hidden_at.is_(None)

    total = await count()
    hidden = await count(Review.hidden_at.isnot(None))
    low = await count(visible, Review.rating <= LOW_RATING)

    average = (
        await db.execute(select(func.avg(Review.rating)).where(visible))
    ).scalar()

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await count(visible, Review.created_at >= week_ago)

    # Contact details cannot be found in SQL without a regex the database would
    # have to apply row by row anyway, so the candidate set is narrowed first:
    # only comments long enough to contain a number are pulled back.
    candidates = (
        await db.execute(
            select(Review)
            .where(visible, Review.comment.isnot(None), func.length(Review.comment) >= 9)
        )
    ).scalars().all()
    with_contact = sum(1 for review in candidates if _has_contact(review.comment))

    return {
        "total": total,
        "visible": total - hidden,
        "hidden": hidden,
        "low_rated": low,
        "with_contact_details": with_contact,
        "average_rating": round(float(average), 2) if average is not None else None,
        "last_7_days": recent,
        "low_rating_threshold": LOW_RATING,
    }


async def listing(
    db: AsyncSession,
    *,
    view: str = "all",
    search: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    query = select(Review)

    if view == "hidden":
        query = query.where(Review.hidden_at.isnot(None))
    else:
        query = query.where(Review.hidden_at.is_(None))
        if view == "low":
            query = query.where(Review.rating <= LOW_RATING)
        elif view == "flagged":
            # Narrow in SQL, then apply the regexes in Python. `flagged` is the
            # union of "low with a comment" and "looks like contact details", and
            # the second cannot be expressed here without a database regex.
            query = query.where(
                or_(
                    Review.rating <= LOW_RATING,
                    func.length(func.coalesce(Review.comment, "")) >= 9,
                ),
                Review.comment.isnot(None),
            )

    if search and search.strip():
        query = query.where(Review.comment.ilike(f"%{search.strip()}%"))

    order = keyset.Order(Review.created_at, Review.id)
    seeded = keyset.seek(query, order, cursor)

    if view == "flagged":
        # `flagged` is the union of "low with a comment" and "looks like contact
        # details", and the second needs a regex the database cannot express —
        # so the SQL narrows and Python decides. Over-fetch, filter, then take a
        # page: the ordering survives the filter, so the last surviving row is
        # still a valid boundary. Exhausting the over-fetch without filling a
        # page is the only honest signal that there is nothing further, which is
        # why `has_more` is derived from the raw count and not the kept one.
        span = max(limit * 3, limit + 1)
        raw = list((await db.execute(seeded.limit(span))).scalars().all())
        kept = [review for review in raw if _flags(review)]
        reviews = kept[:limit]
        has_more = len(kept) > limit or len(raw) == span
        next_cursor = (
            keyset.encode(order.values(reviews[-1])) if has_more and reviews else None
        )
    else:
        raw = list((await db.execute(seeded.limit(limit + 1))).scalars().all())
        reviews, next_cursor = keyset.split(raw, limit, order)

    names = await _names(db, reviews)
    return {
        "items": [
            _serialise(review, names.get((review.target_type, review.target_id)))
            for review in reviews
        ],
        "next_cursor": next_cursor,
    }


async def worst_rated(db: AsyncSession, *, limit: int = 8) -> list[dict[str, Any]]:
    """Targets whose visible average is lowest, above the minimum sample.

    A vendor with one one-star review is not the platform's worst vendor, and
    putting them at the top of this list is how somebody gets suspended for a
    bad day.
    """
    rows = (
        await db.execute(
            select(
                Review.target_type,
                Review.target_id,
                func.avg(Review.rating).label("average"),
                func.count(Review.id).label("reviews"),
            )
            .where(Review.hidden_at.is_(None))
            .group_by(Review.target_type, Review.target_id)
            .having(func.count(Review.id) >= MIN_REVIEWS_FOR_RANKING)
            .order_by(func.avg(Review.rating).asc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    vendor_ids = {tid for ttype, tid, _, _ in rows if ttype == "vendor"}
    rider_ids = {tid for ttype, tid, _, _ in rows if ttype == "rider"}
    names: dict[tuple[str, UUID], str | None] = {}
    if vendor_ids:
        for vid, name in (
            await db.execute(
                select(Vendor.id, Vendor.business_name).where(Vendor.id.in_(vendor_ids))
            )
        ).all():
            names[("vendor", vid)] = name
    if rider_ids:
        for rid, name in (
            await db.execute(select(Deliverer.id, Deliverer.name).where(Deliverer.id.in_(rider_ids)))
        ).all():
            names[("rider", rid)] = name

    return [
        {
            "target_type": target_type,
            "target_id": str(target_id),
            "target_name": names.get((target_type, target_id)),
            "average": round(float(average), 2),
            "reviews": int(reviews),
        }
        for target_type, target_id, average, reviews in rows
    ]


async def set_hidden(
    db: AsyncSession,
    review_id: UUID,
    *,
    hidden: bool,
    reason: str,
    actor_clerk_id: str | None,
) -> dict[str, Any] | None:
    """Take a review down, or put it back, and move the target's rating with it.

    The counters are rebuilt from the visible rows rather than adjusted by a
    delta. A delta is one arithmetic slip away from a rating that no set of
    reviews produces, and the rebuild is a single indexed aggregate over one
    target — the incremental path in `review_service` exists for the write that
    happens thousands of times a day, not for this one.
    """
    review = await db.get(Review, review_id)
    if review is None:
        return None

    was_hidden = review.hidden_at is not None
    if hidden == was_hidden:
        return {"id": str(review_id), "hidden": was_hidden, "changed": False}

    if hidden:
        review.hidden_at = datetime.now(timezone.utc)
        review.hidden_by = actor_clerk_id
        review.hidden_reason = reason.strip()
    else:
        review.hidden_at = None
        review.hidden_by = None
        review.hidden_reason = None

    await db.flush()

    rating = await _rebuild_target_rating(db, review.target_type, review.target_id)

    return {
        "id": str(review_id),
        "hidden": hidden,
        "changed": True,
        "target_type": review.target_type,
        "target_id": str(review.target_id),
        "target_rating": rating,
    }


async def _rebuild_target_rating(db: AsyncSession, target_type: str, target_id: UUID) -> float | None:
    """Recompute one target's rating from its visible reviews.

    Mirrors `review_service.recount_target_rating` but stays in the caller's
    transaction — that one commits, and hiding a review must not be durable
    before the rating that reflects it.
    """
    model = {"vendor": Vendor, "rider": Deliverer}.get(target_type)
    if model is None:
        return None

    target = (
        await db.execute(select(model).where(model.id == target_id).with_for_update())
    ).scalar_one_or_none()
    if target is None:
        return None

    count, total = (
        await db.execute(
            select(func.count(Review.id), func.coalesce(func.sum(Review.rating), 0.0)).where(
                Review.target_type == target_type,
                Review.target_id == target_id,
                Review.hidden_at.is_(None),
            )
        )
    ).one()

    count = int(count or 0)
    total = float(total or 0.0)
    target.rating_count = count
    # A rider with every review hidden falls back to 5.0, a vendor to 0.0 — the
    # same defaults `review_service` uses, so the two paths cannot disagree.
    target.rating_sum = total
    target.rating = round(total / count, 2) if count else (5.0 if target_type == "rider" else 0.0)
    return target.rating
