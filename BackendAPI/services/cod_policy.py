"""Who may pay cash, who may carry it, and how much.

Cash on delivery is the only place on this platform where money exists outside a
ledger. Between the customer handing over notes and the rider's wallet settling
at delivery, the platform's claim is a promise from somebody on a motorbike. The
float check already asked *can this rider cover it*; nothing asked **should this
rider be trusted with it**, and nothing asked anything at all about the customer.

Those are different questions and they fail differently:

* A rider with a large balance and four days on the platform passed the float
  check on their first day and could carry any number of cash orders at once.
* A brand-new account could place a cash order to a fake address, costing the
  rider a wasted trip and the vendor a prepared order. That is the standard
  opening move against every COD platform in this market, and it costs the
  attacker nothing — accounts are free.

## What this module is

One place that answers both, read by checkout, by acceptance, by completion and
by the release sweep. Every threshold is a `Platform_Settings` row, because the
right numbers for this are not knowable in advance and will move with the
platform's actual loss experience. Nothing here is a literal.

## The two ceilings, and why checkout uses the higher one

`cod_max_order_value_standard` is what an ordinary eligible rider may carry;
`cod_max_order_value_platinum` is the same for a rider who has earned the tier.
Checkout does not know who will accept the order, so it caps against the
**platinum** figure — the most any rider could take.

Capping checkout at the standard figure instead would be tidier and wrong: it
would make the platinum ceiling unreachable, since no order above the standard
one could ever exist to be accepted. A setting that can never bind is a setting
somebody will later spend an afternoon discovering is decorative.

The consequence is real and deliberate: an order between the two ceilings can
only be accepted by a Platinum rider, and `assert_rider_may_accept_cash` refuses
everybody else by name so the rider is told why rather than watching an order
they cannot take sit in the radar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_model import Order
from services.order_service import apply_status_transition

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")

#: A cash order is a live exposure from acceptance until it reaches a terminal
#: state. Shared with `settlement_service.OPEN_CASH_ORDER_STATUSES` in meaning —
#: imported rather than restated, because two lists of "still open" that drift
#: apart is how float and exposure come to disagree about the same order.
from services.settlement_service import OPEN_CASH_ORDER_STATUSES  # noqa: E402


def _money(value) -> Decimal:
    return Decimal(str(value or 0))


async def _config(session: AsyncSession):
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    return config


# ── What the platform knows about a rider ─────────────────────────────────


@dataclass(frozen=True)
class TrustAssessment:
    """Whether this rider may carry cash, and the evidence either way.

    `reasons` is written for the **rider**, not for a log. A refusal they cannot
    act on is a support ticket every time, and "you need 25 deliveries, you have
    11" is a thing somebody can go and do something about.
    """

    eligible: bool
    #: `blocked` | `standard` | `platinum`
    tier: str
    max_order_value: Decimal
    reasons: list[str] = field(default_factory=list)
    #: The measured figures, so a screen can show progress rather than a verdict.
    deliveries: int = 0
    completion_rate: float = 0.0
    rating: float = 0.0
    account_age_days: int = 0


async def _delivery_history(session: AsyncSession, rider_id) -> tuple[int, int]:
    """`(delivered, abandoned)` for this rider.

    "Abandoned" counts orders they accepted and did not finish — **excluding**
    cancellations by the vendor or the customer. A rider who loses an order
    because the store ran out of water has done nothing wrong, and counting it
    against them would make the completion gate punish the riders working with
    the least reliable stores.
    """
    delivered = int((
        await session.execute(
            select(func.count(Order.id)).where(
                and_(Order.deliverer_id == rider_id, Order.order_status == "delivered")
            )
        )
    ).scalar() or 0)

    abandoned = int((
        await session.execute(
            select(func.count(Order.id)).where(
                and_(
                    Order.deliverer_id == rider_id,
                    Order.order_status == "cancelled",
                    or_(
                        Order.cancellation_reason == None,  # noqa: E711
                        and_(
                            ~Order.cancellation_reason.like("cancelled_by_vendor%"),
                            ~Order.cancellation_reason.like("cancelled_by_customer%"),
                        ),
                    ),
                )
            )
        )
    ).scalar() or 0)

    return delivered, abandoned


async def assess_rider(session: AsyncSession, rider) -> TrustAssessment:
    """Six factors, evaluated live. No stored trust score.

    Deliberately computed rather than cached on the rider row. A stored score is
    a number that can be stale at exactly the moment it matters — a rider whose
    rating collapsed this morning would still be carrying yesterday's tier — and
    the query is a handful of indexed counts on a table already indexed by
    `deliverer_id`.
    """
    from models.deliverer_model import KYCStatus

    config = await _config(session)

    reasons: list[str] = []

    # 1. KYC. The platform's own guardrail: an errored or absent status is not
    #    permission, so this compares positively against `approved`.
    status = getattr(rider, "kyc_status", None)
    if status != KYCStatus.approved:
        reasons.append("Your account is not verified yet.")

    # 2. Suspension.
    if getattr(rider, "suspended_at", None) is not None or rider.is_active is False:
        reasons.append("Your account is suspended.")

    # 3. Deliveries completed.
    delivered, abandoned = await _delivery_history(session, rider.id)
    min_deliveries = config.get_int("cod_min_rider_deliveries")
    if delivered < min_deliveries:
        reasons.append(
            f"Cash orders need {min_deliveries} completed deliveries — you have {delivered}."
        )

    # 4. Completion rate. Undefined with no history, and the delivery count above
    #    already refuses that case, so an empty denominator is treated as perfect
    #    rather than as zero — otherwise a new rider fails two gates for one
    #    reason and the message contradicts itself.
    attempted = delivered + abandoned
    completion = (delivered / attempted) if attempted else 1.0
    min_completion = float(config.get("cod_min_rider_completion_rate"))
    if completion < min_completion:
        reasons.append(
            f"Cash orders need a {min_completion:.0%} completion rate — yours is {completion:.0%}."
        )

    # 5. Rating.
    rating = float(getattr(rider, "rating", 0) or 0)
    min_rating = float(config.get("cod_min_rider_rating"))
    if rating < min_rating:
        reasons.append(f"Cash orders need a {min_rating} rating — yours is {rating:.1f}.")

    # 6. Account age. A stolen or thrown-away account is worth most on day one.
    created = getattr(rider, "created_at", None)
    age_days = 0
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days
    min_age = config.get_int("cod_min_rider_account_age_days")
    if age_days < min_age:
        reasons.append(
            f"Cash orders open up after {min_age} days on the platform — "
            f"you are {age_days} day(s) in."
        )

    platinum = bool(getattr(rider, "is_platinum", False))
    tier = "blocked" if reasons else ("platinum" if platinum else "standard")
    ceiling = config.get_decimal(
        "cod_max_order_value_platinum" if tier == "platinum" else "cod_max_order_value_standard"
    )

    return TrustAssessment(
        eligible=not reasons,
        tier=tier,
        max_order_value=ceiling if tier != "blocked" else ZERO,
        reasons=reasons,
        deliveries=delivered,
        completion_rate=completion,
        rating=rating,
        account_age_days=age_days,
    )


# ── Exposure already carried ──────────────────────────────────────────────


async def open_cash_orders(session: AsyncSession, rider_id) -> int:
    """How many cash orders this rider is carrying right now."""
    return int((
        await session.execute(
            select(func.count(Order.id)).where(
                and_(
                    Order.deliverer_id == rider_id,
                    Order.payment_method == "cash",
                    Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
                )
            )
        )
    ).scalar() or 0)


async def cash_taken_today(session: AsyncSession, rider_id) -> Decimal:
    """Cash value this rider has taken on since midnight.

    Counts every cash order they accepted today whatever became of it —
    delivered, still open, or cancelled after the fact. The ceiling is about how
    much of the platform's money passes through one person in a day, and an
    order that was carried and then cancelled still passed through them.
    """
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    return _money((
        await session.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                and_(
                    Order.deliverer_id == rider_id,
                    Order.payment_method == "cash",
                    Order.updated_at >= since,
                )
            )
        )
    ).scalar())


# ── The two gates ─────────────────────────────────────────────────────────


async def assert_customer_may_pay_cash(
    session: AsyncSession, *, user, total: Decimal, distance_km: float, vendor=None
) -> None:
    """Checkout. Refuses before an order exists, so nothing has to be unwound.

    Four things, and the first-order rule is the one that matters most: a fake
    address plus cash costs the rider a wasted trip and the vendor a prepared
    order, and is free to attempt. Everything else here caps the size of a
    single bad one.

    `vendor` is optional only so the existing callers that have no store in hand
    keep working; every checkout path passes it. The store's own refusal is
    read through `vendor_availability` rather than off the column, because the
    platform can take that decision back (`vendor_may_decline_cash`) and a
    second reader would keep honouring a decline the platform had withdrawn.
    """
    config = await _config(session)

    if not config.get_bool("cod_enabled"):
        raise HTTPException(
            status_code=400,
            detail="Cash on delivery is not available at the moment. Please pay by M-Pesa.",
        )

    # The store's own decision. A shop with no float — or one that has just been
    # robbed — must be able to decline cash, and until this check existed the
    # platform sent them cash orders regardless of what they had set. Refused
    # here rather than in `vendor_availability` because this module is the only
    # thing on the platform that decides whether an order may be paid in cash.
    if vendor is not None:
        from services import vendor_availability

        state = await vendor_availability.store_state(session, vendor)
        if not state.accepts_cash:
            raise HTTPException(status_code=400, detail=state.cash_reason)

    ceiling = config.get_decimal("cod_max_order_value_platinum")
    if _money(total) > ceiling:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Orders over KSH {ceiling:,.0f} cannot be paid in cash. "
                "Pay by M-Pesa and the order goes through immediately."
            ),
        )

    max_km = config.get_int("cod_max_distance_km")
    if distance_km is not None and float(distance_km) > max_km:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cash is only available within {max_km} km. "
                "Pay by M-Pesa for this address."
            ),
        )

    required = config.get_int("cod_min_customer_completed_orders")
    if required <= 0:
        return

    completed = int((
        await session.execute(
            select(func.count(Order.id)).where(
                and_(Order.customer_id == user.id, Order.order_status == "delivered")
            )
        )
    ).scalar() or 0)

    if completed < required:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cash on delivery opens up after your first completed order. "
                "Pay by M-Pesa this time and it will be available next order."
            ),
        )


async def assert_rider_may_accept_cash(session: AsyncSession, *, rider, order) -> TrustAssessment:
    """Acceptance. Everything the float check never asked.

    Returns the assessment so the caller can log or surface it. Raises 403 for a
    trust failure and 409 for a limit — different problems: one is about who the
    rider is, the other about what they are already carrying, and only the
    second gets better by waiting.
    """
    config = await _config(session)

    assessment = await assess_rider(session, rider)
    if not assessment.eligible:
        raise HTTPException(
            status_code=403,
            detail={
                "type": "cod_not_eligible",
                "message": "You cannot take cash orders yet. " + " ".join(assessment.reasons),
                "reasons": assessment.reasons,
            },
        )

    # `total_amount` is the column; `total` is the quote's field name and does
    # not exist on the model. Accepting either keeps this callable with a quote
    # in a test without the production path silently summing zero.
    total = _money(getattr(order, "total_amount", None) or getattr(order, "total", 0))
    if total > assessment.max_order_value:
        raise HTTPException(
            status_code=403,
            detail={
                "type": "cod_value_ceiling",
                "message": (
                    f"This cash order is KSH {total:,.0f}. Your limit is "
                    f"KSH {assessment.max_order_value:,.0f}"
                    + (
                        " — Platinum riders can carry more."
                        if assessment.tier == "standard"
                        else "."
                    )
                ),
            },
        )

    concurrent = config.get_int("cod_max_concurrent_orders")
    carrying = await open_cash_orders(session, rider.id)
    if carrying >= concurrent:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You are already carrying {carrying} cash order(s), which is the limit. "
                "Deliver one and this opens up again."
            ),
        )

    daily_cap = config.get_decimal("cod_max_daily_exposure")
    taken = await cash_taken_today(session, rider.id)
    if taken + total > daily_cap:
        raise HTTPException(
            status_code=409,
            detail=(
                f"That would take you past your KSH {daily_cap:,.0f} cash limit for today "
                f"(you are at KSH {taken:,.0f}). M-Pesa orders are unaffected."
            ),
        )

    return assessment


# ── Completion, and the release sweep ─────────────────────────────────────


async def photo_required(session: AsyncSession, order) -> bool:
    """Whether this delivery needs a photo regardless of the bottle count.

    The platform already demands one on a bottle shortfall. On a cash order the
    photo is what makes "he never delivered it" a decidable question at all —
    there is no M-Pesa receipt to point at, so without it the only record that
    the goods arrived is the word of the person holding the money.
    """
    if getattr(order, "payment_method", None) != "cash":
        return False
    config = await _config(session)
    return config.get_bool("cod_require_delivery_photo")


async def release_unclaimed_cash_orders(session: AsyncSession) -> dict:
    """Return abandoned cash orders to the pool and free the rider's float.

    Float is committed from acceptance until a terminal state, so one order a
    rider took and forgot locked that money **indefinitely** — and the customer
    waited on a delivery nobody was bringing. Both problems, one sweep.

    The order goes back to `unassigned` rather than being cancelled: the customer
    still wants their water and the stock is still committed to them. That is the
    same distinction `deliverer_service` draws between a rider dropping an order
    and an order being cancelled, and it is the reason nothing is reverted here.
    """
    config = await _config(session)
    minutes = config.get_int("cod_unclaimed_release_minutes")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    rows = (
        await session.execute(
            select(Order)
            .where(
                and_(
                    Order.payment_method == "cash",
                    Order.deliverer_id != None,  # noqa: E711
                    Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
                    Order.updated_at < cutoff,
                )
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).scalars().all()

    released = 0
    for order in rows:
        try:
            previous_rider = order.deliverer_id
            order.deliverer_id = None
            apply_status_transition(order, "unassigned")
            order.cancellation_reason = (
                f"cash float released after {minutes} minutes without delivery"
            )

            # The rider becomes available again — they are not carrying this any
            # more, and leaving them flagged busy would strand them.
            from models.deliverer_model import Deliverer

            rider = (
                await session.execute(
                    select(Deliverer).where(Deliverer.id == previous_rider).with_for_update()
                )
            ).scalars().first()
            if rider is not None:
                rider.is_available = True

            await session.commit()
            released += 1
            logger.warning(
                "Released cash order %s from rider %s after %s minutes.",
                order.id, previous_rider, minutes,
            )
        except Exception:
            await session.rollback()
            logger.exception("Could not release cash order %s", order.id)

    return {"cash_orders_released": released}


# ── What operations needs to see ──────────────────────────────────────────


async def exposure_summary(session: AsyncSession) -> dict:
    """Cash currently in riders' hands, and who is carrying it.

    The one figure nobody could produce. `committed_cash_float` answers it per
    rider on their own screen; the platform's own total — how much of its money
    is on motorbikes right now — existed only as a query somebody would have to
    write. A number nobody can see is a limit nobody can set.
    """
    from models.deliverer_model import Deliverer

    rows = (
        await session.execute(
            select(
                Order.deliverer_id,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.min(Order.updated_at),
            )
            .where(
                and_(
                    Order.payment_method == "cash",
                    Order.deliverer_id != None,  # noqa: E711
                    Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
                )
            )
            .group_by(Order.deliverer_id)
            .order_by(func.coalesce(func.sum(Order.total_amount), 0).desc())
            .limit(100)
        )
    ).all()

    if not rows:
        return {"total_at_risk": "0.00", "orders_open": 0, "riders_carrying": 0, "carriers": []}

    names = dict(
        (
            await session.execute(
                select(Deliverer.id, Deliverer.full_name).where(
                    Deliverer.id.in_([r[0] for r in rows])
                )
            )
        ).all()
    )

    now = datetime.now(timezone.utc)
    carriers = []
    for rider_id, count, value, oldest in rows:
        held_minutes = None
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            held_minutes = int((now - oldest).total_seconds() // 60)
        carriers.append({
            "rider_id": str(rider_id),
            "rider_name": names.get(rider_id),
            "orders": int(count or 0),
            "value": str(_money(value)),
            # Age, beside the amount. The float sweep acts on this, and a
            # figure the console cannot see is one operations learns about from
            # the rider complaining their balance is locked.
            "held_minutes": held_minutes,
        })

    return {
        "total_at_risk": str(_money(sum(Decimal(c["value"]) for c in carriers))),
        "orders_open": sum(c["orders"] for c in carriers),
        "riders_carrying": len(carriers),
        "carriers": carriers,
    }
