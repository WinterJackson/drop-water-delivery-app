"""add bottle_ledger_entries

Append-only audit of empty-bottle movements between riders and vendors. The
running balances stay on VendorRiderRegistry.pending_{10L,20L}_empties; this table
is the evidence behind them.

Also backfills a ledger row for every non-zero existing balance so the sum of the
ledger and the counters agree from the first deploy — otherwise every pre-existing
debt would look like it appeared from nowhere.

Revision ID: c4e2a1f83b76
Revises: b7c1e9f04a21
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e2a1f83b76"
down_revision: Union[str, Sequence[str], None] = "b7c1e9f04a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    entry_type = sa.Enum(
        "DELIVERY_ACCRUAL",
        "VENDOR_RECEIPT",
        "ADJUSTMENT",
        name="bottle_ledger_entry_type",
    )
    entry_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "bottle_ledger_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("rider_id", sa.UUID(), nullable=False),
        sa.Column("vendor_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("capacity_litres", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_type", entry_type, nullable=False),
        sa.Column("actor_clerk_id", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["Deliverers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["Vendors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["Orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "capacity_litres", "entry_type", name="uq_bottle_ledger_order_accrual"
        ),
        sa.CheckConstraint("quantity <> 0", name="ck_bottle_ledger_nonzero"),
        sa.CheckConstraint("capacity_litres > 0", name="ck_bottle_ledger_capacity"),
    )
    op.create_index("ix_bottle_ledger_entries_id", "bottle_ledger_entries", ["id"])
    op.create_index("ix_bottle_ledger_entries_rider_id", "bottle_ledger_entries", ["rider_id"])
    op.create_index("ix_bottle_ledger_entries_vendor_id", "bottle_ledger_entries", ["vendor_id"])
    op.create_index("ix_bottle_ledger_entries_order_id", "bottle_ledger_entries", ["order_id"])
    op.create_index("ix_bottle_ledger_entries_entry_type", "bottle_ledger_entries", ["entry_type"])
    op.create_index(
        "idx_bottle_ledger_rider_vendor", "bottle_ledger_entries", ["rider_id", "vendor_id"]
    )
    op.create_index(
        "idx_bottle_ledger_vendor_created", "bottle_ledger_entries", ["vendor_id", "created_at"]
    )
    op.create_index(
        "idx_bottle_ledger_rider_created", "bottle_ledger_entries", ["rider_id", "created_at"]
    )

    # Backfill: one opening-balance adjustment per non-zero existing counter, so
    # SUM(ledger) == counter holds for every pair from day one.
    for column, capacity in (("pending_10L_empties", 10), ("pending_20L_empties", 20)):
        op.execute(
            sa.text(
                f"""
                INSERT INTO bottle_ledger_entries
                    (id, rider_id, vendor_id, order_id, capacity_litres, quantity,
                     entry_type, actor_clerk_id, note, created_at, updated_at)
                SELECT
                    gen_random_uuid(), r.rider_id, r.vendor_id, NULL, {capacity},
                    r."{column}", 'ADJUSTMENT', NULL,
                    'Opening balance carried over from registry counter at ledger migration',
                    now(), now()
                FROM "VendorRiderRegistry" r
                WHERE COALESCE(r."{column}", 0) <> 0
                """
            )
        )


def downgrade() -> None:
    op.drop_table("bottle_ledger_entries")
    sa.Enum(name="bottle_ledger_entry_type").drop(op.get_bind(), checkfirst=True)
