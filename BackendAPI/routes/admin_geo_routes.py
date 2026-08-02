"""The map.

Layers are separately permissioned, and the customer layer is the reason why.
Rider and vendor positions are operational — where a fleet is and where the
stores are. Customer positions are people's homes, so that layer is never points
and only ever H3 cells with at least two orders in them.

`geo.view` gates the whole surface. It is deliberately not implied by
`riders.read`: knowing a rider exists and being able to watch where they are all
day are different grants, and the second is not needed to approve a document.
"""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, current_admin, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_GEO_VIEW, PERM_ORDERS_READ
from services import admin_geo_service as geo

logger = logging.getLogger(__name__)

router = APIRouter()


def _viewport(
    min_lat: Optional[float],
    min_lng: Optional[float],
    max_lat: Optional[float],
    max_lng: Optional[float],
) -> geo.Viewport:
    return geo.Viewport(min_lat=min_lat, min_lng=min_lng, max_lat=max_lat, max_lng=max_lng)


@router.get("/map/bootstrap", summary="Where to open the map, and what is worth showing")
async def map_bootstrap(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_GEO_VIEW)),
):
    """One call before the map renders.

    Returns the centre and the coverage summary together so the map can open at
    the right place *and* say something useful in the same paint — a map that
    opens centred on the Atlantic while it waits for a second request looks
    broken, and this platform genuinely has rows with no position yet.
    """
    return {
        "centre": await geo.map_centre(db),
        "coverage": await geo.coverage_report(db),
    }


@router.get("/map/riders", summary="Rider positions")
# Polled while the map is open, so the ceiling is generous but real.
@limiter.limit("120/minute")
async def map_riders(
    request: Request,
    min_lat: Optional[float] = None,
    min_lng: Optional[float] = None,
    max_lat: Optional[float] = None,
    max_lng: Optional[float] = None,
    only_deployable: bool = False,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_GEO_VIEW)),
):
    return await geo.rider_positions(
        db,
        viewport=_viewport(min_lat, min_lng, max_lat, max_lng),
        only_deployable=only_deployable,
    )


@router.get("/map/vendors", summary="Store positions")
@limiter.limit("120/minute")
async def map_vendors(
    request: Request,
    min_lat: Optional[float] = None,
    min_lng: Optional[float] = None,
    max_lat: Optional[float] = None,
    max_lng: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_GEO_VIEW)),
):
    return await geo.vendor_positions(
        db, viewport=_viewport(min_lat, min_lng, max_lat, max_lng)
    )


@router.get("/map/demand", summary="Where orders come from, aggregated")
@limiter.limit("60/minute")
async def map_demand(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_GEO_VIEW)),
):
    """The customer layer, and the only form it is ever served in.

    H3 cells, and only those with more than one order. A single delivery inside
    a 460-metre cell is a household, and an operational need to see where demand
    is does not extend to reading addresses off a map.
    """
    return await geo.demand_cells(db, days=days)


@router.get("/map/orders", summary="Orders in flight, positioned at their vendor")
@limiter.limit("120/minute")
async def map_orders(
    request: Request,
    min_lat: Optional[float] = None,
    min_lng: Optional[float] = None,
    max_lat: Optional[float] = None,
    max_lng: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(current_admin),
):
    """Needs both `geo.view` and `orders.read`.

    The layer is a join of the two: it is order data placed on a map, and
    holding one half should not grant the other.
    """
    access.require(PERM_GEO_VIEW)
    access.require(PERM_ORDERS_READ)
    return await geo.live_orders(
        db, viewport=_viewport(min_lat, min_lng, max_lat, max_lng)
    )


@router.get("/map/coverage", summary="Stores with no rider who could serve them")
async def map_coverage(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_GEO_VIEW)),
):
    """The actionable number on this screen.

    Not "how many riders" — a fleet of forty all parked in one suburb is a
    coverage failure every headline count hides. Each uncovered store is one
    taking orders that nobody within the delivery radius can pick up.
    """
    return await geo.coverage_report(db)
