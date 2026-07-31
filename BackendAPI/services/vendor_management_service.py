import logging
import h3
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, update
from sqlalchemy.orm import joinedload
from uuid import UUID
from models.vendor_model import Vendor
from models.product_model import Product
from models.order_model import Order, OrderItem
from models.user_model import User
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from services.expo_push_service import send_push_message, dispatch_background
from services.notification_service import create_notification, push_allowed
import asyncio

logger = logging.getLogger(__name__)


# ── BUG-05 FIX: Stock Restoration Helper ──────────────────────────────────
async def _restore_order_stock(session: AsyncSession, order: Order):
    """Atomically restore product stock for all items in a cancelled/rejected order."""
    items_q = select(OrderItem).where(OrderItem.order_id == order.id)
    result = await session.execute(items_q)
    items = result.scalars().all()

    for item in items:
        await session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(
                stock=Product.stock + item.quantity,
                is_available=True  # Re-enable if it was auto-disabled
            )
        )
    if items:
        logger.info(f"Restored stock for {len(items)} items from order {order.id}")


async def get_vendor_by_clerk_id(session: AsyncSession, clerk_id: str, vendor_id: UUID = None):
    from sqlalchemy import or_, and_
    if vendor_id:
        query = select(Vendor).where(
            and_(
                Vendor.id == vendor_id,
                or_(Vendor.clerk_id == clerk_id, Vendor.staff_clerk_id == clerk_id)
            )
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()
    else:
        query = select(Vendor).where(or_(Vendor.clerk_id == clerk_id, Vendor.staff_clerk_id == clerk_id))
        result = await session.execute(query)
        return result.scalars().first()

async def get_all_vendors_by_clerk_id(session: AsyncSession, clerk_id: str):
    from sqlalchemy import or_
    query = select(Vendor).where(or_(Vendor.clerk_id == clerk_id, Vendor.staff_clerk_id == clerk_id))
    result = await session.execute(query)
    return result.scalars().all()


async def register_vendor(session: AsyncSession, clerk_id: str, data: dict):
    from routes.auth_routes import sanitize_phone_number
    if "phone_number" in data and data["phone_number"]:
         data["phone_number"] = sanitize_phone_number(data["phone_number"])
         
    existing = await get_vendor_by_clerk_id(session, clerk_id)
    if existing:
        # Upsert for Onboarding
        if data.get("phone_number"):
            existing.phone_number = data["phone_number"]
        if data.get("business_name"):
            existing.business_name = data["business_name"]
        if data.get("vendor_type"):
            existing.vendor_type = data["vendor_type"]
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    vendor = Vendor(
        clerk_id=clerk_id,
        owners_name=data["owners_name"],
        business_name=data["business_name"],
        email=data["email"],
        phone_number=data.get("phone_number"),
        profile_pic=data.get("profile_pic"),
        vendor_type=data.get("vendor_type", "retail_refill"),
    )
    session.add(vendor)
    await session.commit()
    await session.refresh(vendor)
    return vendor


async def update_vendor_profile(session: AsyncSession, clerk_id: str, data: dict):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    updatable_fields = [
        "business_name", "owners_name", "phone_number", "profile_pic",
        "business_license", "location_address", "delivery_radius",
        "shift_start", "shift_end", "preferred_payment_method", "vendor_type",
        "is_online", "deposit_fee"
    ]

    # Validate deposit_fee range before applying
    if "deposit_fee" in data and data["deposit_fee"] is not None:
        fee = float(data["deposit_fee"])
        if fee < 0 or fee > 5000:
            raise HTTPException(status_code=400, detail="Deposit fee must be between KSH 0 and KSH 5,000.")

    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(vendor, field, data[field])

    if "lat" in data and "lng" in data and data["lat"] is not None:
        vendor.lat = data["lat"]
        vendor.lng = data["lng"]
        vendor.location = from_shape(Point(data["lng"], data["lat"]), srid=4326)
        vendor.h3_index_res8 = str(h3.latlng_to_cell(data["lat"], data["lng"], 8))

    await session.commit()
    await session.refresh(vendor)
    return vendor


async def create_product(session: AsyncSession, clerk_id: str, data: dict):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Discount validation: prevent negative pricing
    price = float(data["price"])
    discount = float(data.get("discount", 0))
    if discount < 0:
        raise HTTPException(status_code=400, detail="Discount cannot be negative.")
    if discount >= price:
        raise HTTPException(status_code=400, detail=f"Discount (KSH {discount}) must be less than the product price (KSH {price}).")

    product = Product(
        vendor_id=vendor.id,
        name=data["name"],
        description=data.get("description"),
        image_url=data["image_url"],
        price=price,
        discount=discount,
        capacity=data["capacity"],
        weight_kg=data.get("weight_kg", 20.0),
        minimum_order_qty=data.get("minimum_order_qty", 1),
        unit=data["unit"],
        stock=data["stock"],
        is_available=data.get("is_available", True),
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, clerk_id: str, product_id: UUID, data: dict):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    product = await session.get(Product, product_id)
    if not product or product.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    # Discount validation: prevent negative pricing
    new_price = float(data.get("price", product.price))
    new_discount = float(data.get("discount", product.discount))
    if new_discount < 0:
        raise HTTPException(status_code=400, detail="Discount cannot be negative.")
    if new_discount >= new_price:
        raise HTTPException(status_code=400, detail=f"Discount (KSH {new_discount}) must be less than the product price (KSH {new_price}).")

    updatable_fields = [
        "name", "description", "image_url", "price", "discount",
        "capacity", "weight_kg", "minimum_order_qty", "unit", "stock", "is_available"
    ]
    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(product, field, data[field])

    await session.commit()
    await session.refresh(product)
    return product


async def delete_product(session: AsyncSession, clerk_id: str, product_id: UUID):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    product = await session.get(Product, product_id)
    if not product or product.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    await session.delete(product)
    await session.commit()
    return {"message": "Product deleted successfully"}


async def get_vendor_orders(
    session: AsyncSession, 
    clerk_id: str, 
    search_query: str = None, 
    status_filter: str = "All",
    skip: int = 0, 
    limit: int = 50
):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from sqlalchemy import and_, cast, String
    conditions = [Order.vendor_id == vendor.id]
    
    if search_query:
        # Search by order ID string
        conditions.append(cast(Order.id, String).ilike(f"%{search_query}%"))
        
    if status_filter and status_filter != "All":
        # Ensure it is lowered as our DB stores statuses in lowercase
        conditions.append(Order.order_status == status_filter.lower())

    query = (
        select(Order)
        .where(and_(*conditions))
        .options(
            joinedload(Order.order_item).joinedload(OrderItem.product),
            joinedload(Order.user),
            joinedload(Order.deliverer)
        )
        .order_by(Order.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_vendor_products(
    session: AsyncSession, 
    clerk_id: str, 
    search_query: str = None, 
    stock_filter: str = "All",
    limit: int = 20, 
    offset: int = 0
):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from sqlalchemy import and_, or_
    conditions = [Product.vendor_id == vendor.id]
    
    order_by_clauses = []
    
    if search_query and search_query.strip():
        ts_query = func.websearch_to_tsquery('english', search_query)
        conditions.append(Product.search_vector.op('@@')(ts_query))
        order_by_clauses.append(func.ts_rank(Product.search_vector, ts_query).desc())
        
    if stock_filter == "Low Stock":
        conditions.append(and_(Product.stock > 0, Product.stock <= 5))
    elif stock_filter == "Out of Stock":
        conditions.append(Product.stock == 0)

    # Always order alphabetically by name as secondary/fallback ordering
    order_by_clauses.append(Product.name.asc())

    query = (
        select(Product)
        .where(and_(*conditions))
        .order_by(*order_by_clauses)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    return result.scalars().all()


async def update_order_status(session: AsyncSession, clerk_id: str, order_id: UUID, new_status: str):
    from services.order_service import validate_status_transition

    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    order = await session.get(Order, order_id)
    if not order or order.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Order not found")

    valid_statuses = ["accepted", "rejected", "preparing", "ready", "cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    # BUG-01 FIX: Enforce state machine transitions
    if not validate_status_transition(order.order_status, new_status):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition from '{order.order_status}' to '{new_status}'."
        )

    # --- Wholesale Vendor Cash Float Check ---
    if new_status == "accepted" and order.payment_method == "cash":
        required_float = float(order.platform_total or 0)
        current_balance = float(vendor.wallet_balance or 0)
        if current_balance < required_float:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient Wallet Balance to cover Platform Commission. Please top up KSH {required_float:,.2f} to accept this Cash order."
            )

    order.order_status = new_status

    # BUG-05 FIX: Restore stock on rejection/cancellation
    if new_status in ("rejected", "cancelled"):
        await _restore_order_stock(session, order)
        # Flag paid orders for refund processing
        if order.payment_status == "paid":
            order.payment_status = "refund_pending"

    await session.commit()
    
    # Broadcast real-time order status update via WebSocket (BUG-03 FIX: single broadcast)
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id) if order.deliverer_id else "",
            payload={"action": "ORDER_STATUS_UPDATE", "order_id": str(order.id), "status": new_status}
        )
    except Exception as e:
        logger.error(f"WS Broadcast fail in update_order_status: {e}")

    customer = await session.get(User, order.customer_id)
    if customer:
        title = "Order Status Updated"
        body = f"Your order is now {new_status}!"
        action_url = f"/(screens)/OrderDetail/{order.id}"
        await create_notification(
            session=session,
            user_id=customer.id,
            user_type="customer",
            title=title,
            message=body,
            message_type="order_update",
            action_url=action_url,
            related_order_id=order.id
        )
        if customer.push_token and push_allowed(customer, "order_update"):
            dispatch_background(send_push_message(
                to=customer.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    return {"message": f"Order status updated to '{new_status}'"}


async def get_vendor_dashboard(session: AsyncSession, clerk_id: str):
    from datetime import datetime, timedelta
    
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    total_orders_q = select(func.count(Order.id)).where(
        and_(Order.vendor_id == vendor.id, Order.order_status != "cancelled")
    )
    total_revenue_q = select(func.sum(
        func.coalesce(Order.vendor_net, Order.total_amount)
    )).where(
        and_(
            Order.vendor_id == vendor.id, 
            Order.payment_status == "paid",
            Order.order_status != "cancelled"
        )
    )
    pending_orders_q = select(func.count(Order.id)).where(
        and_(Order.vendor_id == vendor.id, Order.order_status == "pending")
    )
    product_count_q = select(func.count(Product.id)).where(Product.vendor_id == vendor.id)

    total_orders = (await session.execute(total_orders_q)).scalar() or 0
    total_revenue = float((await session.execute(total_revenue_q)).scalar() or 0)
    pending_orders = (await session.execute(pending_orders_q)).scalar() or 0
    product_count = (await session.execute(product_count_q)).scalar() or 0

    # Calculate weekly revenue (last 7 days, Mon-Sun or just 7 days leading to today)
    # Actually, a simple 7-day array for chart data [0, 0, 0, 0, 0, 0, 0] 
    # based on weekday. 0=Mon, 6=Sun
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    
    weekly_revenue_q = select(
        Order.created_at,
        func.coalesce(Order.vendor_net, Order.total_amount)
    ).where(
        and_(
            Order.vendor_id == vendor.id,
            Order.payment_status == "paid",
            Order.order_status != "cancelled",
            Order.created_at >= start_of_week
        )
    )
    weekly_res = await session.execute(weekly_revenue_q)
    weekly_orders = weekly_res.all()
    
    weekly_revenue_arr = [0.0] * 7
    for order_date, amount in weekly_orders:
        if order_date:
            day_index = order_date.weekday() # 0 = Monday, 6 = Sunday
            weekly_revenue_arr[day_index] += float(amount)

    return {
        "vendor_id": str(vendor.id),
        "business_name": vendor.business_name,
        "vendor_type": vendor.vendor_type,
        "is_online": vendor.is_online,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "pending_orders": pending_orders,
        "product_count": product_count,
        "rating": vendor.rating or 0,
        "weekly_revenue": weekly_revenue_arr,
    }


async def cancel_order(session: AsyncSession, clerk_id: str, order_id: UUID):
    """Cancel an order before preparation"""
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    order = await session.get(Order, order_id)
    if not order or order.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Order not found or does not belong to this vendor")

    # Only allow cancellation for orders that haven't been processed yet
    valid_cancellations = ["pending", "accepted", "unassigned"]
    if order.order_status not in valid_cancellations:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order with status '{order.order_status}'. Only pending, accepted, or unassigned orders can be cancelled."
        )

    order.order_status = "cancelled"

    # BUG-05 FIX: Restore stock on cancellation
    await _restore_order_stock(session, order)
    # Flag paid orders for refund
    if order.payment_status == "paid":
        order.payment_status = "refund_pending"
        # Track the platform revenue lost due to this cancellation
        order.commission_lost = order.platform_total

    # BUG-ORD-01 FIX: Commit critical state change FIRST before notifications
    # This prevents notification failures from rolling back the cancellation
    await session.commit()

    # Broadcast real-time order status update via WebSocket
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id) if order.deliverer_id else "",
            payload={"action": "ORDER_STATUS_UPDATE", "order_id": str(order.id), "status": "cancelled"}
        )
    except Exception as e:
        logger.error(f"WS Broadcast fail in cancel_order: {e}")

    return {"message": "Order cancelled successfully", "order_id": str(order.id)}


async def assign_order_rider(session: AsyncSession, clerk_id: str, order_id: UUID, rider_id: str):
    from models.deliverer_model import Deliverer

    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from core.redis_client import redis_lock
    lock_key = f"order_accept_lock:{order_id}"
    
    async with redis_lock(lock_key, timeout_seconds=10) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="This order is currently being modified by another process. Please try again.")

        order = await session.get(Order, order_id)
        if not order or order.vendor_id != vendor.id:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.order_status not in ["pending", "accepted", "unassigned", "preparing"]:
            raise HTTPException(status_code=400, detail="Order cannot be assigned at this stage.")

        try:
            rider_uuid = UUID(rider_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid rider ID")

        rider = await session.get(Deliverer, rider_uuid)
        if not rider:
            raise HTTPException(status_code=404, detail="Rider not found")

        # BUG-ORD-02 FIX: Verify rider is approved for this vendor before assignment
        from models.vendor_rider_model import VendorRiderRegistry
        from sqlalchemy import and_
        registry_q = select(VendorRiderRegistry).where(
            and_(
                VendorRiderRegistry.rider_id == rider.id,
                VendorRiderRegistry.vendor_id == vendor.id,
                VendorRiderRegistry.status == "approved"
            )
        )
        registry_result = await session.execute(registry_q)
        if not registry_result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="This rider is not approved for your vendor. Approve them first via Rider Management."
            )

        # Proceed to assign rider to order
        order.deliverer_id = rider.id
        order.order_status = "accepted" if order.order_status == "pending" else order.order_status

        await session.commit()

    # Broadcast real-time order status update via WebSocket
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id),
            payload={"action": "ORDER_ASSIGNED", "order_id": str(order.id), "status": order.order_status, "deliverer_id": str(rider.id)}
        )
        
        # Retract Trip Radar: notify all approved riders for this vendor that the order is taken
        approved_riders_q = select(VendorRiderRegistry.rider_id).where(
            and_(
                VendorRiderRegistry.vendor_id == vendor.id,
                VendorRiderRegistry.status == "approved"
            )
        )
        approved_result = await session.execute(approved_riders_q)
        approved_rider_ids = [str(r) for r in approved_result.scalars().all()]
        if approved_rider_ids:
            await manager.broadcast_to_riders(
                rider_ids=approved_rider_ids,
                payload={"action": "TRIP_RADAR_RETRACT", "order_id": str(order.id)}
            )
    except Exception as e:
        logger.error(f"WS Broadcast fail in assign_order_rider: {e}")

    # Notify Rider
    title = "New Fleet Order Assigned 📦"
    body = f"You have been manually assigned an order by {vendor.business_name}."
    action_url = "/(screens)/ActiveDelivery"
    await create_notification(
        session=session,
        user_id=rider.id,
        user_type="rider",
        title=title,
        message=body,
        message_type="delivery_assigned",
        action_url=action_url,
        related_order_id=order.id
    )
    if rider.push_token:
        dispatch_background(send_push_message(
            to=rider.push_token,
            title=title,
            body=body,
            data={"url": action_url}
        ))

    # Notify Customer
    customer = await session.get(User, order.customer_id)
    if customer:
        title = "Rider Assigned 🛵"
        body = f"{rider.full_name} is on the way to pick up your order!"
        action_url = f"/(screens)/OrderDetail/{order.id}"
        await create_notification(
            session=session,
            user_id=customer.id,
            user_type="customer",
            title=title,
            message=body,
            message_type="order_assigned",
            action_url=action_url,
            related_order_id=order.id
        )
        if customer.push_token and push_allowed(customer, "order_assigned"):
            dispatch_background(send_push_message(
                to=customer.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    return {"message": "Rider assigned successfully", "order_id": str(order.id)}


async def receive_bottles_from_rider(
    session: AsyncSession,
    clerk_id: str,
    rider_id: str,
    received_10L: int,
    received_20L: int,
    note: str | None = None,
):
    """
    Clear empty-bottle debt when a rider physically hands bottles back to the vendor.

    Delegates to `bottle_ledger_service.settle_empties`, which locks the row, checks
    the amount against what is actually outstanding, and writes an audit entry.
    Three things changed from the version this replaced:

    * It no longer requires a registry row. Radar dispatch lets a rider deliver for
      a vendor they never registered with, and those riders could not return
      bottles at all — the endpoint 404'd.
    * Over-receipt is rejected instead of silently clamped to zero. The vendor app
      checked the limit client-side; the API accepted anything.
    * Every settlement leaves a record of who confirmed it and when.
    """
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from services.bottle_ledger_service import settle_empties

    return await settle_empties(
        session,
        rider_id=rider_id,
        vendor_id=vendor.id,
        received_by_capacity={10: received_10L, 20: received_20L},
        actor_clerk_id=clerk_id,
        note=note,
    )


async def get_vendor_bottle_debtors(session: AsyncSession, clerk_id: str):
    """Every rider holding this vendor's empties, registered or not."""
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from services.bottle_ledger_service import get_vendor_outstanding

    return {"riders": await get_vendor_outstanding(session, vendor.id)}
