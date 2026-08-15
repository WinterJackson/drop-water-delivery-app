"""
An invitation is claimed by proving you hold the mailbox it was sent to.

Staff access and administrator access are both granted by **email address**,
because that is the only thing the person issuing the grant knows. The address
becomes a grant when somebody signs in and Clerk is asked what their address is.
That lookup is therefore an authorisation decision.

Clerk lets a user attach an arbitrary secondary address to their own account,
and it stays `unverified` until they enter a code sent to it. Two copies of the
lookup existed — one per invite path — and **neither checked verification**.
Both walked `email_addresses`, preferred `primary_email_address_id`, and fell
back to `addresses[0]` on an unordered list. So an unverified address the
attacker typed could be returned and matched.

The vendor copy handed over a store. The admin copy handed over the console,
which reads every customer's record, every rider's national ID, and the money —
and the admin API shares a Clerk instance with the three consumer apps, so every
customer of the platform holds a structurally valid token to try it with.
"""
import ast
import pathlib

import pytest

from utils.clerk_identity import _pick, verified_email_for

BACKEND = pathlib.Path(__file__).resolve().parent.parent


class _Address:
    def __init__(self, id, email, status):
        self.id = id
        self.email_address = email
        self.verification = type("V", (), {"status": status})()


class _User:
    def __init__(self, addresses, primary_id=None):
        self.email_addresses = addresses
        self.primary_email_address_id = primary_id


VERIFIED = "verified"
UNVERIFIED = "unverified"


# ── What counts as this caller's address ──────────────────────────────────


def test_a_verified_primary_is_used():
    user = _User([_Address("a", "ops@drop.co.ke", VERIFIED)], primary_id="a")
    assert _pick(user) == "ops@drop.co.ke"


def test_an_unverified_address_is_never_returned():
    """The attack: attach the invited address to your own account, don't verify
    it, sign in, collect the grant."""
    user = _User([_Address("a", "ops@drop.co.ke", UNVERIFIED)], primary_id="a")
    assert _pick(user) is None


def test_an_unverified_address_is_not_reachable_through_the_fallback():
    """The specific defect. `primary_email_address_id` names an address that is
    absent from the list, so the old code returned `addresses[0]` — which is
    the attacker's unverified one."""
    user = _User(
        [
            _Address("attacker", "ops@drop.co.ke", UNVERIFIED),
            _Address("real", "someone@example.com", VERIFIED),
        ],
        primary_id="missing",
    )
    assert _pick(user) == "someone@example.com"


def test_a_verified_address_is_still_found_when_primary_is_unset():
    """A real account with no primary set must still be able to accept an
    invitation — the fix is narrowing, not a lockout."""
    user = _User([_Address("a", "ops@drop.co.ke", VERIFIED)], primary_id=None)
    assert _pick(user) == "ops@drop.co.ke"


def test_an_unreadable_verification_shape_fails_closed():
    """A Clerk SDK change must not silently start accepting everything."""
    class Odd:
        id = "a"
        email_address = "ops@drop.co.ke"
        verification = None

    assert _pick(_User([Odd()], primary_id="a")) is None


def test_a_dict_shaped_verification_is_understood():
    class DictShaped:
        id = "a"
        email_address = "ops@drop.co.ke"
        verification = {"status": "verified"}

    assert _pick(_User([DictShaped()], primary_id="a")) == "ops@drop.co.ke"


def test_no_addresses_at_all_binds_nothing():
    assert _pick(_User([], primary_id=None)) is None


@pytest.mark.asyncio
async def test_an_unconfigured_clerk_returns_none_rather_than_raising(monkeypatch):
    """Every caller is on a sign-in path: a failure must leave the invitation
    pending, not turn somebody's sign-in into a 500."""
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    assert await verified_email_for("user_1") is None


# ── One implementation, structurally ──────────────────────────────────────


def test_neither_invite_path_reads_clerk_addresses_itself():
    """Two copies of one rule, drifting, with the permissive one in the path
    that matters, is the shape this codebase refuses everywhere else."""
    offenders = []
    for module in ("services/admin_service.py", "services/vendor_staff_service.py"):
        source = (BACKEND / module).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(source, node) or ""
            # Comments and docstrings describe the defect by name, so match on
            # attribute access rather than on text.
            reads_addresses = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "getattr"
                and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)
                and n.args[1].value in ("email_addresses", "primary_email_address_id")
                for n in ast.walk(node)
            )
            if reads_addresses:
                offenders.append(f"{module}:{node.name}")

    assert offenders == [], (
        "these resolve a caller's email address themselves instead of calling "
        f"`utils.clerk_identity.verified_email_for`: {offenders}"
    )


def test_both_invite_paths_call_the_shared_lookup():
    """Guards the test above from passing because the call was simply deleted."""
    for module, function in (
        ("services/admin_service.py", "bind_admin_for_caller"),
        ("services/vendor_staff_service.py", "bind_invitations_for_caller"),
    ):
        source = (BACKEND / module).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == function:
                assert "verified_email_for" in (ast.get_source_segment(source, node) or ""), (
                    f"{module}:{function} must resolve the caller through the shared lookup"
                )
                break
        else:
            pytest.fail(f"{function} not found in {module}")


def test_an_already_bound_grant_is_never_rebound():
    """Even with a verified address: the email matching an administrator whose
    grant another Clerk account already holds is a takeover, not a bind."""
    source = (BACKEND / "services" / "admin_service.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "bind_admin":
            body = ast.get_source_segment(source, node) or ""
            assert "admin.clerk_id != clerk_id" in body
            return
    pytest.fail("bind_admin not found")
