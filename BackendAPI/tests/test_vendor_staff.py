"""
Staff is a relationship with a capability set, not a nullable column.

`Vendor.staff_clerk_id` held exactly one id and carried a UNIQUE constraint, so a
store could have one staff member, adding a second silently replaced the first
(behind a screen called "Manage Staff"), and one person could work for exactly
one store on the whole platform. Access was also all-or-nothing:
`get_current_vendor` admitted staff to every route that was not owner-only, so
handing someone the till handed them the catalogue, the bottle ledger and the
wallet balance.

The end-to-end behaviour is covered against a real database in
`test_multi_store_integration.py`. This file covers the parts that are pure logic
and the parts that are structural.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from models.vendor_staff_model import (
    ALL_PERMISSIONS,
    DEFAULT_PERMISSIONS,
    PERMISSION_LABELS,
    VendorStaff,
    normalise_permissions,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ── The capability set ────────────────────────────────────────────────────


def test_unknown_permissions_are_discarded():
    """A permission removed from the code must stop granting anything.

    Storing whatever the client sent would mean a capability deleted from this
    version keeps working for anyone whose row still lists it.
    """
    assert normalise_permissions(["manage_orders", "become_owner", ""]) == ["manage_orders"]


def test_permissions_are_stored_in_a_stable_order():
    """So two equivalent rows compare equal and a diff is meaningful."""
    a = normalise_permissions(["view_finances", "manage_orders"])
    b = normalise_permissions(["manage_orders", "view_finances"])
    assert a == b == ["manage_orders", "view_finances"]


def test_new_staff_do_not_get_the_wallet_by_default():
    """Running the shop is the point; seeing the money is a separate decision.

    The old model had no way to express the difference, so every staff member
    could read the store's balance.
    """
    assert "view_finances" not in DEFAULT_PERMISSIONS
    assert "manage_orders" in DEFAULT_PERMISSIONS


def test_every_permission_has_a_label():
    """The label is shown in the management UI and in the refusal message."""
    assert set(PERMISSION_LABELS) == set(ALL_PERMISSIONS)
    assert all(PERMISSION_LABELS[p] for p in ALL_PERMISSIONS)


def test_a_member_reports_only_what_it_holds():
    member = VendorStaff(permissions=["manage_orders"])
    assert member.has("manage_orders")
    assert not member.has("manage_products")


def test_revocation_is_a_soft_delete():
    """Who could act on a store, and when, is part of the audit trail behind
    every order and bottle movement they touched."""
    member = VendorStaff(permissions=list(DEFAULT_PERMISSIONS), is_active=True)
    member.revoke()
    assert member.revoked_at is not None
    assert member.is_active is False


# ── Invitations ───────────────────────────────────────────────────────────


def _session(existing=()):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(existing)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_an_unknown_email_is_recorded_as_a_pending_invitation(monkeypatch):
    """And the reply says nothing about whether the address has an account.

    The old endpoint answered 404 "Staff member not found. Please ask them to
    download the app and sign up first." for an unknown address and 200 for a
    known one, so any vendor could test whether an arbitrary email — a
    competitor's, a customer's — is registered on this platform.
    """
    from services import vendor_staff_service as svc

    monkeypatch.setattr(svc, "_lookup_clerk_id", AsyncMock(return_value=None))
    unknown = await svc.invite_staff(
        _session(), vendor_id="v1", owner_clerk_id="owner", email="nobody@example.com"
    )

    monkeypatch.setattr(svc, "_lookup_clerk_id", AsyncMock(return_value="user_known"))
    known = await svc.invite_staff(
        _session(), vendor_id="v1", owner_clerk_id="owner", email="somebody@example.com"
    )

    assert unknown["message"] == known["message"]
    assert unknown["staff"]["is_pending"] is True
    assert known["staff"]["is_pending"] is False


@pytest.mark.asyncio
async def test_re_inviting_someone_updates_their_row(monkeypatch):
    """Two grants for the same person would need revoking twice, and only one
    of them would be found."""
    from services import vendor_staff_service as svc

    monkeypatch.setattr(svc, "_lookup_clerk_id", AsyncMock(return_value="user_staff"))
    existing = VendorStaff(
        id="s1", vendor_id="v1", clerk_id="user_staff",
        email="assistant@example.com", permissions=["manage_orders"],
    )
    session = _session([existing])

    result = await svc.invite_staff(
        session,
        vendor_id="v1",
        owner_clerk_id="owner",
        email="assistant@example.com",
        permissions=["manage_orders", "view_finances"],
    )

    assert result["updated_existing"] is True
    assert existing.permissions == ["manage_orders", "view_finances"]
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_an_owner_cannot_add_themselves(monkeypatch):
    from services import vendor_staff_service as svc

    monkeypatch.setattr(svc, "_lookup_clerk_id", AsyncMock(return_value="owner"))
    with pytest.raises(HTTPException) as exc:
        await svc.invite_staff(
            _session(), vendor_id="v1", owner_clerk_id="owner", email="owner@example.com"
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_a_malformed_email_never_reaches_clerk(monkeypatch):
    """Validation first: otherwise every typo is an outbound API call."""
    from services import vendor_staff_service as svc

    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(svc, "_lookup_clerk_id", lookup)
    with pytest.raises(HTTPException) as exc:
        await svc.invite_staff(
            _session(), vendor_id="v1", owner_clerk_id="owner", email="not-an-email"
        )
    assert exc.value.status_code == 400
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_roster_is_bounded(monkeypatch):
    """A shop floor is not unbounded, and an unbounded list invites scripting."""
    from services import vendor_staff_service as svc

    crowd = [
        VendorStaff(id=f"s{i}", vendor_id="v1", clerk_id=f"c{i}", email=f"{i}@x.com", permissions=[])
        for i in range(svc.MAX_STAFF_PER_STORE)
    ]
    monkeypatch.setattr(svc, "_lookup_clerk_id", AsyncMock(return_value="user_new"))
    with pytest.raises(HTTPException) as exc:
        await svc.invite_staff(
            _session(crowd), vendor_id="v1", owner_clerk_id="owner", email="one.more@example.com"
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_revoking_clears_the_push_token():
    """The device must stop receiving this store's orders the moment access ends."""
    from services import vendor_staff_service as svc

    member = VendorStaff(
        id="s1", vendor_id="v1", clerk_id="c1", email="a@x.com",
        permissions=["manage_orders"], push_token="ExponentPushToken[abc]",
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = member
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    await svc.revoke_staff(session, vendor_id="v1", staff_id="s1")
    assert member.revoked_at is not None
    assert member.push_token is None


# ── Structural ────────────────────────────────────────────────────────────


def test_nothing_reads_the_single_staff_column_any_more():
    """`staff_clerk_id` and `staff_push_token` are the predecessors.

    They are left on the table so an application rollback does not lose
    anybody's access — expand/contract — but reading either brings back the
    one-staff-per-store limit, and a second reader would drift from this one.
    """
    import io
    import tokenize

    def _code_only(path: pathlib.Path) -> list[tuple[int, str]]:
        """Real tokens only.

        Prose describing the predecessor is not a read of it, and these files
        explain it at length — so comments and strings (docstrings included, in
        all their continuation lines) are tokenized away rather than guessed at
        from line prefixes.
        """
        source = path.read_text(errors="ignore")
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
            return []
        return [
            (tok.start[0], tok.string)
            for tok in tokens
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]

    offenders = []
    for directory in ("routes", "services", "dependencies", "jobs", "utils"):
        root = BACKEND / directory
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            for lineno, text in _code_only(path):
                if text in ("staff_clerk_id", "staff_push_token"):
                    offenders.append(f"{directory}/{path.name}:{lineno}: {text}")
    assert offenders == [], (
        "use the Vendor_Staff membership table — these bring back the "
        f"one-staff-per-store limit: {offenders}"
    )


def test_the_membership_predicate_lives_in_one_place():
    """`clerk_id == … OR staff_clerk_id == …` was written out in a dozen files.

    Every copy was an opportunity to write a subtly different one; the join
    replacing it must not be copied around the same way.
    """
    source = (BACKEND / "services" / "vendor_staff_service.py").read_text()
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    assert {"is_store_member", "staffed_vendor_ids", "revoke_all_for_store"} <= names


def test_deleting_a_store_ends_every_grant_on_it():
    """Otherwise a staff member keeps a live grant to an anonymised store: the
    resolver matches their membership row and never looks at
    `verification_status`."""
    source = (BACKEND / "routes" / "auth_routes.py").read_text()
    assert "revoke_all_for_store" in source


def test_push_tokens_reach_every_staff_member_of_a_store():
    """`Vendor.staff_push_token` was one column on the *store*, so it addressed
    whoever registered last and could not reach the others."""
    source = (BACKEND / "services" / "vendor_staff_service.py").read_text()
    assert "async def push_tokens_for_store" in source
    assert "async def set_push_token" in source
