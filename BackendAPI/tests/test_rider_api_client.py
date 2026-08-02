"""
The rider app talks to the backend through one client.

`drop-rider-app/API/` used to contain nothing but `routes/`. Every hook and
screen hand-rolled its own `fetch`, and nineteen of them threw the HTTP status at
the rider:

    throw new Error(`Rider orders fetch failed: ${res.status}`)

The platform guide says the opposite — show the backend's `detail`, never a
status code — and the customer app had already been migrated to `useApiRequest`
for exactly this reason. The consequences of not having a client were not only
cosmetic: `fetch` has no default timeout, so a hung request hung forever; the
401 sign-out was copy-pasted at about fifteen sites and missing from others; and
nothing enforced HTTPS.

These are structural, in the style of `test_places_proxy`'s Google-key scan:
the defect is "somebody added another one", which no unit test can catch.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RIDER = REPO / "drop-rider-app"

#: The only file allowed to call `fetch` directly is the one that wraps it.
#: `API/useApiClient.ts` uses axios, so it does not appear here at all.
FETCH_ALLOWED = {"API/apiFetch.ts"}

pytestmark = pytest.mark.skipif(not RIDER.exists(), reason="rider app not in this checkout")


def _sources():
    for directory in ("app", "components", "hooks", "services", "stores", "utils", "Helpers", "API", "config"):
        root = RIDER / directory
        if not root.exists():
            continue
        for path in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
            if "node_modules" in path.parts:
                continue
            yield path


def _code_lines(path: pathlib.Path):
    """Lines that are actually code — prose describing the rule is not a breach."""
    for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        yield i, line


def test_nothing_in_the_rider_app_calls_fetch_directly():
    pattern = re.compile(r"(?<![A-Za-z])fetch\s*\(")
    offenders = []
    for path in _sources():
        rel = path.relative_to(RIDER).as_posix()
        if rel in FETCH_ALLOWED:
            continue
        for i, line in _code_lines(path):
            if pattern.search(line):
                offenders.append(f"{rel}:{i}")

    assert offenders == [], (
        "use `useApiRequest` (React) or `apiFetch` (background/store code) — a raw "
        "fetch has no timeout, no 401 handling and no error normalisation: "
        f"{sorted(offenders)}"
    )


def test_no_screen_shows_a_raw_http_status_to_the_rider():
    """`Something failed: 402` instead of the backend's own sentence.

    This is the shape that made "Insufficient balance: KSH 4,000 is committed as
    float" reach the rider as "Earnings fetch failed: 402".
    """
    pattern = re.compile(r"(?:res|response|r)\.status\s*\}|failed:\s*\$\{[^}]*status")
    offenders = []
    for path in _sources():
        rel = path.relative_to(RIDER).as_posix()
        for i, line in _code_lines(path):
            if pattern.search(line):
                offenders.append(f"{rel}:{i}")

    assert offenders == [], (
        "surface the backend's message with `errorMessage(err)`, never the status "
        f"code: {sorted(offenders)}"
    )


def test_the_query_client_does_not_retry_refusals():
    """A plain `retry: 2` costs three round-trips per 4xx.

    Worse, since the client signs the rider out on a 401, it fired the sign-out
    handler three times for one expired session.
    """
    layout = (RIDER / "app" / "_layout.tsx").read_text()
    assert "retryTransientOnly" in layout, (
        "the root QueryClient must use `retryTransientOnly` from API/errors"
    )


def test_the_error_helpers_did_not_drift_from_the_customer_app():
    """Both apps read the same backend; they must read its errors identically.

    `API/errors.ts` was ported from `drop-customer-app`. The exported surface is
    what every call site depends on, so a rename on one side and not the other is
    the failure this catches.
    """
    rider = (RIDER / "API" / "errors.ts").read_text()
    customer = (REPO / "drop-customer-app" / "API" / "errors.ts")
    if not customer.exists():
        pytest.skip("customer app not in this checkout")

    exported = re.compile(r"^export (?:class|function|const) (\w+)", re.M)
    rider_names = set(exported.findall(rider))
    customer_names = set(exported.findall(customer.read_text()))

    assert customer_names <= rider_names, (
        f"the rider app is missing error helpers the customer app has: "
        f"{sorted(customer_names - rider_names)}"
    )
