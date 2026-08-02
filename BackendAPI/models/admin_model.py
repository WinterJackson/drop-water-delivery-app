"""Platform administrators, and the record of what they did.

Admin access used to be `ADMIN_CLERK_IDS`, a comma-separated environment
variable compared against the caller's Clerk subject. That has three problems
that matter once more than one person runs the business:

* it cannot express *roles* — everyone listed could do everything, including
  approve payouts and read every customer's national ID;
* it cannot be **revoked** without a redeploy, which is the wrong latency for
  somebody's last day;
* nothing it permits is **attributable**. Two admins share one capability set
  and leave no trace, so "who approved this payout" has no answer.

`Admin_Users` replaces it, and `Admin_Audit_Log` answers the third point.

The shape deliberately mirrors `models/vendor_staff_model.py`: same invite-by-
email flow, same nullable `clerk_id` until first sign-in, same soft revoke. One
concept, modelled once, so there is no second set of rules to learn.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

from db.session import Base

# ── Capabilities ──────────────────────────────────────────────────────────
#
# Namespaced `domain.action`. Reading and acting are always separate, and
# anything that exposes personal data or moves money is separate again — those
# are the two grants you want to be able to withhold from someone who otherwise
# needs full access to do their job.

PERM_RIDERS_READ = "riders.read"
PERM_RIDERS_KYC_REVIEW = "riders.kyc_review"
PERM_RIDERS_SUSPEND = "riders.suspend"

PERM_VENDORS_READ = "vendors.read"
PERM_VENDORS_APPROVE = "vendors.approve"
PERM_VENDORS_SUSPEND = "vendors.suspend"

PERM_CUSTOMERS_READ = "customers.read"
PERM_CUSTOMERS_SUSPEND = "customers.suspend"
PERM_CUSTOMERS_ERASE = "customers.erase"

PERM_ORDERS_READ = "orders.read"
PERM_ORDERS_INTERVENE = "orders.intervene"

PERM_FINANCE_READ = "finance.read"
PERM_FINANCE_PAYOUT_APPROVE = "finance.payout_approve"
PERM_FINANCE_REFUND_APPROVE = "finance.refund_approve"

PERM_DISPUTES_READ = "disputes.read"
PERM_DISPUTES_RESOLVE = "disputes.resolve"

PERM_ANALYTICS_READ = "analytics.read"

#: Seeing an unmasked national ID, M-Pesa number or ID number. Held separately
#: from the read permissions on purpose: support staff need to find a rider and
#: check their status far more often than they need to see the document itself,
#: and the console should let you grant the first without the second.
PERM_PII_VIEW = "pii.view"

#: Downloading a list. Separate from reading it on screen — an export leaves the
#: building, and the audit row records how many rows went with it.
PERM_DATA_EXPORT = "data.export"

#: Answering a customer, rider or vendor. Its own grant because support is the
#: one job that is routinely staffed by people who should touch nothing else.
PERM_SUPPORT_READ = "support.read"
PERM_SUPPORT_RESPOND = "support.respond"

#: Messaging a whole segment of the platform at once. Separate from
#: `support.respond` because the blast radius is different by three orders of
#: magnitude: a bad reply annoys one person, a bad broadcast annoys everyone.
PERM_BROADCAST_SEND = "broadcast.send"

#: Crediting or debiting somebody's wallet by hand. Deliberately not folded into
#: `finance.payout_approve`: approving a withdrawal moves money the platform
#: already owed, while an adjustment creates the obligation out of nothing, and
#: it is the single most abusable action in this console.
PERM_FINANCE_ADJUST = "finance.adjust"

#: Seeing where riders, vendors and customers actually are. Location history is
#: personal data even in aggregate, so it is not implied by `riders.read`.
PERM_GEO_VIEW = "geo.view"

PERM_ADMINS_MANAGE = "admins.manage"
PERM_SETTINGS_MANAGE = "settings.manage"

#: Order matters: it is the storage order and therefore the display order.
ALL_PERMISSIONS = (
    PERM_RIDERS_READ,
    PERM_RIDERS_KYC_REVIEW,
    PERM_RIDERS_SUSPEND,
    PERM_VENDORS_READ,
    PERM_VENDORS_APPROVE,
    PERM_VENDORS_SUSPEND,
    PERM_CUSTOMERS_READ,
    PERM_CUSTOMERS_SUSPEND,
    PERM_CUSTOMERS_ERASE,
    PERM_ORDERS_READ,
    PERM_ORDERS_INTERVENE,
    PERM_FINANCE_READ,
    PERM_FINANCE_PAYOUT_APPROVE,
    PERM_FINANCE_REFUND_APPROVE,
    PERM_FINANCE_ADJUST,
    PERM_DISPUTES_READ,
    PERM_DISPUTES_RESOLVE,
    PERM_SUPPORT_READ,
    PERM_SUPPORT_RESPOND,
    PERM_BROADCAST_SEND,
    PERM_GEO_VIEW,
    PERM_ANALYTICS_READ,
    PERM_PII_VIEW,
    PERM_DATA_EXPORT,
    PERM_ADMINS_MANAGE,
    PERM_SETTINGS_MANAGE,
)

PERMISSION_LABELS = {
    PERM_RIDERS_READ: "View riders",
    PERM_RIDERS_KYC_REVIEW: "Approve or reject rider KYC",
    PERM_RIDERS_SUSPEND: "Suspend or reinstate riders",
    PERM_VENDORS_READ: "View vendors",
    PERM_VENDORS_APPROVE: "Approve vendor registrations",
    PERM_VENDORS_SUSPEND: "Suspend or reinstate vendors",
    PERM_CUSTOMERS_READ: "View customers",
    PERM_CUSTOMERS_SUSPEND: "Suspend or reinstate customers",
    PERM_CUSTOMERS_ERASE: "Erase a customer's personal data",
    PERM_ORDERS_READ: "View orders",
    PERM_ORDERS_INTERVENE: "Cancel, refund or reassign orders",
    PERM_FINANCE_READ: "View revenue, payouts and wallets",
    PERM_FINANCE_PAYOUT_APPROVE: "Approve payouts",
    PERM_FINANCE_REFUND_APPROVE: "Approve refunds",
    PERM_FINANCE_ADJUST: "Credit or debit a wallet by hand",
    PERM_DISPUTES_READ: "View bottle disputes",
    PERM_DISPUTES_RESOLVE: "Resolve bottle disputes",
    PERM_SUPPORT_READ: "View support tickets",
    PERM_SUPPORT_RESPOND: "Reply to and resolve support tickets",
    PERM_BROADCAST_SEND: "Message everyone on the platform",
    PERM_GEO_VIEW: "View rider, vendor and demand locations on a map",
    PERM_ANALYTICS_READ: "View business analytics",
    PERM_PII_VIEW: "Reveal identity documents and payout details",
    PERM_DATA_EXPORT: "Export data to CSV",
    PERM_ADMINS_MANAGE: "Manage administrators and view the audit log",
    PERM_SETTINGS_MANAGE: "Change platform settings and pricing",
}

#: Grouped for the management UI, so 21 checkboxes read as six decisions.
PERMISSION_GROUPS = (
    ("Riders", (PERM_RIDERS_READ, PERM_RIDERS_KYC_REVIEW, PERM_RIDERS_SUSPEND)),
    ("Vendors", (PERM_VENDORS_READ, PERM_VENDORS_APPROVE, PERM_VENDORS_SUSPEND)),
    ("Customers", (PERM_CUSTOMERS_READ, PERM_CUSTOMERS_SUSPEND, PERM_CUSTOMERS_ERASE)),
    ("Orders & disputes", (PERM_ORDERS_READ, PERM_ORDERS_INTERVENE, PERM_DISPUTES_READ, PERM_DISPUTES_RESOLVE)),
    ("Finance", (PERM_FINANCE_READ, PERM_FINANCE_PAYOUT_APPROVE, PERM_FINANCE_REFUND_APPROVE, PERM_FINANCE_ADJUST)),
    ("Support & messaging", (PERM_SUPPORT_READ, PERM_SUPPORT_RESPOND, PERM_BROADCAST_SEND)),
    ("Platform", (PERM_ANALYTICS_READ, PERM_GEO_VIEW, PERM_PII_VIEW, PERM_DATA_EXPORT, PERM_ADMINS_MANAGE, PERM_SETTINGS_MANAGE)),
)

# ── Role presets ──────────────────────────────────────────────────────────
#
# A preset is a *starting point*, expanded into `permissions` at the moment of
# assignment. The role name is kept only for display and filtering; it is never
# consulted when deciding whether an action is allowed.
#
# Storing the expansion rather than the name is what makes a preset safe to
# edit: narrowing `support` next quarter must not silently narrow the people
# already doing that job, and widening it must not silently widen them either.

ROLE_SUPER_ADMIN = "super_admin"
ROLE_OPERATIONS = "operations"
ROLE_FINANCE = "finance"
ROLE_SUPPORT = "support"
ROLE_ANALYST = "analyst"

ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    ROLE_SUPER_ADMIN: ALL_PERMISSIONS,
    ROLE_OPERATIONS: (
        PERM_RIDERS_READ, PERM_RIDERS_KYC_REVIEW, PERM_RIDERS_SUSPEND,
        PERM_VENDORS_READ, PERM_VENDORS_APPROVE, PERM_VENDORS_SUSPEND,
        PERM_CUSTOMERS_READ,
        PERM_ORDERS_READ, PERM_ORDERS_INTERVENE,
        PERM_DISPUTES_READ, PERM_DISPUTES_RESOLVE,
        PERM_SUPPORT_READ, PERM_SUPPORT_RESPOND,
        PERM_GEO_VIEW,
        PERM_ANALYTICS_READ,
        PERM_PII_VIEW,
    ),
    ROLE_FINANCE: (
        PERM_FINANCE_READ, PERM_FINANCE_PAYOUT_APPROVE, PERM_FINANCE_REFUND_APPROVE,
        # Not `finance.adjust`. Creating a balance out of nothing is a super
        # admin decision even within the finance team — it is the one action
        # here with no upstream obligation to check it against.
        PERM_VENDORS_READ, PERM_RIDERS_READ, PERM_ORDERS_READ,
        PERM_ANALYTICS_READ, PERM_DATA_EXPORT,
        PERM_PII_VIEW,  # a payout cannot be checked without seeing the destination
    ),
    #: Deliberately without `pii.view` and without any finance permission.
    #: Support answers "where is my order" hundreds of times a day; that job
    #: does not require the ability to read a national ID.
    ROLE_SUPPORT: (
        PERM_RIDERS_READ, PERM_VENDORS_READ, PERM_CUSTOMERS_READ,
        PERM_ORDERS_READ, PERM_ORDERS_INTERVENE,
        PERM_DISPUTES_READ,
        PERM_SUPPORT_READ, PERM_SUPPORT_RESPOND,
        #: Answering "where is my rider" is the single most common support
        #: question on a delivery platform, and it cannot be answered without
        #: this. It is still withheld from the analyst preset.
        PERM_GEO_VIEW,
    ),
    #: Answers business questions without being able to change anything, or to
    #: identify anybody.
    ROLE_ANALYST: (PERM_ANALYTICS_READ, PERM_ORDERS_READ),
}

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "Super admin",
    ROLE_OPERATIONS: "Operations",
    ROLE_FINANCE: "Finance",
    ROLE_SUPPORT: "Support",
    ROLE_ANALYST: "Analyst",
}

ROLE_DESCRIPTIONS = {
    ROLE_SUPER_ADMIN: "Full access, including managing other administrators.",
    ROLE_OPERATIONS: "Runs the day to day: KYC, vendors, orders and disputes.",
    ROLE_FINANCE: "Payouts, refunds, revenue and reconciliation.",
    ROLE_SUPPORT: "Handles customer and rider queries. No financial or identity access.",
    ROLE_ANALYST: "Read-only business analytics. No personal data, no actions.",
}


def normalise_permissions(values) -> list[str]:
    """Keep only permissions this version defines, in a stable order.

    A capability deleted from the code must stop granting anything the moment it
    is deleted, including for rows written while it still existed. Storing
    whatever arrived would let a removed permission keep working for anyone
    whose row still lists it.
    """
    requested = {str(v) for v in (values or [])}
    return [p for p in ALL_PERMISSIONS if p in requested]


def permissions_for_role(role: str) -> list[str]:
    """Expand a preset. Unknown role → no permissions, never a default grant."""
    return list(ROLE_PRESETS.get(role, ()))


class AdminUser(Base):
    __tablename__ = "Admin_Users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_admin_users_email"),
        Index("idx_admin_users_clerk", "clerk_id", "revoked_at"),
        Index("idx_admin_users_active", "revoked_at", "is_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: Null until this person signs in for the first time. Admins are invited by
    #: email, and their Clerk subject does not exist until they accept.
    clerk_id = Column(String, nullable=True)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)

    #: The preset this was created from. Display and filtering only — authority
    #: lives entirely in `permissions`.
    role = Column(String, nullable=False, default=ROLE_SUPPORT)
    permissions = Column(JSONB, nullable=False, default=list)

    is_active = Column(Boolean, nullable=False, default=True)
    #: Soft revoke. The audit log references this row, and a deleted admin would
    #: leave every action they took pointing at nothing.
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)

    invited_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=True)

    @property
    def is_pending(self) -> bool:
        return self.clerk_id is None

    def has(self, permission: str) -> bool:
        return permission in (self.permissions or [])

    def revoke(self) -> None:
        self.is_active = False
        self.revoked_at = datetime.now(timezone.utc)


class AdminAuditLog(Base):
    """Append-only. Every mutation, and every reveal of personal data.

    Written in the same transaction as the change it describes, so the two
    cannot disagree: if the audit insert fails, the action is rolled back with
    it. An audit trail that can be skipped silently is worse than no audit
    trail, because it will be relied on.

    There is no update or delete route for this table anywhere in the codebase.
    """

    __tablename__ = "Admin_Audit_Log"
    __table_args__ = (
        Index("idx_admin_audit_admin", "admin_id", "created_at"),
        Index("idx_admin_audit_target", "target_type", "target_id"),
        Index("idx_admin_audit_action", "action", "created_at"),
        # The default view is "everything, newest first", and it is the one query
        # that runs on every open of the audit screen.
        Index("idx_admin_audit_created", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    admin_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    #: Denormalised on purpose. The log has to stay readable after an admin row
    #: is revoked or an email is reassigned, and joining to a mutable table for
    #: an immutable record would let history change retroactively.
    admin_email = Column(String, nullable=False)

    #: Dotted, matching the capability namespace: `rider.kyc.approve`,
    #: `payout.approve`, `customer.pii.view`.
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)

    #: Changed fields only — a full row snapshot on every edit would copy the
    #: PII we are trying to control into a table that is never redacted.
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)

    #: Required for destructive actions and for every PII reveal. "Who looked at
    #: this rider's ID" is only half the question; the other half is "why".
    reason = Column(Text, nullable=True)

    ip = Column(INET, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
