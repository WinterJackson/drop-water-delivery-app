"""Giving a bottle deposit back, and the four ways that goes wrong.

A deposit the platform cannot return is not a deposit, it is a price. Before
this the only path back was an administrator opening the console under
`finance.adjust` — a grant no preset but super admin holds — so the liability
only ever grew, and nothing ever checked that it was right.

Four properties are tested here, and each of them is a way real money leaks:

* **One tap is not evidence.** Two counts, and they must agree. A timeout
  resolves only in favour of the side that put a physical asset at risk.
* **A returned deposit buys water, not cash.** Otherwise the deposit is a
  money-transfer service — pay KSH 300 by M-Pesa, hand the bottle back, take
  KSH 300 out to a different phone — and with the welcome discount against the
  deposit that round trip cleared a profit.
* **Every return path leaves the same record.** The reconciliation subtracts
  what was given back from what was taken. A path that returns money without
  writing a row makes the book report permanent, growing drift that is
  indistinguishable from a real accrual bug.
* **A bottle that leaves a customer arrives somewhere.** The rider is holding
  it, and `bottle_ledger_service` has to say so.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from models.bottle_return_model import BottleReturnRequest, BottleReturnStatus
from models.wallet_transaction_model import TransactionType
from services import customer_bottle_service as deposits
from services import platform_config_service as config
from services.wallet_service import _rebalance_restricted_credit

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings — every "must not appear" assertion needs it,
    because the note explaining a removal has to name what was removed."""
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


def _customer(*, bottles=3, deposit="900.00", wallet="0.00", commercial=False):
    return SimpleNamespace(
        id=uuid4(),
        clerk_id="customer_clerk",
        bottles_held=bottles,
        bottle_deposit_balance=Decimal(deposit),
        wallet_balance=Decimal(wallet),
        non_withdrawable_balance=Decimal("0.00"),
        is_commercial=commercial,
        deposit_last_activity_at=None,
        deposit_dormancy_warned_at=None,
        push_token=None,
    )


def _session(user=None, request=None):
    """A session that hands back whichever row the code under test locks."""
    session = AsyncMock()
    session.add = MagicMock()

    def _execute(statement, *args, **kwargs):
        result = MagicMock()
        text = str(statement)
        row = request if 'Bottle_Return_Requests' in text else user
        result.scalars.return_value.first.return_value = row
        result.scalar.return_value = None
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _request(**overrides):
    row = BottleReturnRequest(
        id=uuid4(),
        customer_id=overrides.pop("customer_id", uuid4()),
        rider_id=overrides.pop("rider_id", None),
        vendor_id=overrides.pop("vendor_id", None),
        bottles_requested=overrides.pop("bottles_requested", 2),
        status=overrides.pop("status", BottleReturnStatus.ASSIGNED.value),
        origin="collection",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# ── Two counts, and what happens when they disagree ───────────────────────


@pytest.mark.asyncio
async def test_one_confirmation_alone_settles_nothing():
    """The rider says four; nobody has paid anybody yet."""
    user = _customer()
    row = _request(customer_id=user.id)
    session = _session(user, row)

    result = await deposits.confirm_handover(
        session, request_id=row.id, bottles=2, by="rider",
        actor_id=uuid4(), vendor_id=uuid4(),
    )

    assert result["status"] == BottleReturnStatus.AWAITING_COUNTERPARTY.value
    assert result["waiting_on"] == "customer"
    assert user.wallet_balance == Decimal("0.00")
    assert user.bottles_held == 3


@pytest.mark.asyncio
async def test_two_counts_that_disagree_become_a_dispute_and_pay_nobody():
    """Never split the difference.

    A rider who learns that claiming one fewer bottle each time costs nobody
    anything will do exactly that, and it would take months to notice.
    """
    user = _customer()
    rider = uuid4()
    row = _request(customer_id=user.id, rider_id=rider)
    session = _session(user, row)

    await deposits.confirm_handover(
        session, request_id=row.id, bottles=1, by="rider", actor_id=rider, vendor_id=uuid4()
    )
    result = await deposits.confirm_handover(
        session, request_id=row.id, bottles=3, by="customer", actor_id=user.id
    )

    assert result["status"] == BottleReturnStatus.DISPUTED.value
    assert "1" in row.resolution_note and "3" in row.resolution_note
    assert user.wallet_balance == Decimal("0.00"), "money moved on a disputed collection"
    assert user.bottles_held == 3


@pytest.mark.asyncio
async def test_a_closed_collection_cannot_be_confirmed_again():
    """The rider app retries from an offline queue. A repeat must not pay twice."""
    from fastapi import HTTPException

    user = _customer()
    row = _request(customer_id=user.id, status=BottleReturnStatus.SETTLED.value)
    session = _session(user, row)

    with pytest.raises(HTTPException) as exc:
        await deposits.confirm_handover(
            session, request_id=row.id, bottles=2, by="rider", actor_id=uuid4()
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_customer_cannot_confirm_somebody_elses_collection():
    from fastapi import HTTPException

    user = _customer()
    row = _request(customer_id=uuid4())   # belongs to somebody else
    session = _session(user, row)

    with pytest.raises(HTTPException) as exc:
        await deposits.confirm_handover(
            session, request_id=row.id, bottles=2, by="customer", actor_id=user.id
        )
    assert exc.value.status_code == 403


def test_only_the_rider_side_can_ever_auto_settle():
    """The asymmetry, asserted against the source.

    A timer that pays out a customer's unilateral claim is a timer that pays
    anybody willing to wait for it. `escalate_one_sided_customer_claims` must
    stay an escalation — if it ever learns to call `settle_return`, the two
    confirmations have stopped meaning anything.
    """
    source = _code_only(BACKEND / "services" / "customer_bottle_service.py")
    body = source.split("async def escalate_one_sided_customer_claims")[1].split("async def ")[0]

    assert "settle_return" not in body, (
        "the customer-only sweep now settles; a unilateral claim must go to a human"
    )
    assert "DISPUTED" in body or "disputed" in body

    rider_body = source.split("async def settle_one_sided_confirmations")[1].split("async def ")[0]
    assert "settle_return" in rider_body


# ── The credit buys water, not cash ───────────────────────────────────────


def test_a_returned_deposit_is_not_withdrawable_by_default():
    """Switched on, the deposit becomes a money-transfer service."""
    assert config.DEFAULTS["deposit_refund_is_withdrawable"] is False


def test_spending_consumes_the_restricted_part_first():
    """Otherwise buying water eats the free money and leaves the restriction
    intact — the customer's *withdrawable* balance falling because they bought
    water, which is precisely backwards."""
    user = SimpleNamespace(
        wallet_balance=Decimal("500"), non_withdrawable_balance=Decimal("300")
    )

    user.wallet_balance -= Decimal("100")
    _rebalance_restricted_credit(
        user, delta=Decimal("-100"), transaction_type=TransactionType.order_payment
    )

    assert user.wallet_balance == Decimal("400")
    assert user.non_withdrawable_balance == Decimal("200")
    # Withdrawable is unchanged: the water was paid for out of restricted money.
    assert user.wallet_balance - user.non_withdrawable_balance == Decimal("200")


def test_a_withdrawal_never_releases_the_restriction():
    """`assert_withdrawable` has already limited the amount to the unrestricted
    part. Treating a withdrawal as a spend would hand back the cash-out path a
    shilling at a time."""
    user = SimpleNamespace(
        wallet_balance=Decimal("500"), non_withdrawable_balance=Decimal("300")
    )

    # 200 was the entire withdrawable part, so the whole remaining balance is
    # restricted afterwards. Nothing was released.
    user.wallet_balance -= Decimal("200")
    _rebalance_restricted_credit(
        user, delta=Decimal("-200"), transaction_type=TransactionType.withdrawal
    )

    assert user.wallet_balance == Decimal("300")
    assert user.non_withdrawable_balance == Decimal("300"), (
        "a withdrawal released part of the restriction"
    )
    assert user.wallet_balance - user.non_withdrawable_balance == Decimal("0")


def test_the_restriction_never_exceeds_the_balance_holding_it():
    user = SimpleNamespace(
        wallet_balance=Decimal("50"), non_withdrawable_balance=Decimal("300")
    )
    _rebalance_restricted_credit(
        user, delta=Decimal("1"), transaction_type=TransactionType.top_up
    )
    assert user.non_withdrawable_balance == Decimal("50")


@pytest.mark.asyncio
async def test_a_customers_withdrawable_balance_excludes_returned_deposits():
    from services import settlement_service

    session = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = Decimal("600")
    session.execute = AsyncMock(return_value=result)

    available = await settlement_service.available_for_payout(
        session, provider_id=uuid4(), provider_type="customer", wallet_balance=Decimal("600")
    )
    assert available == Decimal("0.00")


# ── Every path leaves the same record ─────────────────────────────────────


def test_every_return_path_goes_through_one_implementation():
    """The console, the rider collection and the dormancy sweep must agree to
    the shilling on what a bottle is worth back — and each must leave a row the
    reconciliation can subtract."""
    service = _code_only(BACKEND / "services" / "customer_bottle_service.py")
    job = _code_only(BACKEND / "jobs" / "deposit_maintenance.py")

    # The console path and the collection path both delegate.
    assert service.count("_return_bottles(") >= 3
    # The dormancy sweep does too, rather than moving the balance itself.
    assert "_return_bottles(" in job
    assert "origin='dormancy'" in job or 'origin="dormancy"' in job


def test_the_reconciliation_subtracts_returns_from_a_record_not_from_prose():
    """Matching on a wallet description would break the first time somebody
    rewords a message, and the drift would look like an accrual bug."""
    job = _code_only(BACKEND / "jobs" / "deposit_maintenance.py")

    assert "BottleReturnRequest.amount_refunded" in job
    assert "description" not in job.split("async def reconcile_deposit_book")[1].split("async def ")[0]


def test_the_ledger_records_who_is_holding_a_returned_bottle():
    """A bottle that leaves the customer's count and appears in no other count
    has left the platform's books while still physically existing."""
    service = _code_only(BACKEND / "services" / "customer_bottle_service.py")
    settle = service.split("async def settle_return")[1].split("async def ")[0]

    assert "_record_rider_holding" in settle
    assert "DEPOSIT_RETURN" in service


# ── The ceiling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_order_over_the_bottle_ceiling_is_refused():
    """Unlimited bottles against a deposit is unlimited liability, and an
    unlimited-size target for anyone who works out that the deposit is the
    cheapest way to buy a twenty-litre bottle at cost."""
    from fastapi import HTTPException

    user = _customer(bottles=5)
    session = AsyncMock()

    with config.temporarily({**config.effective(), "max_bottles_held_household": 6}):
        await deposits.assert_can_hold(session, user=user, additional=1)   # 6, exactly at
        with pytest.raises(HTTPException) as exc:
            await deposits.assert_can_hold(session, user=user, additional=2)

    assert exc.value.status_code == 400
    # The refusal has to name the limit and the way out, or it is a ticket.
    assert "6" in exc.value.detail and "return" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_commercial_account_gets_the_commercial_ceiling():
    """An office legitimately holds more than a household, and the ceiling that
    protects the platform would otherwise refuse them at four."""
    session = AsyncMock()

    with config.temporarily({
        **config.effective(),
        "max_bottles_held_household": 6,
        "max_bottles_held_commercial": 30,
    }):
        assert await deposits.bottle_ceiling(session, _customer(commercial=False)) == 6
        assert await deposits.bottle_ceiling(session, _customer(commercial=True)) == 30


@pytest.mark.asyncio
async def test_the_ceiling_is_checked_before_the_customer_pays():
    """At quote time, not at `create_order`. Refusing after M-Pesa has taken the
    money is a refund, an apology and a support ticket."""
    pricer = _code_only(BACKEND / "services" / "pricing_service.py")

    assert "assert_can_hold" in pricer


# ── Dormancy is a conversion, never a forfeiture ──────────────────────────


def test_dormancy_gives_the_money_back_as_credit_rather_than_keeping_it():
    """The customer keeps every shilling as wallet credit. What the platform
    recovers is the bottle, which after eighteen months is not coming back."""
    job = _code_only(BACKEND / "jobs" / "deposit_maintenance.py")
    body = job.split("async def warn_and_convert_dormant_deposits")[1]

    assert "_return_bottles(" in body, "the conversion no longer credits the customer"
    assert "deposit_dormancy_warned_at != None" in body or "deposit_dormancy_warned_at is not None" in body, (
        "an account is being converted without a warning having been sent"
    )


def test_dormancy_is_measured_from_the_deposit_not_from_the_last_order():
    """Someone who orders every week on `exchange` never touches their deposit.
    Converting it while they are an active customer would be indefensible."""
    job = _code_only(BACKEND / "jobs" / "deposit_maintenance.py")
    body = job.split("async def warn_and_convert_dormant_deposits")[1]

    assert "deposit_last_activity_at" in body
    assert "last_order_date" not in body


def test_a_deposit_movement_resets_the_dormancy_clock():
    """`_apply` is the only writer of the deposit position, so it is the only
    place the clock can be stamped without somebody forgetting."""
    user = _customer()
    deposits._apply(user, amount=Decimal("300"), bottles=1)

    assert user.deposit_last_activity_at is not None
    assert user.deposit_dormancy_warned_at is None
    assert (
        datetime.now(timezone.utc) - user.deposit_last_activity_at
    ) < timedelta(seconds=5)


# ── The settings the console owns ─────────────────────────────────────────


def test_the_deposit_controls_are_settings_not_constants():
    for key in (
        "max_bottles_held_household",
        "max_bottles_held_commercial",
        "deposit_dormant_after_days",
        "deposit_dormancy_warning_days",
        "deposit_return_window_hours",
        "deposit_return_auto_settle_minutes",
        "deposit_refund_is_withdrawable",
        "deposit_reconciliation_tolerance",
    ):
        assert key in config.SPEC_BY_KEY, f"{key} is not editable from the console"


def test_a_rider_wallet_is_untouched_by_the_restriction_logic():
    """Riders and vendors have committed cash float, not restricted credit, and
    `settlement_service` owns that. Keying on the attribute existing rather than
    on who the account belongs to is how the two would come to overlap."""
    rider = SimpleNamespace(
        wallet_balance=Decimal("400"), non_withdrawable_balance=Decimal("300")
    )
    _rebalance_restricted_credit(
        rider, delta=Decimal("-100"),
        transaction_type=TransactionType.order_payment, user_type="rider",
    )
    assert rider.non_withdrawable_balance == Decimal("300"), (
        "a rider's balance was treated as restricted customer credit"
    )


def test_an_unreadable_restriction_is_left_alone_rather_than_zeroed():
    """The one direction this must never fail in.

    Resetting an unparseable value to zero would *release* a restriction — the
    cash-out path this exists to close, opened by a bad read. Leaving it costs
    nothing.
    """
    broken = SimpleNamespace(
        wallet_balance=Decimal("400"), non_withdrawable_balance=object()
    )
    before = broken.non_withdrawable_balance

    _rebalance_restricted_credit(
        broken, delta=Decimal("-100"),
        transaction_type=TransactionType.order_payment, user_type="customer",
    )

    assert broken.non_withdrawable_balance is before


# ── The gaps found reviewing what Phase 2 actually shipped ────────────────


def test_a_collection_requires_an_approved_rider():
    """A collection moves goods **and** money — the rider takes physical bottles
    and their confirmation releases a customer's deposit.

    `get_current_rider`'s own docstring draws this line: it admits a rider whose
    KYC is pending or rejected, and "anything that moves an order, goods or
    money must use `get_verified_rider`". These endpoints shipped on the wrong
    one, which is the same defect KYC enforcement exists to prevent arriving
    through a new door.
    """
    source = _code_only(BACKEND / "routes" / "bottle_return_routes.py")

    assert "get_verified_rider" in source
    assert "get_current_rider" not in source, (
        "an unverified rider can trigger a deposit refund again"
    )


@pytest.mark.asyncio
async def test_the_ledger_capacity_comes_from_what_the_customer_paid_for():
    """It was a hardcoded 20.

    `bottle_ledger_service` keeps a counter per capacity and values it at that
    capacity's deposit, so a 10 L return recorded as 20 L overstates the float
    owed to that store and understates the 10 L pool by the same bottles.
    """
    session = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = 10
    session.execute = AsyncMock(return_value=result)

    capacity, basis = await deposits._returned_capacity(session, uuid4())

    assert capacity == 10
    assert "last deposit-bearing order" in basis


@pytest.mark.asyncio
async def test_an_inferred_capacity_says_that_it_is_inferred():
    """A figure nobody can tell was assumed is one somebody will later treat as
    measured."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = None       # no priced order on record
    session.execute = AsyncMock(return_value=result)

    with config.temporarily({
        **config.effective(),
        "bottle_deposit_by_capacity": {"20": 300.0, "10": 150.0},
    }):
        capacity, basis = await deposits._returned_capacity(session, uuid4())

    # The largest priced size: the conservative direction, since it never
    # understates what a store is owed.
    assert capacity == 20
    assert "assumed" in basis


def test_a_bad_store_id_costs_a_ledger_row_and_never_the_refund():
    """`bottle_ledger_entries.vendor_id` is a real foreign key, and the entry is
    written *after* the wallet credit. An id that does not resolve would raise at
    flush and roll the whole transaction back — so a client sending a bad store
    would stop a customer being paid a deposit they are owed."""
    source = _code_only(BACKEND / "services" / "customer_bottle_service.py")
    body = source.split("async def _record_rider_holding")[1].split("async def ")[0]

    assert "select(Vendor.id)" in body, (
        "the destination store is no longer checked before the ledger row is "
        "written; a bad id now rolls back the customer's refund"
    )


def test_the_customer_is_told_when_a_collection_does_not_settle():
    """Somebody is waiting on money. Silence reads as the platform keeping it.

    Every terminal state a customer can reach without being paid — disputed,
    escalated, expired — has to say so, through the platform's own two push
    paths rather than a bare task.
    """
    source = _code_only(BACKEND / "services" / "customer_bottle_service.py")

    for function in (
        "confirm_handover",
        "escalate_one_sided_customer_claims",
        "expire_stale_requests",
        "settle_one_sided_confirmations",
    ):
        body = source.split(f"async def {function}")[1].split("async def ")[0]
        assert "_tell_customer" in body, f"{function} changes a collection silently"

    # And through `queue_push`, so a rollback discards the message with the
    # change it was announcing.
    assert "queue_push" in source
    assert "create_task" not in source


# ── A control nothing can reach is not a control ──────────────────────────
#
# Both of these shipped enforced, validated and unreachable. The ceiling
# refused every account at the household figure because nothing could set the
# column that chooses the other one; the dispute queue routed collections to
# "a human" who had no screen to look at. A setting the console cannot move is
# a wall, and a queue nobody can open is a silence.


def test_the_commercial_ceiling_can_actually_be_switched_on():
    """`max_bottles_held_commercial` was validated, bounded, documented — and
    unreachable, because `is_commercial` had no writer anywhere on the platform.
    Every office ordering water was refused at the household limit."""
    routes = _code_only(BACKEND / "routes" / "admin_people_routes.py")

    assert "account-kind" in routes, "nothing can set a customer's account kind"
    assert "customer.is_commercial = body.is_commercial" in routes
    # Not a read permission: raising the ceiling raises the platform's own
    # exposure to one account.
    kind = routes.split("async def set_account_kind")[1].split("async def ")[0]
    assert "PERM_CUSTOMERS_READ" not in routes.split("async def set_account_kind")[0][-400:]
    assert "record_audit" in kind, "the change is not audited"


def test_the_balances_endpoint_states_which_ceiling_applies():
    """An office refused at six bottles needs somebody to see *why* before they
    can fix it."""
    routes = _code_only(BACKEND / "routes" / "admin_people_routes.py")
    body = routes.split("async def customer_balances")[1].split("async def ")[0]

    assert "is_commercial" in body
    assert "bottle_limit" in body
    # And the part of the balance that cannot be withdrawn, or "the balance says
    # 900 and they can withdraw 0" is a ticket nobody in the console can answer.
    assert "wallet_not_withdrawable" in body


def test_a_disputed_collection_has_somewhere_to_be_decided():
    """The backend routes disputes to a human deliberately — splitting the
    difference teaches riders that understating a count is free. That only works
    if the human has a screen."""
    admin = BACKEND.parent / "drop-admin"
    if not admin.exists():
        pytest.skip("drop-admin/ is not present")

    page = (admin / "app" / "(dashboard)" / "operations" / "bottles" / "page.tsx").read_text()
    component = (
        admin / "app" / "(dashboard)" / "operations" / "bottles" / "DisputedCollections.tsx"
    ).read_text()
    actions = (
        admin / "app" / "(dashboard)" / "operations" / "bottles" / "actions.ts"
    ).read_text()

    # `<DisputedCollections`, not the bare name — the import line contains the
    # name whether or not anything renders it, and a test that passes on an
    # unrendered component is the same silence it exists to catch.
    assert "<DisputedCollections" in page, "the dispute queue is imported but never rendered"
    assert "status=disputed" in page
    assert "resolveBottleReturn" in component
    assert "/resolve" in actions
    # Both counts have to be on screen; deciding without them is guessing.
    assert "bottles_stated_by_customer" in component
    assert "bottles_stated_by_rider" in component
