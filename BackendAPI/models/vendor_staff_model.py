"""
Staff, modelled as a relationship rather than a column.

`Vendor.staff_clerk_id` held exactly one id, and it was `unique=True` — so a
store could have one staff member, that person could be staff of exactly one
store on the entire platform, and adding a second silently replaced the first.
The screen offering all this is called "Manage Staff".

It was also all-or-nothing. `get_current_vendor` admitted staff to every route
that was not owner-only, so handing the till to a weekend assistant handed them
the full catalogue, every order, the bottle ledger and the wallet balance. There
was no way to say "they can take orders but not reprice the products", which is
the ordinary case in a shop.

This table fixes both: many staff per store, one row per (store, person), and an
explicit capability set per row.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    String,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from db.session import Base

#: What a staff member may be trusted with, independently of the others.
#:
#: Deliberately coarse. A permission per endpoint is unusable by the person who
#: has to set it — the owner of a water shop — and permissions nobody
#: understands get granted wholesale, which is the state this replaces.
PERMISSION_MANAGE_ORDERS = "manage_orders"
PERMISSION_MANAGE_PRODUCTS = "manage_products"
PERMISSION_MANAGE_BOTTLES = "manage_bottles"
PERMISSION_VIEW_FINANCES = "view_finances"

ALL_PERMISSIONS = (
    PERMISSION_MANAGE_ORDERS,
    PERMISSION_MANAGE_PRODUCTS,
    PERMISSION_MANAGE_BOTTLES,
    PERMISSION_VIEW_FINANCES,
)

#: Human-readable, for the management screen and for refusal messages.
PERMISSION_LABELS = {
    PERMISSION_MANAGE_ORDERS: "Accept and update orders",
    PERMISSION_MANAGE_PRODUCTS: "Add and edit products",
    PERMISSION_MANAGE_BOTTLES: "Receive empty bottles",
    PERMISSION_VIEW_FINANCES: "See the wallet balance",
}

#: What a new staff member gets. Running the shop floor is the point of the
#: feature, so orders and bottles are on. Money is not: seeing the balance is a
#: decision the owner should make deliberately, not one they discover later.
DEFAULT_PERMISSIONS = [
    PERMISSION_MANAGE_ORDERS,
    PERMISSION_MANAGE_PRODUCTS,
    PERMISSION_MANAGE_BOTTLES,
]


def normalise_permissions(values) -> list[str]:
    """Keep only permissions this version knows about, in a stable order.

    A permission removed from the code must not keep granting anything, and an
    unknown string arriving from an older or newer client must not be stored.
    """
    requested = {str(v) for v in (values or [])}
    return [p for p in ALL_PERMISSIONS if p in requested]


class VendorStaff(Base):
    __tablename__ = "Vendor_Staff"
    __table_args__ = (
        # One row per person per store. Re-inviting someone updates their row
        # rather than creating a second grant that has to be revoked twice.
        UniqueConstraint("vendor_id", "clerk_id", name="uq_vendor_staff_member"),
        Index("idx_vendor_staff_clerk", "clerk_id", "revoked_at"),
        Index("idx_vendor_staff_vendor", "vendor_id", "revoked_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id", ondelete="CASCADE"), nullable=False)

    #: Null until the invited person signs in for the first time. The owner
    #: invites by email; we cannot know their Clerk subject before they exist.
    clerk_id = Column(String, nullable=True)
    #: What the owner typed. Kept so the list shows something recognisable, and
    #: so a pending invitation can be matched when that person does sign up.
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)

    permissions = Column(JSONB, nullable=False, default=list)

    #: This device, for this person, at this store. Replaces the single
    #: `Vendor.staff_push_token` column, which could only ever address one of
    #: them and went to whoever registered last.
    push_token = Column(String, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    #: Revocation is a soft delete: who had access to a store and when is part
    #: of the audit trail for every order and bottle movement they touched.
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    invited_by_clerk_id = Column(String, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    #: Set the first time this person actually signs in and is matched to the
    #: invitation, so the owner can see an invite that was never taken up.
    accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)

    vendor = relationship("Vendor", back_populates="staff", lazy="raise_on_sql")

    @property
    def is_pending(self) -> bool:
        """Invited, but has never signed in — so `clerk_id` is still unknown."""
        return self.clerk_id is None

    def has(self, permission: str) -> bool:
        return permission in (self.permissions or [])

    def revoke(self) -> None:
        self.is_active = False
        self.revoked_at = datetime.now(timezone.utc)


def live_grant():
    """The predicate for a grant that is *currently in force*.

    Two columns say whether someone may act on a store, and every query that
    decides access must read both. `revoke()` sets them together, so today they
    never disagree — but only `_resolve_access` spelled out both, while the
    other seven access queries checked `revoked_at` alone. The moment anything
    deactivates a member without revoking them (suspending a grant while an
    incident is investigated is the obvious one), the REST gate would refuse
    them and `staff_membership` — which backs `resolve_order_role` and
    `owns_entity`, i.e. the **websocket** path — would keep letting them stream
    the store's live orders.

    A predicate written out eight times is a predicate that will eventually be
    written seven ways. Spread into a query as `.where(*live_grant())`.

    Roster queries deliberately do **not** use this: `list_staff` and
    `_get_member` must still return a suspended member, or the owner cannot see
    them to restore them.
    """
    return (VendorStaff.revoked_at.is_(None), VendorStaff.is_active.is_(True))
