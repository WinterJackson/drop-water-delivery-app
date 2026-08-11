"""Business analytics, and CSV export.

Everything here is gated on `analytics.read`, except export which additionally
requires `data.export` — a report read on screen and a file that leaves the
building are different decisions, and the audit row for the second records how
many rows went with it.
"""
import csv
import io
import logging
from datetime import date as DateType
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.admin_dependencies import AdminAccess, require_admin
from core.redis_client import redis_limiter as limiter
from dependencies.dependencies import get_db
from models.admin_model import (
    PERM_ANALYTICS_READ,
    PERM_DATA_EXPORT,
    PERM_FINANCE_READ,
    PERM_SETTINGS_MANAGE,
)
from services import admin_analytics_service as analytics
from services import admin_growth_service as growth
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


# ── Acquisition cost and cohort economics ────────────────────────────────
#
# `/analytics/cohorts` above answers *do customers come back*. These answer the
# question a business acts on — **whether the ones who came back paid back what
# it cost to get them** — and the platform has had every input on every order
# since the first one.
#
# The spend endpoints are `settings.manage` rather than `analytics.read`:
# entering a figure that moves every CAC on the console is a decision about the
# business, not a report. Reading them needs only `analytics.read`, because a
# CAC with the spend hidden is not a CAC.


class AcquisitionSpendRequest(BaseModel):
    """One month's spend on one channel."""

    #: Any day inside the month; normalised to the first on write.
    period_month: DateType
    channel: str = Field(min_length=1, max_length=60)
    amount: Decimal = Field(ge=0, le=Decimal("100000000"))
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/growth/cohorts", summary="What each cohort cost, and what it returned")
@limiter.limit("60/minute")
async def growth_cohorts(
    request: Request,
    months: int = Query(12, ge=2, le=36),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """Cohort economics: CAC, cumulative contribution, payback month.

    `measured` and `entered` acquisition cost are returned separately and are
    never silently blended — the platform can prove the first from its own rows
    and cannot see the second at all, and a screen that adds them without
    saying so reports that acquisition is cheap on a month nobody filled in.
    """
    return {
        "summary": await growth.acquisition_summary(db, months=months),
        **await growth.cohort_economics(db, months=months),
    }


@router.get("/growth/spend", summary="Off-platform acquisition spend, as entered")
@limiter.limit("60/minute")
async def growth_list_spend(
    request: Request,
    months: int = Query(12, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    return await growth.list_spend(db, months=months)


@router.put("/growth/spend", summary="Record or correct one month's spend")
@limiter.limit("30/minute")
async def growth_record_spend(
    request: Request,
    body: AcquisitionSpendRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    """An upsert, keyed on (month, channel).

    Audited: this figure moves every CAC on the console, and a number that
    changed with no record of who changed it is a number nobody will trust
    enough to act on.
    """
    result = await growth.record_spend(
        db,
        period_month=body.period_month,
        channel=body.channel,
        amount=body.amount,
        note=body.note,
        recorded_by=getattr(access, "id", None),
    )
    admin_service.record_audit(
        db,
        access=access,
        action="growth.spend_recorded",
        target_type="acquisition_spend",
        target_id=result["id"],
        after=result,
    )
    # One commit, so the change and the record of who made it land together.
    await db.commit()
    return result


@router.delete("/growth/spend/{spend_id}", summary="Remove a spend entry")
@limiter.limit("30/minute")
async def growth_delete_spend(
    request: Request,
    spend_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    result = await growth.delete_spend(db, spend_id=spend_id)
    admin_service.record_audit(
        db,
        access=access,
        action="growth.spend_deleted",
        target_type="acquisition_spend",
        target_id=spend_id,
        # What it was, not merely that it went. A hole in the CAC series with no
        # record of what filled it is one nobody can later explain.
        before=result["was"],
    )
    await db.commit()
    return {"deleted": result["deleted"]}
