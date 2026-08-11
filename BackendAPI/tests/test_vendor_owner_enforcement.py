"""
Owner and staff are different privileges, and the server has to know it.

A vendor may hand the app to a shop assistant: `Vendor.staff_clerk_id`. That is a
real trust boundary — the whole point of the feature is letting an owner delegate
day-to-day trading without delegating the business.

It was enforced nowhere on the server. `get_current_vendor` matched
`clerk_id OR staff_clerk_id`, `role` was computed for display only
(`"owner" if vendor.clerk_id == clerk_id else "staff"`), and every restriction
lived in a `router.replace()` inside a React component — six of them.

The worst case was money. `payout_service._get_provider_details` used the same
staff-inclusive lookup, so a staff token resolved to the owner's vendor row;
`request_payout` debited that row and disbursed by M-Pesa B2C to
`data.account_details`, a phone number read straight from the request body. A
shop assistant could withdraw the store's balance to their own number.

`wallet_service.resolve_wallet_owner` had always matched on `clerk_id` alone and
correctly refused staff — so the platform held both answers at once and the
permissive one was the one that paid out.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from dependencies import auth_dependencies

_ROUTES_DIR = pathlib.Path(__file__).resolve().parent.parent / "routes"

#: Every module that serves the vendor app. Splitting the rider roster into its
#: own file is exactly how a route escapes a scan that only reads one of them.
ROUTE_MODULES = (
    _ROUTES_DIR / "vendor_management_routes.py",
    _ROUTES_DIR / "vendor_rider_routes.py",
)


def _db(owner_row=None, staff_row=None):
    """AsyncSession stub: first execute answers the owner probe, second the staff probe."""
    db = AsyncMock()

    owner_result = MagicMock()
    owner_result.scalars.return_value.first.return_value = owner_row

    staff_result = MagicMock()
    staff_result.scalars.return_value.first.return_value = staff_row

    db.execute = AsyncMock(side_effect=[owner_result, staff_result])
    return db


# ── The dependency itself ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_owner_passes():
    user = {"sub": "user_owner"}
    got = await auth_dependencies.get_vendor_owner(user=user, db=_db(owner_row=MagicMock()))
    assert got is user


@pytest.mark.asyncio
async def test_a_staff_member_is_refused():
    """The case the whole file exists for."""
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_vendor_owner(
            user={"sub": "user_staff"}, db=_db(owner_row=None, staff_row=MagicMock())
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "owner_only"


@pytest.mark.asyncio
async def test_the_refusal_is_machine_readable():
    """The client routes on `type`, not on the wording.

    String-matching a sentence is how a copy edit silently disables a guard.
    """
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_vendor_owner(
            user={"sub": "s"}, db=_db(owner_row=None, staff_row=MagicMock())
        )
    detail = exc.value.detail
    assert set(detail) == {"type", "message"}
    assert isinstance(detail["message"], str) and detail["message"]


@pytest.mark.asyncio
async def test_a_stranger_is_refused_without_being_told_about_staff():
    """Someone with no vendor relationship at all gets the generic answer."""
    with pytest.raises(HTTPException) as exc:
        await auth_dependencies.get_vendor_owner(
            user={"sub": "nobody"}, db=_db(owner_row=None, staff_row=None)
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "Access denied. Must be a registered vendor."


@pytest.mark.asyncio
async def test_get_current_vendor_still_admits_staff():
    """Staff must keep working the shop floor — this is a narrowing, not a lockout."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = MagicMock()
    db.execute = AsyncMock(return_value=result)

    user = {"sub": "user_staff"}
    assert await auth_dependencies.get_current_vendor(user=user, db=db) is user


@pytest.mark.asyncio
async def test_a_multi_store_owner_does_not_break_the_vendor_dependency():
    """`scalar_one_or_none()` raised MultipleResultsFound on the second store.

    `GET /api/vendor/stores` exists to list several, so this turned every
    authenticated vendor endpoint into a 500 the moment an owner opened a branch.
    The query is now ordered and limited, so more than one row is ordinary.
    """
    db = AsyncMock()
    result = MagicMock()
    # `.scalars().first()` is what a LIMIT 1 query yields; the point is that the
    # dependency no longer calls `scalar_one_or_none`, which would raise here.
    result.scalars.return_value.first.return_value = MagicMock()
    db.execute = AsyncMock(return_value=result)

    user = {"sub": "owner_of_two"}
    assert await auth_dependencies.get_current_vendor(user=user, db=db) is user


def test_the_vendor_dependency_does_not_use_scalar_one_or_none():
    """Structural: the defect is a single method call, and it is easy to reintroduce."""
    source = (
        pathlib.Path(auth_dependencies.__file__).read_text()
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "get_current_vendor":
            continue
        calls = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "scalar_one_or_none" not in calls, (
            "get_current_vendor must tolerate an owner with several stores; "
            "scalar_one_or_none raises MultipleResultsFound on the second one"
        )
        return
    pytest.fail("get_current_vendor not found")


# ── Structural: the route inventory ───────────────────────────────────────

#: Routes that change what the business *is*, or move the owner's money.
#: Staff may run the shop; they may not redefine or drain it.
OWNER_ONLY = {
    ("PUT", "/profile"),
    # Who may operate this store, and what they may do here.
    ("GET", "/staff"),
    ("POST", "/staff"),
    ("PATCH", "/staff/{staff_id}"),
    ("DELETE", "/staff/{staff_id}"),
    # Who may carry this store's goods and collect its cash.
    ("PUT", "/rider-action"),
    # Terms of trade: whether the store takes cash at all, and the smallest
    # order it will prepare. Alongside the payout account and the business
    # name, not alongside the shop-floor pause below.
    ("PUT", "/storefront"),
}

#: Day-to-day trading. A staff member must be able to do all of this, or the
#: feature has no purpose.
STAFF_ALLOWED = {
    ("POST", "/register"),
    ("GET", "/stores"),
    ("GET", "/profile"),
    ("POST", "/products"),
    ("GET", "/products"),
    ("GET", "/products/{product_id}"),
    ("PUT", "/products/{product_id}"),
    ("DELETE", "/products/{product_id}"),
    ("POST", "/receive-bottles"),
    ("GET", "/bottle-debtors"),
    ("GET", "/bottle-ledger"),
    ("GET", "/orders"),
    ("GET", "/orders/{order_id}"),
    ("GET", "/orders/{order_id}/review"),
    ("PUT", "/orders/{order_id}/status"),
    ("PUT", "/orders/{order_id}/cancel"),
    ("PUT", "/orders/{order_id}/assign-rider"),
    ("GET", "/dashboard"),
    ("GET", "/wallet-summary"),
    # Staff photograph stock and update the catalogue; the upload is scoped to
    # the store they can already reach.
    ("POST", "/upload-image"),
    # The assign-rider sheet in OrderDetail needs the roster to dispatch.
    ("GET", "/my-riders"),
    # Pausing is the shop floor, not the business. Whoever has just run out of
    # 20 L bottles at 11am is standing behind the counter; a pause they cannot
    # apply until they reach the owner arrives after the orders do. Reading the
    # storefront is open to any member — it is what the dashboard renders.
    ("GET", "/storefront"),
    ("POST", "/storefront/pause"),
    ("POST", "/storefront/resume"),
}


def _route_dependencies() -> dict:
    """{(METHOD, path): {dependency names}} for every vendor route."""
    found = {}
    for module in ROUTE_MODULES:
        found.update(_module_routes(module))
    return found


def _module_routes(module: pathlib.Path) -> dict:
    tree = ast.parse(module.read_text())
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
                if not (
                    isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name)
                    and default.func.id == "Depends"
                    and default.args
                ):
                    continue
                inner = default.args[0]
                if isinstance(inner, ast.Name):
                    deps.add(inner.id)
                elif (
                    # `Depends(require_permission("manage_orders"))` — a factory,
                    # so the dependency is a Call and not a bare Name. Recorded
                    # as `require_permission:manage_orders` so the inventory can
                    # assert *which* capability a route demands, not merely that
                    # it demands one.
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                ):
                    deps.add(f"{inner.func.id}:{inner.args[0].value}")
            found[(method, path)] = deps
    return found


#: Either gate proves ownership. `get_owned_store` is the stricter of the two —
#: it proves the caller owns *the store this request names*, which matters once a
#: person can own store A and be staff of store B.
OWNER_GATES = {"get_vendor_owner", "get_owned_store"}

#: Routes a staff member may reach *if the owner granted them the capability*.
#: `require_permission("…")` is not an owner gate — owners pass it implicitly and
#: staff pass it when their `VendorStaff.permissions` say so — so these count as
#: staff-allowed for the inventory above.
PERMISSION_GATED = {
    ("POST", "/products"): "manage_products",
    ("PUT", "/products/{product_id}"): "manage_products",
    ("DELETE", "/products/{product_id}"): "manage_products",
    ("POST", "/upload-image"): "manage_products",
    ("POST", "/receive-bottles"): "manage_bottles",
    ("PUT", "/orders/{order_id}/status"): "manage_orders",
    ("PUT", "/orders/{order_id}/cancel"): "manage_orders",
    ("PUT", "/orders/{order_id}/assign-rider"): "manage_orders",
    ("GET", "/wallet-summary"): "view_finances",
}


def test_every_owner_only_route_requires_the_owner():
    routes = _route_dependencies()
    missing = [
        f"{m} {p}"
        for (m, p) in OWNER_ONLY
        if not (OWNER_GATES & routes.get((m, p), set()))
    ]
    assert missing == [], (
        f"a staff member can reach these and change the business: {sorted(missing)}"
    )


def test_the_route_inventory_is_complete():
    """A new vendor route must be classified deliberately, not default to permissive.

    Without this, adding an endpoint and forgetting the gate passes every other
    test in this file — the failure mode being guarded against.
    """
    known = OWNER_ONLY | STAFF_ALLOWED
    actual = set(_route_dependencies())
    unclassified = actual - known
    assert unclassified == set(), (
        "new vendor routes must be added to OWNER_ONLY or STAFF_ALLOWED in this "
        f"test: {sorted(unclassified)}"
    )
    assert known - actual == set(), (
        f"these routes no longer exist; drop them from the test: {sorted(known - actual)}"
    )


def test_every_mutating_route_names_the_capability_it_needs():
    """A staff member with the till should not also get the catalogue.

    Access used to be one nullable column: `get_current_vendor` admitted staff to
    every route that was not owner-only, so handing someone the shop floor handed
    them the products, the bottle ledger and the wallet balance too.
    """
    routes = _route_dependencies()
    missing = []
    for (method, path), permission in PERMISSION_GATED.items():
        if f"require_permission:{permission}" not in routes.get((method, path), set()):
            missing.append(f"{method} {path} (wants {permission})")
    assert missing == [], (
        f"these change something but ask for no capability: {sorted(missing)}"
    )


def test_permission_gated_routes_are_classified_as_staff_reachable():
    """They are not owner-only — an owner grants them, and then staff may act."""
    assert set(PERMISSION_GATED) <= STAFF_ALLOWED
    assert not (set(PERMISSION_GATED) & OWNER_ONLY)


def test_staff_are_not_locked_out_of_trading():
    routes = _route_dependencies()
    over_gated = [
        f"{m} {p}"
        for (m, p) in STAFF_ALLOWED
        if OWNER_GATES & routes.get((m, p), set())
    ]
    assert over_gated == [], (
        f"a staff member cannot run the shop without these: {sorted(over_gated)}"
    )


# ── The money path ────────────────────────────────────────────────────────


def test_payouts_resolve_the_provider_by_ownership_only():
    """Structural, because the defect was one function call.

    `_get_provider_details` used `get_vendor_by_clerk_id`, whose WHERE clause is
    `clerk_id == … OR staff_clerk_id == …`. Nothing about the payout code below
    it was wrong; it was simply told the wrong person owned the money.
    """
    source = (
        pathlib.Path(__file__).resolve().parent.parent / "services" / "payout_service.py"
    ).read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "_get_provider_details":
            continue
        called = {
            n.func.id
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "get_vendor_by_clerk_id" not in called, (
            "_get_provider_details must not resolve a payee with the staff-inclusive "
            "lookup — that let a staff member withdraw the owner's balance"
        )

        # And it must actually filter on ownership.
        assert "staff_clerk_id" in ast.get_source_segment(source, node), (
            "expected an explicit staff branch so a staff member gets a clear refusal"
        )
        return

    pytest.fail("_get_provider_details not found")


def test_account_deletion_checks_a_column_that_exists():
    """`Order.status` is not a column; `order_status` is.

    All three delete branches filtered on `Order.status.in_([...])`, which raises
    AttributeError while the query is being built — so `DELETE /delete_account`
    answered 500 for every user type, and the active-order guard it was meant to
    provide never ran at all. Two of the listed values ("confirmed",
    "out_for_delivery") are not statuses this platform uses either.
    """
    from models.order_model import Order

    assert hasattr(Order, "order_status")
    assert not hasattr(Order, "status")

    source = (
        pathlib.Path(__file__).resolve().parent.parent / "routes" / "auth_routes.py"
    ).read_text()
    assert "Order.status." not in source, "auth_routes still filters on a non-existent column"

    from services.order_service import ACTIVE_ORDER_STATUSES, IN_FLIGHT_DELIVERY_STATUSES

    for value in (*ACTIVE_ORDER_STATUSES, *IN_FLIGHT_DELIVERY_STATUSES):
        assert value in {s.value for s in __import__(
            "services.order_service", fromlist=["OrderStatusEnum"]
        ).OrderStatusEnum}, f"{value} is not a real order status"


# ── Which store? ──────────────────────────────────────────────────────────
# `Vendor` is a *store*, not an account: one clerk id may own several rows, and
# `GET /api/vendor/stores` exists to list them. Every endpoint nonetheless acted
# on whichever row came back first, and the app's store switcher carried the
# comment `// Future: refetch dashboard with new store context`. Selecting a
# store changed a label and nothing else.


def _store(**kw):
    row = MagicMock()
    for k, v in kw.items():
        setattr(row, k, v)
    return row


def _one(row):
    """An AsyncSession whose every execute yields `row`.

    `.first()` is stubbed as well as `.scalars().first()`: the staff branch
    selects a `(VendorStaff, Vendor)` pair and unpacks the row directly, and an
    unstubbed `MagicMock` is truthy — so it would be unpacked, not skipped.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    result.first.return_value = None
    db.execute = AsyncMock(return_value=result)
    return db


async def _access(db, clerk_id, requested=None, owner_only=False):
    """Call the resolver directly.

    `get_active_store` is a FastAPI dependency of a dependency now — it takes the
    resolved `StoreAccess`, not the request parameters — so the unit tests drive
    `_resolve_access`, which is where the logic being asserted actually lives.
    """
    return await auth_dependencies._resolve_access(db, clerk_id, requested, owner_only)


@pytest.mark.asyncio
async def test_the_named_store_is_the_one_returned():
    store = _store(id="11111111-1111-1111-1111-111111111111")
    access = await _access(_one(store), "owner", "11111111-1111-1111-1111-111111111111")
    assert access.vendor is store
    assert access.is_owner


@pytest.mark.asyncio
async def test_a_store_you_do_not_own_is_a_404_not_a_403():
    """403 would confirm the id exists. It is not ours to confirm."""
    with pytest.raises(HTTPException) as exc:
        await _access(_one(None), "outsider", "22222222-2222-2222-2222-222222222222")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_malformed_store_id_is_rejected_before_it_reaches_the_database():
    with pytest.raises(HTTPException) as exc:
        await _access(AsyncMock(), "owner", "not-a-uuid")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_naming_no_store_still_works():
    """Single-store vendors — everyone today — must be unaffected."""
    store = _store(id="33333333-3333-3333-3333-333333333333")
    access = await _access(_one(store), "owner")
    assert access.vendor is store


@pytest.mark.asyncio
async def test_staff_cannot_reach_the_owned_store_dependency():
    db = AsyncMock()
    owned = MagicMock()
    owned.scalars.return_value.first.return_value = None
    staff = MagicMock()
    staff.scalars.return_value.first.return_value = MagicMock()
    db.execute = AsyncMock(side_effect=[owned, staff])

    with pytest.raises(HTTPException) as exc:
        await _access(db, "staff", owner_only=True)
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "owner_only"


@pytest.mark.asyncio
async def test_a_staff_member_reaches_the_store_with_their_own_permissions():
    """The point of the membership table: access is scoped, not all-or-nothing."""
    db = AsyncMock()
    owned = MagicMock()
    owned.scalars.return_value.first.return_value = None  # owns nothing
    staff_row = MagicMock(id="s1", permissions=["manage_orders"])
    store = _store(id="44444444-4444-4444-4444-444444444444")
    membership = MagicMock()
    membership.first.return_value = (staff_row, store)
    db.execute = AsyncMock(side_effect=[owned, membership])

    access = await _access(db, "staff_a")
    assert access.vendor is store
    assert not access.is_owner
    assert access.may("manage_orders")
    assert not access.may("manage_products")


@pytest.mark.asyncio
async def test_an_owner_may_everything_without_a_permission_row():
    access = auth_dependencies.StoreAccess(
        vendor=_store(id="x"), clerk_id="owner", is_owner=True, permissions=frozenset()
    )
    assert access.may("manage_orders") and access.may("view_finances")
    assert access.role == "owner"


@pytest.mark.asyncio
async def test_require_permission_refuses_machine_readably():
    """The client routes on `type` and `permission`, never on the wording."""
    dependency = auth_dependencies.require_permission("view_finances")
    access = auth_dependencies.StoreAccess(
        vendor=_store(id="x"), clerk_id="staff", is_owner=False,
        permissions=frozenset({"manage_orders"}),
    )
    with pytest.raises(HTTPException) as exc:
        await dependency(access=access)
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "permission_required"
    assert exc.value.detail["permission"] == "view_finances"


def test_the_owned_store_resolver_filters_on_ownership_alone():
    """Structural: the whole guard is one branch choosing the WHERE clause.

    Composing an owner check with a store resolver would *not* be equivalent:
    someone may own store A and be staff of store B, pass the owner gate on A,
    and then name B. `_resolve_access` checks ownership against the resolved row.
    """
    source = pathlib.Path(auth_dependencies.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_resolve_access":
            body = ast.get_source_segment(source, node)
            assert "owner_only" in body and "VendorStaff" in body
            return
    pytest.fail("_resolve_access not found")


def test_store_scoped_routes_resolve_a_store_instead_of_re_querying():
    """No vendor route may call `get_vendor_by_clerk_id` for the active store.

    That helper's fallback is `WHERE clerk_id = … OR staff_clerk_id = …` with no
    store id, which is precisely the ambiguity the dependency removes. A route
    that keeps calling it can act on a different store from the one the gate
    approved.
    """
    offenders = []
    for module in ROUTE_MODULES:
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get_vendor_by_clerk_id"
            ):
                offenders.append(f"{module.name}:{node.lineno}")
    assert offenders == [], f"routes must take a resolved store: {offenders}"


def test_the_orders_envelope_is_not_a_fake_infinite_query():
    """`{"pages": [orders]}` was the server imitating React Query's cache shape.

    It carried no page metadata, so the client guessed `has_more` from the page
    length after unwrapping `data.pages[0]` — and `useVendorOrders` threw away
    every page but the first.
    """
    from schemas.order_schema import PaginatedOrders

    fields = set(PaginatedOrders.model_fields)
    assert "pages" not in fields
    assert {"items", "limit", "offset", "has_more"} <= fields
