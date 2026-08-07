"""Wallet security — regression guard for finding B6 and M11.

`POST /api/wallet/top-up` hands the CheckoutRequestID back to the caller. The
top-up callback had no shared secret, no Safaricom IP allow-list and no amount
validation, so anyone who started a top-up could POST a synthetic
`{"ResultCode": 0}` for their own reference and be credited without paying — and
wallet credit is spendable at checkout.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import os
import pytest

from main import app
from models.wallet_transaction_model import TransactionStatus, TransactionType, UserType
from utils.verify_user_token import get_current_user


def _callback(checkout_id="ws_CO_TOPUP", result_code=0, amount=500, receipt="QJI4ABCDEF"):
    metadata = []
    if amount is not None:
        metadata.append({"Name": "Amount", "Value": amount})
    if receipt is not None:
        metadata.append({"Name": "MpesaReceiptNumber", "Value": receipt})
    return {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": checkout_id,
                "ResultCode": result_code,
                "ResultDesc": "The service request is processed successfully." if result_code == 0 else "Cancelled",
                "CallbackMetadata": {"Item": metadata},
            }
        }
    }


def _pending_topup(amount="500"):
    txn = MagicMock()
    txn.id = uuid4()
    txn.user_id = "customer_clerk"
    txn.user_type = UserType.customer
    txn.transaction_type = TransactionType.top_up
    txn.amount = Decimal(amount)
    txn.status = TransactionStatus.pending
    return txn


def _session_with(transaction, owner=None):
    session = AsyncMock()
    txn_result = MagicMock()
    txn_result.scalars.return_value.first.return_value = transaction

    owner_result = MagicMock()
    owner_result.scalars.return_value.first.return_value = owner

    session.execute = AsyncMock(side_effect=[txn_result, owner_result])
    session.commit = AsyncMock()
    return session


# ── Transport guards (route level) ───────────────────────────────────────────

# The guard now lives in `payment_service.reject_mpesa_callback` and reads its
# secret from the environment at call time, so these patch the environment
# rather than a module constant. Reading it per-call is deliberate: as a
# module-level constant it froze at import, and rotating the secret on Render
# needed a redeploy to take effect.

@pytest.mark.asyncio
async def test_callback_rejected_without_shared_secret(client):
    with patch.dict(os.environ, {"MPESA_CALLBACK_SECRET": "s3cret", "ENV": "production"}):
        response = await client.post("/api/wallet/mpesa-callback", json=_callback())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_callback_rejected_with_wrong_shared_secret(client):
    with patch.dict(os.environ, {"MPESA_CALLBACK_SECRET": "s3cret", "ENV": "production"}):
        response = await client.post("/api/wallet/mpesa-callback?secret=guess", json=_callback())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_callback_rejected_from_non_safaricom_ip(client):
    """In production the source IP must be Safaricom's, even with the right secret."""
    with patch.dict(os.environ, {"MPESA_CALLBACK_SECRET": "s3cret", "ENV": "production"}), \
         patch("services.payment_service.is_safaricom_ip", return_value=False):
        response = await client.post("/api/wallet/mpesa-callback?secret=s3cret", json=_callback())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_callback_refused_when_no_secret_is_configured(client):
    """Crediting a wallet must not fall open just because the secret is missing.

    `POST /top-up` hands the CheckoutRequestID back to the caller, so an
    unguarded callback lets anyone replay it with `ResultCode: 0` and credit
    themselves — and wallet credit is spendable at checkout.
    """
    env = {k: v for k, v in os.environ.items() if k != "MPESA_CALLBACK_SECRET"}
    env["ENV"] = "production"
    with patch.dict(os.environ, env, clear=True):
        response = await client.post("/api/wallet/mpesa-callback", json=_callback())
    assert response.status_code == 503


# ── Settlement guards (service level) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_forged_amount_is_rejected_and_nothing_is_credited():
    """A callback claiming more than we asked for must not credit the wallet."""
    from services.wallet_service import handle_mpesa_topup_callback

    txn = _pending_topup("500")
    owner = MagicMock()
    owner.wallet_balance = Decimal("0")
    session = _session_with(txn, owner)

    result = await handle_mpesa_topup_callback(session=session, payload=_callback(amount=50_000))

    assert result["reason"] == "amount_mismatch"
    assert owner.wallet_balance == Decimal("0")
    assert txn.status == TransactionStatus.failed


@pytest.mark.asyncio
async def test_missing_amount_is_rejected():
    from services.wallet_service import handle_mpesa_topup_callback

    txn = _pending_topup("500")
    session = _session_with(txn, MagicMock(wallet_balance=Decimal("0")))

    result = await handle_mpesa_topup_callback(session=session, payload=_callback(amount=None))
    assert result["reason"] == "missing_amount"
    assert txn.status == TransactionStatus.failed


@pytest.mark.asyncio
async def test_missing_receipt_is_rejected():
    """No receipt means we cannot reconcile or reverse the payment later."""
    from services.wallet_service import handle_mpesa_topup_callback

    txn = _pending_topup("500")
    session = _session_with(txn, MagicMock(wallet_balance=Decimal("0")))

    result = await handle_mpesa_topup_callback(session=session, payload=_callback(receipt=None))
    assert result["reason"] == "missing_receipt"


@pytest.mark.asyncio
async def test_replayed_callback_credits_only_once():
    """A settled transaction ignores repeat callbacks."""
    from services.wallet_service import handle_mpesa_topup_callback

    txn = _pending_topup("500")
    txn.status = TransactionStatus.completed  # already settled
    owner = MagicMock()
    owner.wallet_balance = Decimal("500")
    session = _session_with(txn, owner)

    result = await handle_mpesa_topup_callback(session=session, payload=_callback())

    assert result["status"] == "already_settled"
    assert owner.wallet_balance == Decimal("500")  # not credited twice


@pytest.mark.asyncio
async def test_genuine_callback_credits_the_wallet():
    from services.wallet_service import handle_mpesa_topup_callback

    txn = _pending_topup("500")
    owner = MagicMock()
    owner.wallet_balance = Decimal("120")
    session = _session_with(txn, owner)

    result = await handle_mpesa_topup_callback(session=session, payload=_callback(amount=500))

    assert result["status"] == "success"
    assert owner.wallet_balance == Decimal("620")
    assert txn.status == TransactionStatus.completed
    assert txn.mpesa_receipt_number == "QJI4ABCDEF"


@pytest.mark.asyncio
async def test_unknown_reference_is_not_found():
    from services.wallet_service import handle_mpesa_topup_callback

    session = _session_with(None)
    result = await handle_mpesa_topup_callback(session=session, payload=_callback())
    assert result["status"] == "not_found"


# ── Ownership guards ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_act_on_a_wallet_type_you_do_not_own():
    """`user_type` is client input, so it must be verified against the token.

    Otherwise a caller could name any entity type and operate on that wallet.
    """
    from fastapi import HTTPException
    from services.wallet_service import resolve_wallet_owner

    session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=empty)

    with pytest.raises(HTTPException) as exc:
        await resolve_wallet_owner(session, "customer_clerk", "vendor")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unknown_wallet_type_is_rejected():
    from fastapi import HTTPException
    from services.wallet_service import resolve_wallet_owner

    with pytest.raises(HTTPException) as exc:
        await resolve_wallet_owner(AsyncMock(), "customer_clerk", "administrator")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_withdrawal_below_minimum_is_rejected():
    from fastapi import HTTPException
    from services.wallet_service import initiate_wallet_withdrawal

    from models.user_model import User
    with pytest.raises(HTTPException) as exc, \
         patch("services.wallet_service.resolve_wallet_owner", new_callable=AsyncMock) as mock_resolve, \
         patch("services.settlement_service.withdrawal_terms", new_callable=AsyncMock) as mock_terms:
        mock_resolve.return_value = ("customer", User, MagicMock(id=uuid4()))
        mock_terms.return_value = (Decimal("250"), Decimal("0"), Decimal("1000"))
        await initiate_wallet_withdrawal(
            session=_session_with(transaction=MagicMock(wallet_balance=Decimal("200"))), user_id="customer_clerk", user_type="customer",
            amount=100, phone="254700000000",
        )
    assert exc.value.status_code == 400
    assert "Minimum withdrawal" in exc.value.detail


@pytest.mark.asyncio
async def test_topup_rejects_malformed_phone():
    from fastapi import HTTPException
    from services.wallet_service import initiate_wallet_topup

    from models.user_model import User
    with pytest.raises(HTTPException) as exc, \
         patch("services.wallet_service.resolve_wallet_owner", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = ("customer", User, MagicMock(id=uuid4()))
        await initiate_wallet_topup(
            session=_session_with(transaction=MagicMock()), user_id="customer_clerk", user_type="customer",
            amount=500, phone="0700000000",
        )
    assert exc.value.status_code == 400
    assert "2547" in exc.value.detail
