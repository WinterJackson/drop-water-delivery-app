"""What the business spent getting customers, that its own database cannot see.

The platform can compute part of its acquisition cost **exactly**. Every order
carries `welcome_discount` — the share of a first bottle deposit the platform
absorbs — and that is real money, spent on acquisition, already recorded.

It cannot see the rest. Posters at the stage, a branded boda, Meta ads, a
referral paid in cash, the salary of whoever walked the estate signing people
up: none of that touches this database, and no amount of querying will find it.

A CAC built only from the half the platform can measure would be precise,
confident, and typically wrong by an order of magnitude — and wrong in the
dangerous direction. It would report that acquisition is cheap and payback is
fast, on a screen that looks authoritative because every figure in it is real.
Somebody would then spend against it.

So this table holds the other half, entered by an administrator per month and
per channel, and the two are **never blended into a single number without
saying which is which**. A month with nothing entered reports its measured cost
and says plainly that nothing was recorded — not a low CAC.

Rows are per (month, channel) and are edited in place rather than versioned:
unlike a pricing setting, nothing downstream has already been paid out against
a figure here, and "we got the invoice and it was 12,000 not 10,000" is the
ordinary case rather than an audit event. Who last touched it is recorded.
"""
import uuid

from sqlalchemy import (
    Column,
    Date,
    Index,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class AcquisitionSpend(Base):
    """One month's spend on one channel."""

    __tablename__ = "Acquisition_Spend"
    __table_args__ = (
        # One row per channel per month. Without this, "add spend" quietly
        # becomes "add more spend" on a double submit, and a CAC that doubles
        # overnight is indistinguishable from a bad month.
        UniqueConstraint("period_month", "channel", name="uq_acquisition_period_channel"),
        Index("ix_acquisition_spend_month", "period_month"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: Always the first of the month, in UTC. Stored as a date rather than a
    #: string so it sorts and ranges in SQL; normalised on write, because
    #: "2026-08-14" and "2026-08-01" meaning the same month is exactly how a
    #: table like this ends up with two rows for August.
    period_month = Column(Date, nullable=False)

    #: Free text, deliberately. A fixed enum of channels would be wrong within a
    #: month of anybody using it, and the value of this table is that somebody
    #: keeps filling it in.
    channel = Column(String(60), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)

    #: What the money bought. A figure with no note is unauditable a quarter
    #: later, when the person who entered it has moved on.
    note = Column(Text, nullable=True)

    #: The admin id. Nullable so a seed or a migration-inserted row is possible.
    recorded_by = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
