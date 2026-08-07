"""
Both ways out of a wallet must agree, and both must respect committed float.

There were two withdrawal endpoints and they disagreed on everything that
mattered:

| | `POST /api/payouts/request` | `POST /api/wallet/withdraw` |
|---|---|---|
| Minimum | 250 / 500 / 1000 by account type | flat 500 |
| Fee waived on | the **amount** requested | the **balance** held |
| Committed cash float | subtracted | **ignored** |

The last row is the money defect. A rider carrying KSH 5,000 of open cash orders
and holding KSH 5,000 was refused by the first endpoint and allowed by the
second; they could withdraw the float backing those orders, deliver, and be
debited into a negative balance the platform has no way to collect. The
docstring in `vendor_management_service` even asserted this endpoint refused on
the same figure. It did not.

Both now read one schedule from `settlement_service`, and both call
`assert_withdrawable`.
"""
import ast
import pathlib
from decimal import Decimal

import pytest

from services import platform_config_service as config
from services import settlement_service


# ── One schedule, from settings ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_account_type_gets_its_own_terms(db_session=None):
    """Rider, retail vendor and wholesale vendor differ — by id, not by guesswork.

    A clerk-id lookup returns an arbitrary one of an owner's stores, so a
    wholesale branch could be handed the retail threshold depending on row order.
    """
    from unittest.mock import AsyncMock

    session = AsyncMock()

    rider_min, fee, rider_waiver = await settlement_service.withdrawal_terms(
        session, provider_type="rider"
    )
    retail_min, _, retail_waiver = await settlement_service.withdrawal_terms(
        session, provider_type="vendor", vendor_type="retail_refill"
    )
    wholesale_min, _, wholesale_waiver = await settlement_service.withdrawal_terms(
        session, provider_type="vendor", vendor_type="wholesale_b2b"
    )

    assert rider_min == config.get_decimal("payout_min_rider")
    assert retail_min == config.get_decimal("payout_min_retail_vendor")
    assert wholesale_min == config.get_decimal("payout_min_wholesale_vendor")
    assert fee == config.get_decimal("payout_transaction_fee")

    # Bigger balances, bigger minimums — one B2C tariff per disbursement.
    assert rider_min < retail_min < wholesale_min
    assert rider_waiver < retail_waiver < wholesale_waiver


def test_the_fee_is_waived_on_the_amount_not_the_balance():
    """Waiving on the balance rewards sitting on money rather than withdrawing it.

    That is backwards: the platform pays one M-Pesa tariff per disbursement, so
    it wants fewer and larger withdrawals, not a fee holiday for whoever hoards.
    """
    fee = Decimal("15")
    waiver = Decimal("1000")

    assert settlement_service.fee_for(Decimal("999"), fee, waiver) == fee
    assert settlement_service.fee_for(Decimal("1000"), fee, waiver) == Decimal("0")
    assert settlement_service.fee_for(Decimal("5000"), fee, waiver) == Decimal("0")


def test_the_settings_refuse_a_schedule_that_cannot_work():
    """A minimum at or below the fee guarantees every minimum withdrawal is refused."""
    with pytest.raises(ValueError, match="covering its own cost"):
        config.validate_all({"payout_min_rider": 15.0, "payout_transaction_fee": 15.0})


def test_the_settings_refuse_a_waiver_below_the_minimum():
    """A waiver under the minimum means the fee is never charged at all — which
    may be intended, but should be expressed by setting the fee to zero."""
    with pytest.raises(ValueError, match="fee waiver threshold is below"):
        config.validate_all(
            {"payout_fee_waiver_rider": 100.0, "payout_min_rider": 250.0}
        )


# ── The float check, on both paths ────────────────────────────────────────


def _withdrawal_functions():
    """The two functions a client can reach to take money out of a wallet."""
    return (
        ("services/wallet_service.py", "initiate_wallet_withdrawal"),
        ("services/payout_service.py", "request_payout"),
    )


@pytest.mark.parametrize("module_path,function_name", _withdrawal_functions())
def test_every_withdrawal_path_checks_committed_float(module_path, function_name):
    """Structural, not behavioural, and deliberately so.

    A unit test proves the two paths that exist today are correct. This fails the
    build when a third is added without the check — which is exactly how the
    second one came to be missing it.
    """
    tree = ast.parse(pathlib.Path(module_path).read_text())

    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    assert target is not None, f"{function_name} not found in {module_path}"

    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
    }

    assert "assert_withdrawable" in called, (
        f"{module_path}::{function_name} does not call "
        "`settlement_service.assert_withdrawable`.\n\n"
        "A wallet balance is not what is spendable: money already promised to "
        "open cash orders is settled when the rider delivers. Comparing against "
        "the raw balance lets them withdraw the float backing those orders and "
        "then deliver into arrears the platform cannot collect."
    )


@pytest.mark.parametrize("module_path,function_name", _withdrawal_functions())
def test_no_withdrawal_path_carries_its_own_limits(module_path, function_name):
    """The thresholds live in `Platform_Settings`, read through one helper.

    Both functions previously hardcoded their own — 500 against 250/500/1000,
    and two different waiver rules — so the same withdrawal cost a different
    amount depending on which endpoint the app happened to call.
    """
    tree = ast.parse(pathlib.Path(module_path).read_text())
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )

    # The figures that used to be inline. Any of them appearing as a literal in
    # a withdrawal function means a schedule has been re-introduced locally.
    banned = {250, 500, 1000, 2500, 5000}
    found = {
        node.value
        for node in ast.walk(target)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and node.value in banned
    }

    assert not found, (
        f"{module_path}::{function_name} hardcodes {sorted(found)}. "
        "Withdrawal minimums and waivers are `Platform_Settings` rows — read them "
        "through `settlement_service.withdrawal_terms`."
    )


@pytest.mark.asyncio
async def test_available_is_the_balance_minus_committed_float():
    """The equation itself, stated once so it cannot be quietly re-derived."""
    from unittest.mock import AsyncMock, patch

    with patch.object(
        settlement_service, "committed_cash_float", AsyncMock(return_value=Decimal("4000"))
    ):
        available = await settlement_service.available_for_payout(
            AsyncMock(), provider_id="rider-1", provider_type="rider", wallet_balance=Decimal("5000")
        )
    assert available == Decimal("1000")


@pytest.mark.asyncio
async def test_a_rider_owing_more_than_they_hold_has_nothing_available():
    """Never negative. The debt shows as a negative `wallet_balance`, which is
    a real figure, rather than as a negative allowance, which is not."""
    from unittest.mock import AsyncMock, patch

    with patch.object(
        settlement_service, "committed_cash_float", AsyncMock(return_value=Decimal("6000"))
    ):
        available = await settlement_service.available_for_payout(
            AsyncMock(), provider_id="rider-1", provider_type="rider", wallet_balance=Decimal("5000")
        )
    assert available == Decimal("0")


@pytest.mark.asyncio
async def test_the_refusal_explains_where_the_money_went():
    """A rider staring at a balance they cannot withdraw opens a support ticket
    every time. The message has to name the committed figure."""
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    with patch.object(
        settlement_service, "committed_cash_float", AsyncMock(return_value=Decimal("4000"))
    ):
        with pytest.raises(HTTPException) as raised:
            await settlement_service.assert_withdrawable(
                AsyncMock(),
                provider_id="rider-1",
                provider_type="rider",
                wallet_balance=Decimal("5000"),
                amount=Decimal("3000"),
            )

    detail = raised.value.detail
    assert "4000" in detail, "the committed float is not named"
    assert "cash orders" in detail
    assert "released when you deliver" in detail
