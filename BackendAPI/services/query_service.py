from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, func, or_
from geoalchemy2.functions import ST_DWithin
from models.product_model import Product
from models.vendor_model import Vendor
from schemas.product_schemas import ProductFull
from schemas.vendor_schemas import VendorOut
from services.dispatch_policy import DispatchPolicy
from services.vendor_service import discoverable_vendor
from services.product_service import live_product

from sqlalchemy.orm import joinedload
from geoalchemy2 import Geography
from utils.paging import stable


def _within_service_radius(user_location):
    """The predicate that keeps a search result orderable.

    One figure per vendor type — `retail_max_distance_km` /
    `wholesale_max_distance_km` — read through `DispatchPolicy`'s accessors so
    it is the configured row and not the shipped default. A store with no
    `vendor_type` is treated as retail, the narrower of the two: a NULL is a
    row nobody has classified, and guessing the wider radius would list it to
    customers who cannot be delivered to.

    Note the SQL: `vendor_type != 'wholesale_b2b'` is *NULL* for a NULL column,
    not true, so an unclassified store would drop out of both branches and out
    of search entirely. `coalesce` is what makes the two branches exhaustive.
    """
    retail_m = DispatchPolicy.max_distance_km("retail_refill") * 1000.0
    wholesale_m = DispatchPolicy.max_distance_km("wholesale_b2b") * 1000.0
    kind = func.coalesce(Vendor.vendor_type, "retail_refill")
    return and_(
        Vendor.location.isnot(None),
        or_(
            and_(kind == "wholesale_b2b", ST_DWithin(Vendor.location, user_location, wholesale_m)),
            and_(kind != "wholesale_b2b", ST_DWithin(Vendor.location, user_location, retail_m)),
        ),
    )


async def search_service(session: AsyncSession, query: str | None, limit: int = 20, offset: int = 0, category: str | None = None, mode: str | None = None, user_lat: float | None = None, user_lng: float | None = None) -> list[ProductFull]:
    # The join is unconditional. It used to happen only when coordinates were
    # supplied, purely to sort by distance — which meant a search without a
    # location had no access to the vendor row and therefore returned products
    # belonging to deleted and suspended stores.
    stmt = (
        select(Product)
        .options(joinedload(Product.vendor))
        .join(Vendor, Product.vendor_id == Vendor.id)
        .where(discoverable_vendor(), live_product())
    )

    order_by_clauses = []

    if user_lat is not None and user_lng is not None:
        user_location = func.ST_SetSRID(func.ST_MakePoint(user_lng, user_lat), 4326).cast(Geography)
        # Bounded by the *store's own* radius, so a wholesale depot stays
        # reachable at 15 km while a refill shop drops out past 2.5. Search used
        # only to sort by distance, never to cut: every product on the platform
        # was a search result, so the top hit for "20L" could be a shop in
        # another town — findable, tappable, and refused at checkout by the one
        # radius that is enforced. The directory has always filtered this way;
        # search is the screen most people actually use.
        stmt = stmt.where(_within_service_radius(user_location))
        order_by_clauses.append(func.ST_Distance(Vendor.location, user_location).asc())

    if mode == "deals":
        stmt = stmt.where(Product.discount > 0, Product.is_available == True)
        if category and category != "all":
            stmt = stmt.where(Product.category == category)
        order_by_clauses.append((Product.discount / Product.price).desc())
    elif mode == "refill_wholesale":
        if category and category != "all":
            stmt = stmt.where(Product.category == category, Product.is_available == True)
        else:
            stmt = stmt.where(Product.category.in_(["dispenser_refill", "jerrycan", "bulk_wholesale"]), Product.is_available == True)
        order_by_clauses.append(Product.created_at.desc())
    elif query and query.strip():
        # Full-text search with optional category filter
        ts_query = func.websearch_to_tsquery('english', query)
        stmt = stmt.where(Product.search_vector.op('@@')(ts_query))
        # `"all"` is the screen's word for *no* category filter, and the two
        # branches above already spell it that way. Compared literally here it
        # becomes `category = 'all'`, which matches no product on the platform —
        # a search that returns nothing whatever the customer typed.
        if category and category != "all":
            stmt = stmt.where(Product.category == category)
        order_by_clauses.append(func.ts_rank(Product.search_vector, ts_query).desc())
    elif category and category != "all":
        # Category-only browsing — no text query required
        stmt = stmt.where(Product.category == category)
        order_by_clauses.append(Product.created_at.desc())
    else:
        # No query and no category — return latest products
        order_by_clauses.append(Product.created_at.desc())
    
    if order_by_clauses:
        stmt = stmt.order_by(*stable(*order_by_clauses, key=Product.id))
    
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    products = result.unique().scalars().all()
    return products

async def search_vendors_service(session: AsyncSession, query: str | None, limit: int = 20, offset: int = 0, user_lat: float | None = None, user_lng: float | None = None) -> list[VendorOut]:
    stmt = select(Vendor).where(discoverable_vendor())
    order_by_clauses = []

    if user_lat is not None and user_lng is not None:
        user_location = func.ST_SetSRID(func.ST_MakePoint(user_lng, user_lat), 4326).cast(Geography)
        stmt = stmt.where(_within_service_radius(user_location))
        order_by_clauses.append(func.ST_Distance(Vendor.location, user_location).asc())

    if query and query.strip():
        ts_query = func.websearch_to_tsquery('english', query)
        stmt = stmt.where(Vendor.search_vector.op('@@')(ts_query))
        order_by_clauses.append(func.ts_rank(Vendor.search_vector, ts_query).desc())
    else:
        order_by_clauses.append(Vendor.created_at.desc())

    if order_by_clauses:
        stmt = stmt.order_by(*stable(*order_by_clauses, key=Vendor.id))

    stmt = stmt.limit(limit).offset(offset)
    
    result = await session.execute(stmt)
    vendors = result.scalars().all()
    return vendors
