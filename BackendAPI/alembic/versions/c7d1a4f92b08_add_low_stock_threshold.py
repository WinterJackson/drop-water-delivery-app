"""add per-product low stock threshold

A vendor's stock reaching zero silently is expensive for everyone: orders keep
being accepted against nothing, then cancelled — which restores the stock,
refunds the customer, costs the vendor their rating and the platform its cut.
`stock` was captured on create/update and rendered on the products list, and
nothing else in the system referenced it. There was no threshold, no badge, no
notification and no dashboard signal.

Nullable with a server default rather than a backfill: existing rows get 5, and
`NULL` is not a state the application has to reason about.

Revision ID: c7d1a4f92b08
Revises: f8c4a2e17b53
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d1a4f92b08'
down_revision: Union[str, Sequence[str], None] = 'f8c4a2e17b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'Products',
        sa.Column(
            'low_stock_threshold',
            sa.Integer(),
            nullable=False,
            server_default='5',
            comment='Warn the vendor at or below this stock level. 0 disables the warning.',
        ),
    )
    # One notification per crossing, not one per order. Without this the vendor
    # gets a push for every unit sold once they are below the line.
    op.add_column(
        'Products',
        sa.Column('low_stock_notified_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        'idx_products_vendor_low_stock',
        'Products',
        ['vendor_id', 'stock'],
    )


def downgrade() -> None:
    op.drop_index('idx_products_vendor_low_stock', table_name='Products')
    op.drop_column('Products', 'low_stock_notified_at')
    op.drop_column('Products', 'low_stock_threshold')
