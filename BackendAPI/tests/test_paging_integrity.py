"""A list a user scrolls returns every row, once, and answers the question asked.

Three failure modes, all of which look like working software right up until the
table is big enough to matter — and all of which reach the user as "the app has
lost my data" rather than as a page boundary.

**The order is not total.** `LIMIT n OFFSET m` says nothing about rows the
`ORDER BY` cannot tell apart, so a query ordered by a discount percentage, a
product name, a timestamp or a full-text rank may return them in a different
sequence on each execution — and page 1 and page 2 *are* separate executions.
Every `.offset(...)` on this API was written that way. See `utils/paging`.

**The client asks for one page and shows it as all of them.** Nine endpoints
took `limit`/`offset` and were called with neither, so each returned the
server's default and the screen rendered it under no end marker. The customer's
order history stopped at 50, their payment history at 50, the offers list at 20,
notifications at 50 in all three apps, and the vendor directory at 50 with no
`offset` parameter existing to ask for more.

**The filter runs on the page.** Once a list is paged, a `.filter()` over the
rows in hand is a filter that lies: "Delivered" answers *no orders* to a customer
whose last delivery was one page back, and then answers differently after they
scroll. Every filter and search over a paged list belongs in the query string.

The tests below are structural — they read the source of the API and of all
three apps — because each of these is invisible to a functional test on a small
fixture, which is precisely how they all shipped.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

#: Where an app's own source lives. Mirrors `test_route_contract.SOURCE_DIRS`.
APP_DIRS = ("app", "components", "hooks", "utils", "lib", "context", "API", "stores", "services")


def _py_sources() -> list[Path]:
    return [
        path
        for directory in ("routes", "services")
        for path in sorted((BACKEND / directory).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _app_files(app: str) -> list[Path]:
    root = ROOT / app
    return [
        path
        for directory in APP_DIRS
        if (root / directory).is_dir()
        for path in sorted((root / directory).rglob("*.ts*"))
        if "node_modules" not in path.parts
    ]


#: Comments and string literals, replaced by blanks of the same length so line
#: numbers survive.
_NOT_CODE = re.compile(
    r"""(//[^\n]*)|(/\*.*?\*/)|('(?:[^'\\\n]|\\.)*')|("(?:[^"\\\n]|\\.)*")|(`(?:[^`\\]|\\.)*`)""",
    re.S,
)


def _code(source: str) -> str:
    """`source` with comments and strings blanked out.

    Every rule below is about what the code *does*, and each is documented in a
    comment beside the thing it forbids — naming the very construct it forbids.
    Scanning raw text made this file fail on its own explanations, which is the
    kind of test that gets an `# noqa` rather than a fix.
    """
    return _NOT_CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)


# ── The order every offset window is measured against ────────────────────────


def _offset_statements(tree: ast.AST) -> list[ast.AST]:
    """Every expression in which `.offset(...)` is called.

    Returns the outermost node of each such chain, so an `.order_by(...)`
    anywhere in the same expression is visible.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.Return, ast.Expr, ast.AugAssign)):
            continue
        if any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "offset"
            for inner in ast.walk(node)
        ):
            found.append(node)
    return found


def test_every_offset_paged_query_orders_through_stable():
    """`.offset(...)` is only meaningful over a total order.

    Postgres is free to return tied rows in any sequence, and two pages are two
    executions. Where it chooses differently between them, a row is served twice
    or skipped entirely, and nothing anywhere reports an error — which is why
    fourteen queries carried this and every test passed.
    """
    offenders: list[str] = []

    for path in _py_sources():
        source = path.read_text()
        if ".offset(" not in source:
            continue
        tree = ast.parse(source)

        for statement in _offset_statements(tree):
            text = ast.get_source_segment(source, statement) or ""
            if "stable(" in text:
                continue
            # A chain built across several statements: accept the function as a
            # whole ordering through `stable`, since that is where it lives.
            enclosing = _enclosing_function(tree, statement)
            whole = ast.get_source_segment(source, enclosing) if enclosing else None
            if whole and "stable(" in whole:
                continue
            offenders.append(f"{path.relative_to(BACKEND)}:{statement.lineno}")

    assert not offenders, (
        "offset paging over a possibly-tied order — wrap the ORDER BY in "
        "`utils.paging.stable(..., key=Model.id)`:\n  " + "\n  ".join(offenders)
    )


def _enclosing_function(tree: ast.AST, target: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(child is target for child in ast.walk(node)):
                return node
    return None


def test_stable_appends_a_tiebreaker_and_keeps_the_caller_ordering():
    from models.order_model import Order
    from utils.paging import stable

    clauses = stable(Order.created_at.desc(), key=Order.id)

    assert len(clauses) == 2, "the caller's clause plus exactly one tiebreaker"
    assert "created_at" in str(clauses[0])
    assert "id" in str(clauses[-1]), "the primary key goes last, not first"


def test_a_paged_query_compiles_to_sql_that_ends_with_the_primary_key():
    """The point of the helper, checked against the SQL rather than the source."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from models.product_model import Product
    from utils.paging import stable

    statement = (
        select(Product)
        .order_by(*stable(Product.discount.desc(), key=Product.id))
        .limit(20)
        .offset(40)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    order_by = sql.split("ORDER BY", 1)[1]

    assert order_by.strip().split("\n")[0].rstrip().endswith('"Products".id DESC')


def test_the_payment_history_is_one_query_over_both_kinds_of_payment():
    """Cash orders write no `payments` row, so the history is a union.

    It used to be two queries merged in Python: the M-Pesa half paged, the cash
    half taking `limit` rows with **no offset**, and the merged list cut back to
    `limit`. Every page therefore repeated the same newest cash orders, and each
    cut discarded up to `limit` real M-Pesa payments that offset would never come
    back for. Invisible while the app only ever asked for page 1 — which it did.
    """
    source = (BACKEND / "routes" / "payment_routes.py").read_text()
    history = source.split("async def payment_history", 1)[1].split("\n@router", 1)[0]

    assert "union_all(" in history, "the two halves must share one window"
    assert "entries.sort(" not in history, "ordering belongs in SQL, not in Python"
    assert "[:limit]" not in history, "trimming after a merge silently drops rows"


# ── Endpoints the apps must actually page ────────────────────────────────────

#: (app, hook file, the route constant it pages) — one entry per list that was
#: being served a single page and rendered as though it were the whole thing.
PAGED_HOOKS = [
    ("drop-customer-app", "hooks/queries/useNotifications.ts", "GET_NOTIFICATIONS"),
    ("drop-customer-app", "hooks/queries/useOrders.ts", "GET_ORDERS"),
    ("drop-customer-app", "hooks/queries/useOrders.ts", "GET_PAYMENT_HISTORY"),
    ("drop-customer-app", "hooks/queries/useProducts.ts", "GET_PRODUCTS_WITH_OFFER"),
    ("drop-customer-app", "hooks/queries/useVendors.ts", "GET_VENDOR_DIRECTORY"),
    ("drop-rider-app", "hooks/queries/useNotifications.ts", "GetNotifications"),
    ("drop-rider-app", "hooks/queries/useRiderData.ts", "GetOrdersPaged"),
    ("drop-vendor-app", "hooks/queries/useNotifications.ts", "GetNotifications"),
    ("drop-vendor-app", "hooks/queries/useVendorRiders.ts", "GetMyRiders"),
]


@pytest.mark.parametrize(
    "app,hook,route", PAGED_HOOKS, ids=[f"{a}:{r}" for a, _, r in PAGED_HOOKS]
)
def test_the_hook_for_a_long_list_is_an_infinite_query(app, hook, route):
    source = (ROOT / app / hook).read_text()

    assert route in source, f"{hook} no longer reaches {route}"
    assert "useInfiniteQuery" in source, (
        f"{app}/{hook} serves {route} with a single request. The endpoint pages; "
        "a screen that asks for one page and draws no end marker is telling the "
        "user that page is everything they have."
    )


def test_no_app_guesses_the_next_offset_from_the_page_count():
    """`allPages.length * size` assumes every page came back full.

    The first that does not — a page shortened by a row deleted underneath, or
    by a server that returned fewer than asked — sends the next offset past rows
    nobody ever sees. Count the rows actually held instead; `nextOffset` does.
    """
    offenders = []
    pattern = re.compile(r"allPages\.length\s*\*")

    for app in APPS:
        for path in _app_files(app):
            source = _code(path.read_text())
            for match in pattern.finditer(source):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}")

    assert not offenders, (
        "next offset derived from the number of pages rather than the rows held "
        "— use `nextOffset(size)` from `utils/paging`:\n  " + "\n  ".join(offenders)
    )


def test_no_screen_flattens_infinite_pages_by_hand():
    """Offset paging re-serves a row at every page boundary.

    A feed that grows at the top — orders, notifications, the bottle ledger —
    shifts every row down by one when something arrives, so the first row of the
    next page is the last row of the one already on screen. `flattenPages` keys
    on the row id and drops the repeat; `.pages.flat()` renders it twice, under a
    duplicate React key, on a list the user is scrolling.
    """
    offenders = []
    pattern = re.compile(r"\.pages[\s?.]*\.?(flat|flatMap)\s*\(")

    for app in APPS:
        for path in _app_files(app):
            if path.name == "paging.ts":
                continue
            source = _code(path.read_text())
            for match in pattern.finditer(source):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}")

    assert not offenders, (
        "pages flattened without de-duplicating — use `flattenPages` from "
        "`utils/paging`:\n  " + "\n  ".join(offenders)
    )


def _guards(text: str) -> bool:
    """True when this expression refuses to ask while a request is in flight.

    Matches the prefix rather than the exact name: a screen paging two lists
    destructures them apart (`isFetchingNextProducts`, `isFetchingNextVendors`),
    and that is the correct shape, not an evasion.
    """
    return "isFetchingNext" in text or "isFetchingMore" in text


def test_every_end_of_list_handler_asks_for_one_page_at_a_time():
    """`onEndReached` fires repeatedly while a long list settles.

    A bare `fetchNextPage()` in it asks for the same page several times over a
    slow connection, which is exactly where the extra requests hurt most.
    """
    offenders = []

    for app in APPS:
        for path in _app_files(app):
            source = _code(path.read_text())
            for match in re.finditer(r"onEndReached=\{([^\n]*)", source):
                handler = match.group(1)
                line = source[: match.start()].count("\n") + 1

                if "keepPaging(" in handler:
                    continue

                # An inline arrow: the guard must be inside it.
                window = source[match.start() : match.start() + 400].split("}}")[0]
                if _guards(window):
                    continue

                # A named handler: follow it to its definition in the same file
                # and read the first few lines of its body. A nested-brace match
                # is not worth writing here — the guard, where it exists, is the
                # handler's opening statement.
                named = re.fullmatch(r"\s*(\w+)\s*\}?\s*", handler)
                if named:
                    definition = re.search(rf"\b{named.group(1)}\s*=", source)
                    if definition and _guards(source[definition.end() : definition.end() + 300]):
                        continue

                offenders.append(f"{path.relative_to(ROOT)}:{line}")

    assert not offenders, (
        "onEndReached without an in-flight guard — use `keepPaging(query)`:\n  "
        + "\n  ".join(offenders)
    )


# ── Filters and searches belong in the query string ──────────────────────────

#: Screens whose list is paged *and* filtered. Each names the filter it must be
#: passing to the server, so a regression to a client-side `.filter()` is caught.
SERVER_SIDE_FILTERS = [
    ("drop-customer-app", "app/(screens)/Orders.tsx", "useOrders(selectedFilter)"),
    ("drop-rider-app", "app/(screens)/Orders.tsx", "statusesForTab(tab)"),
    ("drop-vendor-app", "app/(screens)/RiderManagement.tsx", "status: filter"),
]


@pytest.mark.parametrize(
    "app,screen,marker", SERVER_SIDE_FILTERS, ids=[s for _, s, _ in SERVER_SIDE_FILTERS]
)
def test_a_paged_lists_filter_is_a_query_parameter(app, screen, marker):
    source = (ROOT / app / screen).read_text()
    assert marker in source, (
        f"{app}/{screen} no longer passes its filter to the server. A filter "
        "applied to the loaded pages searches the page in hand and reports "
        "'nothing found' to somebody whose match is one page back — and then "
        "reports differently once they have scrolled."
    )


def test_the_rider_order_tabs_cover_every_status_the_backend_can_return():
    """A status in neither tab is an order that vanishes from the rider's app.

    The two tabs were spelled inline in the screen as two `.filter()` calls and
    between them named ten of eleven statuses. They are now a table the server is
    asked for by name, which is what makes this checkable at all.
    """
    from services.order_service import OrderStatusEnum

    source = (ROOT / "drop-rider-app" / "hooks" / "queries" / "useRiderData.ts").read_text()
    table = source.split("RIDER_ORDER_TABS = {", 1)[1].split("} as const", 1)[0]
    covered = set(re.findall(r"'([a-z_]+)'", table))

    known = {member.value for member in OrderStatusEnum}
    # An unassigned order has no rider, so it cannot appear in a list scoped to
    # `deliverer_id`; it reaches riders through the Trip Radar.
    expected = known - {"unassigned"}

    assert covered == expected, (
        f"rider tabs miss {sorted(expected - covered)} and invent "
        f"{sorted(covered - known)}"
    )


def test_the_customer_order_filters_cover_every_status_the_backend_can_return():
    """Same rule on the customer's side, where the groups drive `?status=`."""
    from services.order_service import OrderStatusEnum

    # The table moved out of `hooks/queries/useOrders.ts` and into
    # `constants/orderStatus.ts`: it is a domain rule, not a hook, and keeping it
    # beside the query meant that reading it pulled in Clerk and React Query.
    # Located rather than hardcoded, so the next move does not silently turn this
    # into a test of a file that no longer holds the table.
    app = ROOT / "drop-customer-app"
    candidates = [
        path
        for path in list((app / "constants").rglob("*.ts")) + list((app / "hooks").rglob("*.ts"))
        if "__tests__" not in path.parts and "ORDER_STATUS_GROUPS = {" in path.read_text()
    ]
    assert len(candidates) == 1, (
        "expected exactly one definition of ORDER_STATUS_GROUPS, found "
        f"{[str(c.relative_to(ROOT)) for c in candidates]}"
    )

    table = candidates[0].read_text().split("ORDER_STATUS_GROUPS = {", 1)[1].split("} as const", 1)[0]
    covered = set(re.findall(r"'([a-z_]+)'", table))

    known = {member.value for member in OrderStatusEnum}
    assert covered == known, (
        f"customer filters miss {sorted(known - covered)} and invent "
        f"{sorted(covered - known)}"
    )


def test_an_unknown_status_is_refused_rather_than_returning_an_empty_page():
    """A typo in a client's filter table must not read as a lost history.

    Passed through, an unknown status produces an empty page, and the only thing
    a screen can render for that is "you have no orders".
    """
    for module, marker in (
        ("routes/cart_routes.py", "async def get_orders_by_id"),
        ("routes/deliverer_routes.py", "async def rider_get_orders"),
    ):
        source = (BACKEND / module).read_text()
        body = source.split(marker, 1)[1].split("\n@router", 1)[0]
        assert "OrderStatusEnum" in body and "400" in body, (
            f"{module} accepts a status it cannot validate"
        )


# ── Search reaches only what the customer can order from ─────────────────────


def test_product_and_vendor_search_are_bounded_by_the_service_radius():
    """Search is discovery, and discovery is bounded by what can be delivered.

    It sorted by distance and never cut, so every product on the platform was a
    search result: the top hit for "20L" could be a shop in another town —
    findable, tappable, and refused at checkout by the one radius that *is*
    enforced. The directory has always filtered this way; search is the screen
    most people actually use.
    """
    source = (BACKEND / "services" / "query_service.py").read_text()

    calls = re.findall(r"where\(_within_service_radius\(user_location\)\)", source)
    assert len(calls) == 2, (
        "both the product search and the vendor search must apply the radius; "
        f"found {len(calls)} call sites"
    )
    # The accessor read is asserted where the predicate now lives, not here.
    # It moved to `dispatch_policy.within_service_radius` so that product
    # discovery could share the one implementation — this module previously had
    # a private copy, and the home grid, which could not reach it, applied no
    # radius at all. Pinning the *name of the module that reads the setting* is
    # what made this assertion fail on a change that made the rule stronger;
    # `tests/test_service_radius.py` asserts the rule itself.
    assert "within_service_radius" in source, (
        "search must apply the shared radius predicate"
    )


def _compiled_radius_predicate() -> str:
    """`_within_service_radius` as the SQL Postgres will actually receive.

    No database is needed to compile a predicate, which matters here: nothing
    else in this suite reaches one, and asserting on source text is how the
    version of this test below the fold came to pass while the endpoint
    returned 500.
    """
    from sqlalchemy import func
    from sqlalchemy.dialects import postgresql
    from geoalchemy2 import Geography

    from services.query_service import _within_service_radius

    point = func.ST_SetSRID(func.ST_MakePoint(36.65, -1.36), 4326).cast(Geography)
    return str(
        _within_service_radius(point).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_the_radius_predicate_still_matches_an_unclassified_store():
    """`vendor_type != 'wholesale_b2b'` is NULL for a NULL column, not true.

    A store nobody has classified must not fall out of *both* branches of the
    OR and disappear from search.

    **This test used to assert `func.coalesce(Vendor.vendor_type` was present,
    and that was the bug.** It pinned one implementation of the rule rather
    than the rule, and the implementation it pinned is one Postgres refuses:
    `COALESCE(vendor_business_type, varchar)` raises `DatatypeMismatchError`,
    so both search endpoints answered 500 for every customer whose location was
    known. A test naming a mechanism cannot tell a correct fix from a
    regression — it failed on the fix exactly as loudly as it would have on a
    real one. See `tests/test_sql_type_safety.py`.

    So the assertion is now on the compiled SQL, which is what the database
    sees, and on the property rather than the spelling: the NULL is named, and
    each vendor type is measured against its own radius.
    """
    sql = _compiled_radius_predicate()

    assert "vendor_type IS NULL" in sql, (
        "the NULL must be named. `!=` is NULL for a NULL column, not true, so "
        "an unclassified store falls out of both branches and vanishes from "
        f"search:\n{sql}"
    )
    assert "coalesce" not in sql.lower(), (
        "Postgres refuses COALESCE(enum, varchar) rather than choosing a "
        f"result type:\n{sql}"
    )
    # Each type against its own radius, both read from the configured rows.
    assert sql.count("ST_DWithin") == 2, sql
    assert "15000.0" in sql and "2500.0" in sql, (
        "wholesale 15 km and retail 2.5 km, through DispatchPolicy's "
        f"accessors:\n{sql}"
    )


def test_three_valued_logic_is_why_the_null_has_to_be_named():
    """The SQL semantics the predicate above depends on, pinned once.

    Run against sqlite because the point is ternary logic, not PostGIS: `!=`
    against a NULL yields NULL, which `WHERE` discards exactly as if it were
    false. This is the whole reason a store with no `vendor_type` needed
    special handling in the first place.
    """
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE v (kind TEXT)")
    db.executemany("INSERT INTO v VALUES (?)", [("wholesale_b2b",), ("retail_refill",), (None,)])

    naive = db.execute("SELECT count(*) FROM v WHERE kind != 'wholesale_b2b'").fetchone()[0]
    assert naive == 1, "the unclassified store is silently dropped by `!=` alone"

    named = db.execute(
        "SELECT count(*) FROM v WHERE kind != 'wholesale_b2b' OR kind IS NULL"
    ).fetchone()[0]
    assert named == 2, "naming the NULL is what makes the two branches exhaustive"

    wholesale = db.execute("SELECT count(*) FROM v WHERE kind = 'wholesale_b2b'").fetchone()[0]
    assert wholesale + named == 3, "and the two branches must cover every row exactly once"


# ── The scanners above, checked against known inputs ─────────────────────────
#
# Every rule in this file is documented in a comment beside the code it governs,
# and those comments name the construct they forbid. A scanner that read them
# would fail on the fix as loudly as on the defect — which is a test that gets
# suppressed rather than satisfied. These pin the two helpers that stop it.


def test_the_scanner_reads_code_and_not_the_comment_explaining_it():
    source = (
        "// never write allPages.length * size here\n"
        "const label = 'use flattenPages, not .pages.flat()';\n"
        "const next = allPages.length * size;\n"
    )
    stripped = _code(source)

    assert "allPages.length *" in stripped, "the real expression must survive"
    assert stripped.count("allPages.length *") == 1, "the comment must not count"
    assert ".pages.flat()" not in stripped, "a string literal is not code"
    assert stripped.count("\n") == source.count("\n"), "line numbers must survive"


def test_the_in_flight_guard_is_recognised_under_either_naming():
    assert _guards("if (hasNextPage && !isFetchingNextPage) fetchNextPage();")
    assert _guards("if (hasNextProducts && !isFetchingNextProducts) fetchNext();")
    assert not _guards("if (hasNextPage) fetchNextPage();")


def test_no_search_filter_compares_a_category_against_the_word_all():
    """`"all"` is the screen's word for *no* filter, not a category.

    Compared literally it becomes `category = 'all'`, which matches no product on
    the platform — a search that returns nothing whatever the customer typed.
    """
    source = (BACKEND / "services" / "query_service.py").read_text()
    branches = re.findall(r"if category[^\n:]*:", source)

    assert branches, "the category branches have been renamed; update this test"
    for branch in branches:
        assert 'category != "all"' in branch, (
            f"`{branch.strip()}` treats the sentinel 'all' as a real category"
        )


def test_search_resolves_its_own_location_and_takes_none_from_the_client():
    """The radius is only a bound if there is somewhere to measure it from — and
    that somewhere is the saved delivery address, never the request.

    This started as half a fix. Search took coordinates from the client, which
    only sends them while it holds a live GPS fix, so a customer who denied
    location permission searched the whole country with the radius silently
    inapplicable. Falling back to the saved address closed that, and left a
    subtler version of the same problem: when the client *did* send a fix, it
    won — so search was the only surface on the platform measured from where the
    handset was rather than from where the water is delivered. The results listed
    the shops that could reach the customer at work and `validate_cart_preflight`
    refused the basket using the shops that could reach their house.

    Both halves are closed by removing the parameters: there is one origin, it is
    resolved server-side, and `services/delivery_point` is the only thing that
    resolves it.
    """
    source = (BACKEND / "routes" / "query_routes.py").read_text()

    assert "delivery_point.resolve" in source, (
        "search must resolve the customer's delivery address server-side"
    )
    assert source.count("await delivery_point.resolve(") == 2, (
        "both the product search and the vendor search must resolve a location"
    )
    # The signatures, not the prose: the module docstring explains why these
    # parameters were removed, and reading the raw text finds that explanation.
    import ast

    declared = {
        argument.arg
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in node.args.args + node.args.kwonlyargs
    }
    assert not (declared & {"user_lat", "user_lng"}), (
        "search accepts a client-supplied origin again. The radius decides "
        "whether a store may be ordered from at all, so a caller-supplied "
        "origin is a caller-supplied answer."
    )


@pytest.mark.asyncio
async def test_a_search_without_a_delivery_address_returns_nothing():
    """No origin, no results — rather than no bound.

    The radius clause reads "apply it when coordinates are known", so an
    unresolved location did not produce an error or an empty list: it produced
    the **entire national catalogue**, unbounded, on the screen most customers
    actually use. A rider or vendor hitting the same endpoint has nowhere to be
    delivered to, and neither does a customer who has not set an address yet.
    """
    from unittest.mock import AsyncMock, patch

    import routes.query_routes as module

    with patch.object(module.delivery_point, "resolve", AsyncMock(return_value=None)):
        with patch.object(module, "search_service", AsyncMock()) as search_service:
            assert await module.search(db=None, user={"sub": "u"}) == []
            search_service.assert_not_called()

        with patch.object(module, "search_vendors_service", AsyncMock()) as search_vendors:
            assert await module.search_vendors(db=None, user={"sub": "u"}) == []
            search_vendors.assert_not_called()
