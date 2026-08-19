import logging
import math
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from sqlalchemy import select, and_, func, update
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from geoalchemy2.functions import ST_Distance, ST_DWithin
from models.cart_model import CartItem
from models.deliverer_model import Deliverer, dispatchable_rider
from models.product_model import Product
from models.order_model import Order, OrderItem
from models.vendor_model import Vendor
from models.user_model import User
from schemas.order_schema import BaseOrder
from utils.money import MoneyIn, money_str
from services.notification_service import create_notification, push_allowed, queue_push
from services.dispatch_policy import DispatchPolicy
import asyncio
from utils.paging import stable

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

#: Statuses in which an order is still live — goods, money or a delivery are
#: outstanding. Anything not here is finished (`delivered`, `cancelled`,
#: `rejected`) or not yet real (`pending` awaiting payment is handled per caller).
#:
#: Account deletion reads this. It used to inline
#: `["pending", "confirmed", "preparing", "out_for_delivery"]` — two of which are
#: not statuses this platform has ever used — against `Order.status`, a column
#: that does not exist either (`order_status` does). The query raised
#: AttributeError before it could run, so "delete my account" answered 500 for
#: every user type, and the guard it was supposed to provide never existed.
ACTIVE_ORDER_STATUSES = (
    OrderStatusEnum.UNASSIGNED.value,
    OrderStatusEnum.ACCEPTED.value,
    OrderStatusEnum.PREPARING.value,
    OrderStatusEnum.READY.value,
    OrderStatusEnum.PICKED_UP.value,
    OrderStatusEnum.PENDING_REVIEW.value,
    OrderStatusEnum.MISMATCH_PENDING.value,
)

#: An order actually out with a rider. Narrower than the above: a rider may close
#: their account with orders sitting at the vendor, but not mid-delivery.
IN_FLIGHT_DELIVERY_STATUSES = (
    OrderStatusEnum.PICKED_UP.value,
    OrderStatusEnum.READY.value,
    OrderStatusEnum.PENDING_REVIEW.value,
    OrderStatusEnum.MISMATCH_PENDING.value,
)


# ── The order state machine ───────────────────────────────────────────────
#
# `from_status -> the statuses it may legitimately become`.
#
# This table used to describe an *idealised* flow that six of the eight places
# writing `order_status` did not follow — and the two that did enforce it were
# enforcing a shape the platform does not have. A rider marking an order picked
# up straight from `accepted` (the store handed it over before tapping "ready"),
# a rider dropping an order after pickup, the cash-float sweep releasing an
# order back to `unassigned`: all real, all routine, none of them in the table.
#
# A table that contradicts the code is worse than no table. It reads as
# documentation, so the next person either trusts it — and is wrong about how
# their own feature behaves — or "fixes" the six paths to match it and breaks
# the rider flow.
#
# So this now describes what actually happens. What it still buys, and the
# reason it is enforced at all:
#
#   * **Terminal is terminal.** `delivered`, `cancelled` and `rejected` move
#     nowhere. Money has settled, stock has moved, and the customer has been
#     charged or refunded — an order that changes after that is one whose
#     ledger no longer matches its state.
#   * **No going backwards.** `delivered → preparing` is not a slow update
#     arriving late, it is a bug, and it silently un-completes a delivery.
#
# Per-*caller* rules stay with the caller: whether **this** rider may mark
# **this** order picked up is a question about the rider, not about the graph.
VALID_TRANSITIONS = {
    # Awaiting the vendor. A rider may already be attached — `unassigned →
    # pending` is what claiming an order means — so pickup and delivery are
    # reachable from here when a store hands over before tapping through.
    OrderStatusEnum.PENDING: {
        OrderStatusEnum.ACCEPTED, OrderStatusEnum.REJECTED, OrderStatusEnum.CANCELLED,
        OrderStatusEnum.UNASSIGNED, OrderStatusEnum.PREPARING, OrderStatusEnum.PICKED_UP,
        OrderStatusEnum.DELIVERED, OrderStatusEnum.PENDING_REVIEW,
        OrderStatusEnum.MISMATCH_PENDING,
    },
    # Paid and on the radar, with no rider yet.
    OrderStatusEnum.UNASSIGNED: {OrderStatusEnum.PENDING, OrderStatusEnum.CANCELLED},
    OrderStatusEnum.ACCEPTED: {
        OrderStatusEnum.PREPARING, OrderStatusEnum.CANCELLED, OrderStatusEnum.UNASSIGNED,
        OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED,
        OrderStatusEnum.PENDING_REVIEW, OrderStatusEnum.MISMATCH_PENDING,
    },
    OrderStatusEnum.PREPARING: {
        OrderStatusEnum.READY, OrderStatusEnum.CANCELLED, OrderStatusEnum.UNASSIGNED,
        OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED,
        OrderStatusEnum.PENDING_REVIEW, OrderStatusEnum.MISMATCH_PENDING,
    },
    # Packed and waiting. A rider may still drop it, and support may still
    # cancel it; the vendor may not, and that is enforced by the vendor route's
    # own list of statuses rather than here.
    OrderStatusEnum.READY: {
        OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED,
        OrderStatusEnum.UNASSIGNED, OrderStatusEnum.CANCELLED,
        OrderStatusEnum.PENDING_REVIEW, OrderStatusEnum.MISMATCH_PENDING,
    },
    # On the bike. `cancelled` is reachable: a rider whose vehicle fails after
    # pickup drops the order, and `revert_order_side_effects` undoes it.
    OrderStatusEnum.PICKED_UP: {
        OrderStatusEnum.DELIVERED, OrderStatusEnum.PENDING_REVIEW,
        OrderStatusEnum.MISMATCH_PENDING, OrderStatusEnum.CANCELLED,
    },
    # The two paused states. Both resume rather than terminate, and both can
    # still be cancelled by support while a human decides.
    OrderStatusEnum.PENDING_REVIEW: {
        OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED, OrderStatusEnum.CANCELLED,
    },
    OrderStatusEnum.MISMATCH_PENDING: {
        OrderStatusEnum.PICKED_UP, OrderStatusEnum.DELIVERED, OrderStatusEnum.CANCELLED,
    },
    OrderStatusEnum.DELIVERED: set(),
    OrderStatusEnum.CANCELLED: set(),
    OrderStatusEnum.REJECTED: set(),
}

#: Nothing moves out of these. Money has settled and stock has moved.
TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatusEnum.DELIVERED.value,
        OrderStatusEnum.CANCELLED.value,
        OrderStatusEnum.REJECTED.value,
    }
)


def validate_status_transition(current: str, new: str) -> bool:
    """True if the state machine permits `current -> new`."""
    try:
        current_enum = OrderStatusEnum(current)
        new_enum = OrderStatusEnum(new)
    except ValueError:
        return False
    return new_enum in VALID_TRANSITIONS.get(current_enum, set())


def apply_status_transition(order, new_status: str, *, reason: str | None = None) -> str:
    """Move an order to `new_status`, or refuse.

    **The only place `order_status` is assigned.** It was assigned directly in
    twelve places across six modules, each with its own idea of what was legal,
    and two of those consulted a table that disagreed with the other ten. A
    guard that most writers skip is not a guard — it is a comment that runs.

    Raises 409 rather than 400: the caller's request was well-formed, the order
    had simply moved on. That distinction matters to a rider whose tap raced the
    vendor's, and to a client deciding whether retrying is worth anything.

    Returns the status the order was in before, so callers that need to undo
    something conditionally do not have to read it first.
    """
    previous = order.order_status
    if previous == new_status:
        return previous

    if not validate_status_transition(previous, new_status):
        detail = (
            f"This order is already {previous} and cannot be changed."
            if previous in TERMINAL_ORDER_STATUSES
            else f"An order cannot go from '{previous}' to '{new_status}'."
        )
        raise HTTPException(status_code=409, detail=detail)

    order.order_status = new_status
    if reason is not None:
        order.cancellation_reason = reason
    return previous


# ── Revenue splits ────────────────────────────────────────────────────────
#
# These were module constants. They are now rows in `Platform_Settings`, so the
# owners can change the business model from the admin console and have it live
# in all three apps on the next quote — the apps render the server's quote
# verbatim, so nothing ships to a client.
#
# The names below are kept as *module attributes* via `__getattr__` at the
# bottom of this section, because several modules and tests do
# `from services.order_service import SURGE_FEE_KSH`. Each such lookup now reads
# the live configuration rather than a value frozen at import.
#
# Anything inside this module must call `_config.get_decimal(...)` directly:
# module-level `__getattr__` is only consulted for attribute access *on the
# module object*, never for a bare global name inside one of its own functions.

from services import platform_config_service as _config

#: Legacy constant name -> configuration key.
_LEGACY_SETTING_NAMES = {
    "RETAIL_VENDOR_COMMISSION": "retail_vendor_commission_rate",
    "WHOLESALE_VENDOR_COMMISSION": "wholesale_vendor_commission_rate",
    "RETAIL_SERVICE_FEE_KSH": "retail_service_fee",
    "WHOLESALE_SERVICE_FEE_KSH": "wholesale_service_fee",
    "GIG_RIDER_COMMISSION": "gig_rider_commission_rate",
    "GIG_PLATINUM_COMMISSION": "gig_platinum_rider_commission_rate",
    "IN_HOUSE_RIDER_COMMISSION": "in_house_rider_commission_rate",
    "WHOLESALE_DELIVERY_MARKUP": "wholesale_delivery_markup_rate",
    "SURGE_FEE_KSH": "surge_fee",
    "PEAK_HOURS": "peak_hours",
}


def __getattr__(name: str):
    """Resolve the retired pricing constants against the live configuration."""
    key = _LEGACY_SETTING_NAMES.get(name)
    if key is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return _config.get(key)


NAIROBI_TZ_OFFSET_HOURS = 3  # EAT = UTC+3, no DST


def is_surge_active(now=None) -> bool:
    """Is the current East Africa Time inside a configured peak window?

    `now` is injectable so the surge windows can be asserted deterministically
    instead of only when the suite happens to run at 07:00 or 18:00.

    An empty window list switches surge off, which is the honest way to disable
    it — setting the fee to zero would still mark the order as surged.
    """
    from datetime import datetime, timezone, timedelta

    nairobi_tz = timezone(timedelta(hours=NAIROBI_TZ_OFFSET_HOURS))
    moment = now.astimezone(nairobi_tz) if now is not None else datetime.now(nairobi_tz)
    current_hour = moment.hour
    return any(start <= current_hour < end for start, end in _config.get("peak_hours"))

def _haversine_km(lat_from: float, lng_from: float, lat_to: float, lng_to: float) -> float:
    """Pure Haversine distance in km between two GPS points."""
    d_lat = math.radians(lat_to - lat_from)
    d_lng = math.radians(lng_to - lng_from)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat_from)) * math.cos(math.radians(lat_to)) *
         math.sin(d_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(EARTH_RADIUS_KM * c, 2)


def calculate_delivery_fee(
    lat_from: float, lng_from: float,
    lat_to: float, lng_to: float,
    vendor_type: str = "retail_refill",
    vehicle_class: str = "motorbike",
    wholesale_base: MoneyIn = 0,
    wholesale_per_km: MoneyIn = 0,
    delivery_type: str = "quick_swap"
) -> dict:
    """`{ 'distance_km': float, 'fee': Decimal, 'estimated_minutes': int, 'vehicle_class': str }`

    The fee is `Decimal` — it is money. The distance is `float` and stays one:
    it is a measurement, and nothing is charged per metre.
    """
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
    product_total: MoneyIn,
    delivery_fee: MoneyIn,
    vendor_type: str = "retail_refill",
    bottle_deposit: MoneyIn = 0,
    rider_surcharges: MoneyIn = 0,
    delivery_type: str = "quick_swap",
    welcome_discount: MoneyIn = 0,
    debt_settlement: MoneyIn = 0,
    payment_method: str = "mpesa",
) -> dict[str, Decimal]:
    """Calculate platform revenue splits for a single order.
    FIN-01 FIX: Uses Decimal for currency precision to prevent ledger drift.
    Takes and returns `Decimal` — anything `Decimal(str(...))` accepts goes in.
    Returns { 'vendor_commission', 'service_fee', 'rider_commission', 'platform_total',
              'vendor_net', 'rider_net', 'surge_fee', 'delivery_markup' }

    The three components sum to the order's gross by construction:

        vendor_net + rider_net + platform_total == gross_before_discounts − welcome_discount

    `delivery_markup` is taken **out of** the delivery fee, not added beside it,
    so the fee the customer is shown is the fee they pay. It used to be additive
    on wholesale: the cart rendered `delivery_fee` and charged
    `delivery_fee + markup`, so the line item understated itself.

    `platform_cost` sits outside that identity on purpose — it is money that
    never reaches the platform (Safaricom's tariff, or the cost of handling
    cash), not a share of what the customer paid. `platform_net` is the figure
    the business actually keeps.

    A test asserts that identity across every combination of vendor type,
    delivery type and surcharge, because a split that does not add up is money
    the platform either invents or loses without anybody noticing.
    """
    from decimal import Decimal, ROUND_HALF_UP

    # Convert all inputs to Decimal
    _pt = Decimal(str(product_total))
    _df = Decimal(str(delivery_fee))
    _bd = Decimal(str(bottle_deposit))
    _rs = Decimal(str(rider_surcharges))
    _wd = Decimal(str(welcome_discount))
    _ds = Decimal(str(debt_settlement))

    TWO = Decimal("0.01")

    # ── Vendor Commission ──
    # Every rate here is read from the live platform configuration. Reads are
    # synchronous; the caller has already awaited `ensure_fresh`, which is also
    # what makes one quote internally consistent — the configuration cannot move
    # between two lines of this function.
    if vendor_type == "wholesale_b2b":
        vendor_commission = (_pt * _config.get_decimal("wholesale_vendor_commission_rate")).quantize(TWO, rounding=ROUND_HALF_UP)
        service_fee = _config.get_decimal("wholesale_service_fee")
    else:
        vendor_commission = (_pt * _config.get_decimal("retail_vendor_commission_rate")).quantize(TWO, rounding=ROUND_HALF_UP)
        service_fee = _config.get_decimal("retail_service_fee")

    # ── Rider Commission (Gig only; wholesale in-house is exempt) ──
    if vendor_type == "wholesale_b2b":
        rider_commission = Decimal("0.00")
    else:
        # keep_my_bottle carries a premium for the extra bottle handling.
        from services import delivery_types

        commission_rate = _config.get_decimal("gig_rider_commission_rate")
        if delivery_types.is_round_trip(delivery_type):
            commission_rate += _config.get_decimal("refill_mine_commission_premium")
        rider_commission = (_df * commission_rate).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── Delivery Markup ──
    # Platform margin taken *inside* the delivery fee rather than added beside
    # it. Retail had none: on the side of the business with a rider to pay, cash
    # to police and the thinnest basket, the platform's entire margin was a flat
    # service fee and a percentage of one bottle of water.
    markup_key = (
        "wholesale_delivery_markup_rate" if vendor_type == "wholesale_b2b"
        else "retail_delivery_markup_rate"
    )
    delivery_markup = (_df * _config.get_decimal(markup_key)).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── Surge Pricing ──
    surge_fee = _config.get_decimal("surge_fee") if is_surge_active() else Decimal("0.00")

    # ── Platform Total Revenue ──
    # Platform absorbs the welcome discount as a customer acquisition cost, and
    # recovers any debt this order is settling — a cancellation penalty or an
    # approved staircase charge the platform already fronted to whoever earned it.
    platform_total = (
        vendor_commission + service_fee + rider_commission + delivery_markup
        + surge_fee - _wd + _ds
    ).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── Net Payouts ──
    # Wholesale vendors get the delivery fee back, because they own the fleet —
    # and the payload and staircase surcharges with it, for the same reason. Those
    # surcharges pay for carrying and climbing; on retail the gig rider does that
    # work and is paid directly, on wholesale it is the vendor's own employee.
    #
    # They previously landed in `rider_net` on wholesale orders too, on a
    # settlement path that never credits a wholesale rider — so the customer was
    # charged for them and nobody was ever paid, while `platform_total`
    # understated what the platform had actually retained. `rider_net` is now
    # zero on wholesale, which is what the settlement path has always assumed.
    if vendor_type == "wholesale_b2b":
        vendor_net = (_pt - vendor_commission + _df - delivery_markup + _bd + _rs).quantize(TWO, rounding=ROUND_HALF_UP)
        rider_net = Decimal("0.00")
    else:
        vendor_net = (_pt - vendor_commission + _bd).quantize(TWO, rounding=ROUND_HALF_UP)
        rider_net = (_df - rider_commission - delivery_markup + _rs).quantize(TWO, rounding=ROUND_HALF_UP)

    # ── What the order actually costs the platform ──
    # Safaricom charges the business on collection, and a cash order costs
    # reconciliation and float risk instead. Neither was modelled anywhere, so
    # every margin figure on the console was gross dressed up as net — on a
    # KSH 442 order the M-Pesa tariff alone is a large share of the whole cut.
    #
    # Deliberately **outside** the split identity: this is money that never
    # reaches the platform, not a share of what the customer paid. The three
    # nets still sum to the gross; `platform_net` is what is left afterwards.
    if payment_method == "cash":
        platform_cost = _config.get_decimal("cash_handling_cost")
    else:
        platform_cost = _config.get_decimal("mpesa_collection_cost")
    platform_cost = platform_cost.quantize(TWO, rounding=ROUND_HALF_UP)
    platform_net = (platform_total - platform_cost).quantize(TWO, rounding=ROUND_HALF_UP)

    # `Decimal`, not `float`. Every one of these is written to a `Numeric(10, 2)`
    # column and read back into the order's frozen breakdown, and every caller
    # was wrapping the result straight back up in `Decimal(str(...))` — a float
    # round trip in the middle of the one path that decides what a vendor, a
    # rider and the platform are each owed.
    return {
        "vendor_commission": vendor_commission,
        "service_fee": service_fee,
        "rider_commission": rider_commission,
        "platform_total": platform_total,
        "platform_cost": platform_cost,
        "platform_net": platform_net,
        "vendor_net": vendor_net,
        "rider_net": rider_net,
        "surge_fee": surge_fee,
        "delivery_markup": delivery_markup,
    }


#: How many riders one radar sweep may return.
#:
#: `get_radar_deliverers` had no ceiling at all, so in a dense market it
#: materialised every available rider inside the ring — the whole of central
#: Nairobi's fleet — and pushed to all of them. Beyond a couple of dozen the extra
#: riders add nothing: the order is claimed by whoever taps first, and the rest
#: get a notification for an order that is already gone, which is the surest way
#: to teach a rider to stop opening them. Ordered by distance, so the ceiling
#: keeps the *nearest* riders rather than an arbitrary page.
RADAR_FANOUT_LIMIT = 25


def rider_search_bounds(lat: float, lng: float, vendor_type: str):
    """`(pickup_point, h3_cells, max_distance_m)` for a rider search.

    The one definition of "near this pickup". Every dispatch tier uses it, so a
    change to the radius or the ring cannot reach two of the three and leave the
    highest-priority one looking somewhere else.
    """
    import h3
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    max_distance_m = DispatchPolicy.get_max_distance_m(vendor_type, action="rider_search")
    centre = h3.latlng_to_cell(lat, lng, 8)
    ring = DispatchPolicy.get_h3_k_ring(vendor_type)
    cells = [str(cell) for cell in h3.grid_disk(centre, ring)]
    return from_shape(Point(lng, lat), srid=4326), cells, max_distance_m


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
          *dispatchable_rider(),
          Deliverer.employment_model == "gig_economy",  # Tier 2 is restricted to Gig-Economy
          Deliverer.vehicle_type == vehicle_enum, 
          Deliverer.h3_index_res8.in_(nearby_hexes),
          Deliverer.location.isnot(None),
          # `ST_DWithin`, never `ST_Distance(...) <= x`. The first is
          # index-assisted and can use `idx_deliverer_location_gist`; the second
          # forces the distance to be computed for every row the H3 pre-filter
          # let through before any of them can be discarded. The H3 ring bounds
          # that today, but a res-8 k-ring covers a wide area of a dense city.
          ST_DWithin(Deliverer.location, pickup_point, max_distance_m),
      )
  ).order_by(ST_Distance(Deliverer.location, pickup_point)).limit(RADAR_FANOUT_LIMIT)
  
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
              *dispatchable_rider(),
              Deliverer.vehicle_type == vehicle_enum,
              Deliverer.h3_index_res8.in_(nearby_hexes),
              Deliverer.location.isnot(None),
              # Index-assisted; see the fallback below for the full reasoning.
              ST_DWithin(Deliverer.location, pickup_point, max_distance_m),
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

  # Step 2: Fallback — drop the H3 pre-filter, keep the radius.
  #
  # The H3 ring is an approximation of a disk, so a rider very near the boundary
  # can sit in a cell the ring does not cover while still being inside the true
  # radius. This second pass catches them, and is the only reason it exists.
  #
  # It is bounded by `ST_DWithin`, not by `ST_Distance <= …` as it was. That
  # distinction is the whole point: `ST_DWithin` is index-assisted and can use
  # the GiST index on `Deliverer.location`, whereas comparing a computed
  # `ST_Distance` forces the distance to be evaluated for **every rider row on
  # the platform** before anything can be discarded. On this dataset that is
  # invisible; at ten thousand riders it is a sequential scan on every dispatch
  # that finds nobody nearby — which is precisely when it runs.
  fallback_query = (
      select(Deliverer)
      .where(
          and_(
              *dispatchable_rider(),
              Deliverer.vehicle_type == vehicle_enum,
              Deliverer.location.isnot(None),
              ST_DWithin(Deliverer.location, pickup_point, max_distance_m),
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

            # Up to 10 pre-approved riders for this vendor, matching vehicle type,
            # who are actually near the pickup — nearest first.
            #
            # This query previously carried **no geographic predicate at all**.
            # Registration is radius-bounded, so a rider's *operating base* is
            # near the store, but `is_available` says nothing about where they
            # are right now: a rider registered in Ngong and currently in Mombasa
            # received the push. Tiers 2 and 3 both filter on distance; the one
            # tier that did not was the first and strongest offer the platform
            # sends. `rider_search_bounds` is the same helper they use.
            pickup_point, nearby_hexes, max_distance_m = rider_search_bounds(
                lat, lng, vendor_type
            )

            tier1_conditions = [
                VendorRiderRegistry.vendor_id == vendor_id,
                VendorRiderRegistry.status == "approved",
                # Approved *by the store* is not the same as in good standing
                # with the platform. A rider the store trusts is still one the
                # platform may have suspended, and this is the first and
                # strongest offer sent on every dispatch.
                *dispatchable_rider(),
                Deliverer.vehicle_type == vehicle_enum,
                Deliverer.h3_index_res8.in_(nearby_hexes),
                Deliverer.location.isnot(None),
            ]
            if max_distance_m is not None:
                # `ST_DWithin`, for the same reason as the other two search
                # paths: this one runs first and on every single dispatch.
                tier1_conditions.append(
                    ST_DWithin(Deliverer.location, pickup_point, max_distance_m)
                )

            tier1_query = (
                select(Deliverer, Deliverer.push_token, Deliverer.id.label("user_id"))
                .join(VendorRiderRegistry, VendorRiderRegistry.rider_id == Deliverer.id)
                .where(and_(*tier1_conditions))
                .order_by(ST_Distance(Deliverer.location, pickup_point))
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
                            "vendor_net": money_str(order.vendor_net),
                            "platform_total": money_str(order.platform_total),
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

    # ── ESCALATE TO TIER 2 AFTER THE TIMEOUT ───────────────────────────
    # If Wholesale B2B, DO NOT broadcast to Trip Radar (Gig-Economy bypassed)
    if vendor_type == "wholesale_b2b":
        logger.info(f"Dispatch Tier 2: Bypassing Trip Radar for Wholesale Order {order_id}")
        return

    # Hand the wait to ARQ rather than sleeping in this process.
    #
    # This function runs as a background task inside the API. A twenty-second
    # `asyncio.sleep` here means a deploy, a Render restart or a scale-down
    # during the window kills the escalation outright: Tier 2 never fires, and
    # the order is only rescued by the three-minute re-offer sweep. The customer
    # waits three minutes for something that should have taken twenty seconds.
    #
    # `_defer_by` puts the escalation in Redis, where a restart cannot lose it,
    # and `_job_id` keyed on the order makes a duplicate enqueue a no-op — ARQ
    # refuses a job whose id matches one already queued.
    scheduled = await _schedule_trip_radar(
        order_id=order_id,
        vendor_id=vendor_id,
        customer_id=customer_id,
        lat=lat,
        lng=lng,
        delivery_fee=delivery_fee,
        vehicle_class=vehicle_class,
        vendor_type=vendor_type,
        total_weight_kg=total_weight_kg,
        total_quantity=total_quantity,
        delivery_type=delivery_type,
        notification_data=notification_data,
    )
    if scheduled:
        return

    # No queue reachable — a single-process dev machine, or Redis is down. Fall
    # back to the in-process wait so dispatch still escalates locally.
    logger.warning(
        "Dispatch Tier 2 for order %s could not be queued; falling back to an "
        "in-process wait. This will not survive a restart.",
        order_id,
    )
    await asyncio.sleep(DISPATCH_TIER1_TIMEOUT_SECONDS)
    await broadcast_trip_radar(
        order_id=order_id,
        lat=lat,
        lng=lng,
        delivery_fee=delivery_fee,
        vehicle_class=vehicle_class,
        vendor_type=vendor_type,
        total_weight_kg=total_weight_kg,
        total_quantity=total_quantity,
        delivery_type=delivery_type,
        notification_data=notification_data,
    )


async def _schedule_trip_radar(*, order_id, **kwargs) -> bool:
    """Queue the Tier 2 broadcast for `DISPATCH_TIER1_TIMEOUT_SECONDS` from now.

    Returns False when no queue is reachable, so the caller can fall back.
    """
    try:
        from core.redis_client import get_arq_pool

        pool = await get_arq_pool()
        if pool is None:
            return False

        job = await pool.enqueue_job(
            "dispatch_trip_radar_task",
            str(order_id),
            kwargs,
            _job_id=f"trip_radar:{order_id}",
            _defer_by=timedelta(seconds=DISPATCH_TIER1_TIMEOUT_SECONDS),
        )
        # `enqueue_job` returns None when a job with this id already exists.
        if job is None:
            logger.info("Trip Radar for order %s is already queued", order_id)
        return True
    except Exception as exc:
        logger.error("Could not queue Trip Radar for order %s: %s", order_id, exc)
        return False


async def broadcast_trip_radar(
    *,
    order_id: UUID,
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
    """Tier 2 — offer the trip to every eligible rider nearby, vendor-approved or not.

    Split out of `dispatch_order_to_riders` so it can be reached from the ARQ
    worker as well as in-process. Re-checks the order under its own session, so
    an order claimed during the wait is never re-broadcast.
    """
    from dependencies.dependencies import get_db_session

    if vendor_type == "wholesale_b2b":
        logger.info("Trip Radar: wholesale order %s is not broadcast", order_id)
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
                            "vendor_net": money_str(order.vendor_net),
                            "platform_total": money_str(order.platform_total),
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
  from services.vendor_staff_service import is_store_member

  if await is_store_member(session, user.clerk_id, vendor):
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
          payment_method=payment_method,
      )
  elif quote.wallet_discount > locked_balance:
      # The balance moved between pricing and creation (a concurrent order or
      # withdrawal). Refuse rather than silently charging a different amount than
      # the one already pushed to the customer's phone.
      raise HTTPException(
          status_code=409,
          detail="Your wallet balance changed while checking out. Please review your cart and try again.",
      )

  # Re-run every gate under the lock — stock, debt and the store's own opening
  # state can all move between pricing and creation even though the cart itself
  # is locked. This is the last check before an order exists, and it is the one
  # that has to hold: everything after it is a refund.
  validate_quote(quote, pre_order_items, user=user, vendor=vendor)

  from services import vendor_availability

  await vendor_availability.assert_store_accepting(session, vendor)

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
      # `Numeric(10, 2)`, so the `Decimal` goes in as it is. Every other money
      # column on this row is written straight from the quote; this one was
      # cast to `float` on the way past, on the order the rider is paid from.
      delivery_fee=quote.delivery_fee,

      # ── Surcharges ──
      staircase_surcharge=quote.staircase_surcharge,
      payload_surcharge=quote.payload_surcharge,

      # ── Revenue Split Ledger ──
      vendor_commission=revenue["vendor_commission"],
      service_fee=revenue["service_fee"],
      rider_commission=revenue["rider_commission"],
      platform_total=revenue["platform_total"],
      # What this order cost the platform to process, and what survived it.
      # Frozen here like every other split: changing the tariff setting tomorrow
      # must not restate what yesterday's orders earned.
      platform_cost=revenue["platform_cost"],
      platform_net=revenue["platform_net"],
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
      # Every money figure the quote published, without exception. These last
      # two were applied to what the customer paid and frozen onto nothing, so
      # the order could not be reconciled against its own total.
      wallet_discount=quote.wallet_discount,
      welcome_discount=quote.welcome_discount,
      product_subtotal=quote.product_subtotal,
      mpesa_discount=quote.mpesa_discount,
      rounding_adjustment=quote.rounding_adjustment,

      # ── Deposits and debt ──
      bottle_deposit=quote.bottle_deposit,
      debt_settlement=quote.debt_settlement,
  )
  session.add(order)
  await session.flush()

  # ── Settle any debt this order is collecting ───────────────────────────────
  # The customer has just been charged it as a line item, so it stops being
  # owed. Restored by the cancellation paths, which refund them the same amount.
  if quote.debt_settlement > 0:
      user.debt_balance = max(
          Decimal("0.00"),
          Decimal(str(user.debt_balance or 0)) - quote.debt_settlement,
      )
      logger.info(
          "Cleared KSH %s of debt for user %s on order %s",
          quote.debt_settlement, user_id, order.id,
      )

  # ── Record the deposit as a liability to the customer ──────────────────────
  # The money itself is paid out to the vendor in `vendor_net`. This is the
  # other side of that entry: what the platform owes back, and how many bottles
  # it covers.
  if quote.bottle_deposit > 0:
      from services import customer_bottle_service

      await customer_bottle_service.accrue_deposit(
          session,
          user=user,
          amount=quote.bottle_deposit,
          bottles=customer_bottle_service.bottles_in(pre_order_items),
          order_id=order.id,
      )

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
          .returning(
              Product.id,
              Product.stock,
              Product.name,
              Product.vendor_id,
              Product.low_stock_threshold,
              Product.low_stock_notified_at,
          )
      )
      updated_row = result.fetchone()
      if not updated_row:
          raise HTTPException(
              status_code=400,
              detail="Insufficient stock for product (concurrent purchase detected). Please refresh and try again."
          )

      (
          product_id_for_stock,
          new_stock,
          product_name,
          vendor_id_for_push,
          low_stock_threshold,
          low_stock_notified_at,
      ) = updated_row

      await _warn_if_low_stock(
          session,
          product_id=product_id_for_stock,
          product_name=product_name,
          vendor_id=vendor_id_for_push,
          new_stock=new_stock,
          threshold=low_stock_threshold,
          already_notified_at=low_stock_notified_at,
      )

  await session.commit()
  return order

async def _warn_if_low_stock(
    session: AsyncSession,
    *,
    product_id,
    product_name: str,
    vendor_id,
    new_stock: int,
    threshold: int | None,
    already_notified_at,
):
    """Tell the vendor once when a product crosses its low-stock line.

    Three things were wrong with the version this replaces:

    * The threshold was hardcoded to 5 for every product on the platform. A shop
      selling 200 refills a day and one selling a dispenser a month cannot share
      a number, so `Product.low_stock_threshold` is per product (0 disables it).
    * It fired on *every* order once stock was below the line, so the last five
      sales of a product produced five identical pushes. `low_stock_notified_at`
      makes it one per crossing, cleared when stock is replenished back above it.
    * `action_url` was `/(screens)/Inventory`, a screen that does not exist in
      the vendor app. Tapping the notification went nowhere.

    Staff are notified too — they are the ones on the floor who notice the empty
    pallet — but only those who may actually restock. Telling someone about a
    problem they have no permission to fix is noise.
    """
    from datetime import datetime, timezone

    if not threshold or new_stock > threshold:
        return
    if already_notified_at is not None:
        # Still below the line from an earlier crossing; `restock` clears this.
        return

    vendor = await session.get(Vendor, vendor_id)
    if not vendor:
        return

    await session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(low_stock_notified_at=datetime.now(timezone.utc))
    )

    title = "Low stock ⚠️"
    body = (
        f"'{product_name}' is out of stock — customers can't order it."
        if new_stock == 0
        else f"'{product_name}' is down to {new_stock}. Restock soon."
    )
    action_url = "/(screens)/Products"

    await create_notification(
        session=session,
        user_id=vendor.id,
        user_type="vendor",
        title=title,
        message=body,
        message_type="low_stock",
        action_url=action_url,
    )
    # `queue_push`, not `dispatch_background`: the stock decrement above has not
    # committed yet, and a rolled-back order must not have told anyone anything.
    from models.vendor_staff_model import PERMISSION_MANAGE_PRODUCTS
    from services.vendor_staff_service import push_tokens_for_store

    recipients = [vendor.push_token] + await push_tokens_for_store(
        session, vendor.id, permission=PERMISSION_MANAGE_PRODUCTS
    )
    for token in recipients:
        if token and push_allowed(vendor, "low_stock"):
            queue_push(session, to=token, title=title, body=body, data={"url": action_url})


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
                        # A decimal string, like every other money value on the
                        # wire. This is the figure on the rider's offer card —
                        # what they decide to accept a job on — and it reached
                        # all three dispatch broadcasts as a JSON float.
                        delivery_fee=money_str(order.delivery_fee or 0),
                        vehicle_class=order.vehicle_class,
                        vendor_type=vendor_type_str,
                        total_weight_kg=_total_weight,
                        total_quantity=_total_qty,
                        delivery_type=order.delivery_type or "quick_swap",
                        notification_data=snapshot_data,
                    ))

    await session.commit()

    from services.expo_push_service import dispatch_background

    for dispatch_kwargs in pending_dispatches:
        # `dispatch_background`, not a bare `create_task`. The event loop keeps
        # only a *weak* reference to a task, so one whose return value is
        # discarded can be garbage collected part-way through — and this is the
        # task that offers a just-paid order to riders. The failure is silent
        # from every angle: the customer has paid, the order is `unassigned`,
        # and no rider was ever told. It is also likeliest exactly when it costs
        # most, because GC pressure rises with load.
        dispatch_background(dispatch_order_to_riders(**dispatch_kwargs))

    return {
        "message": "Transaction was completed successfully.",
        "code": "0"
      }

def staircase_shortfall(order) -> Decimal:
  """What approving an address mismatch will actually add to this order.

  The one definition, used by the figure the customer is *shown* and by the
  charge that is applied. The app quoted a flat "KSh 30" in the explanation and
  again on the button — "Approve Charge (+KSh 30)" — which is a consent control
  naming an amount the platform does not necessarily charge. Thirty is only
  right for a fifth floor with nothing already billed; the real figure is the
  configured rate over the free allowance, less whatever the quote already
  collected.

  Reads the settings synchronously, so the caller has already awaited
  `ensure_fresh`.
  """
  actual = int(_d_int(getattr(order, "actual_floor_level", 0)))
  free_floors = _config.get_int("staircase_free_floors")
  per_floor = _config.get_decimal("staircase_surcharge_per_floor")
  already = Decimal(str(getattr(order, "staircase_surcharge", 0) or 0))
  owed = Decimal(max(0, actual - free_floors)) * per_floor
  return max(Decimal("0.00"), (owed - already).quantize(Decimal("0.01")))


def _d_int(value) -> int:
  try:
      return int(value or 0)
  except (TypeError, ValueError):
      return 0


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

      # What approving the mismatch would cost, for the order that is asking.
      # Zero everywhere else, so the screen has nothing to render.
      order.pending_staircase_charge = (
          staircase_shortfall(order)
          if order.order_status == "mismatch_pending"
          else Decimal("0.00")
      )
  return orders


async def fetch_orders_by_id(
    session: AsyncSession,
    user_id: UUID,
    skip: int = 0,
    limit: int = 50,
    statuses: Sequence[str] | None = None,
) -> list[BaseOrder]:
  """One page of a customer's orders, newest first, optionally one status group.

  `statuses` is a *group* rather than a single value because that is the shape
  the screen asks in: its filters are Pending, In Transit, Delivered and
  Cancelled, and each covers several statuses. Filtering had to happen on the
  server once the list was paged — a screen that filters the page it holds
  answers "no Delivered orders" to a customer whose deliveries start on page 2,
  which is the same list telling two different stories depending on how far
  somebody had scrolled first.
  """
  query = select(Order).where(Order.customer_id == user_id)
  if statuses:
    query = query.where(Order.order_status.in_(list(statuses)))
  query = query.options(joinedload(Order.order_item).joinedload(OrderItem.product), joinedload(Order.vendor), joinedload(Order.deliverer)).order_by(*stable(Order.created_at.desc(), key=Order.id)).offset(skip).limit(limit)
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

async def restore_order_stock(session: AsyncSession, order: Order) -> list:
    """Atomically return every item on this order to its product's stock.

    Relative `stock = stock + qty`, never read-then-write, so two reversal paths
    racing on the same order cannot lose one. Clearing `low_stock_notified_at`
    puts the product back above the line so the next crossing warns again.

    Returns the order's items, because every caller needs them anyway.
    """
    items = (
        await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars().all()

    for item in items:
        await session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(
                stock=Product.stock + item.quantity,
                is_available=True,
                low_stock_notified_at=None,
            )
        )
    if items:
        logger.info("Restored stock for %s item(s) from order %s", len(items), order.id)
    return items


async def revert_order_side_effects(
    session: AsyncSession,
    order: Order,
    *,
    reason: str,
    customer: User | None = None,
    return_wallet_credit: bool = True,
    restore_welcome_offer: bool = True,
):
    """Undo everything an order consumed, in one place.

    Cancelling an order is not one action, it is seven, and they were previously
    spread across six call sites that each remembered a different subset. Stock
    was restored everywhere; `commission_lost` was set in five of the six, so any
    report summing it understated lost revenue by exactly the vendor-initiated
    rejections — likely the most common kind. The debt settlement and the bottle
    deposit are new, and adding them to six places would have repeated the same
    mistake with two more fields.

    Every reversal path calls this. What each one does *around* it — a
    cancellation penalty, freeing a rider, choosing between `cancelled` and
    `unassigned` — stays with the caller, because those genuinely differ.

    Does not commit; the caller owns the transaction boundary.
    """
    from decimal import Decimal
    from models.wallet_transaction_model import TransactionType
    from services.wallet_service import apply_wallet_delta

    was_paid = order.payment_status == "paid"

    await restore_order_stock(session, order)

    if customer is None and order.customer_id is not None:
        customer = await session.get(User, order.customer_id)

    if customer is not None:
        # ── Wallet credit spent on this order ──
        wallet_refund = Decimal(str(order.wallet_discount or 0))
        if return_wallet_credit and wallet_refund > 0:
            await apply_wallet_delta(
                session,
                owner=customer,
                clerk_id=customer.clerk_id,
                user_type="customer",
                amount=wallet_refund,
                transaction_type=TransactionType.refund,
                description=(
                    f"Wallet credit returned after cancelling order "
                    f"{str(order.id)[:8].upper()}"
                ),
                reference_id=str(order.id),
            )

        # ── Debt this order was collecting ──
        # The customer is being refunded the whole total, which included it, so
        # the balance is still owed. Not restoring it would let a customer clear
        # a penalty by placing an order and immediately cancelling it.
        settled = Decimal(str(order.debt_settlement or 0))
        if settled > 0:
            customer.debt_balance = Decimal(str(customer.debt_balance or 0)) + settled
            order.debt_settlement = Decimal("0.00")
            logger.info(
                "Restored KSH %s of debt to user %s after cancelling order %s",
                settled, customer.id, order.id,
            )

        # ── Bottle deposit ──
        # They never received the bottle, so the platform owes nothing back and
        # they are holding nothing.
        deposit = Decimal(str(order.bottle_deposit or 0))
        if deposit > 0:
            from services import customer_bottle_service

            items = (
                await session.execute(
                    select(OrderItem)
                    .options(joinedload(OrderItem.product))
                    .where(OrderItem.order_id == order.id)
                )
            ).unique().scalars().all()
            await customer_bottle_service.release_deposit(
                session,
                user=customer,
                amount=deposit,
                bottles=customer_bottle_service.bottles_in(items),
                order_id=order.id,
            )

        # ── Welcome offer ──
        # Only when the customer actually paid. Restoring it on a free
        # `pending`/`unassigned` cancellation let the 30% first-order discount be
        # farmed indefinitely.
        if (
            restore_welcome_offer
            and was_paid
            and (order.is_welcome_offer or Decimal(str(order.welcome_discount or 0)) > 0)
        ):
            customer.has_used_welcome_offer = False
            logger.info("Reset welcome offer for user %s (paid order cancelled)", customer.id)

    order.cancellation_reason = reason

    if was_paid:
        order.payment_status = "refund_pending"
        # The platform revenue this cancellation gave up. Set on *every* reversal
        # path, including the vendor's own reject, which previously left it null.
        order.commission_lost = order.platform_total

    return customer


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

    # Lock the customer once, up front — the penalty, the wallet restoration,
    # the deposit release and the welcome-offer reset all mutate this row.
    user_res = await session.execute(select(User).where(User.id == user_id).with_for_update())
    user = user_res.scalar_one_or_none()

    # A vendor who has already accepted is likely preparing the order, so a late
    # cancellation carries a fee. It is added to the customer's debt balance,
    # which their next order collects as a visible line item — the balance is no
    # longer a permanent block on the account.
    #
    # Two figures, not one. Cancelling before pickup costs the rider a wasted
    # approach; cancelling after costs the vendor an order they have already
    # prepared *and* the rider a full trip. A single flat penalty is unfair at
    # one end and toothless at the other.
    #
    # And the first cancellation in a rolling window is free. Genuine mistakes
    # happen, and a support ticket arguing about KSH 50 costs more to handle
    # than the penalty collects.
    PENALISED_STATUSES = {
        "accepted": "late_cancellation_penalty",
        "preparing": "late_cancellation_penalty",
        "ready": "late_cancellation_penalty",
        "picked_up": "late_cancellation_penalty_after_pickup",
    }
    # What actually happened, reported back to the caller. The endpoint used to
    # return "Order cancelled successfully" and nothing else, while adding up to
    # KSH 150 to the customer's `debt_balance` — collected silently on their
    # next order as a line they had never been told about. The app filled the
    # gap by *guessing* in the confirmation dialog: it warned about "a KSH 50
    # cancellation penalty" for every penalised status, which is the wrong
    # figure after pickup and the wrong answer entirely while the customer still
    # has a free cancellation left.
    penalty_charged = Decimal("0.00")
    free_remaining = 0

    if order.order_status in PENALISED_STATUSES and user:
        penalty = _config.get_decimal(PENALISED_STATUSES[order.order_status])
        allowance = _config.get_int("free_cancellations_per_month")

        recent = 0
        if allowance > 0:
            from datetime import datetime as _dt, timezone as _tz

            window_start = _dt.now(_tz.utc) - timedelta(days=30)
            # Counted by `cancellation_reason`, which `revert_order_side_effects`
            # writes — the customer's own cancellations only. A vendor rejecting
            # an order is not the customer's mistake and must not consume their
            # allowance.
            recent = (
                await session.execute(
                    select(func.count(Order.id)).where(
                        Order.customer_id == user_id,
                        Order.order_status == "cancelled",
                        Order.cancellation_reason == "cancelled_by_customer",
                        Order.updated_at >= window_start,
                    )
                )
            ).scalar() or 0

        if recent < allowance:
            free_remaining = allowance - recent - 1
            logger.info(
                "Cancellation by user %s waived: %s of %s free cancellations used.",
                user_id, recent, allowance,
            )
        elif penalty > 0:
            penalty_charged = penalty
            user.debt_balance = Decimal(str(user.debt_balance or 0)) + penalty
            logger.info(
                "Cancellation penalty of KSH %s applied to user %s (status %s)",
                penalty, user_id, order.order_status,
            )

    # Release rider availability if one was already assigned
    if order.deliverer_id:
        deliverer = await session.get(Deliverer, order.deliverer_id)
        if deliverer:
            deliverer.is_available = True

    apply_status_transition(order, "cancelled")

    await revert_order_side_effects(
        session, order, reason="cancelled_by_customer", customer=user
    )

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

    return {
        "message": "Order cancelled successfully",
        "order_id": str(order.id),
        # Zero when nothing was charged — a status that carries no penalty, or a
        # free cancellation. The app renders this rather than composing its own
        # sentence: the two figures and the allowance behind them are settings
        # rows, and a number stated by an app goes stale the moment one moves.
        "penalty_charged": money_str(penalty_charged),
        "free_cancellations_remaining": free_remaining,
    }


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
                    "fee": money_str(order.delivery_fee or 0),
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
        # The charge for the floors the rider was not told about.
        #
        # This was a hardcoded `charge = 30.0` — a float, assigned to `Numeric`
        # columns, unrelated to `staircase_surcharge_per_floor` in the settings
        # table, and flat regardless of how many floors were actually climbed. It
        # is now the same formula the quote uses, so a customer who declares
        # their floor honestly and one who is caught out pay the same rate.
        from decimal import Decimal

        await _config.ensure_fresh(session)

        # Only the shortfall: they may already have been charged for some floors
        # at checkout, and charging the full amount again would bill twice. The
        # same function computes the figure the customer was shown before they
        # tapped approve, so the two cannot disagree.
        already = Decimal(str(order.staircase_surcharge or 0))
        charge = staircase_shortfall(order)

        if charge <= 0:
            logger.info(
                "Mismatch on order %s carries no additional charge (floor %s already covered)",
                order.id, order.actual_floor_level,
            )
            charge = Decimal("0.00")
        else:
            order.staircase_surcharge = already + charge
            order.total_amount = Decimal(str(order.total_amount or 0)) + charge

            # M-Pesa already took the original total, so this goes onto the
            # customer's balance and is collected on their next order.
            user = await session.get(User, user_id)
            if user:
                user.debt_balance = Decimal(str(user.debt_balance or 0)) + charge

            # A gig rider did the climbing and keeps all of it. For an in-house
            # rider the vendor employs them, so the vendor is paid instead —
            # the same rule the revenue split applies to every other surcharge.
            deliverer = (
                await session.get(Deliverer, order.deliverer_id)
                if order.deliverer_id else None
            )
            if deliverer and deliverer.employment_model == "gig_economy":
                order.rider_net = Decimal(str(order.rider_net or 0)) + charge
            else:
                order.vendor_net = Decimal(str(order.vendor_net or 0)) + charge

    elif action == "leave_ground":
        # No extra charge, rider leaves at ground floor
        pass
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    # Transition back to picked_up so rider can complete delivery
    apply_status_transition(order, "picked_up")
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

    # `money_str`, not the bare `Decimal`. There is no `response_model` on this
    # route, so FastAPI's `jsonable_encoder` would turn the column into a JSON
    # **float** — the same defect as an explicit cast, with nothing to grep for.
    # This is the total immediately after it has just been increased by the
    # approved staircase charge, which is the one moment the customer is looking
    # at it to check what they agreed to.
    return {
        "message": "Mismatch resolved successfully",
        "order": {
            "id": str(order.id),
            "status": order.order_status,
            "total_amount": money_str(order.total_amount),
        },
    }