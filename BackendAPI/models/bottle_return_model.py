"""A customer handing bottles back, and getting their deposit returned.

Until now the only way a deposit could come back was an administrator typing it
into the console under `finance.adjust` — a grant no preset but super admin
holds. So in practice a deposit was refundable in principle and unreturnable in
fact, which makes it not a deposit but a price.

## Why two confirmations, and why they are not symmetric

The bottles are a physical asset moving between two people, and each of them can
be wrong or dishonest in a different way. One tap is not enough evidence to move
money.

Both sides state a **count**. Agreement settles it. Disagreement is a dispute a
human looks at — never a silent split of the difference, because a rider who
learns that claiming one fewer bottle each time costs nobody anything will do
exactly that.

The asymmetry is the load-bearing part:

* **The rider confirmed and the customer did not** — settle it after the timer,
  at the rider's count. The rider has attested to taking possession of a
  physical asset and is on the hook for it through `bottle_ledger_service`;
  their word against their own interest is good evidence. Making the customer
  chase their own money because a phone died would be punishing them for our
  process.
* **The customer confirmed and the rider did not** — this **never** auto-settles.
  It goes to a human. A customer's unilateral claim that they handed over six
  bottles is exactly the fraud this exists to prevent, and a timer that pays it
  out is a timer that pays anybody who waits.

So a timeout resolves in favour of whichever side put an asset at risk, which is
the only side that has anything to lose by lying.

## Where the bottles go

A returned bottle does not evaporate. The rider now holds it, and
`bottle_ledger_service` is what says so — `vendor_id` records who it is owed to.
When the return rides along with a delivery that is the order's vendor; on a
standalone pickup the rider names the store they will hand them to, because they
have to hand them somewhere regardless.
"""
import enum
import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class BottleReturnStatus(str, enum.Enum):
    #: The customer has asked for a pickup. No rider yet.
    REQUESTED = "requested"
    #: A rider has taken it on, either standalone or riding with a delivery.
    ASSIGNED = "assigned"
    #: One side has stated a count and is waiting on the other.
    AWAITING_COUNTERPARTY = "awaiting_counterparty"
    #: Both agreed. The deposit has been credited and the ledger written.
    SETTLED = "settled"
    #: The counts differ, or the customer confirmed alone. A human decides.
    DISPUTED = "disputed"
    #: Nobody acted inside the window. No money moved.
    EXPIRED = "expired"
    #: Withdrawn by the customer before anyone collected anything.
    CANCELLED = "cancelled"


#: The states from which a request may still move. Anything else is final, and
#: `settle` refuses so a retried tap cannot pay twice.
OPEN_STATUSES = (
    BottleReturnStatus.REQUESTED,
    BottleReturnStatus.ASSIGNED,
    BottleReturnStatus.AWAITING_COUNTERPARTY,
)


class BottleReturnRequest(Base):
    """One pickup of one customer's deposit-bearing bottles."""

    __tablename__ = "Bottle_Return_Requests"
    __table_args__ = (
        # The customer's own list, newest first.
        Index("idx_bottle_return_customer", "customer_id", "created_at"),
        # The rider's task list, and the sweep's queue.
        Index("idx_bottle_return_status", "status", "created_at"),
        Index("idx_bottle_return_rider", "rider_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("Users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: Null until somebody takes it on.
    rider_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    #: Who the bottles will be handed to. Required before settlement — a
    #: returned bottle the ledger cannot attribute is a bottle the platform has
    #: stopped counting.
    vendor_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    #: Set when the pickup rides along with a delivery rather than standing alone.
    order_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    status = Column(
        String(24), nullable=False,
        default=BottleReturnStatus.REQUESTED.value, index=True,
    )

    #: How this return came about — `collection`, `console` or `dormancy`.
    #:
    #: **Every** path that gives a deposit back writes one of these rows, and
    #: that is what makes the nightly reconciliation exact. The first draft only
    #: recorded rider collections, so the console's manual return and the
    #: dormancy conversion each reduced the liability with nothing on the other
    #: side of the entry — and the book would have reported permanent drift from
    #: the first one onwards, growing, with no way to tell it from a real defect.
    origin = Column(String(16), nullable=False, default="collection", index=True)

    #: What the customer asked to return when they raised it. Advisory — the
    #: money follows the two confirmed counts, not this.
    bottles_requested = Column(Integer, nullable=False, default=0)
    #: What each side says actually changed hands. Null means "has not said".
    bottles_stated_by_customer = Column(Integer, nullable=True)
    bottles_stated_by_rider = Column(Integer, nullable=True)
    #: The count the money was actually paid on.
    bottles_settled = Column(Integer, nullable=True)

    customer_confirmed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    rider_confirmed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    #: When an unanswered request stops waiting. Read by the sweep; stored
    #: rather than computed so changing the setting cannot retroactively expire
    #: a request somebody is in the middle of.
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True, index=True)

    #: What was actually credited, in shillings. Recorded on the request so the
    #: customer's history answers "how much did I get back for those" without
    #: re-deriving it from a deposit balance that has moved on since.
    amount_refunded = Column(Numeric(10, 2), nullable=True)
    settled_at = Column(TIMESTAMP(timezone=True), nullable=True)

    #: Why it is disputed, or why it expired. Shown to the customer verbatim.
    resolution_note = Column(Text, nullable=True)
    resolved_by_email = Column(String(255), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
