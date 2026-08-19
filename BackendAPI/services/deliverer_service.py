import logging
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
from uuid import UUID
from datetime import datetime, timedelta, timezone
from models.deliverer_model import Deliverer
from models.order_model import Order, OrderItem
from models.user_model import User
from models.vendor_model import Vendor
from models.review_model import Review
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from services.expo_push_service import send_push_message, dispatch_background
from services.notification_service import create_notification, push_allowed
from services.settlement_service import cash_float_required
import h3
from decimal import Decimal

from utils.money import money_str
from services.order_service import apply_status_transition
from utils.paging import stable


def _money(value) -> Decimal:
    """Money is Decimal. Balances used to be mutated with float arithmetic, which
    drifts over repeated settlements."""
    return Decimal(str(value or 0))



logger = logging.getLogger(__name__)


async def get_deliverer_by_clerk_id(session: AsyncSession, clerk_id: str):
    """Look up a deliverer by their Clerk ID. Returns None if not found."""
    result = await session.execute(
        select(Deliverer).where(Deliverer.clerk_id == clerk_id)
    )
    return result.scalar_one_or_none()


async def register_deliverer(session: AsyncSession, clerk_id: str, data: dict):
    from routes.auth_routes import sanitize_phone_number
    if "phone_number" in data and data["phone_number"]:
         data["phone_number"] = sanitize_phone_number(data["phone_number"])
         
    existing = await get_deliverer_by_clerk_id(session, clerk_id)
    if existing:
        if data.get("phone_number"):
            existing.phone_number = data["phone_number"]
        if data.get("ID_number"):
            existing.ID_number = data["ID_number"]
        if data.get("vehicle_type"):
            existing.vehicle_type = data["vehicle_type"]
        if data.get("plate_number"):
            existing.plate_number = data["plate_number"]
        if data.get("employment_model"):
            existing.employment_model = data["employment_model"]
        if data.get("employer_vendor_id"):
            existing.employer_vendor_id = data["employer_vendor_id"]
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    deliverer = Deliverer(
        clerk_id=clerk_id,
        name=data["name"],
        email=data["email"],
        phone_number=data.get("phone_number"),
        ID_number=data.get("ID_number", ""),
        vehicle_type=data.get("vehicle_type", "motorbike"),
        employment_model=data.get("employment_model", "gig_economy"),
        employer_vendor_id=data.get("employer_vendor_id"),
        plate_number=data.get("plate_number"),
        profile_pic=data.get("profile_pic"),
    )
    session.add(deliverer)
    await session.commit()
    await session.refresh(deliverer)
    return deliverer


async def update_deliverer_profile(session: AsyncSession, clerk_id: str, data: dict):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    updatable = ["name", "phone_number", "profile_pic", "vehicle_type", "plate_number",
                 "driver_license", "shift_start", "shift_end", "preferences", "payment_methods"]
    for field in updatable:
        if field in data and data[field] is not None:
            setattr(deliverer, field, data[field])

    # Zone change logic
    if "operation_lat" in data and "operation_lng" in data and data["operation_lat"] is not None and data["operation_lng"] is not None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        # Reset counter if it's a new month
        if deliverer.last_zone_change:
            if deliverer.last_zone_change.year < now.year or deliverer.last_zone_change.month < now.month:
                deliverer.zone_changes_this_month = 0
                
        if deliverer.zone_changes_this_month >= 2:
            raise HTTPException(status_code=403, detail="You have reached the maximum allowed zone changes (2) for this month.")
            
        deliverer.operation_lat = data["operation_lat"]
        deliverer.operation_lng = data["operation_lng"]
        deliverer.h3_index_res8 = str(h3.latlng_to_cell(data["operation_lat"], data["operation_lng"], 8))
        deliverer.zone_changes_this_month += 1
        deliverer.last_zone_change = now

    await session.commit()
    await session.refresh(deliverer)
    return deliverer


async def update_deliverer_location(session: AsyncSession, clerk_id: str, lat: float, lng: float):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Guard: Reject Null Island (0,0) and clearly invalid coordinates
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0.0 and lng == 0.0):
        raise HTTPException(status_code=400, detail="Invalid coordinates. Null Island (0,0) and out-of-range values are rejected.")

    deliverer.current_lat = lat
    deliverer.current_lng = lng
    deliverer.location = from_shape(Point(lng, lat), srid=4326)
    deliverer.h3_index_res8 = str(h3.latlng_to_cell(lat, lng, 8))
    await session.commit()
    return {"message": "Location updated"}


async def update_deliverer_location_by_id(session: AsyncSession, deliverer_id: str, lat: float, lng: float):
    """Update rider location by UUID (used by WebSocket handler where clerk_id isn't available)."""
    from uuid import UUID as PyUUID
    try:
        uid = PyUUID(deliverer_id)
    except ValueError:
        return {"message": "Invalid deliverer ID"}
    
    deliverer = await session.get(Deliverer, uid)
    if not deliverer:
        return {"message": "Rider not found"}

    # Guard: Reject Null Island (0,0) and clearly invalid coordinates
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0.0 and lng == 0.0):
        return {"message": "Invalid coordinates rejected"}

    deliverer.current_lat = lat
    deliverer.current_lng = lng
    deliverer.location = from_shape(Point(lng, lat), srid=4326)
    deliverer.h3_index_res8 = str(h3.latlng_to_cell(lat, lng, 8))
    await session.commit()
    return {"message": "Location updated via WebSocket"}


async def toggle_availability(session: AsyncSession, clerk_id: str, is_available: bool):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    deliverer.is_available = is_available
    await session.commit()
    return {"message": f"Availability set to {is_available}"}


async def get_deliverer_orders(
    session: AsyncSession,
    clerk_id: str,
    skip: int = 0,
    limit: int = 50,
    status: str = None,
    search_query: str = None,
):
    """One page of this rider's orders, newest first.

    `status` accepts a comma-separated group as well as a single value. The
    rider's screen has two tabs — the deliveries in progress and the ones that
    are finished — and each spans several statuses, so a single-value filter left
    the app fetching everything and splitting the tabs from whatever one page
    happened to contain. A rider whose last 50 orders were all completed saw an
    empty "in progress" tab while carrying water.

    `search_query` matches the order reference, the same way the vendor's list
    does. It has to be here rather than in the app for the same reason the tabs
    do: a filter applied to the page in hand searches the newest 25 deliveries
    and reports nothing found for the one a rider is being asked about.
    """
    from sqlalchemy import String, cast

    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    query = (
        select(Order)
        .where(Order.deliverer_id == deliverer.id)
    )

    if status:
        wanted = [part.strip().lower() for part in status.split(",") if part.strip()]
        if wanted:
            query = query.where(Order.order_status.in_(wanted))

    if search_query and search_query.strip():
        query = query.where(cast(Order.id, String).ilike(f"%{search_query.strip()}%"))

    query = (
        query.options(
            joinedload(Order.order_item).joinedload(OrderItem.product),
            joinedload(Order.vendor),
            joinedload(Order.user),
            # `OrderWithDetails` inherits `deliverer` from `BaseOrder`, so Pydantic
            # reads this attribute on every row it serialises.
            #
            # It worked without the load, by luck: `get_deliverer_by_clerk_id` above
            # has already put this rider in the session's identity map, and a
            # many-to-one lazy load checks there before emitting SQL. Every order in
            # this result belongs to that same rider, so every lookup hit. Change
            # the order of those two calls, resolve the rider on a different
            # session, or let one order here belong to somebody else, and the same
            # line becomes a query per row — under asyncio, an exception per row.
            joinedload(Order.deliverer),
        )
        .order_by(*stable(Order.created_at.desc(), key=Order.id))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_trip_radar_orders(session: AsyncSession, clerk_id: str):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")
    if deliverer.current_lat is None or deliverer.current_lng is None:
        raise HTTPException(status_code=400, detail="Enable location sharing to see nearby orders.")

    from geopy.distance import geodesic

    query = (
        select(Order)
        .where(Order.order_status == "unassigned")
        .options(
            joinedload(Order.order_item).joinedload(OrderItem.product),
            joinedload(Order.vendor),
            joinedload(Order.user),
            # Serialised by `OrderWithDetails`, same as above. An `unassigned`
            # order normally has a null `deliverer_id`, and a many-to-one with a
            # null foreign key resolves to `None` without touching the database —
            # which is the only reason this was safe. It stops being safe the
            # moment one row in this list carries a rider, and a re-offered order
            # is exactly that: unassigned again, with the previous rider still on
            # the row until the reassignment clears it.
            joinedload(Order.deliverer),
        )
        .order_by(Order.created_at.desc())
        .limit(50)
    )
    result = await session.execute(query)
    orders = result.unique().scalars().all()

    rider_point = (deliverer.current_lat, deliverer.current_lng)
    enriched = []
    for order in orders:
        if order.vendor and order.vendor.lat is not None and order.vendor.lng is not None:
            distance_km = round(geodesic(rider_point, (order.vendor.lat, order.vendor.lng)).km, 2)
        else:
            distance_km = None
        order.distance_km = distance_km
        enriched.append(order)

    enriched.sort(key=lambda o: (o.distance_km if o.distance_km is not None else float("inf")))
    return enriched[:20]


async def update_delivery_status(session: AsyncSession, clerk_id: str, order_id: UUID, new_status: str, proof_url: str | None = None, empties_received: int | None = None):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Your rider account could not be found. Please ensure your profile is fully set up.")

    result = await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
    if not order or order.deliverer_id != deliverer.id:
        raise HTTPException(status_code=404, detail="This order is no longer assigned to you. It may have been reassigned or cancelled.")

    valid_statuses = ["picked_up", "delivered"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    # Idempotency: if this transition was already applied, return success without re-running side effects.
    if order.order_status == new_status:
        return {"message": f"Order status already '{new_status}'", "already_applied": True}
    if new_status == "picked_up" and order.order_status not in ("pending", "accepted", "preparing", "ready"):
        raise HTTPException(status_code=409, detail=f"Cannot mark picked up from status '{order.order_status}'.")
    if new_status == "delivered" and order.order_status not in ("pending", "accepted", "preparing", "ready", "picked_up"):
        raise HTTPException(status_code=409, detail=f"Order is already in a terminal state ('{order.order_status}') and cannot be marked delivered again.")

    apply_status_transition(order, new_status)
    if proof_url:
        from utils.image_utils import validate_proof_url
        if not validate_proof_url(proof_url):
            raise HTTPException(status_code=400, detail="Invalid proof photo URL. Must be a valid Cloudinary image (HTTPS, .webp/.jpg/.png).")
        order.proof_url = proof_url
        
    customer = await session.get(User, order.customer_id)
    vendor = await session.get(Vendor, order.vendor_id)
        
    # --- Delivery Completion Logic ---
    if new_status == "delivered":
        # A cash delivery needs a photo, whatever the bottle count says.
        #
        # The existing guardrail below demands one only on a bottle *shortfall*.
        # On a cash order there is no M-Pesa receipt to point at, so the photo is
        # the only thing that makes "he never delivered it" a decidable question
        # — and it is asked before any money moves, because settlement is what
        # this transition triggers.
        from services import cod_policy

        if await cod_policy.photo_required(session, order) and not (proof_url or order.proof_url):
            raise HTTPException(
                status_code=400,
                detail=(
                    "A delivery photo is required on cash orders. "
                    "Take one at the door and complete the delivery again."
                ),
            )

        deliverer.is_available = True # F-030: Free the rider for the next order

        # Acquisition is a *delivery*, so this is the moment it becomes true.
        #
        # In this transaction, before the commit: a rollback must not leave a
        # customer recorded as acquired by an order that never completed. The call
        # never raises — a growth figure is not worth failing a delivery over, and
        # `customer_cohort_service.reconcile` repairs anything lost here.
        from services import customer_cohort_service

        await customer_cohort_service.record_acquisition(session, order)

        # --- Wallet settlement ---
        # Every movement below goes through `apply_wallet_delta`, which mutates the
        # balance and writes the matching WalletTransaction in one step. These five
        # lines used to assign to `wallet_balance` directly with float arithmetic,
        # so a rider's own Transactions screen could not explain where their money
        # went, and repeated float rounding drifted the balance.
        from services.wallet_service import apply_wallet_delta
        from models.wallet_transaction_model import TransactionType
        from services import platform_config_service as config

        short_id = str(order.id)[:8].upper()
        is_wholesale = bool(vendor and vendor.vendor_type and vendor.vendor_type.value == "wholesale_b2b")

        if order.payment_method == "cash":
            order.payment_status = "paid"
            if vendor:
                if is_wholesale:
                    # The vendor's own in-house rider collected the cash, so the
                    # vendor holds it; only the platform's cut comes off their wallet.
                    await apply_wallet_delta(
                        session,
                        owner=vendor,
                        clerk_id=vendor.clerk_id,
                        user_type="vendor",
                        amount=-_money(order.platform_total),
                        transaction_type=TransactionType.commission_deduction,
                        description=f"Platform commission on cash order {short_id}",
                        reference_id=str(order.id),
                    )
                else:
                    # The gig rider collected the customer's cash, so their float
                    # settles the vendor's cut and the platform's cut.
                    await apply_wallet_delta(
                        session,
                        owner=deliverer,
                        clerk_id=deliverer.clerk_id,
                        user_type="rider",
                        amount=-cash_float_required(order),
                        transaction_type=TransactionType.order_payment,
                        description=f"Cash order {short_id} settled from float",
                        reference_id=str(order.id),
                    )
                    await apply_wallet_delta(
                        session,
                        owner=vendor,
                        clerk_id=vendor.clerk_id,
                        user_type="vendor",
                        amount=_money(order.vendor_net),
                        transaction_type=TransactionType.order_payment,
                        description=f"Payout for cash order {short_id}",
                        reference_id=str(order.id),
                    )
        elif order.payment_method == "mpesa" and order.payment_status == "paid":
            if vendor:
                await apply_wallet_delta(
                    session,
                    owner=vendor,
                    clerk_id=vendor.clerk_id,
                    user_type="vendor",
                    amount=_money(order.vendor_net),
                    transaction_type=TransactionType.order_payment,
                    description=f"Payout for order {short_id}",
                    reference_id=str(order.id),
                )
            # Riders earn a delivery commission only on retail; on wholesale the
            # in-house rider is the vendor's own employee.
            if not is_wholesale:
                await apply_wallet_delta(
                    session,
                    owner=deliverer,
                    clerk_id=deliverer.clerk_id,
                    user_type="rider",
                    amount=_money(order.rider_net),
                    transaction_type=TransactionType.order_payment,
                    description=f"Delivery earnings for order {short_id}",
                    reference_id=str(order.id),
                )
        else:
            # Every other combination pays nobody. That is correct for an order
            # whose M-Pesa payment never settled — but it used to happen in
            # silence, so the vendor and the rider simply never saw the money and
            # nothing anywhere recorded that a delivered order had gone
            # unsettled. Loud, and reconcilable from the logs.
            logger.error(
                "Order %s delivered but not settled: payment_method=%s payment_status=%s. "
                "vendor_net=%s rider_net=%s platform_total=%s remain unpaid.",
                order.id, order.payment_method, order.payment_status,
                order.vendor_net, order.rider_net, order.platform_total,
            )

        # --- Bottle Inventory Debt Tracking (quick_swap) ---
        if order.delivery_type == "quick_swap":
            from services.bottle_ledger_service import (
                accrue_delivery_empties,
                quantities_from_order_items,
            )

            items = (await session.execute(
                select(OrderItem).options(joinedload(OrderItem.product)).where(OrderItem.order_id == order.id)
            )).scalars().all()

            total_qty = sum(int(item.quantity or 0) for item in items)

            # Guardrail first: a deficit without a photo must not reach the ledger,
            # because the accrual is what makes the rider liable for the bottles.
            received = empties_received or 0
            if received < total_qty and not proof_url:
                raise HTTPException(status_code=400, detail="Proof of delivery photo is mandatory when reporting missing empty bottles.")

            # The rider is now holding the vendor's empties. This writes an audit
            # row *and* moves the registry counter, and does so whether or not a
            # registry row exists — radar dispatch deliberately offers orders to
            # riders who have never registered with the vendor, and the previous
            # implementation dropped their debt on the floor.
            await accrue_delivery_empties(
                session,
                rider_id=deliverer.id,
                vendor_id=order.vendor_id,
                order_id=order.id,
                quantities_by_capacity=quantities_from_order_items(items),
                actor_clerk_id=clerk_id,
            )
        
        # Update customer lifecycle tracking
        if customer:
            # Increment bottle refill count for lifecycle tracking
            if hasattr(customer, 'bottle_refill_count'):
                customer.bottle_refill_count = (customer.bottle_refill_count or 0) + 1
            customer.last_order_date = func.now()

            # --- Loyalty cashback: withdrawn, default 0 ---
            #
            # Kept as a switched-off setting rather than deleted, because the
            # mechanism is sound and the *rate* was the problem: KSH 10 on every
            # delivery against a platform cut of about KSH 37 returned a quarter
            # of the platform's revenue, unconditionally, to customers who were
            # buying water anyway. Paying on every order buys nothing. If it
            # comes back it should sit at a retention cliff — a fourth order
            # inside thirty days — not on each delivery.
            #
            # Moves through `apply_wallet_delta` when non-zero, like every other
            # balance movement. It was a bare `customer.wallet_balance += 10.0`:
            # a float added to a `Numeric` column with no `WalletTransaction`
            # behind it, so summing the customer's ledger no longer reproduced
            # their balance.
            await config.ensure_fresh(session)
            cashback = config.get_decimal("loyalty_cashback_per_delivery")
            if cashback > 0 and customer.clerk_id:
                await apply_wallet_delta(
                    session,
                    owner=customer,
                    clerk_id=customer.clerk_id,
                    user_type="customer",
                    amount=cashback,
                    transaction_type=TransactionType.refund,
                    description=f"Loyalty cashback for order {short_id}",
                    reference_id=str(order.id),
                )
    await session.commit()

    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id) if order.deliverer_id else "",
            payload={"action": "ORDER_STATUS_UPDATE", "order_id": str(order.id), "status": new_status}
        )
    except Exception as e:
        logger.error(f"WS Broadcast fail: {e}")

    if customer:
        title = "Delivery Update"
        body = f"Your order is now {new_status}!"
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=customer.id,
            user_type="customer",
            title=title,
            message=body,
            message_type="delivery_update",
            action_url=action_url,
            related_order_id=order.id
        )
        if customer.push_token and push_allowed(customer, "delivery_update"):
            dispatch_background(send_push_message(
                to=customer.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    # Notify Vendor
    if vendor:
        title = "Order Delivery Update 📦"
        body = f"Order #{str(order.id)[-6:]} has been {new_status} by the rider."
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=vendor.id,
            user_type="vendor",
            title=title,
            message=body,
            message_type="delivery_update",
            action_url=action_url,
            related_order_id=order.id
        )
        if vendor.push_token:
            dispatch_background(send_push_message(
                to=vendor.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    return {"message": f"Order status updated to '{new_status}'"}


async def get_deliverer_earnings(session: AsyncSession, clerk_id: str):
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    # The same trailing window the Platinum job evaluates over. Counting the
    # rider's progress over a different period from the one that decides their
    # tier is how a rider reaches the target on screen and is demoted anyway.
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(
        days=config.get_int("platinum_window_days")
    )

    from models.vendor_model import Vendor, VendorType
    paid_rider_filter = and_(
        Order.deliverer_id == deliverer.id,
        Order.order_status == "delivered",
        or_(Vendor.vendor_type.is_(None), Vendor.vendor_type != VendorType.wholesale_b2b),
    )

    total_deliveries_q = select(func.count(Order.id)).where(
        and_(Order.deliverer_id == deliverer.id, Order.order_status == "delivered")
    )
    
    last_7_days_deliveries_q = select(func.count(Order.id)).where(
        and_(
            Order.deliverer_id == deliverer.id, 
            Order.order_status == "delivered",
            Order.updated_at >= seven_days_ago
        )
    )

    total_earnings_q = (
        select(func.sum(func.coalesce(Order.rider_net, Order.delivery_fee)))
        .join(Vendor, Vendor.id == Order.vendor_id)
        .where(paid_rider_filter)
    )

    total_surcharges_q = select(
        func.sum(Order.payload_surcharge).label("total_payload_bonus"),
        func.sum(Order.staircase_surcharge).label("total_staircase_bonus")
    ).where(
        and_(Order.deliverer_id == deliverer.id, Order.order_status == "delivered")
    )

    total_deliveries = (await session.execute(total_deliveries_q)).scalar() or 0
    deliveries_last_7_days = (await session.execute(last_7_days_deliveries_q)).scalar() or 0
    # `Decimal` all the way to `money_str`. These three are what a rider has
    # earned, and they were `float()`-cast off the `SUM()` and sent as JSON
    # numbers — the defect `money_str` exists to prevent, on the figure a rider
    # checks their own takings against. `MONEY_FIELDS` did not list them, so
    # `test_money_serialisation` walked straight past all three.
    total_earnings = Decimal(str((await session.execute(total_earnings_q)).scalar() or 0))

    surcharges_result = (await session.execute(total_surcharges_q)).first()
    total_payload_bonus = Decimal(str(getattr(surcharges_result, "total_payload_bonus", None) or 0))
    total_staircase_bonus = Decimal(str(getattr(surcharges_result, "total_staircase_bonus", None) or 0))

    # What Platinum actually takes, from the same two rows the nightly job reads.
    # The app stated "complete 20 more deliveries" from a literal of its own, so
    # a business that raised the bar would have told every rider the old number
    # while demoting them against the new one. (`config` is already imported and
    # refreshed at the top of this function.)
    platinum_target = config.get_int("platinum_min_deliveries")
    platinum_window_days = config.get_int("platinum_window_days")

    return {
        "rider_id": str(deliverer.id),
        "name": deliverer.name,
        "total_deliveries": total_deliveries,
        # Kept under its original name because the app reads it; the window it
        # is counted over is `platinum_window_days`, which defaults to 7.
        "deliveries_last_7_days": deliveries_last_7_days,
        "deliveries_in_window": deliveries_last_7_days,
        "platinum_target": platinum_target,
        "platinum_window_days": platinum_window_days,
        "total_earnings": money_str(total_earnings),
        "is_available": deliverer.is_available,
        "rating": deliverer.rating or 5.0,
        "acceptance_rate": deliverer.acceptance_rate or 100.0,
        "is_platinum": deliverer.is_platinum,
        "total_staircase_bonus": money_str(total_staircase_bonus),
        "total_payload_bonus": money_str(total_payload_bonus),
    }


async def reject_delivery(session: AsyncSession, clerk_id: str, order_id: UUID):
    """
    Rider rejects an assigned delivery.
    - Validates the rider owns the order and status allows rejection.
    - Unassigns the rider and transitions the order to 'unassigned'.
    - Immediately triggers the reassignment engine to find the next closest rider.
    - Notifies vendor and customer about the reassignment.
    """
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Your rider account could not be found. Please ensure your profile is fully set up.")

    order = await session.get(Order, order_id)
    if not order or order.deliverer_id != deliverer.id:
        raise HTTPException(status_code=404, detail="This order is no longer assigned to you. It may have been reassigned or cancelled.")

    # Only allow rejection for orders that haven't been picked up yet
    rejectable_statuses = ["pending", "accepted", "preparing", "ready"]
    if order.order_status not in rejectable_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject order with status '{order.order_status}'. "
                   f"Only orders in {rejectable_statuses} can be rejected."
        )

    # Unassign rider and transition to unassigned
    previous_rider_id = order.deliverer_id
    order.deliverer_id = None
    apply_status_transition(order, "unassigned")
    
    # F-030: Free the rider since they rejected it
    deliverer.is_available = True

    await session.commit()

    # Broadcast the status change via WebSocket
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(previous_rider_id) if previous_rider_id else "",
            payload={
                "action": "ORDER_STATUS_UPDATE",
                "order_id": str(order.id),
                "status": "unassigned",
                "reason": "rider_rejected",
            }
        )
    except Exception as e:
        logger.error(f"WS Broadcast fail in reject_delivery: {e}")

    # Notify vendor about rider rejection
    from models.vendor_model import Vendor
    vendor = await session.get(Vendor, order.vendor_id)
    if vendor:
        title = "Rider Rejected Delivery 🔄"
        body = "The assigned rider rejected the delivery. We're finding a new rider."
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=vendor.id,
            user_type="vendor",
            title=title,
            message=body,
            message_type="delivery_update",
            action_url=action_url,
            related_order_id=order.id
        )
        if vendor.push_token:
            dispatch_background(send_push_message(
                to=vendor.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    # Notify customer about reassignment
    customer = await session.get(User, order.customer_id)
    if customer:
        title = "Finding a New Rider 🔄"
        body = "Your delivery is being reassigned to another rider. Hang tight!"
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=customer.id,
            user_type="customer",
            title=title,
            message=body,
            message_type="delivery_update",
            action_url=action_url,
            related_order_id=order.id
        )
        if customer.push_token and push_allowed(customer, "delivery_update"):
            dispatch_background(send_push_message(
                to=customer.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    # Immediately attempt reassignment to next closest rider
    reassigned = False
    try:
        from services.order_service import reassign_unassigned_orders
        result = await reassign_unassigned_orders(session=session)
        reassigned = result.get("reassigned", 0) > 0
    except Exception as e:
        logger.error(f"Auto-reassignment after rejection failed: {e}")

    return {
        "message": "Delivery rejected successfully",
        "order_id": str(order.id),
        "reassigned": reassigned,
    }


async def accept_delivery_radar(session: AsyncSession, clerk_id: str, order_id: UUID):
    """
    Rider 'swipes to accept' an order broadcasted via Trip Radar.
    Uses SELECT FOR UPDATE NOWAIT to prevent multiple riders from claiming the same order.
    """
    from sqlalchemy.exc import DBAPIError
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    if not deliverer.is_available:
        raise HTTPException(status_code=400, detail="You must be online and available to accept orders.")

    # Concurrency safe lock with joinedload for anti-fraud checks
    from core.redis_client import redis_lock
    lock_key = f"order_accept_lock:{order_id}"
    
    async with redis_lock(lock_key, timeout_seconds=10) as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Another rider is currently trying to accept this order. Please try again in a moment.")

        query = select(Order).options(joinedload(Order.user), joinedload(Order.vendor)).where(Order.id == order_id).with_for_update(nowait=True)
        try:
            result = await session.execute(query)
            order = result.scalar_one_or_none()
        except DBAPIError:
            # PostgreSQL raises error if unable to get the lock due to nowait=True
            await session.rollback()
            raise HTTPException(status_code=409, detail="This order has already been claimed by another rider.")

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # --- Cash Order: trust, then float ---
        # Two different questions, and the float check only ever asked the
        # second. "Can this rider cover it" says nothing about whether they
        # should be carrying somebody else's money at all — a four-day-old
        # account with a large balance passed, every time, for any number of
        # orders at once.
        if order.payment_method == "cash":
            from services import cod_policy
            from services.settlement_service import committed_cash_float

            # Raises 403 on trust and 409 on a limit. Deliberately before the
            # float check: "you need 25 deliveries" is a truer answer than
            # "insufficient balance" to a rider who could never take this order.
            await cod_policy.assert_rider_may_accept_cash(
                session, rider=deliverer, order=order
            )

            # Lock the rider's row: the check below is read-then-decide, and the
            # deliverer row was previously loaded with a plain SELECT. Two cash
            # orders accepted at once both read the same balance and both passed,
            # committing the rider to more float than they hold.
            locked_rider = (
                await session.execute(
                    select(Deliverer).where(Deliverer.id == deliverer.id).with_for_update()
                )
            ).scalars().first()
            if locked_rider is not None:
                deliverer = locked_rider

            required_float = cash_float_required(order)
            # Float already promised to other cash orders this rider is carrying is
            # not spendable here either — otherwise one balance backs every order.
            already_committed = await committed_cash_float(session, deliverer.id)
            spare = _money(deliverer.wallet_balance) - already_committed

            if spare < required_float:
                await session.rollback()
                detail = (
                    f"Insufficient Wallet Balance. You need at least KSH {required_float:,.2f} "
                    f"to accept this Cash order. You have KSH {spare:,.2f} available"
                )
                if already_committed > 0:
                    detail += (
                        f" (KSH {already_committed:,.2f} of your KSH "
                        f"{_money(deliverer.wallet_balance):,.2f} is held for cash orders "
                        "you are already carrying)"
                    )
                raise HTTPException(status_code=402, detail=detail + ".")

        # Removed duplicate registry check in favor of the auto-register block below

        # Anti-Fraud: Self-Dealing Prevention
        if order.user and order.user.clerk_id == clerk_id:
            await session.rollback()
            raise HTTPException(status_code=403, detail="Self-dealing prohibited. You cannot deliver your own personal order.")
        from services.vendor_staff_service import is_store_member

        if await is_store_member(session, clerk_id, order.vendor):
            await session.rollback()
            raise HTTPException(status_code=403, detail="Self-dealing prohibited. You cannot deliver for a store you manage.")

        if order.order_status != "unassigned" or order.deliverer_id is not None:
            await session.rollback()
            raise HTTPException(status_code=409, detail="This order has already been claimed by another rider.")

        # SEC-03 FIX: Vendor Fleet Integrity Check
        # Verify rider is approved for this vendor, or auto-register for Tier 2 Trip Radar claims
        from models.vendor_rider_model import VendorRiderRegistry
        registry_q = select(VendorRiderRegistry).where(
            and_(
                VendorRiderRegistry.rider_id == deliverer.id,
                VendorRiderRegistry.vendor_id == order.vendor_id,
                VendorRiderRegistry.status == "approved"
            )
        )
        registry_result = await session.execute(registry_q)
        if not registry_result.scalar_one_or_none():
            # Auto-register gig rider for this vendor (Trip Radar Tier 2 implicit approval)
            new_registration = VendorRiderRegistry(
                rider_id=deliverer.id,
                vendor_id=order.vendor_id,
                status="approved"
            )
            session.add(new_registration)
            logger.info(f"Trip Radar: Auto-registered rider {deliverer.id} for vendor {order.vendor_id}")

        # Success: Claim the order
        order.deliverer_id = deliverer.id
        apply_status_transition(order, "pending")
        deliverer.is_available = False # F-030 Single-Client Constraint Enforcement

        # --- Gamification Ledger Recalculation ---
        # The order was created assuming 10% commission. If this rider is Platinum, reduce to 7%.
        # FIN-01 FIX: Use Decimal for currency precision
        if deliverer.is_platinum and order.rider_commission and order.rider_commission > 0:
            from decimal import ROUND_HALF_UP
            from services import platform_config_service as config

            await config.ensure_fresh(session)
            delivery_fee_d = Decimal(str(order.delivery_fee))
            new_commission = (
                delivery_fee_d * config.get_decimal("gig_platinum_rider_commission_rate")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            old_commission = Decimal(str(order.rider_commission))
            commission_diff = old_commission - new_commission
            if commission_diff > 0:
                # Written as `Decimal`. Everything above is carefully `Decimal`
                # — the comment two lines up even says so — and then all three
                # ledger columns were cast back to `float` at the moment of the
                # write. `Numeric(10, 2)` rounds whatever it is handed, so each
                # of the three rounded independently and the identity the whole
                # revenue split is built on (`vendor_net + rider_net +
                # platform_total == gross`) could come apart by a cent on every
                # order a Platinum rider accepts.
                order.rider_commission = new_commission
                order.rider_net = Decimal(str(order.rider_net)) + commission_diff
                order.platform_total = Decimal(str(order.platform_total)) - commission_diff

        await session.commit()

    # Broadcast Assignment to the group so other riders see it disappear
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(deliverer.id),
            payload={
                "action": "ORDER_ASSIGNED",
                "order_id": str(order.id),
                "status": "pending",
                "deliverer_id": str(deliverer.id)
            }
        )
    except Exception as e:
        logger.error(f"WS broadcast fail in accept_delivery_radar: {e}")

    # Notify Customer
    customer = await session.get(User, order.customer_id)
    if customer:
        title = "Rider Assigned 🛵"
        body = f"{deliverer.full_name} is on the way to pick up your order!"
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
            
    # Notify Vendor
    vendor = await session.get(Vendor, order.vendor_id)
    if vendor:
        title = "Rider Claimed Order 🛵"
        body = f"{deliverer.full_name} has claimed Order #{str(order.id)[-6:]}."
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=vendor.id,
            user_type="vendor",
            title=title,
            message=body,
            message_type="order_assigned",
            action_url=action_url,
            related_order_id=order.id
        )
        if vendor.push_token:
            dispatch_background(send_push_message(
                to=vendor.push_token,
                title=title,
                body=body,
                data={"url": action_url}
            ))

    return {
        "message": "Delivery claimed successfully!",
        "order_id": str(order.id),
        "delivery_fee": order.delivery_fee
    }


async def report_address_mismatch(session: AsyncSession, clerk_id: str, order_id: UUID, actual_floor_level: int | None = None):
    """
    Rider reports the customer lied about their floor level.
    Pauses delivery to 'mismatch_pending'. Customer must accept a surcharge or come downstairs.
    """
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    order = await session.get(Order, order_id)
    if not order or order.deliverer_id != deliverer.id:
        raise HTTPException(status_code=404, detail="Order not assigned to you")

    if order.order_status == "delivered":
        raise HTTPException(status_code=400, detail="Order is already delivered")

    apply_status_transition(order, "mismatch_pending")
    
    # Store the actual floor level reported by the rider for surcharge recalculation
    if actual_floor_level is not None and hasattr(order, 'actual_floor_level'):
        order.actual_floor_level = actual_floor_level
    
    await session.commit()

    # Trigger a WebSocket broadcast or FCM push notification to the customer here.
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id),
            payload={
                "action": "ORDER_STATUS_UPDATE", 
                "order_id": str(order.id), 
                "status": "mismatch_pending",
                "actual_floor_level": actual_floor_level,
                "message": "Rider reported an address mismatch. Please come to the ground floor to pick up your bottles."
            }
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"WebSocket broadcast failed: {e}")

    try:
        from services.notification_service import create_notification
        await create_notification(
            session=session,
            user_id=order.customer_id,
            user_type="customer",
            title="Delivery Paused ⚠️",
            message="Rider arrived but reported an address mismatch. Please come to the ground floor to pick up your bottles.",
            message_type="delivery_update",
            related_order_id=order.id,
            data={"order_id": str(order.id), "status": "mismatch_pending", "actual_floor_level": actual_floor_level}
        )
        
        customer = await session.get(User, order.customer_id)
        if customer and customer.push_token and push_allowed(customer, "delivery_update"):
            dispatch_background(send_push_message(
                to=customer.push_token,
                title="Delivery Paused ⚠️",
                body="Rider arrived but reported an address mismatch. Please come to the ground floor to pick up your bottles.",
                data={"url": f"/(screens)/OrderDetail/{order.id}"}
            ))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Notification creation failed: {e}")

    return {"message": "Mismatch reported. Waiting for customer response.", "status": order.order_status}


async def report_bottle_rejection(session: AsyncSession, clerk_id: str, order_id: UUID, reason_text: str, photo_urls: list[str]):
    from models.bottle_rejection_model import BottleRejectionTicket, RejectionStatus
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    order = await session.get(Order, order_id)
    if not order or order.deliverer_id != deliverer.id:
        raise HTTPException(status_code=404, detail="Order not assigned to you")

    if order.order_status == "delivered":
        raise HTTPException(status_code=400, detail="Order is already delivered")

    rejection = BottleRejectionTicket(
        order_id=order.id,
        rider_id=deliverer.id,
        status=RejectionStatus.PENDING_REVIEW,
        reason_text=reason_text,
        photo_urls=photo_urls
    )
    session.add(rejection)
    
    apply_status_transition(order, "pending_review")
    await session.commit()
    await session.refresh(rejection)

    # The ARQ cron sweep (jobs/auto_resolve_bottle_rejections.py) now owns timeout resolution reliably, 
    # independent of this request's lifetime on Vercel Serverless.
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(order.deliverer_id),
            payload={
                "action": "ORDER_STATUS_UPDATE", 
                "order_id": str(order.id), 
                "status": "pending_review",
                "message": "The rider has flagged your empty bottle for review. Please wait 2-5 minutes while admin reviews the photos."
            }
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"WebSocket broadcast failed: {e}")

    return {"message": "Rejection flagged for review. Please wait 2-5 minutes.", "status": order.order_status}

async def get_deliverer_reviews(session: AsyncSession, clerk_id: str, limit: int = 50, offset: int = 0):
    """A rider's rating summary plus a page of their reviews.

    The totals and the star distribution come from one grouped query rather than
    from loading every review the rider has ever received and counting them in
    Python — which is what this did, so a rider with thousands of deliveries pulled
    all of them into memory every time they opened the screen.
    """
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    from services.review_service import get_target_rating_summary

    summary = await get_target_rating_summary(session, "rider", deliverer.id)

    result = await session.execute(
        select(Review)
        .where(
            and_(
                Review.target_type == 'rider',
                Review.target_id == deliverer.id,
                Review.hidden_at.is_(None),
            )
        )
        .order_by(*stable(Review.created_at.desc(), key=Review.id))
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    )

    return {
        "total_reviews": summary["total_reviews"],
        "average_rating": summary["average_rating"],
        "distribution": summary["distribution"],
        "reviews": [
            {
                "id": str(r.id),
                "order_id": str(r.order_id),
                "rating": r.rating,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.scalars().all()
        ],
    }



async def cancel_delivery(session: AsyncSession, clerk_id: str, order_id: str, reason: str, details: str = None):
    """
    Handles a Rider cancelling/rejecting an order.
    Depending on the state and reason, this will either:
    1. Unassign the rider and dispatch to a new rider.
    2. Cancel the order entirely.
    """
    from services.deliverer_service import get_deliverer_by_clerk_id
    from services.notification_service import create_notification
    from services.expo_push_service import send_push_message, dispatch_background
    
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider account not found.")

    order = await session.get(Order, order_id)
    if not order or order.deliverer_id != deliverer.id:
        raise HTTPException(status_code=404, detail="This order is not assigned to you.")

    # Matrix of reasons. These three lists are the two menus the rider app
    # actually offers — and only the first was ever consulted, so any string at
    # all was accepted as a reason. A post-pickup drop could be recorded as
    # `out_of_stock`, which is not a thing that can happen to an order already
    # on the bike and counts against the store in every vendor-fault figure
    # that reads `cancellation_reason`.
    vendor_fault_reasons = ["vendor_closed", "out_of_stock"]
    rider_fault_reasons = ["vehicle_issue", "accident", "other"]
    post_pickup_reasons = [
        "vehicle_issue", "accident", "customer_unreachable", "customer_refused", "other",
    ]

    previous_rider_id = order.deliverer_id
    action_taken = ""

    if order.order_status in ["pending", "accepted", "preparing", "ready"]:
        if reason not in vendor_fault_reasons + rider_fault_reasons:
            raise HTTPException(
                status_code=400,
                detail="That is not a reason this order can be dropped for.",
            )
        # Whose fault it was decides whether the customer still gets their
        # water. A shut store means nobody can fulfil it; a rider's own problem
        # means the order goes back on the radar for somebody else.
        action_taken = "cancelled" if reason in vendor_fault_reasons else "unassigned"
    elif order.order_status == "picked_up":
        if reason not in post_pickup_reasons:
            raise HTTPException(
                status_code=400,
                detail="That is not a reason this order can be dropped for.",
            )
        action_taken = "cancelled"
    else:
        raise HTTPException(status_code=400, detail=f"Cannot cancel order in state {order.order_status}")

    detailed_reason = f"{reason}: {details}" if details else reason

    if action_taken == "unassigned":
        # The order lives on and will be re-offered, so nothing is reverted —
        # the customer still wants it and the stock is still committed to them.
        order.cancellation_reason = detailed_reason
        order.deliverer_id = None
        apply_status_transition(order, "unassigned")
        deliverer.is_available = True
    else:
        # action_taken == "cancelled"
        from services.order_service import revert_order_side_effects

        apply_status_transition(order, "cancelled")
        deliverer.is_available = True
        await revert_order_side_effects(session, order, reason=detailed_reason)

    await session.commit()

    # WebSockets
    try:
        from routes.websocket_routes import manager
        await manager.broadcast_order_update(
            vendor_id=str(order.vendor_id),
            customer_id=str(order.customer_id),
            deliverer_id=str(previous_rider_id) if previous_rider_id else "",
            payload={
                "action": "ORDER_STATUS_UPDATE",
                "order_id": str(order.id),
                "status": action_taken,
                "reason": "rider_cancelled",
            }
        )
    except Exception as e:
        logger.error(f"WS Broadcast fail in cancel_delivery: {e}")

    # Notifications
    if action_taken == "unassigned":
        # Same as reject_delivery
        vendor = await session.get(Vendor, order.vendor_id)
        if vendor:
            title = "Rider Issue 🔄"
            body = f"Rider reported an issue ({reason}). Finding a new rider."
            action_url = "/(screens)/Orders"
            await create_notification(session=session, user_id=vendor.id, user_type="vendor", title=title, message=body, message_type="delivery_update", action_url=action_url, related_order_id=order.id)
            if vendor.push_token:
                dispatch_background(send_push_message(to=vendor.push_token, title=title, body=body, data={"url": action_url}))
        
        customer = await session.get(User, order.customer_id)
        if customer:
            title = "Finding a New Rider 🔄"
            body = "Your previous rider had an issue. We are dispatching a new rider!"
            action_url = "/(screens)/Orders"
            await create_notification(session=session, user_id=customer.id, user_type="customer", title=title, message=body, message_type="delivery_update", action_url=action_url, related_order_id=order.id)
            if customer.push_token and push_allowed(customer, "delivery_update"):
                dispatch_background(send_push_message(to=customer.push_token, title=title, body=body, data={"url": action_url}))
    else:
        # action_taken == "cancelled"
        vendor = await session.get(Vendor, order.vendor_id)
        if vendor:
            title = "Delivery Cancelled ❌"
            body = f"Rider cancelled the delivery. Reason: {reason}."
            if order.order_status == "cancelled" and reason not in vendor_fault_reasons:
                body += " The rider must return the goods to you."
            action_url = "/(screens)/Orders"
            await create_notification(session=session, user_id=vendor.id, user_type="vendor", title=title, message=body, message_type="order_cancelled", action_url=action_url, related_order_id=order.id)
            if vendor.push_token:
                dispatch_background(send_push_message(to=vendor.push_token, title=title, body=body, data={"url": action_url}))
        
        customer = await session.get(User, order.customer_id)
        if customer:
            title = "Delivery Cancelled ❌"
            body = "We are sorry, but your delivery was cancelled due to an issue."
            if order.payment_status == "refund_pending":
                body += " Your refund will be processed shortly."
            action_url = "/(screens)/Orders"
            await create_notification(session=session, user_id=customer.id, user_type="customer", title=title, message=body, message_type="order_cancelled", action_url=action_url, related_order_id=order.id)
            if customer.push_token and push_allowed(customer, "order_cancelled"):
                dispatch_background(send_push_message(to=customer.push_token, title=title, body=body, data={"url": action_url}))

    return {"message": "Cancellation processed", "action_taken": action_taken, "order_id": str(order.id)}

async def flush_tracking_logs():
    """Reads batched tracking logs from Redis and bulk inserts into Postgres."""
    from core.redis_client import get_redis
    r = get_redis()
    if not r:
        return

    # LPOP all logs currently in the list
    logs_to_insert = []
    try:
        while True:
            raw = await r.lpop("gps_tracking_logs")
            if not raw:
                break
            
            import json
            data = json.loads(raw)
            logs_to_insert.append(data)
            
            # Batch size limit per flush to avoid massive transactions
            if len(logs_to_insert) >= 500:
                break
    except Exception as e:
        logger.error(f"Failed to pop gps_tracking_logs from Redis: {e}")

    if not logs_to_insert:
        return

    from dependencies.dependencies import get_db_session
    from models.order_tracking_log_model import OrderTrackingLog
    import uuid
    
    # Process batch
    async with get_db_session() as session:
        try:
            # First, update deliverer current locations (group by rider to only apply the latest)
            rider_latest = {}
            for entry in logs_to_insert:
                rider_latest[entry["rider_id"]] = entry
                
            for rider_id, loc in rider_latest.items():
                await update_deliverer_location_by_id(
                    session=session,
                    deliverer_id=rider_id,
                    lat=loc["lat"],
                    lng=loc["lng"]
                )
                
            # Then, bulk insert order tracking logs
            tracking_records = []
            for entry in logs_to_insert:
                if entry.get("order_id"):
                    try:
                        o_id = uuid.UUID(entry["order_id"])
                        tracking_records.append(OrderTrackingLog(
                            order_id=o_id,
                            lat=entry["lat"],
                            lng=entry["lng"],
                            heading=entry["heading"],
                            speed=entry["speed"]
                        ))
                    except ValueError:
                        pass
                        
            if tracking_records:
                session.add_all(tracking_records)
                
            await session.commit()
            logger.info(f"Flushed {len(logs_to_insert)} tracking logs to DB.")
        except Exception as e:
            logger.error(f"Failed to flush tracking logs to DB: {e}")
            await session.rollback()
            # If we wanted to guarantee no data loss, we could RPUSH them back, 
            # but for tracking data it's okay to drop them to prevent endless poison loops.


# ── Background location pings ────────────────────────────────────────────────

#: One database write per rider per this many seconds. A background task
#: reporting every 25 m produces a ping every few seconds in traffic; writing
#: `Deliverer.current_lat/lng` (which also recomputes the PostGIS point and the
#: H3 cell) on every one of them is the expensive part. The individual pings are
#: still all recorded — they go to the Redis tracking list, which the GPS flush
#: job drains in bulk.
LOCATION_PING_WRITE_INTERVAL_SECONDS = 10

#: A batch bigger than this is either a bug or an attempt to flood the tracking
#: list. Ten minutes of pings at the fastest sane rate.
MAX_LOCATION_PINGS_PER_BATCH = 120


def _is_plausible_coordinate(lat: float, lng: float) -> bool:
    """Null Island and out-of-range values mean "no fix", not "at (0,0)"."""
    if lat is None or lng is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    return not (lat == 0.0 and lng == 0.0)


async def record_location_pings(session: AsyncSession, clerk_id: str, pings: list[dict]) -> dict:
    """Durable path for rider positions, used by the background location task.

    The app used to broadcast position over the WebSocket alone. A backgrounded
    app has no live socket — and backgrounding the app is the *entire* delivery,
    because the rider taps "Navigate" and switches to their maps app. Every
    coordinate from that point on was dropped by a `try/except` that only logged,
    so the customer's live map froze at the last position the rider happened to
    be looking at the screen for.

    This endpoint is now the path that must not lose data; the socket stays as
    the low-latency optimisation on top of it. Pings arrive batched, because a
    background task that wakes up without connectivity buffers and flushes later.
    """
    deliverer = await get_deliverer_by_clerk_id(session, clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    if not pings:
        return {"accepted": 0, "rejected": 0}
    if len(pings) > MAX_LOCATION_PINGS_PER_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"Too many pings in one batch (max {MAX_LOCATION_PINGS_PER_BATCH}).",
        )

    accepted = [p for p in pings if _is_plausible_coordinate(p.get("lat"), p.get("lng"))]
    rejected = len(pings) - len(accepted)
    if not accepted:
        return {"accepted": 0, "rejected": rejected}

    # A ping may name an order, which is what puts it in that order's tracking
    # history. Riders may only write to orders assigned to them — otherwise any
    # rider could forge another rider's delivery trail. An unowned order id is
    # stripped rather than rejected: the coordinate itself is still legitimate.
    named_order_ids = {p["order_id"] for p in accepted if p.get("order_id")}
    owned_order_ids: set[str] = set()
    if named_order_ids:
        try:
            rows = await session.execute(
                select(Order.id).where(
                    Order.id.in_([UUID(str(o)) for o in named_order_ids]),
                    Order.deliverer_id == deliverer.id,
                )
            )
            owned_order_ids = {str(row) for row in rows.scalars().all()}
        except (ValueError, TypeError):
            owned_order_ids = set()

    accepted.sort(key=lambda p: p.get("timestamp") or 0)
    newest = accepted[-1]

    import json
    import time

    from core.redis_client import get_redis

    redis = get_redis()
    now = time.time()

    entries = [
        {
            "rider_id": str(deliverer.id),
            "lat": float(p["lat"]),
            "lng": float(p["lng"]),
            "heading": float(p.get("heading") or 0.0),
            "speed": float(p.get("speed") or 0.0),
            "order_id": str(p["order_id"]) if str(p.get("order_id") or "") in owned_order_ids else None,
            "timestamp": p.get("timestamp") or now,
        }
        for p in accepted
    ]

    should_write_through = True
    if redis:
        try:
            await redis.rpush("gps_tracking_logs", *[json.dumps(e) for e in entries])
            # Throttle the row write, not the history. `nx` means the first ping
            # of each window wins and the rest cost nothing.
            should_write_through = bool(
                await redis.set(
                    f"rider:loc:{deliverer.id}",
                    "1",
                    ex=LOCATION_PING_WRITE_INTERVAL_SECONDS,
                    nx=True,
                )
            )
        except Exception as e:
            logger.warning("Redis unavailable for location pings (rider %s): %s", deliverer.id, e)
            redis = None
            should_write_through = True

    if should_write_through:
        # Reuse the same guarded writer the socket path uses, so the PostGIS
        # point and the H3 dispatch cell can never be updated by one path and
        # not the other.
        await update_deliverer_location_by_id(
            session=session,
            deliverer_id=str(deliverer.id),
            lat=float(newest["lat"]),
            lng=float(newest["lng"]),
        )

    if not redis:
        # No queue, so the per-order trail has to be written here or it is lost.
        from models.order_tracking_log_model import OrderTrackingLog

        records = [
            OrderTrackingLog(
                order_id=UUID(e["order_id"]),
                lat=e["lat"],
                lng=e["lng"],
                heading=e["heading"],
                speed=e["speed"],
            )
            for e in entries
            if e["order_id"]
        ]
        if records:
            session.add_all(records)
            await session.commit()

    # Fan out to whoever is watching this rider. Best effort: a tracking socket
    # that is down must never fail the write that keeps the history correct.
    try:
        from routes.websocket_routes import manager

        await manager.update_rider_location(
            str(deliverer.id),
            {
                "lat": float(newest["lat"]),
                "lng": float(newest["lng"]),
                "heading": float(newest.get("heading") or 0.0),
                "speed": float(newest.get("speed") or 0.0),
                "order_id": str(newest["order_id"]) if newest.get("order_id") else None,
            },
        )
    except Exception as e:
        logger.warning("Could not relay location ping for rider %s: %s", deliverer.id, e)

    return {"accepted": len(accepted), "rejected": rejected}
