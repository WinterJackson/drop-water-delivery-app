from fastapi import APIRouter, Depends, Query
from schemas.product_schemas import (
    CategoryProductsPage,
    ProductFull,
    ProductsPage,
    RequestBodyProductId,
)
from schemas.common_schemas import RequestBodyPage
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from services.product_service import get_product_details, fetch_products_with_offer, fetch_paginated_products, fetch_products_by_category
from services import delivery_point
from services.delivery_point import DeliveryPoint
from utils.verify_user_token import get_current_user


router = APIRouter()


async def _delivery_point(db: AsyncSession, clerk_id: str) -> DeliveryPoint | None:
    """Where to measure the service radius from, for this caller.

    Server-side from the customer's saved delivery address, never from a query
    parameter: the bound is what decides whether a store may be ordered from at
    all, and a client-supplied origin is a client-supplied answer.

    `None` means no delivery address, and these three listings then serve
    **nothing** rather than the national catalogue. They used to serve it
    unbounded, on the reasoning that an empty home screen is worse than a wide
    one — which was true, and was the wrong trade to make, because the four
    vendor endpoints on the same screen answered `[]` in that state. The home
    screen said "No vendors currently deliver to your location" above a grid of
    products from Ngong. See `services/delivery_point`.
    """
    return await delivery_point.resolve(session=db, clerk_id=clerk_id)


def _location_key(point: DeliveryPoint | None) -> str:
    """Cache key fragment for a delivery point.

    These listings are cached in Redis and were keyed on pagination alone. Now
    that the rows depend on where the customer is, a location-independent key
    would serve one customer's in-range catalogue to another 20 km away — the
    defect this change exists to remove, reintroduced by the cache.

    Rounded to ~1 km (2 decimal places), which is well inside the 2.5 km radius
    and keeps the hit rate usable for a neighbourhood rather than per-household.
    """
    if point is None:
        return "nowhere"
    return f"{point.lat:.2f},{point.lng:.2f}"



# ─── Kenya Market Product Categories ─────────────────────────────────────────
CATEGORY_METADATA = [
    {"key": "dispenser_refill", "label": "Dispenser Refills", "icon": "🚰", "description": "18.9L & 20L refill bottles"},
    {"key": "bottled_water", "label": "Bottled Water", "icon": "🍶", "description": "500ml to 2L bottles"},
    {"key": "mineral_spring", "label": "Mineral & Spring", "icon": "⛰️", "description": "Natural mineral & spring water"},
    {"key": "purified_water", "label": "Purified Water", "icon": "💧", "description": "Filtered & treated water"},
    {"key": "alkaline_specialty", "label": "Alkaline & Specialty", "icon": "✨", "description": "Alkaline, infused & premium water"},
    {"key": "jerrycan", "label": "Jerrycans", "icon": "🪣", "description": "5L & 10L jerrycans"},
    {"key": "bulk_wholesale", "label": "Bulk & Wholesale", "icon": "📦", "description": "Large volume B2B orders"},
    {"key": "dispensers_coolers", "label": "Dispensers & Coolers", "icon": "🧊", "description": "Water dispenser hardware"},
    {"key": "accessories", "label": "Accessories", "icon": "🔧", "description": "Pumps, caps, stands & more"},
    {"key": "ice_cold", "label": "Ice & Cold Water", "icon": "❄️", "description": "Chilled & frozen water products"},
]


@router.get("/categories")
async def get_categories():
    """Returns all available product categories with metadata for the UI."""
    from core.redis_client import cache_get, cache_set
    cache_key = "product_categories_metadata"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    result = {"categories": CATEGORY_METADATA}
    await cache_set(cache_key, result, ttl_seconds=86400) # Cache for 24 hours
    return result


@router.get("/products-by-category", response_model=CategoryProductsPage)
async def get_products_by_category(
    category: str = Query(..., description="Category key from /categories endpoint"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Filter products by Kenya market category with pagination."""
    from core.redis_client import cache_get, cache_set

    point = await _delivery_point(db, user["sub"])
    if point is None:
        # No delivery address: nothing here can be ordered, so nothing is
        # listed. The app asks for the address instead of rendering a shelf.
        # The *envelope*, not a bare list — this branch used to return `[]`
        # while the success path returned `{"data": ...}`, so one endpoint had
        # two wire shapes and the client carried an `Array.isArray(json)` test
        # to tell them apart. A response_model makes that impossible.
        return {"data": [], "total_count": 0, "limit": limit, "offset": offset}

    cache_key = f"products_by_cat:v2:{category}:{limit}:{offset}:{_location_key(point)}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    products = await fetch_products_by_category(session=db, category=category, limit=limit, offset=offset, user_lat=point.lat, user_lng=point.lng)
    
    await cache_set(cache_key, products, ttl_seconds=300) # 5 mins
    return products


@router.post("/get_product", response_model=ProductFull)
async def get_product(request_body: RequestBodyProductId, db : AsyncSession =  Depends(get_db)):
  product = await get_product_details(session=db, id=request_body.id)
  return product

@router.get("/products_with_discount", response_model=ProductsPage)
async def get_products_with_offer(db: AsyncSession = Depends(get_db), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(get_current_user)):
  from core.redis_client import cache_get, cache_set

  point = await _delivery_point(db, user["sub"])
  if point is None:
      return {"data": [], "limit": limit, "offset": offset}

  cache_key = f"products_with_discount:v2:{limit}:{offset}:{_location_key(point)}"
  cached = await cache_get(cache_key)
  if cached:
      return cached

  products = await fetch_products_with_offer(session=db, limit=limit, offset=offset, user_lat=point.lat, user_lng=point.lng)
  result = {"data": products, "limit": limit, "offset": offset}
  
  await cache_set(cache_key, result, ttl_seconds=300) # 5 mins
  return result


@router.post("/random_paginated_products", response_model=list[ProductFull])
async def get_paginated_products(request: RequestBodyPage, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
  page_number = request.page
  point = await _delivery_point(db, user["sub"])
  if point is None:
      return []
  products = await fetch_paginated_products(session=db, page=page_number, user_lat=point.lat, user_lng=point.lng)
  return products