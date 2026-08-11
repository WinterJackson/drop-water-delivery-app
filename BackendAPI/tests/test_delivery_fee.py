"""Tests for the delivery fee calculator and DispatchPolicy engine."""
from decimal import ROUND_HALF_UP, Decimal

import pytest
from services.order_service import calculate_delivery_fee
from services.dispatch_policy import DispatchPolicy


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Retail delivery is `RETAIL_FLAT_FEE_KSH + RETAIL_PER_KM * distance`. These tests
# used to hardcode a 30.0 base, which contradicted `test_retail_flat_fee` in this
# same class asserting the constant is 50.0 — three of them had been failing since
# the flat fee changed. Derive the expectation from the constants so a future
# pricing change updates these assertions automatically instead of rotting.
RETAIL_PER_KM = 15.0


def _expected_retail_fee(distance_km: float) -> Decimal:
    """The tiered retail tariff, mirroring `DispatchPolicy.get_delivery_fee`.

    Below the short-hop threshold there is one flat fee and distance does not
    enter into it. A flat base plus per-km overcharged the next street and
    undercharged the next estate, and in a city this dense most deliveries are
    the next street.

    Computed in `Decimal`, like the thing it mirrors. Computed in `float` it
    disagreed by design: `Decimal("93.40") == 93.4` is **False**, because the
    nearest double to 93.4 is 93.40000000000000568…, and that gap is the whole
    reason the fee schedule stopped being a float.
    """
    from services import platform_config_service as config

    km = Decimal(str(distance_km))
    threshold_km = config.get_decimal("short_hop_threshold_m") / Decimal("1000")
    if km <= threshold_km:
        return _money(config.get_decimal("short_hop_delivery_fee"))
    return _money(
        config.get_decimal("retail_delivery_base_fee")
        + config.get_decimal("retail_delivery_per_km") * km
    )


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
        assert result["fee"] == _money(DispatchPolicy.RETAIL_FLAT_FEE_KSH)
        assert result["distance_km"] == 0.0
        assert result["estimated_minutes"] >= 5  # max(5, 0)

    def test_medium_distance_retail(self):
        """~3.5km apart, retail → should calculate using formula."""
        result = calculate_delivery_fee(-1.2921, 36.8219, -1.2637, 36.8069)
        assert result["fee"] == _expected_retail_fee(result["distance_km"])
        assert result["distance_km"] > 2.0
        assert result["estimated_minutes"] > 5

    def test_refilling_the_customers_own_bottle_costs_more_than_an_exchange(self):
        """It is a **round trip**, and that is the only reason it costs more.

        The rider goes to the customer, collects their bottle, carries it to the
        station and brings that same bottle back. An exchange is one leg with a
        filled bottle already on the bike.

        `new_bottle` is *not* dearer: it travels the identical single leg as an
        exchange. Its difference is the refundable deposit, which is a line on
        the quote, not a cost of delivery. The old test asserted the opposite,
        because `keep_my_bottle` conflated the two.
        """
        exchange = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069, delivery_type="exchange"
        )
        refill_mine = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069, delivery_type="refill_mine"
        )
        new_bottle = calculate_delivery_fee(
            -1.2921, 36.8219, -1.2637, 36.8069, delivery_type="new_bottle"
        )

        assert refill_mine["fee"] > exchange["fee"]
        assert new_bottle["fee"] == exchange["fee"]

    def test_a_short_hop_is_flat_unless_it_is_a_round_trip(self):
        """400 m of riding done three times is not a short hop."""
        from services import platform_config_service as config

        exchange = calculate_delivery_fee(
            -1.2864, 36.8172, -1.2828, 36.8172, delivery_type="exchange"
        )
        refill_mine = calculate_delivery_fee(
            -1.2864, 36.8172, -1.2828, 36.8172, delivery_type="refill_mine"
        )

        assert exchange["distance_km"] * 1000 <= float(config.get("short_hop_threshold_m"))
        assert exchange["fee"] == float(config.get("short_hop_delivery_fee"))
        assert refill_mine["fee"] > exchange["fee"]

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
        # The fee is money, so `Decimal`. The distance is a measurement off
        # PostGIS and stays a `float` — nothing is charged per metre, and no
        # ledger holds it.
        assert isinstance(result["fee"], Decimal)
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
        """The radii the platform promises: 2.5 km retail, 15 km wholesale.

        These are the *shipped defaults*. Reading them is legitimate here and
        nowhere that serves a request — see the guard below.
        """
        assert DispatchPolicy.RETAIL_MAX_DISTANCE_KM == 2.5
        assert DispatchPolicy.WHOLESALE_MAX_DISTANCE_KM == 15.0
        assert DispatchPolicy.WHOLESALE_MOQ_KG == 100.0

    def test_the_dataclass_and_the_settings_agree_on_the_radii(self):
        """Two declarations of one figure, and they must not drift.

        The dataclass default is what a fresh deployment with no rows uses; the
        `SettingSpec` default is what the registry hands out. They are written
        in different files and nothing but this connects them.
        """
        from services import platform_config_service as config

        assert float(config.DEFAULTS["retail_max_distance_km"]) == \
            DispatchPolicy.RETAIL_MAX_DISTANCE_KM
        assert float(config.DEFAULTS["wholesale_max_distance_km"]) == \
            DispatchPolicy.WHOLESALE_MAX_DISTANCE_KM

    def test_a_fractional_radius_survives_the_settings_coercer(self):
        """2.5 is the reason both radii are `decimal` and not `int`.

        Under `int` the coercer's `int(value)` would have taken 2.5 to **2**
        silently — a truncation rather than a refusal, on the figure that
        decides which stores a customer can see at all.
        """
        from services import platform_config_service as config

        assert config.validate_one("retail_max_distance_km", 2.5) == 2.5
        assert config.validate_one("wholesale_max_distance_km", 15.5) == 15.5

    def test_the_rider_search_ring_widens_with_the_radius(self):
        """The H3 pre-filter is derived, not hardcoded.

        It was a literal 5, so raising the radius left the rider search looking
        at the old area — orders accepted, then nobody found. At 2.5 km the ring
        has to cover more ground than it did at 2.
        """
        ring = DispatchPolicy.get_h3_k_ring("retail_refill")
        # A res-8 cell edge is ~461 m; 2.5 km needs at least five rings out.
        assert ring >= 5, f"a {DispatchPolicy.RETAIL_MAX_DISTANCE_KM}km radius needs more than {ring} rings"
        assert ring * 461.0 >= DispatchPolicy.retail_max_distance_km() * 1000.0


#: The dataclass attributes that have a `Platform_Settings` row behind them, and
#: the accessor that reads it. Touching the attribute instead skips the row.
CONFIGURABLE_DEFAULTS = {
    "RETAIL_MAX_DISTANCE_KM": "DispatchPolicy.max_distance_km(vendor_type)",
    "WHOLESALE_MAX_DISTANCE_KM": "DispatchPolicy.max_distance_km(vendor_type)",
    "WHOLESALE_MOQ_KG": "DispatchPolicy.wholesale_moq_kg()",
    "RETAIL_FLAT_FEE_KSH": "config.get_decimal('short_hop_delivery_fee')",
}

#: Deliberately *not* configurable, and documented as such on the dataclass:
#: where a rider registers to serve is a different question from how far one
#: order may travel. Reading these directly is correct.
FIXED_DEFAULTS = {
    "RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM",
    "WHOLESALE_RIDER_REGISTRATION_MAX_RADIUS_KM",
    "VEHICLE_CAPACITIES",
}


def _direct_default_reads(source: str, label: str) -> list[str]:
    """Every `DispatchPolicy.SOME_DEFAULT` in `source` that has a settings row."""
    import ast

    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "DispatchPolicy"
            and node.attr in CONFIGURABLE_DEFAULTS
        ):
            found.append(
                f"{label}:{node.lineno} DispatchPolicy.{node.attr} — use "
                f"{CONFIGURABLE_DEFAULTS[node.attr]}"
            )
    return found


def test_nothing_that_serves_a_request_reads_a_shipped_default():
    """`DispatchPolicy` says "read through the accessors, never directly", and
    four modules did not.

    A direct read is invisible: the value is right, the types are right, and the
    tests pass — until an administrator moves the row on the console, at which
    point the two halves of the platform disagree about the same rule. Discovery
    used the shipped 2 km while checkout used the configured radius, so widening
    the radius delivered further without letting anyone *find* the store that
    had come into range; and the cart quoted the shipped wholesale minimum
    beside an enforcement of the configured one.
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []

    for directory in ("routes", "services", "jobs"):
        for path in sorted((backend / directory).rglob("*.py")):
            if path.name == "dispatch_policy.py":
                continue  # where the defaults and their accessors are defined
            offenders += _direct_default_reads(
                path.read_text(), str(path.relative_to(backend))
            )

    assert not offenders, (
        "a shipped default read on a request path, so the console setting is "
        "silently ignored:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_recognises_the_read_it_looks_for():
    """The negative case, in memory — a structural test that has never been
    shown to fail is a test that passes because it matches nothing."""
    caught = _direct_default_reads(
        "limit = float(DispatchPolicy.RETAIL_MAX_DISTANCE_KM)\n", "sample.py"
    )
    assert len(caught) == 1 and "max_distance_km" in caught[0]


def test_the_guard_does_not_flag_the_accessors_that_replaced_them():
    assert _direct_default_reads(
        "limit = DispatchPolicy.max_distance_km(vendor_type)\n"
        "moq = DispatchPolicy.wholesale_moq_kg()\n",
        "sample.py",
    ) == []


def test_the_guard_leaves_the_deliberately_fixed_defaults_alone():
    """Rider registration radius is documented as not configurable. Flagging it
    would push the next person to invent a settings row the platform has
    decided against."""
    assert _direct_default_reads(
        "r = DispatchPolicy.RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM\n"
        "c = DispatchPolicy.VEHICLE_CAPACITIES['motorbike']\n",
        "sample.py",
    ) == []


def test_every_configurable_default_named_above_has_its_settings_row():
    """The guard is only worth anything if these really are configurable."""
    from services import platform_config_service as config

    for key in ("retail_max_distance_km", "wholesale_max_distance_km",
                "wholesale_moq_kg", "short_hop_delivery_fee"):
        assert key in config.SPEC_BY_KEY, f"{key} is no longer a settings row"


def test_the_fixed_defaults_are_still_absent_from_the_settings():
    """The other half. If one of these ever gains a row it must gain an
    accessor and move into the guarded set, not stay readable as a constant."""
    from services import platform_config_service as config

    assert "rider_registration_max_radius_km" not in config.SPEC_BY_KEY
    assert FIXED_DEFAULTS  # named here so the distinction is documented, not implied
