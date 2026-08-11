import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from uuid import UUID

from models.order_model import Order
from schemas.contact_schemas import OrderContactsResponse, ContactInfo

logger = logging.getLogger(__name__)

# Contact info is only visible during active fulfillment states
ACTIVE_ORDER_STATES = ["accepted", "preparing", "ready", "picked_up", "pending_review", "mismatch_pending"]

async def get_order_contacts(session: AsyncSession, order_id: UUID, requester_clerk_id: str) -> OrderContactsResponse:
    """
    Securely retrieve cross-party contact information for an active order.
    Only participants (customer, vendor, or rider) can access the other parties' contacts.
    Contacts are restricted to active fulfillment states only.
    """
    # Fetch the order with all related parties eagerly loaded
    stmt = (
        select(Order)
        .options(
            selectinload(Order.user),
            selectinload(Order.vendor),
            selectinload(Order.deliverer)
        )
        .where(Order.id == order_id)
    )
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Enforce active-state gate
    if order.order_status not in ACTIVE_ORDER_STATES:
        raise HTTPException(
            status_code=403,
            detail="Contact information is only available during active fulfillment."
        )

    # ── Determine the caller's role ──────────────────────────────────────
    # Customer: User.clerk_id matches
    is_customer = (order.user is not None) and (order.user.clerk_id == requester_clerk_id)

    # Vendor: the owner, or live staff of that store. Staff used to be one
    # nullable column on the vendor row; it is a membership table now.
    from services.vendor_staff_service import is_store_member

    is_vendor = await is_store_member(session, requester_clerk_id, order.vendor)

    # Rider: Deliverer.clerk_id matches
    is_rider = (order.deliverer is not None) and (order.deliverer.clerk_id == requester_clerk_id)

    if not (is_customer or is_vendor or is_rider):
        raise HTTPException(status_code=403, detail="You are not authorized to view contacts for this order.")

    # ── Build contact list (exclude caller's own info) ───────────────────
    contacts = []

    # Customer contact (visible to vendor & rider)
    if not is_customer and order.user:
        contacts.append(
            ContactInfo(
                role="customer",
                name=order.user.full_name or "Customer",
                phone=order.phone or order.user.phone_number or "N/A",
                profile_pic=order.user.profile_pic
            )
        )

    # Vendor contact (visible to customer & rider)
    if not is_vendor and order.vendor:
        contacts.append(
            ContactInfo(
                role="vendor",
                name=order.vendor.business_name or "Vendor",
                phone=order.vendor.phone_number or "N/A",
                profile_pic=order.vendor.profile_pic
            )
        )

    # Rider contact (visible to customer & vendor)
    if not is_rider and order.deliverer:
        vehicle_info = str(order.deliverer.vehicle_type or "")
        if hasattr(order.deliverer.vehicle_type, 'value'):
            vehicle_info = order.deliverer.vehicle_type.value
        if order.deliverer.plate_number:
            vehicle_info += f" ({order.deliverer.plate_number})"

        contacts.append(
            ContactInfo(
                role="rider",
                name=order.deliverer.name or "Rider",
                phone=order.deliverer.phone_number or "N/A",
                vehicle_details=vehicle_info,
                profile_pic=order.deliverer.profile_pic
            )
        )

    return OrderContactsResponse(contacts=contacts)
