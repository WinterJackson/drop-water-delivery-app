"""
Append-only ledger of empty-bottle movements between riders and vendors.

Why a ledger and not just counters
----------------------------------
`VendorRiderRegistry.pending_{10L,20L}_empties` are running balances, and they are
kept — they answer "how much does this rider owe?" in one indexed read. But a bare
counter cannot answer any of the questions that actually come up when a rider and a
vendor disagree: when was this incurred, on which order, who confirmed the return,
how many did they say they received. A decrement leaves no evidence.

So every movement writes a row here, and the counter is a denormalisation of the
sum. The ledger is the source of truth; the counter is the index.

Two other things the ledger buys:

* **Idempotency.** `uq_bottle_ledger_order_accrual` makes a second accrual for the
  same (order, capacity) a database error rather than a silent double-charge, which
  matters because delivery completion is retried by the offline queue.
* **Riders with no registry row.** Tier-2 radar dispatch deliberately offers orders
  to any nearby gig rider (`vendor_id=None`), so a rider can complete a delivery for
  a vendor they were never registered with. The old code guarded the accrual on the
  registry row existing, so those bottles left the vendor with no record at all.
  The ledger is keyed on (rider_id, vendor_id) directly and has no such dependency.
"""
from datetime import datetime, timezone
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class BottleLedgerEntryType(str, enum.Enum):
    #: Rider completed a quick_swap delivery; they now hold the vendor's empties.
    DELIVERY_ACCRUAL = "delivery_accrual"
    #: Vendor confirmed physical receipt of empties from the rider.
    VENDOR_RECEIPT = "vendor_receipt"
    #: Rider collected a customer's deposit bottles. They hold them now, and owe
    #: them to the store named on the return. Without this entry a returned
    #: bottle would leave the customer's count, leave the platform's liability,
    #: and appear nowhere — the deposit refunded against an asset the platform
    #: had stopped tracking.
    DEPOSIT_RETURN = "deposit_return"
    #: Manual correction (write-off, dispute resolution, opening balance).
    ADJUSTMENT = "adjustment"


class BottleLedgerEntry(Base):
    __tablename__ = "bottle_ledger_entries"
    __table_args__ = (
        # One accrual per order per bottle size. Delivery completion is retried
        # from the rider app's offline queue, so this is load-bearing.
        UniqueConstraint(
            "order_id",
            "capacity_litres",
            "entry_type",
            name="uq_bottle_ledger_order_accrual",
        ),
        CheckConstraint("quantity <> 0", name="ck_bottle_ledger_nonzero"),
        CheckConstraint("capacity_litres > 0", name="ck_bottle_ledger_capacity"),
        Index("idx_bottle_ledger_rider_vendor", "rider_id", "vendor_id"),
        Index("idx_bottle_ledger_vendor_created", "vendor_id", "created_at"),
        Index("idx_bottle_ledger_rider_created", "rider_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    rider_id = Column(
        UUID(as_uuid=True), ForeignKey("Deliverers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id = Column(
        UUID(as_uuid=True), ForeignKey("Vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Set for accruals; null for receipts and adjustments, which settle a balance
    #: rather than a specific order.
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("Orders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    capacity_litres = Column(Integer, nullable=False)

    #: Signed. Positive increases what the rider owes (accrual), negative reduces
    #: it (receipt). Summing this column per (rider, vendor, capacity) reproduces
    #: the registry counter exactly.
    quantity = Column(Integer, nullable=False)

    entry_type = Column(
        Enum(BottleLedgerEntryType, name="bottle_ledger_entry_type"),
        nullable=False,
        index=True,
    )

    #: Clerk id of whoever caused the entry — the vendor confirming receipt, or the
    #: rider completing the delivery. Not a FK: riders, vendors and admins all
    #: write here and they live in different tables.
    actor_clerk_id = Column(String, nullable=True)
    note = Column(String, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<BottleLedgerEntry {self.entry_type} {self.quantity:+d}"
            f" x{self.capacity_litres}L rider={self.rider_id} vendor={self.vendor_id}>"
        )
