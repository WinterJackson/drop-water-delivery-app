"""The bottle float as the admin console reports it.

`bottle_ledger_entries` is empty on this deployment, so these pin the arithmetic
against fixtures rather than against observed volume. Three properties matter and
none of them are obvious from reading the queries:

  1. a credit against one store must never cancel a debt to another,
  2. a rider with no registry row is not "drift" — that is the documented radar
     case and reporting it would bury the real mismatches,
  3. a write-off cannot forgive more than the rider actually holds.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services import admin_bottle_service as svc

RIDER_A, RIDER_B = uuid4(), uuid4()
VENDOR_A, VENDOR_B = uuid4(), uuid4()

DEPOSITS = {10: Decimal("150.00"), 20: Decimal("300.00")}


def _now(days_ago=0):
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _db(scalar=0):
    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = scalar
    db.execute = AsyncMock(return_value=result)
    return db


# ── netting ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_credit_at_one_store_does_not_cancel_a_debt_at_another():
    """Summing the raw quantity column platform-wide would report less float
    than exists. Every total nets per (rider, vendor, capacity) first."""
    balances = [
        (RIDER_A, VENDOR_A, 20, 6, _now(30)),
        (RIDER_B, VENDOR_B, 20, 3, _now(1)),
    ]

    with (
        patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)),
        patch.object(svc, "_deposits", AsyncMock(return_value=DEPOSITS)),
        patch.object(svc, "drift", AsyncMock(return_value=[])),
    ):
        result = await svc.overview(_db())

    assert result["bottles_out"] == 9
    assert result["value_at_risk"] == "2700.00"


@pytest.mark.asyncio
async def test_a_capacity_with_no_configured_deposit_is_named_not_priced_at_zero():
    balances = [(RIDER_A, VENDOR_A, 5, 4, _now(1))]

    with (
        patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)),
        patch.object(svc, "_deposits", AsyncMock(return_value=DEPOSITS)),
        patch.object(svc, "drift", AsyncMock(return_value=[])),
    ):
        result = await svc.overview(_db())

    assert result["unpriced_capacities"] == [5]
    assert result["by_capacity"][0]["priced"] is False
    assert result["value_at_risk"] == "0.00"


# ── staleness ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_staleness_is_measured_from_the_oldest_entry_not_the_balance():
    """A balance has no age of its own. Without the oldest entry, a pair that
    has sat untouched for a month looks identical to one opened this morning."""
    balances = [
        (RIDER_A, VENDOR_A, 20, 6, _now(svc.STALE_AFTER_DAYS + 1)),
        (RIDER_B, VENDOR_B, 20, 6, _now(1)),
    ]

    with (
        patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)),
        patch.object(svc, "_deposits", AsyncMock(return_value=DEPOSITS)),
        patch.object(svc, "drift", AsyncMock(return_value=[])),
    ):
        result = await svc.overview(_db())

    assert result["stale_pairs"] == 1
    assert result["stale_bottles"] == 6
    assert result["oldest_debt_days"] == svc.STALE_AFTER_DAYS + 1


# ── drift ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rider_with_no_registry_row_is_not_reported_as_drift():
    """Radar dispatch lets a rider deliver for a vendor they never registered
    with: ledger entries, no counter. That is the design, and reporting it as a
    mismatch against zero would bury the genuine ones."""
    balances = [(RIDER_A, VENDOR_A, 20, 6, _now(1))]

    db = AsyncMock()
    registry_result = MagicMock()
    registry_result.all.return_value = []  # no registry rows at all
    db.execute = AsyncMock(return_value=registry_result)

    with patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)):
        assert await svc.drift(db) == []


@pytest.mark.asyncio
async def test_drift_reports_a_counter_that_disagrees_with_the_ledger():
    balances = [(RIDER_A, VENDOR_A, 20, 6, _now(1))]

    db = AsyncMock()
    registry_result = MagicMock()
    registry_result.all.return_value = [(RIDER_A, VENDOR_A, 0, 99, "Rider", "Store")]
    db.execute = AsyncMock(return_value=registry_result)

    with patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)):
        rows = await svc.drift(db)

    assert [(row["capacity"], row["ledger"], row["counter"]) for row in rows] == [(20, 6, 99)]


# ── adjustment ────────────────────────────────────────────────────────────


def _adjust_db(registry=None):
    db = AsyncMock()
    db.added = []
    db.add = MagicMock(side_effect=db.added.append)
    result = MagicMock()
    result.scalars.return_value.first.return_value = registry
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_a_write_off_cannot_forgive_more_than_the_rider_holds():
    """Otherwise the ledger goes negative and every total that nets positives
    starts disagreeing with the vendor's own screen."""
    balances = [(RIDER_A, VENDOR_A, 20, 3, _now(1))]

    with patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)):
        with pytest.raises(ValueError, match="holds 3"):
            await svc.adjust(
                _adjust_db(),
                rider_id=RIDER_A,
                vendor_id=VENDOR_A,
                capacity=20,
                quantity=-9,
                note="rider left the platform",
                actor_clerk_id="user_x",
            )


@pytest.mark.asyncio
async def test_an_adjustment_requires_a_reason():
    with patch.object(svc, "_pair_balances", AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="reason"):
            await svc.adjust(
                _adjust_db(),
                rider_id=RIDER_A,
                vendor_id=VENDOR_A,
                capacity=20,
                quantity=-1,
                note="   ",
                actor_clerk_id="user_x",
            )


@pytest.mark.asyncio
async def test_an_adjustment_moves_the_counter_with_the_ledger_row():
    """The counter is a denormalisation of the ledger. Writing one without the
    other is what produced the drift this screen exists to report."""
    balances = [(RIDER_A, VENDOR_A, 20, 6, _now(1))]
    registry = SimpleNamespace(pending_10L_empties=0, pending_20L_empties=6)
    db = _adjust_db(registry)

    with patch.object(svc, "_pair_balances", AsyncMock(return_value=balances)):
        result = await svc.adjust(
            db,
            rider_id=RIDER_A,
            vendor_id=VENDOR_A,
            capacity=20,
            quantity=-6,
            note="rider left the platform",
            actor_clerk_id="user_x",
        )

    assert len(db.added) == 1, "the correction must be a ledger row, not a counter edit"
    assert db.added[0].quantity == -6
    assert db.added[0].note == "rider left the platform"
    assert registry.pending_20L_empties == 0
    assert result["before"] == 6 and result["after"] == 0


@pytest.mark.asyncio
async def test_reseating_rewrites_the_counter_from_the_ledger_and_never_the_reverse():
    registry = SimpleNamespace(pending_10L_empties=0, pending_20L_empties=99)
    drifted = [
        {
            "rider_id": str(RIDER_A),
            "vendor_id": str(VENDOR_A),
            "capacity": 20,
            "ledger": 6,
            "counter": 99,
            "difference": 93,
        }
    ]
    db = _adjust_db(registry)

    with patch.object(svc, "drift", AsyncMock(return_value=drifted)):
        repaired = await svc.reseat_counters(db)

    assert len(repaired) == 1
    assert registry.pending_20L_empties == 6
