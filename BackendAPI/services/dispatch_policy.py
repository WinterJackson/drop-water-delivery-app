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

from fastapi import HTTPException

from services import platform_config_service as config


@dataclass
class DispatchPolicy:
    # Defaults, mirrored in `platform_config_service.SPECS`. Read through the
    # accessors below, never directly — a direct read silently ignores whatever
    # the owners have configured.
    RETAIL_MAX_DISTANCE_KM: float = 2.0
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
    def vehicle_pricing(cls, vehicle_class: str) -> dict:
        """Wholesale base and per-km rates for a vehicle class."""
        known = vehicle_class if vehicle_class in cls.VEHICLE_CAPACITIES else "tuktuk"
        return {
            "base": float(config.get(f"wholesale_{known}_base")),
            "per_km": float(config.get(f"wholesale_{known}_per_km")),
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

        # 3. Retail Rules
        if vendor_type == "retail_refill":
            limit = cls.retail_max_distance_km()
            if distance_km > limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Distance {distance_km:.1f}km exceeds the single-trip retail limit of {limit:g}km. Please select a closer vendor."
                )
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
    def get_delivery_fee(cls, distance_km: float, vendor_type: str, vehicle_class: str, wholesale_base: float = 0.0, wholesale_per_km: float = 0.0, delivery_type: str = "quick_swap") -> float:
        """Returns the calculated delivery fee based on vendor type and vehicle."""
        if vendor_type == "wholesale_b2b":
            # A vendor's own negotiated rate takes precedence over the platform's.
            if wholesale_base > 0 or wholesale_per_km > 0:
                return round(wholesale_base + (wholesale_per_km * distance_km), 2)

            pricing = cls.vehicle_pricing(vehicle_class)
            return round(pricing["base"] + (pricing["per_km"] * distance_km), 2)

        base = float(config.get("retail_delivery_base_fee"))
        if delivery_type == "keep_my_bottle":
            premium = float(config.get("keep_my_bottle_base_premium"))
            per_km = float(config.get("keep_my_bottle_per_km"))
            return round(base + premium + (per_km * distance_km), 2)

        return round(base + (float(config.get("retail_delivery_per_km")) * distance_km), 2)
