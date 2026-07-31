"""normalise wallet transaction amounts to a signed convention

`WalletTransaction.amount` was stored as a positive magnitude, with direction
implied by `transaction_type`. That worked only while every type moved money one
way. It no longer does: `order_payment` now debits a rider settling a cash order
out of their float *and* credits a rider their delivery earnings. A type alone
cannot say which, and both mobile apps were deriving the sign from a hardcoded
type allow-list that listed `order_payment` as a credit — so a rider's float
deduction would have rendered as income.

From here `amount` is signed: negative means money left the wallet. Summing a
user's rows reproduces their balance movement exactly, whatever the type.

Historical rows are unambiguous, so they can be normalised:

  top_up, refund              credits  → +ABS
  withdrawal, commission_...  debits   → -ABS
  order_payment               debits   → -ABS

`order_payment` is safe to treat as a debit across all existing rows because the
only writer before this change was the customer wallet-credit path in
`order_service`; rider and vendor settlement rows did not exist at all (that was
the missing-ledger defect). Using ABS makes this idempotent and safe to re-run
against rows the new code has already written signed.

Revision ID: e7b3d0c56a19
Revises: d5f1c8a92e34
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3d0c56a19"
down_revision: Union[str, Sequence[str], None] = "d5f1c8a92e34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREDITS = ("top_up", "refund")
_DEBITS = ("withdrawal", "commission_deduction", "order_payment")


def _quoted(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE "WalletTransactions"
            SET amount = ABS(amount)
            WHERE transaction_type::text IN ({_quoted(_CREDITS)})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE "WalletTransactions"
            SET amount = -ABS(amount)
            WHERE transaction_type::text IN ({_quoted(_DEBITS)})
            """
        )
    )


def downgrade() -> None:
    # Back to positive magnitudes; the direction lives in transaction_type again.
    op.execute(sa.text('UPDATE "WalletTransactions" SET amount = ABS(amount)'))
