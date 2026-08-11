from fastapi import APIRouter, Query
from decimal import Decimal

from utils.money import money_str

router = APIRouter()


@router.get("/delivery-fee")
async def preview_delivery_fee(
    lat_from: float = Query(..., description="Pickup latitude"),
    lng_from: float = Query(..., description="Pickup longitude"),
    lat_to: float = Query(..., description="Dropoff latitude"),
    lng_to: float = Query(..., description="Dropoff longitude"),
    vendor_type: str = Query("retail_refill", description="Vendor business type: retail_refill or wholesale_b2b"),
    vehicle_class: str = Query("motorbike", description="Vehicle class: motorbike, tuktuk, or truck"),
    vendor_id: str = Query(None, description="Optional Vendor ID for wholesale specific delivery fees"),
    delivery_type: str = Query("quick_swap", description="Dual-tier logic: quick_swap or keep_my_bottle")
):
    """
    Public preview endpoint — no auth required.
    Returns the tiered delivery fee, distance, estimated time, and vehicle class
    using the V6 Haversine + Vehicle Pricing engine.
    """
    from services.order_service import calculate_delivery_fee, calculate_revenue_splits, is_surge_active
    from services import delivery_types
    from services.dispatch_policy import DispatchPolicy
    from db.session import AsyncSessionLocal
    from models.vendor_model import Vendor

    wholesale_base = Decimal("0")
    wholesale_per_km = Decimal("0")
    if vendor_type == "wholesale_b2b" and vendor_id:
        async with AsyncSessionLocal() as session:
            vendor = await session.get(Vendor, vendor_id)
            if vendor:
                wholesale_base = Decimal(str(vendor.wholesale_base_delivery_fee or 0))
                wholesale_per_km = Decimal(str(vendor.wholesale_per_km_fee or 0))

    result = calculate_delivery_fee(
        lat_from, lng_from, lat_to, lng_to,
        vendor_type=vendor_type,
        vehicle_class=vehicle_class,
        wholesale_base=wholesale_base,
        wholesale_per_km=wholesale_per_km,
        delivery_type=delivery_type
    )

    result_quick_swap = calculate_delivery_fee(
        lat_from, lng_from, lat_to, lng_to,
        vendor_type=vendor_type,
        vehicle_class=vehicle_class,
        wholesale_base=wholesale_base,
        wholesale_per_km=wholesale_per_km,
        delivery_type=delivery_types.EXCHANGE
    )

    result_refill_mine = calculate_delivery_fee(
        lat_from, lng_from, lat_to, lng_to,
        vendor_type=vendor_type,
        vehicle_class=vehicle_class,
        wholesale_base=wholesale_base,
        wholesale_per_km=wholesale_per_km,
        delivery_type=delivery_types.REFILL_MINE
    )

    # Also preview the revenue splits for transparency
    revenue = calculate_revenue_splits(
        product_total=0,  # Preview mode — no product total yet
        delivery_fee=result["fee"],
        vendor_type=vendor_type,
        delivery_type=delivery_type
    )

    # The accessor, so `within_range` below answers the same question checkout
    # will answer. Read off the dataclass default it stated the shipped radius
    # while checkout enforced the configured one.
    max_distance_km = DispatchPolicy.max_distance_km(vendor_type)

    return {
        "delivery_fee": money_str(result["fee"]),
        # One fee per option, so the cart can show the customer what each choice
        # costs *before* they choose rather than after. `new_bottle` travels the
        # same single leg as an exchange — the difference there is the
        # refundable deposit, which is a quote line, not a delivery cost.
        "exchange_fee": money_str(result_quick_swap["fee"]),
        "new_bottle_fee": money_str(result_quick_swap["fee"]),
        "refill_mine_fee": money_str(result_refill_mine["fee"]),
        # Retired names, still served so an app in somebody's pocket keeps
        # rendering a price rather than falling back to a hardcoded one.
        "quick_swap_fee": money_str(result_quick_swap["fee"]),
        "keep_my_bottle_fee": money_str(result_quick_swap["fee"]),
        "distance_km": result["distance_km"],
        "estimated_minutes": result["estimated_minutes"],
        "vehicle_class": result["vehicle_class"],
        "service_fee": money_str(revenue["service_fee"]),
        # Surge was already being charged and recorded but never disclosed, so the
        # customer had no way to understand a peak-hour price difference.
        "surge_fee": money_str(revenue["surge_fee"]),
        "surge_active": is_surge_active(),
        # Lets the client explain an out-of-range address before checkout.
        "max_distance_km": float(max_distance_km),
        "within_range": float(result["distance_km"]) <= float(max_distance_km),
    }
