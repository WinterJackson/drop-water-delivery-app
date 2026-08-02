"""Is CLERK_SECRET_KEY set, valid, and pointed at the *same* Clerk instance?

Three things can go wrong, and only the first announces itself:

1. The variable is unset. Account deletion returns 503 and staff invitations
   return 503. Both fail closed, so this one is visible.
2. The key is valid but belongs to a **different Clerk instance** than
   `CLERK_ISSUER` / `CLERK_JWKS_URL`. Nothing 503s. Tokens still verify, because
   verification reads the JWKS URL. But every `users.list(email_address=…)`
   looks in the other instance's directory, so *every* staff invitation is
   recorded as pending and never binds — the owner sees "invitation sent", the
   member signs in, and nothing happens. Account deletion 404s on a Clerk id
   that exists, just not there.
3. The key was rotated in the dashboard and not here. Same symptom as (1), but
   as a 502 from the lookup rather than a 503.

(2) is the reason this script exists. A secret key is an opaque `sk_…` string
that carries no instance name, so pasting the wrong one is silent. The check:
Clerk's JWKS `kid` **is** the instance id, so the key's own instance
(`GET https://api.clerk.com/v1/jwks`, authenticated) can be compared against the
public JWKS the API verifies tokens with. If the two agree, they are the same
instance.

Usage — locally, or in a Render shell where the environment is already loaded:

    python scripts/check_clerk_secret.py

Exits 0 when everything lines up, 1 otherwise. Prints no secrets.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from dotenv import load_dotenv

# Locally the values live in BackendAPI/.env; on Render they are already in the
# process environment and this is a no-op.
load_dotenv()

TIMEOUT = 20.0
CLERK_API = "https://api.clerk.com/v1/jwks"


def _fingerprint(secret: str) -> str:
    """Enough to tell two keys apart in a screenshot, not enough to use one."""
    return f"{secret[:11]}…{secret[-4:]}" if len(secret) > 20 else "…"


def _kids(jwks: dict) -> set[str]:
    return {k.get("kid", "") for k in jwks.get("keys", []) if k.get("kid")}


def main() -> int:
    problems: list[str] = []
    notes: list[str] = []

    secret = (os.getenv("CLERK_SECRET_KEY") or "").strip()
    issuer = (os.getenv("CLERK_ISSUER") or "").strip().rstrip("/")
    jwks_url = (os.getenv("CLERK_JWKS_URL") or "").strip()

    if not jwks_url and issuer:
        jwks_url = f"{issuer}/.well-known/jwks.json"

    # ── Present? ──────────────────────────────────────────────────────────
    if not secret:
        print("FAIL  CLERK_SECRET_KEY is not set.")
        print("      Account deletion and staff invitations both return 503.")
        return 1

    if not secret.startswith(("sk_test_", "sk_live_")):
        problems.append(
            "CLERK_SECRET_KEY does not look like a Clerk secret key "
            "(expected sk_test_… or sk_live_…). A publishable key (pk_…) is a "
            "different value and will not authenticate."
        )

    print(f"      key           {_fingerprint(secret)}")
    print(f"      issuer        {issuer or '(unset)'}")

    # ── Live, and which instance? ─────────────────────────────────────────
    key_kids: set[str] = set()
    try:
        response = httpx.get(
            CLERK_API, headers={"Authorization": f"Bearer {secret}"}, timeout=TIMEOUT
        )
        if response.status_code in (401, 403):
            problems.append(
                f"Clerk rejected the key ({response.status_code}). It is wrong, "
                "revoked, or rotated in the dashboard without being updated here."
            )
        elif response.status_code >= 400:
            problems.append(f"Clerk returned {response.status_code} for {CLERK_API}.")
        else:
            key_kids = _kids(response.json())
    except httpx.HTTPError as e:
        problems.append(f"Could not reach {CLERK_API}: {e}")

    # ── The same instance the API verifies tokens against? ────────────────
    if not jwks_url:
        problems.append(
            "Neither CLERK_JWKS_URL nor CLERK_ISSUER is set, so the key cannot be "
            "checked against the instance whose tokens this API accepts."
        )
    elif key_kids:
        try:
            public = httpx.get(jwks_url, timeout=TIMEOUT)
            public.raise_for_status()
            issuer_kids = _kids(public.json())
        except (httpx.HTTPError, ValueError) as e:
            problems.append(f"Could not read the public JWKS at {jwks_url}: {e}")
        else:
            if not issuer_kids:
                problems.append(f"{jwks_url} returned no keys.")
            elif key_kids & issuer_kids:
                print(f"      instance      {sorted(key_kids & issuer_kids)[0]}")
            else:
                problems.append(
                    "CLERK_SECRET_KEY belongs to a DIFFERENT Clerk instance than "
                    f"CLERK_ISSUER.\n        key instance    {sorted(key_kids)}\n"
                    f"        issuer instance {sorted(issuer_kids)}\n"
                    "      Staff invitations will never bind and account deletion "
                    "will not find the user. Take the key from the same Clerk "
                    "application as the issuer above."
                )

    # ── Does it have the permission the code actually needs? ──────────────
    if not problems:
        try:
            from clerk_backend_api import Clerk

            clerk = Clerk(bearer_auth=secret)
            # The exact call `vendor_staff_service._lookup_clerk_id` makes. The
            # address is not expected to exist; an empty list is a pass.
            clerk.users.list(request={"email_address": ["nobody.check@drop.invalid"]})
            print("      users.list    ok")
        except Exception as e:  # noqa: BLE001 — surface whatever Clerk said
            problems.append(
                f"The key authenticates but users.list failed: {e}\n"
                "      Staff invitations call this on every invite."
            )

    # ── Consistency notes ─────────────────────────────────────────────────
    is_dev_issuer = ".clerk.accounts.dev" in (issuer or jwks_url)
    if secret.startswith("sk_live_") and is_dev_issuer:
        notes.append(
            "A production key against a development issuer. These are always "
            "two different instances; expect the mismatch above."
        )
    if secret.startswith("sk_test_") and os.getenv("ENV") == "production":
        notes.append(
            "ENV=production with a Clerk *development* instance (sk_test_…). "
            "Development instances carry lower rate limits, a separate user "
            "directory, and relaxed session security. Fine for internal "
            "testing; move to a production instance before public release — and "
            "when you do, CLERK_ISSUER, CLERK_JWKS_URL, the secret key and the "
            "apps' EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY must all move together."
        )

    for note in notes:
        print(f"NOTE  {note}")
    for problem in problems:
        print(f"FAIL  {problem}")

    if problems:
        return 1
    print("OK    CLERK_SECRET_KEY is set, valid, and matches the issuer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
