"""unify rider wallet balance as the single spendable balance

Two problems this closes.

1. `Deliverers.wallet_balance` was `double precision`. It is money, it gates
   cash-order float, and float arithmetic on balances drifts. Now NUMERIC(10,2),
   matching Users and Vendors.

2. Payouts never debited any balance. Withdrawal eligibility was computed from a
   *derived* sum of `rider_net` over delivered orders, while cash-order float was
   checked against the *stored* `wallet_balance`. Nothing reconciled the two, so a
   rider could withdraw their earnings by M-Pesa B2C and then spend the same,
   still-untouched `wallet_balance` as float to accept a cash order — keeping the
   customer's cash while the platform funded the vendor's cut.

   From here `wallet_balance` is the single spendable balance: payouts debit it,
   earnings credit it, cash float is checked and debited against it.

The backfill subtracts every payout that has left (or is leaving) the platform.
Riders who exploited the gap will land negative. That is not a migration error —
it is a real debt, and a negative balance correctly blocks them from accepting
further cash orders until it is settled. Query them with:

    SELECT id, name, phone_number, wallet_balance
    FROM "Deliverers" WHERE wallet_balance < 0 ORDER BY wallet_balance;

Revision ID: d5f1c8a92e34
Revises: c4e2a1f83b76
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5f1c8a92e34"
down_revision: Union[str, Sequence[str], None] = "c4e2a1f83b76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "Deliverers",
        "wallet_balance",
        existing_type=sa.Float(),
        type_=sa.Numeric(10, 2),
        existing_nullable=False,
        postgresql_using="wallet_balance::numeric(10,2)",
    )

    # Reconcile historical payouts against the balance they never debited.
    # 'pending' and 'processing' are included: that money is committed to leaving.
    for table, provider_type in (("Deliverers", "rider"), ("Vendors", "vendor")):
        op.execute(
            sa.text(
                f"""
                UPDATE "{table}" t
                SET wallet_balance = t.wallet_balance - COALESCE(p.total, 0)
                FROM (
                    SELECT provider_id, SUM(amount) AS total
                    FROM payouts
                    WHERE provider_type = '{provider_type}'
                      AND status IN ('pending', 'processing', 'completed')
                    GROUP BY provider_id
                ) p
                WHERE p.provider_id = t.id
                """
            )
        )


def downgrade() -> None:
    # Put the payouts back before widening the type, so the arithmetic happens
    # while the column can still hold the result.
    for table, provider_type in (("Deliverers", "rider"), ("Vendors", "vendor")):
        op.execute(
            sa.text(
                f"""
                UPDATE "{table}" t
                SET wallet_balance = t.wallet_balance + COALESCE(p.total, 0)
                FROM (
                    SELECT provider_id, SUM(amount) AS total
                    FROM payouts
                    WHERE provider_type = '{provider_type}'
                      AND status IN ('pending', 'processing', 'completed')
                    GROUP BY provider_id
                ) p
                WHERE p.provider_id = t.id
                """
            )
        )

    op.alter_column(
        "Deliverers",
        "wallet_balance",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Float(),
        existing_nullable=False,
    )
