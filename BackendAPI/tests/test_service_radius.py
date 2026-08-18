"""The service radius is one figure, and every customer-facing path applies it.

2.5 km retail, 15 km wholesale. The guide says this is *all* of: what discovery
searches, what checkout enforces, what the rider search covers, and the circle
each app draws. Three of those were true.

**What broke, part one — checkout.** `DispatchPolicy.validate_cart_preflight`
enforced distance inside `if vendor_type == "retail_refill"`, so:

* a **wholesale** basket was priced and accepted at any distance at all — the
  15 km figure was enforced nowhere on the ordering path; and
* a store with a **NULL** `vendor_type` matched neither branch and escaped
  entirely, which is the same shape as the `COALESCE` defect one layer down:
  three-valued logic quietly dropping the row nobody has classified.

**What broke, part two — discovery.** The three product listings behind the home
grid, Deals & Offers and every category screen selected straight off `Products`
with **no join to `Vendors` at all**. No `discoverable_vendor()`, so products
from suspended, unverified and deleted stores were on sale; and no radius, so
the home screen rendered "No vendors currently deliver to your location"
directly above a grid of products from stores 20 km away. The vendor list was
bounded and the product grid was not, on the same screen, from the same address.

The predicate now lives in `dispatch_policy` beside the radii it measures
against, and vendor discovery, product discovery and search all import that one.
A second copy is how these came apart in the first place.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Every customer-facing listing that returns rows sourced from `Vendors`.
CATALOGUE_READS = (
    "fetch_products_with_offer",
    "fetch_paginated_products",
    "fetch_products_by_category",
)


def _fn(module: str, name: str) -> str:
    tree = ast.parse((BACKEND / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.unparse(node)
    pytest.fail(f"{name} not found in {module}")


def test_the_radius_predicate_has_one_implementation():
    """`dispatch_policy` owns it, because it owns the two figures."""
    policy = (BACKEND / "services/dispatch_policy.py").read_text(encoding="utf-8")
    assert "def within_service_radius(" in policy

    # And it reads the configured rows, never the shipped dataclass defaults.
    body = _fn("services/dispatch_policy.py", "within_service_radius")
    assert "max_distance_km(" in body
    assert "RETAIL_MAX_DISTANCE_KM" not in body
    assert "WHOLESALE_MAX_DISTANCE_KM" not in body

    # Nobody keeps a private copy.
    for module in ("services/query_service.py", "services/product_service.py"):
        src = (BACKEND / module).read_text(encoding="utf-8")
        assert "ST_DWithin(Vendor.location" not in src, (
            f"{module} builds its own radius predicate instead of importing "
            "dispatch_policy.within_service_radius"
        )


def test_checkout_enforces_the_radius_for_every_vendor_type():
    """Not just retail.

    Asserted structurally: the distance check must not sit inside a branch that
    tests `vendor_type`, because that is exactly how wholesale came to have no
    limit at all.
    """
    body = _fn("services/dispatch_policy.py", "validate_cart_preflight")
    tree = ast.parse(body)

    distance_tests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "distance_km >" in ast.unparse(node.test)
    ]
    assert distance_tests, "validate_cart_preflight no longer checks distance at all"

    for check in distance_tests:
        # Walk the enclosing statements: no `if vendor_type == ...` may contain it.
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node is not check:
                test_src = ast.unparse(node.test)
                if "vendor_type" in test_src and check in list(ast.walk(node)):
                    pytest.fail(
                        "the distance check is nested inside "
                        f"`if {test_src}` — wholesale and unclassified stores "
                        "escape it, which is the defect this test exists for"
                    )

    assert "max_distance_km(" in body, (
        "the limit must come from the accessor that resolves the vendor type, "
        "not from one type's figure"
    )


@pytest.mark.parametrize("function", CATALOGUE_READS)
def test_every_catalogue_read_is_bounded_and_joined(function):
    """A customer sees what they can order from.

    These three selected off `Products` alone. The join is what carries both
    facts: whether the store may be shown at all, and whether it is close
    enough.
    """
    body = _fn("services/product_service.py", function)
    assert "_orderable_products(" in body, (
        f"{function} builds its own product query instead of going through "
        "_orderable_products, which is what applies discoverable_vendor() and "
        "the service radius"
    )


def test_the_shared_base_query_carries_both_halves():
    body = _fn("services/product_service.py", "_orderable_products")
    assert "discoverable_vendor()" in body, "suspended and deleted stores would be listed"
    assert "within_service_radius(" in body, "out-of-range stores would be listed"
    assert "live_product()" in body, "withdrawn products would be listed"
    assert "join(Vendor" in body, "without the join neither filter can apply"


def test_a_location_dependent_listing_is_not_cached_location_blind():
    """The cache must not undo the bound.

    These listings are cached in Redis and were keyed on pagination alone. Now
    that the rows depend on where the customer is, a location-blind key would
    serve one customer's in-range catalogue to another twenty kilometres away —
    the exact defect being fixed, reintroduced one layer up.
    """
    src = (BACKEND / "routes/product_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        body = ast.unparse(node)
        if "cache_key" not in body:
            continue
        # Only listings whose *rows* depend on the customer. `/categories`
        # caches a module-level constant — the same ten category labels for
        # everybody, everywhere — and keying that by location would shard a
        # static payload per neighbourhood for nothing.
        if not any(read in body for read in CATALOGUE_READS):
            continue
        assert "_location_key(" in body, (
            f"{node.name} caches a location-dependent listing under a key that "
            "does not mention the location"
        )


@pytest.mark.parametrize("route", ["get_products_by_category", "get_products_with_offer", "get_paginated_products"])
def test_a_catalogue_route_knows_who_is_asking(route):
    """The delivery point is resolved from the caller, server-side.

    These three had no auth dependency at all, which is why they could not be
    bounded: with no caller there is no address to measure from. It also made
    the whole catalogue, including suspended stores, readable by anyone.
    """
    body = _fn("routes/product_routes.py", route)
    assert "get_current_user" in body, f"{route} serves the catalogue unauthenticated"
    assert "_delivery_point(" in body, (
        f"{route} does not resolve the customer's delivery point, so it cannot "
        "bound what it returns"
    )
    assert "user_lat=lat" in body and "user_lng=lng" in body


def test_the_delivery_point_is_never_taken_from_the_client():
    """A client-supplied origin is a client-supplied answer.

    The radius decides whether a store may be ordered from; letting the caller
    say where they are standing would make it advisory.
    """
    body = _fn("routes/product_routes.py", "_delivery_point")
    assert "get_user_coordinates(" in body
    assert "Query(" not in body
