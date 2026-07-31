"""rating counters, notification list index, drop unused title index

Two unrelated but small changes to the ratings and notifications workflows.

**Ratings.** `Vendors.rating` and `Deliverers.rating` held a derived average with
nothing to derive it from, so every submission recomputed `AVG(rating)` over
every review the target had ever received — unbounded work on exactly the busiest
vendors — and no client could show a review *count*, so one five-star review and
three hundred both rendered as "5.0". `rating_count` and `rating_sum` make the
update O(1) and give the apps the count. Backfilled from `reviews`.

**Notifications.** The list query filters on (user_id, user_type) and orders by
`created_at DESC`; the only composite index ended at `is_read`, so Postgres sorted
the whole set on every open of the screen. The `title` index served no query and
cost a write on every notification the platform produces.

Revision ID: f8c4a2e17b53
Revises: e7b3d0c56a19
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c4a2e17b53"
down_revision: Union[str, Sequence[str], None] = "e7b3d0c56a19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_rating_counters(table: str) -> None:
    op.add_column(table, sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(table, sa.Column("rating_sum", sa.Float(), nullable=False, server_default="0"))


def _backfill(table: str, target_type: str, default_rating: str) -> None:
    """Recompute counters, and the average with them, from the reviews table.

    Targets with no reviews keep the platform default rather than dropping to
    zero: a rider with no ratings yet is not a one-star rider.
    """
    op.execute(
        sa.text(
            f"""
            UPDATE "{table}" AS t
            SET rating_count = COALESCE(r.cnt, 0),
                rating_sum   = COALESCE(r.total, 0),
                rating       = CASE
                                 WHEN COALESCE(r.cnt, 0) > 0
                                 THEN ROUND((r.total / r.cnt)::numeric, 2)
                                 ELSE {default_rating}
                               END
            FROM (
                SELECT target_id, COUNT(*) AS cnt, SUM(rating) AS total
                FROM reviews
                WHERE target_type = '{target_type}'
                GROUP BY target_id
            ) AS r
            WHERE r.target_id = t.id
            """
        )
    )


def upgrade() -> None:
    _add_rating_counters("Vendors")
    _add_rating_counters("Deliverers")
    _backfill("Vendors", "vendor", "0")
    _backfill("Deliverers", "rider", "5.0")

    op.create_index(
        "idx_notif_user_type_created",
        "Notifications",
        ["user_id", "user_type", "created_at"],
        unique=False,
    )
    # Created by the old model definition; `if_exists` keeps this idempotent on
    # databases where it was never created.
    op.execute(sa.text('DROP INDEX IF EXISTS "ix_Notifications_title"'))


def downgrade() -> None:
    op.create_index("ix_Notifications_title", "Notifications", ["title"], unique=False)
    op.drop_index("idx_notif_user_type_created", table_name="Notifications")
    op.drop_column("Deliverers", "rating_sum")
    op.drop_column("Deliverers", "rating_count")
    op.drop_column("Vendors", "rating_sum")
    op.drop_column("Vendors", "rating_count")
