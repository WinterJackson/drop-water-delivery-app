
from sqlalchemy import Column, ForeignKey, Index, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID

from db.session import Base


class CustomerFirstDelivery(Base):
    """When a customer was acquired — recorded once, as it happens.

    The growth screen's cohorts were derived live, by grouping the entire
    `Orders` table:

        SELECT customer_id, MIN(date_trunc('month', created_at))
        FROM "Orders" WHERE order_status = 'delivered' GROUP BY customer_id

    The *semantics* of that query are deliberate and are preserved exactly here
    (see `services/customer_cohort_service.py`). The problem is only that it is
    recomputed on every page load, over all history, by design — so it is one of
    the few queries on the platform whose cost grows without bound and which no
    index can help, because it reads every delivered order there has ever been.
    At the target scale that is tens of seconds, holding a connection, on a screen
    somebody refreshes.

    Materialising it turns that into a join against one row per customer.

    Two columns and not one, on purpose:

    * `first_order_at` is the **exact** timestamp the `MIN()` was taken over, kept
      so the value can be re-derived, compared and repaired. Without it the table
      can only be trusted, never checked.
    * `cohort_month` is the truncation the report actually groups by. Stored
      rather than computed so the query is a plain equality on an indexed column.

    `order_id` records *which* order made the customer, which is the difference
    between a figure somebody can audit and a figure they have to believe.
    """

    __tablename__ = "Customer_First_Delivery"
    __table_args__ = (
        # The report groups by month and filters on it. One row per customer means
        # this index stays small — 50,000 rows at the target scale, against seven
        # million orders.
        Index("ix_customer_first_delivery_month", "cohort_month"),
    )

    #: The customer, and the primary key. One acquisition per customer is the
    #: whole invariant, and making it the key is what lets the write be a single
    #: idempotent `ON CONFLICT` statement rather than a read-then-write with a
    #: race in the middle.
    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("Users.id", ondelete="CASCADE"), primary_key=True
    )

    #: `Orders.created_at` of the earliest **delivered** order — when they
    #: ordered, not when it arrived. That is what the `MIN()` measured and what
    #: acquisition means here: the moment the customer chose the platform.
    first_order_at = Column(TIMESTAMP(timezone=True), nullable=False)

    #: `date_trunc('month', first_order_at)`.
    cohort_month = Column(TIMESTAMP(timezone=True), nullable=False)

    #: The order that acquired them. Nullable because the backfill can always
    #: identify the timestamp and cannot always identify a single order — two
    #: orders may share the earliest instant.
    order_id = Column(UUID(as_uuid=True), nullable=True)

    recorded_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
