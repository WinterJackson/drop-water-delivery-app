import logging
import math
from enum import Enum as PyEnum
from sqlalchemy.ext.asyncio import AsyncSession
from collections import defaultdict
from uuid import UUID
from sqlalchemy import select, and_, update
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from geoalchemy2.functions import ST_Distance
from models.cart_model import CartItem
from models.deliverer_model import Deliverer
from models.product_model import Product
from models.order_model import Order, OrderItem
from models.vendor_model import Vendor
from models.user_model import User
from schemas.order_schema import BaseOrder
from services.expo_push_service import send_push_message
from services.notification_service import create_notification, queue_push
from services.dispatch_policy import DispatchPolicy
import asyncio

EARTH_RADIUS_KM = 6371.0
MINUTES_PER_KM = 3.0  # Average bike speed in Nairobi urban traffic

logger = logging.getLogger(__name__)


# ── F-029 FIX: Order Status Enum & State Machine ────────────────────────────
class OrderStatusEnum(str, PyEnum):
    PENDING = "pending"
    UNASSIGNED = "unassigned"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"
    MISMATCH_PENDING = "mismatch_pending"

# Valid transitions: from_status -> allowed_to_statuses
VALID_TRANSITIONS = {
    OrderStatusEnum.PENDING: {OrderStatusEnum.ACCEPTED, OrderStatusEnum.REJECTED, OrderStatusEnum.CANCELLED, OrderStatusEnum.UNASSIGNED},
    OrderStatusEnum.UNASSIGNED: {OrderStatusEnum.PENDING, OrderStatusEnum.CANCELLED},
    OrderStatusEnum.ACCEPTED: {OrderStatusEnum.PREPARING, OrderStatusEnum.CANCELLED},
    OrderStatusEnum.PREPARING: {OrderStatusEnum.READY, OrderStatusEnum.CANCELLED},
    OrderStatusEnum.READY: {OrderStatusEnum.PICKED_UP},
    OrderStatusEnum.PICKED_UP: {OrderStatusEnum.DELIVERED, OrderStatusEnum.PENDING_REVIEW, OrderStatusEnum.MISMATCH_PENDING},
    OrderStatusEnum.PENDING_REVIEW: {OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED},
    OrderStatusEnum.MISMATCH_PENDING: {OrderStatusEnum.DELIVERED},
    OrderStatusEnum.DELIVERED: set(),  # Terminal state
    OrderStatusEnum.CANCELLED: set(),  # Terminal state
    OrderStatusEnum.REJECTED: set(),   # Terminal state
}

def validate_status_transition(current: str, new: str) -> bool:
    """Returns True if the transition is valid per the state machine."""
    try:
        current_enum = OrderStatusEnum(current)
        new_enum = OrderStatusEnum(new)
    except ValueError:
        return False
    return new_enum in VALID_TRANSITIONS.get(current_enum, set())

# Revenue split constants
RETAIL_VENDOR_COMMISSION = 0.05   # 5% of product price
WHOLESALE_VENDOR_COMMISSION = 0.025  # 2.5% of product price
RETAIL_SERVICE_FEE_KSH = 12.0    # Flat service fee for retail orders
WHOLESALE_SERVICE_FEE_KSH = 50.0
GIG_RIDER_COMMISSION = 0.10       # 10% of delivery fee
GIG_PLATINUM_COMMISSION = 0.07    # 7% of delivery fee for Platinum riders
IN_HOUSE_RIDER_COMMISSION = 0.0   # 0% — vendor owns the fleet
WHOLESALE_DELIVERY_MARKUP = 0.05  # 5% platform surcharge on wholesale delivery fees
SURGE_FEE_KSH = 10.0             # KSH 10 surcharge during peak hours

# Peak hour windows (Nairobi local time)
PEAK_HOURS = [(6, 8), (17, 19)]   # 6:00-8:00 AM and 5:00-7:00 PM


NAIROBI_TZ_OFFSET_HOURS = 3  # EAT = UTC+3, no DST


def is_surge_active(now=None) -> bool:
    """Is the current East Africa Time inside a documented peak window?

    `now` is injectable so the surge windows can be asserted deterministically
    instead of only when the suite happens to run at 07:00 or 18:00.
    """
    from datetime import datetime, timezone, timedelta

    nairobi_tz = timezone(timedelta(hours=NAIROBI_TZ_OFFSET_HOURS))
    moment = now.astimezone(nairobi_tz) if now is not None else datetime.now(nairobi_tz)
    current_hour = moment.hour
    return any(start <= current_hour < end for start, end in PEAK_HOURS)

def _haversine_km(lat_from: float, lng_from: float, lat_to: float, lng_to: float) -> float:
    """Pure Haversine distance in km between two GPS points."""
    d_lat = math.radians(lat_to - lat_from)
    d_lng = math.radians(lng_to - lng_from)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat_from)) * math.cos(math.radians(lat_to)) *
         math.sin(d_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(EARTH_RADIUS_KM * c, 2)


def calculate_cart_payload(items) -> dict:
    """Sum the total weight of all cart items to determine required vehicle class.
    Returns { 'total_weight_kg': float, 'required_vehicle': str, 'total_quantity': int }
    """
    total_weight_kg = 0.0
    total_quantity = 0
    for item in items:
        product = item.product
        total_quantity += item.quantity
        if product and hasattr(product, 'weight_kg'):
            total_weight_kg += float(product.weight_kg) * item.quantity

    if total_weight_kg > 0:
        if total_weight_kg <= 100.0:
            required_vehicle = "motorbike"
        elif total_weight_kg <= 400.0:
            required_vehicle = "tuktuk"
        else:
            required_vehicle = "truck"
    else:
        # Fallback to quantity based capacity logic from DispatchPolicy
        required_vehicle = DispatchPolicy.get_vehicle_class(total_quantity)

    return {"total_weight_kg": round(total_weight_kg, 2), "required_vehicle": required_vehicle, "total_quantity": total_quantity}


def calculate_delivery_fee(
    lat_from: float, lng_from: float,
    lat_to: float, lng_to: float,
    vendor_type: str = "retail_refill",
    vehicle_class: str = "motorbike",
    wholesale_base: float = 0.0,
    wholesale_per_km: float = 0.0,
    delivery_type: str = "quick_swap"
) -> dict:
    """Returns { 'distance_km': float, 'fee': float, 'estimated_minutes': int, 'vehicle_class': str }"""
    if not all([lat_from, lng_from, lat_to, lng_to]):
        return {"distance_km": 0.0, "fee": DispatchPolicy.get_delivery_fee(0.0, vendor_type, vehicle_class, wholesale_base, wholesale_per_km, delivery_type), "estimated_minutes": 15, "vehicle_class": vehicle_class}

    distance_km = _haversine_km(lat_from, lng_from, lat_to, lng_to)
    fee = DispatchPolicy.get_delivery_fee(distance_km, vendor_type, vehicle_class, wholesale_base, wholesale_per_km, delivery_type)
    estimated_minutes = max(5, int(math.ceil(distance_km * MINUTES_PER_KM)))

    return {
        "distance_km": distance_km,
        "fee": fee,
        "estimated_minutes": estimated_minutes,
        "vehicle_class": vehicle_class,
    }


def calculate_revenue_splits(
    product_total: float,
    delivery_fee: float,
    vendor_type: str = "retail_refill",
    bottle_deposit: float = 0.0,
    rider_surcharges: float = 0.0,
    delivery_type: str = "quick_swap",
    welcome_discount: float = 0.0
) -> dict:
    """Calculate platform revenue splits for a single order.
    FIN-01 FIX: Uses Decimal for currency precision to prevent ledger drift.
    Returns { 'vendor_commission', 'service_fee', 'rider_commission', 'platform_total',
              'vendor_net', 'rider_net', 'surge_fee', 'delivery_markup' }
    """
    from decimal import Decimal, ROUND_HALF_UP

    # Convert all inputs to Decimal
    _pt = Decimal(str(product_total))
    _df = Decimal(str(delivery_fee))
    _bd = Decimal(str(bottle_deposit))
    _rs = Decimal(str(rider_surcharges))
    _wd = Decimal(str(welcome_discount))

    TWO = Decimal("0.01")

    # ── Vendor Commission ──
    if vendor_type == "wholesale_b2b":
        vendor_commission = (_pt * Decimal(str(WHOLESALE_VENDOR_COMMISSION))).quantize(TWO, rounding=ROUND_HALF_UP)
        service_fee = Decimal(str(WHOLESALE_SERVICE_FEE_KSH))
    else:
        vendor_commission = (_pt * Decimal(str(RETAIL_VENDOR_COMMISSION))).quantize(TWO, rounding=ROUND_HALF_UP)
        service_fee = Decimal(str(RETAIL_SERVICE_FEE_KSH))

    # ── Rider Commission (Gig only; wholesale in-house is exempt) ──
    if vendor_type == "wholesale_b2b":
        rider_commission = Decimal("0.00")
    else:
        # M-09 FIX: Reference the module-level constants instead of inline values
        # keep_my_bottle adds 2% premium (12% vs 10%) for extra bottle handling
        if delivery_type == "keep_my_bottle":
            commission_rate = Decimal(str(GIG_RIDER_COMMISSION)) + Decimal("0.02")
        else:
            commission_rate = Decimal(str(GIG_RIDER_COMMISSION))
        rider_commission = (_df * commission_rate).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── Wholesale Delivery Markup (5% surcharge on delivery fee) ──
    if vendor_type == "wholesale_b2b":
        delivery_markup = (_df * Decimal(str(WHOLESALE_DELIVERY_MARKUP))).quantize(TWO, rounding=ROUND_HALF_UP)
    else:
        delivery_markup = Decimal("0.00")

    # ── Surge Pricing (KSH 10 during peak hours) ──
    surge_fee = Decimal(str(SURGE_FEE_KSH)) if is_surge_active() else Decimal("0.00")

    # ── Platform Total Revenue ──
    # Platform absorbs the welcome discount as a customer acquisition cost
    platform_total = (vendor_commission + service_fee + rider_commission + delivery_markup + surge_fee - _wd).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── Net Payouts ──
    # Wholesale vendors get delivery fee back (they own the fleet)
    if vendor_type == "wholesale_b2b":
        vendor_net = (_pt - vendor_commission + _df + _bd).quantize(TWO, rounding=ROUND_HALF_UP)
    else:
        vendor_net = (_pt - vendor_commission + _bd).quantize(TWO, rounding=ROUND_HALF_UP)

    rider_net = (_df - rider_commission + _rs).quantize(TWO, rounding=ROUND_HALF_UP)

    return {
        "vendor_commission": float(vendor_commission),
        "service_fee": float(service_fee),
        "rider_commission": float(rider_commission),
        "platform_total": float(platform_total),
        "vendor_net": float(vendor_net),
        "rider_net": float(rider_net),
        "surge_fee": float(surge_fee),
        "delivery_markup": float(delivery_markup),
    }


async def get_radar_deliverers(session: AsyncSession, lat: float, lng: float, vendor_id: UUID = None, vehicle_class: str = "motorbike", vendor_type: str = "retail_refill"):
  """Find the closest available deliverers within precise delivery bounds.
  Uses high-level dynamic k-ring bounds coupled with exact ST_Distance geographic clipping."""
  from models.vendor_rider_model import VendorRiderRegistry
  from models.deliverer_model import RiderVehicleType
  from geoalchemy2.shape import from_shape
  from shapely.geometry import Point
  import h3
  
  try:
      vehicle_enum = RiderVehicleType(vehicle_class)
  except ValueError:
      vehicle_enum = RiderVehicleType.motorbike
      
  # 1. Parameterize limits
  max_distance_m = DispatchPolicy.get_max_distance_m(vendor_type, action="rider_search")
      
  # 2. H3 pre-filter for indexed speed
  center_hex = h3.latlng_to_cell(lat, lng, 8)
  k_ring = DispatchPolicy.get_h3_k_ring(vendor_type)
  nearby_hexes = [str(h) for h in h3.grid_disk(center_hex, k_ring)]

  # 3. Fast Euclidean Post-Filter
  pickup_point = from_shape(Point(lng, lat), srid=4326)

  query = select(Deliverer, Deliverer.push_token, Deliverer.id.label("user_id")).where(
      and_(
          Deliverer.is_available, 
          Deliverer.employment_model == "gig_economy",  # Tier 2 is restricted to Gig-Economy
          Deliverer.vehicle_type == vehicle_enum, 
          Deliverer.h3_index_res8.in_(nearby_hexes),
          Deliverer.location.isnot(None),
          ST_Distance(Deliverer.location, pickup_point) <= max_distance_m
      )
  )
  
  if vendor_id:
      query = query.join(VendorRiderRegistry, VendorRiderRegistry.rider_id == Deliverer.id).where(
          and_(VendorRiderRegistry.vendor_id == vendor_id, VendorRiderRegistry.status == "approved")
      )

  result = await session.execute(query)
  deliverers = result.all()
  return deliverers


async def get_closest_deliverer(session: AsyncSession, lat: float, lng: float, vendor_id: UUID = None, vehicle_class: str = "motorbike", vendor_type: str = "retail_refill"):
  """Find the single nearest available rider using PostGIS ST_Distance.
  Filtered by vehicle_class to match the order's payload requirements.
  Falls back to H3 grid_disk search, then to raw distance-based global scan."""
  from models.vendor_rider_model import VendorRiderRegistry
  from models.deliverer_model import RiderVehicleType
  from geoalchemy2.shape import from_shape
  from shapely.geometry import Point
  import h3

  pickup_point = from_shape(Point(lng, lat), srid=4326)

  try:
      vehicle_enum = RiderVehicleType(vehicle_class)
  except ValueError:
      vehicle_enum = RiderVehicleType.motorbike

  max_distance_m = DispatchPolicy.get_max_distance_m(vendor_type, action="rider_search")

  # Step 1: Try H3 grid_disk neighbors first (fast indexed lookup)
  center_hex = h3.latlng_to_cell(lat, lng, 8)
  k_ring = DispatchPolicy.get_h3_k_ring(vendor_type)
  nearby_hexes = [str(h) for h in h3.grid_disk(center_hex, k_ring)]

  query = (
      select(Deliverer)
      .where(
          and_(
              Deliverer.is_available,
              Deliverer.vehicle_type == vehicle_enum,
              Deliverer.h3_index_res8.in_(nearby_hexes),
              Deliverer.location.isnot(None),
              ST_Distance(Deliverer.location, pickup_point) <= max_distance_m,
          )
      )
      .order_by(ST_Distance(Deliverer.location, pickup_point))
      .limit(1)
  )

  if vendor_id:
      query = query.join(VendorRiderRegistry, VendorRiderRegistry.rider_id == Deliverer.id).where(
          and_(VendorRiderRegistry.vendor_id == vendor_id, VendorRiderRegistry.status == "approved")
      )

  result = await session.execute(query)
  deliverer = result.scalar_one_or_none()

  if deliverer:
      return deliverer

  # Step 2: Fallback — global scan (no H3 filter) within max allowed distance
  fallback_query = (
      select(Deliverer)
      .where(
          and_(
              Deliverer.is_available,
              Deliverer.vehicle_type == vehicle_enum,
              Deliverer.location.isnot(None),
              ST_Distance(Deliverer.location, pickup_point) <= max_distance_m,
          )
      )
      .order_by(ST_Distance(Deliverer.location, pickup_point))
      .limit(1)
  )

  if vendor_id:
      fallback_query = fallback_query.join(VendorRiderRegistry, VendorRiderRegistry.rider_id == Deliverer.id).where(
          and_(VendorRiderRegistry.vendor_id == vendor_id, VendorRiderRegistry.status == "approved")
      )

  result = await session.execute(fallback_query)
  return result.scalar_one_or_none()


# ── V6: 20-Second Tiered Dispatch Engine ───────────────────────────────────
# Tier 1 (0-20s):  Push exclusively to pre-approved riders from VendorRiderRegistry
# Tier 2 (20s+):   Escalate to full Trip Radar broadcast to ALL nearby H3 riders
# ───────────────────────────────────────────────────────────────────────────

DISPATCH_TIER1_TIMEOUT_SECONDS = 20

async def dispatch_order_to_riders(
    order_id: UUID,
    vendor_id: UUID,
    customer_id: UUID,
    lat: float,
    lng: float,
    delivery_fee: float,
    vehicle_class: str = "motorbike",
    vendor_type: str = "retail_refill",
    total_weight_kg: float = 0.0,
    total_quantity: int = 0,
    delivery_type: str = "quick_swap",
    notification_data: dict = None,
):
    """Background async task: implements the 20-second tiered dispatch escalation.

    Tier 1 — Push to pre-approved riders from VendorRiderRegistry.
             Wait 20 seconds for one of them to accept.
    Tier 2 — If the order is still unassigned after 20s, escalate to the
             Trip Radar broadcast targeting ALL H3-nearby riders with matching vehicle type.
    """
    from dependencies.dependencies import get_db_session
    from models.vendor_rider_model import VendorRiderRegistry
    from models.deliverer_model import RiderVehicleType

    try:
        vehicle_enum = RiderVehicleType(vehicle_class)
    except ValueError:
        vehicle_enum = RiderVehicleType.motorbike

    # ── TIER 1: Pre-Approved Vendor Riders ──────────────────────────────
    try:
        from sqlalchemy.orm import selectinload
        async with get_db_session() as session:
            order_res = await session.execute(
                select(Order).options(selectinload(Order.vendor)).where(Order.id == order_id)
            )
            order = order_res.scalar_one_or_none()
            if not order or not order.vendor:
                logger.error(f"Dispatch Tier 1: Order {order_id} or vendor not found")
                return

            # Fetch up to 10 pre-approved riders for this vendor with matching vehicle type
            tier1_query = (
                select(Deliverer, Deliverer.push_token, Deliverer.id.label("user_id"))
                .join(VendorRiderRegistry, VendorRiderRegistry.rider_id == Deliverer.id)
                .where(
                    and_(
                        VendorRiderRegistry.vendor_id == vendor_id,
                        VendorRiderRegistry.status == "approved",
                        Deliverer.is_available,
                        Deliverer.vehicle_type == vehicle_enum,
                    )
                )
                .limit(10)
            )
            result = await session.execute(tier1_query)
            tier1_riders = result.all()

            tier1_count = len(tier1_riders)
            logger.info(f"Dispatch Tier 1: Found {tier1_count} pre-approved riders for order {order_id}")

            if tier1_count > 0:
                title = "New Delivery from Your Vendor! 📦"
                body = f"Ksh {delivery_fee:.0f} Fee | {total_quantity} items ({total_weight_kg}kg). Tap to accept."
                action_url = "/(screens)/Orders"

                for rider_obj, p_token, uid in tier1_riders:
                    await create_notification(
                        session=session,
                        user_id=uid,
                        user_type="rider",
                        title=title,
                        message=body,
                        message_type="new_delivery",
                        action_url=action_url,
                        related_order_id=order_id,
                        data=notification_data
                    )
                    queue_push(session, to=p_token, title=title, body=body,
                               data={"url": action_url})

                # WebSocket event to rider apps
                try:
                    from routes.websocket_routes import manager
                    rider_ids = [str(uid) for _, _, uid in tier1_riders]
                    await manager.broadcast_to_riders(
                        rider_ids=rider_ids,
                        payload={
                            "action": "NEW_DELIVERY_OFFER",
                            "order_id": str(order_id),
                            "fee": delivery_fee,
                            "tier": 1,
                            "weight_kg": total_weight_kg,
                            "quantity": total_quantity,
                            "delivery_type": delivery_type,
                            "vendor": {
                                "id": str(order.vendor.id),
                                "business_name": order.vendor.business_name,
                                "location_address": order.vendor.location_address,
                                "lat": order.vendor.lat,
                                "lng": order.vendor.lng,
                            },
                            "payment_method": order.payment_method,
                            "vendor_net": float(order.vendor_net or 0),
                            "platform_total": float(order.platform_total or 0),
                            "distance_km": order.distance_km,
                            "lat_from": order.lat_from,
                            "lng_from": order.lng_from,
                            "lat": order.lat,
                            "lng": order.lng,
                        }
                    )
                except Exception as e:
                    logger.error(f"Dispatch Tier 1 WS fail: {e}")

                await session.commit()

    except Exception as e:
        logger.error(f"Dispatch Tier 1 error for order {order_id}: {e}")

    # ── WAIT 20 SECONDS ────────────────────────────────────────────────
    await asyncio.sleep(DISPATCH_TIER1_TIMEOUT_SECONDS)

    # ── TIER 2: Trip Radar Broadcast (only if still unassigned) ─────────
    # If Wholesale B2B, DO NOT broadcast to Trip Radar (Gig-Economy bypassed)
    if vendor_type == "wholesale_b2b":
        logger.info(f"Dispatch Tier 2: Bypassing Trip Radar for Wholesale Order {order_id}")
        return

    try:
        from sqlalchemy.orm import selectinload
        async with get_db_session() as session:
            # Re-check order status — someone may have accepted during the 20s window
            order_check = await session.execute(
                select(Order).options(selectinload(Order.vendor)).where(Order.id == order_id)
            )
            order = order_check.scalar_one_or_none()
            if not order or not order.vendor:
                logger.warning(f"Dispatch Tier 2: Order {order_id} not found, aborting.")
                return
            if order.order_status != "unassigned" or order.deliverer_id is not None:
                logger.info(f"Dispatch Tier 2: Order {order_id} already claimed. Skipping broadcast.")
                return

            # Fetch ALL nearby riders via H3 (not just vendor-approved ones)
            radar_riders = await get_radar_deliverers(
                session=session, lat=lat, lng=lng,
                vendor_id=None,  # No vendor filter — open to all nearby riders
                vehicle_class=vehicle_class,
            )

            tier2_count = len(radar_riders)
            logger.info(f"Dispatch Tier 2: Broadcasting to {tier2_count} Trip Radar riders for order {order_id}")

            if tier2_count > 0:
                title = "Trip Radar: New Delivery! 📦"
                body = f"Ksh {delivery_fee:.0f} Fee | {total_quantity} items ({total_weight_kg}kg). Tap to accept."
                action_url = "/(screens)/Orders"

                for rider_obj, p_token, uid in radar_riders:
                    await create_notification(
                        session=session,
                        user_id=uid,
                        user_type="rider",
                        title=title,
                        message=body,
                        message_type="new_delivery",
                        action_url=action_url,
                        related_order_id=order_id,
                        data=notification_data
                    )
                    queue_push(session, to=p_token, title=title, body=body,
                               data={"url": action_url})

                # Trip Radar WebSocket event
                try:
                    from routes.websocket_routes import manager
                    rider_ids = [str(uid) for _, _, uid in radar_riders]
                    await manager.broadcast_to_riders(
                        rider_ids=rider_ids,
                        payload={
                            "action": "TRIP_RADAR_BROADCAST",
                            "order_id": str(order_id),
                            "fee": delivery_fee,
                            "tier": 2,
                            "weight_kg": total_weight_kg,
                            "quantity": total_quantity,
                            "delivery_type": delivery_type,
                            "vendor": {
                                "id": str(order.vendor.id),
                                "business_name": order.vendor.business_name,
                                "location_address": order.vendor.location_address,
                                "lat": order.vendor.lat,
                                "lng": order.vendor.lng,
                            },
                            "payment_method": order.payment_method,
                            "vendor_net": float(order.vendor_net or 0),
                            "platform_total": float(order.platform_total or 0),
                            "distance_km": order.distance_km,
                            "lat_from": order.lat_from,
                            "lng_from": order.lng_from,
                            "lat": order.lat,
                            "lng": order.lng,
                        }
                    )
                except Exception as e:
                    logger.error(f"Dispatch Tier 2 WS fail: {e}")

                await session.commit()
            else:
                logger.warning(f"Dispatch Tier 2: No riders found for order {order_id}. Order remains unassigned.")

    except Exception as e:
        logger.error(f"Dispatch Tier 2 error for order {order_id}: {e}")


async def create_order(
    session: AsyncSession,
    CheckoutRequestID: str | None,
    id: UUID,
    user_id: UUID,
    phone: str,
    type: str,
    lat: float,
    lng: float,
    delivery_type: str = "quick_swap",
    payment_method: str = "mpesa",
    quote=None,
):
  """Materialise a paid-or-pending order from a cart.

  `quote` is an `OrderQuote` from `services.pricing_service`. When the caller has
  already priced the cart — which `POST /api/cart/mpesa_payment` must do, because
  it needs the total *before* it can push the STK request — it passes that exact
  quote in, and every monetary column on the order is taken from it verbatim.
  That is what guarantees `order.total_amount == the amount we charged`; letting
  this function re-derive the price is exactly how the two drifted apart.

  When `quote` is None (tests, seeds, cash-only callers) we price it here using
  the same function, so there is still only one formula in the codebase.
  """
  from services.pricing_service import (
      compute_order_quote,
      validate_quote,
      single_vendor_or_400,
  )
  from decimal import Decimal

  if type != "cart":
      raise HTTPException(status_code=400, detail=f"Unsupported order source '{type}'.")

  # --- Idempotency Guard: Prevent duplicate STK push double-charges ---
  if CheckoutRequestID:
      existing_order = await session.execute(
          select(Order).where(Order.checkout_request_ID == CheckoutRequestID).limit(1)
      )
      if existing_order.scalar_one_or_none():
          raise HTTPException(
              status_code=409,
              detail="This payment request has already been processed. Please refresh your orders."
          )

  # Lock the customer row for the whole transaction: the welcome offer and the
  # wallet balance are both consumed below and must not be spendable twice.
  user_res = await session.execute(select(User).where(User.id == user_id).with_for_update())
  user = user_res.scalar_one_or_none()
  if not user:
      raise HTTPException(status_code=403, detail="Customer profile not found.")

  items_result = await session.execute(
      select(CartItem)
      .where(CartItem.cart_id == id)
      .options(joinedload(CartItem.vendor), joinedload(CartItem.product))
  )
  pre_order_items = items_result.unique().scalars().all()
  if not pre_order_items:
      raise HTTPException(status_code=400, detail="Your cart is empty. Add an item before checking out.")

  vendor_id = single_vendor_or_400(pre_order_items)
  vendor = await session.get(Vendor, vendor_id)

  # --- Anti-Fraud: Self-Dealing Prevention ---
  if vendor and (user.clerk_id == vendor.clerk_id or user.clerk_id == getattr(vendor, "staff_clerk_id", None)):
      raise HTTPException(
          status_code=403,
          detail="Self-dealing prohibited. You cannot place an order from your own store."
      )

  locked_balance = Decimal(str(user.wallet_balance or 0))

  if quote is None:
      quote = await compute_order_quote(
          session,
          items=pre_order_items,
          user=user,
          vendor=vendor,
          delivery_type=delivery_type,
          lat=lat,
          lng=lng,
          wallet_balance_override=locked_balance,
      )
  elif quote.wallet_discount > locked_balance:
      # The balance moved between pricing and creation (a concurrent order or
      # withdrawal). Refuse rather than silently charging a different amount than
      # the one already pushed to the customer's phone.
      raise HTTPException(
          status_code=409,
          detail="Your wallet balance changed while checking out. Please review your cart and try again.",
      )

  # Re-run every gate under the lock — stock and debt can move between pricing
  # and creation even though the cart itself is locked.
  validate_quote(quote, pre_order_items, user=user)

  import h3
  order_h3_index = h3.latlng_to_cell(lat, lng, 8)

  revenue = quote.revenue

  order = Order(
      customer_id=user_id,
      vendor_id=vendor_id,
      checkout_request_ID=CheckoutRequestID,
      deliverer_id=None,
      # Rider is never direct-assigned; the tiered dispatch engine offers the
      # trip and a rider claims it.
      order_status="unassigned",
      lat_from=quote.lat_from,
      lng_from=quote.lng_from,
      lat=lat,
      lng=lng,
      h3_index_res8=str(order_h3_index),
      distance_km=quote.distance_km,
      phone=phone,
      delivery_address=user.location_address if user else None,
      total_amount=quote.total,
      delivery_fee=float(quote.delivery_fee),

      # ── Surcharges ──
      staircase_surcharge=quote.staircase_surcharge,
      payload_surcharge=quote.payload_surcharge,

      # ── Revenue Split Ledger ──
      vendor_commission=revenue["vendor_commission"],
      service_fee=revenue["service_fee"],
      rider_commission=revenue["rider_commission"],
      platform_total=revenue["platform_total"],
      vendor_net=revenue["vendor_net"],
      rider_net=revenue["rider_net"],
      surge_fee=quote.surge_fee,
      delivery_markup=quote.delivery_markup,
      vehicle_class=quote.vehicle_class,
      delivery_time=quote.estimated_minutes,
      is_welcome_offer=quote.is_welcome_offer,
      delivery_type=delivery_type,
      bottle_source="platform" if quote.is_welcome_offer else "own",
      payment_method=payment_method,

      # ── Discount Audit Trail ──
      wallet_discount=quote.wallet_discount,
      welcome_discount=quote.welcome_discount,
      product_subtotal=quote.product_subtotal,
  )
  session.add(order)
  await session.flush()

  # ── Consume the one-shot incentives, now that the order exists ─────────────
  if quote.is_welcome_offer:
      user.has_used_welcome_offer = True
      logger.info(
          "Welcome offer consumed by user %s: KSH %s off a deposit of %s",
          user_id, quote.welcome_discount, quote.bottle_deposit,
      )

  if quote.wallet_discount > 0:
      # Balance and ledger row in one call. The amount is negative because this
      # is money leaving the wallet — `transaction_type` cannot carry direction,
      # since `order_payment` also credits riders their delivery earnings.
      from services.wallet_service import apply_wallet_delta
      from models.wallet_transaction_model import TransactionType
      user.wallet_balance = locked_balance   # value read under the row lock
      await apply_wallet_delta(
          session,
          owner=user,
          clerk_id=user.clerk_id,
          user_type="customer",
          amount=-quote.wallet_discount,
          transaction_type=TransactionType.order_payment,
          description=f"Wallet credit applied to order {str(order.id)[:8].upper()}",
          reference_id=str(order.id),
      )

  for item in pre_order_items:
      session.add(OrderItem(
          order_id=order.id,
          product_id=item.product_id,
          quantity=item.quantity,
          price=item.price,
          Subtotal=item.Subtotal,
      ))

      # --- Atomic Stock Decrement ---
      # UPDATE ... WHERE stock >= qty RETURNING: if no row comes back, a
      # concurrent order depleted the stock and we must not oversell.
      result = await session.execute(
          update(Product)
          .where(Product.id == item.product_id, Product.stock >= item.quantity)
          .values(
              stock=Product.stock - item.quantity,
              is_available=Product.stock - item.quantity > 0
          )
          .returning(Product.stock, Product.name, Product.vendor_id)
      )
      updated_row = result.fetchone()
      if not updated_row:
          raise HTTPException(
              status_code=400,
              detail="Insufficient stock for product (concurrent purchase detected). Please refresh and try again."
          )

      new_stock, product_name, vendor_id_for_push = updated_row

      # Low stock push threshold evaluator
      if new_stock <= 5:
          stock_alert_vendor = await session.get(Vendor, vendor_id_for_push)
          if stock_alert_vendor:
              title = "Low Stock Alert! ⚠️"
              body = f"'{product_name}' is running critically low ({new_stock} left). Restock soon!"
              action_url = "/(screens)/Inventory"
              await create_notification(
                  session=session,
                  user_id=stock_alert_vendor.id,
                  user_type="vendor",
                  title=title,
                  message=body,
                  message_type="low_stock",
                  action_url=action_url
              )
              queue_push(session, to=stock_alert_vendor.push_token, title=title,
                         body=body, data={"url": action_url})

  await session.commit()
  return order

async def update_orders_payment_status_by_checkout_id(
    session: AsyncSession,
    checkout_request_id: str,
    new_status: str
):
    """Transition an order's payment status, exactly once.

    Two independent callers race here on every single order: the client polls
    `/confirm_payment` every few seconds, and Safaricom POSTs `/mpesa/callback`
    (and retries it). Without the guard below, each call re-broadcast NEW_ORDER,
    created another vendor notification, and spawned another
    `dispatch_order_to_riders` cascade — so a normal checkout could offer the same
    trip to the whole rider pool several times over.

    The row lock plus the terminal-state check make this idempotent: only the
    transition *into* `paid` fires side effects, and only one caller can win it.
    """
    stmt = (
        select(Order)
        .where(Order.checkout_request_ID == checkout_request_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    orders = result.scalars().all()

    if not orders:
        return {"message": "No orders found with that checkout_request_ID"}

    # `paid` is terminal for the payment lifecycle. A late `failed` must never
    # walk a paid order backwards, and a repeated `paid` must be a no-op.
    already_settled = [o for o in orders if o.payment_status == "paid"]
    if already_settled:
        if new_status == "paid":
            logger.info(
                "Payment %s already settled — skipping duplicate side effects.", checkout_request_id
            )
            return {"message": "Transaction was completed successfully.", "code": "0"}
        logger.warning(
            "Refusing to move already-paid payment %s to '%s'.", checkout_request_id, new_status
        )
        return {"message": "Transaction was completed successfully.", "code": "0"}

    pending_dispatches: list[dict] = []

    for order in orders:
        order.payment_status = new_status
        if new_status == "paid":
            # Load the vendor separately: combining `joinedload` with
            # `FOR UPDATE` locks the nullable side of an outer join, which
            # Postgres rejects.
            order_vendor = await session.get(Vendor, order.vendor_id)
            try:
                from routes.websocket_routes import manager
                await manager.broadcast_order_update(
                    vendor_id=str(order.vendor_id),
                    customer_id=str(order.customer_id),
                    deliverer_id=str(order.deliverer_id) if order.deliverer_id else "",
                    payload={"action": "NEW_ORDER", "order_id": str(order.id), "status": "paid"}
                )
            except Exception as e:
                logger.error(f"WS Broadcast fail: {e}")

            if order_vendor:
                from services.order_snapshot import build_order_snapshot
                from services.dispatch_policy import DispatchPolicy

                # Fetch order items including product relationship
                _items_result = await session.execute(
                    select(OrderItem).options(joinedload(OrderItem.product))
                    .where(OrderItem.order_id == order.id)
                )
                order_items = _items_result.unique().scalars().all()
                _total_qty = sum(i.quantity for i in order_items)
                _total_weight = sum(float(i.product.weight_kg or 0) * i.quantity for i in order_items if i.product)

                snapshot_data = build_order_snapshot(order, order_items, order_vendor, role="vendor")

                title = "New Order Received! 📦"
                body = (
                    f"Ksh {order.total_amount} | {_total_qty} items | "
                    f"{order.vehicle_class or 'motorbike'} delivery. "
                    f"Type: {order.delivery_type or 'quick_swap'}."
                )
                action_url = "/(screens)/Orders"
                await create_notification(
                    session=session,
                    user_id=order_vendor.id,
                    user_type="vendor",
                    title=title,
                    message=body,
                    message_type="new_order",
                    action_url=action_url,
                    related_order_id=order.id,
                    data=snapshot_data
                )
                queue_push(session, to=order_vendor.push_token, title=title,
                           body=body, data={"url": action_url})

                # Auto-dispatch (only retail per Policy)
                vendor_type_str = order_vendor.vendor_type.value if hasattr(order_vendor.vendor_type, 'value') else order_vendor.vendor_type
                if DispatchPolicy.should_auto_dispatch(vendor_type_str):
                    # Deferred until after the commit: the dispatch task opens its
                    # own session, so firing it now would let it read the order
                    # before this transaction is visible.
                    pending_dispatches.append(dict(
                        order_id=order.id,
                        vendor_id=order.vendor_id,
                        customer_id=order.customer_id,
                        lat=order.lat_from,
                        lng=order.lng_from,
                        delivery_fee=float(order.delivery_fee or 0),
                        vehicle_class=order.vehicle_class,
                        vendor_type=vendor_type_str,
                        total_weight_kg=_total_weight,
                        total_quantity=_total_qty,
                        delivery_type=order.delivery_type or "quick_swap",
                        notification_data=snapshot_data,
                    ))

    await session.commit()

    for dispatch_kwargs in pending_dispatches:
        asyncio.create_task(dispatch_order_to_riders(**dispatch_kwargs))

    return {
        "message": "Transaction was completed successfully.",
        "code": "0"
      }

async def annotate_is_rated(session: AsyncSession, orders: list) -> list:
  """Populate `is_rated` on a batch of orders with one extra query.

  A per-order lookup here would be an N+1 on the orders list, which is the most
  frequently loaded screen in the app.
  """
  if not orders:
      return orders

  from models.review_model import Review

  order_ids = [o.id for o in orders if o is not None]
  if not order_ids:
      return orders

  # Which *targets* have been rated, not merely whether any review exists. The
  # customer rates the vendor and the rider as two separate submissions; if the
  # second one failed, treating the order as rated retired the "Rate Delivery"
  # action and the rider could never be rated at all.
  rated_rows = await session.execute(
      select(Review.order_id, Review.target_type)
      .where(Review.order_id.in_(order_ids))
      .distinct()
  )
  rated: dict = {}
  for order_id, target_type in rated_rows.all():
      rated.setdefault(order_id, set()).add(target_type)

  for order in orders:
      if order is None:
          continue
      done = rated.get(order.id, set())
      # A rider is only ratable once one has been assigned.
      expected = {"vendor"} if order.deliverer_id is None else {"vendor", "rider"}
      order.is_rated = expected.issubset(done)
  return orders


async def fetch_orders_by_id(session: AsyncSession, user_id: UUID, skip: int = 0, limit: int = 50) -> list[BaseOrder]:
  query = select(Order).where(Order.customer_id == user_id).options(joinedload(Order.order_item).joinedload(OrderItem.product), joinedload(Order.vendor), joinedload(Order.deliverer)).order_by(Order.created_at.desc()).offset(skip).limit(limit)
  result = await session.execute(query)
  orders = result.unique().scalars().all()
  return await annotate_is_rated(session, list(orders))

async def get_last_completed_order(session: AsyncSession, user_id: UUID) -> BaseOrder | None:
    query = (
        select(Order)
        .where(Order.customer_id == user_id, Order.order_status == "delivered")
        .options(joinedload(Order.order_item).joinedload(OrderItem.product), joinedload(Order.vendor), joinedload(Order.deliverer))
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    result = await session.execute(query)
    order = result.unique().scalar_one_or_none()
    await annotate_is_rated(session, [order] if order else [])
    return order

async def get_active_order(session: AsyncSession, user_id: UUID) -> BaseOrder | None:
    """Fetch the customer's current active order for the home screen banner."""
    query = (
        select(Order)
        .where(
            Order.customer_id == user_id,
            Order.order_status.in_(["pending", "unassigned", "accepted", "preparing", "ready", "picked_up", "mismatch_pending", "pending_review"])
        )
        .options(joinedload(Order.order_item).joinedload(OrderItem.product), joinedload(Order.vendor), joinedload(Order.deliverer))
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    result = await session.execute(query)
    order = result.unique().scalar_one_or_none()
    await annotate_is_rated(session, [order] if order else [])
    return order

async def fetch_order_tracking_logs(session: AsyncSession, order_id: UUID):
    """Fetch historical tracking logs for an order to draw the polyline."""
    from models.order_tracking_log_model import OrderTrackingLog
    query = (
        select(OrderTrackingLog)
        .where(OrderTrackingLog.order_id == order_id)
        .order_by(OrderTrackingLog.created_at.asc())
    )
    result = await session.execute(query)
    return result.scalars().all()

async def cancel_customer_order(session: AsyncSession, user_id: UUID, order_id: UUID):
    """Customer cancels their own order before preparation."""
    from decimal import Decimal

    # Lock the order: two taps on "Cancel" must not restore stock twice.
    order_res = await session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    order = order_res.scalar_one_or_none()
    if not order or order.customer_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")

    # Only allow cancellation for orders that haven't been processed yet
    valid_cancellations = ["pending", "accepted", "unassigned"]
    if order.order_status not in valid_cancellations:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order with status '{order.order_status}'. Only pending, accepted, or unassigned orders can be cancelled."
        )

    was_paid = order.payment_status == "paid"

    # Lock the customer once, up front — the penalty, the wallet restoration and
    # the welcome-offer reset all mutate this row.
    user_res = await session.execute(select(User).where(User.id == user_id).with_for_update())
    user = user_res.scalar_one_or_none()

    # A vendor who has already accepted is likely preparing the order, so a late
    # cancellation carries a KSH 50 fee added to the customer's debt balance.
    if order.order_status == "accepted" and user:
        penalty = Decimal("50.00")
        user.debt_balance = Decimal(str(user.debt_balance or 0)) + penalty
        logger.info("Cancellation penalty of KSH %s applied to user %s", penalty, user_id)

    # Release rider availability if one was already assigned
    if order.deliverer_id:
        deliverer = await session.get(Deliverer, order.deliverer_id)
        if deliverer:
            deliverer.is_available = True

    order.order_status = "cancelled"
    order.cancellation_reason = "cancelled_by_customer"

    # Restore stock
    items_q = select(OrderItem).where(OrderItem.order_id == order.id)
    result = await session.execute(items_q)
    items = result.scalars().all()

    for item in items:
        await session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(
                stock=Product.stock + item.quantity,
                is_available=True
            )
        )

    if user:
        wallet_refund = Decimal(str(order.wallet_discount or 0))
        if wallet_refund > 0:
            from services.wallet_service import apply_wallet_delta
            from models.wallet_transaction_model import TransactionType
            await apply_wallet_delta(
                session,
                owner=user,
                clerk_id=user.clerk_id,
                user_type="customer",
                amount=wallet_refund,
                transaction_type=TransactionType.refund,
                description=f"Wallet credit returned after cancelling order {str(order.id)[:8].upper()}",
                reference_id=str(order.id),
            )
            logger.info("Restored KSH %s to wallet for user %s", wallet_refund, user_id)

        # Only give the welcome offer back if the customer actually paid for the
        # order they are cancelling. Restoring it on a free `pending`/`unassigned`
        # cancellation let the 30% first-order discount be farmed indefinitely.
        if was_paid and (order.is_welcome_offer or Decimal(str(order.welcome_discount or 0)) > 0):
            user.has_used_welcome_offer = False
            logger.info("Reset welcome offer status for user %s (paid order cancelled)", user_id)

    # Flag paid orders for refund and queue the reversal
    if was_paid:
        order.payment_status = "refund_pending"
        # Track the platform revenue lost due to this cancellation
        order.commission_lost = order.platform_total

    # Notify Vendor
    vendor = await session.get(Vendor, order.vendor_id)
    if vendor:
        title = "Order Cancelled ❌"
        body = "Customer has cancelled their order."
        action_url = "/(screens)/Orders"
        await create_notification(
            session=session,
            user_id=vendor.id,
            user_type="vendor",
            title=title,
            message=body,
            message_type="order_cancelled",
            action_url=action_url,
            related_order_id=order.id
        )
        queue_push(session, to=vendor.push_token, title=title, body=body,
                   data={"url": action_url})
    
    # Notify Rider
    if order.deliverer_id:
        deliverer = await session.get(Deliverer, order.deliverer_id)
        if deliverer:
            title = "Delivery Cancelled ❌"
            body = "Customer has cancelled the order you were assigned."
            action_url = "/(screens)/ActiveDelivery"
            await create_notification(
                session=session,
                user_id=deliverer.id,
                user_type="rider",
                title=title,
                message=body,
                message_type="delivery_cancelled",
                action_url=action_url,
                related_order_id=order.id
            )
            queue_push(session, to=deliverer.push_token, title=title, body=body,
                       data={"url": action_url})

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
        logger.error(f"WS Broadcast fail in cancel_customer_order: {e}")

    return {"message": "Order cancelled successfully", "order_id": str(order.id)}


# ── Order Assignment Retry Engine ──────────────────────────────────────────
# Re-assigns orders that have status="unassigned" and no rider after 3+ minutes

async def reassign_unassigned_orders(session: AsyncSession, batch_size: int = 50):
    """Re-offer paid orders that the tiered dispatch engine failed to place.

    Nothing is force-assigned: the order stays `unassigned` and we simply push the
    offer again to every eligible nearby rider, so a rider still has to actively
    accept it.

    Two things were wrong before:
      * it counted an order as "reassigned" merely because *a* rider existed,
        without changing any state — so the log line was fiction;
      * it notified only the single closest rider, which is a much weaker offer
        than the Trip Radar broadcast used on the first attempt.

    Unpaid orders are deliberately excluded: re-broadcasting an order nobody has
    paid for would have riders competing for a trip that may never exist.
    """
    import datetime

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=3)
    stmt = (
        select(Order)
        .where(
            Order.order_status == "unassigned",
            Order.deliverer_id.is_(None),
            Order.payment_status == "paid",
            Order.created_at <= cutoff,
        )
        .order_by(Order.created_at.asc())
        .limit(batch_size)
    )

    result = await session.execute(stmt)
    unassigned_orders = result.scalars().all()

    if not unassigned_orders:
        return {"reassigned": 0, "riders_notified": 0}

    reoffered_count = 0
    riders_notified = 0

    for order in unassigned_orders:
        lat_from = order.lat_from or 0.0
        lng_from = order.lng_from or 0.0

        vendor = await session.get(Vendor, order.vendor_id)
        vendor_type_str = "retail_refill"
        if vendor is not None and vendor.vendor_type is not None:
            vendor_type_str = (
                vendor.vendor_type.value if hasattr(vendor.vendor_type, "value") else str(vendor.vendor_type)
            )

        radar_riders = await get_radar_deliverers(
            session=session,
            lat=lat_from,
            lng=lng_from,
            vendor_id=None,
            vehicle_class=order.vehicle_class or "motorbike",
            vendor_type=vendor_type_str,
        )
        if not radar_riders:
            logger.info("Re-offer: still no eligible riders for order %s", order.id)
            continue

        title = "New Delivery Nearby! 📦"
        body = (
            f"Ksh {order.delivery_fee or 0:.0f} fee | "
            f"{order.delivery_type or 'quick_swap'} | "
            f"{order.distance_km or 0:.1f}km | "
            f"{order.vehicle_class or 'motorbike'}. Tap to view and accept."
        )
        action_url = "/(screens)/TripRadar"

        rider_ids: list[str] = []
        for rider_obj, push_token, uid in radar_riders:
            rider_ids.append(str(uid))
            await create_notification(
                session=session,
                user_id=uid,
                user_type="rider",
                title=title,
                message=body,
                message_type="new_delivery",
                action_url=action_url,
                related_order_id=order.id,
            )
            queue_push(session, to=push_token, title=title, body=body,
                       data={"url": action_url})

        riders_notified += len(rider_ids)
        reoffered_count += 1

        try:
            from routes.websocket_routes import manager
            await manager.broadcast_to_riders(
                rider_ids=rider_ids,
                payload={
                    "action": "TRIP_RADAR_BROADCAST",
                    "order_id": str(order.id),
                    "fee": float(order.delivery_fee or 0),
                    "tier": 3,  # 3 = re-offer sweep
                    "delivery_type": order.delivery_type or "quick_swap",
                    "distance_km": order.distance_km,
                    "lat_from": order.lat_from,
                    "lng_from": order.lng_from,
                    "lat": order.lat,
                    "lng": order.lng,
                }
            )
        except Exception as e:
            logger.error(f"WS broadcast fail in reassign: {e}")

    await session.commit()
    logger.info(
        "Re-offered %s unassigned order(s) to %s rider slot(s)", reoffered_count, riders_notified
    )
    return {"reassigned": reoffered_count, "riders_notified": riders_notified}

# ── C-03 FIX: Mismatch Resolution Logic ────────────────────────────────────

async def resolve_address_mismatch(session: AsyncSession, user_id: UUID, order_id: UUID, action: str):
    """
    Handles customer response to a rider flagging an address mismatch.
    action: "approve_charge" | "leave_ground"
    """
    order = await session.get(Order, order_id)
    if not order or order.customer_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.order_status != "mismatch_pending":
        raise HTTPException(status_code=400, detail="Order is not in mismatch state")

    if action == "approve_charge":
        # Customer accepts the KSh 30 staircase charge
        charge = 30.0
        order.staircase_surcharge = float(order.staircase_surcharge or 0) + charge
        order.total_amount = float(order.total_amount or 0) + charge
        
        # Add to customer's debt balance since M-PESA already processed the original total
        user = await session.get(User, user_id)
        if user:
            user.debt_balance = float(user.debt_balance or 0) + charge
        
        # Determine rider payout vs platform based on employment type
        # For gig economy riders, they keep 100% of the surcharge
        # For in-house, it goes to the vendor/platform
        deliverer = await session.get(Deliverer, order.deliverer_id) if order.deliverer_id else None
        if deliverer and deliverer.employment_model == "gig_economy":
            order.rider_net = float(order.rider_net or 0) + charge
        else:
            order.vendor_net = float(order.vendor_net or 0) + charge

    elif action == "leave_ground":
        # No extra charge, rider leaves at ground floor
        pass
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    # Transition back to picked_up so rider can complete delivery
    order.order_status = "picked_up"
    await session.commit()

    # Notify Rider
    if order.deliverer_id:
        title = "Mismatch Resolved ✅"
        body = "Customer approved the staircase charge. Proceed up." if action == "approve_charge" else "Customer requested drop-off at ground floor."
        await create_notification(
            session=session,
            user_id=order.deliverer_id,
            user_type="rider",
            title=title,
            message=body,
            message_type="mismatch_resolved",
            action_url="/(screens)/ActiveDelivery"
        )
        
        # Broadcast to rider app
        try:
            from routes.websocket_routes import manager
            await manager.broadcast_order_update(
                vendor_id=str(order.vendor_id),
                customer_id=str(order.customer_id),
                deliverer_id=str(order.deliverer_id),
                payload={
                    "action": "MISMATCH_RESOLVED",
                    "order_id": str(order.id),
                    "status": "picked_up",
                    "resolution": action
                }
            )
        except Exception as e:
            logger.error(f"WS Broadcast fail in resolve_mismatch: {e}")

    return {"message": "Mismatch resolved successfully", "order": {"id": str(order.id), "status": order.order_status, "total_amount": order.total_amount}}