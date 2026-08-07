"""
The deposit a customer pays is a liability, and it has to be returnable.

Before this, `pricing_service` charged a deposit, `calculate_revenue_splits`
folded it into `vendor_net`, and it was never seen again. `Order` had no column
for it, `Users` had no balance, and there was no endpoint, admin action or job
anywhere in the codebase that could return one. A customer who took
`keep_my_bottle`, paid KSH 300 and later handed the bottle back had no way to get
their money, and the platform could not say what it owed in total.

Two counters now move together — the money and the bottle count — and
`customer_bottle_service._apply` is the only thing that writes either, the same
discipline `bottle_ledger_service` applies to the rider side.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services import customer_bottle_service as deposits


class _Product:
    def __init__(self, capacity):
        self.capacity = capacity


class _Item:
    def __init__(self, capacity, quantity):
        self.product = _Product(capacity)
        self.quantity = quantity


def _customer(balance="0", bottles=0):
    return SimpleNamespace(
        id="customer-1",
        clerk_id="user_1",
        bottle_deposit_balance=Decimal(balance),
        bottles_held=bottles,
        wallet_balance=Decimal("0"),
    )


# ── Counting what actually carries a deposit ──────────────────────────────


def test_only_deposit_bearing_capacities_are_counted():
    """A dispenser is not a bottle the customer is holding on deposit.

    Counting it would overstate the platform's liability and let somebody claim
    a refund for an appliance they bought outright.
    """
    items = [_Item(20, 2), _Item(10, 1), _Item(0, 1)]  # the last is an appliance
    assert deposits.bottles_in(items) == 3


def test_an_unpriced_capacity_is_not_counted():
    """A 5 L jerrycan has no configured deposit, so no deposit is owed on it."""
    assert deposits.bottles_in([_Item(5, 4)]) == 0


def test_items_with_no_product_are_skipped_rather_than_crashing():
    """Order items outlive products. Reading one back must not raise."""
    orphan = SimpleNamespace(product=None, quantity=3)
    assert deposits.bottles_in([orphan, _Item(20, 1)]) == 1


# ── Accrual and release ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_deposit_moves_both_counters():
    customer = _customer()
    await deposits.accrue_deposit(
        AsyncMock(), user=customer, amount=Decimal("600"), bottles=2
    )
    assert customer.bottle_deposit_balance == Decimal("600.00")
    assert customer.bottles_held == 2


@pytest.mark.asyncio
async def test_cancelling_the_order_releases_the_deposit():
    """They never received the bottle, so nothing is owed and nothing is held."""
    customer = _customer("600", 2)
    await deposits.release_deposit(
        AsyncMock(), user=customer, amount=Decimal("600"), bottles=2
    )
    assert customer.bottle_deposit_balance == Decimal("0.00")
    assert customer.bottles_held == 0


@pytest.mark.asyncio
async def test_neither_counter_can_go_negative():
    """A negative liability rendered in the customer's app reads as the platform
    claiming they owe it money."""
    customer = _customer("300", 1)
    await deposits.release_deposit(
        AsyncMock(), user=customer, amount=Decimal("900"), bottles=5
    )
    assert customer.bottle_deposit_balance == Decimal("0.00")
    assert customer.bottles_held == 0


@pytest.mark.asyncio
async def test_a_zero_deposit_records_nothing():
    customer = _customer()
    await deposits.accrue_deposit(AsyncMock(), user=customer, amount=Decimal("0"), bottles=0)
    assert customer.bottles_held == 0


# ── Returning it ──────────────────────────────────────────────────────────


def _session_returning(customer):
    """A session whose one query returns this customer.

    `execute` is async but everything it returns is not — an `AsyncMock` makes
    its children async too, so `.scalars()` would hand back a coroutine and the
    chained `.first()` would fail on it. The result has to be a plain `MagicMock`.
    """
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = customer
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_returning_every_bottle_returns_the_whole_balance():
    """No rounding residue stranded on the account.

    A per-bottle average would leave fractions behind on an uneven balance, and
    a customer with 0.01 outstanding and no bottles is a support ticket nobody
    can close.
    """
    customer = _customer("451", 3)
    result = await deposits.refund_deposit(
        _session_returning(customer), customer_id="customer-1", bottles=3,
        actor="ops@drop.co.ke", reason="returned at the depot",
    )

    assert result["amount_refunded"] == "451.00"
    assert customer.bottle_deposit_balance == Decimal("0.00")
    assert customer.bottles_held == 0
    assert customer.wallet_balance == Decimal("451")


@pytest.mark.asyncio
async def test_a_partial_return_is_prorated():
    customer = _customer("600", 2)
    result = await deposits.refund_deposit(
        _session_returning(customer), customer_id="customer-1", bottles=1,
        actor="ops@drop.co.ke", reason="returned one bottle",
    )

    assert result["amount_refunded"] == "300.00"
    assert customer.bottles_held == 1
    assert customer.bottle_deposit_balance == Decimal("300.00")


@pytest.mark.asyncio
async def test_returning_more_than_is_held_is_refused_not_clamped():
    """The bottle ledger learned this the expensive way.

    Its settlement used `max(0, current - received)`, so a client sending 999
    zeroed a real balance and the API reported success. Clamping makes a typo
    indistinguishable from a legitimate return.
    """
    customer = _customer("300", 1)
    with pytest.raises(HTTPException) as raised:
        await deposits.refund_deposit(
            _session_returning(customer), customer_id="customer-1", bottles=5,
            actor="ops@drop.co.ke", reason="typo in the bottle count",
        )

    assert raised.value.status_code == 400
    assert "holds 1" in raised.value.detail
    # And nothing moved.
    assert customer.bottles_held == 1
    assert customer.bottle_deposit_balance == Decimal("300")


@pytest.mark.asyncio
async def test_a_return_of_zero_is_refused():
    with pytest.raises(HTTPException) as raised:
        await deposits.refund_deposit(
            _session_returning(_customer("300", 1)), customer_id="customer-1",
            bottles=0, actor="ops@drop.co.ke", reason="nothing to do",
        )
    assert raised.value.status_code == 400


@pytest.mark.asyncio
async def test_an_unknown_customer_is_a_404_not_a_crash():
    session = _session_returning(None)
    with pytest.raises(HTTPException) as raised:
        await deposits.refund_deposit(
            session, customer_id="nobody", bottles=1,
            actor="ops@drop.co.ke", reason="wrong id pasted",
        )
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_the_refund_writes_a_ledger_row():
    """It goes through `apply_wallet_delta`, so the customer's own Transactions
    screen can explain where the credit came from.

    Asserted by the balance moving *and* the description naming the reason —
    a bare `wallet_balance +=` would satisfy the first and not the second.
    """
    customer = _customer("300", 1)
    session = _session_returning(customer)

    await deposits.refund_deposit(
        session, customer_id="customer-1", bottles=1,
        actor="ops@drop.co.ke", reason="handed in at Ngong depot",
    )

    added = [call.args[0] for call in session.add.call_args_list]
    assert added, "no WalletTransaction was written"
    entry = added[-1]
    assert entry.amount == Decimal("300.00")
    assert "deposit returned" in entry.description.lower()
    assert "Ngong depot" in entry.description


# ── The structural guarantee ──────────────────────────────────────────────


def test_only_one_function_writes_either_counter():
    """`_apply` is the single writer, as `_apply_movement` is for the rider ledger.

    The money and the count are two views of one fact. Writing one without the
    other is how a balance and a bottle count drift apart, and the drift is
    invisible until somebody tries to return a bottle.
    """
    import ast
    import pathlib

    source = pathlib.Path("services/customer_bottle_service.py").read_text()
    tree = ast.parse(source)

    writers = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in ast.walk(node):
            if (
                isinstance(target, ast.Attribute)
                and target.attr in ("bottle_deposit_balance", "bottles_held")
                and isinstance(target.ctx, ast.Store)
            ):
                enclosing = next(
                    fn.name
                    for fn in ast.walk(tree)
                    if isinstance(fn, ast.FunctionDef) and node in ast.walk(fn)
                )
                writers.add(enclosing)

    assert writers == {"_apply"}, (
        f"{sorted(writers)} write the deposit counters directly. Only `_apply` may — "
        "it is what keeps the balance and the bottle count in step."
    )
