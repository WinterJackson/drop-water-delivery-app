"""administrators, the audit log, and suspension state

Three things, one migration because they ship together:

1. `Admin_Users` — replaces the `ADMIN_CLERK_IDS` environment allowlist, which
   could not express roles, could not be revoked without a redeploy, and left
   no attribution.
2. `Admin_Audit_Log` — append-only record of every administrative mutation and
   every reveal of personal data.
3. Suspension columns on `Vendors`, `Users` and `Deliverers`. A vendor could not
   be switched off at all: `verification_status` records how a store *joined*
   and `is_online` is the vendor's own toggle, which they can turn straight back
   on. Customers and riders had `is_active` with nowhere to record why.

This migration adds schema only. No account is suspended by it, and every
existing row keeps the behaviour it had: `Vendors.is_active` defaults to true.

This migration sits *before* `e6b2c8d40f17` (which drops the legacy single-staff
columns) rather than after it, even though it was written later. `e6b2c8d40f17`
is deliberately held back until the deployed backend stops reading those
columns; chaining this behind it would mean the admin console could not ship
without also applying a migration that breaks production.

Revision ID: f1a7c3e59d82
Revises: d3e5f7a91c24
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1a7c3e59d82'
down_revision: Union[str, Sequence[str], None] = 'd3e5f7a91c24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Administrators ────────────────────────────────────────────────────
    op.create_table(
        "Admin_Users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Null until the invited person signs in for the first time.
        sa.Column("clerk_id", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="support"),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_admin_users_email"),
    )
    op.create_index("idx_admin_users_clerk", "Admin_Users", ["clerk_id", "revoked_at"])
    op.create_index("idx_admin_users_active", "Admin_Users", ["revoked_at", "is_active"])

    # ── Audit ─────────────────────────────────────────────────────────────
    op.create_table(
        "Admin_Audit_Log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Denormalised deliberately: the record must stay readable after the
        # administrator row is revoked, and joining to a mutable table for an
        # immutable record would let history change retroactively. For the same
        # reason there is no foreign key here.
        sa.Column("admin_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_admin_audit_admin", "Admin_Audit_Log", ["admin_id", "created_at"])
    op.create_index("idx_admin_audit_target", "Admin_Audit_Log", ["target_type", "target_id"])
    op.create_index("idx_admin_audit_action", "Admin_Audit_Log", ["action", "created_at"])
    # "Everything, newest first" is the default view and the one query that runs
    # on every open of the audit screen.
    op.create_index("idx_admin_audit_created", "Admin_Audit_Log", ["created_at"])

    # ── Suspension state ──────────────────────────────────────────────────
    # `Vendors.is_active` is NOT NULL with a server default of true, so every
    # existing store keeps trading. The default stays on the column rather than
    # being dropped after the backfill: rows are also inserted by vendor
    # registration, which does not set it.
    op.add_column(
        "Vendors",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("idx_vendors_is_active", "Vendors", ["is_active"])

    for table in ("Vendors", "Users", "Deliverers"):
        op.add_column(table, sa.Column("suspended_at", sa.TIMESTAMP(timezone=True), nullable=True))
        op.add_column(table, sa.Column("suspension_reason", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("suspended_by", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    for table in ("Deliverers", "Users", "Vendors"):
        op.drop_column(table, "suspended_by")
        op.drop_column(table, "suspension_reason")
        op.drop_column(table, "suspended_at")

    op.drop_index("idx_vendors_is_active", table_name="Vendors")
    op.drop_column("Vendors", "is_active")

    op.drop_index("idx_admin_audit_created", table_name="Admin_Audit_Log")
    op.drop_index("idx_admin_audit_action", table_name="Admin_Audit_Log")
    op.drop_index("idx_admin_audit_target", table_name="Admin_Audit_Log")
    op.drop_index("idx_admin_audit_admin", table_name="Admin_Audit_Log")
    op.drop_table("Admin_Audit_Log")

    op.drop_index("idx_admin_users_active", table_name="Admin_Users")
    op.drop_index("idx_admin_users_clerk", table_name="Admin_Users")
    op.drop_table("Admin_Users")
