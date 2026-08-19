"""The startup check that refuses to serve against a schema the models outrun.

The incident: `Orders.mpesa_discount` and `Orders.rounding_adjustment` were
added to the model and deployed before the columns existed. SQLAlchemy names
every mapped column in its `SELECT`, so that is not a degraded feature — it is
`UndefinedColumn` on every query touching `Orders`, which is the orders list,
the vendor dashboard, dispatch and the admin console simultaneously.

A pre-deploy `alembic upgrade` would not have caught it. This database was built
by `bootstrap_database.py` (`create_all`, then `stamp` at the head), so
`alembic_version` reads `e6b2c8d40f17` while no revision has ever run against
it: every upgrade is a no-op and the schema tracks the models. Asking alembic
what is applied returns "everything" and is wrong. The only question true of
this database is the one the guard asks — has the table got the columns?

These tests drive the guard with a fake connection, because nothing in this
suite touches a database.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.schema_guard import SchemaDriftError, assert_models_match_database


def _engine_returning(rows: list[tuple[str, str]]):
    """An engine whose `information_schema` query yields exactly `rows`."""
    result = MagicMock()
    result.all.return_value = rows

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=result)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=ctx)
    return engine


def _every_mapped_column() -> list[tuple[str, str]]:
    from db.session import Base
    import models  # noqa: F401

    return [
        (name, column.name)
        for name, table in Base.metadata.tables.items()
        for column in table.columns
    ]


@pytest.mark.asyncio
async def test_a_matching_schema_starts():
    await assert_models_match_database(_engine_returning(_every_mapped_column()))


@pytest.mark.asyncio
async def test_the_exact_incident_is_refused():
    """`Orders` without the two columns the model now declares."""
    rows = [
        row for row in _every_mapped_column()
        if row != ("Orders", "mpesa_discount") and row != ("Orders", "rounding_adjustment")
    ]
    with pytest.raises(SchemaDriftError) as exc:
        await assert_models_match_database(_engine_returning(rows))

    message = str(exc.value)
    assert "Orders.mpesa_discount" in message
    assert "Orders.rounding_adjustment" in message


@pytest.mark.asyncio
async def test_a_missing_table_is_refused():
    rows = [row for row in _every_mapped_column() if row[0] != "Saved_Locations"]
    with pytest.raises(SchemaDriftError) as exc:
        await assert_models_match_database(_engine_returning(rows))
    assert "Saved_Locations" in str(exc.value)


@pytest.mark.asyncio
async def test_a_column_the_database_has_spare_is_fine():
    """The safe half of expand/contract.

    `Vendor.staff_clerk_id` is exactly this today: still in the database, kept
    deliberately so a rollback cannot lose anybody's access. Refusing to boot on
    a spare column would refuse precisely when it is supposed to be there.
    """
    rows = _every_mapped_column() + [
        ("Vendors", "a_column_no_model_declares"),
        ("A_Table_No_Model_Declares", "id"),
    ]
    await assert_models_match_database(_engine_returning(rows))


@pytest.mark.asyncio
async def test_the_escape_hatch_starts_anyway():
    rows = [row for row in _every_mapped_column() if row != ("Orders", "mpesa_discount")]
    with patch.dict("os.environ", {"ALLOW_SCHEMA_DRIFT": "true"}):
        await assert_models_match_database(_engine_returning(rows))


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "false", "0", "no", "  "])
async def test_the_hatch_is_shut_unless_deliberately_opened(value):
    rows = [row for row in _every_mapped_column() if row != ("Orders", "mpesa_discount")]
    with patch.dict("os.environ", {"ALLOW_SCHEMA_DRIFT": value}):
        with pytest.raises(SchemaDriftError):
            await assert_models_match_database(_engine_returning(rows))


def test_both_processes_run_the_check():
    """The API and the worker, because drift breaks a sweep as surely as a request."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for module in ("main.py", "worker.py"):
        source = (root / module).read_text(encoding="utf-8")
        assert "assert_models_match_database" in source, f"{module} does not run the check"


@pytest.mark.asyncio
async def test_an_unreachable_database_does_not_block_startup():
    """Different fact, opposite response.

    Drift is caused by the deploy and never heals — it should stop the deploy.
    A database that is briefly unreachable does heal, and refusing to boot would
    turn seconds of unavailability into a failed release and a restart loop.
    """
    engine = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=OSError("connection refused"))
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=ctx)

    await assert_models_match_database(engine)   # does not raise
