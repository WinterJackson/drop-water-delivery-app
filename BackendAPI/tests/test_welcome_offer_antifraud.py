"""
The welcome offer is platform margin, so it needs a real gate.

`Users.device_id` was created `unique=True` with the comment
"Anti-fraud: one offer per device", and a repository-wide search found **no code
that read or wrote it**. The offer was therefore gated on `has_used_welcome_offer`
alone — a per-account flag — while the discount is 30% of a KSH 300 deposit taken
entirely out of platform margin (`platform_total` goes negative on a first
order). It could be farmed indefinitely with fresh sign-ups from one handset.

Two changes: the column is now written at registration and read when pricing, and
its `unique=True` index became a plain one. Uniqueness was the wrong constraint —
it stops two people in a household from both holding accounts, while doing
nothing about the thing it was named for.
"""
import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.pricing_service import welcome_offer_available


def _customer(*, used=False, device="device-a", user_id="customer-1"):
    return SimpleNamespace(
        id=user_id, has_used_welcome_offer=used, device_id=device
    )


def _session(other_account_on_device=None):
    """A session whose device lookup finds this account id, or nothing."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = other_account_on_device
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_a_fresh_customer_on_a_fresh_device_gets_the_offer():
    assert await welcome_offer_available(_session(), _customer()) is True


@pytest.mark.asyncio
async def test_an_account_that_has_used_it_does_not_get_it_again():
    assert await welcome_offer_available(_session(), _customer(used=True)) is False


@pytest.mark.asyncio
async def test_a_second_account_on_the_same_handset_is_refused():
    """The defect this closes.

    A new account, flag unset, would previously have been given the discount.
    """
    session = _session(other_account_on_device="customer-0")
    assert await welcome_offer_available(session, _customer()) is False


@pytest.mark.asyncio
async def test_an_account_with_no_device_id_is_not_punished_for_it():
    """Older accounts predate the field.

    Refusing them a first order would be a worse error than the one being
    closed — the platform would be denying a genuine customer their offer on the
    strength of a column that did not exist when they registered.
    """
    assert await welcome_offer_available(_session(), _customer(device=None)) is True


@pytest.mark.asyncio
async def test_a_customer_is_not_blocked_by_their_own_earlier_row():
    """The lookup excludes the caller.

    Matching on the device alone would have every customer block themselves the
    moment their own flag was set, which reads as the offer simply not working.
    """
    session = _session(other_account_on_device=None)
    assert await welcome_offer_available(session, _customer()) is True

    # The query must exclude this user's own id. Asserted structurally, because a
    # behavioural test with a stubbed session cannot see the WHERE clause.
    source = pathlib.Path("services/pricing_service.py").read_text()
    function = source[source.index("async def welcome_offer_available"):]
    function = function[: function.index("\ndef ")]
    assert "_User.id != user.id" in function


@pytest.mark.asyncio
async def test_no_user_means_no_offer():
    """An anonymous quote is not a first order — there is no account to consume."""
    assert await welcome_offer_available(_session(), None) is False


# ── The column has to be written, or the check reads nothing ──────────────


def test_registration_records_the_device():
    """A check against a column nothing populates is the previous state of this
    feature, dressed up as a fix."""
    tree = ast.parse(pathlib.Path("services/auth_service.py").read_text())
    create = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "createUser"
    )
    assigned = {kw.arg for call in ast.walk(create) if isinstance(call, ast.Call) for kw in call.keywords}
    assert "device_id" in assigned, "createUser does not record the device id"


def test_the_device_id_is_never_updated_after_registration():
    """A client that could rewrite it could reset the check by sending a new value.

    Written once, at creation, and nowhere else — the same reasoning that keeps
    `clerk_id` out of request bodies.
    """
    offenders = []
    for path in pathlib.Path("services").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "device_id"
                    and isinstance(target.ctx, ast.Store)
                ):
                    offenders.append(f"{path}:{node.lineno}")

    assert not offenders, (
        f"device_id is assigned after registration at {offenders}. "
        "It is set once, in `createUser`; a client able to change it can reset "
        "the one-offer-per-device check simply by sending a new value."
    )


def test_pricing_reads_the_device_check_rather_than_the_flag_alone():
    """`compute_order_quote` must go through `welcome_offer_available`.

    The line it replaced was
    `is_first_order = user and not user.has_used_welcome_offer`, which is the
    per-account gate this test exists to prevent coming back.
    """
    source = pathlib.Path("services/pricing_service.py").read_text()
    quote = source[source.index("async def compute_order_quote"):]

    assert "welcome_offer_available(session, user)" in quote
    assert "not bool(getattr(user, \"has_used_welcome_offer\"" not in quote, (
        "compute_order_quote is reading the account flag directly again — that is "
        "the per-account gate, with no device check."
    )


def test_the_migration_drops_the_unique_constraint():
    """`unique=True` was the wrong constraint and blocked a legitimate case.

    It prevented two people sharing a handset from both holding accounts, while
    doing nothing about repeat offers — the thing it was named for.
    """
    migration = pathlib.Path(
        "alembic/versions/b8e3d1a5c704_deposit_debt_and_money_precision.py"
    ).read_text()
    upgrade = migration[migration.index("def upgrade"): migration.index("def downgrade")]

    assert "ix_Users_device_id" in upgrade
    assert "unique=False" in upgrade
