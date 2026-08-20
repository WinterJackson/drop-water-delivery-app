from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from models.vendor_favorite_model import VendorFavorite
from models.user_model import User
from models.vendor_model import Vendor
from models.order_model import Order, OrderItem
from utils.money import money_str


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
    """
    Fetch the most recent completed/delivered order by this user to a specific vendor.
    Returns order details + items with current product data (for price change detection).
    """
    user_id = await _get_user_id_from_clerk(session, clerk_id)

    # Get the most recent order to this vendor (any status except cancelled)
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
        )
        .order_by(desc(Order.created_at))
        .limit(1)
    )
    result = await session.execute(order_query)
    order = result.scalar_one_or_none()

    if not order:
        return None

    # This feeds a Reorder button. Offering it against a store that is shut
    # produces a full basket and a refusal at the last step.
    from services import vendor_availability

    await vendor_availability.annotate(session, [order.vendor] if order.vendor else [])

    return {
        "id": str(order.id),
        "order_status": order.order_status,
        "total_amount": money_str(order.total_amount),
        "delivery_fee": money_str(order.delivery_fee),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "vendor": {
            "id": str(order.vendor.id),
            "business_name": order.vendor.business_name,
            "profile_pic": order.vendor.profile_pic,
            "is_online": order.vendor.is_online,
            "is_accepting_orders": order.vendor.is_accepting_orders,
            "store_state": order.vendor.store_state,
            "store_reason": order.vendor.store_reason,
            "reopens_at": (
                order.vendor.reopens_at.isoformat() if order.vendor.reopens_at else None
            ),
        } if order.vendor else None,
        "items": [
            {
                "id": str(item.id),
                "product_id": str(item.product_id),
                "quantity": item.quantity,
                "price_at_order": money_str(item.price),
                "subtotal_at_order": money_str(item.Subtotal),
                "product": {
                    "id": str(item.product.id),
                    "name": item.product.name,
                    "price": money_str(item.product.price),
                    "discount": money_str(item.product.discount),
                    "image_url": item.product.image_url,
                    "is_available": item.product.is_available if hasattr(item.product, 'is_available') else True,
                    "stock_quantity": item.product.stock,
                } if item.product else None,
            }
            for item in (order.order_item or [])
        ],
    }
