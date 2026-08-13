"""The catalogue, from the platform's side.

`Product` was read in exactly one place — the top-sellers query in
`admin_analytics_service` — so the platform could tell you what sold and not
what it was selling. There was no way to find a mispriced item, see what is out
of stock, or take a product down.

## Price outliers, and why the band is (category, capacity)

A 20-litre refill and a 500ml bottle are both `Product` rows, and comparing
their prices produces nothing but noise. Outliers are therefore found **within a
band**, against the median for that band rather than the mean: one item priced
at 40,000 by a misplaced decimal drags a mean far enough to hide itself, which is
precisely the case this exists to catch.

Capacity **alone** is not the band, and the first run proved it: `accessories`
(675–1,406) and `dispensers_coolers` (14,655–23,462) both carry `capacity = 0`,
so they pooled into one group with a median of 1,250 and every dispenser on the
platform was reported as an 18× outlier — 21 false positives out of 114 products,
which is a screen nobody would open twice. The band is the pair.

The median is computed in Postgres with `percentile_cont`. Pulling 114 rows into
Python is fine; pulling 114,000 is not, and the query is the same either way.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Float, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset

from models.product_model import Product
from models.vendor_model import Vendor

#: How far from its band's median a price has to sit before it is worth a look.
#: 2.5× catches a decimal slip (10× or 0.1×) with room to spare, without
#: flagging a genuinely premium product.
OUTLIER_FACTOR = Decimal("2.5")


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


async def summary(db: AsyncSession) -> dict[str, Any]:
    async def count(*where) -> int:
        query = select(func.count()).select_from(Product)
        for clause in where:
            query = query.where(clause)
        return int((await db.execute(query)).scalar() or 0)

    total = await count()
    listed = await count(Product.is_available.is_(True))

    # Out of stock but still listed is the one combination that costs an order:
    # a customer adds it, pays, and the vendor cannot fulfil.
    out_of_stock_listed = await count(Product.is_available.is_(True), Product.stock <= 0)

    low_stock = await count(
        Product.is_available.is_(True),
        Product.stock > 0,
        Product.stock <= Product.low_stock_threshold,
    )

    vendors_selling = int(
        (
            await db.execute(
                select(func.count(func.distinct(Product.vendor_id))).where(
                    Product.is_available.is_(True)
                )
            )
        ).scalar()
        or 0
    )

    return {
        "total": total,
        "listed": listed,
        "hidden": total - listed,
        "out_of_stock_listed": out_of_stock_listed,
        "low_stock": low_stock,
        "vendors_selling": vendors_selling,
        "outliers": len(await price_outliers(db)),
    }


async def price_outliers(db: AsyncSession) -> list[dict[str, Any]]:
    """Products priced far from the median for their capacity.

    Returns an empty list rather than raising when a band has too few products
    to have a meaningful median — with two items in a band, one of them is
    always "the outlier" and the finding is noise.
    """
    MIN_BAND_SIZE = 4

    medians = (
        await db.execute(
            select(
                Product.category,
                Product.capacity,
                func.percentile_cont(0.5)
                .within_group(func.cast(Product.price, Float))
                .label("median"),
                func.count().label("n"),
            )
            .where(Product.is_available.is_(True))
            .group_by(Product.category, Product.capacity)
        )
    ).all()

    bands = {
        (category, capacity): Decimal(str(median))
        for category, capacity, median, n in medians
        if n >= MIN_BAND_SIZE and median
    }
    if not bands:
        return []

    rows = (
        await db.execute(
            select(Product, Vendor.business_name)
            .outerjoin(Vendor, Product.vendor_id == Vendor.id)
            .where(Product.is_available.is_(True))
        )
    ).all()

    out: list[dict[str, Any]] = []
    for product, vendor_name in rows:
        median = bands.get((product.category, product.capacity))
        if median is None:
            continue
        price = Decimal(str(product.price or 0))
        if price <= 0 or median <= 0:
            continue

        ratio = price / median
        if ratio >= OUTLIER_FACTOR or ratio <= (Decimal("1") / OUTLIER_FACTOR):
            out.append(
                {
                    "id": str(product.id),
                    "name": product.name,
                    "vendor": vendor_name,
                    "vendor_id": str(product.vendor_id) if product.vendor_id else None,
                    "price": _money(product.price),
                    "capacity": float(product.capacity or 0),
                    "band_median": _money(median),
                    "band": (
                        product.category.value
                        if hasattr(product.category, "value")
                        else str(product.category)
                    ),
                    "ratio": round(float(ratio), 2),
                    "direction": "high" if ratio >= OUTLIER_FACTOR else "low",
                }
            )

    # Worst first: the furthest from normal is the one worth opening.
    out.sort(key=lambda item: abs(item["ratio"] - 1), reverse=True)
    return out


async def list_products(
    db: AsyncSession,
    *,
    search: str | None = None,
    view: str = "all",
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]:
    query = select(Product, Vendor.business_name).outerjoin(
        Vendor, Product.vendor_id == Vendor.id
    )

    if view == "out_of_stock":
        query = query.where(Product.is_available.is_(True), Product.stock <= 0)
    elif view == "low_stock":
        query = query.where(
            Product.is_available.is_(True),
            Product.stock > 0,
            Product.stock <= Product.low_stock_threshold,
        )
    elif view == "hidden":
        query = query.where(Product.is_available.is_(False))

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(Product.name.ilike(term), Vendor.business_name.ilike(term)))

    order = keyset.Order(Product.created_at, Product.id)
    result = await db.execute(keyset.seek(query, order, cursor).limit(limit + 1))
    rows, next_cursor = keyset.split(result.all(), limit, order)

    items = [
        {
            "id": str(product.id),
            "name": product.name,
            "vendor": vendor_name,
            "vendor_id": str(product.vendor_id) if product.vendor_id else None,
            "price": _money(product.price),
            "capacity": float(product.capacity or 0),
            "unit": product.unit,
            "stock": product.stock,
            "low_stock_threshold": product.low_stock_threshold,
            "is_available": bool(product.is_available),
            "category": product.category.value
            if hasattr(product.category, "value")
            else product.category,
            "created_at": product.created_at.isoformat() if product.created_at else None,
        }
        for product, vendor_name in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


async def set_availability(db: AsyncSession, product_id, listed: bool) -> Product | None:
    """Take a product down, or put it back.

    Deliberately a *hide*, never a delete. Order history references products,
    and a deleted row turns every past order that contained it into a receipt
    with a hole in it.
    """
    product = await db.get(Product, product_id)
    if product is None:
        return None
    product.is_available = listed
    return product
