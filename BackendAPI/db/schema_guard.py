"""Refuse to serve when the models declare a column the database has not got.

**What this is for.** Deploys here are automatic on push; the schema is not
carried with them. So the running code can be ahead of the database, and
SQLAlchemy names every mapped column in its `SELECT` — one missing column turns
*every* query on that table into `UndefinedColumn`. Not one screen: the orders
list, the vendor's dashboard, dispatch, the admin console, all at once.

That happened. `Orders.mpesa_discount` and `Orders.rounding_adjustment` were
added to the model and deployed before the column existed.

**Why a pre-deploy `alembic upgrade` would not have caught it.** This database
was built by `scripts/bootstrap_database.py` — `Base.metadata.create_all`, then
`stamp` at the head — so `alembic_version` reads `e6b2c8d40f17` while the
migration chain has never run against it. Every `alembic upgrade` is therefore a
no-op, and its schema tracks the *models* rather than the revisions. A guard
that asks alembic what is applied would have answered "everything" and been
wrong. The only question that is actually true of this database is the one asked
here: does the table have the columns the mapper is about to select?

**Why it fails closed.** A missing column is not a degraded service, it is a
guaranteed 500 on every request touching that table. Refusing to start is
strictly better: the instance never passes its health check, the platform keeps
serving from the previous release, and the deploy fails loudly instead of the
product failing quietly.

**Unreachable is not the same as wrong.** A connection failure here is logged
and allowed through: drift is caused by the deploy and never heals, so it should
stop the deploy, while a database that is briefly unreachable does heal and
refusing to boot would turn seconds of unavailability into a failed release and
a restart loop. The process could not serve a request without a database anyway;
this check does not need to be what decides that.

**Only one direction is checked.** A column the database has and the model does
not is harmless — the mapper never names it — and flagging it would refuse to
boot during the safe half of an expand/contract migration, which is exactly when
the extra column is supposed to be there.

`ALLOW_SCHEMA_DRIFT=true` is the escape hatch, in the spirit of
`ALLOW_STAFF_COLUMN_DROP`: named, deliberate, and set for one deploy rather than
carried permanently. It exists because a false positive in this guard would
otherwise mean an outage that only a code change could clear.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)


class SchemaDriftError(RuntimeError):
    """The mapper would select columns that do not exist."""


def _hatch_open() -> bool:
    return os.getenv("ALLOW_SCHEMA_DRIFT", "").strip().lower() in ("1", "true", "yes")


async def assert_models_match_database(engine) -> None:
    """Raise `SchemaDriftError` if any mapped table or column is absent.

    One `information_schema` query for the whole database — this runs once per
    process at boot and must not become a per-table round trip.
    """
    import importlib

    from db.session import Base

    # Imported for its side effect: `models/__init__.py` is what registers every
    # mapped class on `Base.metadata`, and without it this walks a half-empty
    # metadata and cheerfully reports no drift. `import_module` rather than a
    # plain `import models`, because that binds a name nothing reads and
    # `test_no_undefined_names.py` fails the build on exactly that — correctly,
    # since an unused import is a name in scope. Here the *call* is the point.
    importlib.import_module("models")

    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).all()
    except Exception as unreachable:  # noqa: BLE001 — any driver or network error
        # Not being able to *ask* is a different fact from having asked and
        # found the schema wrong, and it wants the opposite response.
        #
        # Drift is caused by the deploy and never fixes itself, so it should
        # fail the deploy. A database that is briefly unreachable is an
        # infrastructure blip that does heal, and turning it into a refusal to
        # boot converts a few seconds of unavailability into a failed release
        # and a restart loop. The application was already unable to serve a
        # request without a database; this check does not need to be the thing
        # that decides that.
        logger.error(
            "Schema check skipped — the database could not be reached at startup: %s",
            unreachable,
        )
        return

    live: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        live.setdefault(table_name, set()).add(column_name)

    missing_tables: list[str] = []
    missing_columns: list[str] = []

    for name, table in sorted(Base.metadata.tables.items()):
        if name not in live:
            missing_tables.append(name)
            continue
        absent = sorted({column.name for column in table.columns} - live[name])
        if absent:
            missing_columns.extend(f"{name}.{column}" for column in absent)

    if not missing_tables and not missing_columns:
        logger.info(
            "Schema check passed: %d mapped tables, every column present.",
            len(Base.metadata.tables),
        )
        return

    detail = []
    if missing_tables:
        detail.append("tables absent: " + ", ".join(missing_tables))
    if missing_columns:
        detail.append("columns absent: " + ", ".join(missing_columns))
    message = (
        "SCHEMA DRIFT — the models declare things this database does not have, so "
        "every query touching them would fail: " + "; ".join(detail) + ". "
        "Apply the migration (or the equivalent ALTER) before this build serves "
        "traffic. Set ALLOW_SCHEMA_DRIFT=true for a single deploy only if you have "
        "decided the affected tables are not reachable."
    )

    if _hatch_open():
        logger.error("%s  [ALLOW_SCHEMA_DRIFT=true — starting anyway]", message)
        return

    raise SchemaDriftError(message)
