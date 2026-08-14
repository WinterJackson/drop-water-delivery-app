"""Materialise the acquisition date the growth report was deriving live.

`admin_growth_service` grouped the whole `Orders` table on every page load:

    SELECT customer_id, MIN(date_trunc('month', created_at))
    FROM "Orders" WHERE order_status = 'delivered' GROUP BY customer_id

The unbounded window is deliberate and is preserved exactly — a `MIN()` computed
inside the reporting window would re-acquire a two-year customer into this
month's cohort. What is not deliberate is recomputing it per request: this is one
of the few queries whose cost grows without bound and which no index can help,
because it must read every delivered order that has ever existed. At seven
million orders that is tens of seconds, holding a connection, on a screen people
refresh.

After this the report joins one row per customer.

## The backfill is the same query

Written once, in SQL, and it *is* the definition — so the table starts life
exactly equal to what the report used to compute. `services/customer_cohort_service.reconcile`
runs the identical derivation on a schedule and repairs any drift, which is what
makes the fast path safe to depend on.

Note `MIN(created_at)` and not `MIN(date_trunc(...))`: truncating before the
minimum picks an arbitrary order within the earliest month, and the exact
timestamp is what lets a later, earlier-placed delivery correct the row.

Revision ID: b8e1d47f3a92
Revises: a7f4e29b81c6
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8e1d47f3a92"
down_revision: Union[str, Sequence[str], None] = "a7f4e29b81c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "Customer_First_Delivery",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_order_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cohort_month", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["Users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("customer_id"),
    )
    op.create_index(
        "ix_customer_first_delivery_month", "Customer_First_Delivery", ["cohort_month"]
    )

    # The backfill: the definition, applied to every customer already acquired.
    op.execute(
        """
        INSERT INTO "Customer_First_Delivery" (customer_id, first_order_at, cohort_month)
        SELECT
            o.customer_id,
            MIN(o.created_at),
            date_trunc('month', MIN(o.created_at))
        FROM "Orders" o
        WHERE o.order_status = 'delivered'
          AND o.customer_id IS NOT NULL
        GROUP BY o.customer_id
        ON CONFLICT (customer_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_customer_first_delivery_month", table_name="Customer_First_Delivery")
    op.drop_table("Customer_First_Delivery")
