"""Record the last two figures of a quote on the order that was charged

Revision ID: c8b4f0d92e17
Revises: a3f81e6c5d27
Create Date: 2026-08-19

`compute_order_quote` publishes eleven money figures and `create_order` froze
nine of them onto the row. The two it dropped were the two applied last:

* **`mpesa_discount`** — KSH 10 off for not paying cash. Applied to the total,
  recorded nowhere. Every prepaid order therefore had a stored breakdown that
  came out ten shillings above the `total_amount` sitting beside it.
* **`rounding_adjustment`** — the residue of quantizing to a whole shilling,
  which M-Pesa requires. Under fifty cents, and the reason the other ten lines
  do not land exactly on the total even once the discount is there.

Together they are why no order's own lines could be added up to the amount the
customer paid. That reconciliation is not cosmetic: `order_snapshot` is the
frozen record a delivery dispute is settled from weeks later, and a record that
does not add up is one nobody can argue from.

**Backfill is deliberately partial, and says so.** `mpesa_discount` cannot be
recovered for historic orders — the setting may have moved since, and a guess
written into a money column is indistinguishable from a fact. Both columns
default to zero, which for an old order means "not recorded" rather than
"was zero"; `rounding_adjustment` is the honest one to derive, because it is
purely arithmetic on figures the row already holds, so it is computed for rows
where every component is present.

Parented on `a3f81e6c5d27` and the gated drop re-parented onto this, keeping
`e6b2c8d40f17` terminal — a revision after it could only run on a deploy that
had already accepted the column drop.

**A database stamped at `e6b2c8d40f17` will not receive this.** Alembic treats
every ancestor of the recorded version as applied, and inserting below a
terminal revision puts this one behind anything already sitting on it. That is
not the deployed database — it is below the gate, by design, so this runs there
normally — but it *is* every box built with `scripts/bootstrap_database.py`,
which does `create_all` and stamps `head` without walking the chain. Those get
the columns from the models instead, so a fresh bootstrap is already correct and
an existing one needs them added by hand:

    ALTER TABLE "Orders" ADD COLUMN mpesa_discount numeric(10,2) NOT NULL DEFAULT 0;
    ALTER TABLE "Orders" ADD COLUMN rounding_adjustment numeric(10,2) NOT NULL DEFAULT 0;
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c8b4f0d92e17'
down_revision: Union[str, None] = 'a3f81e6c5d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `IF NOT EXISTS`, deliberately, rather than `op.add_column`.
    #
    # Deploys here are automatic on push and migrations are a manual step, so
    # the code always lands before the schema. That window is the whole reason
    # this note exists: the running model names every mapped column in its
    # SELECT, so between the deploy and the upgrade *every* query that selects
    # an Order raises `UndefinedColumn`. Closing it means being able to add the
    # two columns by hand immediately and let alembic catch up afterwards
    # without colliding — which a plain `add_column` cannot do, because it would
    # then fail on a column that is already there and block the upgrade.
    #
    # Adding a `NOT NULL` column with a constant default is metadata-only on
    # PostgreSQL 11+; it does not rewrite the table and does not take a long
    # lock, so it is safe to run on a live database.
    op.execute(
        'ALTER TABLE "Orders" ADD COLUMN IF NOT EXISTS '
        "mpesa_discount numeric(10, 2) NOT NULL DEFAULT 0"
    )
    op.execute(
        'ALTER TABLE "Orders" ADD COLUMN IF NOT EXISTS '
        "rounding_adjustment numeric(10, 2) NOT NULL DEFAULT 0"
    )

    # Derive the rounding only. It is `total_amount` less the ten components,
    # which is arithmetic on this row and nothing else — no setting, no guess.
    #
    # Scoped to rows where the discount is genuinely zero: on a prepaid order
    # the un-recorded `mpesa_discount` is inside this difference, and writing
    # that into `rounding_adjustment` would be recording a discount under the
    # name of a rounding. Those rows keep 0 and are honestly incomplete.
    op.execute(
        """
        UPDATE "Orders"
        SET rounding_adjustment = ROUND(
            total_amount - (
                  COALESCE(product_subtotal, 0)
                + COALESCE(delivery_fee, 0)
                + COALESCE(service_fee, 0)
                + COALESCE(surge_fee, 0)
                + COALESCE(payload_surcharge, 0)
                + COALESCE(staircase_surcharge, 0)
                + COALESCE(bottle_deposit, 0)
                + COALESCE(debt_settlement, 0)
                - COALESCE(welcome_discount, 0)
                - COALESCE(wallet_discount, 0)
            ), 2)
        WHERE payment_method = 'cash'
          AND total_amount IS NOT NULL
          AND ABS(
            total_amount - (
                  COALESCE(product_subtotal, 0)
                + COALESCE(delivery_fee, 0)
                + COALESCE(service_fee, 0)
                + COALESCE(surge_fee, 0)
                + COALESCE(payload_surcharge, 0)
                + COALESCE(staircase_surcharge, 0)
                + COALESCE(bottle_deposit, 0)
                + COALESCE(debt_settlement, 0)
                - COALESCE(welcome_discount, 0)
                - COALESCE(wallet_discount, 0)
            )
          ) <= 0.50
        """
    )


def downgrade() -> None:
    op.execute('ALTER TABLE "Orders" DROP COLUMN IF EXISTS rounding_adjustment')
    op.execute('ALTER TABLE "Orders" DROP COLUMN IF EXISTS mpesa_discount')
