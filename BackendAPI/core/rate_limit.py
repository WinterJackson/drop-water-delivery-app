"""Who a rate limit counts against.

The limiter used to key on `get_remote_address`, which is the client IP. That is
the right key for a web application and the wrong one for this platform.

Safaricom and Airtel put mobile data subscribers behind **carrier-grade NAT**.
Thousands of Drop customers reach this API from a handful of egress addresses,
and `ProxyHeadersMiddleware` trusts `X-Forwarded-For` from every hop, so
`get_remote_address` returns that shared carrier address. Keyed on it, the global
`100/minute` default is not a per-user budget at all — it is a budget shared by
every Safaricom data subscriber using the app at once. The busiest customer
throttles the quietest, the 429s look random and unreproducible, and load-testing
from a single office IP reproduces the symptom perfectly while never explaining
it.

So the key is the **authenticated subject** where there is one, and the address
only where there is not.

## Why the token is verified here rather than merely read

The subject could be read straight out of the JWT payload without checking the
signature — it is only a bucket name. It could not be *trusted*: a JWT is
base64-encoded JSON, so anyone can mint one with a random `sub`, and an unverified
key would hand every attacker an unlimited supply of fresh buckets. That is
strictly worse than keying on the address.

Verification is therefore real, and made cheap rather than skipped. `_SubjectCache`
memoises the result against the token itself, so the RSA verify happens once per
token per replica; Clerk's session tokens are short-lived, which caps the cache
without any eviction policy having to be clever. A token that fails verification
is not an error here — the request is going to be refused by its own dependency a
moment later — it just falls back to the address.

## The address limit stays

Keying on the subject alone would mean an unauthenticated flood costs nothing, so
the two work together: the subject key bounds what one account may do, and the
address key still bounds what one connection may do before it has proved anything.
"""

import hashlib
import logging
import time
from typing import Optional

from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

#: How long a verified subject is trusted without re-verifying. Well under a
#: Clerk session token's own lifetime, so this can never extend one.
_SUBJECT_TTL_SECONDS = 60

#: Ceiling on distinct tokens remembered at once. Reached only under a flood of
#: distinct bearer tokens, which is exactly when unbounded growth would matter.
_SUBJECT_CACHE_MAX = 4096


class _SubjectCache:
    """Token → subject, with a TTL and a hard size ceiling.

    Keyed on a SHA-256 of the token rather than the token itself: this dict is
    reachable from a traceback, a heap dump and a debugger, and a bearer token
    sitting in one is a credential at rest for no reason.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get(self, token: str) -> Optional[str]:
        entry = self._entries.get(self._key(token))
        if not entry:
            return None
        subject, expires_at = entry
        if time.monotonic() >= expires_at:
            self._entries.pop(self._key(token), None)
            return None
        return subject

    def put(self, token: str, subject: str) -> None:
        if len(self._entries) >= _SUBJECT_CACHE_MAX:
            # Drop everything already expired before resorting to anything
            # harsher. Under normal load this empties most of the map, because
            # entries live 60 seconds.
            now = time.monotonic()
            self._entries = {k: v for k, v in self._entries.items() if v[1] > now}
            if len(self._entries) >= _SUBJECT_CACHE_MAX:
                self._entries.clear()
        self._entries[self._key(token)] = (subject, time.monotonic() + _SUBJECT_TTL_SECONDS)


_subjects = _SubjectCache()


def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


async def resolve_rate_limit_key(request: Request) -> str:
    """`sub:<clerk id>` for an authenticated caller, `ip:<address>` otherwise."""
    token = _bearer(request)
    if not token:
        return f"ip:{get_remote_address(request)}"

    cached = _subjects.get(token)
    if cached:
        return f"sub:{cached}"

    try:
        from core.security import verify_clerk_token

        payload = await verify_clerk_token(token)
    except Exception as exc:  # pragma: no cover - defensive
        # Never let the limiter be the thing that fails a request. A limiter that
        # can 500 is worse than one keyed slightly too coarsely.
        logger.warning("Rate-limit subject resolution failed: %s", type(exc).__name__)
        payload = None

    subject = (payload or {}).get("sub")
    if not subject:
        return f"ip:{get_remote_address(request)}"

    _subjects.put(token, str(subject))
    return f"sub:{subject}"


def rate_limit_key(request: Request) -> str:
    """The synchronous `key_func` slowapi calls.

    slowapi's key function cannot be a coroutine, so the resolution happens in
    `RateLimitKeyMiddleware` — which runs **outside** `SlowAPIMiddleware` — and
    this only reads what it left behind. If the middleware is not installed, or
    ran before the header was available, this degrades to the address rather than
    failing: an ordering mistake must not switch the limiter off silently, and
    `tests/test_rate_limiting.py` fails the build if the middleware order changes.
    """
    key = getattr(request.state, "rate_limit_key", None)
    if key:
        return key
    return f"ip:{get_remote_address(request)}"


class RateLimitKeyMiddleware(BaseHTTPMiddleware):
    """Resolves the limiter's key before `SlowAPIMiddleware` consults it.

    Must be added to the app **after** `SlowAPIMiddleware`: Starlette runs
    middleware outermost-first in reverse order of registration, so the one added
    later is the one that runs earlier.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.rate_limit_key = await resolve_rate_limit_key(request)
        return await call_next(request)
