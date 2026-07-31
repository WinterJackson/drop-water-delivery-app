import asyncio
import logging
import os
import time

import httpx
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

CLERK_ISSUER = os.getenv("CLERK_ISSUER")
CLERK_JWKS_URL  = os.getenv("CLERK_JWKS_URL")
FRONTEND_CLERK_API_KEY = os.getenv("FRONTEND_CLERK_API_KEY")

# python-jose skips audience validation entirely when `audience=None`, and skips
# issuer validation when `issuer=None`. A missing env var would therefore silently
# downgrade token verification to "any RS256 token signed by any key in the JWKS"
# — so refuse to start instead of running with a hole nobody can see.
_REQUIRED_CLERK_SETTINGS = {
    "CLERK_JWKS_URL": CLERK_JWKS_URL,
    "CLERK_ISSUER": CLERK_ISSUER,
    "FRONTEND_CLERK_API_KEY": FRONTEND_CLERK_API_KEY,
}
_missing_clerk_settings = [name for name, value in _REQUIRED_CLERK_SETTINGS.items() if not value]
if _missing_clerk_settings:
    message = (
        "Refusing to start: missing Clerk configuration "
        f"({', '.join(_missing_clerk_settings)}). Without these, JWT audience and "
        "issuer validation are silently skipped."
    )
    if os.getenv("ENV", "development") == "development" or os.getenv("PYTEST_CURRENT_TEST"):
        # Local and test runs may legitimately have no Clerk project wired up.
        logger.warning(message.replace("Refusing to start: ", ""))
    else:
        raise RuntimeError(message)

# ── JWKS cache ────────────────────────────────────────────────────────────────
# Three separate concerns, each with its own knob:
#
#   JWKS_CACHE_TTL           how long a healthy cache is reused without asking
#                            Clerk again (the point of caching at all).
#   JWKS_MIN_REFRESH_INTERVAL floor between *forced* refreshes. A forced refresh is
#                            triggered by an unknown `kid`, and `kid` is attacker-
#                            controlled — without a floor, a loop of junk tokens
#                            turns every request into an outbound call to Clerk.
#   JWKS_MAX_STALE           hard ceiling on serving a cache we failed to renew.
#                            Stale keys are normally harmless, but if Clerk revokes
#                            a compromised key we must stop honouring it rather than
#                            accept its signatures indefinitely.
JWKS_CACHE_TTL = 3600            # 1 hour
JWKS_MIN_REFRESH_INTERVAL = 60   # 1 minute
JWKS_MAX_STALE = 86400           # 24 hours

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0, "last_attempt": 0.0}
_jwks_lock = asyncio.Lock()


def _cached_keys() -> dict | None:
    """The cached document, or None once it is older than `JWKS_MAX_STALE`."""
    keys = _jwks_cache["keys"]
    if not keys:
        return None
    if (time.time() - _jwks_cache["fetched_at"]) > JWKS_MAX_STALE:
        logger.error(
            "JWKS cache is older than %ss and could not be renewed — refusing to "
            "verify tokens against keys Clerk may have revoked.",
            JWKS_MAX_STALE,
        )
        return None
    return keys


async def _fetch_jwks() -> dict | None:
    """One HTTP round-trip to Clerk. Updates the cache on success."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(CLERK_JWKS_URL)
            resp.raise_for_status()
            jwks = resp.json()
    except Exception as e:
        logger.error("Failed to fetch JWKS: %s: %s", type(e).__name__, e)
        return None

    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        logger.error("JWKS response was not a key set; keeping the previous cache.")
        return None

    _jwks_cache["keys"] = jwks
    _jwks_cache["fetched_at"] = time.time()
    return jwks


async def _get_jwks(force: bool = False) -> dict | None:
    """Return the JWKS, refreshing it when the cache is cold, expired or forced.

    `force=True` is how key rotation is survived: Clerk publishes the new key and
    starts signing with it immediately, but the cached document predates it, so
    every token would fail for up to `JWKS_CACHE_TTL`. An unknown `kid` is the
    signal to re-read, subject to `JWKS_MIN_REFRESH_INTERVAL`.

    The lock makes the refresh single-flight. Without it a cold cache under load
    sends one request to Clerk per in-flight verification.
    """
    if not CLERK_JWKS_URL:
        logger.error("CLERK_JWKS_URL is not configured")
        return None

    now = time.time()
    if not force and _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < JWKS_CACHE_TTL:
        return _jwks_cache["keys"]

    async with _jwks_lock:
        # Re-check under the lock: whoever held it may have just refreshed, in
        # which case this caller piggybacks on their result.
        now = time.time()
        fresh = _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < JWKS_CACHE_TTL
        if fresh and not force:
            return _jwks_cache["keys"]
        if force and (now - _jwks_cache["last_attempt"]) < JWKS_MIN_REFRESH_INTERVAL:
            # Rate-limit attacker-triggered refreshes; serve what we have.
            return _cached_keys()

        _jwks_cache["last_attempt"] = now
        jwks = await _fetch_jwks()

    # A failed renewal falls back to the cache, but only while it is within
    # `JWKS_MAX_STALE` — an outage should not become a permanent trust anchor.
    return jwks or _cached_keys()


def _find_key(jwks: dict, kid: str | None) -> dict | None:
    return next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)


async def verify_clerk_token(token: str):
    try:
        unverified_header = jwt.get_unverified_header(token)
    except (JWTError, KeyError, ValueError, AttributeError, TypeError) as e:
        logger.warning("Malformed token header: %s", type(e).__name__)
        return None

    kid = unverified_header.get("kid")
    if not kid:
        # Clerk always sets `kid`. A token without one cannot be matched to a key,
        # and picking a key for it would defeat the purpose of having a key set.
        logger.warning("Token verification failed: no `kid` in header")
        return None

    jwks = await _get_jwks()
    if not jwks:
        logger.error("JWKS unavailable — cannot verify token")
        return None

    key = _find_key(jwks, kid)
    if key is None:
        # Either a spoofed token, or Clerk rotated its signing key and our cache
        # predates the new one. Re-read once before deciding; the interval floor
        # inside `_get_jwks` keeps a stream of junk `kid`s from amplifying.
        jwks = await _get_jwks(force=True)
        key = _find_key(jwks, kid) if jwks else None
        if key is None:
            logger.warning("Token verification failed: unknown signing key `kid`")
            return None
        logger.info("JWKS refreshed on unknown `kid` — signing key rotation picked up.")

    try:
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=FRONTEND_CLERK_API_KEY,
            issuer=CLERK_ISSUER,
        )
    except (JWTError, KeyError, ValueError) as e:
        # Log securely without stack-traces for telemetry monitoring
        logger.warning(f"Token verification failed: {type(e).__name__}")
        return None
