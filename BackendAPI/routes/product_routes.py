from fastapi import APIRouter, Depends, Query
from schemas.product_schemas import ProductFull, RequestBodyProductId
from schemas.common_schemas import RequestBodyPage
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from services.product_service import get_product_details, fetch_products_with_offer, fetch_paginated_products, fetch_products_by_category
from services.user_service import get_user_coordinates
from utils.verify_user_token import get_current_user


router = APIRouter()


async def _delivery_point(db: AsyncSession, clerk_id: str) -> tuple[float | None, float | None]:
    """Where to measure the service radius from, for this caller.

    Server-side from the customer's saved delivery address, never from a query
    parameter: the bound is what decides whether a store may be ordered from at
    all, and a client-supplied origin is a client-supplied answer.

    `(None, None)` means the customer has no delivery address yet, and the
    listing is served unbounded — there is nothing to measure, and an empty home
    screen on first launch is worse than a wide one.
    """
    coords = await get_user_coordinates(session=db, clerk_id=clerk_id)
    if coords and coords.lat is not None and coords.lng is not None:
        return coords.lat, coords.lng
    return None, None


def _location_key(lat: float | None, lng: float | None) -> str:
    """Cache key fragment for a delivery point.

    These listings are cached in Redis and were keyed on pagination alone. Now
    that the rows depend on where the customer is, a location-independent key
    would serve one customer's in-range catalogue to another 20 km away — the
    defect this change exists to remove, reintroduced by the cache.

    Rounded to ~1 km (2 decimal places), which is well inside the 2.5 km radius
    and keeps the hit rate usable for a neighbourhood rather than per-household.
    """
    if lat is None or lng is None:
        return "anywhere"
    return f"{lat:.2f},{lng:.2f}"



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


@router.get("/products-by-category")
async def get_products_by_category(
    category: str = Query(..., description="Category key from /categories endpoint"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Filter products by Kenya market category with pagination."""
    from core.redis_client import cache_get, cache_set

    lat, lng = await _delivery_point(db, user["sub"])
    cache_key = f"products_by_cat:{category}:{limit}:{offset}:{_location_key(lat, lng)}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    products = await fetch_products_by_category(session=db, category=category, limit=limit, offset=offset, user_lat=lat, user_lng=lng)
    
    await cache_set(cache_key, products, ttl_seconds=300) # 5 mins
    return products


@router.post("/get_product", response_model=ProductFull)
async def get_product(request_body: RequestBodyProductId, db : AsyncSession =  Depends(get_db)):
  product = await get_product_details(session=db, id=request_body.id)
  return product

@router.get("/products_with_discount")
async def get_products_with_offer(db: AsyncSession = Depends(get_db), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(get_current_user)):
  from core.redis_client import cache_get, cache_set

  lat, lng = await _delivery_point(db, user["sub"])
  cache_key = f"products_with_discount:{limit}:{offset}:{_location_key(lat, lng)}"
  cached = await cache_get(cache_key)
  if cached:
      return cached

  products = await fetch_products_with_offer(session=db, limit=limit, offset=offset, user_lat=lat, user_lng=lng)
  result = {"data": products, "limit": limit, "offset": offset}
  
  await cache_set(cache_key, result, ttl_seconds=300) # 5 mins
  return result


@router.post("/random_paginated_products")
async def get_paginated_products(request: RequestBodyPage, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
  page_number = request.page
  lat, lng = await _delivery_point(db, user["sub"])
  products = await fetch_paginated_products(session=db, page=page_number, user_lat=lat, user_lng=lng)
  return products