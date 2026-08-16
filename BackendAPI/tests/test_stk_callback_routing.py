"""An STK push names the endpoint that settles it, and no two kinds share one.

The defect this exists to prevent, in full:

`initiate_stk_push` set `CallBackURL` from a module-level
`os.getenv("MPESA_CALLBACK_URL")`. There are two callers — order checkout and
wallet top-up — and they are settled by two *different* handlers, because a
`CheckoutRequestID` resolves against `Orders` for one and against
`WalletTransactions` for the other. Both inherited the order URL.

So every wallet top-up's confirmation was delivered to
`/api/cart/mpesa/callback`, which looked the id up in `Orders`, found nothing,
and returned **400** — a retry instruction to Safaricom, not an
acknowledgement. The customer's money left their phone; the `WalletTransaction`
stayed `pending` forever; and `handle_mpesa_topup_callback` — written, guarded,
correct and reachable at `/api/wallet/mpesa-callback` — had never been called by
anybody, because nothing in the codebase had ever told Safaricom its address.

Nothing found it. It is not a type error, not an undefined name, and every unit
test of the top-up handler passed, because the handler was right. The only
signal available was a customer saying their wallet was not credited.

Three things are asserted here, and each is a different half of the same rule:

1. Every call to `initiate_stk_push` passes `callback_url` explicitly. A
   default would silently re-adopt one caller's endpoint for the other.
2. No two callers pass the *same* URL expression, which is the defect stated
   directly.
3. Each declared callback path resolves against FastAPI, so a renamed route
   cannot leave a resolver pointing at a 404 — the failure that is invisible
   from this side, because Safaricom is the only caller and it never complains.
"""
from __future__ import annotations

import ast
import os
import pathlib
from unittest.mock import patch

import pytest

from services import payment_service

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCANNED = ("routes", "services", "jobs")


def _call_sites() -> list[tuple[str, int, ast.Call]]:
    """Every `initiate_stk_push(...)` call in code that serves a request."""
    found: list[tuple[str, int, ast.Call]] = []
    for package in SCANNED:
        for path in sorted((BACKEND / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else None
                )
                if name == "initiate_stk_push":
                    found.append((str(path.relative_to(BACKEND)), node.lineno, node))
    return found


def test_the_scan_finds_both_known_stk_callers():
    """Non-vacuity. Two callers exist; a scan finding none would pass silently."""
    sites = _call_sites()
    files = {path for path, _, _ in sites}

    assert len(sites) >= 2, f"expected at least two STK callers, found {sites}"
    assert "routes/cart_routes.py" in files, files
    assert "services/wallet_service.py" in files, files


def test_every_stk_push_names_its_own_callback_url():
    offenders = [
        f"{path}:{line}"
        for path, line, node in _call_sites()
        if not any(kw.arg == "callback_url" for kw in node.keywords)
    ]

    assert not offenders, (
        "these STK pushes do not say where the confirmation should be "
        "delivered, so they take whichever endpoint the default names — which "
        "is how every wallet top-up came to be settled against the orders "
        "table:\n  " + "\n  ".join(offenders)
    )


def test_no_two_stk_callers_share_one_callback_url():
    """The defect stated directly, rather than by its symptom."""
    by_url: dict[str, list[str]] = {}
    for path, line, node in _call_sites():
        for kw in node.keywords:
            if kw.arg == "callback_url":
                by_url.setdefault(ast.unparse(kw.value), []).append(f"{path}:{line}")

    shared = {url: sites for url, sites in by_url.items() if len(sites) > 1}

    assert not shared, (
        "two different kinds of payment are being settled by one endpoint. "
        "Whichever handler owns it will resolve the other's CheckoutRequestID "
        "against the wrong table, find nothing, and return a retry:\n  "
        + "\n  ".join(f"{url} ← {sites}" for url, sites in shared.items())
    )


def test_callback_paths_resolve_against_the_app():
    """A resolver pointing at a path FastAPI does not serve is a silent 404.

    Safaricom is the only caller of these, and it does not report to us.
    """
    from main import app

    declared = {
        payment_service.ORDER_CALLBACK_PATH,
        payment_service.TOPUP_CALLBACK_PATH,
    }
    served = {getattr(route, "path", None) for route in app.routes}

    missing = declared - served
    assert not missing, (
        f"declared callback paths that no route serves: {sorted(missing)}. "
        f"Safaricom would post to a 404 and nothing here would ever know."
    )


def test_the_two_paths_are_not_the_same():
    assert payment_service.ORDER_CALLBACK_PATH != payment_service.TOPUP_CALLBACK_PATH


# ── The resolvers themselves ──────────────────────────────────────────────


def test_topup_url_is_derived_from_the_order_url_keeping_the_secret():
    """The query string carries `?secret=`, which the guard compares.

    A derivation that dropped it would 403 every callback it received — the
    same silence as the original defect, one layer along.
    """
    env = {"MPESA_CALLBACK_URL": "https://api.example.com/api/cart/mpesa/callback?secret=abc123"}
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("MPESA_TOPUP_CALLBACK_URL", None)
        derived = payment_service.topup_callback_url()

    assert derived == "https://api.example.com/api/wallet/mpesa-callback?secret=abc123"


def test_an_explicit_topup_url_wins_over_the_derivation():
    env = {
        "MPESA_CALLBACK_URL": "https://api.example.com/api/cart/mpesa/callback?secret=abc",
        "MPESA_TOPUP_CALLBACK_URL": "https://other.example.com/api/wallet/mpesa-callback?secret=xyz",
    }
    with patch.dict(os.environ, env, clear=False):
        assert payment_service.topup_callback_url() == env["MPESA_TOPUP_CALLBACK_URL"]


def test_both_resolvers_are_empty_when_nothing_is_configured():
    """Empty is what `initiate_stk_push` refuses on. It must not fall back to
    a hardcoded host, and it must not return the order URL for a top-up."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MPESA_CALLBACK_URL", None)
        os.environ.pop("MPESA_TOPUP_CALLBACK_URL", None)

        assert payment_service.order_callback_url() == ""
        assert payment_service.topup_callback_url() == ""


@pytest.mark.asyncio
async def test_stk_push_refuses_rather_than_pushing_without_a_callback_url():
    """Fail closed: prompting for money with nowhere for the confirmation to
    land is exactly the defect, and it is worse than declining the payment."""
    result = await payment_service.initiate_stk_push(
        phone="254712345678", amount=100, callback_url=""
    )

    assert "error" in result, result
    # The two callers both read a missing CheckoutRequestID as "nothing was
    # charged"; the refusal has to arrive in that shape.
    assert "CheckoutRequestID" not in result
