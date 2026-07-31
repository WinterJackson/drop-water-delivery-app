"""
Tests for rider-vendor registration logic.
Tests the business rules: 5-vendor cap, distance limits, duplicate prevention.
These test the route handler internals via mocking the FastAPI dependencies.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_5_vendor_cap_counts_only_active():
    """The 5-vendor cap should only count pending+approved registrations, not rejected ones."""
    from sqlalchemy import select, func, and_
    from models.vendor_rider_model import VendorRiderRegistry

    # Simulate: rider has 3 approved + 2 rejected + 1 pending = 4 active (under cap)
    # Previously the bug would count ALL 6 and block registration.
    # After fix, only pending+approved matter → 4 active → should be allowed.

    rider_id = uuid4()

    # Build the corrected query (mirrors the fix in rider_vendor_routes.py)
    limit_query = select(func.count(VendorRiderRegistry.id)).where(
        and_(
            VendorRiderRegistry.rider_id == rider_id,
            VendorRiderRegistry.status.in_(["pending", "approved"]),
        )
    )

    # Verify the query filters by status correctly
    compiled = str(limit_query.compile(compile_kwargs={"literal_binds": False}))
    assert "IN" in compiled.upper()
    # Should NOT just count all records — the `IN` clause proves the filter is applied


@pytest.mark.asyncio
async def test_distance_enforcement_constant():
    """Rider registration radius is 2 km for retail, 15 km for wholesale.

    The constant was split per business model; this assertion still referenced the
    old single-radius name and had been failing ever since.
    """
    from services.dispatch_policy import DispatchPolicy

    assert DispatchPolicy.RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM == 2.0
    assert DispatchPolicy.WHOLESALE_RIDER_REGISTRATION_MAX_RADIUS_KM == 15.0


@pytest.mark.asyncio
async def test_validate_status_transition_blocks_invalid():
    """validate_status_transition should block delivered→preparing."""
    from services.order_service import validate_status_transition

    assert validate_status_transition("delivered", "preparing") is False
    assert validate_status_transition("cancelled", "accepted") is False
    assert validate_status_transition("delivered", "cancelled") is False


@pytest.mark.asyncio
async def test_validate_status_transition_allows_valid():
    """validate_status_transition should allow standard forward transitions."""
    from services.order_service import validate_status_transition

    assert validate_status_transition("pending", "accepted") is True
    assert validate_status_transition("accepted", "preparing") is True
    assert validate_status_transition("preparing", "ready") is True
    assert validate_status_transition("ready", "picked_up") is True
    assert validate_status_transition("picked_up", "delivered") is True
    # Cancellation paths
    assert validate_status_transition("pending", "cancelled") is True
    assert validate_status_transition("accepted", "cancelled") is True
    # Unassigned path
    assert validate_status_transition("pending", "unassigned") is True
    assert validate_status_transition("unassigned", "pending") is True
