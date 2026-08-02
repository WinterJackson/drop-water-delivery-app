"""Queue shape: depth, age, throughput and outcome, for the console's headers.

Eight console pages were a table and a filter. A list answers "what is in the
queue" and never "is the queue healthy", which is the only question a supervisor
actually has. Four numbers answer it, and they are the same four for every queue
on the platform:

* **Depth** — how many are waiting.
* **Age of the oldest** — the difference between a queue and an incident. Twelve
  waiting is fine at nine minutes and a crisis at nine hours, and the count is
  identical in both cases.
* **Throughput** — how many were cleared in the last day, so depth can be read
  against the rate that drains it.
* **Outcome split** — approved against rejected. A reviewer approving everything
  and a reviewer approving nothing both look busy.

Every figure is computed in the database. Loading a queue to count it in Python
is a table scan that gets slower exactly as the platform succeeds.

The shape is deliberately uniform so the console can render one component for
every queue, and so a fifth queue added later gets a header for free.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bottle_rejection_model import BottleRejectionTicket, RejectionStatus
from models.deliverer_model import Deliverer, KYCStatus
from models.payout_model import Payout
from models.platform_setting_model import SupportTicket
from models.vendor_model import Vendor


def _minutes_since(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:  # a naive column would otherwise raise on subtraction
        value = value.replace(tzinfo=timezone.utc)
    return round((now - value).total_seconds() / 60)


async def _count(db: AsyncSession, model, *where) -> int:
    query = select(func.count()).select_from(model)
    for clause in where:
        query = query.where(clause)
    return int((await db.execute(query)).scalar() or 0)


async def _oldest(db: AsyncSession, column, *where) -> datetime | None:
    query = select(func.min(column))
    for clause in where:
        query = query.where(clause)
    return (await db.execute(query)).scalar()


def _rate(part: int, whole: int) -> int | None:
    """A percentage, or `None` when the denominator is zero.

    Never 0%. "Nothing has been decided yet" and "everything was rejected" are
    different facts, and reporting the first as a rate invents a number the data
    does not contain.
    """
    return round((part / whole) * 100) if whole else None


async def rider_kyc(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    waiting = await _count(db, Deliverer, Deliverer.kyc_status == KYCStatus.pending)
    approved = await _count(db, Deliverer, Deliverer.kyc_status == KYCStatus.approved)
    rejected = await _count(db, Deliverer, Deliverer.kyc_status == KYCStatus.rejected)
    decided = approved + rejected

    return {
        "waiting": waiting,
        "oldest_wait_minutes": _minutes_since(
            await _oldest(db, Deliverer.updated_at, Deliverer.kyc_status == KYCStatus.pending),
            now,
        ),
        "decided_24h": await _count(
            db,
            Deliverer,
            Deliverer.kyc_status.in_((KYCStatus.approved, KYCStatus.rejected)),
            Deliverer.updated_at >= day_ago,
        ),
        "approved": approved,
        "rejected": rejected,
        "approval_rate": _rate(approved, decided),
        # The bottom of the funnel: signed up and never submitted anything.
        # These are riders the platform acquired and then lost, and they are
        # invisible on a queue that only lists `pending`.
        "never_submitted": await _count(
            db, Deliverer, Deliverer.kyc_status == KYCStatus.unsubmitted
        ),
        "total": await _count(db, Deliverer),
    }


async def vendor_verification(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    waiting = await _count(
        db, Vendor, Vendor.verification_status == "pending", Vendor.is_active.is_(True)
    )
    approved = await _count(db, Vendor, Vendor.verification_status == "approved")
    rejected = await _count(db, Vendor, Vendor.verification_status == "rejected")
    decided = approved + rejected

    return {
        "waiting": waiting,
        "oldest_wait_minutes": _minutes_since(
            await _oldest(
                db,
                Vendor.updated_at,
                Vendor.verification_status == "pending",
                Vendor.is_active.is_(True),
            ),
            now,
        ),
        "approved": approved,
        "rejected": rejected,
        "approval_rate": _rate(approved, decided),
        "suspended": await _count(db, Vendor, Vendor.is_active.is_(False)),
        "total": await _count(db, Vendor),
    }


async def disputes(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    waiting = await _count(
        db, BottleRejectionTicket, BottleRejectionTicket.status == RejectionStatus.PENDING_REVIEW
    )
    upheld = await _count(
        db, BottleRejectionTicket, BottleRejectionTicket.status == RejectionStatus.APPROVED
    )
    denied = await _count(
        db, BottleRejectionTicket, BottleRejectionTicket.status == RejectionStatus.DENIED
    )
    decided = upheld + denied

    return {
        "waiting": waiting,
        "oldest_wait_minutes": _minutes_since(
            await _oldest(
                db,
                BottleRejectionTicket.created_at,
                BottleRejectionTicket.status == RejectionStatus.PENDING_REVIEW,
            ),
            now,
        ),
        "decided_24h": await _count(
            db,
            BottleRejectionTicket,
            BottleRejectionTicket.status != RejectionStatus.PENDING_REVIEW,
            BottleRejectionTicket.created_at >= day_ago,
        ),
        # "Upheld" means the rider's rejection stood and the vendor wears the
        # bottle. The split is the point: consistently siding with one party is
        # the thing an operations lead needs to see and cannot from a list.
        "upheld": upheld,
        "denied": denied,
        "uphold_rate": _rate(upheld, decided),
        "total": await _count(db, BottleRejectionTicket),
    }


async def payouts(db: AsyncSession) -> dict[str, Any]:
    """Depth *and value*. A payout queue is measured in money, not rows.

    Twelve payouts pending is meaningless; KES 240,000 pending is a decision
    about the platform's cash position.
    """
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    async def total(*where) -> str:
        query = select(func.coalesce(func.sum(Payout.amount), 0))
        for clause in where:
            query = query.where(clause)
        value = (await db.execute(query)).scalar() or 0
        return str(Decimal(value).quantize(Decimal("0.01")))

    pending = await _count(db, Payout, Payout.status == "pending")

    # The single largest request waiting. A queue worth KES 240,000 made of two
    # hundred small withdrawals and one made of a single enormous one are the
    # same total and completely different decisions.
    largest = (
        await db.execute(select(func.max(Payout.amount)).where(Payout.status == "pending"))
    ).scalar()

    return {
        "waiting": pending,
        "waiting_value": await total(Payout.status == "pending"),
        "oldest_wait_minutes": _minutes_since(
            await _oldest(db, Payout.created_at, Payout.status == "pending"), now
        ),
        "largest_pending": str(Decimal(largest or 0).quantize(Decimal("0.01"))),
        "paid_24h": await _count(
            db, Payout, Payout.status == "completed", Payout.created_at >= day_ago
        ),
        "paid_24h_value": await total(
            Payout.status == "completed", Payout.created_at >= day_ago
        ),
        # Money that left the platform's hands and did not arrive. Every one is
        # somebody who has not been paid and believes they have.
        "failed": await _count(db, Payout, Payout.status == "failed"),
        "failed_value": await total(Payout.status == "failed"),
        "processing": await _count(db, Payout, Payout.status == "processing"),
    }


async def support(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    open_count = await _count(db, SupportTicket, SupportTicket.status == "open")

    return {
        "waiting": open_count,
        "oldest_wait_minutes": _minutes_since(
            await _oldest(db, SupportTicket.created_at, SupportTicket.status == "open"), now
        ),
        # `pending` means an administrator has replied and the requester has
        # not. It is deliberately not counted as waiting — a number nobody can
        # act on is how people learn to ignore every badge in the console.
        "awaiting_requester": await _count(db, SupportTicket, SupportTicket.status == "pending"),
        "resolved_24h": await _count(
            db,
            SupportTicket,
            SupportTicket.status.in_(("resolved", "closed")),
            SupportTicket.updated_at >= day_ago,
        ),
        "unassigned": await _count(
            db, SupportTicket, SupportTicket.status == "open", SupportTicket.assigned_admin_id.is_(None)
        ),
        "total": await _count(db, SupportTicket),
    }
