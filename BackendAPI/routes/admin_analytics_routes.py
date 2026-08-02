"""Business analytics, and CSV export.

Everything here is gated on `analytics.read`, except export which additionally
requires `data.export` — a report read on screen and a file that leaves the
building are different decisions, and the audit row for the second records how
many rows went with it.
"""
import csv
import io
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.admin_dependencies import AdminAccess, require_admin
from core.redis_client import redis_limiter as limiter
from dependencies.dependencies import get_db
from models.admin_model import PERM_ANALYTICS_READ, PERM_DATA_EXPORT, PERM_FINANCE_READ
from services import admin_analytics_service as analytics
from services import admin_service

logger = logging.getLogger(__name__)

router = APIRouter()

#: Bounded because every one of these scans the orders table. A caller asking
#: for five years of daily buckets is asking for a table scan and a chart with
#: 1,800 unreadable points.
MAX_DAYS = 365


@router.get("/analytics/summary", summary="Everything the analytics screen needs")
# Six aggregations over the orders table per call.
@limiter.limit("60/minute")
async def analytics_summary(
    request: Request,
    days: int = Query(30, ge=1, le=MAX_DAYS),
    grain: Literal["day", "week", "month"] = "day",
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """Assembled server-side into one response.

    Six widgets meant six requests, six spinners, and six chances for the
    numbers to disagree with each other by however long the slowest one took.
    """
    payload = {
        "timeseries": await analytics.timeseries(db, days=days, grain=grain),
        "unit_economics": await analytics.unit_economics(db, days=days),
        "operations": await analytics.operations_health(db, days=days),
        "growth": await analytics.growth(db, days=days),
        "top_vendors": await analytics.leaderboard(db, kind="vendor", days=days),
        "top_riders": await analytics.leaderboard(db, kind="rider", days=days),
        "status_funnel": await analytics.status_funnel(db, days=days),
        "fulfilment": await analytics.fulfilment(db, days=days),
        "supply": await analytics.supply_health(db, days=days),
        "products": await analytics.product_performance(db, days=days),
        "customers": await analytics.customer_behaviour(db, days=max(days, 90)),
        "quality": await analytics.quality(db, days=max(days, 90)),
        "bottles": await analytics.bottle_flow(db, days=max(days, 90)),
    }

    # Financial detail is a *separate* grant. An analyst answering demand
    # questions gets everything above and none of this — and gets a working
    # page rather than a 403, because refusing the whole screen for one section
    # is how people end up being handed `finance.read` "just to see the charts".
    #
    # The flag is what the console renders against: omitting the key silently
    # would look identical to a period with no money in it.
    payload["finance_visible"] = access.may(PERM_FINANCE_READ)
    if payload["finance_visible"]:
        payload["payment_mix"] = await analytics.payment_mix(db, days=days)
        payload["float_exposure"] = await analytics.float_exposure(db)

    return payload


@router.get("/analytics/cohorts", summary="Customer repeat-purchase cohorts")
@limiter.limit("60/minute")
async def analytics_cohorts(
    request: Request,
    months: int = Query(6, ge=2, le=24),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """Bottled water is a repeat purchase or it is nothing, so this is the
    single most important chart on the platform."""
    return await analytics.retention_cohorts(db, months=months)


@router.get("/analytics/export", summary="Download a report as CSV")
# Data leaving the building. A human downloads a report a few times a day.
@limiter.limit("10/minute")
async def analytics_export(
    request: Request,
    report: Literal["revenue", "vendors", "riders"] = "revenue",
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_DATA_EXPORT)),
):
    """A file that leaves the building, so it is its own permission and audited.

    Deliberately aggregate-only. There is no export of the customer table here:
    the fastest way to turn a permissions system into a data breach is a button
    that writes every personal record to a spreadsheet.
    """
    access.require(PERM_ANALYTICS_READ)

    if report == "revenue":
        data = await analytics.timeseries(db, days=days, grain="day")
        header = ["date", "revenue", "gmv", "orders"]
        rows = [[p["date"], p["revenue"], p["gmv"], p["orders"]] for p in data["points"]]
    else:
        kind = "vendor" if report == "vendors" else "rider"
        data = await analytics.leaderboard(db, kind=kind, days=days, limit=200)
        header = ["id", "name", "orders", "gmv", "revenue", "rating"]
        rows = [
            [i["id"], i["name"], i["orders"], i["gmv"], i["revenue"], i["rating"]]
            for i in data["items"]
        ]

    admin_service.record_audit(
        db,
        access=access,
        action="data.export",
        target_type="report",
        target_id=report,
        after={"rows": len(rows), "window_days": days},
        reason=f"Exported the {report} report",
    )
    await db.commit()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="drop-{report}-{days}d.csv"',
            # The file holds business figures; no intermediary should keep a copy.
            "Cache-Control": "no-store",
        },
    )


@router.get("/analytics/demand", summary="When and where orders arrive")
@limiter.limit("60/minute")
async def analytics_demand(
    request: Request,
    days: int = Query(90, ge=7, le=MAX_DAYS),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """Rider shift planning is built from these two.

    Kept out of `/summary` because they want a longer window than the revenue
    charts — an hour-of-week grid over seven days is mostly noise.
    """
    return {
        "pattern": await analytics.demand_pattern(db, days=days),
        "geography": await analytics.geographic_demand(db, days=days),
    }
