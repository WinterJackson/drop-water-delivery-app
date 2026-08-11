"""Business analytics over the revenue ledger the schema already carries.

`Order` records `vendor_commission`, `service_fee`, `rider_commission`,
`delivery_markup`, `surge_fee`, `platform_total`, `vendor_net`, `rider_net`,
`commission_lost`, `wallet_discount` and `welcome_discount` per order. All of it
was being written and none of it read — `/admin/revenue` summed five columns and
cast them to `float`.

Everything here is `Decimal` and crosses the wire as a string. A take rate that
disagrees with the ledger in the third decimal place is a number people argue
with instead of using.

Aggregation happens in Postgres, not Python: pulling every order into the web
process to sum it works at 14 orders and stops working long before it matters.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer
from models.order_model import Order
from models.user_model import User
from models.vendor_model import Vendor

logger = logging.getLogger(__name__)

Grain = Literal["day", "week", "month"]

#: Postgres `date_trunc` units, allow-listed rather than interpolated — the
#: value reaches SQL, and a free string there is an injection.
GRAINS: dict[str, str] = {"day": "day", "week": "week", "month": "month"}

#: The revenue split, in the order the console renders it.
COMPONENTS = (
    ("vendor_commissions", Order.vendor_commission),
    ("service_fees", Order.service_fee),
    ("rider_commissions", Order.rider_commission),
    ("delivery_markups", Order.delivery_markup),
    ("surge_fees", Order.surge_fee),
)


def money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _window(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def _paid(start: datetime, end: datetime) -> list:
    """Paid orders only.

    Revenue is recognised on payment, not on order creation — an abandoned cart
    that never paid is not a discount, it is not a sale.
    """
    return [
        Order.payment_status == "paid",
        Order.created_at >= start,
        Order.created_at < end,
    ]


async def timeseries(session: AsyncSession, *, days: int = 30, grain: Grain = "day") -> dict:
    """Revenue, GMV and order count over time.

    Buckets with no orders are filled in Python rather than left out. A chart
    that silently omits a zero day draws a straight line across an outage and
    makes it look like an ordinary Tuesday.
    """
    start, end = _window(days)
    unit = GRAINS.get(grain, "day")
    bucket = func.date_trunc(unit, Order.created_at).label("bucket")

    rows = (
        await session.execute(
            select(
                bucket,
                func.coalesce(func.sum(Order.platform_total), 0),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.count(Order.id),
            )
            .where(*_paid(start, end))
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()

    found = {
        row[0].date().isoformat(): {
            "revenue": money(row[1]),
            "gmv": money(row[2]),
            "orders": int(row[3] or 0),
        }
        for row in rows
        if row[0] is not None
    }

    step = {"day": 1, "week": 7, "month": 30}[unit]
    points = []
    cursor = start.date()
    while cursor <= end.date():
        key = cursor.isoformat()
        points.append({"date": key, **found.get(key, {"revenue": "0.00", "gmv": "0.00", "orders": 0})})
        cursor += timedelta(days=step)

    return {"grain": unit, "points": points}


async def unit_economics(session: AsyncSession, *, days: int = 30) -> dict:
    """What one order is actually worth, and where the money goes.

    The averages are computed as `SUM / COUNT` in Postgres rather than `AVG` per
    row, because `AVG` over a nullable column silently ignores the nulls and
    quietly changes the denominator between components.
    """
    start, end = _window(days)

    selections = [
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount), 0),
        func.coalesce(func.sum(Order.platform_total), 0),
        func.coalesce(func.sum(Order.vendor_net), 0),
        func.coalesce(func.sum(Order.rider_net), 0),
        func.coalesce(func.sum(Order.commission_lost), 0),
        func.coalesce(func.sum(Order.wallet_discount + Order.welcome_discount), 0),
        func.coalesce(func.avg(cast(Order.distance_km, Numeric)), 0),
    ]
    selections += [func.coalesce(func.sum(column), 0) for _, column in COMPONENTS]

    row = (await session.execute(select(*selections).where(*_paid(start, end)))).one()

    orders = int(row[0] or 0)
    gmv = Decimal(row[1] or 0)
    revenue = Decimal(row[2] or 0)

    def per_order(total) -> str:
        return money(Decimal(total or 0) / orders) if orders else "0.00"

    return {
        "window_days": days,
        "orders": orders,
        "gmv": money(gmv),
        "revenue": money(revenue),
        "vendor_net": money(row[3]),
        "rider_net": money(row[4]),
        "commission_lost": money(row[5]),
        "discounts_given": money(row[6]),
        "avg_distance_km": str(Decimal(row[7] or 0).quantize(Decimal("0.01"))),
        "avg_order_value": per_order(gmv),
        "avg_revenue_per_order": per_order(revenue),
        "take_rate_pct": (
            str((revenue / gmv * 100).quantize(Decimal("0.01"))) if gmv else "0.00"
        ),
        "breakdown": {
            name: money(row[8 + index]) for index, (name, _) in enumerate(COMPONENTS)
        },
    }


async def operations_health(session: AsyncSession, *, days: int = 30) -> dict:
    """The numbers that say whether the platform is working, not how much it earned.

    Cancellation and dispute rates are counted over *all* orders in the window,
    not just paid ones — an order cancelled before payment is exactly the
    failure being measured, and excluding it would report a perfect record.
    """
    start, end = _window(days)
    window = [Order.created_at >= start, Order.created_at < end]

    row = (
        await session.execute(
            select(
                func.count(Order.id),
                func.count(case((Order.order_status == "cancelled", 1))),
                func.count(case((Order.order_status == "delivered", 1))),
                func.count(case((Order.order_status.in_(("mismatch_pending", "pending_review")), 1))),
                func.coalesce(func.avg(cast(Order.delivery_time, Numeric)), 0),
            ).where(*window)
        )
    ).one()

    total = int(row[0] or 0)

    def pct(count) -> str:
        return str((Decimal(count or 0) / total * 100).quantize(Decimal("0.01"))) if total else "0.00"

    return {
        "window_days": days,
        "orders": total,
        "delivered": int(row[2] or 0),
        "cancelled": int(row[1] or 0),
        "under_review": int(row[3] or 0),
        "cancellation_rate_pct": pct(row[1]),
        "dispute_rate_pct": pct(row[3]),
        "avg_delivery_minutes": str(Decimal(row[4] or 0).quantize(Decimal("0.1"))),
    }


async def leaderboard(
    session: AsyncSession, *, kind: Literal["vendor", "rider"], days: int = 30, limit: int = 10
) -> dict:
    """Who is carrying the platform.

    Joined and grouped in the database. The obvious alternative — fetch the
    orders, group them in Python — is the query that quietly becomes the slowest
    thing in the console.
    """
    start, end = _window(days)

    if kind == "vendor":
        model, join_column, name = Vendor, Order.vendor_id, Vendor.business_name
    else:
        model, join_column, name = Deliverer, Order.deliverer_id, Deliverer.name

    rows = (
        await session.execute(
            select(
                model.id,
                name,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.coalesce(func.sum(Order.platform_total), 0),
                model.rating,
            )
            .join(model, join_column == model.id)
            .where(*_paid(start, end))
            .group_by(model.id, name, model.rating)
            .order_by(func.coalesce(func.sum(Order.total_amount), 0).desc())
            .limit(limit)
        )
    ).all()

    return {
        "kind": kind,
        "window_days": days,
        "items": [
            {
                "id": str(row[0]),
                "name": row[1],
                "orders": int(row[2] or 0),
                "gmv": money(row[3]),
                "revenue": money(row[4]),
                "rating": float(row[5]) if row[5] is not None else None,
            }
            for row in rows
        ],
    }


async def retention_cohorts(session: AsyncSession, *, months: int = 6) -> dict:
    """Do customers come back?

    For bottled water this is *the* question — it is a repeat purchase or it is
    nothing. Customers are grouped by the month of their first paid order, and
    each cell is the share of that cohort who ordered again in a later month.

    Two aggregates in the database and the pivot in Python: the cohort grid is
    at most `months × months` cells, so assembling it here costs nothing and
    keeps the SQL legible.
    """
    start = datetime.now(timezone.utc) - timedelta(days=months * 31)

    first_order = (
        select(
            Order.customer_id.label("customer_id"),
            func.min(func.date_trunc("month", Order.created_at)).label("cohort"),
        )
        .where(Order.payment_status == "paid", Order.customer_id.isnot(None))
        .group_by(Order.customer_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                first_order.c.cohort,
                func.date_trunc("month", Order.created_at).label("active"),
                func.count(func.distinct(Order.customer_id)),
            )
            .join(first_order, Order.customer_id == first_order.c.customer_id)
            .where(Order.payment_status == "paid", first_order.c.cohort >= start)
            .group_by(first_order.c.cohort, "active")
            .order_by(first_order.c.cohort)
        )
    ).all()

    cohorts: dict[str, dict[int, int]] = {}
    for cohort_at, active_at, customers in rows:
        if cohort_at is None or active_at is None:
            continue
        key = cohort_at.date().isoformat()
        offset = (active_at.year - cohort_at.year) * 12 + (active_at.month - cohort_at.month)
        cohorts.setdefault(key, {})[offset] = int(customers or 0)

    return {
        "cohorts": [
            {
                "cohort": key,
                "size": buckets.get(0, 0),
                "retention": [
                    {
                        "month": offset,
                        "customers": buckets.get(offset, 0),
                        "pct": (
                            str(
                                (Decimal(buckets.get(offset, 0)) / Decimal(buckets[0]) * 100).quantize(
                                    Decimal("0.1")
                                )
                            )
                            if buckets.get(0)
                            else "0.0"
                        ),
                    }
                    for offset in range(0, min(months, max(buckets) + 1 if buckets else 1))
                ],
            }
            for key, buckets in sorted(cohorts.items())
        ]
    }


async def growth(session: AsyncSession, *, days: int = 30) -> dict:
    """New accounts per type, and how that compares with the previous window.

    The comparison is against the immediately preceding window of the same
    length, which is the only comparison that does not require explaining.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    previous_start = start - timedelta(days=days)

    async def count(model, since, until) -> int:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.created_at >= since, model.created_at < until)
                )
            ).scalar()
            or 0
        )

    out = {}
    for label, model in (("customers", User), ("riders", Deliverer), ("vendors", Vendor)):
        current = await count(model, start, end)
        prior = await count(model, previous_start, start)
        out[label] = {
            "current": current,
            "previous": prior,
            "change_pct": (
                str((Decimal(current - prior) / Decimal(prior) * 100).quantize(Decimal("0.1")))
                if prior
                # No previous accounts is not "infinite growth"; it is a number
                # with no meaningful denominator, and the console says so.
                else None
            ),
        }

    return {"window_days": days, **out}


# ══════════════════════════════════════════════════════════════════════════
# The rest of the picture.
#
# Everything above answers "how much did we make". These answer "what is
# actually happening" — where demand is, when it arrives, what sells, whether
# riders and vendors are keeping up, and how much money the platform is
# currently exposed to.
#
# Split by *sensitivity*, not by screen: `float_exposure` and `payment_mix`
# read balances and payment instruments and are gated on `finance.read`, while
# demand and fulfilment are operational and ride on `analytics.read`. The route
# assembles whichever the caller is entitled to, so an analyst gets a working
# page rather than a 403.
# ══════════════════════════════════════════════════════════════════════════


async def status_funnel(session: AsyncSession, *, days: int = 30) -> dict:
    """Where orders end up, and where they fall out.

    Counted over every order in the window rather than paid ones: an order
    abandoned before payment is precisely the leak being measured, and
    filtering on `payment_status = 'paid'` would report a funnel with no top.
    """
    start, end = _window(days)
    rows = (
        await session.execute(
            select(Order.order_status, func.count(Order.id))
            .where(Order.created_at >= start, Order.created_at < end)
            .group_by(Order.order_status)
            .order_by(func.count(Order.id).desc())
        )
    ).all()

    total = sum(int(r[1] or 0) for r in rows)
    return {
        "window_days": days,
        "total": total,
        "statuses": [
            {
                "status": r[0] or "unknown",
                "count": int(r[1] or 0),
                "pct": str((Decimal(r[1] or 0) / total * 100).quantize(Decimal("0.1")))
                if total
                else "0.0",
            }
            for r in rows
        ],
    }


async def payment_mix(session: AsyncSession, *, days: int = 30) -> dict:
    """Cash versus M-Pesa, and how much of each is still unpaid.

    This is the platform's cash-float risk in one query: a wholesale cash order
    debits the vendor's wallet at delivery, so the share of cash orders is the
    share of revenue the platform is fronting.
    """
    start, end = _window(days)

    rows = (
        await session.execute(
            select(
                Order.payment_method,
                Order.payment_status,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .where(Order.created_at >= start, Order.created_at < end)
            .group_by(Order.payment_method, Order.payment_status)
        )
    ).all()

    methods: dict[str, dict] = {}
    for method, status, count, amount in rows:
        key = method or "unknown"
        entry = methods.setdefault(key, {"method": key, "orders": 0, "value": Decimal(0), "unpaid": 0})
        entry["orders"] += int(count or 0)
        entry["value"] += Decimal(amount or 0)
        if status != "paid":
            entry["unpaid"] += int(count or 0)

    return {
        "window_days": days,
        "methods": [
            {**entry, "value": money(entry["value"])}
            for entry in sorted(methods.values(), key=lambda e: e["orders"], reverse=True)
        ],
    }


async def demand_pattern(session: AsyncSession, *, days: int = 90) -> dict:
    """When orders arrive, by hour of day and day of week.

    This is what rider shift planning is built from: knowing that Saturday
    10:00 is triple Tuesday 15:00 is the difference between paying riders to
    wait and having nobody available.

    `EXTRACT` runs in Postgres against the timestamp; doing it in Python would
    mean fetching every order.
    """
    start, end = _window(days)

    rows = (
        await session.execute(
            select(
                func.extract("dow", Order.created_at),
                func.extract("hour", Order.created_at),
                func.count(Order.id),
            )
            .where(Order.created_at >= start, Order.created_at < end)
            .group_by(func.extract("dow", Order.created_at), func.extract("hour", Order.created_at))
        )
    ).all()

    # Dense grid: an hour with no orders is a real, useful zero — it is when
    # nobody needs to be on shift.
    grid = {(d, h): 0 for d in range(7) for h in range(24)}
    for dow, hour, count in rows:
        if dow is None or hour is None:
            continue
        grid[(int(dow), int(hour))] = int(count or 0)

    peak = max(grid.values()) if grid else 0
    return {
        "window_days": days,
        "peak": peak,
        "cells": [
            {"dow": d, "hour": h, "orders": grid[(d, h)]}
            for d in range(7)
            for h in range(24)
        ],
    }


async def geographic_demand(session: AsyncSession, *, days: int = 90, limit: int = 25) -> dict:
    """Demand by H3 cell — where to recruit vendors and station riders.

    `h3_index_res8` is already written on every order for dispatch, so this is
    a group-by rather than a spatial scan.
    """
    start, end = _window(days)

    rows = (
        await session.execute(
            select(
                Order.h3_index_res8,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.avg(cast(Order.distance_km, Numeric)),
            )
            .where(
                Order.created_at >= start,
                Order.created_at < end,
                Order.h3_index_res8.isnot(None),
            )
            .group_by(Order.h3_index_res8)
            .order_by(func.count(Order.id).desc())
            .limit(limit)
        )
    ).all()

    return {
        "window_days": days,
        "cells": [
            {
                "h3": r[0],
                "orders": int(r[1] or 0),
                "gmv": money(r[2]),
                "avg_distance_km": str(Decimal(r[3] or 0).quantize(Decimal("0.01"))),
            }
            for r in rows
        ],
    }


async def product_performance(session: AsyncSession, *, days: int = 30, limit: int = 20) -> dict:
    """What actually sells, by product and by category.

    Joined through `Order_Items`, so quantity is real units sold rather than a
    count of orders that happened to mention the product.
    """
    from models.order_model import OrderItem
    from models.product_model import Product

    start, end = _window(days)
    joined = [
        OrderItem.order_id == Order.id,
    ]

    products = (
        await session.execute(
            select(
                Product.id,
                Product.name,
                Product.category,
                func.sum(OrderItem.quantity),
                func.coalesce(func.sum(OrderItem.Subtotal), 0),
            )
            .join(Order, *joined)
            .join(Product, OrderItem.product_id == Product.id)
            .where(*_paid(start, end))
            .group_by(Product.id, Product.name, Product.category)
            .order_by(func.coalesce(func.sum(OrderItem.Subtotal), 0).desc())
            .limit(limit)
        )
    ).all()

    categories = (
        await session.execute(
            select(
                Product.category,
                func.sum(OrderItem.quantity),
                func.coalesce(func.sum(OrderItem.Subtotal), 0),
            )
            .join(Order, *joined)
            .join(Product, OrderItem.product_id == Product.id)
            .where(*_paid(start, end))
            .group_by(Product.category)
            .order_by(func.coalesce(func.sum(OrderItem.Subtotal), 0).desc())
        )
    ).all()

    return {
        "window_days": days,
        "products": [
            {
                "id": str(r[0]),
                "name": r[1],
                "category": r[2],
                "units": int(r[3] or 0),
                "revenue": money(r[4]),
            }
            for r in products
        ],
        "categories": [
            {"category": r[0] or "uncategorised", "units": int(r[1] or 0), "revenue": money(r[2])}
            for r in categories
        ],
    }


async def fulfilment(session: AsyncSession, *, days: int = 30) -> dict:
    """Delivery distance and vehicle mix, plus how far the average order travels.

    Distance buckets rather than a mean: the mean hides the tail, and the tail
    is where the delivery-fee model either works or loses money.
    """
    start, end = _window(days)

    buckets = case(
        (cast(Order.distance_km, Numeric) < 1, "under 1km"),
        (cast(Order.distance_km, Numeric) < 3, "1-3km"),
        (cast(Order.distance_km, Numeric) < 5, "3-5km"),
        (cast(Order.distance_km, Numeric) < 10, "5-10km"),
        else_="over 10km",
    )

    distance = (
        await session.execute(
            select(buckets, func.count(Order.id), func.coalesce(func.sum(Order.delivery_fee), 0))
            .where(*_paid(start, end), Order.distance_km.isnot(None))
            .group_by(buckets)
        )
    ).all()

    vehicles = (
        await session.execute(
            select(
                Order.vehicle_class,
                func.count(Order.id),
                func.coalesce(func.avg(cast(Order.delivery_time, Numeric)), 0),
            )
            .where(*_paid(start, end))
            .group_by(Order.vehicle_class)
        )
    ).all()

    types = (
        await session.execute(
            select(Order.delivery_type, func.count(Order.id))
            .where(*_paid(start, end))
            .group_by(Order.delivery_type)
        )
    ).all()

    return {
        "window_days": days,
        "distance_buckets": [
            {"bucket": r[0], "orders": int(r[1] or 0), "delivery_fees": money(r[2])}
            for r in distance
        ],
        "vehicles": [
            {
                "vehicle": r[0] or "unknown",
                "orders": int(r[1] or 0),
                "avg_minutes": str(Decimal(r[2] or 0).quantize(Decimal("0.1"))),
            }
            for r in vehicles
        ],
        "delivery_types": [
            {"type": r[0] or "unknown", "orders": int(r[1] or 0)} for r in types
        ],
    }


async def customer_behaviour(session: AsyncSession, *, days: int = 90) -> dict:
    """Repeat rate, and how concentrated revenue is.

    Repeat rate is the number that decides whether this business works. The
    concentration figure — share of GMV from the top decile — is the one that
    says how exposed it is if a handful of customers leave.
    """
    start, end = _window(days)

    per_customer = (
        select(
            Order.customer_id.label("customer_id"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("spend"),
        )
        .where(*_paid(start, end), Order.customer_id.isnot(None))
        .group_by(Order.customer_id)
        .subquery()
    )

    summary = (
        await session.execute(
            select(
                func.count(),
                func.count(case((per_customer.c.orders > 1, 1))),
                func.coalesce(func.sum(per_customer.c.spend), 0),
                func.coalesce(func.avg(per_customer.c.orders), 0),
            ).select_from(per_customer)
        )
    ).one()

    customers = int(summary[0] or 0)
    repeat = int(summary[1] or 0)
    total_spend = Decimal(summary[2] or 0)

    top_decile_count = max(1, customers // 10) if customers else 0
    top_spend = Decimal(0)
    if top_decile_count:
        top_rows = (
            await session.execute(
                select(per_customer.c.spend)
                .order_by(per_customer.c.spend.desc())
                .limit(top_decile_count)
            )
        ).scalars().all()
        top_spend = sum((Decimal(v or 0) for v in top_rows), Decimal(0))

    welcome = (
        await session.execute(
            select(func.count(Order.id)).where(*_paid(start, end), Order.is_welcome_offer.is_(True))
        )
    ).scalar()

    return {
        "window_days": days,
        "customers_who_ordered": customers,
        "repeat_customers": repeat,
        "repeat_rate_pct": str((Decimal(repeat) / customers * 100).quantize(Decimal("0.1")))
        if customers
        else "0.0",
        "avg_orders_per_customer": str(Decimal(summary[3] or 0).quantize(Decimal("0.01"))),
        "avg_spend_per_customer": money(total_spend / customers) if customers else "0.00",
        "top_decile_share_pct": str((top_spend / total_spend * 100).quantize(Decimal("0.1")))
        if total_spend
        else "0.0",
        "welcome_offer_orders": int(welcome or 0),
    }


async def supply_health(session: AsyncSession, *, days: int = 30) -> dict:
    """Whether there are enough riders and vendors, and how busy they are.

    "Active" means *delivered an order in the window*, not "has an account" —
    which is the number that looked healthy right up until nobody was available.
    """
    start, end = _window(days)

    active_riders = (
        await session.execute(
            select(func.count(func.distinct(Order.deliverer_id))).where(
                *_paid(start, end), Order.deliverer_id.isnot(None)
            )
        )
    ).scalar()

    active_vendors = (
        await session.execute(
            select(func.count(func.distinct(Order.vendor_id))).where(
                *_paid(start, end), Order.vendor_id.isnot(None)
            )
        )
    ).scalar()

    riders = (
        await session.execute(
            select(
                func.count(),
                func.count(case((Deliverer.kyc_status == "approved", 1))),
                # "Deployable" means *can actually be given an order right now*:
                # available, KYC-approved and not suspended. Counting
                # `is_available` alone reported 30 riders ready to work on a
                # platform where none had passed KYC — the flag defaults to
                # true at signup, so it measured registrations, not supply.
                func.count(
                    case(
                        (
                            (Deliverer.is_available.is_(True))
                            & (Deliverer.kyc_status == "approved")
                            & (Deliverer.suspended_at.is_(None)),
                            1,
                        )
                    )
                ),
                func.count(case((Deliverer.suspended_at.isnot(None), 1))),
                func.coalesce(func.avg(Deliverer.acceptance_rate), 0),
                func.count(case((Deliverer.is_available.is_(True), 1))),
            ).select_from(Deliverer)
        )
    ).one()

    vendors = (
        await session.execute(
            select(
                func.count(),
                func.count(case((Vendor.is_online.is_(True), 1))),
                func.count(case((Vendor.suspended_at.isnot(None), 1))),
                func.count(case((Vendor.verification_status == "verified", 1))),
            ).select_from(Vendor)
        )
    ).one()

    orders = (
        await session.execute(select(func.count(Order.id)).where(*_paid(start, end)))
    ).scalar()

    return {
        "window_days": days,
        "riders": {
            "total": int(riders[0] or 0),
            "kyc_approved": int(riders[1] or 0),
            #: Available, KYC-approved and not suspended — riders who can be
            #: dispatched to right now.
            "deployable_now": int(riders[2] or 0),
            #: Flag-only, for contrast. A large gap between the two means
            #: onboarding is the bottleneck, not recruitment.
            "marked_available": int(riders[5] or 0),
            "suspended": int(riders[3] or 0),
            "delivered_in_window": int(active_riders or 0),
            "avg_acceptance_rate": str(Decimal(riders[4] or 0).quantize(Decimal("0.01"))),
            "orders_per_active_rider": str(
                (Decimal(orders or 0) / Decimal(active_riders)).quantize(Decimal("0.01"))
            )
            if active_riders
            else "0.00",
        },
        "vendors": {
            "total": int(vendors[0] or 0),
            "online_now": int(vendors[1] or 0),
            "suspended": int(vendors[2] or 0),
            "verified": int(vendors[3] or 0),
            "sold_in_window": int(active_vendors or 0),
        },
    }


async def quality(session: AsyncSession, *, days: int = 90) -> dict:
    """Ratings and disputes — the things that predict churn before revenue does."""
    from models.bottle_rejection_model import BottleRejectionTicket
    from models.review_model import Review

    start, end = _window(days)

    ratings = (
        await session.execute(
            select(Review.target_type, Review.rating, func.count(Review.id))
            .where(Review.created_at >= start, Review.hidden_at.is_(None))
            .group_by(Review.target_type, Review.rating)
        )
    ).all()

    distribution: dict[str, dict[int, int]] = {}
    for target, rating, count in ratings:
        distribution.setdefault(target or "unknown", {})[int(rating or 0)] = int(count or 0)

    disputes = (
        await session.execute(
            select(BottleRejectionTicket.status, func.count(BottleRejectionTicket.id))
            .where(BottleRejectionTicket.created_at >= start)
            .group_by(BottleRejectionTicket.status)
        )
    ).all()

    return {
        "window_days": days,
        "ratings": [
            {
                "target": target,
                "counts": counts,
                "average": str(
                    (
                        Decimal(sum(r * c for r, c in counts.items()))
                        / Decimal(sum(counts.values()))
                    ).quantize(Decimal("0.01"))
                )
                if sum(counts.values())
                else "0.00",
            }
            for target, counts in distribution.items()
        ],
        "disputes": [
            {"status": getattr(r[0], "value", r[0]) or "unknown", "count": int(r[1] or 0)}
            for r in disputes
        ],
    }


async def bottle_flow(session: AsyncSession, *, days: int = 90) -> dict:
    """The empties ledger: what went out, what came back, what is outstanding.

    Bottles are the platform's physical working capital. Every entry type is
    reported rather than a net figure, because "500 out, 480 back" and "20
    outstanding" are answers to different questions.
    """
    from models.bottle_ledger_model import BottleLedgerEntry

    start, end = _window(days)

    rows = (
        await session.execute(
            select(
                BottleLedgerEntry.entry_type,
                func.coalesce(func.sum(BottleLedgerEntry.quantity), 0),
                func.count(BottleLedgerEntry.id),
            )
            .where(BottleLedgerEntry.created_at >= start)
            .group_by(BottleLedgerEntry.entry_type)
        )
    ).all()

    inventory = (
        await session.execute(
            select(
                func.coalesce(func.sum(Vendor.empty_bottle_inventory), 0),
                func.coalesce(func.sum(Vendor.full_bottle_inventory), 0),
            )
        )
    ).one()

    customer_debt = (
        await session.execute(
            select(func.coalesce(func.sum(User.debt_balance), 0)).where(User.debt_balance > 0)
        )
    ).scalar()

    return {
        "window_days": days,
        "entries": [
            {
                "type": getattr(r[0], "value", r[0]) or "unknown",
                "quantity": int(r[1] or 0),
                "movements": int(r[2] or 0),
            }
            for r in rows
        ],
        "vendor_inventory": {
            "empty": int(inventory[0] or 0),
            "full": int(inventory[1] or 0),
        },
        "customer_bottle_debt": money(customer_debt),
    }


async def float_exposure(session: AsyncSession) -> dict:
    """How much money the platform is currently holding or owed. Point in time.

    Gated on `finance.read`, not `analytics.read`: this is the balance sheet,
    and an analyst answering demand questions has no need for it.

    A negative wallet balance means the account owes the platform — that is the
    arrears figure `settlement_service` blocks withdrawals against, and it is
    the one number here that is a live risk rather than a statistic.
    """
    async def totals(model):
        row = (
            await session.execute(
                select(
                    func.coalesce(func.sum(case((model.wallet_balance > 0, model.wallet_balance))), 0),
                    func.coalesce(func.sum(case((model.wallet_balance < 0, model.wallet_balance))), 0),
                    func.count(case((model.wallet_balance < 0, 1))),
                )
            )
        ).one()
        return {
            "held": money(row[0]),
            "arrears": money(abs(Decimal(row[1] or 0))),
            "accounts_in_arrears": int(row[2] or 0),
        }

    from models.payout_model import Payout

    pending = (
        await session.execute(
            select(
                func.coalesce(func.sum(Payout.amount), 0),
                func.count(Payout.id),
            ).where(Payout.status.in_(("pending", "processing", "approved")))
        )
    ).one()

    return {
        "vendors": await totals(Vendor),
        "riders": await totals(Deliverer),
        "customers": await totals(User),
        "payouts_in_flight": {
            "amount": money(pending[0]),
            "count": int(pending[1] or 0),
        },
    }
