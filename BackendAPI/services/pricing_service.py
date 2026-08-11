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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.vendor_model import Vendor
from services import platform_config_service as config
from services import delivery_types
from services.dispatch_policy import DispatchPolicy
from utils.money import money_str

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")
WHOLE = Decimal("1")
ZERO = Decimal("0.00")

# Every figure below used to be a constant here. They are rows in
# `Platform_Settings` now, read through `platform_config_service`, so the owners
# can change the deposit schedule or the welcome discount from the admin console
# and have it apply to the next quote in all three apps.
#
# `compute_order_quote` awaits `config.ensure_fresh(session)` before reading any
# of them, so a single quote is priced against one consistent configuration.


def bottle_deposit_for(capacity_litres: int) -> Optional[Decimal]:
    """The deposit for one bottle of this capacity, or None if not offered.

    None is meaningful: a capacity with no configured deposit is a product the
    platform does not take a deposit on, which is different from a deposit of
    zero.
    """
    schedule = config.get("bottle_deposit_by_capacity") or {}
    amount = schedule.get(str(int(capacity_litres)))
    return None if amount is None else _money(_d(amount))


def welcome_discount_rate() -> Decimal:
    """Off the deposit for **one** bottle on a customer's first order.

    The platform absorbs it as an acquisition cost — it is never charged to the
    vendor. Scoped to a single bottle deliberately: applied to the whole
    deposit, a first order of six 20 L bottles cost the platform KSH 540 of pure
    margin, and the cheapest way to claim the maximum was to order bottles the
    customer did not want and return them. One bottle is the incentive to try
    the platform; six is an arbitrage.
    """
    return config.get_decimal("welcome_discount_rate")


def cheapest_bottle_deposit(items: Iterable) -> Decimal:
    """The deposit on the single least expensive deposit-bearing bottle.

    The *cheapest*, not the first or the dearest: the discount is a fixed,
    predictable acquisition cost the platform can budget for, and taking the
    largest would make the cost depend on what a stranger put in their basket.
    """
    deposits = []
    for item in items:
        product = getattr(item, "product", None)
        if product is None:
            continue
        per_bottle = bottle_deposit_for(int(_d(getattr(product, "capacity", 0))))
        if per_bottle is not None and per_bottle > ZERO:
            deposits.append(per_bottle)
    return min(deposits) if deposits else ZERO


def min_chargeable_total() -> Decimal:
    """An STK push for 0 is rejected by Safaricom, so discounts never consume
    the final shilling."""
    return config.get_decimal("min_chargeable_total")


def max_debt_before_block() -> Decimal:
    """The point at which an unpaid balance stops being a line item and starts
    being a refusal.

    Below it, `outstanding_debt` is added to the next order and cleared when that
    order is created — the customer settles it by carrying on using the platform,
    which is the only way they were ever going to. At or above it, the platform
    stops extending credit.
    """
    return config.get_decimal("max_customer_debt_before_block")

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
    #: An unpaid balance from an earlier order, collected on this one. Charged
    #: like any other line and cleared by `create_order`.
    debt_settlement: Decimal
    welcome_discount: Decimal
    #: Taken off for paying by M-Pesa rather than cash. A reward, not a cash
    #: surcharge — see `compute_order_quote`.
    mpesa_discount: Decimal
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
            + self.payload_surcharge
            + self.staircase_surcharge
            + self.bottle_deposit
            + self.debt_settlement
        )  # `delivery_markup` is inside `delivery_fee`, never beside it

    def as_dict(self) -> dict:
        """JSON-serialisable breakdown for the client to render verbatim.

        Money is a decimal string. This is the single most-read money payload
        on the platform — the cart renders every line of it and the customer is
        charged `total` — and it went out as JSON numbers, so the one figure
        the whole pricing discipline exists to protect was a float by the time
        anybody saw it. `total_weight_kg` stays a number: it is a weight, and
        the wholesale MOQ check compares it against `moq_kg`.
        """
        return {
            "vendor_id": str(self.vendor_id),
            "vendor_type": self.vendor_type,
            "delivery_type": self.delivery_type,
            "total_quantity": self.total_quantity,
            "total_weight_kg": float(self.total_weight_kg),
            "vehicle_class": self.vehicle_class,
            "distance_km": self.distance_km,
            "estimated_minutes": self.estimated_minutes,
            "product_subtotal": money_str(self.product_subtotal),
            "delivery_fee": money_str(self.delivery_fee),
            "service_fee": money_str(self.service_fee),
            "surge_fee": money_str(self.surge_fee),
            "delivery_markup": money_str(self.delivery_markup),
            "payload_surcharge": money_str(self.payload_surcharge),
            "staircase_surcharge": money_str(self.staircase_surcharge),
            "bottle_deposit": money_str(self.bottle_deposit),
            "debt_settlement": money_str(self.debt_settlement),
            "welcome_discount": money_str(self.welcome_discount),
            "mpesa_discount": money_str(self.mpesa_discount),
            "wallet_discount": money_str(self.wallet_discount),
            "total": money_str(self.total),
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
        per_bottle = bottle_deposit_for(capacity)
        if per_bottle is not None:
            deposit += per_bottle * int(item.quantity or 0)
    return _money(deposit)


async def welcome_offer_available(session: AsyncSession, user) -> bool:
    """Whether this customer may still have the first-order discount.

    Two conditions, not one:

    * **The account has not used it.** `has_used_welcome_offer`, consumed under a
      row lock by `create_order`.
    * **No other account on the same handset has used it.** `Users.device_id`
      was added for exactly this — the column carries the comment
      "Anti-fraud: one offer per device" — and then nothing anywhere read or
      wrote it. The offer was therefore gated per account, and since the
      discount is 30% of a KSH 300 deposit taken entirely out of platform
      margin, it could be farmed indefinitely with fresh sign-ups from one
      phone.

    A null `device_id` is refused the offer when the platform requires one
    (`welcome_offer_requires_device`, on by default). This is the opposite of
    what it used to do, and the reversal matters: no app sent the field, so
    **every** account had a null and every account passed. The gate was not
    merely weak, it had never once been consulted — the discount was scoped to
    one per account, and accounts are free.

    Turning the requirement off is the escape hatch for a client release that
    cannot report a device, and it fails *open* by explicit choice rather than
    by accident.
    """
    if user is None or bool(getattr(user, "has_used_welcome_offer", True)):
        return False

    device_id = getattr(user, "device_id", None)
    if not device_id:
        if config.get_bool("welcome_offer_requires_device"):
            logger.info(
                "Welcome offer refused for user %s: no device recorded.", user.id
            )
            return False
        return True

    from models.user_model import User as _User

    used_on_this_device = (
        await session.execute(
            select(_User.id)
            .where(
                _User.device_id == device_id,
                _User.id != user.id,
                _User.has_used_welcome_offer.is_(True),
            )
            .limit(1)
        )
    ).scalars().first()

    if used_on_this_device is not None:
        logger.info(
            "Welcome offer refused for user %s: device %s already claimed it on account %s",
            user.id, device_id, used_on_this_device,
        )
        return False
    return True


def vendor_type_of(vendor: Optional[Vendor]) -> str:
    if vendor is None or vendor.vendor_type is None:
        return "retail_refill"
    raw = vendor.vendor_type
    return raw.value if hasattr(raw, "value") else str(raw)


def service_fee_for(vendor_type: str) -> Decimal:
    """The one definition of the customer-facing service fee."""
    return _money(
        config.get_decimal(
            "wholesale_service_fee" if vendor_type == "wholesale_b2b" else "retail_service_fee"
        )
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
    payment_method: str = "mpesa",
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
    )

    # One load, at the top. Everything below reads the configuration
    # synchronously, so a single quote cannot be priced against two different
    # fee schedules even if an administrator saves a change mid-request.
    await config.ensure_fresh(session)

    if not items:
        raise HTTPException(status_code=400, detail="Your cart is empty. Add an item before checking out.")

    # One canonical value from here down. Old app builds still send `quick_swap`
    # and `keep_my_bottle`, and they must price as what they meant.
    delivery_type = delivery_types.normalise(delivery_type)

    vendor_type = vendor_type_of(vendor)
    total_quantity, total_weight_kg, product_subtotal = _cart_payload(items)

    try:
        vehicle_class = required_vehicle_class(total_quantity, total_weight_kg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lat_from = getattr(vendor, "lat", None)
    lng_from = getattr(vendor, "lng", None)

    wholesale_base = Decimal("0")
    wholesale_per_km = Decimal("0")
    if vendor_type == "wholesale_b2b" and vendor is not None:
        wholesale_base = _d(getattr(vendor, "wholesale_base_delivery_fee", 0))
        wholesale_per_km = _d(getattr(vendor, "wholesale_per_km_fee", 0))

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
    is_first_order = await welcome_offer_available(session, user)
    bottle_deposit = ZERO
    welcome_discount = ZERO
    is_welcome_offer = False

    # **The type alone decides.** It used to be `keep_my_bottle or
    # is_first_order`, and the second half was standing in for `new_bottle`
    # before that type existed — so a first-time customer exchanging a bottle
    # they already owned was charged a deposit for it, and a customer having
    # their *own* bottle refilled was charged one on their own property.
    if delivery_types.takes_deposit(delivery_type):
        bottle_deposit = _bottle_deposit(items)

        # The ceiling, checked here rather than at `create_order`, so the
        # customer is refused *before* M-Pesa takes the money. Unlimited bottles
        # against a deposit is unlimited liability, and an unlimited-size target
        # for anyone who works out that the deposit is the cheapest way to buy a
        # twenty-litre bottle at cost.
        if bottle_deposit > ZERO:
            from services import customer_bottle_service

            await customer_bottle_service.assert_can_hold(
                session, user=user, additional=customer_bottle_service.bottles_in(items)
            )

        if is_first_order and bottle_deposit > ZERO:
            # **One bottle only.** Against the whole deposit, a first order of
            # six 20 L bottles cost the platform KSH 540 out of pure margin, and
            # the cheapest way to claim the maximum was to order bottles you did
            # not want and hand them straight back.
            one_bottle = min(cheapest_bottle_deposit(items), bottle_deposit)
            welcome_discount = _money(one_bottle * welcome_discount_rate())
            is_welcome_offer = welcome_discount > ZERO

    # ── Surcharges ──────────────────────────────────────────────────────────
    payload_surcharge = ZERO
    free_units = config.get_int("payload_free_units")
    if total_quantity > free_units:
        payload_surcharge = _money(
            Decimal(total_quantity - free_units) * config.get_decimal("payload_surcharge_per_unit")
        )

    staircase_surcharge = ZERO
    if user is not None:
        floor_level = int(_d(getattr(user, "floor_level", 0)))
        has_elevator = bool(getattr(user, "has_elevator", False))
        free_floors = config.get_int("staircase_free_floors")
        if floor_level > free_floors and not has_elevator:
            staircase_surcharge = _money(
                Decimal(floor_level - free_floors) * config.get_decimal("staircase_surcharge_per_floor")
            )

    # ── Platform fees ───────────────────────────────────────────────────────
    service_fee = service_fee_for(vendor_type)
    surge_active = is_surge_active()
    surge_fee = _money(config.get_decimal("surge_fee")) if surge_active else ZERO

    # Platform margin taken **out of** the delivery fee, on both vendor types.
    # It is not added to `gross` — the customer pays the delivery fee they were
    # shown, and this is how that fee is divided. Adding it beside the fee made
    # the rendered line understate what was charged.
    markup_rate = config.get_decimal(
        "wholesale_delivery_markup_rate" if vendor_type == "wholesale_b2b"
        else "retail_delivery_markup_rate"
    )
    delivery_markup = _money(delivery_fee * markup_rate)

    # ── Outstanding debt ────────────────────────────────────────────────────
    # A cancellation penalty or an approved staircase charge from an earlier
    # order. It is collected here, as a visible line, and cleared by
    # `create_order`. `debt_balance` used to be write-only: nothing anywhere
    # decremented it and any positive value refused every subsequent quote, so a
    # customer who cancelled one accepted order was locked out of the platform
    # permanently over KSH 50. Above `max_debt_before_block` it still refuses —
    # at that point the platform is extending credit, not collecting change.
    debt_settlement = ZERO
    if user is not None:
        outstanding = _money(_d(getattr(user, "debt_balance", 0)))
        if ZERO < outstanding < max_debt_before_block():
            debt_settlement = outstanding

    # `delivery_markup` is **not** here: it comes out of `delivery_fee`, which
    # is already in this sum. Adding it too would charge the customer the
    # platform's margin twice and make the rendered delivery line understate
    # itself.
    gross = _money(
        product_subtotal
        + delivery_fee
        + service_fee
        + surge_fee
        + payload_surcharge
        + staircase_surcharge
        + bottle_deposit
        + debt_settlement
    )

    # ── Paying by M-Pesa instead of cash ────────────────────────────────────
    # A discount, never a cash surcharge. Arithmetically identical; behaviourally
    # not close. A surcharge reads as a penalty for paying the way most of this
    # market pays and costs goodwill the platform cannot spare, while the same
    # money framed as a reward steers volume to the method that costs nothing to
    # police. Set `mpesa_payment_discount` to 0 to remove the steer entirely.
    mpesa_discount = ZERO
    if payment_method != "cash":
        mpesa_discount = _money(min(config.get_decimal("mpesa_payment_discount"), gross))

    # ── Discounts ───────────────────────────────────────────────────────────
    # Welcome discount first (it reduces the deposit component), then wallet
    # credit against the remainder. Order matters: reversing it lets the wallet
    # over-discount when both apply.
    after_welcome = _money(gross - welcome_discount - mpesa_discount)

    wallet_discount = ZERO
    if apply_wallet:
        balance = (
            wallet_balance_override
            if wallet_balance_override is not None
            else _d(getattr(user, "wallet_balance", 0) if user else 0)
        )
        if balance > ZERO:
            headroom = after_welcome - min_chargeable_total()
            if headroom > ZERO:
                wallet_discount = _money(min(balance, headroom))

    # Whole shillings: M-Pesa cannot push a fraction, and persisting anything
    # else would reintroduce the charged-vs-recorded drift this module exists to
    # eliminate.
    total = (after_welcome - wallet_discount).quantize(WHOLE, rounding=ROUND_HALF_UP)
    if total < min_chargeable_total():
        total = min_chargeable_total()

    revenue = calculate_revenue_splits(
        product_total=product_subtotal,
        delivery_fee=delivery_fee,
        vendor_type=vendor_type,
        bottle_deposit=bottle_deposit,
        rider_surcharges=payload_surcharge + staircase_surcharge,
        delivery_type=delivery_type,
        welcome_discount=welcome_discount,
        debt_settlement=debt_settlement,
        payment_method=payment_method,
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
        debt_settlement=debt_settlement,
        welcome_discount=welcome_discount,
        mpesa_discount=mpesa_discount,
        wallet_discount=wallet_discount,
        total=total,
        surge_active=surge_active,
        is_welcome_offer=is_welcome_offer,
        revenue=revenue,
    )


def validate_quote(quote: OrderQuote, items: list, *, user=None, vendor=None) -> None:
    """Every gate that must pass before money moves.

    Called *before* the STK push so a validation failure can never leave the
    customer debited with no order (see H8). `create_order` calls it again under
    its row lock, because stock can change in between.

    `vendor` is optional so a caller that has priced without loading the row
    still validates everything else; every checkout path passes it.
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

    # 3. Outstanding debt. Below the ceiling it is collected on this order
    #    (`quote.debt_settlement`) rather than refused; only a balance the
    #    platform is no longer willing to carry blocks checkout, and the message
    #    names the mechanism instead of leaving the customer with no way out.
    if user is not None:
        debt = _money(_d(getattr(user, "debt_balance", 0)))
        ceiling = max_debt_before_block()
        if debt >= ceiling:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"You have an outstanding balance of KSH {debt:.0f}, which is at "
                    f"the KSH {ceiling:.0f} limit. Contact support to clear it — "
                    "smaller balances are added to your next order automatically."
                ),
            )

    # 4. Self-dealing.
    if user is not None and quote.vendor_id is not None:
        # Vendor identity is checked in create_order where the Vendor row is
        # loaded; nothing to assert here without another query.
        pass

    # 5. The store's own minimum, on the goods rather than the total — see
    #    `vendor_availability.assert_meets_minimum`. Here rather than beside the
    #    open/closed check because this one is basket arithmetic, and putting it
    #    in `validate_quote` reaches the quote, the pre-push validation and
    #    `create_order`'s locked re-check without three call sites.
    if vendor is not None:
        from services import vendor_availability

        vendor_availability.assert_meets_minimum(vendor, quote.product_subtotal)

    if quote.total < min_chargeable_total():
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
