"""Refund and payout reconciliation.

`payouts` and `WalletTransactions` are empty on this deployment, so the two
structural properties are pinned here rather than against volume:

  1. the settlement screen must never offer to re-send a refund, and
  2. the encrypted payout destination must never leave the backend.

Both are the kind of thing that is obviously right when written and quietly
wrong three changes later.
"""
import ast
import pathlib
import re

import pytest

from services import admin_settlement_service as svc

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ADMIN = BACKEND.parent / "drop-admin"


def _source(base: pathlib.Path, relative: str) -> str:
    return (base / relative).read_text()


# ── no retry ──────────────────────────────────────────────────────────────


def test_the_settlement_routes_never_initiate_a_reversal():
    """A reversal that succeeded and lost its callback is indistinguishable from
    one that failed. Retrying pays the customer twice out of the platform's own
    float, with no way to claw it back — so the console records a settlement made
    elsewhere and sends nothing."""
    source = _source(BACKEND, "routes/admin_finance_routes.py")
    tree = ast.parse(source)

    forbidden = ("initiate_mpesa_reversal", "process_single_refund", "process_all_pending_refunds")

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if "settle" not in node.name and "settlement" not in node.name:
            continue
        body = ast.get_source_segment(source, node) or ""
        for name in forbidden:
            assert name not in body, (
                f"{node.name} calls {name}. The settlement screen records a refund "
                f"made by hand; it must never send one."
            )


def _without_comments(source: str) -> str:
    """Strip block and line comments.

    Both files *explain* why there is no retry, so a naive substring search
    matches the explanation and fails on correct code — the same trap that made
    an earlier regex test flag its own docstring.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def test_the_settlement_page_does_not_offer_a_retry():
    page = _without_comments(_source(ADMIN, "app/(dashboard)/finance/settlement/page.tsx"))
    button = _without_comments(
        _source(ADMIN, "app/(dashboard)/finance/settlement/SettleButton.tsx")
    )
    assert "Retry" not in button and "Retry" not in page, (
        "labelling this 'Retry' would make it the most dangerous control in the "
        "console — see the route docstring"
    )
    assert "Mark settled" in button


# ── the encrypted destination stays server-side ───────────────────────────


def test_the_payout_destination_is_never_serialised():
    """`Payout.account_details` is the recipient's phone number, encrypted at
    rest. This screen is readable by anyone with finance.read."""
    source = _source(BACKEND, "services/admin_settlement_service.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_row":
            body = ast.get_source_segment(source, node) or ""
            assert "account_details" not in body, (
                "the encrypted destination must never reach the console payload"
            )
            assert '"has_receipt"' in body, "presence of a receipt is what the screen needs"
            return
    pytest.fail("_row serialiser not found")


# ── the arithmetic ────────────────────────────────────────────────────────


def test_refund_outstanding_excludes_the_settled_state():
    """`refunded` is money that went back. Counting it as outstanding would put
    the platform's largest number on a screen about what it still owes."""
    assert "refunded" in svc.REFUND_STATES
    assert "refunded" not in svc.REFUND_OUTSTANDING
    assert set(svc.REFUND_OUTSTANDING) < set(svc.REFUND_STATES)


def test_the_stuck_threshold_is_generous_enough_not_to_cry_wolf():
    """A false 'stuck' sends somebody chasing a payment that is about to land.
    Safaricom settles B2C in minutes; anything under an hour would flag normal
    latency as a fault."""
    assert svc.STUCK_AFTER_HOURS >= 1


def test_hours_since_handles_a_naive_timestamp():
    """Some rows carry `updated_at` without a timezone. Subtracting an aware
    datetime from a naive one raises, and it would raise inside the one screen
    somebody opens when money has gone missing."""
    from datetime import datetime, timedelta, timezone

    naive = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)
    aware = datetime.now(timezone.utc) - timedelta(hours=3)

    assert svc._hours_since(naive) == pytest.approx(3.0, abs=0.2)
    assert svc._hours_since(aware) == pytest.approx(3.0, abs=0.2)
    assert svc._hours_since(None) is None


def test_money_is_formatted_from_the_decimal_never_a_float():
    assert svc._money(None) == "0.00"
    assert svc._money("1234.5") == "1234.50"
    assert svc._money(0) == "0.00"
