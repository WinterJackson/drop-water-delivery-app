"""Enforce payment idempotency at the database level

Application-level guards keep duplicate payment callbacks from re-dispatching an
order, but the database should be the backstop: a retried STK push or a replayed
callback must not be able to create a second order or a second payment row for
the same M-Pesa transaction, no matter what the application does.

Adds:
  * partial unique index on Orders.checkout_request_ID (NULLs allowed, so
    cash-on-delivery orders are unaffected)
  * partial unique index on payments.mpesa_receipt
  * index on Orders.payment_status to keep the refund sweep cheap

Revision ID: b7c1e9f04a21
Revises: fd28f730de67
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c1e9f04a21"
down_revision = "fd28f730de67"
branch_labels = None
depends_on = None


def _assert_no_duplicates(conn, table: str, column: str) -> None:
    """Refuse to create the index while conflicting rows exist.

    Before this migration the application could write duplicates, so an existing
    database may contain them. Failing loudly with the offending values is far
    safer than deleting order or payment rows automatically — that is a decision
    for an operator, not a migration.
    """
    result = conn.execute(
        sa.text(
            f'SELECT "{column}", COUNT(*) AS n FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL GROUP BY "{column}" HAVING COUNT(*) > 1 LIMIT 20'
        )
    )
    duplicates = result.fetchall()
    if duplicates:
        listed = ", ".join(f"{row[0]} (x{row[1]})" for row in duplicates)
        raise RuntimeError(
            f'Cannot add a unique index on "{table}"."{column}": duplicate values exist — {listed}. '
            "These are the double-order/double-payment rows the old code could create. "
            "Reconcile them manually (keep the settled row, cancel the rest), then re-run this migration."
        )


def upgrade() -> None:
    conn = op.get_bind()

    _assert_no_duplicates(conn, "Orders", "checkout_request_ID")
    _assert_no_duplicates(conn, "payments", "mpesa_receipt")

    # Partial unique indexes: one order and one payment per M-Pesa transaction,
    # while still allowing many rows with a NULL reference (cash orders, payments
    # whose receipt has not arrived yet).
    op.create_index(
        "uq_orders_checkout_request_id",
        "Orders",
        ["checkout_request_ID"],
        unique=True,
        postgresql_where=sa.text('"checkout_request_ID" IS NOT NULL'),
    )
    op.create_index(
        "uq_payments_mpesa_receipt",
        "payments",
        ["mpesa_receipt"],
        unique=True,
        postgresql_where=sa.text("mpesa_receipt IS NOT NULL"),
    )

    # The refund sweep and the payment-pending banner both filter on this.
    op.create_index("idx_orders_payment_status", "Orders", ["payment_status"])

    # Supports the batched `is_rated` lookup on the orders list, and the average
    # rating recalculation after each review.
    op.create_index("idx_reviews_order_id", "reviews", ["order_id"])
    op.create_index("idx_reviews_target", "reviews", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("idx_reviews_target", table_name="reviews")
    op.drop_index("idx_reviews_order_id", table_name="reviews")
    op.drop_index("idx_orders_payment_status", table_name="Orders")
    op.drop_index("uq_payments_mpesa_receipt", table_name="payments")
    op.drop_index("uq_orders_checkout_request_id", table_name="Orders")
