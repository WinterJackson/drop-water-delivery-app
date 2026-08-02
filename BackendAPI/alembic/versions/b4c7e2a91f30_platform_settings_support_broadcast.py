"""configurable business settings, support tickets and broadcast campaigns

Three tables, one theme: things the owners need to change or answer without a
developer.

`Platform_Settings` is the significant one. Every fee, commission and radius on
the platform was a Python constant, so the business model could only be changed
by editing source and waiting for a deploy — which meant it never was. Moving it
into a row makes it an owner's decision.

Two properties keep that safe, and both are load-bearing:

* The three apps render `POST /api/cart/quote` verbatim, so a change is live on
  the next quote with no client release.
* Orders snapshot their own economics at quote time into their
  `vendor_commission` / `service_fee` / `rider_commission` / `platform_total`
  columns, and settlement pays from those columns. Changing a rate today
  therefore cannot alter what is owed on an order placed yesterday.

The table is deliberately **not** seeded. An absent key means "use the value the
platform shipped with", which is what `platform_config_service.DEFAULTS` holds,
so a fresh database and a rolled-back deploy both behave exactly as before this
migration. Seeding would instead freeze today's defaults into rows that a future
release could no longer change.

Revision ID: b4c7e2a91f30
Revises: a2d8f4b61e93
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4c7e2a91f30'
down_revision: Union[str, Sequence[str], None] = 'a2d8f4b61e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Configuration ─────────────────────────────────────────────────────

    op.create_table(
        "Platform_Settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_by_email", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "Platform_Setting_History",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by_email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_Platform_Setting_History_key", "Platform_Setting_History", ["key"])
    op.create_index(
        "ix_Platform_Setting_History_created_at", "Platform_Setting_History", ["created_at"]
    )
    # "What has changed on the delivery markup, most recent first" — the one
    # query the history screen makes.
    op.create_index(
        "idx_setting_history_key_created", "Platform_Setting_History", ["key", "created_at"]
    )

    # ── Support ───────────────────────────────────────────────────────────

    op.create_table(
        "Support_Tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # No foreign key, and no three nullable ones either: the platform's three
        # account tables have no common parent, exactly as with `Notifications`.
        sa.Column("requester_type", sa.String(length=16), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("related_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_admin_email", sa.String(length=255), nullable=True),
        sa.Column(
            "messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "requester_type IN ('customer', 'rider', 'vendor')",
            name="ck_ticket_requester_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')",
            name="ck_ticket_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_ticket_priority",
        ),
    )
    op.create_index("ix_Support_Tickets_status", "Support_Tickets", ["status"])
    op.create_index("ix_Support_Tickets_created_at", "Support_Tickets", ["created_at"])
    op.create_index("ix_Support_Tickets_related_order_id", "Support_Tickets", ["related_order_id"])
    op.create_index("ix_Support_Tickets_assigned_admin_id", "Support_Tickets", ["assigned_admin_id"])
    # The queue view: open tickets, oldest first.
    op.create_index("idx_ticket_status_created", "Support_Tickets", ["status", "created_at"])
    # "Every ticket this rider has raised", from their account page.
    op.create_index("idx_ticket_requester", "Support_Tickets", ["requester_type", "requester_id"])

    # ── Broadcast ─────────────────────────────────────────────────────────

    op.create_table(
        "Broadcast_Campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("audience_filter", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        # Defaults to false: a campaign is marketing unless someone says
        # otherwise, because the failure mode of guessing the other way is a
        # promotion that overrides a recipient's muted preferences.
        sa.Column("transactional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email', 'both')", name="ck_campaign_channel"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sending', 'sent', 'failed')", name="ck_campaign_status"
        ),
    )
    op.create_index("ix_Broadcast_Campaigns_status", "Broadcast_Campaigns", ["status"])
    op.create_index("ix_Broadcast_Campaigns_created_at", "Broadcast_Campaigns", ["created_at"])


def downgrade() -> None:
    op.drop_table("Broadcast_Campaigns")
    op.drop_table("Support_Tickets")
    op.drop_table("Platform_Setting_History")
    # Dropping this reverts the platform to its shipped defaults, which is the
    # correct behaviour: the code that reads it is going away in the same
    # rollback, and it falls back to exactly those values.
    op.drop_table("Platform_Settings")
