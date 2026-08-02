"""Business configuration the owners can change without a deploy.

Every number in here used to be a Python module constant in `order_service.py`
and `pricing_service.py`. Changing the retail service fee meant editing source,
opening a pull request, and waiting for Render to redeploy — so in practice it
never changed, and the "business model" was whatever a developer typed once.

Two properties make this safe to expose to an administrator:

* **The apps never see it.** They render `POST /api/cart/quote` verbatim, and
  that quote is computed server-side by `pricing_service`. A change here is
  therefore live in all three apps on the next quote, with no client release.
* **Orders snapshot their own economics.** `calculate_revenue_splits` runs at
  quote time and its results are written to the order's `vendor_commission`,
  `service_fee`, `rider_commission`, `platform_total`, `vendor_net` and
  `rider_net` columns; `settlement_service` pays out from those columns. So
  raising a commission today cannot retroactively change what is owed on an
  order placed yesterday — the money already agreed stays agreed.

Rows are versioned rather than overwritten. "What was the service fee in March,
when this order was placed?" is a question that gets asked after a customer
complains, and an UPDATE in place makes it unanswerable.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    String,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.session import Base


class PlatformSetting(Base):
    """One row per configuration key, holding the current value.

    `value` is JSONB rather than a typed column because the settings are
    heterogeneous — a rate, a flat fee, a list of peak-hour windows, a map of
    bottle capacity to deposit. A table per shape would be five tables and the
    same validation code.

    Validation lives in `platform_config_service`, not here: a CHECK constraint
    cannot express "the platinum rider commission must not exceed the standard
    one", and a value that passes the database and breaks the business is worse
    than one rejected with a sentence explaining why.
    """

    __tablename__ = "Platform_Settings"

    key = Column(String(64), primary_key=True)
    value = Column(JSONB, nullable=False)

    #: Bumped on every write. The pricing snapshot on an order records this, so
    #: a disputed total can be traced to the exact configuration that produced
    #: it rather than to "whatever the fees were around then".
    version = Column(Integer, nullable=False, default=1)

    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    #: Denormalised, and deliberately not a foreign key — the same reasoning as
    #: `Admin_Audit_Log`. Removing an administrator must not erase who set the
    #: platform's commission rate.
    updated_by_email = Column(String(255), nullable=True)


class PlatformSettingHistory(Base):
    """Append-only. Every change to every key, with the reason given.

    Separate from `Admin_Audit_Log` because this is read by the business, not by
    an auditor: "when did we last raise the delivery markup, and what was it
    before" is a question the owners ask, and making them filter an audit log of
    every document view to answer it is hostile.
    """

    __tablename__ = "Platform_Setting_History"
    __table_args__ = (
        Index("idx_setting_history_key_created", "key", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(64), nullable=False, index=True)
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=False)
    version = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    changed_by_email = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)


class SupportTicket(Base):
    """A customer, rider or vendor asking for help.

    `requester_type` + `requester_id` rather than three nullable foreign keys,
    matching `Notification` — the platform's three account tables have no common
    parent, and inventing one for this would be a migration across every row on
    the platform to serve a support queue.

    Deliberately **not** a chat system. A ticket has a body, a thread of replies,
    a status and an owner; anything more (typing indicators, attachments beyond
    a URL, SLA escalation trees) is a product in its own right and would be
    better bought than built.
    """

    __tablename__ = "Support_Tickets"
    __table_args__ = (
        # The queue view: open tickets, oldest first.
        Index("idx_ticket_status_created", "status", "created_at"),
        Index("idx_ticket_requester", "requester_type", "requester_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    requester_type = Column(String(16), nullable=False)  # customer | rider | vendor
    requester_id = Column(UUID(as_uuid=True), nullable=False)
    #: Captured at intake. The account's address can change, and a ticket that
    #: cannot be replied to six weeks later is not a ticket.
    requester_email = Column(String(255), nullable=True)

    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(32), nullable=False, default="other")
    #: low | normal | high | urgent
    priority = Column(String(16), nullable=False, default="normal")
    #: open | pending | resolved | closed
    status = Column(String(16), nullable=False, default="open", index=True)

    related_order_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    assigned_admin_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    assigned_admin_email = Column(String(255), nullable=True)

    #: The thread, oldest first: [{author, author_email, body, at, internal}].
    #: A list column rather than a child table because a ticket is read whole,
    #: always, and never queried by reply.
    messages = Column(JSONB, nullable=False, default=list)

    resolution = Column(Text, nullable=True)
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class BroadcastCampaign(Base):
    """A message sent to a segment of the platform.

    Recorded before it is sent, and updated as it goes out, so a campaign that
    dies halfway leaves evidence of how far it got. "We emailed everyone" is a
    claim; `sent_count` is a fact.
    """

    __tablename__ = "Broadcast_Campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: in_app | email | both
    channel = Column(String(16), nullable=False)
    #: customers | riders | vendors, optionally narrowed — see `broadcast_service`.
    audience = Column(String(32), nullable=False)
    audience_filter = Column(JSONB, nullable=True)

    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)

    #: queued | sending | sent | failed
    status = Column(String(16), nullable=False, default="queued", index=True)
    recipient_count = Column(Integer, nullable=False, default=0)
    sent_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    #: False for anything the recipient can mute. A campaign is marketing unless
    #: an administrator explicitly says it is not, because the failure mode of
    #: guessing the other way is a promotion that ignores someone's preferences.
    transactional = Column(Boolean, nullable=False, default=False)

    created_by_email = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
