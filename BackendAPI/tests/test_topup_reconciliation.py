"""Settling a top-up from an STK query, when its callback never arrived.

The callback for every wallet top-up was delivered to the *order* endpoint,
which resolves a `CheckoutRequestID` against `Orders`, found nothing, and
returned 400 — so the money left the customer's phone and the transaction sat
`pending` for ever. Naming the callback URL per caller stops that recurring;
this path is what recovers the money already taken, and what catches the
ordinary case of Safaricom exhausting its retries against a restart.

It settles from a *query*, which is a weaker source than a callback: Daraja's
`stkpushquery` answers with a result code and carries **no receipt and no
amount**. Everything below is about not overreaching from that.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from models.wallet_transaction_model import TransactionStatus, TransactionType, UserType
from services import wallet_service


def _pending_topup(amount="500"):
    txn = MagicMock()
    txn.id = uuid4()
    txn.user_id = "customer_clerk"
    txn.user_type = UserType.customer
    txn.transaction_type = TransactionType.top_up
    txn.amount = Decimal(amount)
    txn.status = TransactionStatus.pending
    txn.reference_id = "ws_CO_STRANDED"
    txn.wallet_owner_id = uuid4()
    txn.mpesa_receipt_number = None
    txn.description = "M-Pesa STK Push Top Up"
    return txn


def _owner(balance="1000"):
    owner = MagicMock()
    owner.id = uuid4()
    owner.wallet_balance = Decimal(balance)
    return owner


def _session_returning(owner):
    session = AsyncMock()
    owner_result = MagicMock()
    owner_result.scalars.return_value.first.return_value = owner
    session.execute = AsyncMock(return_value=owner_result)
    session.commit = AsyncMock()
    return session


def _outcome(state, result_code=None, result_desc="", reason=None):
    return {
        "state": state,
        "result_code": result_code,
        "result_desc": result_desc,
        "reason": reason,
    }


@pytest.mark.asyncio
async def test_a_successful_query_credits_the_amount_that_was_requested():
    """A query carries no Amount, so the credit is what we asked for.

    That is exact rather than approximate: an STK push collects the amount in
    the request and the payer cannot edit it on the handset.
    """
    txn = _pending_topup("500")
    owner = _owner("1000")
    session = _session_returning(owner)

    result = await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("success", "0", "Success")
    )

    assert result["status"] == "success"
    assert owner.wallet_balance == Decimal("1500")
    assert txn.status == TransactionStatus.completed


@pytest.mark.asyncio
async def test_a_reconciled_credit_invents_no_receipt_number():
    """`mpesa_receipt_number` is indexed and reconciled against real M-Pesa
    statements. A synthetic value there is a fabricated Safaricom reference
    that looks exactly like a real one to whoever reads it next."""
    txn = _pending_topup("500")
    session = _session_returning(_owner())

    await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("success", "0", "Success")
    )

    assert txn.mpesa_receipt_number is None
    # But the row must say how it was settled, or the missing receipt is
    # indistinguishable from a callback that lost one.
    assert "reconciliation" in txn.description


@pytest.mark.asyncio
async def test_a_failed_query_fails_the_transaction_and_moves_no_money():
    txn = _pending_topup("500")
    owner = _owner("1000")
    session = _session_returning(owner)

    result = await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("failed", "1032", "Request cancelled by user")
    )

    assert result["status"] == "failed"
    assert txn.status == TransactionStatus.failed
    assert txn.failure_reason == "Transaction cancelled by user"
    assert owner.wallet_balance == Decimal("1000")


@pytest.mark.asyncio
async def test_an_unknown_failure_code_reports_safaricoms_own_words():
    txn = _pending_topup()
    session = _session_returning(_owner())

    await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("failed", "9999", "Some new Daraja condition")
    )

    assert "Some new Daraja condition" in txn.failure_reason


@pytest.mark.asyncio
async def test_an_already_settled_transaction_is_never_credited_twice():
    """A real callback landing between the sweep's select and its settle."""
    txn = _pending_topup("500")
    txn.status = TransactionStatus.completed
    owner = _owner("1000")
    session = _session_returning(owner)

    result = await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("success", "0", "Success")
    )

    assert result["status"] == "already_settled"
    assert owner.wallet_balance == Decimal("1000")


@pytest.mark.asyncio
async def test_a_missing_account_fails_rather_than_crediting_nothing_silently():
    txn = _pending_topup("500")
    session = _session_returning(None)

    result = await wallet_service.settle_pending_topup_from_query(
        session, txn, _outcome("success", "0", "Success")
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "account_not_found"
    assert txn.status == TransactionStatus.failed


# ── The sweep's own decisions ─────────────────────────────────────────────


def test_the_sweep_waits_before_asking_about_a_fresh_push():
    """Safaricom will not resolve a push whose prompt is still on the handset,
    and a customer typing their PIN is not a stranded transaction."""
    from jobs.reconcile_pending_topups import MIN_AGE_MINUTES

    # Safaricom's STK prompt expires at about 60 seconds.
    assert MIN_AGE_MINUTES >= 2


def test_the_reconciliation_window_is_a_settings_row_not_a_literal():
    """A business value that sits in the source is a defect here — an operator
    cannot widen the window when Daraja has been down for a day."""
    import inspect

    from jobs import reconcile_pending_topups
    from services import platform_config_service

    source = inspect.getsource(reconcile_pending_topups)
    assert "topup_reconcile_max_age_hours" in source

    keys = {spec.key for spec in platform_config_service.SPECS}
    assert "topup_reconcile_max_age_hours" in keys


def test_a_pending_query_is_never_a_reason_to_settle():
    """`pending` means *we could not find out*. The sweep must skip, not guess.

    Asserted against the source because the branch guards a wallet credit: the
    failure mode is crediting on an unanswerable query, and that is the shape
    of mistake this whole file exists because of.
    """
    import inspect

    from jobs import reconcile_pending_topups

    source = inspect.getsource(reconcile_pending_topups.run_reconcile_pending_topups)
    assert 'outcome["state"] == "pending"' in source
    assert "continue" in source.split('outcome["state"] == "pending"')[1][:200]
