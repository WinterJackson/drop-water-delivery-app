"""Indexes for the three hottest unindexed filters on Orders.

`Orders` is the table that grows fastest and never shrinks, and three of the
queries run most often against it had no index that could serve them.

1. **`order_status` alone.** It is the most-filtered column on the table and
   every existing index that mentions it has something else leading —
   `(customer_id, order_status)` is only usable when the customer is known. The
   re-dispatch sweep asks `WHERE order_status = 'unassigned'` with no other
   predicate, and the auto-cancel job asks
   `WHERE order_status IN ('pending','unassigned') AND now() - created_at > …`
   ordered by `created_at`. Both were sequential scans of the whole order
   history, on a schedule, forever.

2. **A rider's open cash orders.** `settlement_service.committed_cash_float`
   runs on every wallet summary, on every cash-order acceptance check, and in
   the release sweep — seven call sites. It filters
   `deliverer_id = … AND payment_method = 'cash' AND order_status IN (…)`, and
   only `deliverer_id` was indexed, so it read every order that rider has ever
   delivered to answer a question about the handful still open. Partial on
   `payment_method = 'cash'`, which is the minority of orders and the only
   subset this query ever wants; `updated_at` rides along as the third column so
   the ten-minute release sweep's `updated_at < cutoff` is answered from the
   index too.

3. **A vendor's open cash orders.** The same query, from the store's side, on
   the vendor wallet summary.

Deliberately three indexes and not eight. Every one of them is write cost on
the busiest table on the platform, so each is here because a named query on a
named screen or schedule could not be answered without it.

Created without CONCURRENTLY on purpose: Alembic runs a migration in a
transaction, and `CREATE INDEX CONCURRENTLY` cannot run inside one. On a table
this size the lock is momentary. If this platform ever reaches the point where
that is not true, the index should be built by hand with CONCURRENTLY and this
migration stamped rather than run.

Revision ID: d4a8f2c61b93
Revises: f7e3b91c8d24
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a8f2c61b93"
down_revision: Union[str, Sequence[str], None] = "f7e3b91c8d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. The dispatch sweep and the auto-cancel job.
    op.create_index(
        "ix_orders_status_created_at",
        "Orders",
        ["order_status", "created_at"],
        unique=False,
    )

    # 2. A rider's live cash obligation.
    op.create_index(
        "ix_orders_cash_float_rider",
        "Orders",
        ["deliverer_id", "order_status", "updated_at"],
        unique=False,
        postgresql_where=sa.text("payment_method = 'cash'"),
    )

    # 3. The same, from the store's side.
    op.create_index(
        "ix_orders_cash_float_vendor",
        "Orders",
        ["vendor_id", "order_status", "updated_at"],
        unique=False,
        postgresql_where=sa.text("payment_method = 'cash'"),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_cash_float_vendor", table_name="Orders")
    op.drop_index("ix_orders_cash_float_rider", table_name="Orders")
    op.drop_index("ix_orders_status_created_at", table_name="Orders")
