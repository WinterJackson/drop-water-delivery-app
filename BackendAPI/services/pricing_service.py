"""Single source of truth for customer order pricing.

Every figure the customer is ever shown, charged, or has recorded against their
order MUST come from `compute_order_quote`. Before this module existed the total
was computed independently in four places (the cart preview, the STK-push route,
the order ledger, and the mobile client) with three different results — the
customer was shown one number, charged a second, and had a third written to the
order row, which made the M-Pesa callback's amount cross-check fail on every
retail order.

Rules of the road:
  * All arithmetic is Decimal. Never float.
  * `quote.total` is quantized to a whole shilling, because that is the
    granularity M-Pesa's STK push accepts. The integer we push and the amount we
    persist are therefore identical by construction, not by coincidence.
  * This module is pure: it reads, it never mutates and never commits. Consuming
    the welcome offer and debiting the wallet are side effects owned by
    `order_service.create_order`, under a row lock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.vendor_model import Vendor
from services.dispatch_policy import DispatchPolicy

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")
WHOLE = Decimal("1")
ZERO = Decimal("0.00")

# ── Bottle deposit schedule (KSH per bottle, by capacity in litres) ──────────
BOTTLE_DEPOSIT_BY_CAPACITY: dict[int, Decimal] = {
    20: Decimal("300.00"),
    10: Decimal("150.00"),
}

# First order gets 30% off the bottle deposit. The platform absorbs it as a
# customer-acquisition cost (see `calculate_revenue_splits`).
WELCOME_DISCOUNT_RATE = Decimal("0.30")

# Surcharge schedule
PAYLOAD_FREE_UNITS = 2
PAYLOAD_SURCHARGE_PER_UNIT = Decimal("10.00")
STAIRCASE_FREE_FLOORS = 2
STAIRCASE_SURCHARGE_PER_FLOOR = Decimal("10.00")

# An STK push for 0 is rejected by Safaricom, so discounts never consume the
# final shilling.
MIN_CHARGEABLE_TOTAL = Decimal("1")

# Ordering used to reconcile the weight-derived and quantity-derived vehicle
# classes. We always take the larger of the two: 100 kg of water does not fit on
# a motorbike just because the bottle count is low, and 20 bottles do not fit
# just because they are light.
_VEHICLE_RANK = {"motorbike": 0, "tuktuk": 1, "truck": 2}
_RANK_TO_VEHICLE = {rank: name for name, rank in _VEHICLE_RANK.items()}


def _d(value: Any) -> Decimal:
    """Coerce anything numeric (float, Decimal, str, None) to Decimal safely."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def required_vehicle_class(total_quantity: int, total_weight_kg: Decimal) -> str:
    """The vehicle class an order needs, reconciling weight and unit count.

    `DispatchPolicy.get_vehicle_class` raises when the unit count exceeds even a
    truck; that is a genuine validation failure and is surfaced by
    `validate_quote`, so we let it propagate as a ValueError here.
    """
    by_quantity = DispatchPolicy.get_vehicle_class(total_quantity)

    weight = float(total_weight_kg)
    if weight <= 0:
        by_weight = "motorbike"
    elif weight <= 100.0:
        by_weight = "motorbike"
    elif weight <= 400.0:
        by_weight = "tuktuk"
    else:
        by_weight = "truck"

    return _RANK_TO_VEHICLE[max(_VEHICLE_RANK[by_quantity], _VEHICLE_RANK[by_weight])]


@dataclass
class OrderQuote:
    """An immutable, fully itemised price for one single-vendor cart."""

    # ── Context ──
    vendor_id: UUID
    vendor_type: str
    delivery_type: str
    total_quantity: int
    total_weight_kg: Decimal
    vehicle_class: str
    distance_km: float
    estimated_minutes: int
    lat_from: Optional[float]
    lng_from: Optional[float]

    # ── Line items (all Decimal, 2dp) ──
    product_subtotal: Decimal
    delivery_fee: Decimal
    service_fee: Decimal
    surge_fee: Decimal
    delivery_markup: Decimal
    payload_surcharge: Decimal
    staircase_surcharge: Decimal
    bottle_deposit: Decimal
    welcome_discount: Decimal
    wallet_discount: Decimal

    # ── Result ──
    total: Decimal  # whole shillings — this is what we charge AND persist
    surge_active: bool
    is_welcome_offer: bool
    revenue: dict = field(default_factory=dict)

    @property
    def stk_amount(self) -> int:
        """The integer handed to `initiate_stk_push`.

        Equal to `total` by construction — `total` is quantized to whole
        shillings precisely so this conversion is lossless.
        """
        return int(self.total)

    @property
    def gross_before_discounts(self) -> Decimal:
        return _money(
            self.product_subtotal
            + self.delivery_fee
            + self.service_fee
            + self.surge_fee
            + self.delivery_markup
            + self.payload_surcharge
            + self.staircase_surcharge
            + self.bottle_deposit
        )

    def as_dict(self) -> dict:
        """JSON-serialisable breakdown for the client to render verbatim."""
        return {
            "vendor_id": str(self.vendor_id),
            "vendor_type": self.vendor_type,
            "delivery_type": self.delivery_type,
            "total_quantity": self.total_quantity,
            "total_weight_kg": float(self.total_weight_kg),
            "vehicle_class": self.vehicle_class,
            "distance_km": self.distance_km,
            "estimated_minutes": self.estimated_minutes,
            "product_subtotal": float(self.product_subtotal),
            "delivery_fee": float(self.delivery_fee),
            "service_fee": float(self.service_fee),
            "surge_fee": float(self.surge_fee),
            "delivery_markup": float(self.delivery_markup),
            "payload_surcharge": float(self.payload_surcharge),
            "staircase_surcharge": float(self.staircase_surcharge),
            "bottle_deposit": float(self.bottle_deposit),
            "welcome_discount": float(self.welcome_discount),
            "wallet_discount": float(self.wallet_discount),
            "total": float(self.total),
            "surge_active": self.surge_active,
            "is_welcome_offer": self.is_welcome_offer,
        }


def _cart_payload(items: Iterable) -> tuple[int, Decimal, Decimal]:
    """Returns (total_quantity, total_weight_kg, product_subtotal)."""
    total_quantity = 0
    total_weight = ZERO
    subtotal = ZERO
    for item in items:
        qty = int(item.quantity or 0)
        total_quantity += qty
        product = getattr(item, "product", None)
        if product is not None:
            total_weight += _d(getattr(product, "weight_kg", 0)) * qty
        # CartItem.Subtotal and OrderItem.Subtotal are both authoritative;
        # fall back to price × qty for freshly built rows.
        line = getattr(item, "Subtotal", None)
        subtotal += _d(line) if line is not None else _d(item.price) * qty
    return total_quantity, _money(total_weight), _money(subtotal)


def _bottle_deposit(items: Iterable) -> Decimal:
    """Total refundable deposit for the bottles in this cart."""
    deposit = ZERO
    for item in items:
        product = getattr(item, "product", None)
        if product is None:
            continue
        capacity = int(_d(getattr(product, "capacity", 0)))
        per_bottle = BOTTLE_DEPOSIT_BY_CAPACITY.get(capacity)
        if per_bottle is not None:
            deposit += per_bottle * int(item.quantity or 0)
    return _money(deposit)


def vendor_type_of(vendor: Optional[Vendor]) -> str:
    if vendor is None or vendor.vendor_type is None:
        return "retail_refill"
    raw = vendor.vendor_type
    return raw.value if hasattr(raw, "value") else str(raw)


def service_fee_for(vendor_type: str) -> Decimal:
    """The one definition of the customer-facing service fee."""
    from services.order_service import RETAIL_SERVICE_FEE_KSH, WHOLESALE_SERVICE_FEE_KSH

    return _money(
        _d(WHOLESALE_SERVICE_FEE_KSH if vendor_type == "wholesale_b2b" else RETAIL_SERVICE_FEE_KSH)
    )


async def compute_order_quote(
    session: AsyncSession,
    *,
    items: list,
    user,
    vendor: Optional[Vendor],
    delivery_type: str,
    lat: float,
    lng: float,
    apply_wallet: bool = True,
    wallet_balance_override: Optional[Decimal] = None,
) -> OrderQuote:
    """Price a single-vendor set of cart (or order) items.

    `items` must all belong to `vendor`. Callers holding a `Cart` should pass
    `cart.cart_item`. Pure — no mutation, no commit.
    """
    # Imported lazily: order_service imports this module inside create_order, so
    # a module-level import here would close a cycle.
    from services.order_service import (
        calculate_delivery_fee,
        calculate_revenue_splits,
        is_surge_active,
        SURGE_FEE_KSH,
    )

    if not items:
        raise HTTPException(status_code=400, detail="Your cart is empty. Add an item before checking out.")

    vendor_type = vendor_type_of(vendor)
    total_quantity, total_weight_kg, product_subtotal = _cart_payload(items)

    try:
        vehicle_class = required_vehicle_class(total_quantity, total_weight_kg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lat_from = getattr(vendor, "lat", None)
    lng_from = getattr(vendor, "lng", None)

    wholesale_base = 0.0
    wholesale_per_km = 0.0
    if vendor_type == "wholesale_b2b" and vendor is not None:
        wholesale_base = float(_d(getattr(vendor, "wholesale_base_delivery_fee", 0)))
        wholesale_per_km = float(_d(getattr(vendor, "wholesale_per_km_fee", 0)))

    delivery = calculate_delivery_fee(
        lat_from=lat_from or 0.0,
        lng_from=lng_from or 0.0,
        lat_to=lat,
        lng_to=lng,
        vendor_type=vendor_type,
        vehicle_class=vehicle_class,
        wholesale_base=wholesale_base,
        wholesale_per_km=wholesale_per_km,
        delivery_type=delivery_type,
    )
    delivery_fee = _money(_d(delivery["fee"]))

    # ── Bottle deposit & welcome offer ──────────────────────────────────────
    # A deposit is due when the customer keeps the bottle, or on a first order
    # (they have no empty to swap). First orders get 30% off that deposit.
    is_first_order = bool(user) and not bool(getattr(user, "has_used_welcome_offer", True))
    bottle_deposit = ZERO
    welcome_discount = ZERO
    is_welcome_offer = False

    if delivery_type == "keep_my_bottle" or is_first_order:
        bottle_deposit = _bottle_deposit(items)
        if is_first_order and bottle_deposit > ZERO:
            welcome_discount = _money(bottle_deposit * WELCOME_DISCOUNT_RATE)
            is_welcome_offer = True

    # ── Surcharges ──────────────────────────────────────────────────────────
    payload_surcharge = ZERO
    if total_quantity > PAYLOAD_FREE_UNITS:
        payload_surcharge = _money(Decimal(total_quantity - PAYLOAD_FREE_UNITS) * PAYLOAD_SURCHARGE_PER_UNIT)

    staircase_surcharge = ZERO
    if user is not None:
        floor_level = int(_d(getattr(user, "floor_level", 0)))
        has_elevator = bool(getattr(user, "has_elevator", False))
        if floor_level > STAIRCASE_FREE_FLOORS and not has_elevator:
            staircase_surcharge = _money(
                Decimal(floor_level - STAIRCASE_FREE_FLOORS) * STAIRCASE_SURCHARGE_PER_FLOOR
            )

    # ── Platform fees ───────────────────────────────────────────────────────
    service_fee = service_fee_for(vendor_type)
    surge_active = is_surge_active()
    surge_fee = _money(_d(SURGE_FEE_KSH)) if surge_active else ZERO
    delivery_markup = ZERO
    if vendor_type == "wholesale_b2b":
        from services.order_service import WHOLESALE_DELIVERY_MARKUP

        delivery_markup = _money(delivery_fee * _d(WHOLESALE_DELIVERY_MARKUP))

    gross = _money(
        product_subtotal
        + delivery_fee
        + service_fee
        + surge_fee
        + delivery_markup
        + payload_surcharge
        + staircase_surcharge
        + bottle_deposit
    )

    # ── Discounts ───────────────────────────────────────────────────────────
    # Welcome discount first (it reduces the deposit component), then wallet
    # credit against the remainder. Order matters: reversing it lets the wallet
    # over-discount when both apply.
    after_welcome = _money(gross - welcome_discount)

    wallet_discount = ZERO
    if apply_wallet:
        balance = (
            wallet_balance_override
            if wallet_balance_override is not None
            else _d(getattr(user, "wallet_balance", 0) if user else 0)
        )
        if balance > ZERO:
            headroom = after_welcome - MIN_CHARGEABLE_TOTAL
            if headroom > ZERO:
                wallet_discount = _money(min(balance, headroom))

    # Whole shillings: M-Pesa cannot push a fraction, and persisting anything
    # else would reintroduce the charged-vs-recorded drift this module exists to
    # eliminate.
    total = (after_welcome - wallet_discount).quantize(WHOLE, rounding=ROUND_HALF_UP)
    if total < MIN_CHARGEABLE_TOTAL:
        total = MIN_CHARGEABLE_TOTAL

    revenue = calculate_revenue_splits(
        product_total=float(product_subtotal),
        delivery_fee=float(delivery_fee),
        vendor_type=vendor_type,
        bottle_deposit=float(bottle_deposit),
        rider_surcharges=float(payload_surcharge + staircase_surcharge),
        delivery_type=delivery_type,
        welcome_discount=float(welcome_discount),
    )

    return OrderQuote(
        vendor_id=vendor.id if vendor is not None else None,
        vendor_type=vendor_type,
        delivery_type=delivery_type,
        total_quantity=total_quantity,
        total_weight_kg=total_weight_kg,
        vehicle_class=vehicle_class,
        distance_km=float(delivery["distance_km"]),
        estimated_minutes=int(delivery["estimated_minutes"]),
        lat_from=lat_from,
        lng_from=lng_from,
        product_subtotal=product_subtotal,
        delivery_fee=delivery_fee,
        service_fee=service_fee,
        surge_fee=surge_fee,
        delivery_markup=delivery_markup,
        payload_surcharge=payload_surcharge,
        staircase_surcharge=staircase_surcharge,
        bottle_deposit=bottle_deposit,
        welcome_discount=welcome_discount,
        wallet_discount=wallet_discount,
        total=total,
        surge_active=surge_active,
        is_welcome_offer=is_welcome_offer,
        revenue=revenue,
    )


def validate_quote(quote: OrderQuote, items: list, *, user=None) -> None:
    """Every gate that must pass before money moves.

    Called *before* the STK push so a validation failure can never leave the
    customer debited with no order (see H8). `create_order` calls it again under
    its row lock, because stock can change in between.
    """
    # 1. Capacity + wholesale MOQ + retail distance/quantity caps.
    DispatchPolicy.validate_cart_preflight(
        vendor_type=quote.vendor_type,
        distance_km=quote.distance_km,
        total_quantity=quote.total_quantity,
        total_weight_kg=float(quote.total_weight_kg),
    )

    # 2. Stock availability.
    for item in items:
        product = getattr(item, "product", None)
        if product is None or product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient stock for '{product.name if product else 'unknown'}'. "
                    f"Available: {product.stock if product else 0}, requested: {item.quantity}."
                ),
            )

    # 3. Outstanding bottle-deposit debt blocks new orders.
    if user is not None:
        debt = _d(getattr(user, "debt_balance", 0))
        if debt > ZERO:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"You have an outstanding bottle deposit debt of KSH {debt:.0f}. "
                    "Please clear it before placing a new order."
                ),
            )

    # 4. Self-dealing.
    if user is not None and quote.vendor_id is not None:
        # Vendor identity is checked in create_order where the Vendor row is
        # loaded; nothing to assert here without another query.
        pass

    if quote.total < MIN_CHARGEABLE_TOTAL:
        raise HTTPException(status_code=400, detail="Order total must be greater than zero.")


def single_vendor_or_400(items: list) -> UUID:
    """Carts are single-vendor by design (`add_to_cart_service` enforces it).

    Re-assert it here: a multi-vendor cart would produce several orders sharing
    one CheckoutRequestID, which makes the payment callback ambiguous about which
    order it just paid for.
    """
    vendor_ids = {item.vendor_id for item in items}
    if len(vendor_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail="Your cart contains items from more than one vendor. Please check out one vendor at a time.",
        )
    return next(iter(vendor_ids))
