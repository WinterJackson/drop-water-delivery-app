"""Order-scoped authorisation — regression guard for findings B7 and H5.

Authenticating a token proves who is calling. It says nothing about whether that
caller has any relationship to the order they named. Several endpoints verified
the JWT and then trusted an order id straight from the URL, so any signed-in
account could stream another customer's live rider GPS, read their delivery
breadcrumb trail, or push fabricated coordinates for an arbitrary rider.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from dependencies.auth_dependencies import (
    authorise_order_access,
    owns_entity,
    resolve_order_role,
)


def _order(customer_id, vendor_id, deliverer_id=None):
    order = MagicMock()
    order.id = uuid4()
    order.customer_id = customer_id
    order.vendor_id = vendor_id
    order.deliverer_id = deliverer_id
    return order


def _session(order, *, customer=None, vendor=None, rider=None, staff_clerk_ids=()):
    """A session double for the lookups `resolve_order_role` actually makes.

    Staff used to be `Vendor.staff_clerk_id`, a column already loaded with the
    vendor row. It is a membership table now, so "is this person staff of that
    store" is a query — and a bare `AsyncMock.execute()` answers every query
    truthily, which would silently make *everyone* a vendor here.
    """
    session = AsyncMock()

    async def _get(model, ident):
        name = model.__name__
        if name == "Order":
            return order
        if name == "User":
            return customer
        if name == "Vendor":
            return vendor
        if name == "Deliverer":
            return rider
        return None

    session.get = AsyncMock(side_effect=_get)

    def _membership(statement):
        # `staff_membership` filters on the clerk id; pull it back out of the
        # compiled parameters rather than guessing from call order.
        params = statement.compile().params
        wanted = {v for k, v in params.items() if k.startswith("clerk_id")}
        result = MagicMock()
        match = MagicMock() if wanted & set(staff_clerk_ids) else None
        result.scalars.return_value.first.return_value = match
        return result

    session.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: _membership(stmt))
    return session


@pytest.mark.asyncio
async def test_owning_customer_is_recognised():
    customer = MagicMock(clerk_id="customer_a")
    order = _order(uuid4(), uuid4())
    session = _session(order, customer=customer, vendor=MagicMock(clerk_id="v"))

    assert await resolve_order_role(session, order.id, "customer_a") == "customer"


@pytest.mark.asyncio
async def test_unrelated_customer_gets_no_role():
    """The core of B7: customer B must have no access to customer A's order."""
    customer = MagicMock(clerk_id="customer_a")
    order = _order(uuid4(), uuid4())
    session = _session(order, customer=customer, vendor=MagicMock(clerk_id="v"))

    assert await resolve_order_role(session, order.id, "customer_b") is None


@pytest.mark.asyncio
async def test_order_vendor_and_staff_are_recognised():
    order = _order(uuid4(), uuid4())
    vendor = MagicMock(clerk_id="vendor_a")
    session = _session(
        order, customer=MagicMock(clerk_id="c"), vendor=vendor, staff_clerk_ids=("staff_a",)
    )

    assert await resolve_order_role(session, order.id, "vendor_a") == "vendor"
    assert await resolve_order_role(session, order.id, "staff_a") == "vendor"
    # And a staff member of some *other* store is nobody here.
    assert await resolve_order_role(session, order.id, "staff_elsewhere") is None


@pytest.mark.asyncio
async def test_assigned_rider_is_recognised_but_other_riders_are_not():
    rider_id = uuid4()
    order = _order(uuid4(), uuid4(), deliverer_id=rider_id)
    session = _session(
        order,
        customer=MagicMock(clerk_id="c"),
        vendor=MagicMock(clerk_id="v"),
        rider=MagicMock(clerk_id="rider_a"),
    )

    assert await resolve_order_role(session, order.id, "rider_a") == "rider"
    assert await resolve_order_role(session, order.id, "rider_b") is None


@pytest.mark.asyncio
async def test_unauthorised_access_raises_404_not_403():
    """404 rather than 403: confirming an order id exists is itself a leak."""
    from fastapi import HTTPException

    order = _order(uuid4(), uuid4())
    session = _session(order, customer=MagicMock(clerk_id="customer_a"),
                       vendor=MagicMock(clerk_id="v"))

    with pytest.raises(HTTPException) as exc:
        await authorise_order_access(session, order.id, "attacker")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_role_restriction_is_enforced():
    """A vendor on the order still cannot use a customer-only endpoint."""
    from fastapi import HTTPException

    order = _order(uuid4(), uuid4())
    session = _session(order, customer=MagicMock(clerk_id="customer_a"),
                       vendor=MagicMock(clerk_id="vendor_a"))

    assert await authorise_order_access(session, order.id, "customer_a", ("customer",)) == "customer"
    with pytest.raises(HTTPException):
        await authorise_order_access(session, order.id, "vendor_a", ("customer",))


@pytest.mark.asyncio
async def test_missing_order_is_denied():
    from fastapi import HTTPException

    session = _session(None)
    with pytest.raises(HTTPException) as exc:
        await authorise_order_access(session, uuid4(), "anyone")
    assert exc.value.status_code == 404


# ── Entity ownership (the /ws/rider/{id} and /ws/orders/{type}/{id} guard) ────

@pytest.mark.asyncio
async def test_rider_socket_ownership_is_enforced():
    """H5: `rider_id` came from the URL and was never compared to the token."""
    rider_id = uuid4()
    session = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock(clerk_id="rider_a"))

    assert await owns_entity(session, "rider", str(rider_id), "rider_a") is True
    assert await owns_entity(session, "rider", str(rider_id), "impostor") is False


@pytest.mark.asyncio
async def test_customer_socket_ownership_is_enforced():
    session = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock(clerk_id="customer_a"))

    assert await owns_entity(session, "customer", str(uuid4()), "customer_a") is True
    assert await owns_entity(session, "customer", str(uuid4()), "customer_b") is False


@pytest.mark.asyncio
async def test_malformed_entity_id_is_denied_not_crashed():
    session = AsyncMock()
    assert await owns_entity(session, "customer", "not-a-uuid", "anyone") is False
    assert await owns_entity(session, "customer", None, "anyone") is False


@pytest.mark.asyncio
async def test_unknown_entity_type_is_denied():
    session = AsyncMock()
    assert await owns_entity(session, "admin", str(uuid4()), "anyone") is False


@pytest.mark.asyncio
async def test_missing_entity_row_is_denied():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    assert await owns_entity(session, "rider", str(uuid4()), "rider_a") is False


# ── Every customer-facing order-by-id route is scoped to the caller ──────────


def _cart_order_routes():
    """Route functions in `cart_routes` whose path names an `{order_id}`.

    Parsed rather than listed, so a route added tomorrow is covered without
    anybody remembering to add it here.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "routes" / "cart_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        paths = [
            decorator.args[0].value
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.value.__dict__.get("id") == "router"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ]
        if any("{order_id}" in path for path in paths):
            yield node.name, ast.get_source_segment(source, node) or ""


def test_every_customer_order_route_scopes_the_order_to_the_caller():
    """An order id in the URL is a claim, not a credential.

    Authenticating proves who is calling; it says nothing about whether they have
    anything to do with the order they named. There are exactly two acceptable
    ways to establish that here, and every route must use one:

    * `authorise_order_access(...)`, which resolves the caller's role against the
      order and raises **404** for a stranger — a 403 would confirm the id exists.
    * passing the caller's own `user_id` into the service, so the query cannot
      match somebody else's order in the first place.

    Written as a sweep because the risk is a *new* route: `GET /orders/{id}` was
    added so the detail screen could stop searching the cached list, and it
    returns a customer's address, phone number and order total to whoever asks
    for the id if this line is ever dropped.
    """
    unscoped = []
    for name, body in _cart_order_routes():
        if "authorise_order_access" in body:
            continue
        if "user_id=user_obj.id" in body or "user_id=user.id" in body:
            continue
        unscoped.append(name)

    assert not unscoped, (
        "order-scoped route with no check that the caller is a party to it: "
        f"{unscoped}"
    )


def test_the_route_sweep_still_finds_the_routes_it_is_meant_to_cover():
    """A parser that matches nothing passes the test above vacuously."""
    names = {name for name, _ in _cart_order_routes()}

    assert "get_one_order" in names, "the single-order read must be covered"
    assert len(names) >= 4, f"the decorator parser has stopped matching (found {names})"
