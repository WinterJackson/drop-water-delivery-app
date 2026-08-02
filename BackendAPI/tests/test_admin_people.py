"""Managing customers, riders and vendors from the console.

The masking tests exist because the first implementation did not mask anything.
`mask(email, keep=0)` was meant to hide the whole value; `value[-0:]` in Python
is the *entire string*, so every list response carried full email addresses
behind a decorative `••••` prefix. It read correctly, reviewed correctly, and
leaked the column it was written to protect.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from services.admin_people_service import (
    MODELS,
    global_search,
    mask,
    mask_email,
    money,
    set_suspended,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ── Masking ───────────────────────────────────────────────────────────────


def test_keep_zero_hides_everything():
    """`value[-0:]` is the whole string, not the empty one.

    This is the actual defect: the guard `len(value) > keep` passed, the slice
    returned everything, and the result looked masked.
    """
    assert mask("deannelson@example.org", keep=0) == "••••"
    assert mask("0712345678", keep=0) == "••••"


def test_a_negative_keep_cannot_widen_the_window():
    assert mask("0712345678", keep=-3) == "••••"


def test_masking_keeps_only_the_requested_tail():
    assert mask("0712345678", keep=3) == "••••678"
    assert mask("0712345678", keep=4) == "••••5678"


def test_a_short_value_is_not_padded_into_a_hint():
    """Never return more characters than the input had."""
    assert mask("12", keep=4) == "••••12"


def test_email_masking_keeps_the_domain_and_hides_the_person():
    """The domain distinguishes a staff account from a customer at a glance;
    the local part is the half that identifies somebody."""
    assert mask_email("deannelson@example.org") == "d••••@example.org"
    assert mask_email("a@b.com") == "a••••@b.com"


def test_a_malformed_email_is_hidden_entirely():
    """Anything without an `@` is not an address we can partly reveal safely."""
    assert mask_email("garbage") == "••••"
    assert mask_email("") is None
    assert mask_email(None) is None


def test_no_list_response_returns_an_unmasked_contact_column():
    """Structural: `summarise` is what every list row goes through.

    A future field added there must go through `mask`/`mask_email`, because the
    list is rendered for roles that deliberately lack `pii.view`.
    """
    source = (BACKEND / "services" / "admin_people_service.py").read_text()
    tree = ast.parse(source)
    summarise = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "summarise"
    )

    raw = []
    for node in ast.walk(summarise):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in {"email", "phone_number", "ID_number"}:
            continue
        raw.append(node.attr)

    # Each occurrence must be an argument to a masking call, never returned bare.
    masked_args = {
        sub.attr
        for call in ast.walk(summarise)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in {"mask", "mask_email"}
        for sub in ast.walk(call)
        if isinstance(sub, ast.Attribute)
    }
    assert set(raw) <= masked_args, (
        f"these contact columns appear in summarise() outside a mask call: "
        f"{set(raw) - masked_args}"
    )


# ── Money ─────────────────────────────────────────────────────────────────


def test_money_is_a_decimal_string_not_a_float():
    assert money("0.1") == "0.10"
    assert money(None) == "0.00"
    assert money("38889.594") == "38889.59"


# ── Suspension ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suspending_a_vendor_clears_the_flag_discovery_reads():
    """`is_active` is what `vendor_service.discoverable_vendor()` filters on.

    Recording a suspension without clearing it would leave the store in customer
    search — a button that reports success and changes nothing a customer sees.
    """
    from models.vendor_model import Vendor

    vendor = Vendor(business_name="Test", is_active=True)
    session = AsyncMock()
    session.get = AsyncMock(return_value=vendor)

    row, before, after = await set_suspended(
        session, kind="vendor", person_id="v1", suspend=True,
        reason="Health complaint", admin_id=None,
    )

    assert row.is_active is False
    assert row.suspended_at is not None
    assert row.suspension_reason == "Health complaint"
    assert before["is_active"] is True and after["is_active"] is False


@pytest.mark.asyncio
async def test_suspending_a_rider_also_takes_them_off_dispatch():
    """Otherwise they keep receiving offers until their shift ends."""
    from models.deliverer_model import Deliverer

    rider = Deliverer(name="Test", is_active=True, is_available=True)
    session = AsyncMock()
    session.get = AsyncMock(return_value=rider)

    await set_suspended(
        session, kind="rider", person_id="r1", suspend=True,
        reason="Under investigation", admin_id=None,
    )

    assert rider.is_available is False
    assert rider.is_active is False


@pytest.mark.asyncio
async def test_reinstating_clears_the_reason():
    """A stale reason on an active account reads as a current sanction."""
    from models.vendor_model import Vendor

    vendor = Vendor(business_name="Test", is_active=False)
    vendor.suspended_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    vendor.suspension_reason = "Old reason"

    session = AsyncMock()
    session.get = AsyncMock(return_value=vendor)

    await set_suspended(
        session, kind="vendor", person_id="v1", suspend=False,
        reason="Resolved", admin_id=None,
    )

    assert vendor.suspended_at is None
    assert vendor.suspension_reason is None
    assert vendor.is_active is True


@pytest.mark.asyncio
async def test_suspending_an_already_suspended_account_is_refused():
    """Not idempotent on purpose: a second suspension would overwrite the
    original reason and timestamp, losing why it happened."""
    from models.vendor_model import Vendor

    vendor = Vendor(business_name="Test", is_active=False)
    vendor.suspended_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=vendor)

    with pytest.raises(HTTPException) as exc:
        await set_suspended(
            session, kind="vendor", person_id="v1", suspend=True,
            reason="Again", admin_id=None,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_missing_account_is_a_404_not_a_crash():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await set_suspended(
            session, kind="customer", person_id="nope", suspend=True,
            reason="x", admin_id=None,
        )
    assert exc.value.status_code == 404


def test_suspension_is_not_committed_by_the_service():
    """The route owns the transaction, so the change and its audit row land
    together or not at all."""
    source = (BACKEND / "services" / "admin_people_service.py").read_text()
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "set_suspended"
    )
    commits = [
        n for n in ast.walk(func)
        if isinstance(n, ast.Attribute) and n.attr == "commit"
    ]
    assert commits == []


# ── Search ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_returns_nothing_for_a_kind_the_caller_cannot_read():
    """Search must not become a way around the permission guarding the detail
    page — otherwise a support account without `customers.read` can still
    enumerate the customer table by typing partial phone numbers.
    """
    session = AsyncMock()
    result = await global_search(session, term="0712", permissions=set())
    assert result["results"] == []
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_one_character_search_does_not_scan_every_table():
    """`%a%` against three tables on every keystroke is a denial of service
    against your own database."""
    session = AsyncMock()
    result = await global_search(session, term="a", permissions={"customers.read"})
    assert result["results"] == []
    session.execute.assert_not_awaited()


def test_every_account_type_is_covered():
    assert set(MODELS) == {"customer", "rider", "vendor"}
