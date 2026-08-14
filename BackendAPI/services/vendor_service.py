
import h3
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.vendor_model import Vendor
from schemas.vendor_schemas import BaseVendor, VendorWithProductsThin, VendorWithProductsFull
from geoalchemy2.functions import ST_Distance, ST_DWithin
from sqlalchemy.orm import joinedload
from uuid import UUID
from services import platform_config_service
from services.dispatch_policy import DispatchPolicy
from services.product_service import live_product
from utils.paging import stable


#: Statuses that take a store out of the customer-facing app entirely.
#:
#: `deleted` is set by account deletion in `auth_routes`, which anonymises the
#: row but leaves it in place for the orders that reference it.
UNDISCOVERABLE_STATUSES = ("deleted",)


def discoverable_vendor():
  """The predicate every customer-facing vendor query must carry.

  Nine discovery queries existed and **none of them filtered on account state**,
  so a store whose owner had deleted their account — anonymised, status
  `deleted` — still appeared in search, in "near you", and in the directory. The
  same hole would have swallowed suspension the moment an administrator used it,
  which is why the suspend action and this predicate ship together.

  Written once and imported, rather than repeated per query: nine copies is nine
  chances to write a subtly different one, and the one that gets missed is
  invisible until a customer orders from a store that is not there.

  Deliberately **not** filtered on `verification_status == "verified"`. Every
  vendor on the platform is currently `pending`, so that predicate would empty
  the customer app. Whether unverified stores may trade is a business decision,
  not something to change silently inside a bug fix.
  """
  clauses = [
      Vendor.is_active.is_(True),
      Vendor.verification_status.notin_(UNDISCOVERABLE_STATUSES),
  ]

  # Off by default, and read per call rather than frozen at import so it can be
  # turned on without a redeploy — and turned off again just as fast if it
  # empties the app.
  #
  # This was an environment variable, which meant changing it needed a Render
  # edit and a restart. It is a `Platform_Settings` row now, so an owner can
  # switch it from the console and revert in seconds when they see the
  # consequences. Reads are synchronous against the cached snapshot; callers
  # that price or search have already refreshed it.
  if platform_config_service.get_bool("require_vendor_verification"):
      clauses.append(Vendor.verification_status == "verified")

  return and_(*clauses)


async def _annotated(session: AsyncSession, vendors):
  """Stamp each row with whether that store is taking orders, then hand it back.

  Every customer-facing read goes through this, for the same reason every one
  of them carries `discoverable_vendor()`: seven functions each remembering to
  do it is seven chances to forget, and the one that gets missed is invisible
  until a customer orders from a shop that is shut.

  It does not *filter*. A closed store must appear and be marked closed — the
  customer looking for the shop they always use should not conclude it has left
  the platform, and a store that paused for twenty minutes should lose those
  twenty minutes of orders, not its place in everybody's list.
  """
  from services import vendor_availability

  await vendor_availability.annotate(session, vendors)
  return vendors


async def get_all_vendors(session: AsyncSession, limit: int = 20, offset: int = 0):
  count_query = select(func.count()).select_from(Vendor).where(discoverable_vendor())
  count_result = await session.execute(count_query)
  total = count_result.scalar() or 0

  query = (
      select(Vendor)
      .where(discoverable_vendor())
      .order_by(*stable(Vendor.created_at.desc(), key=Vendor.id))
      .offset(offset)
      .limit(limit)
  )
  result = await session.execute(query)
  vendors = await _annotated(session, result.scalars().all())
  return vendors, total

# The H3 ring pre-filter is an index-friendly bounding box, not a radius. A
# res-8 disk always over-reaches the circle it approximates — `get_h3_k_ring`
# rounds *up* on purpose, because a ring too small silently hides stores that
# are genuinely in range. On its own it therefore returned retail vendors beyond
# the configured limit: the customer could browse them, fill a cart, and only
# discover the problem when checkout rejected the distance.
#
# So every discovery query pairs the pre-filter with an exact `ST_DWithin`, and
# both the ring and the distance come from the same configured radius — which is
# what stops the two from ever describing different areas.

def _search_bounds(lat: float, lng: float, vendor_type: str):
  """Returns (user_point, neighbour_h3_cells, max_distance_m) for a discovery query."""
  user_point = func.ST_GeogFromText(f"SRID=4326;POINT({lng} {lat})")
  center_h3 = h3.latlng_to_cell(lat, lng, 8)
  k_ring = DispatchPolicy.get_h3_k_ring(vendor_type)
  neighbour_cells = [str(cell) for cell in h3.grid_disk(center_h3, k_ring)]
  # Through the accessor, never the dataclass default. Discovery read the
  # shipped 2.0 while checkout read the configured row, so raising
  # `retail_max_distance_km` on the console widened what the platform would
  # deliver and not what a customer could find — the store that had just come
  # into range stayed invisible, which reads as the platform being broken.
  max_km = DispatchPolicy.max_distance_km(vendor_type)
  return user_point, neighbour_cells, max_km * 1000.0


async def get_nearby_vendors(session : AsyncSession, lat : float, lng : float ) -> list[VendorWithProductsThin]:
  user_point, neighbour_cells, max_distance_m = _search_bounds(lat, lng, "retail_refill")

  query = (
      select(Vendor)
      .where(
          and_(
              discoverable_vendor(),
              Vendor.vendor_type == "retail_refill",
              Vendor.h3_index_res8.in_(neighbour_cells),
              Vendor.location.isnot(None),
              ST_DWithin(Vendor.location, user_point, max_distance_m),
          )
      )
      .options(joinedload(Vendor.products.and_(live_product())))
      .order_by(ST_Distance(Vendor.location, user_point))
      .limit(3)
  )
  result = await session.execute(query)
  return await _annotated(session, result.unique().scalars().all())

async def get_top_rated_vendors(session: AsyncSession, lat : float, lng: float) -> list[BaseVendor]:
  user_point, neighbour_cells, max_distance_m = _search_bounds(lat, lng, "retail_refill")

  query = (
      select(Vendor)
      .where(
          and_(
              discoverable_vendor(),
              Vendor.vendor_type == "retail_refill",
              Vendor.rating >= 4,
              Vendor.h3_index_res8.in_(neighbour_cells),
              Vendor.location.isnot(None),
              ST_DWithin(Vendor.location, user_point, max_distance_m),
          )
      )
      .order_by(ST_Distance(Vendor.location, user_point))
      .limit(10)
  )
  result = await session.execute(query)
  return await _annotated(session, result.unique().scalars().all())

async def get_vendors_by_type_service(session : AsyncSession, type: str, lng: float, lat: float) -> list[BaseVendor]:
  """Vendors of one type within that type's serviceable radius.

  The non-retail branch used to return early with a nationwide, rating-sorted
  list — so the 15 km wholesale rule was never applied here, and the
  `k_rings = 32 if wholesale` line below it was unreachable.
  """
  if not type:
    raise HTTPException(status_code=400, detail="\'vendor_type\' parameter is required")

  if lat is None or lng is None:
    raise HTTPException(status_code=400, detail="Coordinates are required to find vendors near you.")

  user_point, neighbour_cells, max_distance_m = _search_bounds(lat, lng, type)

  query_with_location = (
      select(Vendor)
      .where(
          and_(
              discoverable_vendor(),
              Vendor.vendor_type == type,
              Vendor.h3_index_res8.in_(neighbour_cells),
              Vendor.location.isnot(None),
              ST_DWithin(Vendor.location, user_point, max_distance_m),
          )
      )
      .order_by(ST_Distance(Vendor.location, user_point))
      .limit(10)
  )
  result = await session.execute(query_with_location)
  return await _annotated(session, result.unique().scalars().all())

async def get_vendor_by_id_service(session: AsyncSession, id: UUID) -> VendorWithProductsFull:
  # A direct link (a bookmark, a shared product) must not bypass what the
  # listings enforce, or suspension only hides a store from people who were not
  # already looking for it.
  query = (
      select(Vendor)
      .where(Vendor.id == id, discoverable_vendor())
      .options(joinedload(Vendor.products.and_(live_product())))
  )
  result = await session.execute(query)
  vendor = result.unique().scalar_one_or_none()
  await _annotated(session, [vendor] if vendor else [])
  return vendor

async def get_top_brands_service(session : AsyncSession, lat : float, lng : float) -> list[BaseVendor]:
  """Highest-rated wholesale brands that can actually deliver to this customer.

  Two fixes here. The guard was `if not lat and not lng`, which only rejects the
  case where *both* are missing — a valid longitude with a zero latitude sailed
  through. And the query ignored the coordinates entirely, so a screen captioned
  "near you" listed brands from anywhere in the country that the customer could
  never order from.
  """
  if lat is None or lng is None:
    raise HTTPException(status_code=400 , detail="Coordinates are required for this service")

  user_point, neighbour_cells, max_distance_m = _search_bounds(lat, lng, "wholesale_b2b")

  query = (
      select(Vendor)
      .where(
          and_(
              discoverable_vendor(),
              Vendor.vendor_type == "wholesale_b2b",
              Vendor.rating >= 4,
              Vendor.h3_index_res8.in_(neighbour_cells),
              Vendor.location.isnot(None),
              ST_DWithin(Vendor.location, user_point, max_distance_m),
          )
      )
      .order_by(Vendor.rating.desc(), ST_Distance(Vendor.location, user_point))
      .limit(10)
  )
  result = await session.execute(query)
  return await _annotated(session, result.unique().scalars().all())

from typing import Optional
import os
from sqlalchemy import func , and_, or_

async def get_vendor_directory(
    session: AsyncSession, 
    lat: float, 
    lng: float, 
    limit: int = 50,
    offset: int = 0,
    search_query: Optional[str] = None,
    vendor_type: Optional[str] = "all"
) -> list[VendorWithProductsThin]:
    """One page of the stores a customer can order from, nearest first.

    Took a `limit` and no `offset`, so the directory was permanently the nearest
    50 stores and the screen had no way to ask for the 51st. In a dense estate
    that is half a suburb.
    """
    # "all" spans both business models, so bound it by the wider of the two radii
    # and let the per-type filter narrow it when the customer picks one.
    bounds_type = vendor_type if vendor_type in ("retail_refill", "wholesale_b2b") else "wholesale_b2b"
    user_point, neighbour_cells, max_distance_m = _search_bounds(lat, lng, bounds_type)

    query = (
        select(Vendor)
        .options(joinedload(Vendor.products.and_(live_product())))
        .where(
            discoverable_vendor(),
            Vendor.h3_index_res8.in_(neighbour_cells),
            Vendor.location.isnot(None),
            # Never list a vendor the customer cannot actually order from.
            ST_DWithin(Vendor.location, user_point, max_distance_m),
        )
    )

    if vendor_type and vendor_type != "all":
        query = query.where(Vendor.vendor_type == vendor_type)


    if search_query and search_query.strip():
        # Postgres TSVECTOR Full-Text Search on Vendor.search_vector
        search_term = search_query.strip()
        tsquery = func.websearch_to_tsquery('english', search_term)
        query = query.where(Vendor.search_vector.op("@@")(tsquery))
        
    # `joinedload` on a collection multiplies rows, so a LIMIT applied to the
    # joined result would count *product* rows — page 1 would be four stores and
    # half of a fifth store's catalogue. SQLAlchemy sees the collection load and
    # wraps the limited select in a subquery so the window counts vendors, which
    # is the behaviour this relies on; a rewrite to a plain join must page in a
    # subquery by hand.
    query = (
        query.order_by(*stable(ST_Distance(Vendor.location, user_point), key=Vendor.id))
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    return await _annotated(session, result.unique().scalars().all())