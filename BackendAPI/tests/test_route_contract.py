"""Every endpoint the three apps call must exist on this API.

This test would have caught five separate findings in the Phase 1 audit:
`/api/payments/history` (no such route), `/api/vendor-favorites/check/{id}` (no
such route), `/api/vendor-favorites/last-order/{id}` (segments inverted),
`/api/orders/{id}/cancel` and `/api/orders/{id}/resolve-mismatch` (both missing
the `/cart` prefix). Each was a 404 on a live user action.

It parses each app's route table straight out of its own source, so it keeps
working as the clients evolve — no list to maintain in two places.

**All three apps, not one.** It covered only the customer app for a long time,
which meant the rider's 47 entries and the vendor's 45 were correct by nobody's
enforcement — a state that had already failed once on the surface that *was*
covered. The two tables are shaped differently (`ROUTES.KEY` is a template
string; `RiderApiRoutes.Key.path` is an object with a method), so the parser is
per-app and the assertions are shared.

**One table per app.** The customer file used to carry two — `ROUTES`, and a
legacy `ApiRoutes` "kept for screens not yet migrated". By the end the legacy
table declared 41 endpoints of which two were still reached, four screens
imported it without using it at all, and every live endpoint had two independent
declarations free to drift apart. Resolving paths against the server cannot see
that: both copies of a route resolve, and a table nothing imports resolves best
of all. The tests below therefore also assert that every declared route is
*called*, and that a second table does not come back.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from main import app

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]

# Where an app's own source lives — everything that may reference a route.
#
# `services` matters and is easy to miss: the rider's background location
# uploader lives there and is the only caller of `LocationPing`, so omitting it
# reports a live route as dead. Non-existent directories are skipped per app.
SOURCE_DIRS = (
    "app", "components", "hooks", "utils", "lib", "context", "Helpers", "API",
    "stores", "services", "config", "constants", "types",
)


@dataclass(frozen=True)
class AppSpec:
    """One Expo app, and how to read its route table."""

    name: str
    table: str
    #: `ROUTES.KEY` on the customer app; `RiderApiRoutes.Key.path` on the others.
    reference: str
    #: Matches a key in the table's source.
    key_pattern: str
    #: Floor for the parsers, so a regex that stops matching fails loudly
    #: rather than making every assertion below pass over an empty set.
    min_paths: int
    min_keys: int


APPS = (
    AppSpec(
        name="drop-customer-app",
        table="API/routes/ApiRoutes.ts",
        reference="ROUTES.{key}",
        key_pattern=r"^\s{4}([A-Z][A-Z0-9_]*)\s*:",
        min_paths=30,
        min_keys=50,
    ),
    AppSpec(
        name="drop-rider-app",
        table="API/routes/RiderApiRoutes.ts",
        reference="RiderApiRoutes.{key}",
        key_pattern=r"^\s{2}([A-Z][A-Za-z0-9_]*)\s*:\s*\{",
        min_paths=30,
        min_keys=30,
    ),
    AppSpec(
        name="drop-vendor-app",
        table="API/routes/VendorApiRoutes.ts",
        reference="VendorApiRoutes.{key}",
        key_pattern=r"^\s{2}([A-Z][A-Za-z0-9_]*)\s*:\s*\{",
        min_paths=30,
        min_keys=28,
    ),
)

IDS = [spec.name for spec in APPS]


def _table_path(spec: AppSpec) -> Path:
    path = ROOT / spec.name / spec.table
    if not path.exists():  # pragma: no cover - monorepo layout guard
        pytest.skip(f"{spec.name} route table not found at {path}")
    return path


def _declared_paths(spec: AppSpec) -> set[str]:
    """Every backend path referenced by an app's route table.

    Template holes (`${vendorId}`) and the BASE_URL prefix are normalised to
    `{}` so they can be compared against FastAPI's `{param}` placeholders.
    """
    source = _table_path(spec).read_text()
    paths: set[str] = set()

    for raw in re.findall(r"\$\{BASE_URL\}([^`\"']*)", source):
        path = re.sub(r"\$\{[^}]+\}", "{}", raw)      # ${id} → {}
        # A conditional hole — `${status ? `?status=${status}` : ""}` — closes
        # the outer template early, leaving a dangling `${`. Everything from
        # there on is an optional query string, never part of the path.
        path = path.split("${")[0]
        path = path.split("?")[0]                     # drop query strings
        path = path.rstrip("/") or "/"
        if path.startswith("/api"):
            paths.add(path)

    return paths


def _strip_comments(source: str) -> str:
    """TypeScript without comments.

    Mandatory here: a doc comment explaining which endpoint a hook calls is
    prose, not a call. `useVendors` documents the `/api/vendors` envelope and
    would otherwise read as a path built outside the table.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _app_source(spec: AppSpec) -> str:
    """Every line of app source, concatenated, minus the route table itself."""
    table = _table_path(spec)
    chunks = []
    for directory in SOURCE_DIRS:
        root = ROOT / spec.name / directory
        if not root.exists():
            continue
        for file in root.rglob("*"):
            if file.suffix not in (".ts", ".tsx") or file == table:
                continue
            if "node_modules" in file.parts:
                continue
            chunks.append(_strip_comments(file.read_text()))
    return "\n".join(chunks)


def _server_paths() -> set[str]:
    """FastAPI's registered paths, with parameter names erased."""
    return {
        re.sub(r"\{[^}]+\}", "{}", route.path).rstrip("/") or "/"
        for route in app.routes
        if getattr(route, "path", None)
    }


# ── The contract itself ───────────────────────────────────────────────────


@pytest.mark.parametrize("spec", APPS, ids=IDS)
def test_every_client_endpoint_exists_on_the_server(spec):
    declared = _declared_paths(spec)
    served = _server_paths()

    missing = sorted(p for p in declared if p not in served)
    assert not missing, (
        f"{spec.name} calls endpoints this API does not serve — every one of "
        f"these is a 404 on a real user action: {missing}"
    )


@pytest.mark.parametrize("spec", APPS, ids=IDS)
def test_the_route_table_parser_still_matches(spec):
    """Guards the parser: a regex that silently matches nothing would make
    every assertion in this file pass vacuously."""
    declared = _declared_paths(spec)
    assert len(declared) >= spec.min_paths, (
        f"{spec.name}: only {len(declared)} paths parsed out of "
        f"{spec.table} — the extractor has stopped matching the table"
    )


@pytest.mark.parametrize("spec", APPS, ids=IDS)
def test_the_app_declares_exactly_one_route_table(spec):
    """Two tables declaring the same endpoints are two declarations free to
    disagree, with nothing to notice. The customer app carried exactly that."""
    source = _table_path(spec).read_text()
    tables = re.findall(r"(?:export )?const ([A-Za-z][A-Za-z0-9_]*)\s*=\s*\{", source)
    # `interface ApiRoute` and `const BASE_URL` are not tables.
    tables = [t for t in tables if t != "BASE_URL"]

    assert len(tables) == 1, (
        f"{spec.name} declares {len(tables)} route tables ({tables}); "
        "one endpoint, one declaration"
    )


@pytest.mark.parametrize("spec", APPS, ids=IDS)
def test_no_screen_builds_a_backend_path_inline(spec):
    """The table is only the single source of truth while nothing goes round it.

    Two shapes, and the second is the one that hid. A quoted literal
    (`"/api/…"`) is obvious. An interpolated base URL —
    `` `${process.env.EXPO_PUBLIC_BACKEND_BASE_URL}/api/auth/push-token` `` —
    reads as configuration and is the same defect: the vendor app registered
    and cleared its push token that way, so neither call appeared in its route
    table and neither was ever checked against the server. Matching only a
    quote immediately before `/api/` could not see it, because what precedes
    it is `}`.
    """
    source = _app_source(spec)
    offenders = re.findall(r"""["'`}]/api/[a-z0-9\-_/]+""", source)
    assert not offenders, (
        f"{spec.name} builds backend paths outside its route table: "
        f"{sorted(set(offenders))}"
    )


def test_the_inline_path_check_sees_an_interpolated_base_url():
    """The negative case for the widened pattern above."""
    pattern = r"""["'`}]/api/[a-z0-9\-_/]+"""
    assert re.findall(pattern, "await apiFetch(`${BASE}/api/auth/push-token`)")
    assert re.findall(pattern, 'get("/api/orders")')
    # A route table entry is how the path is *supposed* to be written, and the
    # table itself is excluded from the scanned source — but the pattern must
    # still not fire on ordinary prose or a URL that is not an API path.
    assert not re.findall(pattern, "see the /docs page for the api reference")


@pytest.mark.parametrize("spec", APPS, ids=IDS)
def test_every_declared_route_is_actually_called(spec):
    """A route nothing calls is a route nothing checks.

    The customer app's legacy table had 41 entries that all resolved against the
    server; 39 were reached by no screen.
    """
    table = _table_path(spec).read_text()
    keys = set(re.findall(spec.key_pattern, table, flags=re.M))
    assert len(keys) >= spec.min_keys, (
        f"{spec.name}: the key parser has stopped matching the table "
        f"(found {len(keys)})"
    )

    source = _app_source(spec)
    unused = sorted(k for k in keys if spec.reference.format(key=k) not in source)
    assert not unused, (
        f"{spec.name} declares routes called by nothing — delete the entry or "
        f"wire up the screen that needs it: {unused}"
    )


# ── Endpoints without which a core flow cannot complete ───────────────────


def test_customer_money_path_endpoints_are_present():
    """The endpoints without which checkout cannot complete."""
    served = _server_paths()
    for path in (
        "/api/cart/quote",
        "/api/cart/mpesa_payment",
        "/api/cart/confirm_payment",
        "/api/cart/mpesa/callback",
        "/api/cart/get_orders",
        "/api/cart/orders/{}/cancel",
        "/api/payments/history",
        "/api/wallet/transactions",
    ):
        assert path in served, f"missing critical endpoint {path}"


def test_rider_and_vendor_money_path_endpoints_are_present():
    """A rider cannot be paid and a vendor cannot see what they are owed
    without these. Both surfaces went uncovered by this file for a long time."""
    served = _server_paths()
    for path in (
        "/api/rider/wallet-summary",
        "/api/rider/cash-eligibility",
        "/api/vendor/wallet-summary",
        "/api/wallet/withdraw",
        "/api/wallet/top-up",
    ):
        assert path in served, f"missing critical endpoint {path}"


def test_no_rate_limited_route_leaks_its_request_parameter_as_a_query_field():
    """`request` on a `@limiter.limit` route must be annotated `Request`.

    slowapi needs a parameter literally named `request`. FastAPI decides what a
    parameter *is* from its annotation, and an un-annotated one with no default
    is a **required query parameter** — so the endpoint answers 422 to every
    real call, on a field no client knows to send.

    It is silent: the route mounts, the OpenAPI schema looks plausible, and
    nothing fails until somebody uses the feature. Five endpoints shipped this
    way on the bottle-return router and were unreachable from both apps.
    """
    import ast

    offenders = []
    for path in (BACKEND / "routes").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            decorated = any(
                "limit" in ast.unparse(dec) and "limiter" in ast.unparse(dec)
                for dec in node.decorator_list
            )
            if not decorated:
                continue

            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.arg != "request":
                    continue
                annotation = ast.unparse(arg.annotation) if arg.annotation else None
                if annotation is None or "Request" not in annotation:
                    offenders.append(f"{path.name}::{node.name}")

    assert not offenders, (
        "these rate-limited routes take an un-annotated `request`, which FastAPI "
        "turns into a required query parameter — every call gets a 422: "
        + ", ".join(sorted(offenders))
    )
