"""Build a Drop database from nothing: extensions, schema, then stamp.

**Why this exists rather than `alembic upgrade head`.**

The migration chain cannot create this database. Sixty-five revisions, two
bases, and not one of them creates `Vendors`, `Users`, `Orders` or `Products` —
the core tables predate Alembic and were built out-of-band, so every revision in
the chain *alters* a schema no revision ever *creates*. Running `upgrade head`
against an empty database fails on the first `ALTER TABLE`.

That was invisible for as long as there was exactly one database and nobody ever
made a second. It stops being invisible the moment you want a local one, a
staging one, or a new provider — and it means the repository could not rebuild
production from scratch if it had to.

`db/session.py` says there is deliberately no `create_all` helper, and it is
right about the case it describes: calling it against a database that already
has a migration history builds something no migration produced, and it diverges
silently. That warning is about an *existing* database. This is the other case —
an empty one — where `create_all` from the models is the only source of truth
there is, and the schema it produces is by construction the schema the code
expects.

The three steps, in order, and none of them optional:

1. **Extensions.** PostGIS is required by 44 spatial calls across `services/`
   and `routes/`, and no migration creates it — it was enabled by hand on the
   original database and never written down, so any fresh database failed at the
   first `Geography` column with no clue why. `pg_trgm` is created by
   `a7f4e29b81c6`, and is created here too so the order cannot matter.
2. **Schema**, from `Base.metadata`, which every model registers against.
3. **Stamp** at the Alembic head, recording that this database is current so the
   next real migration applies cleanly on top.

Refuses outright if the database already has an `alembic_version` row. This
script is for empty databases; against a live one it would be `create_all`
exactly as `db/session.py` warns.

Usage — the target comes from `DATABASE_URL`, whatever provider it names:

    python scripts/bootstrap_database.py
    python scripts/bootstrap_database.py --stamp-at f7e3b91c8d24   # skip the gated drop
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

#: Extensions the schema needs before a single table can be created.
REQUIRED_EXTENSIONS = ("postgis", "pg_trgm")

#: The last revision before the gated single-staff column drop. `CLAUDE.md`:
#: "Routine deploys should target `f7e3b91c8d24`." A database bootstrapped today
#: is built from the current models, which no longer carry those columns, so the
#: head is the honest stamp — but the flag is here because a deployment that has
#: not accepted the drop needs to say so.
DEFAULT_STAMP = "head"


async def _bootstrap(database_url: str, stamp_at: str, force: bool) -> int:
    # Imported here, after `sys.path` is set, and *before* the engine is built so
    # every model has registered against `Base.metadata`.
    from db.session import Base
    import models

    # Imported for its side effect: `models/__init__` imports every model
    # module, and each one registers a mapper against `Base.metadata`. Without
    # this the metadata is empty and `create_all` silently creates nothing.
    assert models is not None

    url = make_url(database_url)
    print(f"target   : {url.host}:{url.port or 5432}/{url.database}")

    # The same TLS decision the application makes, imported rather than repeated.
    # This script had its own copy — `ssl=True` for any non-loopback host — which
    # verified against the system trust store and therefore could not reach a
    # provider with a private CA. It failed on Supabase while the application,
    # correctly configured, would have connected: a bootstrap that cannot reach
    # the database it is meant to build, for a reason that lives in a second
    # implementation of a rule that already had one.
    from db.session import _requires_tls, _tls_context

    connect_args = {}
    if _requires_tls(database_url):
        connect_args["ssl"] = _tls_context()

    engine = create_async_engine(database_url, connect_args=connect_args)

    try:
        async with engine.begin() as conn:
            existing = await conn.execute(
                text("SELECT to_regclass('public.alembic_version')")
            )
            if existing.scalar() is not None:
                version = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = version.first()
                if row and not force:
                    print(
                        f"\nREFUSED: this database already has a migration history "
                        f"(at {row[0]}).\n"
                        "         Bootstrapping is for empty databases. Running "
                        "`create_all` here would\n"
                        "         build tables no migration produced — see the note in "
                        "`db/session.py`.\n"
                        "         Use `alembic upgrade head` instead."
                    )
                    return 1

            for extension in REQUIRED_EXTENSIONS:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
                print(f"extension: {extension}")

            await conn.run_sync(Base.metadata.create_all)
            print(f"schema   : {len(Base.metadata.tables)} tables created")
    finally:
        await engine.dispose()

    return 0


def _stamp(stamp_at: str) -> None:
    """Record the revision, through Alembic rather than by writing the row.

    Deliberately outside the event loop above. `alembic/env.py` runs its own
    `asyncio.run`, and asyncio refuses to nest one inside another — calling this
    from the coroutine died with `asyncio.run() cannot be called from a running
    event loop` *after* the schema had been created, which is the worst place to
    fail: a built database with no version row, which the next run then refuses
    to touch.
    """
    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command.stamp(Config(os.path.join(root, "alembic.ini")), stamp_at)
    print(f"stamped  : {stamp_at}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stamp-at",
        default=DEFAULT_STAMP,
        help="Alembic revision to record. Default 'head'.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if a migration history exists. Almost never correct.",
    )
    args = parser.parse_args()

    from db.session import database_url as configured_url

    target = configured_url()
    if not target:
        print("DATABASE_URL is not set. Point it at the database to build.")
        return 1

    result = asyncio.run(_bootstrap(target, args.stamp_at, args.force))
    if result != 0:
        return result

    _stamp(args.stamp_at)
    print("\nReady. Seed it with:  python -m seed.seed_data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
