"""Returning a deposit: the request, the limits, and the restricted credit.

Four things a refundable deposit needs before it is refundable in fact rather
than in principle.

**`Bottle_Return_Requests`** — the two-sided handover. Until now the only path
back was an administrator typing it into the console under `finance.adjust`, a
grant no preset but super admin holds, so a deposit was in practice a price.

**`Users.non_withdrawable_balance`** — the part of the wallet that buys water
and does not buy a withdrawal. Without it the deposit is a money-transfer
service: pay KSH 300 by M-Pesa, hand the bottle back, withdraw KSH 300 to a
different phone. With the welcome discount it cleared a profit.

**`Users.is_commercial`** — an office holds more bottles than a household, and
the ceiling that stops one account farming deposits would otherwise refuse them
at four.

`origin` on the request records *which* path returned a deposit — a rider
collection, the console, or the dormancy sweep. Every one of them writes a
settled row, and that is what lets the nightly reconciliation be exact rather
than approximately right.

**`Users.deposit_last_activity_at`** — dormancy is measured from the deposit
moving, not from the last order. Someone ordering weekly on `exchange` never
touches their deposit, and converting it while they are an active customer would
be indefensible.

## The backfill is deliberately generous

Every customer holding a deposit gets `deposit_last_activity_at = NOW()`, so
everybody starts the dormancy clock from the day this ships. Backfilling from
`last_order_date` would be more *accurate* and would convert the deposits of
customers already 18 months away on the first nightly run — a feature whose
first act is to take money off dormant accounts, with no warning ever sent,
because the warning latch would also be empty. The warnings are the point. They
have to be able to happen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3a7f21b9e40'
down_revision: Union[str, Sequence[str], None] = 'b2f9c14e7a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A collected bottle does not evaporate — the rider holds it and owes it to
    # a store. The label is the enum member's *name*, matching the three the
    # type already carries.
    op.execute(
        "ALTER TYPE bottle_ledger_entry_type ADD VALUE IF NOT EXISTS 'DEPOSIT_RETURN'"
    )

    op.add_column("Users", sa.Column(
        "is_commercial", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("Users", sa.Column(
        "non_withdrawable_balance", sa.Numeric(10, 2), nullable=False, server_default="0"))
    op.add_column("Users", sa.Column(
        "deposit_last_activity_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("Users", sa.Column(
        "deposit_dormancy_warned_at", sa.TIMESTAMP(timezone=True), nullable=True))

    # See the docstring: everyone's clock starts now, not from their last order.
    op.execute(
        """UPDATE "Users" SET deposit_last_activity_at = NOW()
           WHERE bottle_deposit_balance > 0 OR bottles_held > 0"""
    )

    op.create_table(
        "Bottle_Return_Requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="collection"),
        sa.Column("bottles_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bottles_stated_by_customer", sa.Integer(), nullable=True),
        sa.Column("bottles_stated_by_rider", sa.Integer(), nullable=True),
        sa.Column("bottles_settled", sa.Integer(), nullable=True),
        sa.Column("customer_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rider_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("amount_refunded", sa.Numeric(10, 2), nullable=True),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_bottle_return_customer", "Bottle_Return_Requests",
                    ["customer_id", "created_at"])
    op.create_index("idx_bottle_return_status", "Bottle_Return_Requests",
                    ["status", "created_at"])
    op.create_index("idx_bottle_return_rider", "Bottle_Return_Requests",
                    ["rider_id", "status"])
    op.create_index("ix_bottle_return_expires", "Bottle_Return_Requests", ["expires_at"])
    op.create_index("ix_bottle_return_origin", "Bottle_Return_Requests", ["origin"])

    # The dormancy sweep filters `Users` on this every night. Partial, because
    # the sweep only ever looks at accounts actually holding a deposit — which
    # on this platform is a small minority of the table, and a full index would
    # be mostly nulls maintained on every user write.
    op.execute(
        """CREATE INDEX ix_users_deposit_activity ON "Users" (deposit_last_activity_at)
           WHERE bottle_deposit_balance > 0"""
    )


def downgrade() -> None:
    # `if_exists` on every one. Dropping the table takes its indexes with it
    # anyway, so naming them is for a legible log rather than for correctness —
    # and a downgrade that dies on a missing index leaves the schema
    # half-reverted, which is a worse place to be than either end of the move.
    for index in (
        "ix_bottle_return_origin",
        "ix_bottle_return_expires",
        "idx_bottle_return_rider",
        "idx_bottle_return_status",
        "idx_bottle_return_customer",
    ):
        op.drop_index(index, table_name="Bottle_Return_Requests", if_exists=True)
    op.drop_table("Bottle_Return_Requests")

    op.execute("DROP INDEX IF EXISTS ix_users_deposit_activity")
    op.drop_column("Users", "deposit_dormancy_warned_at")
    op.drop_column("Users", "deposit_last_activity_at")
    op.drop_column("Users", "non_withdrawable_balance")
    op.drop_column("Users", "is_commercial")

    # `DEPOSIT_RETURN` is left on the enum. Postgres cannot drop a label, and
    # recreating the type would mean rewriting every ledger row to do it — a
    # table rewrite to undo something that costs nothing to leave behind.
