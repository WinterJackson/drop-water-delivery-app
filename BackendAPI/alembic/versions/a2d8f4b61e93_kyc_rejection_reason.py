"""tell a rejected rider what was wrong

The KYC reviewer types a reason and it went into a push notification and nowhere
else. `VerificationWall` prefills the rider's previous answers, so a rejected
rider who dismissed the notification — or never received it, push being
best-effort — returns to a form that looks correct and offers no clue what
failed. The usual outcome is resubmitting the same document, which costs another
review cycle and makes the queue longer for everyone.

`kyc_rejection_reason` is cleared on resubmission so a stale reason cannot
outlive the problem it described. `kyc_reviewed_at` is what the queue sorts and
ages by; a rider waiting three days is an SLA breach, not just a row.

Revision ID: a2d8f4b61e93
Revises: f1a7c3e59d82
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a2d8f4b61e93'
down_revision: Union[str, Sequence[str], None] = 'f1a7c3e59d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("Deliverers", sa.Column("kyc_rejection_reason", sa.Text(), nullable=True))
    op.add_column("Deliverers", sa.Column("kyc_reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True))
    # The review queue is "pending, oldest first" on every open.
    op.create_index(
        "idx_deliverers_kyc_queue",
        "Deliverers",
        ["kyc_status", "kyc_reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_deliverers_kyc_queue", table_name="Deliverers")
    op.drop_column("Deliverers", "kyc_reviewed_at")
    op.drop_column("Deliverers", "kyc_rejection_reason")
