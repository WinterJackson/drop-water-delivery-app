"""What a customer costs to acquire, and whether they pay it back.

`admin_analytics_service.retention_cohorts` already answers *do customers come
back*. It does not answer the question a business acts on, which is **whether
the ones who came back paid back what it cost to get them** — and the platform
has had every input for that on every order since the first one.

Three figures, all already written by `create_order`:

* `welcome_discount` — the share of a first bottle deposit the platform absorbs.
  Real money, spent on acquisition, recorded per order, summed nowhere.
* `platform_net` — the platform's cut after the M-Pesa or cash-handling tariff.
  The honest contribution figure; `platform_total` overstates it by the tariff.
* the order's own timestamps, which give the cohort and the month offset.

## The half the database cannot see

Posters at the stage, a branded boda, Meta ads, a referral paid in cash, the
person who walked the estate signing people up. None of it touches this
database.

A CAC built from the measured half alone would be precise, confident, and
typically wrong by an order of magnitude — *and wrong in the direction that
makes acquisition look cheap*. Somebody would then spend against it. So
`AcquisitionSpend` holds the entered half, and every figure returned here keeps
the two separate: `measured_cac`, `entered_cac`, `blended_cac`, plus
`has_entered_spend` so a screen can say "nothing recorded for this month"
rather than rendering a flatteringly small number as though it were the answer.

## Decisions worth stating

* **A cohort is the month of a customer's first *delivered* order**, not their
  signup. An account that never received water was not acquired, and a signup
  cohort makes every retention figure look worse than the business is.
* **Contribution is `platform_net`, never re-derived.** It is frozen on the
  order at creation, so raising a commission today cannot restate what a cohort
  earned last March — which is the whole point of freezing it.
* **Realised only. Nothing is projected.** An LTV extrapolated from four months
  of data is a guess wearing a number's clothes, and it is the number people
  raise budgets against.
* **Payback is the first month offset where cumulative contribution per acquired
  customer reaches CAC.** `None` means not yet, which is a fact about a young
  cohort rather than a failure.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.acquisition_spend_model import AcquisitionSpend
from models.order_model import Order

logger = logging.getLogger(__name__)

TWO = Decimal("0.01")
ZERO = Decimal("0")

#: The order states a cohort is built from.
#:
#: `delivered` only. A paid-but-undelivered order is not yet a customer the
#: platform has served, and a cancelled one that was refunded earned nothing —
#: counting either inflates both the cohort and its contribution, in the
#: direction that makes acquisition look like it worked.
ACQUIRED_STATUS = "delivered"

#: Bounded because each query below aggregates the orders table. Two years of
#: monthly cohorts is already a grid nobody reads.
MAX_MONTHS = 36


def _money(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(TWO, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def _month_floor(value: date | datetime) -> date:
    """The first of the month. Normalised on write *and* on read.

    "2026-08-14" and "2026-08-01" meaning the same month is exactly how a table
    like this ends up holding two rows for August that nobody can reconcile.
    """
    return date(value.year, value.month, 1)


def _offset(cohort: date, active: date) -> int:
    return (active.year - cohort.year) * 12 + (active.month - cohort.month)


def _window_start(months: int) -> datetime:
    """The first day of the month `months - 1` back, in UTC.

    Counted in calendar months rather than `months * 31` days: the day-based
    approximation drifts by a fortnight over a year and silently drops the
    oldest cohort — the one with the most history and therefore the only one
    that can show a completed payback.
    """
    today = datetime.now(timezone.utc)
    year, month = today.year, today.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


# ── The entered half ──────────────────────────────────────────────────────


async def record_spend(
    session: AsyncSession,
    *,
    period_month: date,
    channel: str,
    amount,
    note: Optional[str] = None,
    recorded_by: Optional[UUID] = None,
) -> dict:
    """Enter (or correct) one month's spend on one channel.

    An upsert rather than an insert. The ordinary case is "the invoice came in
    and it was 12,000 not 10,000", and making that a second row would double the
    month's spend — a CAC that doubles overnight is indistinguishable from a bad
    month, which is the worst kind of wrong number because it prompts action.

    **Does not commit.** The route stages its audit row in the same transaction
    and commits once, so the change and the record of who made it land together
    or not at all — the discipline `admin_service.record_audit` is built around.
    """
    cleaned_channel = (channel or "").strip()
    if not cleaned_channel:
        raise HTTPException(status_code=400, detail="Name the channel this was spent on.")

    value = _money(amount)
    if value < ZERO:
        raise HTTPException(
            status_code=400,
            detail="Acquisition spend cannot be negative. To remove an entry, delete it.",
        )

    month = _month_floor(period_month)
    if month > _month_floor(datetime.now(timezone.utc)):
        raise HTTPException(
            status_code=400,
            detail="That month has not happened yet. Record spend against the month it was spent in.",
        )

    statement = (
        pg_insert(AcquisitionSpend)
        .values(
            period_month=month,
            channel=cleaned_channel,
            amount=value,
            note=(note or "").strip() or None,
            recorded_by=recorded_by,
        )
        .on_conflict_do_update(
            constraint="uq_acquisition_period_channel",
            set_={
                "amount": value,
                "note": (note or "").strip() or None,
                "recorded_by": recorded_by,
                "updated_at": func.now(),
            },
        )
        .returning(AcquisitionSpend.id)
    )

    row_id = (await session.execute(statement)).scalar_one()

    return {
        "id": str(row_id),
        "period_month": month.isoformat(),
        "channel": cleaned_channel,
        "amount": str(value),
    }


async def list_spend(session: AsyncSession, *, months: int = 12) -> dict:
    """Everything entered inside the window, newest month first."""
    months = max(1, min(months, MAX_MONTHS))
    start = _window_start(months).date()

    rows = (
        await session.execute(
            select(AcquisitionSpend)
            .where(AcquisitionSpend.period_month >= start)
            .order_by(AcquisitionSpend.period_month.desc(), AcquisitionSpend.channel)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(row.id),
                "period_month": row.period_month.isoformat(),
                "channel": row.channel,
                "amount": str(_money(row.amount)),
                "note": row.note,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
        "total": str(sum((_money(r.amount) for r in rows), ZERO)),
    }


async def delete_spend(session: AsyncSession, *, spend_id: UUID) -> dict:
    """Remove an entry. Does not commit — see `record_spend`.

    Returns what was removed so the route can put it in the audit row's
    `before`: an amount deleted with no record of what it was is a hole in the
    CAC series that nobody can later explain.
    """
    row = await session.get(AcquisitionSpend, spend_id)
    if row is None:
        raise HTTPException(status_code=404, detail="That spend entry no longer exists.")

    removed = {
        "period_month": row.period_month.isoformat(),
        "channel": row.channel,
        "amount": str(_money(row.amount)),
    }
    await session.execute(delete(AcquisitionSpend).where(AcquisitionSpend.id == spend_id))
    return {"deleted": str(spend_id), "was": removed}


# ── The measured half, and the cohorts ────────────────────────────────────


async def _first_delivered_month(session: AsyncSession):
    """Subquery: each customer, and the month they were actually acquired.

    Over *all* history, not the window. A customer whose first delivery was two
    years ago belongs to that cohort and must not be re-acquired into this
    month's simply because the window starts after they joined — which is what a
    `MIN()` computed inside the window would do, and it would invent new
    customers out of loyal ones.
    """
    return (
        select(
            Order.customer_id.label("customer_id"),
            func.min(func.date_trunc("month", Order.created_at)).label("cohort"),
        )
        .where(
            Order.order_status == ACQUIRED_STATUS,
            Order.customer_id.isnot(None),
        )
        .group_by(Order.customer_id)
        .subquery()
    )


async def cohort_economics(
    session: AsyncSession, *, months: int = 12, entered: Optional[dict] = None
) -> dict:
    """Per cohort: what it cost, what it has returned, and when it broke even.

    Two aggregates and the pivot in Python. The grid is at most
    `months × months` cells, so assembling it here costs nothing and leaves the
    SQL readable — the same trade `retention_cohorts` makes.

    `entered` is the month → spend map, injectable so `acquisition_summary` can
    read the spend table **once** and hand it down. It needs the same map for
    its own totals, and loading it twice per page view is a redundant round trip
    on the one screen that is already the console's heaviest.
    """
    months = max(1, min(months, MAX_MONTHS))
    start = _window_start(months)
    first = await _first_delivered_month(session)

    # One pass: for every (cohort, active month), how many distinct customers
    # ordered, what the platform netted, and what it discounted away.
    rows = (
        await session.execute(
            select(
                first.c.cohort,
                func.date_trunc("month", Order.created_at).label("active"),
                func.count(func.distinct(Order.customer_id)).label("customers"),
                func.coalesce(func.sum(Order.platform_net), 0).label("net"),
                func.coalesce(func.sum(Order.welcome_discount), 0).label("discount"),
            )
            .join(first, Order.customer_id == first.c.customer_id)
            .where(
                Order.order_status == ACQUIRED_STATUS,
                first.c.cohort >= start,
            )
            .group_by(first.c.cohort, "active")
            .order_by(first.c.cohort)
        )
    ).all()

    if entered is None:
        entered = await _entered_by_month(session, start.date())

    grid: dict[date, dict[int, dict]] = {}
    for cohort_at, active_at, customers, net, discount in rows:
        if cohort_at is None or active_at is None:
            continue
        cohort = _month_floor(cohort_at)
        offset = _offset(cohort, _month_floor(active_at))
        if offset < 0:
            # Cannot happen while `cohort` is a MIN() over the same rows, but a
            # negative offset would silently corrupt every cumulative figure
            # below rather than raising, so it is dropped rather than trusted.
            logger.warning("Cohort %s has activity at a negative offset; ignoring.", cohort)
            continue
        grid.setdefault(cohort, {})[offset] = {
            "customers": int(customers or 0),
            "net": _money(net),
            "discount": _money(discount),
        }

    cohorts = []
    for cohort in sorted(grid):
        buckets = grid[cohort]
        size = buckets.get(0, {}).get("customers", 0)
        if size <= 0:
            # A cohort with no month-zero row is not a cohort — every customer
            # in it was acquired in a month whose first delivery we did not see.
            continue

        measured = sum((b["discount"] for b in buckets.values()), ZERO)
        entered_total = entered.get(cohort, ZERO)
        has_entered = cohort in entered

        cac_measured = _money(measured / size)
        cac_entered = _money(entered_total / size) if has_entered else None
        cac_blended = _money((measured + entered_total) / size)

        cumulative = ZERO
        series = []
        payback_month: Optional[int] = None
        for offset in range(0, max(buckets) + 1):
            bucket = buckets.get(offset)
            month_net = bucket["net"] if bucket else ZERO
            cumulative += month_net
            per_customer = _money(cumulative / size)
            if payback_month is None and per_customer >= cac_blended and cac_blended > ZERO:
                payback_month = offset
            series.append(
                {
                    "month": offset,
                    "customers": bucket["customers"] if bucket else 0,
                    "retention_pct": str(
                        (
                            Decimal((bucket["customers"] if bucket else 0)) / Decimal(size) * 100
                        ).quantize(Decimal("0.1"))
                    ),
                    "net": str(month_net),
                    "cumulative_net": str(_money(cumulative)),
                    "cumulative_per_customer": str(per_customer),
                }
            )

        cohorts.append(
            {
                "cohort": cohort.isoformat(),
                "size": size,
                "cac": {
                    "measured": str(cac_measured),
                    "entered": str(cac_entered) if cac_entered is not None else None,
                    "blended": str(cac_blended),
                    "has_entered_spend": has_entered,
                },
                # Realised, not projected. Named so nobody reads it as a
                # forecast: this is what these customers have paid so far.
                "realised_per_customer": series[-1]["cumulative_per_customer"] if series else "0.00",
                "payback_month": payback_month,
                "months": series,
            }
        )

    return {
        "cohorts": cohorts,
        "basis": {
            "status": ACQUIRED_STATUS,
            "contribution": "platform_net",
            "measured_spend": "welcome_discount",
        },
    }


async def _entered_by_month(session: AsyncSession, start: date) -> dict[date, Decimal]:
    rows = (
        await session.execute(
            select(
                AcquisitionSpend.period_month,
                func.coalesce(func.sum(AcquisitionSpend.amount), 0),
            )
            .where(AcquisitionSpend.period_month >= start)
            .group_by(AcquisitionSpend.period_month)
        )
    ).all()
    return {_month_floor(month): _money(total) for month, total in rows if month}


async def acquisition_summary(session: AsyncSession, *, months: int = 12) -> dict:
    """CAC by month, and the payback the completed cohorts actually achieved.

    Deliberately reports **completed** payback only. Averaging in cohorts too
    young to have paid back would report a payback period shorter than any
    cohort has ever achieved, which is the most persuasive kind of wrong number.
    """
    months = max(1, min(months, MAX_MONTHS))

    # Read once and hand it down. Both this function and `cohort_economics` need
    # the same map, and the naive version queried the spend table twice on every
    # view of the console's heaviest page.
    entered = await _entered_by_month(session, _window_start(months).date())
    economics = await cohort_economics(session, months=months, entered=entered)
    cohorts = economics["cohorts"]

    paid_back = [c for c in cohorts if c["payback_month"] is not None]

    total_customers = sum(c["size"] for c in cohorts)
    total_measured = sum(
        (Decimal(c["cac"]["measured"]) * c["size"] for c in cohorts), ZERO
    )

    # **Every shilling entered in the window**, not only the shillings that
    # happened to land in a month that acquired somebody.
    #
    # Summing per cohort was the obvious way to write this and it is wrong in
    # the one case that matters: a month where the business spent money and
    # acquired *nobody* has no cohort, so its spend was silently discarded and
    # never appeared in any CAC on the console. That month is the single most
    # important one on the screen — it is the definition of acquisition not
    # working — and the arithmetic was quietly hiding it.
    entered = await _entered_by_month(session, _window_start(months).date())
    total_entered = sum(entered.values(), ZERO)

    acquired_months = {date.fromisoformat(c["cohort"]) for c in cohorts}
    unattributed = sum(
        (amount for month, amount in entered.items() if month not in acquired_months),
        ZERO,
    )

    return {
        "customers_acquired": total_customers,
        "measured_spend": str(_money(total_measured)),
        "entered_spend": str(_money(total_entered)),
        #: Entered spend in months that acquired nobody. Reported on its own
        #: rather than folded away: it is money the business spent for no
        #: customers, and a blended CAC alone cannot show it.
        "unattributed_spend": str(_money(unattributed)),
        # `None` rather than 0 when nothing has been acquired: a CAC of zero
        # reads as "free", and free is a claim.
        "measured_cac": str(_money(total_measured / total_customers)) if total_customers else None,
        "blended_cac": (
            str(_money((total_measured + total_entered) / total_customers))
            if total_customers
            else None
        ),
        #: How much of the window has any entered spend at all. A blended CAC
        #: over a window that is mostly blank is a measured CAC with a
        #: misleading name, and the screen needs to be able to say so.
        "months_with_entered_spend": len(entered),
        "months_covered": len(cohorts),
        "cohorts_paid_back": len(paid_back),
        "median_payback_month": _median([c["payback_month"] for c in paid_back]),
        "best_cohort": (
            max(cohorts, key=lambda c: Decimal(c["realised_per_customer"]))["cohort"]
            if cohorts
            else None
        ),
    }


def _median(values: list[int]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2
