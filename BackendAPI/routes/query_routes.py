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

`services/delivery_point.resolve` is the origin, for these two exactly as for
every other discovery read: the saved delivery address, resolved server-side,
answering `None` when there is none — at which point these endpoints serve
nothing, because nothing they could find would have been orderable.

These two used to take `user_lat`/`user_lng` from the client and prefer them.
That made search the only surface on the platform measured from the handset
rather than from the address the order is delivered to, so it listed shops that
could reach the phone and checkout refused the ones that could not reach the
house.
"""

from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from services.query_service import search_service, search_vendors_service
from services import delivery_point
from schemas.product_schemas import ProductFull
from schemas.vendor_schemas import VendorStorefront

router = APIRouter()




@router.get("/search", response_model=list[ProductFull])
async def search(
  query: str | None = Query(None, min_length=2, max_length=100),
  category: str | None = Query(None),
  mode: str | None = Query(None),
  limit: int = Query(20, ge=1, le=100),
  offset: int = Query(0, ge=0),
  db: AsyncSession = Depends(get_db),
  user=Depends(get_current_user)
):
  point = await delivery_point.resolve(db, user["sub"])
  if point is None:
      # No delivery address and no live fix. Nothing found here could be
      # ordered, and an unbounded search is how the top hit for "20L" came to be
      # a shop in another town.
      return []
  products = await search_service(session=db, query=query, category=category, mode=mode, limit=limit, offset=offset, user_lat=point.lat, user_lng=point.lng)
  return products

@router.get("/search/vendors", response_model=list[VendorStorefront])
async def search_vendors(
  query: str | None = Query(None, min_length=2, max_length=100),
  limit: int = Query(20, ge=1, le=100),
  offset: int = Query(0, ge=0),
  db: AsyncSession = Depends(get_db),
  user=Depends(get_current_user)
):
  point = await delivery_point.resolve(db, user["sub"])
  if point is None:
      return []
  vendors = await search_vendors_service(session=db, query=query, limit=limit, offset=offset, user_lat=point.lat, user_lng=point.lng)
  return vendors
