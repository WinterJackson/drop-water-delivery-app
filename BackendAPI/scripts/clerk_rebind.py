#!/usr/bin/env python
"""Find and repair rows still bound to a retired Clerk instance.

A Clerk subject (`user_2x8b…`) is only meaningful inside the instance that
issued it. Move the platform to a different Clerk application — because the old
one belonged to an email address nobody can sign into any more, which is what
happened here — and every stored `clerk_id` becomes a pointer into a directory
the backend no longer talks to. The row is not corrupt; it is addressed to
somebody who, as far as the new instance is concerned, does not exist.

There is no way to translate an old subject into a new one. Clerk mints ids
independently per instance, and the same human signing into the new application
gets an entirely unrelated id. So the repair is always the same shape: the
person signs in once against the new instance, and their row is repointed at
whatever subject they were given.

    # What is still bound, and to how many rows
    python scripts/clerk_rebind.py audit

    # After they have signed in once against the new instance
    python scripts/clerk_rebind.py repoint --table Users \\
        --email winterjacksonwj@gmail.com --clerk-id user_3aBc…

`clerk_id` is `NOT NULL` on most of these tables, so "unbind and let it rebind"
is not available — the column has to hold *something*, and that something has to
be a real subject from the live instance.

Administrators need none of this: `Admin_Users` rows bind by email on first
sign-in (`bind_admin_for_caller`), so a role granted under the old instance
attaches itself to the new account with no intervention.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from db.session import AsyncSessionLocal  # noqa: E402

#: Every table that stores a Clerk subject, and the column holding it. Kept
#: explicit rather than discovered from `information_schema`: a column named
#: `clerk_id` on a table nobody thought about is exactly the row that gets
#: silently rewritten by a clever script.
BOUND_COLUMNS: tuple[tuple[str, str, str | None], ...] = (
    ("Users", "clerk_id", "email"),
    ("Deliverers", "clerk_id", "email"),
    ("Vendors", "clerk_id", "email"),
    ("Admin_Users", "clerk_id", "email"),
    ("Vendor_Staff", "clerk_id", "email"),
    ("reviews", "customer_clerk_id", None),
    ("bottle_ledger_entries", "actor_clerk_id", None),
)


async def cmd_audit() -> int:
    async with AsyncSessionLocal() as session:
        print("Rows carrying a Clerk subject:\n")
        total = 0

        for table, column, label in BOUND_COLUMNS:
            try:
                bound = (
                    await session.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NOT NULL')
                    )
                ).scalar() or 0
                rows = (
                    await session.execute(text(f'SELECT count(*) FROM "{table}"'))
                ).scalar() or 0
            except Exception as exc:  # table or column absent on this schema
                print(f"  {table:<16} skipped ({type(exc).__name__})")
                continue

            total += bound
            print(f"  {table:<16} {bound} of {rows} rows bound")

            if bound and label:
                detail = (
                    await session.execute(
                        text(
                            f'SELECT "{column}", "{label}" FROM "{table}" '
                            f'WHERE "{column}" IS NOT NULL ORDER BY "{label}" LIMIT 20'
                        )
                    )
                ).all()
                for subject, who in detail:
                    # A real Clerk subject is `user_` plus ~27 base58 characters.
                    # Anything much shorter is seed data, and seed data needs no
                    # repair — it was never a person.
                    kind = "seed?" if len(subject or "") < 24 else "real "
                    print(f"      [{kind}] {subject:<34} {who}")

        print(f"\n{total} bound row(s) in total.")
        if total:
            print(
                "\nEach one whose subject came from the retired instance must be\n"
                "repointed after that person signs in against the live instance:\n"
                "  python scripts/clerk_rebind.py repoint --table Users \\\n"
                "      --email them@example.com --clerk-id user_<new subject>"
            )
    return 0


async def cmd_repoint(table: str, email: str, clerk_id: str, apply: bool) -> int:
    known = {name for name, _, _ in BOUND_COLUMNS}
    if table not in known:
        print(f"Unknown table {table!r}. Choose one of: {', '.join(sorted(known))}")
        return 2

    column = next(col for name, col, _ in BOUND_COLUMNS if name == table)
    email = email.strip().lower()

    if not clerk_id.startswith("user_"):
        print(f"{clerk_id!r} does not look like a Clerk subject (expected `user_…`).")
        return 2

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(f'SELECT "{column}", email FROM "{table}" WHERE lower(email) = :e'),
                {"e": email},
            )
        ).all()

        if not rows:
            print(f"No row in {table} with the address {email}.")
            return 1
        if len(rows) > 1:
            # Repointing the wrong one of a duplicate pair is worse than
            # refusing: it hands one person's history to another.
            print(f"{len(rows)} rows in {table} share that address. Resolve by hand.")
            return 1

        current = rows[0][0]
        print(f"{table}.{column} for {email}:")
        print(f"  {current}  →  {clerk_id}")

        if current == clerk_id:
            print("Already pointing there. Nothing to do.")
            return 0

        if not apply:
            print("\nDry run. Re-run with --apply to write it.")
            return 0

        await session.execute(
            text(f'UPDATE "{table}" SET "{column}" = :new WHERE lower(email) = :e'),
            {"new": clerk_id, "e": email},
        )
        await session.commit()

    print("\nRepointed. That account can sign in again.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("audit", help="Show every row bound to a Clerk subject")

    repoint = sub.add_parser("repoint", help="Point one row at a new Clerk subject")
    repoint.add_argument("--table", required=True)
    repoint.add_argument("--email", required=True)
    repoint.add_argument("--clerk-id", required=True)
    repoint.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    if args.command == "audit":
        return asyncio.run(cmd_audit())
    if args.command == "repoint":
        return asyncio.run(cmd_repoint(args.table, args.email, args.clerk_id, args.apply))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
