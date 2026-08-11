"""The retail delivery radius becomes 2.5 km, and the vendor column goes.

Two changes, one decision: **how far an order travels is the platform's to set,
it is 2.5 km for retail refill and 15 km for wholesale, and no store sets its
own.**

## 1. Retiring the superseded 2 km default

`retail_max_distance_km` ships 2.5 from this release. Changing the shipped
default does not change a running platform: `_load` reads a stored row and the
row wins, which is right for a figure somebody chose and wrong for one that
merely materialised the old default. Once written the two are indistinguishable.
So, exactly as `b2f9c14e7a35` established, any stored row **still holding the
superseded 2** is deleted — that value carries no decision, it says precisely
what the platform would have said with no row at all. Anything else is left
alone: a stored 3 is somebody's choice, and overwriting it would be the opposite
of the fix.

Deleting rather than writing 2.5 is deliberate. An absent row means "follow the
platform", so the key stays correct through the *next* change too; writing 2.5
would pin it and reproduce the defect one release later.

## 2. Dropping `Vendor.delivery_radius`

The column was writable by the vendor — the profile PATCH accepted it and the
vendor app shipped a stepper — and **no dispatch, discovery or checkout path has
ever read it**. Placing a test order after moving it therefore looked correct,
because the radius that applied was the platform's.

It was not inert, though. Two screens rendered it: the vendor's own map drew its
catchment circle from it, and the customer's product page derived the delivery
estimate from it — from the *radius* rather than the distance to that customer,
so everybody browsing the store saw the time to the edge of the catchment. A
shop that set 15 km quoted "45 min – 1.5 hrs" to the flat upstairs. The only
outcome a vendor could achieve with the control was making their own store look
slower.

Now that the API refuses to write it and no client reads it, a nullable float on
`Vendors` that nothing populates and nothing consults is a column whose only
remaining function is to be mistaken for the catchment by the next person. The
real figure reaches the vendor app through `GET /api/vendor/storefront`, beside
the other bounds the server owns.

The data is not worth preserving: every value in it was either a seed constant
or a vendor's guess at a number that never applied. `downgrade()` restores the
column, empty, which is the honest inverse — the platform radius it was being
confused with is a settings row and was never in here.

Revision ID: c7d2e94a6f18
Revises: d4a8f2c61b93
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d2e94a6f18"
down_revision: Union[str, Sequence[str], None] = "d4a8f2c61b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: `key: (superseded_default, current_default)`.
#:
#: Point-in-time by design, like `b2f9c14e7a35`'s: a migration records what the
#: defaults were when it ran and must keep saying so after the source moves on.
#: `test_the_retirement_table_still_describes_todays_defaults` reads every table
#: in this directory and fires when one of these defaults moves again.
_SUPERSEDED: dict[str, tuple[float, float]] = {
    # 2 km was the launch figure and excluded stores a rider reaches in the same
    # few minutes. 2.5 is a deliberate widening of what a customer can see,
    # applied to discovery and checkout together — they read the one setting.
    "retail_max_distance_km": (2.0, 2.5),
}

_REASON = (
    "Retired by migration c7d2e94a6f18: this row held the previous shipped "
    "retail radius, so it recorded no decision while preventing the current "
    "one from applying."
)


def upgrade() -> None:
    for key, (superseded, current) in _SUPERSEDED.items():
        # History first — the row has to still exist to be read off.
        op.execute(
            f"""
            INSERT INTO "Platform_Setting_History"
                (id, key, before, after, version, reason, changed_by_email, created_at)
            SELECT
                gen_random_uuid(),
                '{key}',
                s.value,
                '{current}'::jsonb,
                COALESCE((SELECT MAX(version) FROM "Platform_Settings"), 0) + 1,
                '{_REASON}',
                'migration:c7d2e94a6f18',
                NOW()
            FROM "Platform_Settings" s
            WHERE s.key = '{key}'
              AND jsonb_typeof(s.value) = 'number'
              AND (s.value #>> '{{}}')::numeric = {superseded}
            """
        )
        op.execute(
            f"""
            DELETE FROM "Platform_Settings"
            WHERE key = '{key}'
              AND jsonb_typeof(value) = 'number'
              AND (value #>> '{{}}')::numeric = {superseded}
            """
        )

    op.drop_index("ix_Vendors_delivery_radius", table_name="Vendors", if_exists=True)
    op.drop_column("Vendors", "delivery_radius")


def downgrade() -> None:
    """Restore the column empty, and put the superseded radius back.

    The history row is the evidence, matched on `changed_by_email` so a
    downgrade cannot resurrect a value an administrator deleted by other means.
    The history rows themselves stay: they are an append-only record of what
    happened, and it did happen.
    """
    op.add_column(
        "Vendors",
        sa.Column("delivery_radius", sa.Float(), nullable=True),
    )
    op.create_index("ix_Vendors_delivery_radius", "Vendors", ["delivery_radius"])

    for key, (superseded, _current) in _SUPERSEDED.items():
        op.execute(
            f"""
            INSERT INTO "Platform_Settings" (key, value, version, updated_at, updated_by_email)
            SELECT
                '{key}',
                '{superseded}'::jsonb,
                COALESCE((SELECT MAX(version) FROM "Platform_Settings"), 0) + 1,
                NOW(),
                'migration:c7d2e94a6f18'
            WHERE EXISTS (
                SELECT 1 FROM "Platform_Setting_History"
                WHERE key = '{key}' AND changed_by_email = 'migration:c7d2e94a6f18'
            )
            AND NOT EXISTS (
                SELECT 1 FROM "Platform_Settings" WHERE key = '{key}'
            )
            """
        )
