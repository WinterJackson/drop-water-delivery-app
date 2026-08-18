"""A store's position is four columns that move together, and a cache that cannot hide it.

Two defects sat behind one symptom. The customer app showed

    ⚠️  Limited Coverage Area
        No vendors currently deliver to your location.

to an account with **six deliverable retail shops inside 2.5 km**, the nearest
1.87 km away. Neither the radius nor the account state was involved.

**1. Three writers, three different subsets.** `lat`, `lng`, `location` and
`h3_index_res8` all describe where a store is. `create_vendor` wrote three of
them and not `location`; the onboarding update branch in `auth_routes` wrote
three of them and not `h3_index_res8`; only `vendor_management_service` wrote
all four. The onboarding branch is the one every real vendor takes, so **21 of
23 stores on the database had a NULL H3 cell.**

**2. A pre-filter that could reject.** Every discovery query pruned on that cell
with a bare `Vendor.h3_index_res8.in_(cells)`. `NULL IN (...)` is NULL, never
true, so all 21 dropped out *before* the exact `ST_DWithin` ran — the test the
comments describe as authoritative and the one thing on the query that was
actually correct.

The fix is both halves, and this file is both halves:

* a position is written in one place, so the columns cannot drift apart again;
* the ring may *skip* rows and may never *reject* them, so correctness does not
  depend on a backfill having run — which is the only reason the defect could
  reach a customer in the first place.

Nothing in this suite touches a real database (`tests/conftest.py` yields an
`AsyncMock()`), so a filter that silently matches no rows is invisible to every
behavioural test here. These are static and compiled-SQL assertions for exactly
that reason.
"""

import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: The four columns that say where a store is. A writer touching any of them is
#: making a statement about position and must make the whole statement.
POSITION_COLUMNS = {"lat", "lng", "location", "h3_index_res8"}

#: The one function allowed to write them.
THE_WRITER = "set_vendor_position"

SOURCE_DIRS = ("services", "routes", "jobs")


def _python_files():
    for directory in SOURCE_DIRS:
        for path in sorted((BACKEND / directory).rglob("*.py")):
            yield path


def _strip_comments_and_docstrings(tree: ast.AST, source: str) -> str:
    """Source with docstrings removed, so prose describing a defect is not read
    as the defect. An earlier guard in this suite flagged `vendor_upload_image`
    because a schema name appeared in its docstring."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                spans.append((first.lineno, first.end_lineno))
    lines = source.splitlines()
    for start, end in spans:
        for i in range(start - 1, min(end, len(lines))):
            lines[i] = ""
    return "\n".join(l.split("#", 1)[0] for l in lines)


# ─────────────────────────────────────────────────────────────────────────────
# 1. The ring is a pre-filter: it may skip a row, never reject one.
# ─────────────────────────────────────────────────────────────────────────────

def test_no_query_prunes_vendors_on_a_bare_h3_membership_test():
    """`Vendor.h3_index_res8.in_(cells)` on its own deletes every unindexed store.

    The column is a *cache* of a fact `location` already holds, kept so Postgres
    can discard most of the table on a cheap string index before the exact
    `ST_DWithin`. Written as a bare membership test it stops being a pre-filter
    and becomes a second, unreviewed radius — one that answers "no" for any row
    whose cache was never written, which was 21 of 23.

    `in_search_cells` is the only permitted spelling.
    """
    offenders = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if "h3_index_res8" not in source:
            continue
        code = _strip_comments_and_docstrings(ast.parse(source), source)
        for lineno, line in enumerate(code.splitlines(), start=1):
            if re.search(r"Vendor\.h3_index_res8\s*\.\s*in_\(", line):
                offenders.append(f"{path.relative_to(BACKEND)}:{lineno}: {line.strip()}")

    # `in_search_cells` itself is where the membership test legitimately lives.
    offenders = [o for o in offenders if "vendor_service.py" not in o]

    assert not offenders, (
        "A vendor discovery query prunes on the H3 cache with a bare `.in_(...)`, "
        "which rejects every store whose cell has never been written rather than "
        "letting it fall through to `ST_DWithin`. Use `in_search_cells(cells)`.\n  "
        + "\n  ".join(offenders)
    )


def test_the_ring_predicate_admits_a_store_with_no_cached_cell():
    """Compiled against PostgreSQL, so the assertion is about the SQL rather than
    about how the Python happens to be spelled.

    An earlier guard in this suite pinned a mechanism instead of a rule and
    failed on the correct fix exactly as loudly as on a regression. This one
    reads the statement Postgres would actually receive.
    """
    from sqlalchemy.dialects import postgresql

    from services.vendor_service import in_search_cells

    compiled = str(
        in_search_cells(["887a6e0b0bfffff", "887a6e0b3bfffff"]).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "IS NULL" in compiled.upper(), (
        "The ring pre-filter does not admit a store whose H3 cell is NULL, so an "
        f"unindexed store is invisible to discovery. Compiled to: {compiled}"
    )
    assert "h3_index_res8" in compiled, compiled


@pytest.mark.parametrize(
    "function_name",
    [
        "get_nearby_vendors",
        "get_top_rated_vendors",
        "get_vendors_by_type_service",
        "get_top_brands_service",
        "get_vendor_directory",
    ],
)
def test_every_discovery_query_still_carries_the_exact_distance_test(function_name):
    """The ring is allowed to be loose only because `ST_DWithin` follows it.

    Making the pre-filter NULL-tolerant is safe precisely because the exact test
    is what decides. If one of these ever loses its `ST_DWithin`, the looser ring
    stops being an optimisation and starts being a hole — a store 400 km away in
    a neighbouring cell would be listed as deliverable.
    """
    source = (BACKEND / "services" / "vendor_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name
        ),
        None,
    )
    assert node is not None, f"{function_name} has gone; update this test with it"

    body = ast.get_source_segment(source, node) or ""
    # Either spelling: the literal test, or `within_service_radius`, which is
    # `ST_DWithin` applied per vendor type inside one predicate.
    assert "ST_DWithin" in body or "within_service_radius" in body, (
        f"`{function_name}` prunes on the H3 ring but no longer applies an exact "
        "distance test. The ring over-reaches the circle it approximates on "
        "purpose, so without the exact test it lists undeliverable stores."
    )


def test_a_mixed_type_listing_measures_each_store_against_its_own_radius():
    """A list that spans both business models cannot be bounded by one figure.

    2.5 km and 15 km are not two settings of one rule, they are the rule for two
    different kinds of store. `get_vendor_directory` picked whichever applied to
    the type filter and fell back to the wider one — so on "All", which is the
    screen's default, refill shops were listed up to **15 km**. Each opened,
    showed a catalogue, filled a basket and was refused at checkout by the very
    radius the directory exists to express.

    `within_service_radius` is the per-row predicate: it measures each store
    against its own type's limit inside one query.
    """
    source = (BACKEND / "services" / "vendor_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.get_source_segment(source, node) or ""
        # Query builders only. `in_search_cells` is a predicate whose *docstring*
        # explains why `ST_DWithin` has to follow it — prose about the rule read
        # as a violation of it.
        if "select(Vendor)" not in body:
            continue
        if "ST_DWithin" not in body and "within_service_radius" not in body:
            continue
        # A query pinned to one type may use that type's own figure directly.
        if re.search(r"Vendor\.vendor_type\s*==", body):
            continue
        if "within_service_radius" not in body:
            offenders.append(f"services/vendor_service.py::{node.name}")

    assert not offenders, (
        "A discovery query spans both vendor types but bounds every row at a "
        "single distance. Retail is 2.5 km and wholesale is 15 km; use "
        "`within_service_radius(point)`, which measures each row against its "
        "own type's limit:\n  " + "\n  ".join(offenders)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. A position is written in one place.
# ─────────────────────────────────────────────────────────────────────────────

def _vendor_position_writes(tree: ast.AST):
    """(function name, variable, columns written) for every function that assigns
    a position column on something named like a vendor."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        written = {}
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
                    continue
                if target.attr not in POSITION_COLUMNS:
                    continue
                if "vendor" not in target.value.id.lower():
                    continue
                written.setdefault(target.value.id, set()).add(target.attr)
        for variable, columns in written.items():
            found.append((node.name, variable, columns))
    return found


def test_a_vendors_position_is_written_only_through_the_one_function():
    """Any function that sets one position column must set all four.

    This is the rule the three writers broke, in three different ways, and the
    reason 21 of 23 rows were internally inconsistent. Stated as "all four or
    none" rather than "call this function", so an inlined copy that happens to
    be correct today still fails: the next edit to it is what actually causes
    the drift, and by then nothing points at the original.
    """
    offenders = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if not any(c in source for c in ("h3_index_res8", ".location =", ".lat =")):
            continue
        for function_name, variable, columns in _vendor_position_writes(ast.parse(source)):
            if function_name == THE_WRITER:
                continue
            if columns and columns != POSITION_COLUMNS:
                missing = ", ".join(sorted(POSITION_COLUMNS - columns))
                offenders.append(
                    f"{path.relative_to(BACKEND)}::{function_name} writes "
                    f"{sorted(columns)} on `{variable}` but not {missing}"
                )

    assert not offenders, (
        "A vendor's position was written in pieces. All four of "
        f"{sorted(POSITION_COLUMNS)} describe the same fact and must be written "
        f"together — call `vendor_service.{THE_WRITER}(vendor, lat, lng)`.\n  "
        + "\n  ".join(offenders)
    )


def test_the_one_writer_writes_all_four_columns():
    """Non-vacuity for the test above: if `set_vendor_position` itself stopped
    writing one of the four, every caller would be silently wrong and the
    all-four rule would still pass, because it exempts this function by name."""
    source = (BACKEND / "services" / "vendor_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == THE_WRITER
    )
    written = {
        target.attr
        for stmt in ast.walk(node)
        if isinstance(stmt, ast.Assign)
        for target in stmt.targets
        if isinstance(target, ast.Attribute)
    }
    missing = POSITION_COLUMNS - written
    assert not missing, f"`{THE_WRITER}` no longer writes: {sorted(missing)}"


def test_the_writer_derives_the_cache_columns_rather_than_taking_them():
    """`location` and `h3_index_res8` are derived from the pair of scalars.

    Accepting them as arguments would let a caller pass a geography and a cell
    that disagree, which is the original defect wearing the fix's clothes.
    """
    source = (BACKEND / "services" / "vendor_service.py").read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == THE_WRITER
    )
    parameters = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
    assert "location" not in parameters and "h3_index_res8" not in parameters, (
        f"`{THE_WRITER}` takes a derived column as a parameter, so a caller can "
        "supply a geography and a cell that disagree with each other."
    )
    body = ast.get_source_segment(source, node) or ""
    assert "latlng_to_cell" in body, f"`{THE_WRITER}` no longer computes the H3 cell"


# ─────────────────────────────────────────────────────────────────────────────
# 3. One rule for a caller with no delivery address.
# ─────────────────────────────────────────────────────────────────────────────

#: Every route that lists something a customer could order, and the module it
#: lives in. Discovered per-module rather than listed per-function, because the
#: last guard of this shape enumerated seven functions by name and the eighth
#: was in a different module.
DISCOVERY_MODULES = (
    "routes/vendor_routes.py",
    "routes/product_routes.py",
    "routes/query_routes.py",
)


@pytest.mark.parametrize("module", DISCOVERY_MODULES)
def test_discovery_resolves_its_origin_through_the_one_resolver(module):
    """No module re-derives "where is this customer".

    `vendor_routes` asked `get_user_coordinates` and bailed on `not coords.lat`
    — which treats a latitude of exactly 0 as absent — while `product_routes`
    asked the same question and served the national catalogue on a miss. Same
    question, three answers, on three surfaces of one screen.
    """
    source = (BACKEND / module).read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(ast.parse(source), source)

    assert "delivery_point.resolve" in code, (
        f"{module} does not resolve its origin through `services/delivery_point`."
    )
    assert "get_user_coordinates" not in code, (
        f"{module} still resolves a delivery point itself. There is one "
        "implementation and this is not it — see `services/delivery_point`."
    )


@pytest.mark.parametrize("module", DISCOVERY_MODULES)
def test_no_discovery_listing_is_served_without_a_delivery_point(module):
    """A miss on the resolver returns nothing, and is never passed through.

    The failure this prevents is not an exception — it is `user_lat=None`
    reaching a service whose radius clause reads "apply the bound when
    coordinates are known", at which point unknown coordinates mean no bound and
    the customer is shown the whole country.
    """
    source = (BACKEND / module).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Route handlers only. The thin `_delivery_point` wrapper *returns* the
        # miss; handling it is its callers' job, which is what this asserts.
        decorators = {ast.unparse(d) for d in node.decorator_list}
        if not any(".get(" in d or ".post(" in d or ".put(" in d for d in decorators):
            continue
        body = ast.get_source_segment(source, node) or ""
        if "delivery_point.resolve" not in body and "_delivery_point(" not in body:
            continue
        if not re.search(r"if\s+point\s+is\s+None", body):
            offenders.append(f"{module}::{node.name}")

    assert not offenders, (
        "A discovery handler resolves a delivery point and does not handle its "
        "absence, so `None` reaches the radius clause and the bound silently "
        "stops applying:\n  " + "\n  ".join(offenders)
    )


def test_the_resolver_refuses_half_a_location():
    """A latitude with no longitude is not half a location.

    Letting one through leaves the radius unapplied, which on the wire is
    indistinguishable from the unbounded behaviour this rule removes.
    """
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from services import delivery_point

    for saved in (None, SimpleNamespace(lat=-1.38, lng=None), SimpleNamespace(lat=None, lng=36.68)):
        with patch.object(delivery_point, "get_user_coordinates", AsyncMock(return_value=saved)):
            assert asyncio.run(delivery_point.resolve(AsyncMock(), "user_x")) is None

    with patch.object(
        delivery_point,
        "get_user_coordinates",
        AsyncMock(return_value=SimpleNamespace(lat=-1.38, lng=36.68)),
    ):
        point = asyncio.run(delivery_point.resolve(AsyncMock(), "user_x"))
    assert point is not None and (point.lat, point.lng) == (-1.38, 36.68)


def test_the_origin_is_never_taken_from_the_caller():
    """`resolve` accepts no coordinates, so no endpoint can be pointed elsewhere.

    Search took `user_lat`/`user_lng` as query parameters and preferred them over
    the saved address — the only surface on the platform measured from the
    handset rather than from the address the water is delivered to. It listed the
    shops that could reach the phone while checkout enforced the shops that could
    reach the house, and the refusal named a distance from an origin the customer
    could not see.
    """
    import inspect

    from services import delivery_point

    parameters = set(inspect.signature(delivery_point.resolve).parameters)
    assert parameters == {"session", "clerk_id"}, (
        "`delivery_point.resolve` takes coordinates from its caller again, so a "
        f"discovery endpoint can be centred anywhere. Signature: {sorted(parameters)}"
    )

    # Route *signatures* only. `user_lat=point.lat` further down is the service
    # function's keyword argument, carrying the origin this module just resolved
    # — the opposite of taking one from the wire.
    offenders = []
    for module in DISCOVERY_MODULES:
        source = (BACKEND / module).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {ast.unparse(d) for d in node.decorator_list}
            if not any(".get(" in d or ".post(" in d or ".put(" in d for d in decorators):
                continue
            declared = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
            leaked = declared & {"user_lat", "user_lng", "lat", "lng"}
            if leaked:
                offenders.append(f"{module}::{node.name} declares {sorted(leaked)}")

    assert not offenders, (
        "A discovery endpoint accepts a client-supplied origin. The radius "
        "decides whether a store may be ordered from at all, so its origin is "
        "the saved delivery address and nothing else:\n  " + "\n  ".join(offenders)
    )


def test_a_zero_coordinate_is_a_location_not_a_miss():
    """`if not coords.lat` was the guard in four vendor endpoints.

    Latitude 0 is the equator and longitude 0 is the prime meridian; both are
    real places, and `not 0.0` is True. Kenya straddles the equator, so this is
    not a theoretical coordinate here — it is about 200 km from Nairobi.
    """
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from services import delivery_point

    saved = SimpleNamespace(lat=0.0, lng=36.68)
    with patch.object(delivery_point, "get_user_coordinates", AsyncMock(return_value=saved)):
        point = asyncio.run(delivery_point.resolve(AsyncMock(), "user_x"))

    assert point is not None, (
        "A customer on the equator resolves to no delivery point, so discovery "
        "serves them nothing at all."
    )
    assert (point.lat, point.lng) == (0.0, 36.68)
