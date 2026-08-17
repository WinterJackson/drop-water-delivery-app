"""A Postgres enum is not a string, and `COALESCE` is where that stops being free.

**What broke.** Both search endpoints answered **500** — but only once the
customer's location was known, which after the discovery fixes is every real
customer:

    GET /api/search/vendors  ->  500
    asyncpg.exceptions.DatatypeMismatchError:
      COALESCE types vendor_business_type and character varying cannot be matched

`services/query_service._within_service_radius` classified a store so it could
apply the right service radius, and treated a NULL `vendor_type` as retail:

    kind = func.coalesce(Vendor.vendor_type, "retail_refill")   # <-- refused
    ...
    and_(kind == "wholesale_b2b", ST_DWithin(..., wholesale_m))  # <-- fine

The second line is correct and the first is not, for a reason worth stating
because it is what makes this invisible. In a **comparison**, the column is on
one side, so SQLAlchemy binds the literal with the *column's* type and Postgres
receives `$2::vendor_business_type`. In `coalesce` there is no such anchor: the
literal binds as `varchar`, and Postgres will not guess which type a
`COALESCE(enum, varchar)` returns — it refuses the statement outright. Half of
one expression was right, which is why nothing looked wrong.

**Why no test caught it.** `tests/conftest.py` yields an `AsyncMock()`, so *no
test in this suite touches a real database*. The statement compiles, every mock
returns what it was told to, and the only thing that ever objected was Postgres,
in production, on the customer's home screen. That is the same gap this platform
refuses everywhere else: a rule enforced by nothing is a rule that holds until
somebody is watching a spinner.

So this file is a static check, deliberately. It cannot type-check SQL in
general; it forbids the one construct that silently loses an enum's type, in
the one place — `coalesce` — where the type has nothing to anchor it.

**The fix is not a cast.** Casting the column to text would work and would also
discard the index on `vendor_type`. Spelling out the NULL keeps the comparison
typed by the column and keeps the branches exhaustive:

    is_wholesale = Vendor.vendor_type == "wholesale_b2b"
    is_retail    = or_(Vendor.vendor_type != "wholesale_b2b",
                       Vendor.vendor_type.is_(None))
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import pkgutil

import pytest
import sqlalchemy as sa

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: Where a request is served from. A migration or a script may legitimately
#: cast its way out of a schema change; these three run for a user.
SERVING = ("services", "routes", "jobs")


def _enum_columns() -> dict[str, str]:
    """`attribute name -> postgres enum type`, by reflection over the models.

    Reflected rather than listed: a column that becomes an enum tomorrow is
    covered without anybody remembering this file exists, and a list would go
    stale in the direction that passes.
    """
    import models

    found: dict[str, str] = {}
    for module in pkgutil.iter_modules(models.__path__):
        mod = importlib.import_module(f"models.{module.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            table = getattr(obj, "__table__", None)
            if table is None:
                continue
            for column in table.columns:
                if isinstance(column.type, sa.Enum):
                    found[column.key] = column.type.name
    return found


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings — including this file's own, which quotes the
    defective line."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _sources():
    for package in SERVING:
        for path in sorted((BACKEND / package).rglob("*.py")):
            yield path.relative_to(BACKEND), ast.parse(_code_only(path))


def _coalesce_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name == "coalesce":
            yield node


def _offends(call: ast.Call, enum_columns: dict[str, str]) -> str | None:
    """A coalesce naming an enum column and a bare literal in the same call."""
    column = next(
        (
            a.attr
            for a in call.args
            if isinstance(a, ast.Attribute) and a.attr in enum_columns
        ),
        None,
    )
    if column is None:
        return None
    literal = next(
        (
            a.value
            for a in call.args
            if isinstance(a, ast.Constant) and isinstance(a.value, str)
        ),
        None,
    )
    if literal is None:
        return None
    return f"coalesce({column}, {literal!r}) — {column} is {enum_columns[column]}"


def test_no_enum_column_is_coalesced_with_a_bare_string():
    enum_columns = _enum_columns()
    offenders: list[str] = []

    for path, tree in _sources():
        for call in _coalesce_calls(tree):
            problem = _offends(call, enum_columns)
            if problem:
                offenders.append(f"{path}:{call.lineno}  {problem}")

    assert not offenders, (
        "Postgres refuses COALESCE(enum, varchar) rather than choosing a result "
        "type, so each of these raises DatatypeMismatchError the first time it "
        "reaches a real database — and nothing in this suite uses one. Compare "
        "against the column instead (which binds the literal with the column's "
        "own type) and spell out the NULL:\n  " + "\n  ".join(offenders)
    )


def test_the_reflection_still_sees_the_column_that_broke():
    """Non-vacuity, first half: the rule must know `vendor_type` is an enum."""
    enum_columns = _enum_columns()
    assert enum_columns.get("vendor_type") == "vendor_business_type"
    # And a plain column must not be in there, or the rule matches everything.
    assert "business_name" not in enum_columns
    assert "total_amount" not in enum_columns


@pytest.mark.parametrize(
    "source, flagged",
    [
        # The shipped defect.
        ('func.coalesce(Vendor.vendor_type, "retail_refill")', True),
        # Same shape, other enums.
        ('func.coalesce(Product.category, "jerrycan")', True),
        ('func.coalesce(Deliverer.kyc_status, "unsubmitted")', True),
        # The fix: a comparison anchors the literal to the column's type.
        ('or_(Vendor.vendor_type != "wholesale_b2b", Vendor.vendor_type.is_(None))', False),
        # Numeric coalesce, which is the overwhelming majority here.
        ("func.coalesce(func.sum(Order.total_amount), 0)", False),
        # An enum coalesced with another column is fine — both sides typed.
        ("func.coalesce(Vendor.vendor_type, Other.vendor_type)", False),
        # Text column with a string default is fine.
        ('func.coalesce(Review.comment, "")', False),
    ],
)
def test_the_guard_can_tell_the_two_apart(source, flagged):
    """Non-vacuity, second half — on synthetic sources, so proving the rule
    bites never involves editing a module that serves requests."""
    enum_columns = _enum_columns()
    tree = ast.parse(source)
    hits = [
        problem
        for call in _coalesce_calls(tree)
        if (problem := _offends(call, enum_columns))
    ]
    assert bool(hits) is flagged, (source, hits)
