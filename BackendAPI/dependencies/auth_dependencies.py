from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.dependencies import get_db
from models.deliverer_model import Deliverer
from models.user_model import User
from models.vendor_model import Vendor
from utils.verify_user_token import get_current_user


async def get_current_customer(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    clerk_id = user["sub"]
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered customer.")
    return user


async def get_current_vendor(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    clerk_id = user["sub"]
    result = await db.execute(select(Vendor).where(or_(Vendor.clerk_id == clerk_id, Vendor.staff_clerk_id == clerk_id)))
    db_vendor = result.scalar_one_or_none()
    if not db_vendor:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered vendor.")
    return user


async def get_current_rider(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    clerk_id = user["sub"]
    result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
    db_rider = result.scalar_one_or_none()
    if not db_rider:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered rider.")
    return user


# ── Order-scoped authorisation ───────────────────────────────────────────────
# Authenticating a token proves *who* is calling. It says nothing about whether
# that caller has any relationship to the order they named. Every order-scoped
# endpoint — REST or WebSocket — must go through `authorise_order_access`, or a
# leaked/guessed order id exposes one customer's live delivery location and
# contact details to any other signed-in account.

async def resolve_order_role(session: AsyncSession, order_id: UUID, clerk_id: str) -> str | None:
    """Return the caller's role on this order, or None if they have none.

    One of: "customer", "vendor", "rider".
    """
    from models.order_model import Order

    order = await session.get(Order, order_id)
    if order is None:
        return None

    customer = await session.get(User, order.customer_id) if order.customer_id else None
    if customer is not None and customer.clerk_id == clerk_id:
        return "customer"

    vendor = await session.get(Vendor, order.vendor_id) if order.vendor_id else None
    if vendor is not None and clerk_id in {vendor.clerk_id, getattr(vendor, "staff_clerk_id", None)}:
        return "vendor"

    if order.deliverer_id:
        rider = await session.get(Deliverer, order.deliverer_id)
        if rider is not None and rider.clerk_id == clerk_id:
            return "rider"

    return None


async def authorise_order_access(
    session: AsyncSession,
    order_id: UUID,
    clerk_id: str,
    allowed_roles: tuple[str, ...] = ("customer", "vendor", "rider"),
) -> str:
    """Assert the caller is a party to this order; return their role.

    Raises 404 rather than 403 when the caller has no relationship to the order:
    confirming that an order id exists is itself a small information leak.
    """
    role = await resolve_order_role(session, order_id, clerk_id)
    if role is None or role not in allowed_roles:
        raise HTTPException(status_code=404, detail="Order not found")
    return role


async def owns_entity(session: AsyncSession, entity_type: str, entity_id: str, clerk_id: str) -> bool:
    """True if `clerk_id` is the owner of the given entity id.

    Used by the realtime endpoints, where the entity id arrives in the URL path
    and must be proven to belong to the token holder before we start streaming
    that entity's order events to the socket.
    """
    try:
        parsed_id = UUID(str(entity_id))
    except (ValueError, TypeError, AttributeError):
        return False

    if entity_type == "customer":
        row = await session.get(User, parsed_id)
        return row is not None and row.clerk_id == clerk_id
    if entity_type == "vendor":
        row = await session.get(Vendor, parsed_id)
        return row is not None and clerk_id in {row.clerk_id, getattr(row, "staff_clerk_id", None)}
    if entity_type == "rider":
        row = await session.get(Deliverer, parsed_id)
        return row is not None and row.clerk_id == clerk_id
    return False
