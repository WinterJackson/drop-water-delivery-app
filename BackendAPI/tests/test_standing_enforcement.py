"""
Being signed in is not standing.

Three separate questions this platform kept confusing with authentication:

* **Is this rider still allowed to work?** An administrator suspends a rider —
  `suspended_at`, a reason, an audit row, `is_active` cleared and `is_available`
  forced off. Nothing on the rider's operational path read any of it.
  `get_verified_rider` checked `kyc_status` alone; `toggle_availability` and
  `accept_delivery_radar` checked `is_available`, which is *the rider's own
  toggle*. So the suspension was a switch its subject could flip back: go
  online, take the next radar offer, deliver. Only cash was refused, and only
  because `cod_policy` happened to read `suspended_at`.

* **Should the platform be offering them work at all?** Every rider search on
  the dispatch path filtered on `is_available` and nothing else, so suspended
  riders and riders whose KYC was `pending`/`unsubmitted`/`rejected` were pushed
  the pickup address and the customer's area for orders they could never take —
  occupying slots in a fan-out that is deliberately bounded.

* **Who is the customer allowed to see?** `POST
  /api/vendor_details_and_products` had no auth dependency at all and returned
  the owner's name, email, phone number and `preferred_payment_method` — which
  is the store's **payout destination**, not a payment method it accepts.
  `GET /api/vendors` handed out every store id, also unauthenticated.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _rider(**over):
    from models.deliverer_model import KYCStatus

    rider = MagicMock()
    rider.kyc_status = over.pop("kyc_status", KYCStatus.approved)
    rider.suspended_at = over.pop("suspended_at", None)
    rider.suspension_reason = over.pop("suspension_reason", None)
    rider.is_active = over.pop("is_active", True)
    for k, v in over.items():
        setattr(rider, k, v)
    # `is_suspended` is a real property; MagicMock would otherwise stub it.
    from models.deliverer_model import Deliverer

    rider.is_suspended = Deliverer.is_suspended.fget(rider)
    return rider


def _db(rider):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = rider
    db.execute = AsyncMock(return_value=result)
    return db


# ── The gate every operational rider route already passes through ─────────


@pytest.mark.asyncio
async def test_a_suspended_rider_cannot_reach_an_operational_route():
    from dependencies.auth_dependencies import get_verified_rider
    from datetime import datetime, timezone

    rider = _rider(suspended_at=datetime.now(timezone.utc), is_active=False)
    with pytest.raises(HTTPException) as exc:
        await get_verified_rider(user={"sub": "rider_1"}, db=_db(rider))

    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "account_suspended"


@pytest.mark.asyncio
async def test_suspension_outranks_kyc_so_the_rider_is_told_the_right_thing():
    """A suspended rider sent to VerificationWall resubmits documents that were
    never the problem, and the screen offers no way to reach anybody."""
    from datetime import datetime, timezone

    from dependencies.auth_dependencies import get_verified_rider
    from models.deliverer_model import KYCStatus

    rider = _rider(
        suspended_at=datetime.now(timezone.utc),
        kyc_status=KYCStatus.pending,
        suspension_reason="Under review following a delivery dispute.",
    )
    with pytest.raises(HTTPException) as exc:
        await get_verified_rider(user={"sub": "rider_1"}, db=_db(rider))

    assert exc.value.detail["type"] == "account_suspended"
    assert exc.value.detail["message"] == "Under review following a delivery dispute."


@pytest.mark.asyncio
async def test_an_approved_unsuspended_rider_still_passes():
    """This is a narrowing, not a lockout."""
    from dependencies.auth_dependencies import get_verified_rider

    user = {"sub": "rider_1"}
    assert await get_verified_rider(user=user, db=_db(_rider())) is user


def test_is_suspended_does_not_read_the_overloaded_column():
    """`is_active` also means "has not finished onboarding" — `create_deliverer`
    defaults it to False. Reading it here would tell a half-registered rider
    their account was suspended."""
    from models.deliverer_model import Deliverer

    half_registered = MagicMock(suspended_at=None, is_active=False)
    assert Deliverer.is_suspended.fget(half_registered) is False

    from datetime import datetime, timezone

    suspended = MagicMock(suspended_at=datetime.now(timezone.utc), is_active=True)
    assert Deliverer.is_suspended.fget(suspended) is True


# ── Dispatch offers work only to riders who may take it ───────────────────


def test_the_dispatch_predicate_covers_standing_not_just_the_rider_toggle():
    from models.deliverer_model import dispatchable_rider

    rendered = " ".join(str(c) for c in dispatchable_rider())
    assert "is_available" in rendered
    assert "suspended_at IS NULL" in rendered
    assert "kyc_status" in rendered


def test_no_rider_search_filters_on_availability_alone():
    """Structural: three searches, and the defect was the same in all three."""
    source = (_ROOT / "services" / "order_service.py").read_text()
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        # `Deliverer.is_available` written out inside a query is the shape being
        # guarded against; the predicate spreads `*dispatchable_rider()` instead.
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "is_available"
            and isinstance(node.value, ast.Name)
            and node.value.id == "Deliverer"
        ):
            offenders.append(node.lineno)

    assert offenders == [], (
        "a rider search must spread `*dispatchable_rider()` rather than filter on "
        f"the rider's own online toggle alone: lines {offenders}"
    )


def test_every_radar_search_uses_the_predicate():
    source = (_ROOT / "services" / "order_service.py").read_text()
    assert source.count("*dispatchable_rider()") == 4, (
        "expected the tier-1 registry search, the tier-2 fan-out, the H3 ring "
        "search and the unbucketed fallback to share one definition"
    )


# ── A customer sees a shop, not the person who owns it ────────────────────

#: Four fields that are the owner's, not the store's. `preferred_payment_method`
#: is the payout destination — a till, a paybill or a bank account — despite the
#: name.
OWNER_PII = {"owners_name", "email", "phone_number", "preferred_payment_method"}


def test_no_customer_facing_vendor_schema_carries_owner_pii():
    from schemas.vendor_schemas import (
        BaseVendor,
        VendorStorefront,
        VendorWithProductsFull,
        VendorWithProductsThin,
    )

    for model in (BaseVendor, VendorStorefront, VendorWithProductsFull, VendorWithProductsThin):
        leaked = OWNER_PII & set(model.model_fields)
        assert leaked == set(), f"{model.__name__} exposes {sorted(leaked)} to customers"


def test_the_schema_that_carried_it_is_gone_rather_than_merely_unused():
    """An existing schema that already has the fields is what the next
    customer-facing read reaches for."""
    import schemas.vendor_schemas as vendor_schemas

    assert not hasattr(vendor_schemas, "VendorOut")


def test_every_vendor_discovery_route_is_authenticated():
    """Two of these had no auth dependency at all, and between them they were an
    owner-name-plus-phone-plus-till list for the whole vendor base."""
    source = (_ROOT / "routes" / "vendor_routes.py").read_text()
    tree = ast.parse(source)

    unauthenticated = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        routes = [
            d
            for d in node.decorator_list
            if isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
        ]
        if not routes:
            continue

        deps = {
            arg.args[0].id
            for arg in list(node.args.defaults) + [k for k in node.args.kw_defaults if k]
            if isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == "Depends"
            and arg.args
            and isinstance(arg.args[0], ast.Name)
        }
        if not deps & {"get_current_customer", "get_current_user"}:
            path = routes[0].args[0].value if routes[0].args else "?"
            unauthenticated.append(f"{routes[0].func.attr.upper()} {path}")

    assert unauthenticated == [], (
        f"these vendor reads are open to anyone who can reach the API: {unauthenticated}"
    )


# ── An administrator's decision is not the subject's to undo ──────────────


def test_re_registration_cannot_clear_a_suspension():
    """`POST /api/auth/create_rider` is the rider app's onboarding form, which a
    suspended rider can post at any time. It set `is_active = True`
    unconditionally, leaving `suspended_at` set — two columns contradicting each
    other with nothing to say which was meant."""
    source = (_ROOT / "routes" / "auth_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "register_rider":
            continue
        body = ast.get_source_segment(source, node)
        assert "is_suspended" in body, (
            "register_rider must not reactivate an account an administrator stopped"
        )
        return
    pytest.fail("register_rider not found")


def test_re_registration_cannot_overwrite_a_verification_decision():
    """A rejected vendor could re-post the onboarding form and relabel itself
    "verified" — which the console then lists as approved."""
    source = (_ROOT / "routes" / "auth_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "register_vendor":
            continue
        body = ast.get_source_segment(source, node)
        assert 'verification_status != "rejected"' in body, (
            "create_vendor must not overwrite an administrator's rejection"
        )
        assert "suspended_at is None" in body
        return
    pytest.fail("register_vendor not found")
