"""bottle deposits, settleable debt, product withdrawal, and money precision

Everything the remediation of the business-logic audit needs from the schema, in
one revision so a deploy applies it atomically.

Parented **before** `e6b2c8d40f17`, which is gated on `ALLOW_STAFF_COLUMN_DROP`
and stays the head. A revision after it could never run on a routine
`alembic upgrade a9f4b2c71d63`.

Five groups of change:

**1. Bottle deposits become an accounted liability.** `Orders.bottle_deposit`
records what was charged; `Users.bottle_deposit_balance` and `Users.bottles_held`
record what the platform owes back and for how many bottles. The deposit was
previously folded into `vendor_net` and forgotten, so the platform could not
answer "how much deposit has this customer paid?" and had no way to return one.

**2. Debt becomes settleable.** `Orders.debt_settlement` records how much of a
customer's outstanding balance an order collected, so a cancellation can put it
back. Without the column a reversal cannot tell a debt-collecting order from an
ordinary one.

**3. Products are withdrawn, not deleted.** `Products.deleted_at`.
`Order_Items.product_id` is a foreign key with no `ondelete`, so deleting a
product that has ever sold was a foreign-key violation the vendor saw as a 500.

**4. `device_id` stops being unique per account and starts being usable.** It
was created `unique=True`, which is the wrong constraint for "one welcome offer
per device": two people in a household sharing a handset could not both hold
accounts, while the check the column exists for was never written. A plain index
supports the lookup that now runs.

**5. Money columns move from `Double` to `Numeric(10, 2).`** `Orders.delivery_fee`,
`Order_Items.price`, `Order_Items.Subtotal`, `Products.price`, `Products.discount`.
`Order_Items.Subtotal` is what the whole commission structure is computed from.

The `USING` casts are explicit because PostgreSQL will not silently narrow a
double precision column to a scaled numeric; existing values are rounded to two
decimal places, which is the precision they should always have had.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8e3d1a5c704'
down_revision: Union[str, Sequence[str], None] = 'a9f4b2c71d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Deposits as a tracked liability ────────────────────────────────
    op.add_column(
        'Orders',
        sa.Column('bottle_deposit', sa.Numeric(10, 2), nullable=False, server_default='0'),
    )
    op.add_column(
        'Users',
        sa.Column('bottle_deposit_balance', sa.Numeric(10, 2), nullable=False, server_default='0'),
    )
    op.add_column(
        'Users',
        sa.Column('bottles_held', sa.Integer(), nullable=False, server_default='0'),
    )

    # ── 2. Debt collected on an order, so a reversal can restore it ───────
    op.add_column(
        'Orders',
        sa.Column('debt_settlement', sa.Numeric(10, 2), nullable=False, server_default='0'),
    )

    # ── 3. Product withdrawal ─────────────────────────────────────────────
    op.add_column('Products', sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index(op.f('ix_Products_deleted_at'), 'Products', ['deleted_at'], unique=False)

    # ── 4. device_id: unique index → plain index ──────────────────────────
    # Dropped and recreated rather than altered: a unique index and a plain one
    # are different objects, and `ix_Users_device_id` is the name both the model
    # and the original revision use.
    op.drop_index(op.f('ix_Users_device_id'), table_name='Users')
    op.create_index(op.f('ix_Users_device_id'), 'Users', ['device_id'], unique=False)

    # ── 5. Money columns to Numeric ───────────────────────────────────────
    for table, column in (
        ('Orders', 'delivery_fee'),
        ('Order_Items', 'price'),
        ('Order_Items', 'Subtotal'),
        ('Products', 'price'),
        ('Products', 'discount'),
    ):
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f'TYPE NUMERIC(10, 2) USING ROUND("{column}"::numeric, 2)'
        )


def downgrade() -> None:
    for table, column in (
        ('Products', 'discount'),
        ('Products', 'price'),
        ('Order_Items', 'Subtotal'),
        ('Order_Items', 'price'),
        ('Orders', 'delivery_fee'),
    ):
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f'TYPE DOUBLE PRECISION USING "{column}"::double precision'
        )

    # Restoring the unique index can fail where two accounts now share a handset
    # — which is exactly the situation this revision made legal. That is a real
    # constraint violation, not a migration bug: deduplicate before downgrading.
    op.drop_index(op.f('ix_Users_device_id'), table_name='Users')
    op.create_index(op.f('ix_Users_device_id'), 'Users', ['device_id'], unique=True)

    op.drop_index(op.f('ix_Products_deleted_at'), table_name='Products')
    op.drop_column('Products', 'deleted_at')

    op.drop_column('Orders', 'debt_settlement')
    op.drop_column('Users', 'bottles_held')
    op.drop_column('Users', 'bottle_deposit_balance')
    op.drop_column('Orders', 'bottle_deposit')
