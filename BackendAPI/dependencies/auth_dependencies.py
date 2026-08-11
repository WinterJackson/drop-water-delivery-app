from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.dependencies import get_db
from models.deliverer_model import Deliverer
from models.user_model import User
from models.vendor_model import Vendor
from utils.verify_user_token import get_current_user
from sqlalchemy import select, or_


async def get_current_customer(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    clerk_id = user["sub"]
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered customer.")
    return user


async def get_current_vendor(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Anyone who can reach *some* store — the owner, or staff they added.

    Correct only for `GET /api/vendor/stores`, which exists to enumerate what
    the caller can reach and therefore cannot be scoped to one of them. Every
    other vendor route resolves a specific store through `get_store_access` and
    a permission.

    Deliberately not `scalar_one_or_none()`. An owner may hold several stores,
    and `scalar_one_or_none` raises `MultipleResultsFound` on the second one —
    which turned every authenticated vendor endpoint into a 500 the moment an
    owner opened a branch.
    """
    from models.vendor_staff_model import VendorStaff

    clerk_id = user["sub"]
    owned = await db.execute(select(Vendor.id).where(Vendor.clerk_id == clerk_id).limit(1))
    if owned.scalars().first():
        return user

    staffed = await db.execute(
        select(VendorStaff.id)
        .where(VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None))
        .limit(1)
    )
    if staffed.scalars().first():
        return user

    raise HTTPException(status_code=403, detail="Access denied. Must be a registered vendor.")


async def get_vendor_owner(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The owner of a store, never a staff member.

    Staff used to be indistinguishable from owners on the server. `role` was
    computed for display only — `"owner" if vendor.clerk_id == clerk_id else
    "staff"` — and every restriction lived in a `router.replace()` inside a
    React component. A staff member calling the API directly could rename the
    business, move its location, change its payment methods, or take it offline.

    Worst of all, `payout_service._get_provider_details` resolved a payee with
    the same staff-inclusive lookup and disbursed by M-Pesa B2C to a phone
    number taken from the request body — so a shop assistant could withdraw the
    store's balance to their own number. `wallet_service.resolve_wallet_owner`
    already matched on `clerk_id` alone and refused them; the two money paths
    disagreed, and the permissive one was the one that paid out.

    The `detail` is structured so the client can tell "you are staff" apart from
    "you are not a vendor at all" without string-matching a sentence.
    """
    clerk_id = user["sub"]
    result = await db.execute(
        select(Vendor)
        .where(Vendor.clerk_id == clerk_id)
        .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        .limit(1)
    )
    if result.scalars().first():
        return user

    # Distinguish a staff member from a stranger: the first is a real account
    # being told what it may not do, the second has no business here at all.
    from models.vendor_staff_model import VendorStaff

    staff = await db.execute(
        select(VendorStaff.id)
        .where(VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None))
        .limit(1)
    )
    if staff.scalars().first():
        raise HTTPException(
            status_code=403,
            detail={
                "type": "owner_only",
                "message": "Only the store owner can do this. Ask the owner of this store to make the change.",
            },
        )

    raise HTTPException(status_code=403, detail="Access denied. Must be a registered vendor.")


# ── Which store, and on whose behalf? ────────────────────────────────────────
# A vendor account may hold several stores. `GET /api/vendor/stores` returns them
# all and the app has a switcher, but every endpoint used to act on whichever row
# the database handed back first — the switcher changed a label and nothing else
# (`// Future: refetch dashboard with new store context`).
#
# The store is named by the caller in an `X-Store-Id` header and validated
# against the stores that caller can actually reach. It is never trusted as an
# identity: the header selects among grants the token already has, it cannot
# reach one it does not.
#
# *Who* is asking matters as much as *which* store. An owner may do anything; a
# staff member may do what their `VendorStaff.permissions` allow. Both arrive as
# a `StoreAccess`, so a route can never accidentally treat the two alike.


@dataclass(frozen=True)
class StoreAccess:
    """The resolved answer to "who is acting on which store, and may they?"."""

    vendor: Vendor
    clerk_id: str
    is_owner: bool
    permissions: frozenset[str]
    #: The `VendorStaff` row id when this is a staff member, else None. Written
    #: into audit trails so "who confirmed this" survives a revocation.
    staff_id: UUID | None = None

    @property
    def role(self) -> str:
        return "owner" if self.is_owner else "staff"

    def may(self, permission: str) -> bool:
        return self.is_owner or permission in self.permissions


def _permission_denied(permission: str) -> HTTPException:
    """403 the client can route on without string-matching a sentence."""
    from models.vendor_staff_model import PERMISSION_LABELS

    label = PERMISSION_LABELS.get(permission, permission.replace("_", " "))
    return HTTPException(
        status_code=403,
        detail={
            "type": "permission_required",
            "permission": permission,
            "message": f"You don't have permission to {label.lower()} for this store. Ask the owner to enable it.",
        },
    )


async def _resolve_access(
    db: AsyncSession, clerk_id: str, requested: str | None, owner_only: bool
) -> StoreAccess:
    """Resolve the store and the caller's standing on it, or raise.

    `requested` is caller-supplied and untrusted; the WHERE clauses below are
    what make it safe. A store the caller cannot reach answers 404, not 403 —
    confirming an id exists is itself a small leak, and the caller has no
    legitimate way to tell the two apart.
    """
    from models.vendor_staff_model import VendorStaff

    store_id: UUID | None = None
    if requested:
        try:
            store_id = UUID(str(requested))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid store id.")

    # Ownership first. Someone can own store A *and* be staff of store B, so the
    # two must be resolved separately against the store actually named — an
    # owner gate composed with a store resolver would let them act on B.
    owned = select(Vendor).where(Vendor.clerk_id == clerk_id)
    if store_id:
        owned = owned.where(Vendor.id == store_id)
    # `created_at` is NULL on rows predating that column, and Postgres sorts
    # NULLs last for ASC; the id tiebreak keeps the answer stable either way.
    result = await db.execute(
        owned.order_by(Vendor.created_at.asc(), Vendor.id.asc()).limit(1)
    )
    vendor = result.scalars().first()
    if vendor is not None:
        return StoreAccess(
            vendor=vendor,
            clerk_id=clerk_id,
            is_owner=True,
            permissions=frozenset(),  # unused: `may()` short-circuits for owners
        )

    if owner_only:
        # No owned store. Distinguish a staff member — a real account being told
        # what it may not do — from someone with no vendor relationship at all.
        staff_probe = select(VendorStaff.id).where(
            VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None)
        )
        if store_id:
            staff_probe = staff_probe.where(VendorStaff.vendor_id == store_id)
        if (await db.execute(staff_probe.limit(1))).scalars().first():
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "owner_only",
                    "message": "Only the store owner can do this. Ask the owner of this store to make the change.",
                },
            )
        if store_id:
            raise HTTPException(status_code=404, detail="Store not found.")
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered vendor.")

    staff_query = (
        select(VendorStaff, Vendor)
        .join(Vendor, Vendor.id == VendorStaff.vendor_id)
        .where(
            VendorStaff.clerk_id == clerk_id,
            VendorStaff.revoked_at.is_(None),
            VendorStaff.is_active.is_(True),
        )
    )
    if store_id:
        staff_query = staff_query.where(Vendor.id == store_id)
    row = (
        await db.execute(
            staff_query.order_by(Vendor.created_at.asc(), Vendor.id.asc()).limit(1)
        )
    ).first()

    if row is not None:
        staff, vendor = row
        return StoreAccess(
            vendor=vendor,
            clerk_id=clerk_id,
            is_owner=False,
            permissions=frozenset(staff.permissions or []),
            staff_id=staff.id,
        )

    if store_id:
        raise HTTPException(status_code=404, detail="Store not found.")
    raise HTTPException(status_code=403, detail="Access denied. Must be a registered vendor.")


async def get_store_access(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    store_id: str | None = Query(default=None, description="Store to act on; overrides X-Store-Id"),
) -> StoreAccess:
    """The store this request acts on, and the caller's standing on it.

    Grants nothing beyond *reaching* the store. Any route that changes something
    must additionally require a permission — see `require_permission`.
    """
    return await _resolve_access(db, user["sub"], store_id or x_store_id, owner_only=False)


async def get_active_store(
    access: StoreAccess = Depends(get_store_access),
) -> Vendor:
    """The `Vendor` row this request acts on — owner or staff.

    For reads that every member of a store may make. Routes take the resolved
    row rather than re-querying, so they cannot drift from the row the gate
    approved.
    """
    return access.vendor


def require_permission(permission: str):
    """Dependency factory: the store, if the caller may do `permission` on it.

    Owners always may. Staff need it in `VendorStaff.permissions`, which is the
    whole point of the table — handing someone the till used to hand them the
    catalogue, the bottle ledger and the balance as well, because access was a
    single nullable column with nothing to say about scope.
    """

    async def _dependency(access: StoreAccess = Depends(get_store_access)) -> Vendor:
        if not access.may(permission):
            raise _permission_denied(permission)
        return access.vendor

    return _dependency


async def get_owned_store(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    store_id: str | None = Query(default=None, description="Store to act on; overrides X-Store-Id"),
) -> Vendor:
    """The store this request acts on, and the caller owns it.

    Stricter than an owner check composed with a store resolver: someone can own
    store A *and* be staff of store B, and that pair would pass an owner gate and
    then act on B. Ownership is checked against the resolved row.
    """
    access = await _resolve_access(db, user["sub"], store_id or x_store_id, owner_only=True)
    return access.vendor


async def staff_membership(db: AsyncSession, clerk_id: str, vendor_id: UUID):
    """The caller's live staff row for this store, or None.

    Used where a `Vendor` row is already in hand — the websocket and order-role
    helpers below — and by `clear_push_token`.
    """
    from models.vendor_staff_model import VendorStaff

    result = await db.execute(
        select(VendorStaff).where(
            VendorStaff.vendor_id == vendor_id,
            VendorStaff.clerk_id == clerk_id,
            VendorStaff.revoked_at.is_(None),
        )
    )
    return result.scalars().first()


async def get_current_rider(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Any rider with a row — including one whose KYC is pending or rejected.

    Correct only for reads a rider must be able to make *before* approval: their
    own profile, KYC status, notifications. Anything that moves an order, goods
    or money must use `get_verified_rider` instead.
    """
    clerk_id = user["sub"]
    result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
    db_rider = result.scalar_one_or_none()
    if not db_rider:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered rider.")
    return user


async def get_verified_rider(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A rider whose KYC has actually been approved.

    KYC used to be enforced nowhere on the server. `get_current_rider` checks
    only that a Deliverer row exists, and `accept_delivery_radar` checked
    availability and cash float but never `kyc_status`. The single gate was a
    client-side redirect in the rider app's `(screens)/_layout.tsx` — which also
    failed *open* when the KYC query errored. A rider whose KYC was
    `unsubmitted`, or explicitly `rejected`, could accept orders, collect
    customers' cash and take their empty bottles, either by calling the API
    directly or just by using the app while that query was failing.

    The `detail` is structured so the client can route to VerificationWall on
    `type == "kyc_required"` rather than string-matching a sentence that will
    inevitably be reworded.
    """
    clerk_id = user["sub"]
    result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
    db_rider = result.scalar_one_or_none()
    if not db_rider:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered rider.")

    from models.deliverer_model import KYCStatus

    status = db_rider.kyc_status
    if status != KYCStatus.approved:
        readable = {
            KYCStatus.unsubmitted: "Submit your verification documents to start delivering.",
            KYCStatus.pending: "Your documents are under review. You can start delivering once approved.",
            KYCStatus.rejected: "Your verification was not approved. Please contact support.",
        }.get(status, "Your account is not verified for deliveries.")
        raise HTTPException(
            status_code=403,
            detail={
                "type": "kyc_required",
                "message": readable,
                "kyc_status": getattr(status, "value", str(status)),
            },
        )
    return user


# ── Order-scoped authorisation ───────────────────────────────────────────────
# Authenticating a token proves *who* is calling. It says nothing about whether
# that caller has any relationship to the order they named. Every order-scoped
# endpoint — REST or WebSocket — must go through `authorise_order_access`, or a
# leaked/guessed order id exposes one customer's live delivery location and
# contact details to any other signed-in account.

async def resolve_order_role(session: AsyncSession, order_id: UUID, clerk_id: str) -> str | None:
    """Return the caller's role on this order, or None if they have none.

    One of: "customer", "vendor", "rider".
    """
    from models.order_model import Order

    order = await session.get(Order, order_id)
    if order is None:
        return None

    customer = await session.get(User, order.customer_id) if order.customer_id else None
    if customer is not None and customer.clerk_id == clerk_id:
        return "customer"

    vendor = await session.get(Vendor, order.vendor_id) if order.vendor_id else None
    if vendor is not None:
        # Owner, or live staff of that store. Staff used to be one nullable
        # column on the vendor row; it is a table now, so membership is a query.
        if vendor.clerk_id == clerk_id:
            return "vendor"
        if await staff_membership(session, clerk_id, vendor.id):
            return "vendor"

    if order.deliverer_id:
        rider = await session.get(Deliverer, order.deliverer_id)
        if rider is not None and rider.clerk_id == clerk_id:
            return "rider"

    return None


async def authorise_order_access(
    session: AsyncSession,
    order_id: UUID,
    clerk_id: str,
    allowed_roles: tuple[str, ...] = ("customer", "vendor", "rider"),
) -> str:
    """Assert the caller is a party to this order; return their role.

    Raises 404 rather than 403 when the caller has no relationship to the order:
    confirming that an order id exists is itself a small information leak.
    """
    role = await resolve_order_role(session, order_id, clerk_id)
    if role is None or role not in allowed_roles:
        raise HTTPException(status_code=404, detail="Order not found")
    return role


async def owns_entity(session: AsyncSession, entity_type: str, entity_id: str, clerk_id: str) -> bool:
    """True if `clerk_id` is the owner of the given entity id.

    Used by the realtime endpoints, where the entity id arrives in the URL path
    and must be proven to belong to the token holder before we start streaming
    that entity's order events to the socket.
    """
    try:
        parsed_id = UUID(str(entity_id))
    except (ValueError, TypeError, AttributeError):
        return False

    if entity_type == "customer":
        row = await session.get(User, parsed_id)
        return row is not None and row.clerk_id == clerk_id
    if entity_type == "vendor":
        row = await session.get(Vendor, parsed_id)
        if row is None:
            return False
        if row.clerk_id == clerk_id:
            return True
        return await staff_membership(session, clerk_id, row.id) is not None
    if entity_type == "rider":
        row = await session.get(Deliverer, parsed_id)
        return row is not None and row.clerk_id == clerk_id
    return False
