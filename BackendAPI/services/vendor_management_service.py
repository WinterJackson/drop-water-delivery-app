import logging
from decimal import Decimal, InvalidOperation

from utils.money import money_str

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from uuid import UUID
from models.vendor_model import Vendor
from models.product_model import Product
from models.order_model import Order, OrderItem
from models.user_model import User
from services.expo_push_service import send_push_message, dispatch_background
from services.notification_service import create_notification, push_allowed
from sqlalchemy import func, and_
from services.order_service import apply_status_transition
from utils.paging import stable
from services.vendor_service import set_vendor_position

logger = logging.getLogger(__name__)


# Stock restoration lives in `order_service` with the rest of the reversal, so
# there is one implementation rather than three that drifted. Re-exported here
# because this module's own callers and its tests import it by this name.
async def _restore_order_stock(session: AsyncSession, order: Order):
    """Atomically restore product stock for all items in a cancelled/rejected order."""
    from services.order_service import restore_order_stock

    return await restore_order_stock(session, order)


async def _reachable_vendor_filter(session: AsyncSession, clerk_id: str):
    """`Vendor` rows this clerk id owns or staffs.

    Staff used to be `Vendor.staff_clerk_id`, one nullable column, so this was a
    two-term OR. It is a join table now — see `models/vendor_staff_model.py`.
    """
    from sqlalchemy import or_

    from services.vendor_staff_service import staffed_vendor_ids

    staffed = await staffed_vendor_ids(session, clerk_id)
    if staffed:
        return or_(Vendor.clerk_id == clerk_id, Vendor.id.in_(staffed))
    return Vendor.clerk_id == clerk_id


async def get_vendor_by_clerk_id(session: AsyncSession, clerk_id: str, vendor_id: UUID = None):
    from sqlalchemy import and_

    reachable = await _reachable_vendor_filter(session, clerk_id)
    if vendor_id:
        query = select(Vendor).where(and_(Vendor.id == vendor_id, reachable))
        result = await session.execute(query)
        return result.scalar_one_or_none()
    else:
        # Deterministic: an owner with two stores must not get a different one
        # from request to request just because Postgres felt like a different
        # plan. The app names the store it means via `X-Store-Id`; this ordered
        # fallback is only for callers that have not (and for single-store
        # vendors, which is everyone today).
        query = (
            select(Vendor)
            .where(reachable)
            .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        )
        result = await session.execute(query)
        return result.scalars().first()

async def get_all_vendors_by_clerk_id(session: AsyncSession, clerk_id: str):
    """Every store this clerk id can reach, owned or staffed, oldest first."""
    reachable = await _reachable_vendor_filter(session, clerk_id)
    query = (
        select(Vendor)
        .where(reachable)
        .order_by(Vendor.created_at.asc(), Vendor.id.asc())
    )
    result = await session.execute(query)
    return result.scalars().all()


async def register_vendor(session: AsyncSession, clerk_id: str, data: dict):
    """Create this caller's store, or update the one they already own.

    Resolved by **ownership alone**, never through `get_vendor_by_clerk_id`.
    That helper's filter is `owned OR staffed`, and the upsert below writes
    `business_name`, `phone_number` and `vendor_type` — so with it, a staff
    member calling this endpoint rewrote the *owner's* business: its name, its
    contact number, and the vendor type that decides both the commission rate
    and the service radius. Exactly what `PUT /profile` is owner-gated to
    prevent, reachable by the token of anyone handed the till.

    Ownership here also matches `POST /api/auth/create_vendor`, which is the
    endpoint the vendor app's onboarding actually calls and which has always
    resolved this way. Two registration paths disagreeing about who owns a store
    is the same shape as the two withdrawal paths disagreeing about what is
    spendable, and as there the permissive one was the one that wrote.
    """
    from routes.auth_routes import sanitize_phone_number
    if "phone_number" in data and data["phone_number"]:
         data["phone_number"] = sanitize_phone_number(data["phone_number"])

    owned = await session.execute(
        select(Vendor)
        .where(Vendor.clerk_id == clerk_id)
        .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        .limit(1)
    )
    existing = owned.scalars().first()
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


async def update_vendor_profile(session: AsyncSession, clerk_id: str, data: dict, vendor_id: UUID | None = None):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # `delivery_radius` is not here on purpose: the radius is a platform
    # setting, like the delivery fee, and for the same reason — see
    # `VendorProfileUpdateRequest`. A field absent from the request model but
    # present here would still be writable by anything calling this service
    # directly.
    updatable_fields = [
        "business_name", "owners_name", "phone_number", "profile_pic",
        "business_license", "location_address",
        "shift_start", "shift_end", "preferred_payment_method", "vendor_type",
        "is_online", "deposit_fee"
    ]

    # Validate deposit_fee range before applying. Compared as `Decimal`: the
    # field arrives as one and is written to a `Numeric` column, so the `float()`
    # that used to sit here was a round trip in the middle of a bounds check on
    # money — harmless at these magnitudes and exactly the residue that makes
    # the next person think a float is acceptable on this path.
    if "deposit_fee" in data and data["deposit_fee"] is not None:
        fee = Decimal(str(data["deposit_fee"]))
        if fee < 0 or fee > 5000:
            raise HTTPException(status_code=400, detail="Deposit fee must be between KSH 0 and KSH 5,000.")

    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(vendor, field, data[field])

    if "lat" in data and "lng" in data and data["lat"] is not None:
        # This was the only one of the three writers that set all four columns.
        # It goes through the shared function regardless, so "what a position is"
        # has one definition rather than one correct copy and two wrong ones.
        set_vendor_position(vendor, data["lat"], data["lng"])

    await session.commit()
    await session.refresh(vendor)
    return vendor


def _money_in(value, field: str) -> Decimal:
    """A money value off a request body, as `Decimal`, or a 400.

    `Decimal(str(...))` rather than `Decimal(value)`: a JSON number arrives as a
    Python float, and `Decimal(249.5)` is the exact binary value, not 249.50.
    Going through `str` takes the repr, which is the figure the vendor typed.
    """
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"'{field}' must be a number.")


async def create_product(session: AsyncSession, clerk_id: str, data: dict, vendor_id: UUID | None = None):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Discount validation: prevent negative pricing.
    #
    # `Decimal`, not `float`. `Products.price` and `.discount` are `Numeric(10, 2)`
    # and they are the base of every cart subtotal, every vendor commission and
    # every shelf label on the platform — the most-multiplied money on it. They
    # were coerced with `float()` here and then written straight to the columns,
    # which is the one thing the whole `Decimal` discipline exists to prevent.
    # The messages went out with a float's repr too ("KSH 60.0").
    price = _money_in(data["price"], "price")
    discount = _money_in(data.get("discount", 0), "discount")
    if discount < 0:
        raise HTTPException(status_code=400, detail="Discount cannot be negative.")
    if discount >= price:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Discount (KSH {money_str(discount)}) must be less than the "
                f"product price (KSH {money_str(price)})."
            ),
        )

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
        low_stock_threshold=data.get("low_stock_threshold", 5),
        is_available=data.get("is_available", True),
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, clerk_id: str, product_id: UUID, data: dict, vendor_id: UUID | None = None):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    product = await session.get(Product, product_id)
    if not product or product.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    # Discount validation: prevent negative pricing. Same rule as `create_product`.
    new_price = _money_in(data.get("price", product.price), "price")
    new_discount = _money_in(data.get("discount", product.discount), "discount")
    if new_discount < 0:
        raise HTTPException(status_code=400, detail="Discount cannot be negative.")
    if new_discount >= new_price:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Discount (KSH {money_str(new_discount)}) must be less than the "
                f"product price (KSH {money_str(new_price)})."
            ),
        )

    # The validated `Decimal`s are what gets written, not whatever shape the
    # request happened to carry — `setattr` used to put the raw value back on the
    # column while the float above was only ever used for the comparison.
    data = {**data}
    if "price" in data and data["price"] is not None:
        data["price"] = new_price
    if "discount" in data and data["discount"] is not None:
        data["discount"] = new_discount

    updatable_fields = [
        "name", "description", "image_url", "price", "discount",
        "capacity", "weight_kg", "minimum_order_qty", "unit", "stock",
        "low_stock_threshold", "is_available"
    ]
    for field in updatable_fields:
        if field in data and data[field] is not None:
            setattr(product, field, data[field])

    # A restock arms the warning again. The latch exists to stop one push per
    # unit sold below the line, not to silence the product forever.
    threshold = product.low_stock_threshold or 0
    if product.stock > threshold:
        product.low_stock_notified_at = None

    await session.commit()
    await session.refresh(product)
    return product


async def delete_product(session: AsyncSession, clerk_id: str, product_id: UUID, vendor_id: UUID | None = None):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    product = await session.get(Product, product_id)
    if not product or product.vendor_id != vendor.id or product.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    # Withdraw it, do not delete the row.
    #
    # `Order_Items.product_id` references this table with no `ondelete`, so a
    # hard delete of a product that has ever sold is a foreign-key violation the
    # vendor sees as a bare 500. Relaxing the constraint would be worse: the
    # bottle ledger reads `item.product.capacity` to work out what a rider owes,
    # and an order item with no product silently contributes no bottle debt.
    #
    # A withdrawn product disappears from the catalogue and from the vendor's own
    # list, but stays readable for the orders that reference it.
    from datetime import datetime, timezone

    sold_before = (
        await session.execute(
            select(OrderItem.id).where(OrderItem.product_id == product.id).limit(1)
        )
    ).scalars().first()

    product.deleted_at = datetime.now(timezone.utc)
    product.is_available = False
    await session.commit()

    return {
        "message": (
            "Product withdrawn. It is no longer on sale; past orders that include "
            "it are unaffected."
            if sold_before
            else "Product deleted successfully"
        ),
        "product_id": str(product.id),
    }


async def get_vendor_orders(
    session: AsyncSession, 
    clerk_id: str, 
    search_query: str = None, 
    status_filter: str = "All",
    skip: int = 0, 
    limit: int = 50,
    vendor_id: UUID | None = None,
):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
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
            joinedload(Order.deliverer),
            # `BaseOrder.vendor` is serialised on every row here and was never
            # loaded. It survived only because `get_active_store` puts this one
            # store in the session's identity map and every order on the page
            # belongs to it, so the attribute resolved without SQL — the same
            # accident that hid the missing `Order.deliverer` load on the rider
            # side. Nothing about that is guaranteed: a session that has not
            # already fetched the store raises `raise_on_sql` mid-serialisation,
            # which is a 500 on the screen a shop runs its day from.
            joinedload(Order.vendor)
        )
        .order_by(*stable(Order.created_at.desc(), key=Order.id))
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
    offset: int = 0,
    vendor_id: UUID | None = None,
):
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from services.product_service import live_product

    # A withdrawn product is gone from the vendor's own catalogue too. It is kept
    # only so the orders that reference it still resolve — `Product.deleted_at`.
    conditions = [Product.vendor_id == vendor.id, live_product()]
    
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
        .order_by(*stable(*order_by_clauses, key=Product.id))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    return result.scalars().all()


async def update_order_status(session: AsyncSession, clerk_id: str, order_id: UUID, new_status: str, vendor_id: UUID | None = None):
    from services.order_service import validate_status_transition

    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Locked for the rest of the transaction. Two staff members on two devices
    # is not a hypothetical — it is what the staff feature is *for* — and an
    # unlocked read-then-write let both accept the same order, run the cash-float
    # check against a stale balance, and restore stock twice on a double
    # rejection. `assign_order_rider` has always taken a lock; this did not.
    result = await session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    order = result.scalars().first()
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
    # `Decimal`, not `float`. This comparison decides whether a vendor may trade
    # at all, and binary floating point cannot represent 0.10 exactly — a balance
    # of exactly the required amount could compare as short. The platform rule is
    # that money is never a float; this was the one place that broke it.
    if new_status == "accepted" and order.payment_method == "cash":
        from services.settlement_service import committed_cash_float_for_vendor

        required_float = Decimal(str(order.platform_total or 0))
        balance = Decimal(str(vendor.wallet_balance or 0))
        # Balance alone is not what is spendable: earlier cash orders have
        # already claimed part of it, and `POST /api/wallet/withdraw` refuses on
        # the same figure. Accepting against the raw balance is how a vendor ends
        # up owing the platform on delivery.
        committed = await committed_cash_float_for_vendor(session, vendor.id)
        available = balance - committed
        if available < required_float:
            shortfall = required_float - available
            detail = (
                f"Your float can't cover the platform commission on this cash order. "
                f"Top up KSH {shortfall:,.2f} to accept it."
            )
            if committed > 0:
                detail += (
                    f" (KSH {committed:,.2f} of your KSH {balance:,.2f} balance is already "
                    f"committed to open cash orders.)"
                )
            raise HTTPException(status_code=402, detail=detail)

    apply_status_transition(order, new_status)

    # Restore stock, return the customer's wallet credit, put back any debt this
    # order was collecting, release the bottle deposit and record the lost
    # commission. This branch previously restored stock and flagged the refund
    # and nothing else — so `commission_lost` was null on every vendor rejection,
    # which is the most common kind, and any report summing it was wrong.
    if new_status in ("rejected", "cancelled"):
        from services.order_service import revert_order_side_effects

        await revert_order_side_effects(
            session, order, reason=f"{new_status}_by_vendor"
        )

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


async def get_vendor_dashboard(session: AsyncSession, clerk_id: str, vendor_id: UUID | None = None):
    from datetime import datetime, timedelta, timezone

    from services.order_service import NAIROBI_TZ_OFFSET_HOURS
    
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
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
    total_revenue = Decimal(str((await session.execute(total_revenue_q)).scalar() or 0))
    pending_orders = (await session.execute(pending_orders_q)).scalar() or 0
    product_count = (await session.execute(product_count_q)).scalar() or 0

    # This week's revenue by weekday, Monday first, for the dashboard chart.
    #
    # Bucketed in **East Africa Time**, not the server's. `datetime.now()` with
    # no timezone is UTC on Render, so "start of week" began at 03:00 Monday
    # Nairobi and every order placed between midnight and 3am was filed under
    # the previous day — the last bar of the chart for orders that happened on
    # the first. `Order.created_at` is `TIMESTAMP(timezone=True)`, so the
    # comparison was also aware-vs-naive and left Postgres to guess.
    nairobi = timezone(timedelta(hours=NAIROBI_TZ_OFFSET_HOURS))
    today = datetime.now(nairobi)
    start_of_week = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
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
    
    # Accumulated as `Decimal`. Seven running float totals over a week of orders
    # is the textbook case for binary error to show up in a figure a vendor
    # reconciles against their own takings.
    weekly_revenue_arr = [Decimal("0.00")] * 7
    for order_date, amount in weekly_orders:
        if order_date:
            # The weekday the order happened *in Nairobi*, for the same reason.
            day_index = order_date.astimezone(nairobi).weekday()  # 0 = Monday
            weekly_revenue_arr[day_index] += Decimal(str(amount or 0))

    # What needs restocking, so the vendor sees it before a customer does.
    low_stock_q = (
        select(Product.id, Product.name, Product.stock, Product.low_stock_threshold)
        .where(
            and_(
                Product.vendor_id == vendor.id,
                Product.low_stock_threshold > 0,
                Product.stock <= Product.low_stock_threshold,
            )
        )
        .order_by(Product.stock.asc(), Product.name.asc())
        .limit(20)
    )
    low_stock_rows = (await session.execute(low_stock_q)).all()

    return {
        "vendor_id": str(vendor.id),
        "business_name": vendor.business_name,
        "vendor_type": vendor.vendor_type,
        "is_online": vendor.is_online,
        "total_orders": total_orders,
        "total_revenue": money_str(total_revenue),
        "pending_orders": pending_orders,
        "product_count": product_count,
        "rating": vendor.rating or 0,
        # 0 is what an unrated store scores by policy, which reads on the
        # dashboard exactly like a store everybody rated badly.
        "rating_count": int(vendor.rating_count or 0),
        "weekly_revenue": [money_str(v) for v in weekly_revenue_arr],
        "low_stock_products": [
            {
                "id": str(pid),
                "name": name,
                "stock": stock,
                "low_stock_threshold": threshold,
            }
            for pid, name, stock, threshold in low_stock_rows
        ],
    }


async def cancel_order(session: AsyncSession, clerk_id: str, order_id: UUID, vendor_id: UUID | None = None):
    """Cancel an order before preparation"""
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
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

    apply_status_transition(order, "cancelled")

    from services.order_service import revert_order_side_effects

    await revert_order_side_effects(session, order, reason="cancelled_by_vendor")

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


async def assign_order_rider(session: AsyncSession, clerk_id: str, order_id: UUID, rider_id: str, vendor_id: UUID | None = None):
    from models.deliverer_model import Deliverer

    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
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
        # Assigning a rider to an order the vendor has not yet accepted implies
        # acceptance; one already further along keeps the status it has.
        if order.order_status == "pending":
            apply_status_transition(order, "accepted")

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
    vendor_id: UUID | None = None,
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
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
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


async def get_vendor_bottle_debtors(session: AsyncSession, clerk_id: str, vendor_id: UUID | None = None):
    """Every rider holding this vendor's empties, registered or not."""
    vendor = await get_vendor_by_clerk_id(session, clerk_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from services.bottle_ledger_service import get_vendor_outstanding

    return {"riders": await get_vendor_outstanding(session, vendor.id)}
