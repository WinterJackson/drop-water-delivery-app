"""A response bounded by the delivery address is cached per delivery address.

Ten endpoints resolve `services/delivery_point.resolve` and filter what they
return to what can actually be delivered to *that* origin — the two searches,
five vendor reads and three product listings. Their bodies are a function of
the customer's saved coordinates, so a React Query key that omits those
coordinates cannot tell two different answers apart.

It was omitted from all ten, and the customer app persists its cache to
AsyncStorage with a 24-hour `maxAge`. A customer who changed their delivery
address — moved house, or switched from home to the office — was therefore
served the previous address's shops from disk, across app restarts, until the
entry aged out; React Query had no reason to refetch, because the key was
identical and the entry was still fresh.

That is the "two halves of the app disagreeing" defect, and this one reaches
checkout: the basket is filled from a store the cache called nearby, and
`validate_cart_preflight` refuses it against the radius measured from the
address the customer actually has. It was first seen as a stale "Vendors (19)"
on a screen the server answers with 11.

The check **discovers** the endpoints rather than listing them: it reads which
routes resolve a delivery point, maps those paths to their `ROUTES` entries, and
requires every hook calling one to carry the scope in its key. A new
origin-bounded endpoint is covered the day it is written, which is the whole
point — the previous generation of this platform's guards listed call sites by
name and the one that got missed was in another module.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND_ROUTES = ROOT / "BackendAPI" / "routes"
APP = ROOT / "drop-customer-app"
ROUTE_TABLE = APP / "API" / "routes" / "ApiRoutes.ts"
HOOKS = APP / "hooks" / "queries"

# What resolving an origin looks like, directly or through a module-local helper.
RESOLVES = ("delivery_point.resolve", "_delivery_point(")


def _origin_bound_paths() -> set[str]:
    """Every FastAPI path whose handler resolves a delivery point."""
    paths: set[str] = set()
    for file in sorted(BACKEND_ROUTES.glob("*.py")):
        source = file.read_text(encoding="utf-8")
        parts = re.split(r'(@router\.(?:get|post)\("([^"]+)")', source)
        for index in range(1, len(parts), 3):
            path, tail = parts[index + 1], parts[index + 2]
            handler = tail.split("@router.")[0]
            if any(marker in handler for marker in RESOLVES):
                paths.add(path)
    return paths


def _route_constants() -> dict[str, str]:
    """`ROUTES` entry name -> the API path it points at."""
    source = ROUTE_TABLE.read_text(encoding="utf-8")
    table: dict[str, str] = {}
    for name, path in re.findall(r"(\w+):\s*`\$\{BASE_URL\}(/api/[^`?]+)`", source):
        table[name] = path
    return table


def _hook_blocks() -> list[tuple[str, str, str]]:
    """`(file, hook name, body)` for every exported hook in hooks/queries."""
    blocks: list[tuple[str, str, str]] = []
    for file in sorted(HOOKS.glob("*.ts")):
        source = file.read_text(encoding="utf-8")
        matches = list(re.finditer(r"export function (\w+)\s*\(", source))
        for position, match in enumerate(matches):
            end = matches[position + 1].start() if position + 1 < len(matches) else len(source)
            blocks.append((file.name, match.group(1), source[match.start():end]))
    return blocks


@pytest.fixture(scope="module")
def origin_paths() -> set[str]:
    found = _origin_bound_paths()
    assert found, "no origin-bound routes discovered — this guard is measuring nothing"
    return found


def _scoped_hooks(origin_paths: set[str]) -> list[tuple[str, str, str]]:
    """Hooks that call an origin-bound endpoint, with their bodies."""
    constants = _route_constants()
    # The routers are mounted under `/api`, so the decorator paths carry no
    # prefix while the client's table is written with the full URL.
    origin_names = {
        name
        for name, path in constants.items()
        if path.removeprefix("/api").rstrip("/") in origin_paths
    }
    assert origin_names, "no ROUTES entry matched an origin-bound path"

    hits = []
    for file, name, body in _hook_blocks():
        used = {c for c in origin_names if re.search(rf"ROUTES\.{c}\b", body)}
        if used and "queryKey" in body:
            hits.append((file, name, body))
    return hits


def test_the_endpoints_are_actually_discovered(origin_paths: set[str]) -> None:
    """The two searches, the vendor reads and the product listings."""
    assert "/search" in origin_paths and "/search/vendors" in origin_paths
    assert "/nearby_vendors" in origin_paths and "/vendors/directory" in origin_paths
    assert len(origin_paths) >= 8, sorted(origin_paths)


def test_every_origin_bound_hook_is_found(origin_paths: set[str]) -> None:
    """If the mapping breaks, the real assertion below would pass vacuously."""
    hits = _scoped_hooks(origin_paths)
    assert len(hits) >= 8, [f"{f}:{n}" for f, n, _ in hits]


def test_every_origin_bound_query_is_keyed_by_the_origin(origin_paths: set[str]) -> None:
    """The rule: bounded by the address means cached per address."""
    offenders = []
    for file, name, body in _scoped_hooks(origin_paths):
        key = re.search(r"queryKey:\s*\[([^\]]*)\]", body)
        if key is None or "scope" not in key.group(1):
            offenders.append(f"{file}:{name} queryKey={key.group(1).strip() if key else '?'}")
    assert not offenders, (
        "These queries are filtered server-side by the customer's delivery "
        "address but cached without it, so changing the address keeps serving "
        "the old neighbourhood's results — from disk, for 24 hours:\n  "
        + "\n  ".join(offenders)
        + "\nAdd `const scope = useDeliveryScope();` and put `scope` in the key."
    )


def _code_only(source: str) -> str:
    """Strip comments — prose *about* `useLocation` is not a call to it."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def test_the_scope_reads_the_saved_address_not_the_handset() -> None:
    """The origin is the address, and this hook must stay cheap enough to reuse."""
    source = _code_only((HOOKS / "useDeliveryScope.ts").read_text(encoding="utf-8"))
    assert "useUserDetails" in source
    assert "useLocation" not in source, (
        "`useDeliveryScope` runs inside ten query hooks. `useLocation` asks for "
        "foreground permission and takes a GPS fix; the radius is measured from "
        "the saved address, never the handset."
    )
    # Compared against `null`, in either direction, rather than tested for
    # truthiness: Kenya straddles the equator, latitude 0 is a real place a
    # customer can live, and `!0` is true. The server-side guard had exactly
    # this bug in four endpoints.
    assert re.search(r"[!=]= *null", source), (
        "Coordinates must be compared against `null`, not tested for truthiness."
    )
    assert not re.search(r"if *\( *! *(lat|lng)\b", source), (
        "`!lat` erases the equator. Compare against `null`."
    )
