from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from models.vendor_favorite_model import VendorFavorite
from models.user_model import User
from models.vendor_model import Vendor
from models.order_model import Order, OrderItem
from schemas.order_schema import BaseOrder


async def _get_user_id_from_clerk(session: AsyncSession, clerk_id: str):
    """Resolve clerk_id → internal user UUID."""
    result = await session.execute(select(User).where(User.clerk_id == clerk_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.id


async def get_vendor_favorites(session: AsyncSession, clerk_id: str):
    """Return all vendor favorites for a user, with vendor profile data."""
    user_id = await _get_user_id_from_clerk(session, clerk_id)
    query = (
        select(VendorFavorite)
        .where(VendorFavorite.user_id == user_id)
        .options(selectinload(VendorFavorite.vendor))
        .order_by(desc(VendorFavorite.created_at))
    )
    result = await session.execute(query)
    favorites = result.scalars().all()

    # `is_online` alone answers one of the five reasons a store may not be
    # taking orders, so a favourites list built on it showed a paused, suspended
    # or out-of-hours shop as open — on precisely the screen a customer opens
    # when they already know which store they want.
    from services import vendor_availability

    await vendor_availability.annotate(
        session, [fav.vendor for fav in favorites if fav.vendor]
    )

    return [
        {
            "id": str(fav.id),
            "vendor_id": str(fav.vendor_id),
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
            "vendor": {
                "id": str(fav.vendor.id),
                "business_name": fav.vendor.business_name,
                "profile_pic": fav.vendor.profile_pic,
                "location_address": fav.vendor.location_address,
                "rating": float(fav.vendor.rating) if fav.vendor.rating is not None else None,
                # Without the count the app cannot tell an unrated shop from a
                # badly rated one, and the favourites card used to answer that
                # by rendering a hardcoded "4.5 • Verified".
                "rating_count": fav.vendor.rating_count or 0,
                "is_online": fav.vendor.is_online,
                "is_accepting_orders": fav.vendor.is_accepting_orders,
                "store_state": fav.vendor.store_state,
                "store_reason": fav.vendor.store_reason,
                "reopens_at": (
                    fav.vendor.reopens_at.isoformat() if fav.vendor.reopens_at else None
                ),
                "vendor_type": fav.vendor.vendor_type.value if fav.vendor.vendor_type else None,
                "shift_start": fav.vendor.shift_start.strftime("%H:%M") if fav.vendor.shift_start else None,
                "shift_end": fav.vendor.shift_end.strftime("%H:%M") if fav.vendor.shift_end else None,
            } if fav.vendor else None,
        }
        for fav in favorites
    ]


async def add_vendor_favorite(session: AsyncSession, clerk_id: str, vendor_id: str):
    """Add a vendor to favorites. Idempotent — returns 409 if already exists."""
    user_id = await _get_user_id_from_clerk(session, clerk_id)

    # Verify vendor exists
    vendor_result = await session.execute(select(Vendor).where(Vendor.id == vendor_id))
    if not vendor_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Check existing
    existing = await session.execute(
        select(VendorFavorite).where(
            VendorFavorite.user_id == user_id,
            VendorFavorite.vendor_id == vendor_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Vendor already in favourites")

    fav = VendorFavorite(user_id=user_id, vendor_id=vendor_id)
    session.add(fav)
    await session.commit()
    return {"message": "Vendor added to favourites", "id": str(fav.id)}


async def remove_vendor_favorite(session: AsyncSession, clerk_id: str, vendor_id: str):
    """Remove a vendor from favorites."""
    user_id = await _get_user_id_from_clerk(session, clerk_id)
    result = await session.execute(
        select(VendorFavorite).where(
            VendorFavorite.user_id == user_id,
            VendorFavorite.vendor_id == vendor_id
        )
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise HTTPException(status_code=404, detail="Vendor favourite not found")
    await session.delete(fav)
    await session.commit()
    return {"message": "Vendor removed from favourites"}


async def get_last_order_to_vendor(session: AsyncSession, clerk_id: str, vendor_id: str):
    """The most recent non-cancelled order by this customer to this vendor.

    Returns the platform's own `BaseOrder`, not a shape invented here.

    It used to build a dict by hand, and that dict disagreed with the app's one
    `Order` declaration in the two ways that matter: the items came back under
    **`items`** where every other order response calls them `order_item`, and
    the money was `total_amount` and `delivery_fee` and nothing else. The hook
    is typed `Order`, so TypeScript asserted the wrong shape and never looked
    again — `lastOrder.order_item` was `undefined` on every render.

    The visible result was a Repeat Order screen that had never worked: an
    empty item list, a summary that read "Delivery Fee 120.00, Total Paid
    365.00" with the 245 of water missing between them, and a button whose
    handler opens `if (!lastOrder?.order_item?.length) return;` — so the one
    control on the screen did nothing at all, silently, on every tap.

    This is the second-table defect the guide already names one layer up, and
    it is why the fix belongs here rather than in the screen: there is one
    declaration of an order on the wire, and an endpoint that serves orders
    serves that.
    """
    user_id = await _get_user_id_from_clerk(session, clerk_id)

    # `deliverer` is loaded because `BaseOrder` serialises it. Every
    # relationship is `lazy="raise_on_sql"`, so an unloaded one is an error at
    # render time rather than a lazy SELECT — and an order that has been
    # delivered always has a rider to load.
    order_query = (
        select(Order)
        .where(
            Order.customer_id == user_id,
            Order.vendor_id == vendor_id,
            Order.order_status != "cancelled",
        )
        .options(
            selectinload(Order.order_item).selectinload(OrderItem.product),
            selectinload(Order.vendor),
            selectinload(Order.deliverer),
        )
        .order_by(desc(Order.created_at))
        .limit(1)
    )
    result = await session.execute(order_query)
    order = result.scalar_one_or_none()

    if not order:
        return None

    # No `vendor_availability.annotate` here. It used to run so the hand-rolled
    # dict could carry `store_state` and friends, but `OrderVendorSnippet` does
    # not declare them and the screen asks `vendor_availability` itself through
    # `useVendorDetails` — which is the one thing allowed to decide whether a
    # store is trading. Annotating for a field nobody serialises is a query per
    # request buying nothing.
    return BaseOrder.model_validate(order)
