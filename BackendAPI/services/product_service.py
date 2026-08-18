from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from uuid import UUID
from sqlalchemy.future import select
from models.product_model import Product
from schemas.product_schemas import ProductFull,BaseProduct
from utils.paging import stable


def live_product():
  """The predicate every read of `Products` must carry.

  A product is withdrawn by setting `deleted_at`, not by deleting the row —
  `Order_Items` references it and the bottle ledger reads its capacity to work
  out what a rider owes. Withdrawn rows must therefore stay queryable while
  being invisible everywhere a customer or a vendor is choosing what to sell.

  Written once and imported, rather than repeated per query: seven reads is
  seven chances to write a subtly different one, and the one that gets missed is
  invisible until a customer orders a product the vendor has taken down.
  `tests/test_product_withdrawal.py` walks these modules with `ast` and fails the
  build on a `select(Product)` that does not mention `deleted_at`.
  """
  return Product.deleted_at.is_(None)


async def get_product_details(session : AsyncSession, id : UUID) -> ProductFull:
  query = select(Product).options(selectinload(Product.vendor)).where(Product.id == id, live_product())
  result = await session.execute(query)
  product = result.unique().scalar_one_or_none()
  if not product:
    raise HTTPException(status_code=404, detail="Product by this id does not exist")
  return product


async def get_product_for_cart(session : AsyncSession, id : UUID) -> BaseProduct:
  query = select(Product).where(Product.id == id, live_product())
  result = await session.execute(query)
  product = result.unique().scalar_one_or_none()
  if not product:
    raise HTTPException(status_code=404, detail="Product by this id does not exist")
  return product

def _orderable_products(user_lat: float | None, user_lng: float | None):
    """The base catalogue query: live products, from stores a customer may
    actually order from.

    Every product listing goes through this, for the reason `search_service`
    already had it and these three did not: they selected straight off
    `Products` with **no join to `Vendors` at all**. So the home grid, Deals &
    Offers and every category listing showed products belonging to suspended,
    unverified and deleted stores, and — once coordinates were known —
    products from stores the very same screen had just reported as out of
    range. The home screen rendered "No vendors currently deliver to your
    location" directly above a grid of things from Ngong.

    A customer sees what they can buy. An out-of-range store is not a
    temporarily shut one: the pause banner exists because a closed shop must be
    *marked, never hidden*, but a shop 20 km away is not shut — it is not
    reachable from this address at all, and listing it only produces a refusal
    at checkout after the basket is full.

    Coordinates are optional and the bound is applied only when they are known,
    exactly as in search: a caller with no delivery address has nothing to
    measure against, and an unbounded list is better than an empty one.
    """
    from sqlalchemy import func as _func
    from geoalchemy2 import Geography

    from models.vendor_model import Vendor
    from services.dispatch_policy import within_service_radius
    from services.vendor_service import discoverable_vendor

    query = (
        select(Product)
        .join(Vendor, Product.vendor_id == Vendor.id)
        .where(Product.is_available == True, live_product(), discoverable_vendor())
    )

    if user_lat is not None and user_lng is not None:
        user_location = _func.ST_SetSRID(
            _func.ST_MakePoint(user_lng, user_lat), 4326
        ).cast(Geography)
        query = query.where(within_service_radius(user_location))

    return query


async def fetch_products_with_offer(session: AsyncSession, limit: int = 20, offset: int = 0, user_lat: float | None = None, user_lng: float | None = None) -> list[BaseProduct]:
  # `discount` is a percentage: on any real catalogue dozens of products share
  # each value, so this ordering ties almost everywhere and the offset window
  # would land differently on every execution — see `utils/paging`.
  query = _orderable_products(user_lat, user_lng).where(Product.discount > 0).order_by(*stable(Product.discount.desc(), key=Product.id)).offset(offset).limit(limit)
  result = await session.execute(query)
  products = result.unique().scalars().all()
  if not products :
    return []
  return products

async def fetch_paginated_products(session: AsyncSession, page: int, user_lat: float | None = None, user_lng: float | None = None) ->  list[BaseProduct]:
  offset = (page - 1 ) * 16
  query = _orderable_products(user_lat, user_lng).order_by(*stable(Product.created_at.desc(), key=Product.id)).offset(offset).limit(16)
  result = await session.execute(query)
  products = result.unique().scalars().all()
  return products


async def fetch_products_by_category(session: AsyncSession, category: str, limit: int = 20, offset: int = 0, user_lat: float | None = None, user_lng: float | None = None) -> dict:
  """Fetch products filtered by Kenya market category with pagination."""
  base_query = _orderable_products(user_lat, user_lng).where(Product.category == category)
  
  # Get total count
  count_query = select(func.count()).select_from(base_query.subquery())
  count_result = await session.execute(count_query)
  total = count_result.scalar() or 0
  
  # Get paginated results
  query = base_query.order_by(*stable(Product.created_at.desc(), key=Product.id)).offset(offset).limit(limit)
  result = await session.execute(query)
  products = result.unique().scalars().all()
  
  return {"data": products, "total": total, "limit": limit, "offset": offset}