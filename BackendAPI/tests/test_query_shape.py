"""No request path issues a query per row, and the hot filters have indexes.

Two different failure modes, both invisible until the table is large:

* **A query inside a loop.** One round trip per row, so the cost grows with the
  data and the code looks fine at every review. Batched resolvers already exist
  for the cases that mattered (`admin_review_service._names` resolves every
  vendor and rider in two queries) — this keeps a new one from appearing on a
  path a user waits on.

* **A filter with no index.** `Orders` grows fastest and never shrinks, and its
  most-filtered column had no index that could lead with it: every index
  mentioning `order_status` had something else first, so the re-dispatch sweep
  and the auto-cancel job scanned the whole order history on a schedule.

Sweeps are exempt from the first rule and always will be: `FOR UPDATE … SKIP
LOCKED` with a commit per item is the platform's deliberate pattern for
background work, and it is a query per row on purpose — one poisoned row must
not roll back the batch.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: Paths a user is waiting on. `jobs/` is deliberately absent.
REQUEST_DIRS = ("routes", "services")

#: Modules whose whole purpose is a per-item sweep with its own lock and commit.
SWEEP_MODULES = {
    "services/cod_policy.py",          # releases float from undelivered cash orders
    "services/admin_bottle_service.py",  # per-row repair, each under FOR UPDATE
    "services/broadcast_service.py",    # one send per recipient, by definition
    "services/customer_bottle_service.py",  # dormancy conversion, per customer
    "services/platform_config_service.py",  # settings applied one row at a time
}

DB_CALLS = frozenset({"execute", "scalar", "scalars", "get", "refresh"})
SESSION_NAMES = frozenset({"session", "db", "s"})


def _is_bounded_iterable(node: ast.AST, tree: ast.AST) -> bool:
    """True when the loop runs a fixed number of times regardless of the data.

    `for audience, model in AUDIENCES.items()` is three iterations on a platform
    with three kinds of account, whatever happens to the order table. Two
    queries inside it is six queries, forever — a constant, not an N+1. Treating
    it as one would push the rule into territory where the only way to satisfy
    it is to make the code worse.
    """
    target = node
    if isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
        # `.items()`, `.values()`, `.keys()` — judge the thing they came off.
        target = target.func.value

    if isinstance(target, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return True

    if isinstance(target, ast.Name):
        name = target.id
        # A module-level constant, by this codebase's naming.
        if name.isupper():
            return True
        # …or a local bound to a literal collection in the same module.
        for assign in ast.walk(tree):
            if isinstance(assign, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in assign.targets
            ):
                if isinstance(assign.value, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
                    return True
    return False


def _in_loop_queries(path: pathlib.Path, label: str | None = None) -> list[str]:
    where = label or path.name
    tree = ast.parse(path.read_text())
    found: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        if isinstance(node, (ast.For, ast.AsyncFor)) and _is_bounded_iterable(node.iter, tree):
            continue
        # The loop's own iterable is evaluated once — `for row in (await
        # db.execute(...)).all()` is one query, not one per row.
        iterable = set(ast.walk(node.iter)) if isinstance(node, (ast.For, ast.AsyncFor)) else set()

        for statement in node.body:
            for inner in ast.walk(statement):
                if not isinstance(inner, ast.Await) or inner in iterable:
                    continue
                call = inner.value
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                receiver = call.func.value
                if (
                    call.func.attr in DB_CALLS
                    and isinstance(receiver, ast.Name)
                    and receiver.id in SESSION_NAMES
                ):
                    found.append(f"{where}:{inner.lineno} {receiver.id}.{call.func.attr}(…)")
    return found


def test_no_request_path_queries_once_per_row():
    offenders: list[str] = []
    for directory in REQUEST_DIRS:
        for path in sorted((BACKEND / directory).rglob("*.py")):
            if path.relative_to(BACKEND).as_posix() in SWEEP_MODULES:
                continue
            offenders.extend(
                _in_loop_queries(path, path.relative_to(BACKEND).as_posix())
            )

    # `order_service` genuinely needs three: the atomic per-product stock
    # decrement (`UPDATE … WHERE stock >= qty RETURNING`, which cannot be
    # batched without losing the oversell guard), its inverse on restore, and
    # the payment-callback loop, which resolves one order per CheckoutRequestID.
    allowed_prefixes = ("services/order_service.py",)
    offenders = [o for o in offenders if not o.startswith(allowed_prefixes)]

    assert not offenders, (
        "a query inside a loop on a path a user waits on — resolve the rows in "
        "one query, as `admin_review_service._names` does:\n  "
        + "\n  ".join(offenders)
    )


def test_the_detector_recognises_the_shape_it_looks_for():
    """The negative case, so this cannot pass by matching nothing."""
    import tempfile

    source = (
        "async def f(session, ids):\n"
        "    for i in ids:\n"
        "        row = await session.get(Thing, i)\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        temp = pathlib.Path(handle.name)

    try:
        assert len(_in_loop_queries(temp)) == 1
    finally:
        temp.unlink()


def test_the_detector_does_not_flag_a_batched_resolver():
    """`for x in (await db.execute(...)).all()` is one query for the whole set —
    the fix, not the defect."""
    import tempfile

    source = (
        "async def f(db, ids):\n"
        "    for a, b in (await db.execute(select(T).where(T.id.in_(ids)))).all():\n"
        "        out[a] = b\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        temp = pathlib.Path(handle.name)

    try:
        assert _in_loop_queries(temp) == []
    finally:
        temp.unlink()


# ── Index coverage ────────────────────────────────────────────────────────


#: Every index this platform's hot paths depend on, and the query that needs it.
#: Asserted against the migration rather than a live database so it runs
#: anywhere — the migration is what a deploy actually applies.
REQUIRED_ORDER_INDEXES = {
    "ix_orders_status_created_at": "the re-dispatch sweep and the auto-cancel job",
    "ix_orders_cash_float_rider": "a rider's committed cash float, on every wallet summary",
    "ix_orders_cash_float_vendor": "a store's committed cash float",
}


def test_the_hot_order_filters_are_indexed():
    """`Orders` is the table that grows fastest and never shrinks.

    Each of these was a sequential scan over the whole order history, on a
    schedule or on every open of a wallet screen.
    """
    migrations = "\n".join(
        p.read_text() for p in (BACKEND / "alembic" / "versions").glob("*.py")
    )

    missing = [
        f"{name} — needed for {why}"
        for name, why in REQUIRED_ORDER_INDEXES.items()
        if name not in migrations
    ]
    assert not missing, "hot-path indexes with no migration:\n  " + "\n  ".join(missing)


def test_the_cash_float_indexes_are_partial_on_cash():
    """Cash is the minority of orders and the only subset these queries want.

    A full index would carry every M-Pesa order for no reader, on the busiest
    table on the platform.
    """
    migration = next(
        (BACKEND / "alembic" / "versions").glob("*order_hot_path_indexes.py")
    ).read_text()

    for name in ("ix_orders_cash_float_rider", "ix_orders_cash_float_vendor"):
        block = migration[migration.index(name):]
        block = block[: block.index(")\n\n")] if ")\n\n" in block else block
        assert "postgresql_where" in block and "payment_method = 'cash'" in block, (
            f"{name} is no longer partial on cash orders"
        )


def test_the_index_migration_is_reversible():
    """Every index it creates, it drops."""
    migration = next(
        (BACKEND / "alembic" / "versions").glob("*order_hot_path_indexes.py")
    ).read_text()

    upgrade = migration[migration.index("def upgrade") : migration.index("def downgrade")]
    downgrade = migration[migration.index("def downgrade") :]

    for name in REQUIRED_ORDER_INDEXES:
        assert name in upgrade, f"{name} is not created"
        assert name in downgrade, f"{name} is created but never dropped"
