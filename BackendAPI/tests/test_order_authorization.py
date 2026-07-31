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


def _session(order, *, customer=None, vendor=None, rider=None):
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
    return session


@pytest.mark.asyncio
async def test_owning_customer_is_recognised():
    customer = MagicMock(clerk_id="customer_a")
    order = _order(uuid4(), uuid4())
    session = _session(order, customer=customer, vendor=MagicMock(clerk_id="v", staff_clerk_id=None))

    assert await resolve_order_role(session, order.id, "customer_a") == "customer"


@pytest.mark.asyncio
async def test_unrelated_customer_gets_no_role():
    """The core of B7: customer B must have no access to customer A's order."""
    customer = MagicMock(clerk_id="customer_a")
    order = _order(uuid4(), uuid4())
    session = _session(order, customer=customer, vendor=MagicMock(clerk_id="v", staff_clerk_id=None))

    assert await resolve_order_role(session, order.id, "customer_b") is None


@pytest.mark.asyncio
async def test_order_vendor_and_staff_are_recognised():
    order = _order(uuid4(), uuid4())
    vendor = MagicMock(clerk_id="vendor_a", staff_clerk_id="staff_a")
    session = _session(order, customer=MagicMock(clerk_id="c"), vendor=vendor)

    assert await resolve_order_role(session, order.id, "vendor_a") == "vendor"
    assert await resolve_order_role(session, order.id, "staff_a") == "vendor"


@pytest.mark.asyncio
async def test_assigned_rider_is_recognised_but_other_riders_are_not():
    rider_id = uuid4()
    order = _order(uuid4(), uuid4(), deliverer_id=rider_id)
    session = _session(
        order,
        customer=MagicMock(clerk_id="c"),
        vendor=MagicMock(clerk_id="v", staff_clerk_id=None),
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
                       vendor=MagicMock(clerk_id="v", staff_clerk_id=None))

    with pytest.raises(HTTPException) as exc:
        await authorise_order_access(session, order.id, "attacker")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_role_restriction_is_enforced():
    """A vendor on the order still cannot use a customer-only endpoint."""
    from fastapi import HTTPException

    order = _order(uuid4(), uuid4())
    session = _session(order, customer=MagicMock(clerk_id="customer_a"),
                       vendor=MagicMock(clerk_id="vendor_a", staff_clerk_id=None))

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
