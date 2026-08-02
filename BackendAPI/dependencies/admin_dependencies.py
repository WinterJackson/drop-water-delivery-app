"""The one gate every `/api/admin` route goes through.

There is deliberately a single way to authorise an admin request —
`require_admin("some.permission")` — for the same reason the vendor routes have
a single `require_permission`: a second way to check is a second way to get it
wrong, and the one that gets it wrong is the one an attacker finds.

`tests/test_admin_rbac.py` walks the route table and fails the build if any
handler under `/api/admin` is registered without this dependency, so a new
endpoint cannot be added unprotected by omission.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.dependencies import get_db
from models.admin_model import (
    ALL_PERMISSIONS,
    PERMISSION_LABELS,
    AdminUser,
)
from services import admin_service
from utils.verify_user_token import get_current_user

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminAccess:
    """The authenticated admin, resolved once per request."""

    admin: AdminUser
    clerk_id: str
    email: str
    permissions: frozenset[str]
    ip: str | None = None
    user_agent: str | None = None

    @property
    def id(self):
        return self.admin.id

    def may(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        """For a second check inside a handler that branches on capability.

        Used where one endpoint serves two audiences — e.g. a rider detail page
        that includes the identity document only for `pii.view`.
        """
        if not self.may(permission):
            raise _denied(permission)


def _denied(permission: str) -> HTTPException:
    """The refusal shape the frontends already branch on.

    Typed, so the dashboard can say "you need X" instead of showing a raw 403,
    and so a copy-edit to the message never breaks a client that matched on it.
    """
    return HTTPException(
        status_code=403,
        detail={
            "type": "permission_required",
            "permission": permission,
            "message": (
                f"You do not have permission to {PERMISSION_LABELS.get(permission, permission).lower()}."
            ),
        },
    )


def _two_factor_required() -> bool:
    """Default on. Turning this off is a deliberate act, not an omission."""
    return (os.getenv("ADMIN_2FA_REQUIRED", "true").strip().lower()) != "false"


async def _resolve_admin(request: Request, db: AsyncSession, user: dict) -> AdminAccess:
    clerk_id = user.get("sub")
    if not clerk_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    result = await db.execute(
        select(AdminUser).where(
            AdminUser.clerk_id == clerk_id,
            AdminUser.revoked_at.is_(None),
            AdminUser.is_active.is_(True),
        )
    )
    admin = result.scalars().first()

    if admin is None:
        # Nobody matches this Clerk subject *yet*. An administrator invited by
        # email has a row with `clerk_id = NULL` until their first sign-in, and
        # this is that sign-in — so try to bind it before refusing. Without this
        # the invite flow could never complete: the row stayed unbound for ever
        # and the console refused somebody who had genuinely been granted access.
        #
        # Costs a Clerk round trip only when there is a pending invitation to
        # bind, which is the exceptional case rather than the normal one.
        admin = await admin_service.bind_admin_for_caller(db, clerk_id)

    if admin is None:
        # Every signed-in user of the three apps holds a structurally valid
        # token — that is the accepted cost of sharing one Clerk instance — so
        # this branch is ordinary traffic, not necessarily an attack. It is
        # logged without the token and answered without detail.
        logger.info("ADMIN_ACCESS_DENIED: no admin record for %s", clerk_id)
        raise HTTPException(status_code=403, detail="Administrator access required.")

    # Two-factor is asserted from the session claim rather than trusted from the
    # client. Clerk sets it when the session was established with a second
    # factor; a session that never had one cannot acquire the claim by asking.
    if _two_factor_required() and not _claims_two_factor(user):
        raise HTTPException(
            status_code=403,
            detail={
                "type": "two_factor_required",
                "message": (
                    "Two-factor authentication is required for administrator "
                    "access. Enable it on your account, then sign in again."
                ),
            },
        )

    # Cheap liveness signal for the admin roster; not worth a write per request.
    now = datetime.now(timezone.utc)
    last = admin.last_seen_at
    if last is None or (now - last).total_seconds() > 300:
        admin.last_seen_at = now
        await db.commit()

    return AdminAccess(
        admin=admin,
        clerk_id=clerk_id,
        email=admin.email,
        permissions=frozenset(p for p in (admin.permissions or []) if p in ALL_PERMISSIONS),
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def _claims_two_factor(user: dict) -> bool:
    """Did this Clerk session use a second factor?

    Clerk exposes it in different shapes across token versions, so all three
    known spellings are accepted rather than pinning one and silently locking
    every admin out on a Clerk upgrade.
    """
    if user.get("two_factor_enabled") is True:
        return True
    if user.get("tfa") is True:
        return True
    verification = user.get("fva")  # first/second factor age pair, Clerk v2
    if isinstance(verification, (list, tuple)) and len(verification) >= 2:
        # -1 means "never verified" for that factor position.
        return verification[1] != -1
    return False


def _client_ip(request: Request) -> str | None:
    """Best-effort client address for the audit record.

    `X-Forwarded-For` is attacker-controlled, so this is evidence, not proof —
    which is why it is never used for an authorisation decision, only recorded.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def require_admin(permission: str):
    """Dependency factory. `Depends(require_admin("riders.kyc_review"))`.

    Fails fast and loudly at import time on a typo: a permission that is not in
    `ALL_PERMISSIONS` would otherwise produce a route nobody can ever call, and
    it would look exactly like a permissions misconfiguration in production.
    """
    if permission not in ALL_PERMISSIONS:
        raise ValueError(
            f"Unknown admin permission {permission!r}. "
            f"Add it to models/admin_model.ALL_PERMISSIONS first."
        )

    async def dependency(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user: dict = Depends(get_current_user),
    ) -> AdminAccess:
        access = await _resolve_admin(request, db, user)
        if not access.may(permission):
            raise _denied(permission)
        return access

    return dependency


async def current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> AdminAccess:
    """Authenticated as *an* admin, with no particular capability required.

    Only for endpoints whose whole purpose is to tell the caller what they may
    do — the dashboard's own bootstrap call. Never for anything that reads
    business data.
    """
    return await _resolve_admin(request, db, user)
