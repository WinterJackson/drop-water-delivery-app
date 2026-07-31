"""Tests for the delivery fee calculator and DispatchPolicy engine."""
import pytest
from services.order_service import calculate_delivery_fee
from services.dispatch_policy import DispatchPolicy


# Retail delivery is `RETAIL_FLAT_FEE_KSH + RETAIL_PER_KM * distance`. These tests
# used to hardcode a 30.0 base, which contradicted `test_retail_flat_fee` in this
# same class asserting the constant is 50.0 — three of them had been failing since
# the flat fee changed. Derive the expectation from the constants so a future
# pricing change updates these assertions automatically instead of rotting.
RETAIL_PER_KM = 15.0


def _expected_retail_fee(distance_km: float) -> float:
    return round(DispatchPolicy.RETAIL_FLAT_FEE_KSH + RETAIL_PER_KM * distance_km, 2)


class TestCalculateDeliveryFee:
    """Pure function tests — no DB required."""

    def test_short_distance_base_fee(self):
        """Close coordinates → should return calculated fee."""
        # Nairobi CBD (~0.67km apart)
        result = calculate_delivery_fee(-1.2864, 36.8172, -1.2804, 36.8165)
        assert result["fee"] == _expected_retail_fee(result["distance_km"])
        assert result["distance_km"] < 2.0
        assert result["estimated_minutes"] >= 2  # max(5, ceil(0.67*3)) = 5

    def test_zero_distance(self):
        """Same point → should return base flat fee."""
        result = calculate_delivery_fee(-1.2921, 36.8219, -1.2921, 36.8219)
        assert result["fee"] == DispatchPolicy.RETAIL_FLAT_FEE_KSH
        assert result["distance_km"] == 0.0
        assert result["estimated_minutes"] >= 5  # max(5, 0)

    def test_medium_distance_retail(self):
        """~3.5km apart, retail → should calculate using formula."""
        result = calculate_delivery_fee(-1.2921, 36.8219, -1.2637, 36.8069)
        assert result["fee"] == _expected_retail_fee(result["distance_km"])
        assert result["distance_km"] > 2.0
        assert result["estimated_minutes"] > 5

    def test_keep_my_bottle_costs_more_than_quick_swap(self):
        """Keeping the bottle adds a handling premium to the delivery fee."""
        quick = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069, delivery_type="quick_swap"
        )
        keep = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069, delivery_type="keep_my_bottle"
        )
        assert keep["fee"] > quick["fee"]

    def test_wholesale_pricing_uses_per_km(self):
        """Wholesale orders should use base + per_km pricing."""
        result = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069,
            vendor_type="wholesale_b2b",
            vehicle_class="tuktuk",
        )
        assert result["fee"] > 50.0  # Should be base + per_km * distance
        assert result["vehicle_class"] == "tuktuk"

    def test_null_coordinates_fallback(self):
        """Missing coords → should return safe default."""
        result = calculate_delivery_fee(0.0, 0.0, -1.2921, 36.8219)
        # 0,0 passes through since lat_from=0.0 is falsy → hits the null guard
        assert "fee" in result
        assert "distance_km" in result
        assert "estimated_minutes" in result

    def test_return_shape(self):
        """Result dict must have all required keys."""
        result = calculate_delivery_fee(-1.2921, 36.8219, -1.3000, 36.8300)
        assert "fee" in result
        assert "distance_km" in result
        assert "estimated_minutes" in result
        assert "vehicle_class" in result
        assert isinstance(result["fee"], float)
        assert isinstance(result["distance_km"], float)
        assert isinstance(result["estimated_minutes"], int)


class TestDispatchPolicy:
    """Verify the core dispatch constants and vehicle classification."""

    def test_vehicle_classification(self):
        assert DispatchPolicy.get_vehicle_class(1) == "motorbike"
        assert DispatchPolicy.get_vehicle_class(4) == "motorbike"
        assert DispatchPolicy.get_vehicle_class(5) == "tuktuk"
        assert DispatchPolicy.get_vehicle_class(20) == "tuktuk"
        assert DispatchPolicy.get_vehicle_class(21) == "truck"

    def test_rider_registration_radius(self):
        # Renamed when wholesale gained its own (15 km) registration radius.
        assert DispatchPolicy.RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM == 2.0
        assert DispatchPolicy.WHOLESALE_RIDER_REGISTRATION_MAX_RADIUS_KM == 15.0

    def test_retail_flat_fee(self):
        assert DispatchPolicy.RETAIL_FLAT_FEE_KSH == 50.0

    def test_documented_service_radii(self):
        """The radii the READMEs promise customers."""
        assert DispatchPolicy.RETAIL_MAX_DISTANCE_KM == 2.0
        assert DispatchPolicy.WHOLESALE_MAX_DISTANCE_KM == 15.0
        assert DispatchPolicy.WHOLESALE_MOQ_KG == 100.0
