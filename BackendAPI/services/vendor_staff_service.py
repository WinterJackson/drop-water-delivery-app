"""
Managing who may operate a store, and what they may do there.

Replaces `Vendor.staff_clerk_id` — a single nullable column with a UNIQUE
constraint, behind a screen called "Manage Staff". Adding a second person
silently replaced the first, one person could be staff of exactly one store
platform-wide, and access was all-or-nothing.

Two properties this module is careful about:

* **It never reveals whether an email has a Drop account.** The old endpoint
  answered 404 "Staff member not found. Please ask them to download the app and
  sign up first." for an unknown address and 200 for a known one, which let any
  vendor test arbitrary emails — a competitor's, a customer's. An invitation is
  recorded either way and binds when that person signs in.
* **Revocation is a soft delete.** Who could act on a store, and when, is part
  of the audit trail behind every order and bottle movement they touched.
"""
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.vendor_staff_model import (
    DEFAULT_PERMISSIONS,
    VendorStaff,
    normalise_permissions,
)

logger = logging.getLogger(__name__)

#: A store with more members than this is not a shop floor any more, and an
#: unbounded list is an invitation to script the endpoint.
MAX_STAFF_PER_STORE = 20


def _clean_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


async def _lookup_clerk_id(email: str) -> str | None:
    """Resolve an email to a Clerk subject, or None.

    Returns None rather than raising when the address is simply unknown — the
    caller must behave identically either way, or the endpoint becomes an
    account-existence oracle.
    """
    import asyncio

    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        # Fails closed rather than silently doing nothing: without the secret
        # there is no way to bind the invitation at all.
        raise HTTPException(
            status_code=503, detail="Staff management is not configured on this server."
        )

    def _lookup() -> str | None:
        from clerk_backend_api import Clerk

        clerk = Clerk(bearer_auth=secret)
        # `clerk-backend-api` 2.x takes a request object here, not keyword
        # arguments — `users.list(email_address=[…])` raises TypeError, which the
        # `except Exception` below turned into "Could not reach the accounts
        # service", so a signature change read as a network fault and every
        # invitation 502'd. `users.get`/`users.delete` still take keywords.
        response = clerk.users.list(request={"email_address": [email]})
        users = getattr(response, "data", response)
        return users[0].id if users else None

    try:
        # The Clerk SDK is synchronous; calling it inline blocks the event loop
        # for the whole round trip, stalling every other request on the worker.
        return await asyncio.to_thread(_lookup)
    except Exception as e:
        logger.error("STAFF_LOOKUP_FAILED: %s", e)
        raise HTTPException(
            status_code=502, detail="Could not reach the accounts service. Please try again."
        )


def serialize_staff(staff: VendorStaff) -> dict:
    return {
        "id": str(staff.id),
        "email": staff.email,
        "name": staff.name,
        "permissions": list(staff.permissions or []),
        "is_pending": staff.clerk_id is None,
        "is_active": bool(staff.is_active) and staff.revoked_at is None,
        "created_at": staff.created_at.isoformat() if staff.created_at else None,
        "accepted_at": staff.accepted_at.isoformat() if staff.accepted_at else None,
    }


async def list_staff(session: AsyncSession, vendor_id: UUID) -> list[dict]:
    """Everyone who can currently act on this store."""
    result = await session.execute(
        select(VendorStaff)
        .where(VendorStaff.vendor_id == vendor_id, VendorStaff.revoked_at.is_(None))
        .order_by(VendorStaff.created_at.asc())
    )
    return [serialize_staff(s) for s in result.scalars().all()]


async def invite_staff(
    session: AsyncSession,
    *,
    vendor_id: UUID,
    owner_clerk_id: str,
    email: str,
    permissions: list[str] | None = None,
) -> dict:
    """Grant someone access to this store.

    The response is deliberately the same whether or not the email belongs to a
    Drop account — see the module docstring. When it does, the grant is live
    immediately; when it does not, the row is a pending invitation that binds on
    their first sign-in (`bind_pending_invitations`).
    """
    email = _clean_email(email)
    granted = normalise_permissions(permissions if permissions is not None else DEFAULT_PERMISSIONS)

    live = await session.execute(
        select(VendorStaff).where(
            VendorStaff.vendor_id == vendor_id, VendorStaff.revoked_at.is_(None)
        )
    )
    existing = live.scalars().all()

    if len(existing) >= MAX_STAFF_PER_STORE:
        raise HTTPException(
            status_code=400,
            detail=f"This store already has {MAX_STAFF_PER_STORE} staff members. Remove one first.",
        )

    clerk_id = await _lookup_clerk_id(email)

    if clerk_id and clerk_id == owner_clerk_id:
        raise HTTPException(
            status_code=400,
            detail="You already own this store — you do not need to add yourself as staff.",
        )

    # Re-inviting an existing member updates their row. Two grants for the same
    # person would have to be revoked twice, and only one of them would be found.
    match = next(
        (
            s
            for s in existing
            if (clerk_id and s.clerk_id == clerk_id) or (s.clerk_id is None and s.email == email)
        ),
        None,
    )

    if match is not None:
        match.permissions = granted
        match.email = email
        match.is_active = True
        if clerk_id and match.clerk_id is None:
            match.clerk_id = clerk_id
            match.accepted_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(match)
        logger.info("STAFF_UPDATED vendor=%s staff=%s", vendor_id, match.id)
        return {
            "staff": serialize_staff(match),
            "updated_existing": True,
            "message": "Their access has been updated.",
        }

    staff = VendorStaff(
        vendor_id=vendor_id,
        clerk_id=clerk_id,
        email=email,
        permissions=granted,
        invited_by_clerk_id=owner_clerk_id,
        accepted_at=datetime.now(timezone.utc) if clerk_id else None,
    )
    session.add(staff)
    await session.commit()
    await session.refresh(staff)

    logger.info("STAFF_INVITED vendor=%s staff=%s bound=%s", vendor_id, staff.id, bool(clerk_id))
    return {
        "staff": serialize_staff(staff),
        "updated_existing": False,
        # Identical wording in both branches. The owner learns whether it worked
        # from the list — where a pending invitation is labelled as such — not
        # from the shape of this reply.
        "message": "Invitation sent. They'll have access as soon as they sign in to Drop with that email.",
    }


async def update_permissions(
    session: AsyncSession, *, vendor_id: UUID, staff_id: UUID, permissions: list[str]
) -> dict:
    staff = await _get_member(session, vendor_id, staff_id)
    staff.permissions = normalise_permissions(permissions)
    await session.commit()
    await session.refresh(staff)
    logger.info("STAFF_PERMISSIONS_CHANGED vendor=%s staff=%s", vendor_id, staff_id)
    return serialize_staff(staff)


async def revoke_staff(session: AsyncSession, *, vendor_id: UUID, staff_id: UUID) -> dict:
    """Remove someone's access, keeping the record that they had it."""
    staff = await _get_member(session, vendor_id, staff_id)
    staff.revoke()
    # The device must stop receiving this store's orders the moment access ends.
    staff.push_token = None
    await session.commit()
    logger.info("STAFF_REVOKED vendor=%s staff=%s", vendor_id, staff_id)
    return {"message": "Their access to this store has been removed."}


async def _get_member(session: AsyncSession, vendor_id: UUID, staff_id: UUID) -> VendorStaff:
    result = await session.execute(
        select(VendorStaff).where(
            VendorStaff.id == staff_id,
            VendorStaff.vendor_id == vendor_id,
            VendorStaff.revoked_at.is_(None),
        )
    )
    staff = result.scalars().first()
    if staff is None:
        # Scoped to `vendor_id`, so a staff id from another store is a 404 here
        # and reveals nothing about whether it exists.
        raise HTTPException(status_code=404, detail="Staff member not found.")
    return staff


async def bind_pending_invitations(session: AsyncSession, *, clerk_id: str, email: str) -> int:
    """Attach any invitations addressed to `email` to this Clerk subject.

    Called when a vendor-app user signs in. An owner can invite someone who has
    never opened Drop; without this the invitation would sit unbound forever and
    the owner would be told, truthfully but uselessly, that it had been sent.
    """
    email = (email or "").strip().lower()
    if not email or not clerk_id:
        return 0

    result = await session.execute(
        select(VendorStaff).where(
            VendorStaff.email == email,
            VendorStaff.clerk_id.is_(None),
            VendorStaff.revoked_at.is_(None),
        )
    )
    pending = result.scalars().all()
    if not pending:
        return 0

    now = datetime.now(timezone.utc)
    for staff in pending:
        staff.clerk_id = clerk_id
        staff.accepted_at = now
    await session.commit()
    logger.info("STAFF_INVITATIONS_BOUND clerk=%s count=%d", clerk_id, len(pending))
    return len(pending)


async def bind_invitations_for_caller(session: AsyncSession, clerk_id: str) -> int:
    """Bind any invitation addressed to *this* caller's email address.

    Called from `profile-status` when the caller resolves to no store at all —
    i.e. the onboarding path. The Clerk session token carries `sub` and not an
    email claim, so the address has to be read from Clerk, and doing it only on
    the no-store path keeps that round trip off every other request.

    Looking up the caller's *own* identity leaks nothing: they already know their
    email address.
    """
    import asyncio

    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        return 0

    # Cheap pre-check: no unbound invitations at all means no reason to call out.
    any_pending = await session.execute(
        select(VendorStaff.id)
        .where(VendorStaff.clerk_id.is_(None), VendorStaff.revoked_at.is_(None))
        .limit(1)
    )
    if not any_pending.scalars().first():
        return 0

    def _email() -> str | None:
        from clerk_backend_api import Clerk

        clerk = Clerk(bearer_auth=secret)
        user = clerk.users.get(user_id=clerk_id)
        addresses = getattr(user, "email_addresses", None) or []
        primary_id = getattr(user, "primary_email_address_id", None)
        for address in addresses:
            if getattr(address, "id", None) == primary_id:
                return getattr(address, "email_address", None)
        return getattr(addresses[0], "email_address", None) if addresses else None

    try:
        email = await asyncio.to_thread(_email)
    except Exception as e:
        # A failure here must not block sign-in. The invitation stays pending
        # and binds on the next attempt.
        logger.warning("STAFF_BIND_LOOKUP_FAILED clerk=%s: %s", clerk_id, e)
        return 0

    if not email:
        return 0
    return await bind_pending_invitations(session, clerk_id=clerk_id, email=email)


async def set_push_token(session: AsyncSession, *, clerk_id: str, token: str | None) -> int:
    """Write this device's push token onto every store the person staffs.

    `Vendor.staff_push_token` was one column on the *store*, so it addressed
    whichever staff member registered last and could not reach the others.
    """
    result = await session.execute(
        select(VendorStaff).where(
            VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None)
        )
    )
    rows = result.scalars().all()
    for staff in rows:
        staff.push_token = token
    return len(rows)


async def push_tokens_for_store(session: AsyncSession, vendor_id: UUID, permission: str | None = None) -> list[str]:
    """Live staff push tokens for a store, optionally only those who can act.

    Telling someone about an order they have no permission to touch is noise;
    telling nobody because the store had one token column was the bug.
    """
    result = await session.execute(
        select(VendorStaff).where(
            VendorStaff.vendor_id == vendor_id,
            VendorStaff.revoked_at.is_(None),
            VendorStaff.push_token.isnot(None),
        )
    )
    return [
        s.push_token
        for s in result.scalars().all()
        if permission is None or s.has(permission)
    ]


# ── Membership helpers ───────────────────────────────────────────────────────
# `Vendor.staff_clerk_id` was read in a dozen places as `clerk_id == … OR
# staff_clerk_id == …`. That predicate is now a join, and putting it in one
# place is what stops the next caller from writing a subtly different one.


async def is_store_member(session: AsyncSession, clerk_id: str | None, vendor) -> bool:
    """True if `clerk_id` owns `vendor` or is live staff of it."""
    if not clerk_id or vendor is None:
        return False
    if vendor.clerk_id == clerk_id:
        return True
    result = await session.execute(
        select(VendorStaff.id)
        .where(
            VendorStaff.vendor_id == vendor.id,
            VendorStaff.clerk_id == clerk_id,
            VendorStaff.revoked_at.is_(None),
        )
        .limit(1)
    )
    return result.scalars().first() is not None


async def staffed_vendor_ids(session: AsyncSession, clerk_id: str) -> list:
    """Ids of every store this person staffs (not owns)."""
    result = await session.execute(
        select(VendorStaff.vendor_id).where(
            VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None)
        )
    )
    return list(result.scalars().all())


async def revoke_all_for_store(session: AsyncSession, vendor_id) -> int:
    """End every grant on a store. Used when the store itself is deleted.

    Without it, a staff member keeps a live grant to an anonymised store: the
    resolver matches the membership row and never looks at `verification_status`.
    """
    result = await session.execute(
        select(VendorStaff).where(
            VendorStaff.vendor_id == vendor_id, VendorStaff.revoked_at.is_(None)
        )
    )
    rows = result.scalars().all()
    for staff in rows:
        staff.revoke()
        staff.push_token = None
    return len(rows)
