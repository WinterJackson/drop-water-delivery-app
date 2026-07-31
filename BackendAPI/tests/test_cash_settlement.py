"""
Cash-order settlement and the single spendable balance.

Riders pay for cash orders out of their own wallet float and keep the customer's
cash. That only works if one number governs both withdrawing and spending. It did
not: withdrawal eligibility came from a derived sum of `rider_net` over delivered
orders, cash float was checked against the stored `wallet_balance`, and payouts
debited neither. A rider could therefore withdraw their earnings by M-Pesa and
then spend the same untouched balance as float — keeping the customer's cash while
the platform funded the vendor's cut.

These tests pin the closed version: `wallet_balance` is the balance, payouts debit
it, and float already committed to open cash orders is not available for anything
else.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services import settlement_service as svc


def _session_returning(value):
    session = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = value
    session.execute = AsyncMock(return_value=result)
    return session


# ── committed float ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_committed_float_sums_vendor_and_platform_cuts():
    session = _session_returning(Decimal("1450.00"))
    assert await svc.committed_cash_float(session, uuid4()) == Decimal("1450.00")


@pytest.mark.asyncio
async def test_committed_float_is_zero_when_carrying_nothing():
    assert await svc.committed_cash_float(_session_returning(None), uuid4()) == Decimal("0")


def test_open_statuses_cover_the_whole_carry_window():
    """A rider holds the goods from acceptance until the order reaches a terminal
    state. Dropping any of these would free float that is still committed."""
    for status in ("accepted", "preparing", "ready", "picked_up"):
        assert status in svc.OPEN_CASH_ORDER_STATUSES
    # Disputes are not terminal — the order can still complete.
    assert "pending_review" in svc.OPEN_CASH_ORDER_STATUSES
    assert "mismatch_pending" in svc.OPEN_CASH_ORDER_STATUSES
    # Terminal states must NOT hold float.
    assert "delivered" not in svc.OPEN_CASH_ORDER_STATUSES
    assert "cancelled" not in svc.OPEN_CASH_ORDER_STATUSES


# ── available for payout ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_available_excludes_float_committed_to_open_cash_orders():
    """The core fix. A rider holding a cash order cannot withdraw the float
    backing it and leave the platform to pay the vendor."""
    session = AsyncMock()
    with patch.object(svc, "committed_cash_float", AsyncMock(return_value=Decimal("4000"))):
        available = await svc.available_for_payout(
            session, provider_id=uuid4(), provider_type="rider", wallet_balance=Decimal("5000")
        )
    assert available == Decimal("1000")


@pytest.mark.asyncio
async def test_available_is_never_negative():
    """A rider who owes more than they hold has nothing available; the debt shows
    as a negative balance, not a negative allowance."""
    session = AsyncMock()
    with patch.object(svc, "committed_cash_float", AsyncMock(return_value=Decimal("6000"))):
        available = await svc.available_for_payout(
            session, provider_id=uuid4(), provider_type="rider", wallet_balance=Decimal("5000")
        )
    assert available == Decimal("0")


@pytest.mark.asyncio
async def test_full_balance_is_available_with_no_open_cash_orders():
    session = AsyncMock()
    with patch.object(svc, "committed_cash_float", AsyncMock(return_value=Decimal("0"))):
        available = await svc.available_for_payout(
            session, provider_id=uuid4(), provider_type="rider", wallet_balance=Decimal("2500.50")
        )
    assert available == Decimal("2500.50")


@pytest.mark.asyncio
async def test_wholesale_vendor_float_is_the_platform_cut_only():
    """On a wholesale cash order the vendor's own rider collects the cash, so the
    vendor holds it; only the platform's cut is owed."""
    session = AsyncMock()
    with patch.object(
        svc, "committed_cash_float_for_vendor", AsyncMock(return_value=Decimal("300"))
    ):
        available = await svc.available_for_payout(
            session, provider_id=uuid4(), provider_type="vendor", wallet_balance=Decimal("1000")
        )
    assert available == Decimal("700")


@pytest.mark.asyncio
async def test_balance_is_read_as_decimal_not_float():
    """`Deliverers.wallet_balance` used to be a Float column mutated with float
    arithmetic; repeated settlements drifted the balance."""
    session = AsyncMock()
    with patch.object(svc, "committed_cash_float", AsyncMock(return_value=Decimal("0.10"))):
        available = await svc.available_for_payout(
            session, provider_id=uuid4(), provider_type="rider", wallet_balance=0.30
        )
    assert available == Decimal("0.20")   # 0.30 - 0.10 exactly, no float residue


# ── the withdraw-then-spend sequence ──────────────────────────────────────


@pytest.mark.asyncio
async def test_withdrawal_is_blocked_once_float_is_committed():
    """End-to-end shape of the exploit: balance 5000, one cash order committing
    4000, so only 1000 may leave. Requesting 5000 must fail and must explain why."""
    from services.payout_service import request_payout
    from schemas.payout_schemas import PayoutCreate

    rider_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))
    owner = SimpleNamespace(wallet_balance=Decimal("5000"), clerk_id="clerk_r1")

    with patch(
        "services.payout_service._get_provider_details",
        new_callable=AsyncMock, return_value=(rider_id, "rider"),
    ), patch(
        "services.payout_service._get_provider_row",
        new_callable=AsyncMock, return_value=owner,
    ), patch(
        "services.settlement_service.committed_cash_float",
        new_callable=AsyncMock, return_value=Decimal("4000"),
    ), pytest.raises(HTTPException) as exc:
        await request_payout(
            session,
            "clerk_r1",
            PayoutCreate(amount=5000.0, payment_method="mpesa", account_details="254700000000"),
        )

    assert exc.value.status_code == 400
    assert "insufficient" in exc.value.detail.lower()
    # The rider must be told where their money went, not just refused.
    assert "float" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_failed_disbursement_returns_the_debited_amount():
    """The debit happens before the B2C call, so a failure must refund it or the
    payout silently confiscates the money."""
    from services.payout_service import request_payout
    from schemas.payout_schemas import PayoutCreate
    from models.wallet_transaction_model import TransactionType, WalletTransaction

    rider_id = uuid4()
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))
    owner = SimpleNamespace(wallet_balance=Decimal("5000"), clerk_id="clerk_r1")

    with patch(
        "services.payout_service._get_provider_details",
        new_callable=AsyncMock, return_value=(rider_id, "rider"),
    ), patch(
        "services.payout_service._get_provider_row",
        new_callable=AsyncMock, return_value=owner,
    ), patch(
        "services.settlement_service.committed_cash_float",
        new_callable=AsyncMock, return_value=Decimal("0"),
    ), patch(
        "services.payment_service.initiate_b2c_payout",
        new_callable=AsyncMock, return_value={"success": False, "error": "declined"},
    ), patch(
        "services.notification_service.create_notification", new_callable=AsyncMock,
    ):
        await request_payout(
            session,
            "clerk_r1",
            PayoutCreate(amount=1000.0, payment_method="mpesa", account_details="254700000000"),
        )

    ledger = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], WalletTransaction)]
    kinds = [e.transaction_type for e in ledger]
    assert TransactionType.withdrawal in kinds
    assert TransactionType.refund in kinds
    # Net effect on the balance is zero.
    assert sum(e.amount for e in ledger) == Decimal("0")
    assert owner.wallet_balance == Decimal("5000")


# ── the ledger helper ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_wallet_delta_moves_balance_and_writes_one_row():
    from services.wallet_service import apply_wallet_delta
    from models.wallet_transaction_model import TransactionType

    session = AsyncMock()
    session.add = MagicMock()
    owner = SimpleNamespace(wallet_balance=Decimal("100"))

    entry = await apply_wallet_delta(
        session, owner=owner, clerk_id="c1", user_type="rider",
        amount=Decimal("-40"), transaction_type=TransactionType.order_payment,
        description="Cash order settled from float",
    )

    assert owner.wallet_balance == Decimal("60")
    assert entry.amount == Decimal("-40")     # sign preserved for reconciliation
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_apply_wallet_delta_ignores_a_zero_move():
    from services.wallet_service import apply_wallet_delta
    from models.wallet_transaction_model import TransactionType

    session = AsyncMock()
    session.add = MagicMock()
    owner = SimpleNamespace(wallet_balance=Decimal("100"))

    assert await apply_wallet_delta(
        session, owner=owner, clerk_id="c1", user_type="rider", amount=0,
        transaction_type=TransactionType.order_payment, description="noop",
    ) is None
    assert owner.wallet_balance == Decimal("100")
    session.add.assert_not_called()


# ── sign convention ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_withdrawal_is_recorded_as_a_negative_amount():
    """`transaction_type` cannot carry direction: `order_payment` debits a rider
    settling cash-order float and credits them delivery earnings. The sign does."""
    from models.wallet_transaction_model import TransactionType, WalletTransaction
    from services.wallet_service import apply_wallet_delta

    session = AsyncMock()
    session.add = MagicMock()
    owner = SimpleNamespace(wallet_balance=Decimal("1000"))

    debit = await apply_wallet_delta(
        session, owner=owner, clerk_id="c1", user_type="rider", amount=Decimal("-250"),
        transaction_type=TransactionType.withdrawal, description="withdraw",
    )
    credit = await apply_wallet_delta(
        session, owner=owner, clerk_id="c1", user_type="rider", amount=Decimal("400"),
        transaction_type=TransactionType.order_payment, description="earnings",
    )

    assert debit.amount < 0 and credit.amount > 0
    # Same type, opposite directions — only the sign distinguishes them.
    assert credit.transaction_type == TransactionType.order_payment
    assert owner.wallet_balance == Decimal("1150")


@pytest.mark.asyncio
async def test_summing_the_ledger_reproduces_the_balance_movement():
    from models.wallet_transaction_model import TransactionType
    from services.wallet_service import apply_wallet_delta

    session = AsyncMock()
    session.add = MagicMock()
    owner = SimpleNamespace(wallet_balance=Decimal("0"))

    moves = [
        (Decimal("5000"), TransactionType.top_up),
        (Decimal("-1450"), TransactionType.order_payment),   # cash order float
        (Decimal("300"), TransactionType.order_payment),     # delivery earnings
        (Decimal("-1000"), TransactionType.withdrawal),
    ]
    entries = []
    for amount, kind in moves:
        entries.append(
            await apply_wallet_delta(
                session, owner=owner, clerk_id="c1", user_type="rider",
                amount=amount, transaction_type=kind, description="x",
            )
        )

    assert sum(e.amount for e in entries) == owner.wallet_balance == Decimal("2850")
