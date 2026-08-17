"""Can the test identities actually sign in, and if not, why.

`test_accounts.py list` answers "does the account exist and is it bound". That is
not the same question as "can somebody sign in with it", and the two came apart:
every row read `yes yes yes` while all five were refused at the password step,
because **the Clerk instance had a second factor enabled**. No account had one
enrolled — `two_factor_enabled` was false on all five — so nothing about the
users explained it, and each app reported it differently and none named the
cause:

    customer  "Two-factor authentication is currently not supported on this app.
               Please log in via the web or disable 2FA."
    rider     "Additional verification is required to sign in. Please check your
               email or contact support."
    vendor    "Login incomplete. Status: needs_second_factor."

The first is the actively misleading one: there is no 2FA on the account to
disable, and the web sign-in it recommends would demand the same second factor.

So this asks Clerk the question the app asks, through the same Frontend API and
the same publishable key, and prints the status Clerk returns. It reproduces a
sign-in failure without a handset, an APK or a rebuild — which is what made the
original diagnosis slow.

    python scripts/check_test_signin.py

Exit code is 0 only when every identity reaches `complete`.

It signs in and immediately abandons the attempt; no session is left behind, and
nothing here writes to Clerk or to the database. Development instance only — it
refuses a `pk_live_` key, because these passwords are published.
"""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

#: The same roster `test_accounts.py` provisions, plus the console's five. All
#: eight hit the same instance setting, so all eight are worth one answer.
APP_IDENTITIES = [
    "customer", "rider", "vendor-retail", "vendor-wholesale", "vendor-staff",
]
CONSOLE_IDENTITIES = [
    "super-admin", "operations", "finance", "support", "analyst",
]

PASSWORD = "Drop2026!!"
SUBADDRESS = "+clerk_test"
DOMAIN = "example.com"

#: Clerk's JS version travels as a query parameter on every Frontend API call.
#: Omitted, Clerk answers with a payload shape a much older client expects.
CLERK_JS = "5.35.0"

#: Seconds between attempts. Clerk rate-limits sign-ins per instance, and ten
#: back to back trips it — reporting "Too many requests" for every identity
#: after the third, which reads exactly like a credential problem.
PACE_SECONDS = 1.5

#: What each status means for somebody holding a handset.
EXPLAIN = {
    "complete": "signs in",
    "needs_second_factor": (
        "the INSTANCE requires a second factor. Not the account — check "
        "Clerk Dashboard > Configure > User & authentication > Multi-factor "
        "and turn off every factor. No app implements one."
    ),
    "needs_first_factor": "the password was not accepted as a first factor",
    "needs_identifier": "Clerk does not recognise this address",
    "needs_new_password": "the password is expired or flagged and must be reset",
}


def _frontend_api() -> str:
    """Derive the Frontend API host from the publishable key.

    The key is `pk_<env>_<base64 of the host + '$'>`, so the host cannot drift
    from the key the apps ship — which is the point of reading it rather than
    writing it down. `eas.json` pins the same key in all three apps.
    """
    key = (os.getenv("FRONTEND_CLERK_API_KEY") or "").strip()
    if not key:
        raise SystemExit("FRONTEND_CLERK_API_KEY is not set in BackendAPI/.env")
    if not key.startswith("pk_test_"):
        raise SystemExit(
            "FRONTEND_CLERK_API_KEY is not a development key. These passwords "
            "are published; this script must never be pointed at production."
        )
    host = base64.b64decode(key.split("_", 2)[2] + "==").decode().rstrip("$")
    return f"https://{host}"


def _dev_browser(client: httpx.Client) -> str:
    """A fresh dev-browser token.

    A development instance authenticates the *caller* as well as the user: every
    Frontend API call carries a dev-browser JWT, and without one Clerk answers

        Unable to authenticate this browser for your development instance.

    One per identity, deliberately. A sign-in attempt is stored against the
    client that made it, so reusing a browser carries the previous identity's
    half-finished attempt into the next check and reports the wrong status for
    every identity after the first.
    """
    response = client.post("/v1/dev_browser", params={"_clerk_js_version": CLERK_JS})
    response.raise_for_status()
    return response.json()["token"]


def _attempt(client: httpx.Client, email: str) -> tuple[str, str]:
    """`(status, detail)` for one sign-in, without keeping the session."""
    try:
        token = _dev_browser(client)
        response = client.post(
            "/v1/client/sign_ins",
            params={"_clerk_js_version": CLERK_JS, "__clerk_db_jwt": token},
            headers={"Authorization": f"Bearer {token}"},
            data={"identifier": email, "password": PASSWORD, "strategy": "password"},
        )
    except httpx.HTTPError as exc:
        return "unreachable", f"{type(exc).__name__}: {exc}"

    body = response.json()
    if body.get("errors"):
        first = body["errors"][0]
        return "error", first.get("long_message") or first.get("message") or str(first)

    payload = body.get("response") or body
    status = payload.get("status") or "unknown"
    second = [f.get("strategy") for f in (payload.get("supported_second_factors") or [])]
    detail = EXPLAIN.get(status, "unrecognised status")
    if second:
        detail += f"  [second factors offered: {', '.join(second)}]"
    return status, detail


def main() -> int:
    base = _frontend_api()
    print(f"Clerk frontend API: {base}")
    print(f"Password          : {PASSWORD}\n")

    failures = 0
    with httpx.Client(base_url=base, timeout=30.0) as client:
        for label, slugs in (("apps", APP_IDENTITIES), ("console", CONSOLE_IDENTITIES)):
            print(f"── {label} ──")
            for slug in slugs:
                email = f"{slug}{SUBADDRESS}@{DOMAIN}"
                # Clerk rate-limits sign-in attempts per instance, and ten in a
                # row trips it — which then reports "Too many requests" for
                # every identity after the third and looks like a credential
                # problem. Ten checks are worth fifteen seconds.
                if slug != slugs[0] or label != "apps":
                    time.sleep(PACE_SECONDS)
                status, detail = _attempt(client, email)
                mark = "ok  " if status == "complete" else "FAIL"
                if status != "complete":
                    failures += 1
                print(f"  {mark} {email:<44} {status}")
                if status != "complete":
                    print(f"       {detail}")
            print()

    if failures:
        print(f"{failures} identity/identities cannot sign in.")
        return 1
    print("All identities sign in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
