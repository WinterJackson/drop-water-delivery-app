from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from models.product_model import Product
from models.vendor_model import Vendor
from schemas.product_schemas import ProductFull
from schemas.vendor_schemas import VendorStorefront
from services.dispatch_policy import within_service_radius
from services.vendor_service import _annotated, discoverable_vendor
from services.product_service import live_product

from sqlalchemy.orm import joinedload
from geoalchemy2 import Geography
from utils.paging import stable


#: The radius predicate now lives in `dispatch_policy`, beside the two figures
#: it measures against, because product discovery needs it too and a second copy
#: is how the home grid came to ignore a limit the vendor list was enforcing.
#: Re-exported under the old private name so the compiled-SQL assertion in
#: `tests/test_paging_integrity.py` keeps pointing at the predicate this module
#: actually applies.
_within_service_radius = within_service_radius


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

async def search_vendors_service(session: AsyncSession, query: str | None, limit: int = 20, offset: int = 0, user_lat: float | None = None, user_lng: float | None = None) -> list[VendorStorefront]:
    """Stores matching a search, marked with whether each one is trading.

    The annotation is not optional. `VendorStorefront` embeds `StorefrontState`,
    whose fields default *permissively* — a read that does not stamp them serves
    `store_state: "open"` and `is_accepting_orders: true` for every store,
    whatever its real state. So a paused shop appeared open in search and closed
    on its own page: the two surfaces that have to agree, disagreeing.

    `vendor_service` has always annotated its seven reads. This one was missed
    because it lives in a different module, and the guard test enumerated those
    seven by name rather than discovering every read that serves this schema.
    """
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
    return await _annotated(session, result.scalars().all())
