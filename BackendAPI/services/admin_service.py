"""Administrator roster, and the audit trail.

Two rules hold this together:

1. **Audit is written in the caller's transaction, never on its own.**
   `record_audit` adds the row and does not commit. The route commits once, so
   the change and its audit record land together or not at all. A `commit()`
   here would let the audit succeed while the action rolls back, or the reverse
   — and the reverse is the one that matters.

2. **Invitations never reveal whether an email has an account.** Same reasoning
   as `vendor_staff_service`: the reply is identical either way, so the endpoint
   cannot be used to enumerate who is registered on the platform.
"""
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.admin_model import (
    ALL_PERMISSIONS,
    PERM_ADMINS_MANAGE,
    PERMISSION_GROUPS,
    PERMISSION_LABELS,
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    ROLE_PRESETS,
    ROLE_SUPER_ADMIN,
    AdminAuditLog,
    AdminUser,
    normalise_permissions,
    permissions_for_role,
)

logger = logging.getLogger(__name__)

#: More administrators than this is not a back office any more, and an unbounded
#: roster is worth noticing before it is worth explaining.
MAX_ADMINS = 50


# ── Audit ─────────────────────────────────────────────────────────────────


def record_audit(
    session: AsyncSession,
    *,
    access,
    action: str,
    target_type: str | None = None,
    target_id: str | UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AdminAuditLog:
    """Stage an audit row in the caller's transaction. Does not commit.

    `access` is an `AdminAccess`. The admin's email is copied in rather than
    referenced, so the record stays readable after the admin row is revoked.
    """
    entry = AdminAuditLog(
        admin_id=getattr(access, "id", None),
        admin_email=getattr(access, "email", "unknown"),
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        before=before,
        after=after,
        reason=reason,
        ip=getattr(access, "ip", None),
        user_agent=getattr(access, "user_agent", None),
    )
    session.add(entry)
    return entry


def changed_fields(before: dict, after: dict) -> tuple[dict, dict]:
    """Reduce a pair of snapshots to only what actually differs.

    Storing whole rows would copy the personal data this console exists to
    control into a table that is never redacted and never deleted.
    """
    keys = [k for k in after if before.get(k) != after.get(k)]
    return ({k: before.get(k) for k in keys}, {k: after.get(k) for k in keys})


async def list_audit(
    session: AsyncSession,
    *,
    limit: int = 50,
    before_id: UUID | None = None,
    admin_id: UUID | None = None,
    action: str | None = None,
    target_id: str | None = None,
) -> list[dict]:
    """Newest first, keyset-paginated on `created_at`.

    Keyset rather than OFFSET: this table only grows, and OFFSET degrades
    exactly when the log becomes large enough to be worth reading.
    """
    query = select(AdminAuditLog).order_by(
        AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()
    )

    if admin_id:
        query = query.where(AdminAuditLog.admin_id == admin_id)
    if action:
        query = query.where(AdminAuditLog.action.startswith(action))
    if target_id:
        query = query.where(AdminAuditLog.target_id == str(target_id))
    if before_id:
        anchor = await session.get(AdminAuditLog, before_id)
        if anchor is not None:
            query = query.where(
                (AdminAuditLog.created_at < anchor.created_at)
                | (
                    (AdminAuditLog.created_at == anchor.created_at)
                    & (AdminAuditLog.id < anchor.id)
                )
            )

    result = await session.execute(query.limit(min(limit, 200)))
    return [serialize_audit(row) for row in result.scalars().all()]


def serialize_audit(entry: AdminAuditLog) -> dict:
    return {
        "id": str(entry.id),
        "admin_email": entry.admin_email,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "before": entry.before,
        "after": entry.after,
        "reason": entry.reason,
        "ip": str(entry.ip) if entry.ip else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


# ── Roster ────────────────────────────────────────────────────────────────


def serialize_admin(admin: AdminUser) -> dict:
    return {
        "id": str(admin.id),
        "email": admin.email,
        "name": admin.name,
        "role": admin.role,
        "role_label": ROLE_LABELS.get(admin.role, admin.role),
        "permissions": list(admin.permissions or []),
        "is_pending": admin.clerk_id is None,
        "is_active": bool(admin.is_active) and admin.revoked_at is None,
        "created_at": admin.created_at.isoformat() if admin.created_at else None,
        "accepted_at": admin.accepted_at.isoformat() if admin.accepted_at else None,
        "last_seen_at": admin.last_seen_at.isoformat() if admin.last_seen_at else None,
    }


def permission_catalogue() -> dict:
    """Shipped with the roster so the UI can never offer a capability the server
    has dropped, nor miss one it has added."""
    return {
        "permissions": [
            {"key": p, "label": PERMISSION_LABELS[p]} for p in ALL_PERMISSIONS
        ],
        "groups": [
            {"title": title, "permissions": list(perms)}
            for title, perms in PERMISSION_GROUPS
        ],
        "roles": [
            {
                "key": role,
                "label": ROLE_LABELS[role],
                "description": ROLE_DESCRIPTIONS[role],
                "permissions": list(perms),
            }
            for role, perms in ROLE_PRESETS.items()
        ],
    }


def _clean_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


async def list_admins(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        select(AdminUser)
        .where(AdminUser.revoked_at.is_(None))
        .order_by(AdminUser.created_at.asc())
    )
    return [serialize_admin(a) for a in result.scalars().all()]


async def invite_admin(
    session: AsyncSession,
    *,
    access,
    email: str,
    name: str | None,
    role: str,
    permissions: list[str] | None = None,
) -> dict:
    """Grant administrator access.

    The grant is live the moment the invited person signs in — `bind_admin`
    matches the pending row by email. No acceptance step: an admin who has been
    given access by another admin does not also need to agree to it.
    """
    email = _clean_email(email)

    if role not in ROLE_PRESETS:
        raise HTTPException(status_code=400, detail="Choose a valid role.")

    granted = normalise_permissions(
        permissions if permissions is not None else permissions_for_role(role)
    )
    if not granted:
        raise HTTPException(
            status_code=400, detail="An administrator needs at least one permission."
        )

    live = await session.execute(
        select(AdminUser).where(AdminUser.revoked_at.is_(None))
    )
    existing_rows = live.scalars().all()

    if len(existing_rows) >= MAX_ADMINS:
        raise HTTPException(
            status_code=400,
            detail=f"There are already {MAX_ADMINS} administrators. Remove one first.",
        )

    existing = next((a for a in existing_rows if a.email == email), None)
    if existing is not None:
        existing.role = role
        existing.permissions = granted
        if name:
            existing.name = name
        return {
            "admin": serialize_admin(existing),
            "updated_existing": True,
            "message": "Their access has been updated.",
        }

    admin = AdminUser(
        email=email,
        name=name,
        role=role,
        permissions=granted,
        invited_by=getattr(access, "id", None),
    )
    session.add(admin)
    await session.flush()  # populate `id` for the audit row, still one transaction

    return {
        "admin": serialize_admin(admin),
        "updated_existing": False,
        "message": "They now have access. It applies the next time they sign in.",
    }


async def update_admin(
    session: AsyncSession,
    *,
    access,
    admin_id: UUID,
    role: str | None = None,
    permissions: list[str] | None = None,
) -> tuple[AdminUser, dict, dict]:
    """Change a role or capability set. Returns (row, before, after) for audit."""
    admin = await _get_admin(session, admin_id)

    before = {"role": admin.role, "permissions": list(admin.permissions or [])}

    if role is not None:
        if role not in ROLE_PRESETS:
            raise HTTPException(status_code=400, detail="Choose a valid role.")
        admin.role = role
        if permissions is None:
            admin.permissions = permissions_for_role(role)

    if permissions is not None:
        granted = normalise_permissions(permissions)
        if not granted:
            raise HTTPException(
                status_code=400,
                detail="An administrator needs at least one permission. Remove them instead.",
            )
        admin.permissions = granted

    # Downgrading the last administrator who can manage administrators is the
    # same lockout as deleting them, and it is the easier one to do by accident.
    if PERM_ADMINS_MANAGE in before["permissions"] and PERM_ADMINS_MANAGE not in (
        admin.permissions or []
    ):
        await _assert_not_last_super_admin(session, admin, ignore_self=True)

    after = {"role": admin.role, "permissions": list(admin.permissions or [])}
    return admin, *changed_fields(before, after)


async def revoke_admin(session: AsyncSession, *, access, admin_id: UUID) -> AdminUser:
    admin = await _get_admin(session, admin_id)

    if getattr(access, "id", None) == admin.id:
        # Not paternalism: the last super admin removing themselves locks
        # everybody out of the console permanently, and the only recovery is a
        # manual database edit.
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator access. Ask another administrator.",
        )

    await _assert_not_last_super_admin(session, admin)
    admin.revoke()
    return admin


async def _get_admin(session: AsyncSession, admin_id: UUID) -> AdminUser:
    result = await session.execute(
        select(AdminUser).where(
            AdminUser.id == admin_id, AdminUser.revoked_at.is_(None)
        )
    )
    admin = result.scalars().first()
    if admin is None:
        raise HTTPException(status_code=404, detail="Administrator not found.")
    return admin


async def _assert_not_last_super_admin(
    session: AsyncSession, admin: AdminUser, *, ignore_self: bool = False
) -> None:
    """The console must always retain somebody who can grant access.

    Without this, one careless edit leaves a platform whose administrator list
    can never be changed again — recoverable only by editing the database by
    hand, which is exactly the situation an admin console exists to avoid.

    `ignore_self` is for the downgrade path, where `admin.permissions` has
    already been mutated in the session and so no longer counts toward the
    total; the delete path still holds the permission and must be excluded by
    id instead.
    """
    if not ignore_self and PERM_ADMINS_MANAGE not in (admin.permissions or []):
        return

    query = (
        select(func.count())
        .select_from(AdminUser)
        .where(
            AdminUser.revoked_at.is_(None),
            AdminUser.is_active.is_(True),
            AdminUser.permissions.contains([PERM_ADMINS_MANAGE]),
            AdminUser.id != admin.id,
        )
    )
    if (await session.execute(query)).scalar() or 0:
        return

    raise HTTPException(
        status_code=400,
        detail=(
            "This is the only administrator who can manage administrators. "
            "Grant that permission to somebody else first."
        ),
    )


# ── Sign-in binding, and the bootstrap ────────────────────────────────────


async def bind_admin(session: AsyncSession, *, clerk_id: str, email: str | None) -> AdminUser | None:
    """Attach a pending invitation to the Clerk subject that just signed in.

    Matching is by email, which is the only thing the inviting admin knew.
    """
    if not email:
        return None

    email = email.strip().lower()
    result = await session.execute(
        select(AdminUser).where(
            AdminUser.email == email, AdminUser.revoked_at.is_(None)
        )
    )
    admin = result.scalars().first()
    if admin is None:
        return None

    if admin.clerk_id is None:
        admin.clerk_id = clerk_id
        admin.accepted_at = datetime.now(timezone.utc)
        await session.commit()
    elif admin.clerk_id != clerk_id:
        # The email matches an administrator, but a *different* Clerk account
        # already holds that grant. Rebinding here would let anyone who can
        # register an address take over an existing administrator.
        logger.warning(
            "ADMIN_BIND_CONFLICT: %s is bound to another account; refusing to rebind.",
            email,
        )
        return None

    return admin


async def bind_admin_for_caller(session: AsyncSession, clerk_id: str) -> AdminUser | None:
    """Bind an invitation addressed to *this* caller's email address.

    Called from `_resolve_admin` when the caller matches no administrator row —
    i.e. the first sign-in after being invited. Without it `bind_admin` was never
    reached by anything, so an invited administrator's row kept `clerk_id = NULL`
    for ever and the console answered "Administrator access required" to a person
    who had genuinely been granted access. The invite flow could not complete.

    The Clerk session token carries `sub` and no email claim, so the address has
    to be read from Clerk. Doing it only on the no-match path keeps that round
    trip off every other admin request, and the pre-check below keeps it off this
    one too whenever there is no pending invitation at all — which is the normal
    state of the table.

    Looking up the caller's *own* identity leaks nothing: they already know their
    own email address.
    """
    import asyncio

    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        return None

    pending = await session.execute(
        select(AdminUser.id)
        .where(AdminUser.clerk_id.is_(None), AdminUser.revoked_at.is_(None))
        .limit(1)
    )
    if not pending.scalars().first():
        return None

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
        # The Clerk SDK is synchronous; inline it blocks the event loop for the
        # whole round trip, stalling every other request on the worker.
        email = await asyncio.to_thread(_email)
    except Exception as exc:
        # A failure here must not turn into a 500 on sign-in. The invitation
        # stays pending and binds on the next attempt.
        logger.warning("ADMIN_BIND_LOOKUP_FAILED clerk=%s: %s", clerk_id, exc)
        return None

    if not email:
        return None
    return await bind_admin(session, clerk_id=clerk_id, email=email)


async def seed_first_admin(session: AsyncSession) -> int:
    """Promote `ADMIN_CLERK_IDS` to real rows, once.

    The env allowlist is what this table replaces, but removing it without a
    migration path would lock the owners out of the console the moment it ships.
    So on first run each listed Clerk id becomes a `super_admin` row and the
    variable can then be deleted.

    Idempotent: an id that already has a row is skipped, so a redeploy with the
    variable still set does not resurrect an administrator who was revoked.
    """
    raw = os.getenv("ADMIN_CLERK_IDS", "")
    clerk_ids = [c.strip() for c in raw.split(",") if c.strip()]
    if not clerk_ids:
        return 0

    existing = await session.execute(select(AdminUser.clerk_id))
    already = {c for c in existing.scalars().all() if c}

    created = 0
    for clerk_id in clerk_ids:
        if clerk_id in already:
            continue
        session.add(
            AdminUser(
                clerk_id=clerk_id,
                # A placeholder the owner replaces on first sign-in; the column
                # is NOT NULL because every other path invites by email.
                email=f"{clerk_id}@seed.drop.local",
                name="Seeded administrator",
                role=ROLE_SUPER_ADMIN,
                permissions=list(ALL_PERMISSIONS),
                accepted_at=datetime.now(timezone.utc),
            )
        )
        created += 1

    if created:
        await session.commit()
        logger.info("ADMIN_SEED: promoted %d ADMIN_CLERK_IDS entries to Admin_Users.", created)

    return created
