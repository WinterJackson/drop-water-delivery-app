"""Make the device gate reachable, and record what an order cost the platform.

## `Users.device_id` was UNIQUE, which made its own check impossible

The column exists to stop one handset claiming the first-order welcome discount
repeatedly — 30% of a KSH 300 deposit, taken entirely out of platform margin,
against an account that costs nothing to create.

`pricing_service.welcome_offer_available` implements that by looking for
*another* account carrying the same `device_id`. A UNIQUE constraint guarantees
there is never one, so the query could not return a row under any circumstances.
The gate had never fired, and could not have.

It was also wrong on its own terms: a second person registering on a shared
handset — a household with one phone, entirely ordinary here — hit an integrity
error at signup. Dropping the constraint fixes both. The index stays, because
the gate queries the column on every first quote.

(The other two halves of that defect are not schema: no app ever sent the field,
and a null was treated as eligible. Both are fixed in the same change.)

## `Orders.platform_cost` / `platform_net`

Safaricom charges the business to collect a C2B payment, and a cash order costs
reconciliation and float risk instead. Neither was modelled anywhere, so every
margin figure on the console was gross presented as net — on a KSH 442 order the
M-Pesa tariff alone is a large share of the platform's entire cut.

Recorded per order, at quote time, alongside the splits it sits beside. Like
every other figure there it is frozen when the order is created: changing the
tariff setting tomorrow must not restate what yesterday's orders earned.

Nullable, with no back-fill. Historic orders genuinely have no recorded cost and
inventing one would put a number the business never measured into its own
history. Reports must treat null as unknown, not as zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd9f3a71c5b82'
down_revision: Union[str, Sequence[str], None] = 'c4d7e2f18a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The constraint name Postgres generated for `unique=True` on this column.
    # Dropped defensively: a database built from an older head may not have it.
    op.execute('ALTER TABLE "Users" DROP CONSTRAINT IF EXISTS "Users_device_id_key"')
    op.execute('DROP INDEX IF EXISTS ix_Users_device_id')
    op.create_index("ix_users_device_id", "Users", ["device_id"], unique=False)

    op.add_column("Orders", sa.Column("platform_cost", sa.Numeric(10, 2), nullable=True))
    op.add_column("Orders", sa.Column("platform_net", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("Orders", "platform_net")
    op.drop_column("Orders", "platform_cost")

    op.drop_index("ix_users_device_id", table_name="Users")
    # Recreating the UNIQUE constraint can fail if two accounts now share a
    # handset — which is exactly the state this migration made legal. Left to
    # the operator rather than failing the downgrade halfway through.
    op.create_index("ix_Users_device_id", "Users", ["device_id"], unique=False)
