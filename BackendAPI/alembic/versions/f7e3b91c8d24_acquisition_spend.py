"""Acquisition spend the database cannot otherwise see

The platform can compute part of its acquisition cost exactly — `welcome_discount`
is on every order — and none of the rest. Posters, a branded boda, Meta ads, a
referral paid in cash: real money, spent on acquisition, invisible here.

A CAC built from the measured half alone would report that acquisition is cheap
and payback is fast, which is the wrong direction to be wrong in. This table
holds the other half, entered per month and per channel, and the growth service
keeps the two visibly separate.

One row per (month, channel). Without the constraint, "add spend" quietly
becomes "add more spend" on a double submit, and a CAC that doubles overnight is
indistinguishable from a bad month.

Revision ID: f7e3b91c8d24
Revises: a5c8d3f21b74
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f7e3b91c8d24'
down_revision: Union[str, Sequence[str], None] = 'a5c8d3f21b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'Acquisition_Spend',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        # Always the first of the month; normalised on write.
        sa.Column('period_month', sa.Date(), nullable=False),
        sa.Column('channel', sa.String(60), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('recorded_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('period_month', 'channel', name='uq_acquisition_period_channel'),
    )
    op.create_index('ix_acquisition_spend_month', 'Acquisition_Spend', ['period_month'])


def downgrade() -> None:
    op.drop_index('ix_acquisition_spend_month', table_name='Acquisition_Spend', if_exists=True)
    op.drop_table('Acquisition_Spend')
