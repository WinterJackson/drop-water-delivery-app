"""hide a review without deleting it

`reviews` had no moderation state at all. A review naming a rider's home
address, or one a customer left on the wrong order, could only be removed with a
DELETE — which loses the fact that it ever existed, breaks
`uq_customer_order_target_review` (the customer can then leave another), and
leaves the target's `rating_sum` and `rating_count` pointing at a row that is
gone.

So this is a hide, with the three columns that make it accountable: when, by
whom, and why. Every read path filters on `hidden_at IS NULL`, and the target's
counters are rebuilt from the visible rows the moment a review is hidden — a
one-star review that stays in the average after being taken down is moderation
theatre.

The partial index is what keeps the moderation queue cheap: the console reads
hidden rows only on one tab, and every other query wants the complement.

Revision ID: a9f4b2c71d63
Revises: b4c7e2a91f30
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9f4b2c71d63'
down_revision: Union[str, Sequence[str], None] = 'b4c7e2a91f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reviews',
        sa.Column(
            'hidden_at',
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment='Set when an administrator takes the review down. Never deleted.',
        ),
    )
    op.add_column(
        'reviews',
        sa.Column(
            'hidden_by',
            sa.String(),
            nullable=True,
            comment="Clerk id of the administrator who hid it.",
        ),
    )
    op.add_column(
        'reviews',
        sa.Column(
            'hidden_reason',
            sa.String(length=500),
            nullable=True,
            comment='Why. Mandatory at the API; nullable here because rows predate it.',
        ),
    )

    # Every public read wants the visible rows for one target. Partial, because
    # hidden reviews are read on exactly one screen and would otherwise bloat
    # the index that carries the customer-facing query.
    op.create_index(
        'idx_reviews_visible_target',
        'reviews',
        ['target_type', 'target_id'],
        postgresql_where=sa.text('hidden_at IS NULL'),
    )
    # The moderation queue reads the complement, newest first.
    op.create_index(
        'idx_reviews_hidden_at',
        'reviews',
        ['hidden_at'],
        postgresql_where=sa.text('hidden_at IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('idx_reviews_hidden_at', table_name='reviews')
    op.drop_index('idx_reviews_visible_target', table_name='reviews')
    op.drop_column('reviews', 'hidden_reason')
    op.drop_column('reviews', 'hidden_by')
    op.drop_column('reviews', 'hidden_at')
