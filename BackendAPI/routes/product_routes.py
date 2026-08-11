from fastapi import APIRouter, Depends, Query
from schemas.product_schemas import ProductFull, RequestBodyProductId
from schemas.common_schemas import RequestBodyPage
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from services.product_service import get_product_details, fetch_products_with_offer, fetch_paginated_products, fetch_products_by_category


router = APIRouter()


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
    db: AsyncSession = Depends(get_db)
):
    """Filter products by Kenya market category with pagination."""
    from core.redis_client import cache_get, cache_set
    cache_key = f"products_by_cat:{category}:{limit}:{offset}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    products = await fetch_products_by_category(session=db, category=category, limit=limit, offset=offset)
    
    await cache_set(cache_key, products, ttl_seconds=300) # 5 mins
    return products


@router.post("/get_product", response_model=ProductFull)
async def get_product(request_body: RequestBodyProductId, db : AsyncSession =  Depends(get_db)):
  product = await get_product_details(session=db, id=request_body.id)
  return product

@router.get("/products_with_discount")
async def get_products_with_offer(db: AsyncSession = Depends(get_db), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
  from core.redis_client import cache_get, cache_set
  cache_key = f"products_with_discount:{limit}:{offset}"
  cached = await cache_get(cache_key)
  if cached:
      return cached

  products = await fetch_products_with_offer(session=db, limit=limit, offset=offset)
  result = {"data": products, "limit": limit, "offset": offset}
  
  await cache_set(cache_key, result, ttl_seconds=300) # 5 mins
  return result


@router.post("/random_paginated_products")
async def get_paginated_products(request: RequestBodyPage, db: AsyncSession = Depends(get_db)):
  page_number = request.page
  products = await fetch_paginated_products(session=db, page=page_number)
  return products