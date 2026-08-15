"""Reading a caller's own identity from Clerk, once.

An invitation — to staff a store, or to administer the platform — is addressed
to an **email address**, because that is the only thing the person issuing it
knows. It becomes a grant when somebody signs in and that address is matched to
their Clerk subject. So the question "what is this caller's email address?" is
an authorisation decision, and the answer has to be a mailbox they demonstrably
hold rather than a string they typed.

Clerk lets a user attach an arbitrary secondary address to their own account,
and it stays `unverified` until they enter a code sent to it. `verification`
status is therefore the whole security of the match.

**This module exists because there were two copies of that lookup and both were
wrong the same way.** Each walked `email_addresses`, preferred the one matching
`primary_email_address_id`, and — on an unordered list — fell back to
`addresses[0]` when nothing matched. Neither looked at verification at all. The
vendor copy handed over a store; the admin copy handed over the console, which
reads every customer's details, every rider's national ID, and the money.

That is the shape this codebase refuses everywhere else: two implementations of
one rule, drifting, with the permissive one in the path that matters. One
function now, and `tests/test_identity_binding.py` fails the build if a second
appears.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _verified(address) -> bool:
    """Has Clerk confirmed the account holder actually receives mail here?

    Read defensively: a shape change in the SDK must fail *closed* — an address
    whose verification cannot be read is not treated as verified.
    """
    verification = getattr(address, "verification", None)
    status = getattr(verification, "status", None)
    if status is None and isinstance(verification, dict):
        status = verification.get("status")
    return status == "verified"


def _pick(user) -> str | None:
    """The caller's verified primary address, or a verified one, or nothing.

    There is deliberately **no** unverified fallback. An account with no
    verified address binds no invitation, which is the correct answer rather
    than a degraded one — the alternative is letting somebody claim a grant
    addressed to a mailbox they do not hold.
    """
    addresses = getattr(user, "email_addresses", None) or []
    verified = [a for a in addresses if _verified(a)]
    if not verified:
        return None

    primary_id = getattr(user, "primary_email_address_id", None)
    for address in verified:
        if getattr(address, "id", None) == primary_id:
            return getattr(address, "email_address", None)

    # Primary is unset, or points at an address that is not verified. Any
    # verified address still proves possession, which is what the match needs.
    return getattr(verified[0], "email_address", None)


async def verified_email_for(clerk_id: str) -> str | None:
    """This Clerk subject's own verified email address, lowercased.

    Returns `None` — never raises — when Clerk is unreachable, unconfigured, or
    the account holds no verified address. Every caller is on a sign-in path,
    where a failure must leave the invitation pending for the next attempt
    rather than turning somebody's sign-in into a 500.

    Looking up the caller's *own* identity leaks nothing: they already know
    their own address.
    """
    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret or not clerk_id:
        return None

    def _lookup() -> str | None:
        from clerk_backend_api import Clerk

        clerk = Clerk(bearer_auth=secret)
        return _pick(clerk.users.get(user_id=clerk_id))

    try:
        # The Clerk SDK is synchronous. Called inline it blocks the event loop
        # for the whole round trip, stalling every other request on the worker.
        email = await asyncio.to_thread(_lookup)
    except Exception as exc:
        logger.warning("CLERK_IDENTITY_LOOKUP_FAILED clerk=%s: %s", clerk_id, exc)
        return None

    return email.strip().lower() if email else None
