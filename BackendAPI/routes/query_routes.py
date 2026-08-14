"""Product and vendor search.

Search is discovery, and on this platform discovery is bounded by what can
actually be delivered — `retail_max_distance_km` for a refill shop,
`wholesale_max_distance_km` for a depot. Every other discovery endpoint has
always worked that way; these two sorted by distance and never cut, so the top
hit for "20L" could be a store in another town: findable, tappable, and refused
at checkout by the one radius that *is* enforced.

Bounding it needs a location, and where that location comes from is the second
half of the same defect. The rest of `vendor_routes` resolves it server-side
from the customer's saved delivery address and answers `[]` without one. These
two took it from the client, and the client only sends it when it holds a live
GPS fix — so a customer who has denied location permission, or who opened the
app indoors before the first fix landed, searched the whole country.

`_coordinates` therefore prefers the live fix (more accurate for somebody out on
the street than their saved address) and falls back to the saved address. A
caller with neither has no delivery address, so nothing found here could have
been ordered anyway.
"""

from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from services.query_service import search_service, search_vendors_service
from services.user_service import get_user_coordinates
from schemas.product_schemas import ProductFull
from schemas.vendor_schemas import VendorOut

router = APIRouter()


async def _coordinates(
    db: AsyncSession,
    clerk_id: str,
    user_lat: float | None,
    user_lng: float | None,
) -> tuple[float | None, float | None]:
    """Where to measure the service radius from.

    Both halves must be present to be usable: a latitude with no longitude is
    not half a location, and passing one through would leave the radius
    unapplied exactly as before.
    """
    if user_lat is not None and user_lng is not None:
        return user_lat, user_lng

    coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
    if coords and coords.lat is not None and coords.lng is not None:
        return coords.lat, coords.lng

    return None, None


@router.get("/search", response_model=list[ProductFull])
async def search(
  query: str | None = Query(None, min_length=2, max_length=100),
  category: str | None = Query(None),
  mode: str | None = Query(None),
  limit: int = Query(20, ge=1, le=100),
  offset: int = Query(0, ge=0),
  user_lat: float | None = Query(None),
  user_lng: float | None = Query(None),
  db: AsyncSession = Depends(get_db),
  user=Depends(get_current_user)
):
  lat, lng = await _coordinates(db, user["sub"], user_lat, user_lng)
  products = await search_service(session=db, query=query, category=category, mode=mode, limit=limit, offset=offset, user_lat=lat, user_lng=lng)
  return products

@router.get("/search/vendors", response_model=list[VendorOut])
async def search_vendors(
  query: str | None = Query(None, min_length=2, max_length=100),
  limit: int = Query(20, ge=1, le=100),
  offset: int = Query(0, ge=0),
  user_lat: float | None = Query(None),
  user_lng: float | None = Query(None),
  db: AsyncSession = Depends(get_db),
  user=Depends(get_current_user)
):
  lat, lng = await _coordinates(db, user["sub"], user_lat, user_lng)
  vendors = await search_vendors_service(session=db, query=query, limit=limit, offset=offset, user_lat=lat, user_lng=lng)
  return vendors
