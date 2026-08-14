"""drop the single-staff columns — the contract half of the expand/contract

`d3e5f7a91c24` created `Vendor_Staff` and backfilled every grant into it, then
deliberately left `Vendor.staff_clerk_id` and `Vendor.staff_push_token` in place
and unread so that rolling the application back could not lose anybody's access.
This removes them.

**Do not apply this until the deployed backend is confirmed to be reading
`Vendor_Staff`.** The ordering is the whole point of expand/contract: while a
build that still reads the old columns can be rolled back to, dropping them
turns that rollback into a 500 on every vendor request. Once this is applied,
the previous release is no longer a safe rollback target.

The safe sequence — step 3 is the one that is easy to miss:

1. Deploy the backend that reads `Vendor_Staff`. Every reader was converted and
   `tests/test_vendor_staff.py` fails the build if one comes back, but the
   *model* still declares both columns at this point, which is deliberate: the
   DB still has them, so the mapping is accurate and a rollback is safe.
2. Let it run long enough that rolling back to the previous release is no longer
   on the table.
3. Delete `staff_clerk_id` and `staff_push_token` from `models/vendor_model.py`
   and deploy that. **Before** the migration, not after — SQLAlchemy names every
   mapped column in its SELECT, so a model that still declares them against a
   table that no longer has them turns *every* vendor query into an
   `UndefinedColumn` error. A model that declares fewer columns than the table
   has is harmless, which is why this ordering is the safe one.
4. `alembic upgrade head`.

Applying this migration while any running instance still maps those columns is
the failure mode to avoid; it is not something `_assert_backfilled` can detect,
because the problem is in the deployed code rather than in the data.

That is why `upgrade()` also demands `ALLOW_STAFF_COLUMN_DROP=true`. This
revision is the repository's head, so a routine `alembic upgrade head` would
otherwise reach it and drop the columns out from under whatever is deployed —
turning every vendor request into `UndefinedColumn`. The variable is the
operator asserting step 3 has actually happened; without it the migration stops
with an instruction instead of breaking production.

`upgrade()` also refuses rather than dropping when it finds a grant that exists
only in the old column — see `_assert_backfilled`. That is the case where a
store gained a staff member through an older build after the backfill ran, and
dropping would silently revoke them.

Revision ID: e6b2c8d40f17
Revises: f7e3b91c8d24
Create Date: 2026-08-01 00:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6b2c8d40f17'
down_revision: Union[str, Sequence[str], None] = 'b8e1d47f3a92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_backfilled() -> None:
    """Refuse to drop a grant that was never copied across.

    `d3e5f7a91c24` backfilled what existed when it ran. A store that was given a
    staff member afterwards, by a build still writing the old column, would have
    the id here and no row in `Vendor_Staff` — and dropping the column would
    revoke them with nothing to show it happened.
    """
    orphaned = op.get_bind().execute(
        sa.text(
            """
            SELECT v.id, v.staff_clerk_id
            FROM "Vendors" v
            WHERE v.staff_clerk_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM "Vendor_Staff" s
                  WHERE s.vendor_id = v.id
                    AND s.clerk_id = v.staff_clerk_id
                    AND s.revoked_at IS NULL
              )
            """
        )
    ).fetchall()

    if orphaned:
        listed = ", ".join(f"vendor {row[0]} -> {row[1]}" for row in orphaned[:10])
        more = f" (and {len(orphaned) - 10} more)" if len(orphaned) > 10 else ""
        raise RuntimeError(
            f"{len(orphaned)} staff grant(s) exist only in Vendors.staff_clerk_id "
            f"and would be silently revoked by this migration: {listed}{more}. "
            "A build that still writes the old column has run since "
            "d3e5f7a91c24. Re-run that backfill (or insert the missing "
            'Vendor_Staff rows) before upgrading.'
        )


def _assert_operator_opted_in() -> None:
    """Refuse unless someone has confirmed the application no longer maps these.

    `_assert_backfilled` checks the *data*. This checks the thing that actually
    goes wrong: SQLAlchemy names every mapped column in its SELECT, so a build
    whose `Vendor` model still declares `staff_clerk_id` will raise
    `UndefinedColumn` on **every vendor query** the moment this runs. No query
    against the database can detect that, because the problem is in the code
    that is deployed.

    Since this revision is the head, a routine `alembic upgrade head` reaches it
    on any deploy. The opt-in is what makes that safe: unset, this stops with
    the sequence to follow; set, it is an operator saying step 3 is done.
    """
    if os.getenv("ALLOW_STAFF_COLUMN_DROP", "").strip().lower() == "true":
        return

    raise RuntimeError(
        "Refusing to drop Vendors.staff_clerk_id / staff_push_token.\n"
        "\n"
        "This is the contract half of an expand/contract migration and it is not "
        "safe to run on a schedule. Before applying it:\n"
        "  1. Deploy the backend that reads Vendor_Staff (already done).\n"
        "  2. Let it run long enough that rolling back is off the table.\n"
        "  3. Delete staff_clerk_id and staff_push_token from "
        "models/vendor_model.py and deploy THAT — before this migration, not "
        "after. A model that declares a column the table no longer has turns "
        "every vendor query into UndefinedColumn.\n"
        "  4. Re-run with ALLOW_STAFF_COLUMN_DROP=true.\n"
        "\n"
        "Every other migration up to b4c7e2a91f30 applies normally; use "
        "`alembic upgrade b4c7e2a91f30` for routine deploys until then."
    )


def upgrade() -> None:
    _assert_operator_opted_in()
    _assert_backfilled()

    # The index and UNIQUE constraint go with the column automatically, but the
    # index was created explicitly by `index=True` on the model, so drop it by
    # name first to keep the operation legible in the logs.
    op.drop_index("ix_Vendors_staff_clerk_id", table_name="Vendors", if_exists=True)
    op.drop_column("Vendors", "staff_clerk_id")
    op.drop_column("Vendors", "staff_push_token")


def downgrade() -> None:
    """Restore the columns, and repopulate them as faithfully as the old shape allows.

    It cannot be faithful in general: the old schema holds **one** staff member
    per store and one push token, so a store with three members comes back with
    one. The earliest is chosen, matching `d3e5f7a91c24`'s own downgrade, so the
    two are at least consistent about which grant survives.

    `staff_clerk_id` is UNIQUE platform-wide, so a person staffing two stores
    would violate it on the way back. `DISTINCT ON (clerk_id)` drops the second
    store's row rather than failing the downgrade — losing a grant that the old
    schema was incapable of holding in the first place.
    """
    op.add_column("Vendors", sa.Column("staff_clerk_id", sa.String(), nullable=True))
    op.add_column("Vendors", sa.Column("staff_push_token", sa.String(), nullable=True))

    op.execute(
        """
        WITH earliest AS (
            SELECT DISTINCT ON (vendor_id) vendor_id, clerk_id, push_token, created_at
            FROM "Vendor_Staff"
            WHERE revoked_at IS NULL AND clerk_id IS NOT NULL
            ORDER BY vendor_id, created_at ASC
        ), one_store_each AS (
            SELECT DISTINCT ON (clerk_id) vendor_id, clerk_id, push_token
            FROM earliest
            ORDER BY clerk_id, created_at ASC
        )
        UPDATE "Vendors" v
        SET staff_clerk_id = e.clerk_id,
            staff_push_token = e.push_token
        FROM one_store_each e
        WHERE v.id = e.vendor_id
        """
    )

    op.create_index(
        "ix_Vendors_staff_clerk_id", "Vendors", ["staff_clerk_id"], unique=True
    )
