"""Vendor storefront controls: cash toggle, order minimum, timed pause

Three decisions that belong to whoever is standing in the shop.

The platform already had `is_online` and a swipe control in the vendor app
wired to it — and **nothing on the ordering path ever read it**. A vendor could
swipe their store closed, watch the toggle turn grey, and keep receiving
orders. `shift_start`/`shift_end` were in the same position: stored since the
first migration, rendered on the console, enforced nowhere.

This adds the two controls that did not exist at all and the expiry that makes
the pause safe to use:

* ``accepts_cash`` — a store with no float must be able to decline cash.
  Deliberately **not** `preferred_payment_method`: that array holds the
  vendor's *payout* destination (`MPESA_TILL`, a paybill, a bank account) and
  is written by the payout settings screen.
* ``min_order_value`` — the smallest basket the store will prepare.
* ``paused_until`` / ``pause_reason`` — a pause that ends by itself. An
  indefinite closure is what `is_online` is for; the failure mode of a pause
  with no expiry is a store dark until somebody notices the next morning.

Backfill is the permissive value in every case (`accepts_cash = true`,
`min_order_value = 0`, no pause), so no existing store changes behaviour when
this runs. The enforcement that follows is what changes behaviour, and only
for a store that sets something.

Revision ID: a5c8d3f21b74
Revises: c3a7f21b9e40
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c8d3f21b74'
down_revision: Union[str, Sequence[str], None] = 'c3a7f21b9e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'Vendors',
        sa.Column('accepts_cash', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column(
        'Vendors',
        sa.Column('min_order_value', sa.Numeric(10, 2), nullable=False, server_default='0'),
    )
    op.add_column(
        'Vendors',
        sa.Column('paused_until', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column('Vendors', sa.Column('pause_reason', sa.String(), nullable=True))

    op.create_index('ix_Vendors_accepts_cash', 'Vendors', ['accepts_cash'])

    # Partial: the sweep that reopens expired pauses only ever looks at rows
    # that have one, and on any real platform that is a handful out of every
    # store on it.
    op.create_index(
        'ix_vendors_paused_until',
        'Vendors',
        ['paused_until'],
        postgresql_where=sa.text('paused_until IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_vendors_paused_until', table_name='Vendors', if_exists=True)
    op.drop_index('ix_Vendors_accepts_cash', table_name='Vendors', if_exists=True)
    op.drop_column('Vendors', 'pause_reason')
    op.drop_column('Vendors', 'paused_until')
    op.drop_column('Vendors', 'min_order_value')
    op.drop_column('Vendors', 'accepts_cash')
