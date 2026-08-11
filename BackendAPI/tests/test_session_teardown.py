"""Signing out has to actually end the session on this device.

`DELETE /api/auth/push-token` takes `app_type` as a **query parameter with a
default of `customer`**, and that default is the trap. Omit it as a rider and
the endpoint looks up a `User` row by your clerk id, finds none — a rider has no
`User` row — clears nothing, commits, and answers `200`. The app sees success.
`Deliverer.push_token` is still registered.

Riders share devices more than anyone else on this platform, so the failure is
not hypothetical: the rider who signs out keeps receiving delivery offers, and
the next rider to sign in receives them too, on the same handset, for orders
neither of them is assigned. The vendor app met the identical default, diagnosed
it, and fixed it in its own copy; nothing carried that fix to the rider app, and
nothing could have — until this file.

The customer app was correct only because `customer` is what the default
happens to be. All three now say which they are.

The other half of teardown — wiping the query cache, and the vendor's remembered
`X-Store-Id` — is `useSessionCleanup`, mounted in each root layout, and is
checked here too. It exists because a session also ends without anyone tapping
"Sign out": any query signs the user out on a 401, and Clerk ends a revoked
session on its own.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: app → the `app_type` its push token is registered under.
APP_TYPES = {
    "drop-customer-app": "customer",
    "drop-rider-app": "rider",
    "drop-vendor-app": "vendor",
}

#: app → its route table.
TABLES = {
    "drop-customer-app": "API/routes/ApiRoutes.ts",
    "drop-rider-app": "API/routes/RiderApiRoutes.ts",
    "drop-vendor-app": "API/routes/VendorApiRoutes.ts",
}


def _table(app: str) -> str:
    return (ROOT / app / TABLES[app]).read_text()


def _code_only(source: str) -> str:
    """TypeScript with comment *bodies* blanked, newlines kept.

    Mandatory, and this file is the illustration: every correct sign-out site on
    the platform carries a comment reading "Before `signOut()` — the endpoint is
    authenticated". Scanning raw text, the comment explaining the fix is itself
    a match, so the sites that got it right are the ones that fail. Newlines
    survive so reported line numbers still point at real code.
    """
    source = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


# ── The push token ────────────────────────────────────────────────────────


@pytest.mark.parametrize("app,app_type", sorted(APP_TYPES.items()))
def test_each_app_clears_the_push_token_it_registered(app, app_type):
    source = _table(app)

    deletes = [
        line
        for line in source.splitlines()
        if "/api/auth/push-token" in line and not line.strip().startswith(("*", "//"))
    ]
    assert deletes, f"{app} declares no push-token path"

    clearing = [line for line in deletes if "app_type=" in line]
    assert clearing, (
        f"{app} clears its push token with no app_type, so the endpoint "
        f"defaults to `customer` — for {app_type} that clears nothing and "
        "returns 200"
    )
    for line in clearing:
        assert f"app_type={app_type}" in line, (
            f"{app} clears the push token as the wrong kind of account: {line.strip()}"
        )


def test_the_endpoint_still_defaults_to_customer():
    """The assumption every assertion above rests on.

    If the default ever becomes required — which would be the better design —
    this fires, and the rule here changes rather than quietly protecting
    nothing.
    """
    source = (ROOT / "BackendAPI" / "routes" / "auth_routes.py").read_text()
    body = source[source.index("async def clear_push_token"):]
    body = body[: body.index("\n@")] if "\n@" in body else body

    assert re.search(r'app_type:\s*str\s*=\s*"customer"', body), (
        "clear_push_token no longer defaults app_type to `customer` — the "
        "reasoning in this file needs revisiting"
    )
    for kind in ("vendor", "rider"):
        assert f'app_type == "{kind}"' in body, (
            f"clear_push_token no longer handles {kind}"
        )


@pytest.mark.parametrize("app", sorted(APP_TYPES))
def test_the_token_is_cleared_before_the_session_ends(app):
    """`clearPushToken` calls an authenticated endpoint, so it cannot run after
    `signOut()`. Every sign-out path has to clear first."""
    offenders = []
    for path in (ROOT / app).rglob("*.tsx"):
        if "node_modules" in path.parts:
            continue
        source = _code_only(path.read_text(errors="ignore"))
        if "signOut(" not in source or "clearPushToken" not in source:
            continue
        for match in re.finditer(r"\bsignOut\s*\(", source):
            window = source[max(0, match.start() - 1200): match.start()]
            if "clearPushToken" not in window:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT / app)}:{line}")

    assert not offenders, (
        f"{app} signs out without clearing the push token first — the endpoint "
        "is authenticated, so afterwards is too late:\n  " + "\n  ".join(offenders)
    )


# ── The rest of the session ───────────────────────────────────────────────


@pytest.mark.parametrize("app", sorted(APP_TYPES))
def test_session_cleanup_is_mounted_in_the_root_layout(app):
    """Not in the sign-out handlers alone.

    A session ends without anyone tapping "Sign out" — a 401 on any query does
    it, and so does Clerk ending a revoked session. Those routes left the cache
    fully populated for the next account on the device.
    """
    layout = (ROOT / app / "app" / "_layout.tsx").read_text()
    assert re.search(r"^\s*useSessionCleanup\(\);", layout, re.M), (
        f"{app}: useSessionCleanup() is not called in the root layout"
    )


def test_the_vendor_forgets_the_active_store_too():
    """`X-Store-Id` is sent on every vendor request and validated against the
    caller's own stores. Left behind, the next account on the device sends a
    store id it does not own and every request 404s."""
    source = (ROOT / "drop-vendor-app" / "hooks" / "useSessionCleanup.ts").read_text()
    assert "useActiveStore" in source, (
        "the vendor's session cleanup no longer clears the remembered store"
    )
