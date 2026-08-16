"""Money leaves the platform exactly as it was debited, off the row it was debited from.

Four defects, all on the outbound side, all invisible from either end:

* **Truncation.** Every Daraja amount field is whole shillings and the code sent
  `int(amount)`. The withdrawal fee is a `Platform_Settings` row an administrator
  may set to 15.50 at any moment; a KSH 1,000 withdrawal then debited 1,000,
  recorded a fee of 15.50 and put **984** on the phone. The missing 50 cents
  appeared in no ledger and was reported to nobody.

* **The wrong balance row.** `WalletTransactions.user_id` is a Clerk id, and one
  identity may own several stores with a `wallet_balance` each. Callbacks arrive
  minutes later and re-resolved the owner by clerk id with an unordered
  `.first()`, so a top-up paid into the second branch credited the first, and a
  failed withdrawal from the second was refunded to the first.

* **A balance moved with no ledger row.** The B2C failure path assigned
  `wallet_balance` directly. The money reappeared with nothing in the history to
  account for it — on the one event a provider is most likely to query.

* **A token minted per call.** Daraja tokens live an hour and Safaricom throttles
  the mint; a throttled mint returned `None`, which went out as the literal
  header `Authorization: Bearer None`.
"""
from __future__ import annotations

import ast
import datetime
import pathlib
import re
from decimal import Decimal

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source with every docstring stripped.

    Mandatory for any "must not appear" assertion: the comment explaining why
    something was removed has to name the thing that was removed. `ast.unparse`
    also normalises double quotes to single, so needles are written that way.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── Whole shillings, or refuse ────────────────────────────────────────────


def test_whole_shillings_refuses_a_fraction_instead_of_truncating():
    """The caller has already decided what to debit. Silently adjusting here is
    what put the debit and the disbursement out of step."""
    from services.payment_service import MpesaError, whole_shillings

    assert whole_shillings(Decimal("984"), label="x") == 984
    assert whole_shillings(984, label="x") == 984

    for bad in (Decimal("984.50"), Decimal("0"), Decimal("-5"), 984.01):
        with pytest.raises(MpesaError):
            whole_shillings(bad, label="x")


def test_no_mpesa_amount_is_built_with_a_bare_int_cast():
    """`int(984.50)` is 984. Every amount field must go through
    `whole_shillings`, which refuses rather than rounds."""
    source = _code_only(BACKEND / "services" / "payment_service.py")

    assert "int(amount)" not in source, (
        "an M-Pesa amount is being truncated; use whole_shillings()"
    )
    assert source.count("whole_shillings(") >= 4, (
        "STK push, B2C and reversal must each quantise their amount"
    )


@pytest.mark.parametrize("fee", ["15", "15.50", "0"])
def test_a_withdrawal_debits_exactly_what_it_disburses_plus_the_fee(fee):
    """The identity that must hold for every fee the console can be set to:

        amount debited == amount disbursed + fee retained

    and the disbursed figure must be a whole number of shillings, because that
    is the only thing M-Pesa can move.
    """
    from decimal import ROUND_DOWN

    amount = Decimal("1000")
    transaction_fee = Decimal(fee)

    disbursement = (amount - transaction_fee).to_integral_value(rounding=ROUND_DOWN)
    retained = amount - disbursement

    assert disbursement == disbursement.to_integral_value()
    assert disbursement + retained == amount
    assert retained >= transaction_fee, "the platform must never disburse more than it debited"


def test_the_withdrawal_path_reconciles_its_own_arithmetic():
    """Guards the source, not a copy of it: the three lines above must actually
    be the ones in `initiate_wallet_withdrawal`."""
    source = _code_only(BACKEND / "services" / "wallet_service.py")

    assert "ROUND_DOWN" in source
    assert "transaction_fee = amount - disbursement_amount" in source, (
        "the fee must be re-derived from the rounded disbursement, or the "
        "difference is money in no ledger"
    )


# ── The right balance row ─────────────────────────────────────────────────


def test_a_wallet_movement_records_which_balance_row_it_came_off():
    from models.wallet_transaction_model import WalletTransaction

    assert hasattr(WalletTransaction, "wallet_owner_id"), (
        "a clerk id cannot identify a balance: one owner, several stores, "
        "one `wallet_balance` each"
    )


def test_the_owner_resolver_prefers_the_recorded_row():
    source = _code_only(BACKEND / "services" / "wallet_service.py")
    assert "async def _locked_wallet_owner" in source

    resolver = source.split("async def _locked_wallet_owner", 1)[1].split("\nasync def ", 1)[0]
    assert "wallet_owner_id" in resolver
    assert "with_for_update()" in resolver, "settling a balance must lock it"
    # The clerk-id fallback is for pre-migration rows and must at least be
    # deterministic — an unordered `.first()` is what caused this.
    assert "order_by" in resolver


@pytest.mark.parametrize(
    "path",
    ["services/wallet_service.py", "routes/payout_routes.py"],
)
def test_no_callback_resolves_a_balance_by_clerk_id_and_takes_the_first_row(path):
    """The specific shape of the defect: `.where(model.clerk_id == …)` followed
    by `.first()` with no ordering, on a path that then moves money."""
    source = _code_only(BACKEND / path)
    offenders = re.findall(
        r"clerk_id == (?:tx|transaction)\.user_id[^\n]*", source
    )
    for line in offenders:
        assert "order_by" in line or "_locked_wallet_owner" in line, (
            f"{path}: a callback is settling against an arbitrary store row: {line}"
        )


# ── Every movement leaves a ledger row ────────────────────────────────────


def test_no_module_assigns_a_wallet_balance_outside_the_two_that_may():
    """`apply_wallet_delta` moves the balance and writes the row in one call.
    Assigning `wallet_balance` anywhere else is how money came back after a
    failed payout with nothing in the history to explain it.

    `wallet_service.apply_wallet_delta` is the implementation. Crediting a
    settled top-up is the other exception, and it is `_credit_topup` — one
    function, called by both settlement paths.

    It moved there from inside `handle_mpesa_topup_callback` when the top-up
    reconciliation was added. A second settlement path was going to have to
    credit a wallet too, and the alternative was a second entry on this list —
    i.e. two implementations of "put this top-up on its balance", which is how
    every defect this file guards against began.

    What counts as a defect is *arithmetic* on the balance — `+=`, or an assigned
    expression. `create_order` assigns the value it read under its own row lock
    back onto the instance and then calls `apply_wallet_delta`; that resync moves
    no money and is not what this guards.
    """
    allowed = {
        ("services/wallet_service.py", "apply_wallet_delta"),
        ("services/wallet_service.py", "_credit_topup"),
    }
    offenders: list[str] = []

    for path in sorted(BACKEND.glob("services/*.py")) + sorted(BACKEND.glob("routes/*.py")):
        rel = f"{path.parent.name}/{path.name}"
        tree = ast.parse(path.read_text())
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if (rel, func.name) in allowed:
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.AugAssign):
                    targets, computes = [node.target], True
                elif isinstance(node, ast.Assign):
                    targets, computes = node.targets, isinstance(node.value, ast.BinOp)
                else:
                    continue
                if not computes:
                    continue
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "wallet_balance":
                        offenders.append(f"{rel}::{func.name} line {node.lineno}")

    assert not offenders, (
        "these move a balance without writing its ledger row — use "
        f"apply_wallet_delta: {offenders}"
    )


def test_the_b2c_failure_path_returns_the_money_through_the_ledger():
    source = _code_only(BACKEND / "routes" / "payout_routes.py")
    reconcile = source.split("async def _reconcile_wallet_transaction", 1)[1].split(
        "\n@callback_router", 1
    )[0]

    assert "apply_wallet_delta" in reconcile, (
        "a refund the provider cannot see in their history is a balance that "
        "changed for no stated reason"
    )
    assert "TransactionType.refund" in reconcile


# ── The Daraja client ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_access_token_is_cached_across_calls():
    """Two round trips per payment, and a throttled mint returning `None` that
    then went on the wire as `Bearer None`."""
    import services.payment_service as ps

    calls = {"n": 0}

    class _Response:
        status_code = 200

        def json(self):
            return {"access_token": "tok-abc", "expires_in": "3599"}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            calls["n"] += 1
            return _Response()

    ps._token_cache["value"] = None
    ps._token_cache["expires_at"] = 0.0

    original = ps.httpx.AsyncClient
    ps.httpx.AsyncClient = _Client
    try:
        import os

        os.environ.setdefault("MPESA_CONSUMER_KEY", "k")
        os.environ.setdefault("MPESA_CONSUMER_SECRET", "s")

        first = await ps.get_access_token()
        second = await ps.get_access_token()
    finally:
        ps.httpx.AsyncClient = original
        ps._token_cache["value"] = None
        ps._token_cache["expires_at"] = 0.0

    assert first == second == "tok-abc"
    assert calls["n"] == 1, f"token was minted {calls['n']} times for two calls"


@pytest.mark.asyncio
async def test_a_token_failure_raises_rather_than_returning_none():
    import services.payment_service as ps

    class _Response:
        status_code = 401

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Response()

    ps._token_cache["value"] = None
    ps._token_cache["expires_at"] = 0.0
    original = ps.httpx.AsyncClient
    ps.httpx.AsyncClient = _Client
    try:
        with pytest.raises(ps.MpesaError):
            await ps.get_access_token()
    finally:
        ps.httpx.AsyncClient = original
        ps._token_cache["value"] = None
        ps._token_cache["expires_at"] = 0.0


@pytest.mark.asyncio
async def test_a_failed_token_does_not_propagate_out_of_the_initiators():
    """The checkout route reads a missing `CheckoutRequestID` as "nothing was
    charged", and the withdrawal path refunds on a falsy `success`. Both only
    hold if a pre-flight failure comes back the same shape as an in-flight one."""
    import services.payment_service as ps

    async def _boom(*a, **kw):
        raise ps.MpesaError("no credentials")

    original = ps.get_access_token
    ps.get_access_token = _boom
    try:
        stk = await ps.initiate_stk_push(
            phone="254712345678",
            amount=100,
            callback_url="https://example.test/api/cart/mpesa/callback?secret=x",
        )
        b2c = await ps.initiate_b2c_payout(phone="254712345678", amount=100, payout_id="x" * 8)
        rev = await ps.initiate_mpesa_reversal(transaction_id="ABC", amount=100)
    finally:
        ps.get_access_token = original

    assert "error" in stk
    assert b2c["success"] is False
    assert rev["success"] is False


def test_the_stk_timestamp_is_east_africa_time():
    """Safaricom validates the timestamp against its own clock, and the password
    is the base64 of shortcode+passkey+timestamp — so both must be generated
    from the same instant *in EAT*. `datetime.now()` is naive local time, which
    in a container is UTC: three hours behind, on every request."""
    from services.payment_service import EAT, generate_password

    _password, timestamp = generate_password()
    expected = datetime.datetime.now(EAT).strftime("%Y%m%d%H")

    assert timestamp[:10] == expected, (
        f"STK timestamp {timestamp} is not EAT (expected to start {expected})"
    )
    assert EAT.utcoffset(None) == datetime.timedelta(hours=3)


def test_no_naive_now_survives_in_the_payment_client():
    source = _code_only(BACKEND / "services" / "payment_service.py")
    assert "datetime.datetime.now()" not in source


# ── Locks and authorisation ───────────────────────────────────────────────


def test_the_payout_advisory_lock_key_is_stable_across_processes():
    """`hash()` on a str is salted per interpreter, so two API replicas computed
    two different keys for one provider and the lock serialised nothing between
    them — the exact case it was added for."""
    source = _code_only(BACKEND / "services" / "payout_service.py")

    assert "crc32" in source
    assert "abs(hash(str(provider_id)))" not in source


def test_confirming_a_payment_is_scoped_to_the_caller():
    """The checkout id names an order, so this is an order-scoped action.
    Authenticating proves who is calling, not that they have anything to do with
    that payment."""
    source = _code_only(BACKEND / "routes" / "cart_routes.py")
    body = source.split("async def payment_confirmation", 1)[1].split("\n@router", 1)[0]

    assert "Order.customer_id == user_obj.id" in body, (
        "any signed-in customer could drive another account's payment transition"
    )


def test_a_delivered_but_unsettled_order_is_reported():
    """An M-Pesa order delivered while its payment never settled pays nobody.
    That is correct — but it used to happen in silence, so the vendor and rider
    simply never saw the money."""
    source = _code_only(BACKEND / "services" / "deliverer_service.py")
    assert "delivered but not settled" in source
