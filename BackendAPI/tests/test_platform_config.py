"""The business model as data — bounds, invariants, and the preview.

Every number the platform earns from used to be a Python constant. It is now a
row an administrator can change from a browser, and that trade is only safe
because of what is tested here:

* a value outside its range is a **refusal with a sentence**, not a saved row;
* the cross-field rules (a platinum rider must pay *less* commission, the
  commissions together cannot take the whole order) hold against the *merged*
  configuration, not just the fields that were submitted;
* the preview prices the proposal through the same `calculate_revenue_splits` a
  real quote uses, so what an owner approves is what customers are charged;
* the legacy constant names still resolve, because four modules import them.

The arithmetic itself is covered by `test_pricing_parity.py` and
`test_delivery_fee.py`. This file is about what happens when somebody types the
wrong thing into the screen that moves it.
"""
import ast
import pathlib
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services import platform_config_service as config

BACKEND = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_config_cache():
    """The cache is module-global. A test that leaves a proposal in it would
    price every later test's order against that proposal."""
    before = (config._cache.values, config._cache.version, config._cache.stamp, config._cache.loaded_at)
    config._cache.values = {}
    yield
    (
        config._cache.values,
        config._cache.version,
        config._cache.stamp,
        config._cache.loaded_at,
    ) = before


# ── The registry itself ───────────────────────────────────────────────────


def test_every_setting_has_a_key_a_label_and_a_group_that_exists():
    """The screen renders from `describe()`. A spec with a group the labels map
    does not know renders under a raw slug like `bottles`, which reads as a bug
    in a screen about money."""
    keys = [spec.key for spec in config.SPECS]
    assert len(keys) == len(set(keys)), "duplicate setting key"

    for spec in config.SPECS:
        assert spec.label, f"{spec.key} has no label"
        assert spec.group in config.GROUP_LABELS, f"{spec.key} is in unknown group {spec.group}"
        assert spec.kind in {"rate", "money", "int", "bool", "windows", "deposits"}


def test_every_numeric_setting_is_bounded():
    """An unbounded number on this screen is a 5000% commission one keystroke
    away. `describe()` also feeds the input's min/max attributes, so an absent
    bound is silently permissive in the browser too."""
    unbounded = [
        spec.key
        for spec in config.SPECS
        if spec.kind in {"rate", "money", "int"}
        and (spec.minimum is None or spec.maximum is None)
    ]
    assert unbounded == [], f"these settings have no bounds: {unbounded}"


def test_describe_reports_whether_a_value_is_still_the_shipped_default():
    """"We chose 5%" and "nobody has ever touched this" are indistinguishable on
    screen without it, and they call for different conversations."""
    described = {row["key"]: row for row in config.describe()}
    assert described["retail_service_fee"]["is_default"] is True

    config._cache.values = {"retail_service_fee": 25.0}
    described = {row["key"]: row for row in config.describe()}
    assert described["retail_service_fee"]["is_default"] is False
    assert described["retail_service_fee"]["value"] == 25.0


# ── Single-field bounds ───────────────────────────────────────────────────


def test_a_rate_entered_as_a_percentage_is_refused_with_the_reason():
    """`5` where `0.05` was meant is the single most likely mistake on this
    screen, and the message has to say so — "invalid value" teaches nobody."""
    with pytest.raises(ValueError) as excinfo:
        config.validate_one("retail_vendor_commission_rate", 5.0)

    message = str(excinfo.value)
    assert "0.05" in message and "5%" in message


def test_negative_money_and_unknown_keys_are_refused():
    with pytest.raises(ValueError):
        config.validate_one("retail_service_fee", -1)
    with pytest.raises(ValueError, match="not a platform setting"):
        config.validate_one("retail_service_fee_v2", 12)


def test_a_bool_setting_will_not_accept_a_string():
    """`"false"` is truthy in Python. Coercing it would silently switch vendor
    gating *on* for the whole platform."""
    with pytest.raises(ValueError):
        config.validate_one("require_vendor_verification", "false")
    assert config.validate_one("require_vendor_verification", True) is True


def test_a_peak_window_that_never_elapses_is_refused():
    """`[22, 6]` looks like "ten at night until six" and is in fact empty, so
    surge would silently never apply."""
    with pytest.raises(ValueError, match="never elapses"):
        config.validate_one("peak_hours", [[22, 6]])

    assert config.validate_one("peak_hours", [[6, 8], [17, 19]]) == [[6, 8], [17, 19]]
    assert config.validate_one("peak_hours", []) == []


def test_bottle_deposits_are_keyed_by_capacity_and_kept_as_strings():
    """JSON object keys are strings; the lookup in `price_sample` and
    `pricing_service` uses `str(capacity)`. An int key here would never match."""
    cleaned = config.validate_one("bottle_deposit_by_capacity", {20: 300, "10": 150.5})
    assert cleaned == {"20": 300.0, "10": 150.5}

    with pytest.raises(ValueError):
        config.validate_one("bottle_deposit_by_capacity", {"large": 300})
    with pytest.raises(ValueError):
        config.validate_one("bottle_deposit_by_capacity", {})


# ── Cross-field invariants ────────────────────────────────────────────────


def test_platinum_riders_cannot_be_charged_more_than_standard_riders():
    """The whole point of the tier. Inverting it would quietly pay the platform's
    best riders less, and nothing downstream would complain."""
    with pytest.raises(ValueError, match="[Pp]latinum"):
        config.validate_all({"gig_platinum_rider_commission_rate": 0.20})


def test_an_invariant_is_checked_against_the_merged_configuration():
    """Submitting only the *other* half of a pair must still be refused.

    Validating the submitted subset alone would let someone lower the standard
    rate below the platinum one and break the same invariant from the other
    side.
    """
    config._cache.values = {"gig_platinum_rider_commission_rate": 0.07}
    with pytest.raises(ValueError, match="[Pp]latinum"):
        config.validate_all({"gig_rider_commission_rate": 0.05})


def test_the_order_total_cannot_be_floored_at_zero():
    """Safaricom rejects an STK push for zero, so a fully discounted order would
    become an unpayable one."""
    with pytest.raises(ValueError, match="STK push"):
        config.validate_all({"min_chargeable_total": 0})


def test_the_retail_radius_cannot_exceed_the_wholesale_one():
    """The rider search radius is derived from the wholesale figure, so a retail
    order could be accepted at a distance no rider is ever searched for."""
    with pytest.raises(ValueError, match="radius"):
        config.validate_all({"retail_max_distance_km": 40})


def test_the_commissions_together_cannot_take_the_whole_order():
    with pytest.raises(ValueError, match="entire order value"):
        config.validate_all(
            {"retail_vendor_commission_rate": 0.6, "gig_rider_commission_rate": 0.5}
        )


def test_a_valid_change_passes_and_is_returned_coerced():
    cleaned = config.validate_all({"retail_service_fee": "25", "payload_free_units": "3"})
    assert cleaned == {"retail_service_fee": 25.0, "payload_free_units": 3}


# ── Reads ─────────────────────────────────────────────────────────────────


def test_reads_fall_back_to_the_shipped_default_and_reject_unknown_keys():
    assert config.get("retail_service_fee") == 12.0
    assert config.get_decimal("retail_vendor_commission_rate") == Decimal("0.05")
    assert isinstance(config.get_decimal("retail_service_fee"), Decimal)
    assert config.get_int("payload_free_units") == 2
    assert config.get_bool("require_vendor_verification") is False

    with pytest.raises(KeyError):
        config.get("retail_service_fee_v2")


def test_temporarily_restores_the_previous_values_even_when_the_block_raises():
    """The cache is process-wide. A preview that leaves the proposal loaded would
    price every subsequent request in the process against values nobody
    approved."""
    config._cache.values = {"retail_service_fee": 12.0}

    with pytest.raises(RuntimeError):
        with config.temporarily({"retail_service_fee": 999.0}):
            assert config.get("retail_service_fee") == 999.0
            raise RuntimeError("boom")

    assert config.get("retail_service_fee") == 12.0


# ── The legacy constant names ─────────────────────────────────────────────


def test_the_old_order_service_constants_still_resolve_through_the_config():
    """`from services.order_service import RETAIL_SERVICE_FEE_KSH` appears in
    several modules and in tests. The shim keeps those working *and* makes them
    live — the point of the change is that they are no longer constants."""
    from services import order_service

    assert order_service.RETAIL_SERVICE_FEE_KSH == 12.0

    config._cache.values = {"retail_service_fee": 30.0}
    assert order_service.RETAIL_SERVICE_FEE_KSH == 30.0


def test_an_unknown_module_attribute_still_raises_attribute_error():
    """A module-level `__getattr__` that answers everything turns a typo into a
    silent `None` and an import error into a runtime one."""
    from services import order_service

    with pytest.raises(AttributeError):
        order_service.RETAIL_SERVICE_FEE_KSH_V2


def test_no_module_hardcodes_a_fee_constant_any_more():
    """The constants were removed, not shadowed. A module that re-declares one
    is a second source of truth that the admin screen cannot change — which is
    the exact defect this replaced.
    """
    offenders = []
    for directory in ("services", "routes"):
        for path in (BACKEND / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(errors="ignore"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "RETAIL_SERVICE_FEE_KSH",
                        "WHOLESALE_SERVICE_FEE_KSH",
                        "SURGE_FEE_KSH",
                        "RETAIL_VENDOR_COMMISSION",
                        "GIG_RIDER_COMMISSION",
                    }:
                        offenders.append(f"{directory}/{path.name}::{target.id}")

    assert offenders == [], f"these are configurable now, not constants: {offenders}"


# ── Pricing actually moves ────────────────────────────────────────────────


def test_a_fee_change_moves_the_customer_total_and_the_platform_take():
    """The end-to-end claim of the whole feature: change a number in the console
    and the next quote in every app is different, with no release."""
    before = config.price_sample(
        product_total=500.0, distance_km=2.0, quantity=2, bottle_capacity=20
    )

    with config.temporarily({**config.effective(), "retail_service_fee": 25.0}):
        after = config.price_sample(
            product_total=500.0, distance_km=2.0, quantity=2, bottle_capacity=20
        )

    assert Decimal(after["customer_total"]) - Decimal(before["customer_total"]) == Decimal("13")
    assert Decimal(after["platform_revenue"]) - Decimal(before["platform_revenue"]) == Decimal("13")
    # The vendor is unaffected by a platform fee — it is not taken from them.
    assert after["vendor_receives"] == before["vendor_receives"]


def test_a_commission_change_moves_the_vendor_not_the_customer():
    before = config.price_sample(
        product_total=500.0, distance_km=2.0, quantity=2, bottle_capacity=20
    )

    with config.temporarily({**config.effective(), "retail_vendor_commission_rate": 0.08}):
        after = config.price_sample(
            product_total=500.0, distance_km=2.0, quantity=2, bottle_capacity=20
        )

    assert after["customer_total"] == before["customer_total"]
    assert Decimal(after["vendor_receives"]) < Decimal(before["vendor_receives"])
    assert Decimal(after["platform_revenue"]) > Decimal(before["platform_revenue"])


def test_the_sample_quote_reports_money_as_decimal_strings():
    """Money is a decimal string end to end. A float here would be rendered
    straight onto the approval screen."""
    quote = config.price_sample(
        product_total=500.0, distance_km=2.0, quantity=2, bottle_capacity=20
    )
    for key, value in quote.items():
        if key == "vehicle_class":
            continue
        assert isinstance(value, str), f"{key} is not a string"
        Decimal(value)  # raises if it is not a decimal


# ── The endpoints ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def console(monkeypatch):
    """The real app and the real dependency graph, with a mocked session.

    The routes are gated by `require_admin(...)`, which resolves an `AdminUser`
    row — so the override is on `get_current_user` and the session, not on the
    gate itself. Overriding the gate would test nothing about it.
    """
    monkeypatch.setenv("ADMIN_2FA_REQUIRED", "false")

    from main import app
    from dependencies.dependencies import get_db
    from models.admin_model import ALL_PERMISSIONS
    from utils.verify_user_token import get_current_user

    admin = SimpleNamespace(
        id=uuid4(),
        clerk_id="admin_clerk",
        email="owner@drop.invalid",
        name="Owner",
        role="super_admin",
        permissions=list(ALL_PERMISSIONS),
        is_active=True,
        revoked_at=None,
        last_seen_at=datetime.now(timezone.utc),
    )

    result = MagicMock()
    result.scalars.return_value.first.return_value = admin
    result.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "admin_clerk", "tfa": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, db=db, admin=admin)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_the_preview_prices_a_proposal_without_saving_it(console):
    """Regression: the delta was computed over every string in the quote, and
    `vehicle_class` is a string. `Decimal("motorbike")` raises, so every call to
    the one screen that makes a pricing change safe to approve was a 500."""
    response = await console.client.post(
        "/api/admin/config/preview",
        json={"changes": {"retail_service_fee": 25.0}},
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["before"]["service_fee"] == "12.00"
    assert payload["after"]["service_fee"] == "25.00"
    assert payload["delta"]["customer_total"] == "13.00"
    # Present in the quote, absent from the deltas: it is a description.
    assert payload["before"]["vehicle_class"] == "motorbike"
    assert "vehicle_class" not in payload["delta"]

    # Nothing was written, and the process is still pricing at the old fee.
    console.db.add.assert_not_called()
    assert config.get("retail_service_fee") == 12.0


@pytest.mark.asyncio
async def test_the_preview_refuses_an_out_of_range_proposal_with_a_readable_reason(console):
    response = await console.client.post(
        "/api/admin/config/preview", json={"changes": {"retail_vendor_commission_rate": 5}}
    )

    assert response.status_code == 400
    assert "0.05" in response.json()["detail"]


@pytest.mark.asyncio
async def test_saving_an_out_of_range_value_is_refused_before_anything_is_written(console):
    response = await console.client.put(
        "/api/admin/config",
        json={
            "changes": {"gig_platinum_rider_commission_rate": 0.9},
            "reason": "Testing the guard",
        },
    )

    assert response.status_code == 400
    console.db.add.assert_not_called()
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_a_change_requires_a_reason(console):
    response = await console.client.put(
        "/api/admin/config", json={"changes": {"retail_service_fee": 13}}
    )
    assert response.status_code == 422

    response = await console.client.put(
        "/api/admin/config", json={"changes": {"retail_service_fee": 13}, "reason": "x"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_settings_screen_lists_every_setting_with_its_bounds(console):
    response = await console.client.get("/api/admin/config")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["settings"]) == len(config.SPECS)
    assert {group["key"] for group in payload["groups"]} == set(config.GROUP_LABELS)
