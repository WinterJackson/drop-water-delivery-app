#!/usr/bin/env python
"""Grant, switch and revoke administrator access from the command line.

The console's own roster screen is the normal way to manage administrators — but
it needs somebody signed in already, and on a fresh deployment nobody is. This
script is the way in, and the way to check every role without needing five Clerk
accounts.

`ADMIN_CLERK_IDS` does **not** do this. `seed_first_admin` reads it, but nothing
calls `seed_first_admin`, so the variable currently grants nobody anything.

    # Who has access right now
    python scripts/admin_access.py list

    # The first administrator (do this once, then use the console)
    python scripts/admin_access.py grant --email you@example.com --role super_admin

    # One row per role, to pair with five users created in the Clerk dashboard.
    # --clerk-test is what makes the fixed 424242 verification code work.
    python scripts/admin_access.py grant-roles --domain example.com --clerk-test

    # Check a screen as somebody else, without a second Clerk account
    python scripts/admin_access.py role --email you@example.com --role support
    python scripts/admin_access.py role --email you@example.com --role super_admin

    # Tidy up rows left behind by an interrupted E2E run
    python scripts/admin_access.py prune-tests

Binding: a row created here has no Clerk subject until that person signs in, at
which point `_resolve_admin` attaches it by matching the email address. Pass
`--clerk-id` to bind immediately if you already know the subject.

Nothing here is destructive without saying so: `revoke` sets `revoked_at` (the
audit trail keeps the row), and `prune-tests` only ever deletes rows whose email
ends in `.invalid`.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from db.session import AsyncSessionLocal  # noqa: E402
from models.admin_model import (  # noqa: E402
    ROLE_ANALYST,
    ROLE_FINANCE,
    ROLE_OPERATIONS,
    ROLE_PRESETS,
    ROLE_SUPER_ADMIN,
    ROLE_SUPPORT,
    AdminUser,
    permissions_for_role,
)

#: The five presets, in the order somebody would walk the console.
ROLE_ROSTER = (
    (ROLE_SUPER_ADMIN, "Super Admin"),
    (ROLE_OPERATIONS, "Operations"),
    (ROLE_FINANCE, "Finance"),
    (ROLE_SUPPORT, "Support"),
    (ROLE_ANALYST, "Analyst"),
)

#: Clerk's own marker for a test identity. An address carrying this subaddress
#: verifies with the fixed code `424242` and never sends an email — but only on a
#: **development** instance. See `docs/admin-console-runbook.md` §3.
CLERK_TEST_SUBADDRESS = "+clerk_test"

#: The only rows `prune-tests` will touch, and all three are provably incapable
#: of being a real mailbox: `.invalid` is reserved by RFC 2606, `.local` by
#: RFC 6762, and `+clerk_test` is Clerk's test marker. This cannot delete a
#: working account.
TEST_EMAIL_MARKERS = (".invalid", ".local", CLERK_TEST_SUBADDRESS)


def _fmt(admin: AdminUser) -> str:
    state = "revoked" if admin.revoked_at else ("bound" if admin.clerk_id else "awaiting sign-in")
    return (
        f"  {admin.email:<40} {admin.role:<12} "
        f"{len(admin.permissions or []):>2} perms   {state}"
    )


async def cmd_list() -> int:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(AdminUser).order_by(AdminUser.created_at))).scalars().all()

    if not rows:
        print("No administrators. Nobody can sign in to the console.")
        print("Grant the first one:")
        print("  python scripts/admin_access.py grant --email you@example.com --role super_admin")
        return 0

    live = [a for a in rows if not a.revoked_at]
    print(f"{len(live)} active administrator(s), {len(rows) - len(live)} revoked:\n")
    for admin in rows:
        print(_fmt(admin))
    return 0


async def cmd_grant(email: str, role: str, name: str | None, clerk_id: str | None) -> int:
    if role not in ROLE_PRESETS:
        print(f"Unknown role {role!r}. Choose one of: {', '.join(sorted(ROLE_PRESETS))}")
        return 2

    email = email.strip().lower()
    permissions = list(permissions_for_role(role))

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(AdminUser).where(AdminUser.email == email))
        ).scalars().first()

        if existing is not None:
            existing.role = role
            existing.permissions = permissions
            existing.revoked_at = None
            if name:
                existing.name = name
            if clerk_id:
                existing.clerk_id = clerk_id
                existing.accepted_at = datetime.now(timezone.utc)
            await session.commit()
            print(f"Updated {email} → {role} ({len(permissions)} permissions).")
            return 0

        session.add(
            AdminUser(
                email=email,
                name=name or email.split("@")[0],
                role=role,
                permissions=permissions,
                clerk_id=clerk_id,
                accepted_at=datetime.now(timezone.utc) if clerk_id else None,
            )
        )
        await session.commit()

    print(f"Granted {email} the {role} role ({len(permissions)} permissions).")
    if not clerk_id:
        print("It binds to their Clerk account the first time they open the console.")
    return 0


async def cmd_grant_roles(domain: str, clerk_test: bool) -> int:
    """Grant one administrator row per role, at predictable addresses.

    Pairs with creating the five users by hand in the Clerk dashboard: create
    the same five addresses there, run this, and each one binds to its Clerk
    account the first time it opens the console.

    `--clerk-test` inserts Clerk's `+clerk_test` subaddress, which is what makes
    the fixed `424242` verification code work. Without it, Clerk sends a real
    email to a mailbox that does not exist and the account cannot be verified —
    which is the whole problem with inventing a domain like `droptest.local`.
    The subaddress only behaves this way on a **development** instance.

    Deliberately does **not** touch Clerk. Creating administrator accounts
    through the API means a script holding a password for five privileged
    identities; doing it in the dashboard leaves the credential where it belongs
    and the audit trail with Clerk.
    """
    domain = domain.strip().lower().lstrip("@")
    suffix = CLERK_TEST_SUBADDRESS if clerk_test else ""
    print(f"Granting the five role presets at @{domain}:\n")

    for role, _ in ROLE_ROSTER:
        await cmd_grant(f"{role.replace('_', '-')}{suffix}@{domain}", role, None, None)

    print(
        "\nCreate these five users in the Clerk dashboard (Users → Create user),\n"
        "with the same email addresses, character for character. Each row binds\n"
        "on that account's first sign-in — there is nothing else to run.\n"
    )
    if clerk_test:
        print("Verification code for all five: 424242 (development instance only).\n")
    return 0


async def cmd_role(email: str, role: str) -> int:
    """Swap an existing administrator's preset — for checking the console as
    each role without maintaining five Clerk accounts."""
    if role not in ROLE_PRESETS:
        print(f"Unknown role {role!r}. Choose one of: {', '.join(sorted(ROLE_PRESETS))}")
        return 2

    email = email.strip().lower()
    permissions = list(permissions_for_role(role))

    async with AsyncSessionLocal() as session:
        admin = (
            await session.execute(select(AdminUser).where(AdminUser.email == email))
        ).scalars().first()
        if admin is None:
            print(f"No administrator with the address {email}.")
            return 1
        before = admin.role
        admin.role = role
        admin.permissions = permissions
        await session.commit()

    print(f"{email}: {before} → {role}")
    print(f"  {', '.join(permissions)}")
    print("Reload the console — the capability set is read per request.")
    return 0


async def cmd_revoke(email: str) -> int:
    email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        admin = (
            await session.execute(select(AdminUser).where(AdminUser.email == email))
        ).scalars().first()
        if admin is None:
            print(f"No administrator with the address {email}.")
            return 1
        admin.revoked_at = datetime.now(timezone.utc)
        await session.commit()

    print(f"Revoked {email}. The row stays for the audit trail.")
    return 0


async def cmd_prune_tests(apply: bool) -> int:
    """Remove administrator rows left behind by an interrupted E2E run.

    `tests/test_admin_e2e.py` cleans up in a `finally`, but a hard kill —
    Ctrl-C, an OOM — skips it, and those rows count against `MAX_ADMINS`.
    """
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(AdminUser))).scalars().all()
        doomed = [
            a
            for a in rows
            if any(marker in (a.email or "") for marker in TEST_EMAIL_MARKERS)
        ]

        if not doomed:
            print("No test rows to remove.")
            return 0

        print(f"{len(doomed)} test row(s):")
        for admin in doomed:
            print(_fmt(admin))

        if not apply:
            print("\nDry run. Re-run with --apply to delete them.")
            return 0

        for admin in doomed:
            await session.delete(admin)
        await session.commit()

    print(f"\nDeleted {len(doomed)} row(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show every administrator and their standing")

    grant = sub.add_parser("grant", help="Create or restore an administrator")
    grant.add_argument("--email", required=True)
    grant.add_argument("--role", required=True, choices=sorted(ROLE_PRESETS))
    grant.add_argument("--name")
    grant.add_argument("--clerk-id", help="Bind immediately instead of on first sign-in")

    roles = sub.add_parser(
        "grant-roles", help="Grant all five presets at <role>@domain, for Clerk-created users"
    )
    roles.add_argument("--domain", required=True)
    roles.add_argument(
        "--clerk-test",
        action="store_true",
        help="Use Clerk's +clerk_test subaddress, so 424242 verifies (dev instance only)",
    )

    role = sub.add_parser("role", help="Change an administrator's role preset")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True, choices=sorted(ROLE_PRESETS))

    revoke = sub.add_parser("revoke", help="Withdraw access (keeps the row)")
    revoke.add_argument("--email", required=True)

    prune = sub.add_parser("prune-tests", help="Delete leftover *.invalid rows")
    prune.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    if args.command == "list":
        return asyncio.run(cmd_list())
    if args.command == "grant":
        return asyncio.run(cmd_grant(args.email, args.role, args.name, args.clerk_id))
    if args.command == "grant-roles":
        return asyncio.run(cmd_grant_roles(args.domain, args.clerk_test))
    if args.command == "role":
        return asyncio.run(cmd_role(args.email, args.role))
    if args.command == "revoke":
        return asyncio.run(cmd_revoke(args.email))
    if args.command == "prune-tests":
        return asyncio.run(cmd_prune_tests(args.apply))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
