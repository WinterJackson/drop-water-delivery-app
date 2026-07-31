"""
Authentication and session security.

Three separate failures are pinned here, each of which was exploitable:

1. **Registration trusted the request body.** `create_vendor` and `create_rider`
   took `clerk_id` from the posted JSON and had no auth dependency at all, so
   anyone could POST a vendor row bound to somebody else's Clerk subject — a
   direct account takeover, and a customer→vendor privilege escalation for the
   caller's own id.

2. **Key rotation locked everybody out.** The JWKS cache had a one-hour TTL and an
   unknown `kid` was treated as a forgery with no attempt to re-read. When Clerk
   rotated its signing key, every token in the platform failed verification for up
   to an hour.

3. **Sockets never re-checked expiry.** A REST call re-presents its token on every
   request. A socket presents one once, at connect, and then streams for hours —
   a rider signed out or deactivated mid-shift kept broadcasting.
"""
import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROUTES_DIR = Path(__file__).resolve().parent.parent / "routes"


# ── 1. Registration identity comes from the token ─────────────────────────


def _defaults_by_name(module: str, func: str) -> dict[str, ast.expr]:
    """Map parameter name → default expression for one route handler.

    Reading the AST rather than importing keeps this independent of whether the
    app can be constructed in the test environment.
    """
    tree = ast.parse((ROUTES_DIR / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            args = node.args
            names = [a.arg for a in [*args.posonlyargs, *args.args]]
            paired = dict(zip(names[len(names) - len(args.defaults):], args.defaults))
            paired.update(
                {a.arg: d for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None}
            )
            return paired
    raise AssertionError(f"{func} not found in routes/{module}")


@pytest.mark.parametrize("func", ["create_user", "register_vendor", "register_rider"])
def test_registration_endpoints_require_a_verified_token(func):
    """Registration must not be reachable anonymously.

    `_defaults_by_name` raises if the handler is gone, so a rename fails loudly
    rather than quietly testing nothing.
    """
    defaults = _defaults_by_name("auth_routes.py", func)
    source = ast.unparse(defaults.get("user")) if "user" in defaults else ""
    assert "get_current_user" in source, (
        f"{func} has no auth dependency — it could be called without a token"
    )


def test_registration_never_reads_clerk_id_from_the_request_body():
    """Every registration handler must overwrite `clerk_id` with `user["sub"]`.

    The body is attacker-controlled. Binding a new vendor or rider row to a
    `clerk_id` the caller supplied hands them whatever account that id names.
    """
    tree = ast.parse((ROUTES_DIR / "auth_routes.py").read_text())
    handlers = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    # (handler, the schema variable it mutates)
    targets = [
        ("create_user", "user_data"),
        ("register_vendor", "vendor_data"),
        ("register_rider", "rider_data"),
    ]
    for name, var in targets:
        node = handlers.get(name)
        assert node is not None, f"{name} is no longer a handler in auth_routes.py"
        body = ast.unparse(node)
        assert f"{var}.clerk_id = user['sub']" in body, (
            f"{name} does not derive clerk_id from the verified token"
        )


# ── 2. JWKS rotation ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    from core import security

    security._jwks_cache.update({"keys": None, "fetched_at": 0.0, "last_attempt": 0.0})
    yield
    security._jwks_cache.update({"keys": None, "fetched_at": 0.0, "last_attempt": 0.0})


def _jwks(*kids):
    return {"keys": [{"kid": k, "kty": "RSA", "n": "x", "e": "AQAB"} for k in kids]}


@pytest.mark.asyncio
async def test_unknown_kid_forces_one_refresh_and_then_verifies():
    """The rotation fix. Clerk publishes a new key and signs with it immediately;
    a cached document that predates it must be re-read, not treated as forgery."""
    from core import security

    security._jwks_cache.update({"keys": _jwks("old"), "fetched_at": time.time()})

    async def _fetch():
        security._jwks_cache.update({"keys": _jwks("old", "new"), "fetched_at": time.time()})
        return security._jwks_cache["keys"]

    with patch.object(security.jwt, "get_unverified_header", return_value={"kid": "new"}), patch.object(
        security, "_fetch_jwks", side_effect=_fetch
    ) as fetch, patch.object(security.jwt, "decode", return_value={"sub": "user_1"}):
        payload = await security.verify_clerk_token("token")

    assert payload == {"sub": "user_1"}
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_a_kid_that_is_still_unknown_after_refresh_is_rejected():
    """The refresh must not become a way to accept anything."""
    from core import security

    security._jwks_cache.update({"keys": _jwks("old"), "fetched_at": time.time()})

    with patch.object(security.jwt, "get_unverified_header", return_value={"kid": "forged"}), patch.object(
        security, "_fetch_jwks", AsyncMock(return_value=_jwks("old"))
    ), patch.object(security.jwt, "decode", side_effect=AssertionError("must not decode")):
        assert await security.verify_clerk_token("token") is None


@pytest.mark.asyncio
async def test_forced_refreshes_are_rate_limited():
    """`kid` is attacker-controlled. Without a floor between forced refreshes a
    stream of junk tokens turns every request into an outbound call to Clerk."""
    from core import security

    now = time.time()
    security._jwks_cache.update({"keys": _jwks("old"), "fetched_at": now, "last_attempt": now})

    with patch.object(security, "_fetch_jwks", AsyncMock(return_value=_jwks("old"))) as fetch:
        for _ in range(20):
            await security._get_jwks(force=True)

    assert fetch.await_count == 0, "forced refresh ignored JWKS_MIN_REFRESH_INTERVAL"


@pytest.mark.asyncio
async def test_a_cold_cache_refreshes_once_under_concurrent_load():
    """Single-flight. Without the lock, N in-flight verifications on a cold cache
    each sent their own request to Clerk."""
    from core import security

    calls = 0

    async def _slow():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        security._jwks_cache.update({"keys": _jwks("k1"), "fetched_at": time.time()})
        return security._jwks_cache["keys"]

    with patch.object(security, "_fetch_jwks", side_effect=_slow):
        await asyncio.gather(*[security._get_jwks() for _ in range(10)])

    assert calls == 1


@pytest.mark.asyncio
async def test_a_cache_too_stale_to_trust_is_not_used():
    """Stale keys are normally harmless, but a key Clerk revoked because it leaked
    must stop being honoured rather than serve as a permanent trust anchor."""
    from core import security

    security._jwks_cache.update(
        {"keys": _jwks("k1"), "fetched_at": time.time() - (security.JWKS_MAX_STALE + 60)}
    )

    with patch.object(security, "_fetch_jwks", AsyncMock(return_value=None)):
        assert await security._get_jwks() is None


@pytest.mark.asyncio
async def test_a_recent_cache_survives_a_failed_renewal():
    """The converse: an outage at Clerk must not sign every user out."""
    from core import security

    security._jwks_cache.update({"keys": _jwks("k1"), "fetched_at": time.time() - 7200})

    with patch.object(security, "_fetch_jwks", AsyncMock(return_value=None)):
        assert await security._get_jwks() == _jwks("k1")


@pytest.mark.asyncio
async def test_a_token_with_no_kid_is_rejected_without_touching_the_network():
    from core import security

    with patch.object(security.jwt, "get_unverified_header", return_value={"alg": "RS256"}), patch.object(
        security, "_get_jwks", AsyncMock(side_effect=AssertionError("must not fetch"))
    ):
        assert await security.verify_clerk_token("token") is None


def test_only_rs256_is_accepted():
    """`algorithms` must stay pinned. Omitting it lets a token declare `alg: none`
    or HS256 and be verified against the public key as a shared secret."""
    source = (Path(__file__).resolve().parent.parent / "core" / "security.py").read_text()
    assert 'algorithms=["RS256"]' in source


# ── 3. WebSocket session expiry ───────────────────────────────────────────


def test_an_expired_token_ends_the_socket():
    from routes.websocket_routes import _token_expired

    assert _token_expired({"exp": time.time() - 1}) is True
    assert _token_expired({"exp": time.time() + 300}) is False


def test_a_token_without_an_expiry_is_treated_as_expired():
    """Fail closed: a socket is the one place a token is not re-presented, so an
    unexpected shape must not buy an unbounded session."""
    from routes.websocket_routes import _token_expired

    assert _token_expired({}) is True
    assert _token_expired({"exp": None}) is True
    assert _token_expired({"exp": "not-a-number"}) is True


@pytest.mark.asyncio
async def test_the_socket_is_closed_with_a_reconnectable_code():
    """1008 (policy violation), not 1011 (server error): every client reconnects
    on close with a freshly minted token, so this costs a reconnect rather than a
    dropped session."""
    from routes.websocket_routes import _close_if_token_expired

    ws = AsyncMock()
    assert await _close_if_token_expired(ws, {"exp": time.time() - 1}) is True
    ws.close.assert_awaited_once()
    assert ws.close.await_args.kwargs["code"] == 1008


@pytest.mark.asyncio
async def test_a_live_token_leaves_the_socket_open():
    from routes.websocket_routes import _close_if_token_expired

    ws = AsyncMock()
    assert await _close_if_token_expired(ws, {"exp": time.time() + 300}) is False
    ws.close.assert_not_awaited()


def test_every_socket_loop_checks_expiry():
    """Adding a fourth socket without the check would silently reintroduce the
    unbounded session, so assert on the count rather than on any one handler."""
    source = (ROUTES_DIR / "websocket_routes.py").read_text()
    assert source.count("_close_if_token_expired(websocket, user)") == 3


def test_every_socket_loop_accepts_an_in_band_token_refresh():
    """Expiry enforcement without a refresh path would rebuild every socket on the
    platform once a minute, since Clerk tokens live about that long."""
    source = (ROUTES_DIR / "websocket_routes.py").read_text()
    assert source.count("_handle_auth_refresh(websocket, user,") == 3


@pytest.mark.asyncio
async def test_a_refresh_extends_the_session_in_place():
    from routes.websocket_routes import _handle_auth_refresh

    ws = AsyncMock()
    user = {"sub": "clerk_me", "exp": time.time() - 1}
    fresh_exp = time.time() + 600

    with patch(
        "routes.websocket_routes.verify_clerk_token",
        AsyncMock(return_value={"sub": "clerk_me", "exp": fresh_exp}),
    ):
        consumed = await _handle_auth_refresh(
            ws, user, {"action": "auth_refresh", "token": "fresh"}
        )

    assert consumed is True
    assert user["exp"] == fresh_exp     # mutated in place — the loop reads this dict
    ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refresh_cannot_hand_the_socket_to_another_account():
    """The socket's entity/order access was authorised at connect for one subject.
    Accepting a valid token for a *different* subject would donate that authorised
    stream to whoever presented it."""
    from routes.websocket_routes import _handle_auth_refresh

    ws = AsyncMock()
    user = {"sub": "clerk_me", "exp": time.time() + 300}

    with patch(
        "routes.websocket_routes.verify_clerk_token",
        AsyncMock(return_value={"sub": "clerk_attacker", "exp": time.time() + 600}),
    ):
        consumed = await _handle_auth_refresh(
            ws, user, {"action": "auth_refresh", "token": "valid-but-someone-else"}
        )

    assert consumed is True
    assert user["sub"] == "clerk_me"
    ws.close.assert_awaited_once()
    assert ws.close.await_args.kwargs["code"] == 1008


@pytest.mark.asyncio
async def test_an_unverifiable_refresh_token_closes_the_socket():
    from routes.websocket_routes import _handle_auth_refresh

    ws = AsyncMock()
    user = {"sub": "clerk_me", "exp": time.time() + 300}

    with patch("routes.websocket_routes.verify_clerk_token", AsyncMock(return_value=None)):
        assert await _handle_auth_refresh(ws, user, {"action": "auth_refresh", "token": "x"}) is True

    ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ordinary_messages_pass_through_untouched():
    """The handler must not swallow location updates or room joins."""
    from routes.websocket_routes import _handle_auth_refresh

    ws = AsyncMock()
    user = {"sub": "clerk_me", "exp": time.time() + 300}

    for message in ({"action": "join-entity-room"}, {"lat": 1.0, "lng": 2.0}, {}):
        assert await _handle_auth_refresh(ws, user, message) is False
    ws.close.assert_not_awaited()


# ── Entity authorisation is still enforced ────────────────────────────────


@pytest.mark.asyncio
async def test_owning_a_different_rider_id_is_refused():
    """Authentication proves who is calling; it says nothing about the id in the
    URL. Without this, any signed-in account could stream fabricated GPS for an
    arbitrary rider."""
    from dependencies.auth_dependencies import owns_entity
    from uuid import uuid4

    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(clerk_id="clerk_other"))
    assert await owns_entity(session, "rider", str(uuid4()), "clerk_me") is False


@pytest.mark.asyncio
async def test_a_malformed_entity_id_is_refused_rather_than_raising():
    from dependencies.auth_dependencies import owns_entity

    session = AsyncMock()
    assert await owns_entity(session, "rider", "not-a-uuid", "clerk_me") is False


@pytest.mark.asyncio
async def test_an_unknown_entity_type_is_refused():
    from dependencies.auth_dependencies import owns_entity
    from uuid import uuid4

    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(clerk_id="clerk_me"))
    assert await owns_entity(session, "admin", str(uuid4()), "clerk_me") is False


@pytest.mark.asyncio
async def test_a_stranger_gets_404_not_403_on_an_order():
    """403 confirms the order id exists. 404 does not."""
    from fastapi import HTTPException
    from dependencies.auth_dependencies import authorise_order_access
    from uuid import uuid4

    session = AsyncMock()
    with patch(
        "dependencies.auth_dependencies.resolve_order_role", AsyncMock(return_value=None)
    ), pytest.raises(HTTPException) as exc:
        await authorise_order_access(session, uuid4(), "clerk_stranger")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_party_to_the_order_outside_the_allowed_roles_is_refused():
    """A rider is a party to the order but must not reach a customer-only
    endpoint; membership and permission are different questions."""
    from fastapi import HTTPException
    from dependencies.auth_dependencies import authorise_order_access
    from uuid import uuid4

    session = AsyncMock()
    with patch(
        "dependencies.auth_dependencies.resolve_order_role", AsyncMock(return_value="rider")
    ), pytest.raises(HTTPException) as exc:
        await authorise_order_access(session, uuid4(), "clerk_rider", allowed_roles=("customer",))

    assert exc.value.status_code == 404


# ── Webhook and callback guards ───────────────────────────────────────────


def test_the_sms_webhook_is_not_reachable_without_the_shared_secret():
    """It marks orders delivered. An unguarded version let anyone close out an
    order they did not deliver."""
    source = (ROUTES_DIR / "sms_routes.py").read_text()
    assert "SMS_WEBHOOK_SECRET" in source
    assert "compare_digest" in source, "secret compared without a constant-time check"


def test_mpesa_callbacks_are_not_protected_by_ip_alone():
    """`ProxyHeadersMiddleware(trusted_hosts=["*"])` makes the client IP
    attacker-controlled, so the allow-list cannot be the only guard on endpoints
    that mark payouts complete or reverse transactions.

    The guard used to be a hand-written comparison in each module. It is now a
    single call to `payment_service.reject_mpesa_callback`, which also fails
    closed when the secret is unset — see
    `tests/test_callback_guard_and_deletion.py`.
    """
    for module in ("payout_routes.py", "refund_routes.py", "wallet_routes.py", "cart_routes.py"):
        source = (ROUTES_DIR / module).read_text()
        assert "reject_mpesa_callback" in source, f"{module} has no shared-secret guard"
