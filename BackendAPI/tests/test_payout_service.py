"""
Tests for payout_service: request_payout balance validation, wallet debiting and
advisory locking. Pure mocks — no real database.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from schemas.payout_schemas import PayoutCreate


def _owner(balance):
    """Stand-in for a Deliverer/Vendor row with a real Decimal balance."""
    return SimpleNamespace(wallet_balance=Decimal(str(balance)), clerk_id="clerk_v1")


@pytest.mark.asyncio
async def test_request_payout_insufficient_balance():
    """request_payout should raise 400 when requested amount exceeds available balance."""
    from services.payout_service import request_payout

    clerk_id = "clerk_v1"
    vendor_id = uuid4()

    session = AsyncMock()
    # Advisory lock call succeeds (returns result)
    session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))

    with patch(
        "services.payout_service._get_provider_details",
        new_callable=AsyncMock,
        return_value=(vendor_id, "vendor"),
    ), patch(
        "services.payout_service._get_provider_row",
        new_callable=AsyncMock,
        return_value=_owner(500),
    ), patch(
        "services.payout_service._get_available_balance",
        new_callable=AsyncMock,
        return_value=Decimal("500"),  # Only 500 available
    ), patch(
        "services.settlement_service.committed_cash_float_for_vendor",
        new_callable=AsyncMock,
        return_value=Decimal("0"),
    ):
        with pytest.raises(HTTPException) as exc:
            await request_payout(
                session,
                clerk_id,
                PayoutCreate(amount=1000.0, payment_method="mpesa", account_details="254700000000"),
            )

    assert exc.value.status_code == 400
    assert "insufficient" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_request_payout_success():
    """request_payout should create a Payout record and commit when balance is sufficient."""
    from services.payout_service import request_payout

    clerk_id = "clerk_v1"
    vendor_id = uuid4()

    session = AsyncMock()
    session.add = MagicMock()
    # Advisory lock call
    session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))

    with patch(
        "services.payout_service._get_provider_details",
        new_callable=AsyncMock,
        return_value=(vendor_id, "vendor"),
    ), patch(
        "services.payout_service._get_provider_row",
        new_callable=AsyncMock,
        return_value=_owner(2000),
    ), patch(
        "services.payout_service._get_available_balance",
        new_callable=AsyncMock,
        return_value=Decimal("2000"),
    ), patch(
        # Patch where it is defined: request_payout imports it inside the function,
        # so patching the payout_service namespace never took effect and the real
        # call was silently failing into the refund path.
        "services.payment_service.initiate_b2c_payout",
        new_callable=AsyncMock,
        return_value={"success": True, "ConversationID": "AG_123"},
    ), patch(
        "services.notification_service.create_notification",
        new_callable=AsyncMock,
    ):
        payout = await request_payout(
            session,
            clerk_id,
            PayoutCreate(amount=500.0, payment_method="mpesa", account_details="254700000000"),
        )

    # Two rows: the Payout itself and the withdrawal ledger entry. The balance is
    # debited up front so the same money cannot also be spent as cash-order float
    # while the disbursement is in flight.
    added = [c.args[0] for c in session.add.call_args_list]
    assert len(added) == 2, [type(a).__name__ for a in added]

    from models.payout_model import Payout
    from models.wallet_transaction_model import TransactionType, WalletTransaction

    assert isinstance(added[0], Payout)
    ledger = added[1]
    assert isinstance(ledger, WalletTransaction)
    assert ledger.transaction_type == TransactionType.withdrawal
    assert ledger.amount == Decimal("-500")      # signed debit
    # A successful disbursement must not also refund.
    assert not any(
        getattr(a, "transaction_type", None) == TransactionType.refund for a in added
    )
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_request_payout_zero_amount():
    """request_payout should reject zero or negative amounts."""
    from services.payout_service import request_payout

    session = AsyncMock()

    with patch(
        "services.payout_service._get_provider_details",
        new_callable=AsyncMock,
        return_value=(uuid4(), "vendor"),
    ):
        with pytest.raises(HTTPException) as exc:
            await request_payout(
                session,
                "clerk_v1",
                PayoutCreate(amount=0, payment_method="mpesa", account_details="254700000000"),
            )

    assert exc.value.status_code == 400
    assert "greater than zero" in exc.value.detail.lower()
