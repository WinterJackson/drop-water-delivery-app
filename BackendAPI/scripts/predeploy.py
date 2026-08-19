"""Bring the schema up before the new build serves anything.

Point Render's **Pre-Deploy Command** at this:

    python scripts/predeploy.py

Render runs it after the image is built and before any traffic moves; a non-zero
exit aborts the deploy and leaves the previous release serving. That is the
ordering this platform needs and did not have — pushes deploy automatically
while `alembic upgrade` was something a person remembered to run, so the code
could reach production ahead of its own schema. One missing column is
`UndefinedColumn` on every query touching that table.

Two steps, because this repository has two kinds of database and only one of
them is a migration chain:

1. **Upgrade to the last ungated revision.** Never `head`: the head is
   `e6b2c8d40f17`, which drops the legacy single-staff columns and refuses to
   run without `ALLOW_STAFF_COLUMN_DROP=true`. Reaching for `head` would fail
   every deploy. The target is discovered rather than written down, so it does
   not go stale the next time a revision is added.

2. **Verify the models against the database, and fail if they disagree.** Step 1
   is a *no-op* on a database built by `scripts/bootstrap_database.py`, which
   does `create_all` and stamps the head without ever running the chain —
   `alembic_version` then reads `e6b2c8d40f17` and every upgrade has nothing to
   do. That is the deployed database, and it is exactly how a missing column
   reached production while alembic reported itself perfectly up to date. Step 1
   alone would not have caught it. Step 2 is the check that is true of both.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

#: The revision that must stay last, and must never be applied by a deploy.
GATED_REVISION = "e6b2c8d40f17"


def _last_ungated(config: Config) -> str:
    """The revision immediately below the gate, found rather than hardcoded."""
    script = ScriptDirectory.from_config(config)
    gate = script.get_revision(GATED_REVISION)
    parents = gate.down_revision
    if isinstance(parents, (tuple, list)):
        raise SystemExit(
            f"{GATED_REVISION} has several parents; a human should choose the target."
        )
    if not parents:
        raise SystemExit(f"{GATED_REVISION} has no parent — the chain is broken.")
    return parents


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(root, "alembic.ini"))

    target = _last_ungated(config)
    print(f"predeploy: upgrading to {target} (last revision before the gate)", flush=True)
    command.upgrade(config, target)

    print("predeploy: checking the models against the database", flush=True)
    from db.schema_guard import SchemaDriftError, assert_models_match_database
    from db.session import engine

    async def check() -> None:
        try:
            await assert_models_match_database(engine)
        finally:
            await engine.dispose()

    try:
        asyncio.run(check())
    except SchemaDriftError as drift:
        # Printed rather than raised so the deploy log carries the sentence a
        # person needs, not a traceback they have to read past.
        print(f"predeploy: REFUSING THE DEPLOY\n{drift}", file=sys.stderr, flush=True)
        return 1

    print("predeploy: schema is ready", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
