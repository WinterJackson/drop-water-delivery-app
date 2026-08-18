"""Where an order may go, on what, and for how much.

The numeric policy — delivery rates, radii, the wholesale minimum order — now
comes from `platform_config_service`, so the owners can change it from the admin
console without a deploy. The class attributes below are the **shipped
defaults**, kept here so the module is readable on its own and so a running
process still prices correctly with the settings table unreachable.

Reads are synchronous by design; whatever is about to price an order awaits
`platform_config_service.ensure_fresh(session)` first. See that module.

Capacities are *not* configurable. How many 20-litre bottles fit on a motorbike
is a fact about motorbikes, and a console field that let someone set it to 40
would produce orders no rider can physically accept.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException

from services import platform_config_service as config
from utils.money import MoneyIn

#: Money is quantized to two places, half-up, exactly as `utils.money.money_str`
#: does on the way out — so a fee computed here and the same fee rendered on a
#: screen can never differ by a cent.
CENTS = Decimal("0.01")


def _money(value: MoneyIn) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _km(distance_km: float) -> Decimal:
    """A distance as `Decimal`, so it can be multiplied by a rate.

    Distance stays a `float` everywhere else and should: it is a measurement off
    PostGIS, not money, and no ledger holds it. It only becomes `Decimal` at the
    moment it is multiplied by a shilling rate — which is the moment a float
    would put binary error into a figure somebody is charged.
    """
    return Decimal(str(distance_km))


@dataclass
class DispatchPolicy:
    # Defaults, mirrored in `platform_config_service.SPECS`. Read through the
    # accessors below, never directly — a direct read silently ignores whatever
    # the owners have configured.
    #: 2.5 km for retail refill, 15 km for wholesale. One figure each, set by
    #: the platform: it is what discovery searches, what checkout enforces and
    #: what the rider search covers. A store does not set its own.
    RETAIL_MAX_DISTANCE_KM: float = 2.5
    WHOLESALE_MAX_DISTANCE_KM: float = 15.0
    WHOLESALE_MOQ_KG: float = 100.0
    RETAIL_FLAT_FEE_KSH: float = 50.0

    # Not configurable: where a rider registers to serve is a different question
    # from how far a single order may travel.
    RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM: float = 2.0
    WHOLESALE_RIDER_REGISTRATION_MAX_RADIUS_KM: float = 15.0

    #: Physical limits, not business policy. Quantities are bottles.
    VEHICLE_CAPACITIES = {
        "motorbike": 4,
        "tuktuk": 20,
        "truck": 200,
    }

    # ── Configurable accessors ────────────────────────────────────────────

    @classmethod
    def retail_max_distance_km(cls) -> float:
        return float(config.get("retail_max_distance_km"))

    @classmethod
    def wholesale_max_distance_km(cls) -> float:
        return float(config.get("wholesale_max_distance_km"))

    @classmethod
    def wholesale_moq_kg(cls) -> float:
        return float(config.get("wholesale_moq_kg"))

    @classmethod
    def max_distance_km(cls, vendor_type: str) -> float:
        return (
            cls.wholesale_max_distance_km()
            if vendor_type == "wholesale_b2b"
            else cls.retail_max_distance_km()
        )

    @classmethod
    def vehicle_pricing(cls, vehicle_class: str) -> dict[str, Decimal]:
        """Wholesale base and per-km rates for a vehicle class, as `Decimal`."""
        known = vehicle_class if vehicle_class in cls.VEHICLE_CAPACITIES else "tuktuk"
        return {
            "base": config.get_decimal(f"wholesale_{known}_base"),
            "per_km": config.get_decimal(f"wholesale_{known}_per_km"),
        }

    # ── Policy ────────────────────────────────────────────────────────────

    @classmethod
    def get_vehicle_class(cls, total_quantity: int) -> str:
        """Determines the required vehicle class based on quantity payload."""
        if total_quantity <= cls.VEHICLE_CAPACITIES["motorbike"]:
            return "motorbike"
        elif total_quantity <= cls.VEHICLE_CAPACITIES["tuktuk"]:
            return "tuktuk"
        elif total_quantity <= cls.VEHICLE_CAPACITIES["truck"]:
            return "truck"
        else:
            raise ValueError(f"Payload capacity exceeded. Maximum {cls.VEHICLE_CAPACITIES['truck']} items per trip.")

    @classmethod
    def get_max_distance_m(cls, vendor_type: str, action: str = "delivery") -> float:
        """
        Returns max distance in meters for ST_DWithin constraints.
        action can be "delivery" or "rider_search".
        """
        if action == "rider_search":
            return cls.max_distance_km(vendor_type) * 1000.0

        # Action is "delivery" (checkout restriction)
        if vendor_type == "retail_refill":
            return cls.retail_max_distance_km() * 1000.0
        else:
            # Wholesale deliveries are not distance-capped at checkout.
            return None

    @classmethod
    def get_h3_k_ring(cls, vendor_type: str) -> int:
        """Grid search ring radius, derived from the configured radius.

        A res-8 cell edge is ~461 m. This used to be a hardcoded 5 or 22, so
        raising the delivery radius left the rider search looking at the old
        area — orders would be accepted and then find nobody.
        """
        radius_m = cls.max_distance_km(vendor_type) * 1000.0
        return max(1, int(radius_m / 461.0) + 1)

    @classmethod
    def validate_cart_preflight(cls, vendor_type: str, distance_km: float, total_quantity: int, total_weight_kg: float = 0.0, is_wholesale_capable: bool = False):
        """
        Enforce distance and payload restrictions prior to checkout processing.
        """
        # 1. Capacity Rules
        try:
            cls.get_vehicle_class(total_quantity)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 2. Wholesale Business Rules
        if vendor_type == "wholesale_b2b":
            moq = cls.wholesale_moq_kg()
            if total_weight_kg < moq:
                raise HTTPException(status_code=400, detail=f"Wholesale requires a minimum payload of {moq:g}kg. Current payload: {total_weight_kg}kg. Please add more items.")

        # 3. Service radius — every vendor type, not just retail.
        #
        # This branch used to sit inside `if vendor_type == "retail_refill"`, so
        # the 15 km wholesale radius was enforced *nowhere on the ordering path*.
        # Discovery bounded it (`query_service._within_service_radius`) and the
        # rider search bounded it, but a wholesale basket that reached checkout
        # by any other route — a favourite, a past order, a shared link, a cart
        # that outlived a change of address — was priced and accepted at any
        # distance at all. The one figure that is supposed to mean "what this
        # platform will deliver" was advisory on half the catalogue.
        #
        # A NULL `vendor_type` matched neither branch and so escaped entirely.
        # `max_distance_km` resolves it the way discovery does: anything that is
        # not wholesale is retail, the narrower of the two, because an
        # unclassified store is one nobody has decided about and the wider radius
        # would be a decision made by omission.
        limit = cls.max_distance_km(vendor_type)
        if distance_km > limit:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This store is {distance_km:.1f} km away, beyond the "
                    f"{limit:g} km delivery limit for this kind of store. "
                    "Please choose a closer vendor or update your delivery location."
                ),
            )

        # 4. Retail Rules
        if vendor_type == "retail_refill":
            motorbike_capacity = cls.VEHICLE_CAPACITIES["motorbike"]
            if total_quantity > motorbike_capacity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Retail orders are fulfilled via motorbikes which can carry a maximum of {motorbike_capacity} (20L) bottles per trip. You requested {total_quantity}."
                )

    @classmethod
    def should_auto_dispatch(cls, vendor_type: str) -> bool:
        """
        Determines whether the system should immediately trigger the automated dispatch engine.
        Enabled for both Retail and Wholesale to handle Tier 1 (In-House) -> Tier 2 (Trip Radar) switch.
        """
        return True

    @classmethod
    def get_delivery_fee(
        cls,
        distance_km: float,
        vendor_type: str,
        vehicle_class: str,
        wholesale_base: MoneyIn = 0,
        wholesale_per_km: MoneyIn = 0,
        delivery_type: str = "quick_swap",
    ) -> Decimal:
        """The delivery fee for one trip, as `Decimal`.

        Every rate here is a shilling figure off `Platform_Settings`, and the
        result is written to a `Numeric(10, 2)` column and shown to a customer
        before they pay. It used to be computed in `float` and rounded at the
        end — safe in practice, because the rounding happened before anything
        was charged, but it was the one arithmetic path on the platform that was
        not `Decimal` end to end, and "safe because of where the rounding
        happens" is a property somebody has to keep checking.
        """
        km = _km(distance_km)

        if vendor_type == "wholesale_b2b":
            # A vendor's own negotiated rate takes precedence over the platform's.
            own_base = Decimal(str(wholesale_base or 0))
            own_per_km = Decimal(str(wholesale_per_km or 0))
            if own_base > 0 or own_per_km > 0:
                return _money(own_base + own_per_km * km)

            pricing = cls.vehicle_pricing(vehicle_class)
            return _money(pricing["base"] + pricing["per_km"] * km)

        # ── Short hop: one flat fee ───────────────────────────────────────
        #
        # Urban Kenya is dense. A flat base plus per-km overcharges the next
        # street and undercharges the next estate, and the per-km component is
        # noise over 400 m. Below the threshold there is one number, which is
        # also the only delivery price most customers will ever see.
        #
        # `keep_my_bottle` is excluded deliberately: it is a **round trip** —
        # collect the customer's own bottle, carry it to the station, bring it
        # back — so distance is exactly what it costs, even over 400 m.
        from services import delivery_types

        round_trip = delivery_types.is_round_trip(delivery_type)

        # A threshold in metres, compared against a distance in kilometres.
        threshold_km = config.get_decimal("short_hop_threshold_m") / Decimal("1000")
        if not round_trip and km <= threshold_km:
            return _money(config.get_decimal("short_hop_delivery_fee"))

        base = config.get_decimal("retail_delivery_base_fee")
        if round_trip:
            premium = config.get_decimal("refill_mine_base_premium")
            per_km = config.get_decimal("refill_mine_per_km")
            return _money(base + premium + per_km * km)

        return _money(base + config.get_decimal("retail_delivery_per_km") * km)


def within_service_radius(user_location):
    """SQL predicate: is this store close enough to deliver to `user_location`?

    The one implementation of "may this customer see and order from this store",
    used by vendor discovery, product discovery and search alike. It lived in
    `query_service` and was reachable only from the two search endpoints, which
    is how the home screen came to show a grid of products from stores the same
    screen had just said were out of range.

    It belongs here because this module owns the two radii it measures against
    and reads them through the accessors, never the shipped defaults.

    `Vendor.location IS NOT NULL` is part of the predicate rather than a
    precondition: a store with no coordinates cannot be measured, and an
    unmeasurable store is not one a customer can be promised delivery from.

    An unclassified `vendor_type` is retail — the narrower radius — because a
    NULL is a store nobody has classified, and taking the wider one would be a
    decision made by omission. The NULL is named rather than coalesced: Postgres
    refuses `COALESCE(vendor_business_type, varchar)` outright, and `!=` alone is
    NULL for a NULL column, which would drop the store from both branches.
    """
    from sqlalchemy import and_, or_
    from geoalchemy2.functions import ST_DWithin

    from models.vendor_model import Vendor

    retail_m = DispatchPolicy.max_distance_km("retail_refill") * 1000.0
    wholesale_m = DispatchPolicy.max_distance_km("wholesale_b2b") * 1000.0

    is_wholesale = Vendor.vendor_type == "wholesale_b2b"
    is_retail = or_(Vendor.vendor_type != "wholesale_b2b", Vendor.vendor_type.is_(None))

    return and_(
        Vendor.location.isnot(None),
        or_(
            and_(is_wholesale, ST_DWithin(Vendor.location, user_location, wholesale_m)),
            and_(is_retail, ST_DWithin(Vendor.location, user_location, retail_m)),
        ),
    )
