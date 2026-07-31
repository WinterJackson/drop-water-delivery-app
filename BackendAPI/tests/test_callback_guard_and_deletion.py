"""
Two defects that shared a shape: a guard written so that missing configuration
disabled it, rather than refusing the request.

`if MPESA_CALLBACK_SECRET and supplied != MPESA_CALLBACK_SECRET` was copied into
five callback handlers. Unset, the comparison vanished and the only remaining
layer was an IP allow-list read from an attacker-controlled header — on
endpoints that mark orders paid and refund debited wallet balances.

`if clerk_secret:` around account deletion did the same thing to a
data-protection obligation: it skipped the Clerk deletion silently while the
endpoint still reported the account permanently deleted.

The routing test is here for a related reason: the B2C callbacks existed,
correct and unreachable, because the router carrying them was dropped from
`main.py` while `wallet_service` kept disbursing real money to
`MPESA_B2C_RESULT_URL`.
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from routes import auth_routes
from services import payment_service


# ── M-Pesa callback guard ─────────────────────────────────────────────────


def _request(ip: str = "196.201.214.200", forwarded: str | None = None):
    """A stand-in Request carrying just what the guard reads."""
    req = MagicMock()
    req.headers = {"x-forwarded-for": forwarded} if forwarded else {}
    req.client = MagicMock()
    req.client.host = ip
    return req


def test_an_unset_secret_refuses_the_callback_in_production():
    """The defect: unset used to mean *unguarded*, not *refused*."""
    with patch.dict(os.environ, {"ENV": "production"}, clear=False):
        os.environ.pop("MPESA_CALLBACK_SECRET", None)
        rejected = payment_service.reject_mpesa_callback(_request(), None, "test")
        assert rejected is not None
        assert rejected.status_code == 503


def test_an_unset_secret_is_permitted_in_development():
    with patch.dict(os.environ, {"ENV": "development"}, clear=False):
        os.environ.pop("MPESA_CALLBACK_SECRET", None)
        assert payment_service.reject_mpesa_callback(_request(), None, "test") is None


def test_a_wrong_secret_is_rejected():
    with patch.dict(
        os.environ, {"ENV": "production", "MPESA_CALLBACK_SECRET": "right"}, clear=False
    ):
        rejected = payment_service.reject_mpesa_callback(_request(), "wrong", "test")
        assert rejected is not None
        assert rejected.status_code == 403


def test_a_missing_secret_is_rejected_when_one_is_configured():
    """Safaricom calling the pre-rollout URL must not be waved through."""
    with patch.dict(
        os.environ, {"ENV": "production", "MPESA_CALLBACK_SECRET": "right"}, clear=False
    ):
        rejected = payment_service.reject_mpesa_callback(_request(), None, "test")
        assert rejected is not None
        assert rejected.status_code == 403


def test_the_correct_secret_from_a_safaricom_ip_passes():
    with patch.dict(
        os.environ, {"ENV": "production", "MPESA_CALLBACK_SECRET": "right"}, clear=False
    ):
        assert payment_service.reject_mpesa_callback(_request(), "right", "test") is None


def test_a_correct_secret_from_a_foreign_ip_is_still_rejected():
    """Defence in depth: the secret can leak through access logs in query form."""
    with patch.dict(
        os.environ, {"ENV": "production", "MPESA_CALLBACK_SECRET": "right"}, clear=False
    ):
        rejected = payment_service.reject_mpesa_callback(
            _request(ip="203.0.113.9"), "right", "test"
        )
        assert rejected is not None
        assert rejected.status_code == 403


def test_the_forwarded_header_wins_over_the_socket_peer():
    """Render terminates TLS at its edge; the socket peer is the proxy."""
    with patch.dict(
        os.environ, {"ENV": "production", "MPESA_CALLBACK_SECRET": "right"}, clear=False
    ):
        req = _request(ip="10.0.0.1", forwarded="196.201.214.200, 10.0.0.1")
        assert payment_service.reject_mpesa_callback(req, "right", "test") is None


def test_no_callback_route_still_reads_the_secret_inline():
    """Structural guard, over the AST rather than the file text.

    The bug was five hand-written copies of one comparison; a sixth would
    reintroduce it silently, so the copies themselves are what is banned. Text
    matching would also fire on prose *describing* the defect — including the
    docstring at the top of this file — so this walks the syntax tree and looks
    only at real `os.getenv("MPESA_CALLBACK_SECRET")` calls.
    """
    import ast
    import pathlib

    routes_dir = pathlib.Path(__file__).resolve().parent.parent / "routes"
    offenders = []
    for path in routes_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in {"getenv", "get"}:
                continue
            if any(
                isinstance(a, ast.Constant) and a.value == "MPESA_CALLBACK_SECRET"
                for a in node.args
            ):
                offenders.append(path.name)

    assert offenders == [], (
        f"{sorted(set(offenders))} read MPESA_CALLBACK_SECRET directly; "
        "use payment_service.reject_mpesa_callback instead."
    )


# ── B2C callbacks must be reachable ───────────────────────────────────────


def test_the_b2c_callbacks_are_routed():
    """`wallet_service` disburses real money and points Safaricom at these.

    While they were unrouted every withdrawal stayed `processing` for ever, and
    a disbursement that failed after Safaricom queued it never refunded the
    balance that had already been debited.
    """
    import main

    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert "/api/payouts/mpesa/b2c_result" in paths
    assert "/api/payouts/mpesa/b2c_timeout" in paths


def test_the_legacy_payout_endpoints_stay_unrouted():
    """Cashouts go through /api/wallet/withdraw; the old ones were retired."""
    import main

    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert "/api/payouts/request" not in paths


def test_the_b2c_result_url_env_var_matches_the_mounted_path():
    """A result URL pointing anywhere else is the bug this whole file exists for."""
    configured = os.getenv("MPESA_B2C_RESULT_URL", "")
    if not configured:
        pytest.skip("MPESA_B2C_RESULT_URL not set in this environment")
    assert "/api/payouts/mpesa/b2c_result" in configured


# ── Account deletion ──────────────────────────────────────────────────────


def test_deletion_is_refused_when_the_clerk_secret_is_missing():
    """The defect: it returned "permanently deleted" while the identity lived on."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CLERK_SECRET_KEY", None)
        with pytest.raises(HTTPException) as exc:
            auth_routes._require_clerk_secret()
        assert exc.value.status_code == 503


def test_the_clerk_secret_is_returned_when_configured():
    with patch.dict(os.environ, {"CLERK_SECRET_KEY": "sk_test_x"}, clear=False):
        assert auth_routes._require_clerk_secret() == "sk_test_x"


@pytest.mark.asyncio
async def test_the_clerk_identity_is_deleted_off_the_event_loop():
    """`clerk_backend_api` is synchronous; calling it directly blocks the loop."""
    clerk = MagicMock()
    with patch("clerk_backend_api.Clerk", return_value=clerk):
        assert await auth_routes._delete_clerk_identity("sk_test_x", "user_123") is True
    clerk.users.delete.assert_called_once_with("user_123")


@pytest.mark.asyncio
async def test_a_clerk_failure_reports_itself_instead_of_claiming_success():
    clerk = MagicMock()
    clerk.users.delete.side_effect = RuntimeError("clerk is down")
    with patch("clerk_backend_api.Clerk", return_value=clerk):
        assert await auth_routes._delete_clerk_identity("sk_test_x", "user_123") is False


def test_a_failed_clerk_delete_is_surfaced_in_the_response():
    """The PII really is gone, so this is a warning — but it must not be silent."""
    ok = auth_routes._deletion_response("Deleted.", clerk_deleted=True)
    assert "warning" not in ok

    degraded = auth_routes._deletion_response("Deleted.", clerk_deleted=False)
    assert degraded["clerk_identity_deleted"] is False
    assert "warning" in degraded


def test_no_delete_flow_skips_clerk_removal_on_a_falsy_secret():
    """Structural guard against a truthiness check on the secret returning.

    Over the AST, so the prose in this file's docstring — which necessarily
    quotes the defect — does not trip it.
    """
    import ast
    import pathlib

    tree = ast.parse(
        (
            pathlib.Path(__file__).resolve().parent.parent / "routes" / "auth_routes.py"
        ).read_text()
    )
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "clerk_secret"
    ]
    assert offenders == [], (
        f"lines {offenders}: account deletion must not make Clerk removal "
        "conditional on the secret being present — call _require_clerk_secret() "
        "before mutating any row instead."
    )
