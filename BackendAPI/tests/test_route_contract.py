"""Every endpoint the customer app calls must exist on this API.

This single test would have caught five separate findings in the Phase 1 audit:
`/api/payments/history` (no such route), `/api/vendor-favorites/check/{id}` (no
such route), `/api/vendor-favorites/last-order/{id}` (segments inverted),
`/api/orders/{id}/cancel` and `/api/orders/{id}/resolve-mismatch` (both missing
the `/cart` prefix). Each was a 404 on a live user action.

It parses the app's route table straight out of `ApiRoutes.ts`, so it keeps
working as the client evolves — no list to maintain in two places.
"""

import re
from pathlib import Path

import pytest

from main import app

CUSTOMER_APP_ROUTES = (
    Path(__file__).resolve().parents[2] / "drop-customer-app" / "API" / "routes" / "ApiRoutes.ts"
)

# Endpoints the client reaches without going through ApiRoutes.ts.
EXTRA_CLIENT_PATHS = {
    "/api/contacts/{}",                       # useOrderContacts
    "/api/cart/orders/last-completed",        # useLastCompletedOrder
    "/api/cart/orders/active",                # useActiveOrder
    "/api/cart/orders/{}/tracking-logs",      # useOrderTrackingLogs
    "/api/cart/orders/{}/cancel",             # useCancelOrder
    "/api/cart/orders/{}/resolve-mismatch",   # useResolveMismatch
    "/api/cart/quote",                        # useCartQuote
    "/api/app-version",                       # utils/appUpdate
}


def _declared_client_paths() -> set[str]:
    """Extract every backend path referenced by the client's route table.

    Template holes (`${vendorId}`) and the BASE_URL prefix are normalised to `{}`
    so they can be compared against FastAPI's `{param}` placeholders.
    """
    if not CUSTOMER_APP_ROUTES.exists():  # pragma: no cover - monorepo layout guard
        pytest.skip(f"Customer app route table not found at {CUSTOMER_APP_ROUTES}")

    source = CUSTOMER_APP_ROUTES.read_text()
    paths: set[str] = set()

    for raw in re.findall(r"\$\{BASE_URL\}([^`\"']*)", source):
        path = raw.split("?")[0]                      # drop query strings
        path = re.sub(r"\$\{[^}]+\}", "{}", path)     # ${id} → {}
        path = path.rstrip("/") or "/"
        if path.startswith("/api"):
            paths.add(path)

    return paths | EXTRA_CLIENT_PATHS


def _server_paths() -> set[str]:
    """FastAPI's registered paths, with parameter names erased."""
    return {
        re.sub(r"\{[^}]+\}", "{}", route.path).rstrip("/") or "/"
        for route in app.routes
        if getattr(route, "path", None)
    }


def test_every_client_endpoint_exists_on_the_server():
    declared = _declared_client_paths()
    served = _server_paths()

    missing = sorted(p for p in declared if p not in served)
    assert not missing, (
        "The customer app calls endpoints this API does not serve — every one of "
        f"these is a 404 on a real user action: {missing}"
    )


def test_client_route_table_is_not_empty():
    """Guards the parser itself: a regex that silently matches nothing would make
    the test above pass vacuously."""
    assert len(_declared_client_paths()) > 30


@pytest.mark.parametrize("path", sorted(EXTRA_CLIENT_PATHS))
def test_out_of_table_client_paths_exist(path):
    """Paths the client builds inline still have to resolve."""
    assert path in _server_paths(), f"{path} is called by the client but not served"


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
