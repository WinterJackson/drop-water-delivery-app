"""Record which balance row a wallet movement belongs to.

`WalletTransactions.user_id` is a **Clerk id**, and one Clerk identity may own
several stores — each `Vendor` row carries its own `wallet_balance`. Every
M-Pesa callback arrives minutes after the request that raised it and had to
re-resolve the owner from that clerk id with an unordered `.first()`, so:

* a top-up paid into the second branch credited the first, and
* a withdrawal debited from the second was refunded to the first when the
  disbursement failed.

Both leave two real balances wrong by the same amount in opposite directions,
with nothing in either ledger to explain it. `wallet_owner_id` names the row the
money actually came off, so the callback settles the one it started on.

Nullable on purpose. Existing rows predate the column and are resolved by the
clerk-id fallback in `wallet_service._locked_wallet_owner`; back-filling them
would mean guessing exactly the thing that was ambiguous. No foreign key, for
the same reason `user_id` has none — it points into one of three tables.

This revision sits **before** the gated staff-column drop, per the repository
rule: anything parented on `e6b2c8d40f17` could only ever run on a deploy that
had already accepted that drop.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c4d7e2f18a90'
down_revision: Union[str, Sequence[str], None] = 'b8e3d1a5c704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "WalletTransactions",
        sa.Column("wallet_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "idx_wallet_trans_owner",
        "WalletTransactions",
        ["wallet_owner_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_wallet_trans_owner", table_name="WalletTransactions")
    op.drop_column("WalletTransactions", "wallet_owner_id")
