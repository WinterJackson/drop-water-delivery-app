"""staff as a relationship, not a column

`Vendor.staff_clerk_id` held exactly one id and carried a UNIQUE constraint, so:

* a store could have one staff member, and adding a second silently replaced the
  first (behind a screen called "Manage Staff");
* one person could be staff of exactly one store on the whole platform;
* access was all-or-nothing — there was no way to let someone take orders
  without also handing them the catalogue, the bottle ledger and the balance;
* `Vendor.staff_push_token` could address only one of them.

This creates `Vendor_Staff` and backfills every existing grant into it with the
default capability set. The two old columns are deliberately **left in place and
unread**: this is the expand half of an expand/contract, so a rollback of the
application does not lose anybody's access. Dropping them is a separate
migration, once the deployed backend is known to be reading this table.

Revision ID: d3e5f7a91c24
Revises: c7d1a4f92b08
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd3e5f7a91c24'
down_revision: Union[str, Sequence[str], None] = 'c7d1a4f92b08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Matches `DEFAULT_PERMISSIONS` in `models/vendor_staff_model.py`. Existing
#: staff had unrestricted access to everything that was not owner-only, so this
#: is a narrowing — `view_finances` is deliberately not granted, because seeing
#: the store's balance should be a decision the owner makes, not one inherited
#: from a schema that could not express the question.
_BACKFILL_PERMISSIONS = '["manage_orders", "manage_products", "manage_bottles"]'


def upgrade() -> None:
    op.create_table(
        'Vendor_Staff',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        # Null until the invited person signs in for the first time — the owner
        # invites by email and we cannot know their Clerk subject before then.
        sa.Column('clerk_id', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('push_token', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('revoked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('invited_by_clerk_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('accepted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['vendor_id'], ['Vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vendor_id', 'clerk_id', name='uq_vendor_staff_member'),
    )
    op.create_index('idx_vendor_staff_clerk', 'Vendor_Staff', ['clerk_id', 'revoked_at'])
    op.create_index('idx_vendor_staff_vendor', 'Vendor_Staff', ['vendor_id', 'revoked_at'])

    # Backfill. `email` is NOT NULL and the old schema never recorded one, so
    # the placeholder is explicit rather than blank — the owner sees a row they
    # can recognise as pre-existing and re-invite properly.
    op.execute(
        f"""
        INSERT INTO "Vendor_Staff"
            (id, vendor_id, clerk_id, email, permissions, push_token,
             is_active, created_at, accepted_at)
        SELECT
            gen_random_uuid(),
            v.id,
            v.staff_clerk_id,
            'migrated-staff@drop.local',
            '{_BACKFILL_PERMISSIONS}'::jsonb,
            v.staff_push_token,
            true,
            now(),
            now()
        FROM "Vendors" v
        WHERE v.staff_clerk_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Restore the single-staff columns from the table. Only one grant per store
    # can survive this, which is the whole reason the table exists — the oldest
    # is kept, so a rollback never promotes someone added later.
    op.execute(
        """
        UPDATE "Vendors" v
        SET staff_clerk_id = s.clerk_id,
            staff_push_token = s.push_token
        FROM (
            SELECT DISTINCT ON (vendor_id) vendor_id, clerk_id, push_token
            FROM "Vendor_Staff"
            WHERE revoked_at IS NULL AND clerk_id IS NOT NULL
            ORDER BY vendor_id, created_at ASC
        ) s
        WHERE s.vendor_id = v.id
        """
    )
    op.drop_index('idx_vendor_staff_vendor', table_name='Vendor_Staff')
    op.drop_index('idx_vendor_staff_clerk', table_name='Vendor_Staff')
    op.drop_table('Vendor_Staff')
