"""
Bottle-debt reconciliation between riders and vendors.

These pin the four defects the ledger was built to fix:
  1. debt vanished when the rider had no registry row (radar deliveries),
  2. settlement left no audit trail,
  3. over-receipt was silently clamped instead of rejected,
  4. a retried delivery double-charged the rider.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from models.bottle_ledger_model import BottleLedgerEntryType
from services import bottle_ledger_service as svc


def _session(existing_accrual_caps=(), registry=None):
    """AsyncSession stub: first execute() answers the duplicate-accrual probe,
    the second the FOR UPDATE registry lookup."""
    session = AsyncMock()
    session.added = []
    session.add = MagicMock(side_effect=session.added.append)

    dup_result = MagicMock()
    dup_result.scalars.return_value.all.return_value = list(existing_accrual_caps)

    reg_result = MagicMock()
    reg_result.scalars.return_value.first.return_value = registry

    session.execute = AsyncMock(side_effect=[dup_result, reg_result])
    return session


def _registry(p10=0, p20=0):
    return SimpleNamespace(pending_10L_empties=p10, pending_20L_empties=p20)


# ── accrual ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accrual_is_recorded_when_rider_has_no_registry_row():
    """Radar dispatch offers orders with vendor_id=None, so a rider can deliver
    for a vendor they never registered with. The old code skipped the accrual
    entirely and the bottles left with no record."""
    session = _session(registry=None)

    entries = await svc.accrue_delivery_empties(
        session,
        rider_id=uuid4(),
        vendor_id=uuid4(),
        order_id=uuid4(),
        quantities_by_capacity={20: 3},
    )

    assert len(entries) == 1
    assert entries[0].quantity == 3
    assert entries[0].capacity_litres == 20
    assert entries[0].entry_type == BottleLedgerEntryType.DELIVERY_ACCRUAL


@pytest.mark.asyncio
async def test_accrual_moves_the_registry_counter_when_there_is_one():
    registry = _registry(p10=1, p20=2)
    session = _session(registry=registry)

    await svc.accrue_delivery_empties(
        session,
        rider_id=uuid4(),
        vendor_id=uuid4(),
        order_id=uuid4(),
        quantities_by_capacity={10: 4, 20: 5},
    )

    assert registry.pending_10L_empties == 5
    assert registry.pending_20L_empties == 7


@pytest.mark.asyncio
async def test_repeat_accrual_for_the_same_order_is_a_no_op():
    """Delivery completion is retried from the rider app's offline queue."""
    session = _session(existing_accrual_caps=(10, 20), registry=_registry())

    entries = await svc.accrue_delivery_empties(
        session,
        rider_id=uuid4(),
        vendor_id=uuid4(),
        order_id=uuid4(),
        quantities_by_capacity={10: 2, 20: 3},
    )

    assert entries == []
    assert session.added == []


@pytest.mark.asyncio
async def test_partial_replay_only_records_the_missing_capacity():
    registry = _registry()
    session = _session(existing_accrual_caps=(20,), registry=registry)

    entries = await svc.accrue_delivery_empties(
        session,
        rider_id=uuid4(),
        vendor_id=uuid4(),
        order_id=uuid4(),
        quantities_by_capacity={10: 2, 20: 3},
    )

    assert [e.capacity_litres for e in entries] == [10]
    assert registry.pending_20L_empties == 0   # untouched
    assert registry.pending_10L_empties == 2


@pytest.mark.asyncio
async def test_zero_quantities_write_nothing():
    session = _session(registry=_registry())
    assert await svc.accrue_delivery_empties(
        session, rider_id=uuid4(), vendor_id=uuid4(), order_id=uuid4(),
        quantities_by_capacity={10: 0, 20: 0},
    ) == []


# ── item → capacity mapping ───────────────────────────────────────────────


def test_quantities_from_order_items_groups_by_capacity():
    items = [
        SimpleNamespace(quantity=2, product=SimpleNamespace(capacity=20)),
        SimpleNamespace(quantity=3, product=SimpleNamespace(capacity=20)),
        SimpleNamespace(quantity=1, product=SimpleNamespace(capacity=10)),
    ]
    assert svc.quantities_from_order_items(items) == {20: 5, 10: 1}


def test_items_without_capacity_are_skipped_not_miscounted():
    items = [
        SimpleNamespace(id="a", quantity=2, product=SimpleNamespace(capacity=None)),
        SimpleNamespace(id="b", quantity=4, product=None),
        SimpleNamespace(id="c", quantity=1, product=SimpleNamespace(capacity=20)),
    ]
    assert svc.quantities_from_order_items(items) == {20: 1}


def test_unusual_capacity_still_enters_the_ledger():
    """A 5L product has no registry counter, but the audit trail must be complete."""
    items = [SimpleNamespace(id="a", quantity=6, product=SimpleNamespace(capacity=5))]
    assert svc.quantities_from_order_items(items) == {5: 6}


# ── settlement ────────────────────────────────────────────────────────────


def _settle_session(registry=None):
    session = AsyncMock()
    session.added = []
    session.add = MagicMock(side_effect=session.added.append)
    reg_result = MagicMock()
    reg_result.scalars.return_value.first.return_value = registry
    session.execute = AsyncMock(return_value=reg_result)
    return session


@pytest.mark.asyncio
async def test_settlement_rejects_more_than_is_owed():
    """Previously `max(0, current - received)` clamped silently, so a client
    sending 999 zeroed a real balance and the API reported success."""
    session = _settle_session(_registry(p20=5))

    with patch.object(svc, "get_outstanding_for_pair", AsyncMock(return_value={20: 5})), \
         pytest.raises(HTTPException) as exc:
        await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={20: 999},
        )

    assert exc.value.status_code == 400
    assert "owes 5" in exc.value.detail
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settlement_writes_a_negative_audit_entry():
    registry = _registry(p20=5)
    session = _settle_session(registry)

    with patch.object(
        svc, "get_outstanding_for_pair",
        AsyncMock(side_effect=[{20: 5}, {20: 2}]),
    ):
        result = await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={20: 3},
            actor_clerk_id="user_vendor_1",
        )

    entry = session.added[0]
    assert entry.quantity == -3
    assert entry.entry_type == BottleLedgerEntryType.VENDOR_RECEIPT
    assert entry.actor_clerk_id == "user_vendor_1"   # who confirmed it
    assert registry.pending_20L_empties == 2
    assert result["pending_20L_empties"] == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_works_without_a_registry_row():
    """Radar riders have no registry row; the endpoint used to 404, leaving them
    unable to return bottles they were charged for."""
    session = _settle_session(None)

    with patch.object(
        svc, "get_outstanding_for_pair",
        AsyncMock(side_effect=[{20: 4}, {20: 1}]),
    ):
        result = await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={20: 3},
        )

    assert session.added[0].quantity == -3
    assert result["pending_20L_empties"] == 1


@pytest.mark.asyncio
async def test_settlement_rejects_negative_input():
    session = _settle_session(_registry(p10=5))
    with pytest.raises(HTTPException) as exc:
        await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={10: -5},
        )
    assert exc.value.status_code == 400
    assert "negative" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_settlement_rejects_an_empty_submission():
    session = _settle_session(_registry())
    with pytest.raises(HTTPException) as exc:
        await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={10: 0, 20: 0},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_settlement_locks_the_registry_row():
    """Read-modify-write on a counter; without FOR UPDATE a vendor confirming on
    two devices loses a decrement."""
    session = _settle_session(_registry(p20=5))

    with patch.object(
        svc, "get_outstanding_for_pair",
        AsyncMock(side_effect=[{20: 5}, {20: 4}]),
    ):
        await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={20: 1},
        )

    statement = str(session.execute.await_args.args[0]).upper()
    assert "FOR UPDATE" in statement


@pytest.mark.asyncio
async def test_counter_never_goes_negative():
    """The ledger keeps the true signed history; a negative 'owed' counter would
    render as nonsense in both apps."""
    registry = _registry(p20=1)
    session = _settle_session(registry)

    with patch.object(
        svc, "get_outstanding_for_pair",
        AsyncMock(side_effect=[{20: 3}, {20: 0}]),
    ):
        await svc.settle_empties(
            session, rider_id=uuid4(), vendor_id=uuid4(),
            received_by_capacity={20: 3},
        )

    assert registry.pending_20L_empties == 0


@pytest.mark.asyncio
async def test_history_requires_a_subject():
    with pytest.raises(HTTPException) as exc:
        await svc.get_ledger_history(AsyncMock())
    assert exc.value.status_code == 400
