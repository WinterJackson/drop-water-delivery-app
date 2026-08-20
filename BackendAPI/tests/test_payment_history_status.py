"""A cash order's payment history row tells the truth about the money.

`GET /api/payments/history` is one query over two kinds of event: an M-Pesa
payment, which has a `payments` row of its own, and a cash-on-delivery order,
which never produces one. The M-Pesa half reads `Payment.status` — the
authority for that row. The cash half used to re-derive its status from
`order_status`:

    case((Order.order_status == "delivered", "paid"), else_="pending")

Two separate defects in one expression, both of them on the screen a customer
opens to check what they have been charged:

* **A cancelled or rejected cash order read "pending" for ever.** The order is
  terminal — nothing was collected and nothing ever will be — but the row
  rendered with the pending icon and the pending colour, an outstanding charge
  against an order that died. Nothing will ever move it, because nothing ever
  moves a terminal order.

* **A refunded cash order read "pending" too**, or "paid" if it had been
  delivered first. `Order.payment_status` was sitting on the same row saying
  `refunded`, and the customer who is owed money was shown a charge in flight.

`Order.payment_status` is the authority, and it *is* maintained for cash:
`deliverer_service` writes "paid" when the rider settles at the door, and the
reversal paths write `refund_pending` / `refund_processing` / `refunded` /
`refund_failed`. The one thing it cannot say on its own is "this order ended
before anybody collected" — there it holds the `pending` default it was created
with, which is a statement about a charge never being *attempted* rather than a
charge being *outstanding*.

These assert the **compiled SQL**, not the source text. An earlier guard
elsewhere in this suite pinned the mechanism it happened to be written with and
so failed on the fix exactly as loudly as on a regression.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy.dialects import postgresql

from models.order_model import Order
from routes.payment_routes import _TERMINAL_UNCOLLECTED, cash_payment_status


def _sql() -> str:
    return str(
        cash_payment_status().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_the_cash_status_reads_the_payment_status_column():
    """The authority for what was collected, not a proxy for it."""
    sql = _sql()
    assert "payment_status" in sql, (
        "the cash half of the payment history no longer reads "
        f"Orders.payment_status:\n{sql}"
    )


def test_the_cash_status_is_not_re_derived_from_delivery():
    """`order_status = 'delivered'` must not be what decides "paid".

    That is the defect: delivery is when a rider *collects*, but whether the
    money is still with the platform afterwards is `payment_status`'s answer
    and only its answer. A delivered-then-refunded cash order is the case the
    two disagree on.
    """
    sql = _sql()
    assert not re.search(r"order_status\s*=\s*'delivered'", sql), (
        "the cash half decides 'paid' from the order having been delivered. A "
        "delivered order that was later refunded still reads 'paid' this way, "
        f"and the refund never reaches the customer's screen:\n{sql}"
    )
    assert "'paid'" not in sql, (
        "the cash half writes a literal 'paid'. It should be passing "
        f"Orders.payment_status through instead:\n{sql}"
    )


@pytest.mark.parametrize("status", _TERMINAL_UNCOLLECTED)
def test_an_order_that_ended_uncollected_is_not_called_pending(status):
    """Terminal and never charged is its own answer, and it is not "pending"."""
    sql = _sql()
    assert f"'{status}'" in sql, (
        f"a cash order in '{status}' is terminal and was never collected, but "
        f"the status expression does not mention it — so it falls through to "
        f"the 'pending' default and shows an outstanding charge for ever:\n{sql}"
    )
    assert "'not_charged'" in sql, (
        "nothing distinguishes an order that ended uncollected from one whose "
        f"payment is genuinely still in flight:\n{sql}"
    )


def test_the_terminal_statuses_are_real_order_statuses():
    """Guards the premise, so the table above cannot rot into a no-op.

    A typo here fails nothing — the `IN` simply never matches and every
    cancelled order quietly goes back to reading "pending".
    """
    from services.order_service import OrderStatusEnum

    known = {s.value for s in OrderStatusEnum}
    unknown = [s for s in _TERMINAL_UNCOLLECTED if s not in known]
    assert not unknown, f"not order statuses this platform uses: {unknown}"


def test_neither_column_is_a_postgres_enum():
    """Why this expression may compare and coalesce plain strings at all.

    `COALESCE(<enum>, <varchar>)` is a `DatatypeMismatchError` at execution
    time, and nothing in this suite touches a real database. Both columns are
    `String` today; if either becomes an enum, this expression needs revisiting
    rather than silently 500ing every customer's payment history.
    """
    for column in (Order.payment_status, Order.order_status):
        assert not isinstance(column.type, postgresql.ENUM), (
            f"{column.key} became a Postgres enum — `cash_payment_status()` "
            "mixes it with string literals and will fail at execution."
        )
