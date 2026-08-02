"""
KYC approval is a server-side gate, not a client-side redirect.

`CLAUDE.md` states riders "remain blocked in VerificationWall until
`kyc_status == 'approved'`". They were not. `grep -c kyc` across
`routes/deliverer_routes.py` and `services/deliverer_service.py` returned 0 and
0: `get_current_rider` checked only that a Deliverer row existed, and
`accept_delivery_radar` checked availability and cash float but never KYC.

The only gate was a redirect in the rider app's `(screens)/_layout.tsx`, which
additionally failed *open* — when the KYC query errored, `statusData` was
undefined and the rider landed in the full app including Trip Radar. So a rider
whose KYC was `unsubmitted`, or explicitly `rejected`, could accept orders,
collect customers' cash and take their empty bottles: by calling the API
directly, or just by using the app with flaky connectivity.

This mirrors the proof-of-delivery guardrail, which was already correct on both
sides — the client refuses, and `deliverer_service` enforces it independently so
a modified client cannot bypass it.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from dependencies import auth_dependencies
from models.deliverer_model import KYCStatus

ROUTES = pathlib.Path(__file__).resolve().parent.parent / "routes" / "deliverer_routes.py"


def _rider_with(status):
    rider = MagicMock()
    rider.kyc_status = status
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = rider
    db.execute.return_value = result
    return db


# ── The dependency itself ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_approved_rider_passes():
    user = {"sub": "user_ok"}
    got = await auth_dependencies.get_verified_rider(
        user=user, db=_rider_with(KYCStatus.approved)
    )
    assert got is user


@pytest.mark.parametrize(
    "status", [KYCStatus.unsubmitted, KYCStatus.pending, KYCStatus.rejected]
)
@pytest.mark.asyncio
async def test_an_unapproved_rider_is_refused(status):
    """Especially `rejected` — that rider was actively turned down."""
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_verified_rider(
            user={"sub": "user_x"}, db=_rider_with(status)
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "kyc_required"
    assert exc.value.detail["kyc_status"] == status.value


@pytest.mark.asyncio
async def test_the_refusal_is_machine_readable():
    """The client routes on `type`, not on the wording of `message`.

    String-matching a sentence is how a copy edit silently disables a security
    redirect.
    """
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_verified_rider(
            user={"sub": "u"}, db=_rider_with(KYCStatus.rejected)
        )
    detail = exc.value.detail
    assert set(detail) == {"type", "message", "kyc_status"}
    assert isinstance(detail["message"], str) and detail["message"]


@pytest.mark.asyncio
async def test_a_non_rider_is_still_refused():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_verified_rider(user={"sub": "nobody"}, db=db)
    assert exc.value.status_code == 403


# ── Structural: every state-changing route must carry the gate ────────────

#: Routes that move an order, goods or money. A new one added without
#: `get_verified_rider` is exactly the regression this file exists to catch.
MUST_BE_VERIFIED = {
    ("PUT", "/availability"),
    ("GET", "/trip-radar"),
    ("PUT", "/orders/{order_id}/status"),
    ("PUT", "/orders/{order_id}/reject"),
    ("PUT", "/orders/{order_id}/cancel"),
    ("POST", "/orders/{order_id}/accept"),
    ("POST", "/orders/{order_id}/mismatch"),
    ("POST", "/orders/{order_id}/bottle-rejection"),
    ("POST", "/upload_proof"),
    # Background position reporting. Only runs during an active delivery, which
    # already requires approval, and it feeds the dispatch index — an unapproved
    # rider must not appear in it.
    ("POST", "/location-ping"),
}

#: Reads a rider must be able to make *before* approval, so they can see where
#: they stand rather than facing a blank wall. Gating these would 403-loop a
#: pending rider on their own home screen.
MAY_BE_UNVERIFIED = {
    ("POST", "/register"),
    ("GET", "/profile"),
    ("PUT", "/profile"),
    ("PUT", "/location"),
    ("GET", "/orders"),
    ("GET", "/earnings"),
    ("GET", "/orders/{order_id}/rider-location"),
    ("GET", "/reviews"),
    ("GET", "/bottle-debt"),
    ("GET", "/bottle-ledger"),
    ("GET", "/wallet-summary"),
}


def _route_dependencies() -> dict:
    """{(METHOD, path): {dependency names}} for every route in the module."""
    tree = ast.parse(ROUTES.read_text())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"):
                continue
            method = dec.func.attr.upper()
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            path = dec.args[0].value

            deps = set()
            for default in list(node.args.defaults) + [
                d for d in node.args.kw_defaults if d is not None
            ]:
                if (
                    isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name)
                    and default.func.id == "Depends"
                    and default.args
                    and isinstance(default.args[0], ast.Name)
                ):
                    deps.add(default.args[0].id)
            found[(method, path)] = deps
    return found


def test_every_state_changing_rider_route_requires_an_approved_rider():
    routes = _route_dependencies()
    missing = [
        f"{m} {p}"
        for (m, p) in MUST_BE_VERIFIED
        if "get_verified_rider" not in routes.get((m, p), set())
    ]
    assert missing == [], (
        f"these move orders, goods or money without checking KYC: {sorted(missing)}"
    )


def test_the_route_inventory_is_complete():
    """A new route must be classified deliberately, not default to unguarded.

    Without this, adding an endpoint and forgetting the gate passes every other
    test in this file — the failure mode being guarded against.
    """
    known = MUST_BE_VERIFIED | MAY_BE_UNVERIFIED
    actual = set(_route_dependencies())
    unclassified = actual - known
    assert unclassified == set(), (
        "new rider routes must be added to MUST_BE_VERIFIED or MAY_BE_UNVERIFIED "
        f"in this test: {sorted(unclassified)}"
    )
    assert known - actual == set(), (
        f"these routes no longer exist; drop them from the test: {sorted(known - actual)}"
    )


def test_pre_approval_reads_are_not_gated():
    """A pending rider must still see their own status, or the wall is a dead end."""
    routes = _route_dependencies()
    over_gated = [
        f"{m} {p}"
        for (m, p) in MAY_BE_UNVERIFIED
        if "get_verified_rider" in routes.get((m, p), set())
    ]
    assert over_gated == [], (
        f"a rider awaiting approval cannot reach these: {sorted(over_gated)}"
    )
