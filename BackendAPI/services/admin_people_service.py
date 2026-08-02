"""Managing the people on the platform: customers, riders and vendors.

Three account types with genuinely different shapes — a rider has a KYC state
and a cash float, a vendor has a wallet and a staff roster, a customer has a
bottle debt — so they are not forced through one generic "user" abstraction.
What *is* shared is the part that must not diverge: masking, keyset pagination,
and suspension.

Suspension is the reason this module and
`vendor_service.discoverable_vendor()` were written in the same change. A
suspend button that leaves the store in customer search is worse than no button
at all, because it reports success.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer, KYCStatus
from models.order_model import Order
from models.user_model import User
from models.vendor_model import Vendor

logger = logging.getLogger(__name__)

Kind = Literal["customer", "rider", "vendor"]

MODELS: dict[str, type] = {"customer": User, "rider": Deliverer, "vendor": Vendor}

#: What each account type is called in the audit log and in refusal messages.
LABELS = {"customer": "Customer", "rider": "Rider", "vendor": "Vendor"}


def mask(value: str | None, keep: int = 4) -> str | None:
    """Enough to recognise a record, not enough to use it.

    Applied to every list response regardless of the caller's permissions. The
    unmasked value is a separate, audited request — see `reveal_contact`.

    `keep` is clamped at zero because `value[-0:]` is the *whole string* in
    Python, not the empty one — so a `keep=0` call intended to hide everything
    returned the value untouched behind a decorative `••••`.
    """
    if not value:
        return None
    if keep <= 0:
        return "••••"
    tail = value[-keep:] if len(value) > keep else value
    return f"••••{tail}"


def mask_email(value: str | None) -> str | None:
    """Mask the local part, keep the domain.

    The domain is what makes a row recognisable in a list — it distinguishes a
    staff account from a customer at a glance — while the local part is the
    half that identifies a person. `a••••@example.org` rather than the whole
    address for anyone without `pii.view`.
    """
    if not value or "@" not in value:
        return mask(value, keep=0)
    local, _, domain = value.partition("@")
    head = local[0] if local else ""
    return f"{head}••••@{domain}"


def money(value) -> str:
    """Money crosses the wire as a decimal string, never a float."""
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _name(row) -> str | None:
    """The three models spell the display name differently."""
    return (
        getattr(row, "full_name", None)
        or getattr(row, "name", None)
        or getattr(row, "business_name", None)
    )


# ── Listing ───────────────────────────────────────────────────────────────


def _search_filter(model, term: str):
    """Match on the things an operator actually has to hand.

    A support call starts with a phone number or an email, never a UUID. Email
    and phone are plain columns on all three models, so this is an ILIKE rather
    than the full-text vector — which is built for customer-facing discovery and
    does not cover riders or customers at all.
    """
    like = f"%{term.strip()}%"
    clauses = [model.email.ilike(like), model.phone_number.ilike(like)]

    for attribute in ("full_name", "name", "business_name", "owners_name", "plate_number"):
        column = getattr(model, attribute, None)
        if column is not None:
            clauses.append(column.ilike(like))

    return or_(*clauses)


async def list_people(
    session: AsyncSession,
    *,
    kind: Kind,
    search: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: UUID | None = None,
) -> dict:
    """Keyset pagination, newest first. Never OFFSET.

    OFFSET degrades precisely when a table grows large enough for pagination to
    matter, and it skips or repeats rows when the underlying set changes between
    pages — which it does constantly on a live platform.
    """
    model = MODELS[kind]
    query = select(model).order_by(model.created_at.desc(), model.id.desc())

    if search and search.strip():
        query = query.where(_search_filter(model, search))

    if status == "suspended":
        query = query.where(model.suspended_at.isnot(None))
    elif status == "active":
        query = query.where(model.suspended_at.is_(None))
    elif status and kind == "rider":
        query = query.where(Deliverer.kyc_status == KYCStatus(status))
    elif status and kind == "vendor":
        # Verification state, which is not the same axis as suspension: a store
        # can be unverified and trading, or verified and suspended. The console's
        # verification queue filters on this to answer "who is still waiting".
        query = query.where(Vendor.verification_status == status)

    if cursor:
        anchor = await session.get(model, cursor)
        if anchor is not None:
            query = query.where(
                (model.created_at < anchor.created_at)
                | ((model.created_at == anchor.created_at) & (model.id < anchor.id))
            )

    rows = (await session.execute(query.limit(limit + 1))).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    return {
        "items": [summarise(row, kind) for row in rows],
        "next_cursor": str(rows[-1].id) if has_more and rows else None,
    }


def summarise(row, kind: Kind) -> dict:
    """The list row. Contact details are masked for everybody."""
    common = {
        "id": str(row.id),
        "kind": kind,
        "name": _name(row),
        "email": mask_email(row.email),
        "phone_number": mask(row.phone_number, keep=3),
        "is_suspended": row.suspended_at is not None,
        "suspension_reason": row.suspension_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

    if kind == "rider":
        return {
            **common,
            "kyc_status": row.kyc_status.value if row.kyc_status else None,
            "vehicle_type": row.vehicle_type,
            "plate_number": row.plate_number,
            "is_available": bool(row.is_available),
            "rating": float(row.rating) if row.rating is not None else None,
            "wallet_balance": money(row.wallet_balance),
        }

    if kind == "vendor":
        return {
            **common,
            "vendor_type": row.vendor_type,
            "verification_status": row.verification_status,
            "is_online": bool(row.is_online),
            "is_active": bool(row.is_active),
            "rating": float(row.rating) if row.rating is not None else None,
            "wallet_balance": money(row.wallet_balance),
        }

    return {
        **common,
        "is_active": bool(row.is_active),
        "wallet_balance": money(row.wallet_balance),
        "debt_balance": money(row.debt_balance),
        "bottle_refill_count": int(row.bottle_refill_count or 0),
        "last_order_date": row.last_order_date.isoformat() if row.last_order_date else None,
    }


# ── Detail ────────────────────────────────────────────────────────────────


async def get_person(session: AsyncSession, *, kind: Kind, person_id: UUID) -> dict:
    """One account, with the order history that makes a support call answerable.

    Contact details stay masked here too. An operator looking someone up to
    check an order does not need their phone number on screen; the ones who do
    can reveal it, and that is recorded.
    """
    model = MODELS[kind]
    row = await session.get(model, person_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{LABELS[kind]} not found.")

    column = {
        "customer": Order.customer_id,
        "rider": Order.deliverer_id,
        "vendor": Order.vendor_id,
    }[kind]

    totals = (
        await session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
                func.max(Order.created_at),
            ).where(column == person_id, Order.payment_status == "paid")
        )
    ).one()

    recent = (
        (
            await session.execute(
                select(Order)
                .where(column == person_id)
                .order_by(Order.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    return {
        **summarise(row, kind),
        "location_address": getattr(row, "location_address", None),
        "suspended_at": row.suspended_at.isoformat() if row.suspended_at else None,
        "orders": {
            "paid_count": int(totals[0] or 0),
            "lifetime_value": money(totals[1]),
            "last_order_at": totals[2].isoformat() if totals[2] else None,
        },
        "recent_orders": [
            {
                "id": str(order.id),
                "status": order.order_status,
                "payment_status": order.payment_status,
                "total": money(order.total_amount),
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            for order in recent
        ],
    }


async def reveal_contact(session: AsyncSession, *, kind: Kind, person_id: UUID) -> dict:
    """The unmasked contact details. Caller must hold `pii.view`; audited by the route."""
    model = MODELS[kind]
    row = await session.get(model, person_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{LABELS[kind]} not found.")

    revealed = {
        "id": str(row.id),
        "email": row.email,
        "phone_number": row.phone_number,
        "location_address": getattr(row, "location_address", None),
    }
    if kind == "rider":
        # Decrypted by the ORM type on the way out — see `StringEncryptedType`.
        revealed["ID_number"] = row.ID_number
    return revealed


# ── Suspension ────────────────────────────────────────────────────────────


async def set_suspended(
    session: AsyncSession,
    *,
    kind: Kind,
    person_id: UUID,
    suspend: bool,
    reason: str,
    admin_id,
) -> tuple[object, dict, dict]:
    """Suspend or reinstate. Returns (row, before, after) for the audit record.

    Does **not** commit — the route owns the transaction so the change and its
    audit row land together.

    For a vendor this also clears `is_active`, which is what
    `vendor_service.discoverable_vendor()` reads. Customers and riders are
    gated by their own `is_active`, which already existed but had nowhere to
    record why it was cleared.
    """
    model = MODELS[kind]
    row = await session.get(model, person_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{LABELS[kind]} not found.")

    already = row.suspended_at is not None
    if already == suspend:
        raise HTTPException(
            status_code=409,
            detail=f"This {kind} is already {'suspended' if suspend else 'active'}.",
        )

    before = {"suspended": already, "is_active": bool(row.is_active)}

    if suspend:
        row.suspended_at = datetime.now(timezone.utc)
        row.suspension_reason = reason
        row.suspended_by = admin_id
        row.is_active = False
        if kind == "rider":
            # A suspended rider must stop receiving dispatch offers immediately,
            # not at the end of whatever shift they are on.
            row.is_available = False
    else:
        row.suspended_at = None
        row.suspension_reason = None
        row.suspended_by = None
        row.is_active = True

    after = {"suspended": bool(row.suspended_at), "is_active": bool(row.is_active)}
    return row, before, after


# ── Global search ─────────────────────────────────────────────────────────

#: Deliberately small. The command palette exists to get an operator to one
#: record fast, not to be a reporting tool.
SEARCH_LIMIT_PER_KIND = 5


async def global_search(session: AsyncSession, *, term: str, permissions: set[str]) -> dict:
    """One box over every account type, plus an order id.

    Scoped by capability: an operator without `customers.read` gets no customer
    results rather than a list they cannot open. Searching must not become a way
    around the permission that guards the detail page.
    """
    term = (term or "").strip()
    if len(term) < 2:
        return {"results": []}

    results: list[dict] = []

    allowed = {
        "customer": "customers.read",
        "rider": "riders.read",
        "vendor": "vendors.read",
    }

    for kind, permission in allowed.items():
        if permission not in permissions:
            continue
        model = MODELS[kind]
        rows = (
            (
                await session.execute(
                    select(model)
                    .where(_search_filter(model, term))
                    .order_by(model.created_at.desc())
                    .limit(SEARCH_LIMIT_PER_KIND)
                )
            )
            .scalars()
            .all()
        )
        results.extend(
            {
                "kind": kind,
                "id": str(row.id),
                "title": _name(row) or mask_email(row.email) or str(row.id),
                "subtitle": mask(row.phone_number, keep=3) or "",
                "href": f"/people/{kind}s/{row.id}",
            }
            for row in rows
        )

    # An order id pasted straight from a support ticket is the other thing an
    # operator arrives with.
    if "orders.read" in permissions:
        try:
            order_id = UUID(term)
        except ValueError:
            order_id = None
        if order_id is not None:
            order = await session.get(Order, order_id)
            if order is not None:
                results.insert(
                    0,
                    {
                        "kind": "order",
                        "id": str(order.id),
                        "title": f"Order {str(order.id)[:8]}",
                        "subtitle": f"{order.order_status} · {money(order.total_amount)}",
                        "href": f"/operations/orders/{order.id}",
                    },
                )

    return {"results": results}
