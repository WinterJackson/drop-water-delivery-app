"""Who may pay cash, who may carry it, and how much.

Cash is the only place on this platform where money exists outside a ledger.
Between the customer handing over notes and the rider's wallet settling at
delivery, the platform's claim is a promise from somebody on a motorbike.

The float check asked one question — *can this rider cover it* — and it was the
only question anyone asked. Nothing asked whether they should be trusted with it
at all, nothing limited how many they could carry at once, and nothing asked
anything whatsoever about the customer. A four-day-old account with a large
balance passed every time, for any number of orders.

What is tested here is that each gate exists, bites on its own, and says
something the person refused can act on.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from models.deliverer_model import KYCStatus
from services import cod_policy
from services import platform_config_service as config

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings — any "must not appear" assertion needs it,
    because the note explaining a rule has to name the thing it forbids."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _rider(**over):
    base = dict(
        id=uuid4(),
        kyc_status=KYCStatus.approved,
        suspended_at=None,
        is_active=True,
        rating=4.8,
        is_platinum=False,
        created_at=datetime.now(timezone.utc) - timedelta(days=90),
    )
    base.update(over)
    return SimpleNamespace(**base)


def _session(*, delivered=100, abandoned=0, scalar=None):
    """A session whose counts are whatever the test needs.

    `assess_rider` issues two counts (delivered, abandoned) in order; anything
    afterwards takes `scalar`.
    """
    answers = [delivered, abandoned]
    if scalar is not None:
        answers.extend(scalar if isinstance(scalar, list) else [scalar])

    session = AsyncMock()
    calls = {"n": 0}

    def _execute(*args, **kwargs):
        result = MagicMock()
        index = calls["n"]
        calls["n"] += 1
        result.scalar.return_value = answers[index] if index < len(answers) else 0
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


# ── The six trust factors, each on its own ────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,rider,phrase",
    [
        ("unverified", _rider(kyc_status=KYCStatus.pending), "not verified"),
        ("rejected", _rider(kyc_status=KYCStatus.rejected), "not verified"),
        ("suspended", _rider(suspended_at=datetime.now(timezone.utc)), "suspended"),
        ("deactivated", _rider(is_active=False), "suspended"),
        ("too new", _rider(created_at=datetime.now(timezone.utc) - timedelta(days=2)), "days"),
        ("poorly rated", _rider(rating=3.0), "rating"),
    ],
)
async def test_each_trust_factor_blocks_cash_on_its_own(label, rider, phrase):
    """Six independent reasons, and any one of them is enough."""
    assessment = await cod_policy.assess_rider(_session(), rider)

    assert not assessment.eligible, f"a {label} rider was cleared to carry cash"
    assert assessment.tier == "blocked"
    assert assessment.max_order_value == Decimal("0.00")
    assert any(phrase in reason.lower() for reason in assessment.reasons), (
        f"nothing in {assessment.reasons} tells a {label} rider what is wrong"
    )


@pytest.mark.asyncio
async def test_the_delivery_count_gate_states_the_gap():
    """A refusal a rider cannot act on is a support ticket. "You need 25, you
    have 11" is a thing somebody can go and do."""
    assessment = await cod_policy.assess_rider(_session(delivered=11), _rider())

    assert not assessment.eligible
    assert "25" in " ".join(assessment.reasons)
    assert "11" in " ".join(assessment.reasons)


@pytest.mark.asyncio
async def test_a_vendor_cancellation_does_not_count_against_the_rider():
    """The completion gate must not punish the riders working with the least
    reliable stores. A rider who loses an order because the store ran out of
    water has done nothing wrong."""
    source = _code_only(BACKEND / "services" / "cod_policy.py")
    body = source.split("async def _delivery_history")[1].split("async def ")[0]

    assert "cancelled_by_vendor%" in body
    assert "cancelled_by_customer%" in body


@pytest.mark.asyncio
async def test_a_rider_with_no_history_fails_the_count_and_not_the_rate():
    """An empty denominator is treated as perfect, not as zero. Otherwise a new
    rider fails two gates for one reason and the messages contradict each
    other — "you need 25 deliveries" beside "your completion rate is 0%"."""
    assessment = await cod_policy.assess_rider(_session(delivered=0, abandoned=0), _rider())

    assert assessment.completion_rate == 1.0
    assert not any("completion" in reason.lower() for reason in assessment.reasons)


@pytest.mark.asyncio
async def test_an_eligible_rider_gets_a_tier_and_a_ceiling():
    with config.temporarily({**config.effective(), "cod_min_rider_deliveries": 5}):
        standard = await cod_policy.assess_rider(_session(delivered=50), _rider())
        platinum = await cod_policy.assess_rider(
            _session(delivered=50), _rider(is_platinum=True)
        )

    assert standard.eligible and standard.tier == "standard"
    assert platinum.eligible and platinum.tier == "platinum"
    assert platinum.max_order_value > standard.max_order_value


# ── The ceilings, and why checkout uses the higher one ────────────────────


def test_checkout_caps_against_the_platinum_ceiling_not_the_standard_one():
    """Capping checkout at the standard figure would be tidier and wrong: no
    order above it could ever exist, so `cod_max_order_value_platinum` could
    never bind. A setting that cannot bind is decorative, and somebody will
    spend an afternoon working that out."""
    source = _code_only(BACKEND / "services" / "cod_policy.py")
    body = source.split("async def assert_customer_may_pay_cash")[1].split("async def ")[0]

    assert "cod_max_order_value_platinum" in body
    assert "cod_max_order_value_standard" not in body


def test_the_platinum_ceiling_is_above_the_standard_one():
    assert (
        config.DEFAULTS["cod_max_order_value_platinum"]
        > config.DEFAULTS["cod_max_order_value_standard"]
    )


@pytest.mark.asyncio
async def test_an_order_over_the_riders_own_ceiling_is_refused_by_name():
    order = SimpleNamespace(total_amount=Decimal("5000"))

    with config.temporarily({
        **config.effective(),
        "cod_min_rider_deliveries": 0,
        "cod_max_order_value_standard": 2000.0,
    }):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_rider_may_accept_cash(
                _session(delivered=50), rider=_rider(), order=order
            )

    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "cod_value_ceiling"
    # And it points at the way up rather than just refusing.
    assert "Platinum" in exc.value.detail["message"]


# ── The limits on exposure already carried ────────────────────────────────


@pytest.mark.asyncio
async def test_a_rider_at_the_concurrent_cap_is_refused():
    """A rider with a large balance could carry six customers' water at once.
    The float check permits it — one balance can back several small orders."""
    order = SimpleNamespace(total_amount=Decimal("500"))

    with config.temporarily({
        **config.effective(),
        "cod_min_rider_deliveries": 0,
        "cod_max_concurrent_orders": 2,
    }):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_rider_may_accept_cash(
                # delivered, abandoned, then open_cash_orders = 2
                _session(delivered=50, abandoned=0, scalar=[2]),
                rider=_rider(), order=order,
            )

    assert exc.value.status_code == 409
    assert "limit" in exc.value.detail.lower()
    # 409, not 403: this one gets better by delivering, and the message says so.
    assert "deliver" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_the_daily_ceiling_counts_what_is_already_taken():
    order = SimpleNamespace(total_amount=Decimal("3000"))

    with config.temporarily({
        **config.effective(),
        "cod_min_rider_deliveries": 0,
        "cod_max_concurrent_orders": 10,
        # Above the order value, so the ceiling gate cannot fire first and mask
        # the one being tested.
        "cod_max_order_value_standard": 5000.0,
        "cod_max_daily_exposure": 15000.0,
    }):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_rider_may_accept_cash(
                # delivered, abandoned, concurrent, then taken_today
                _session(delivered=50, abandoned=0, scalar=[0, Decimal("14000")]),
                rider=_rider(), order=order,
            )

    assert exc.value.status_code == 409
    assert "15,000" in exc.value.detail
    # M-Pesa is unaffected, and the rider is told so — otherwise this reads as
    # "you are done for the day".
    assert "M-Pesa" in exc.value.detail


# ── The customer's side ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cash_is_not_offered_on_a_first_order():
    """A fake address plus cash costs the rider a wasted trip and the vendor a
    prepared order, and it is free to attempt. Accounts are free."""
    with config.temporarily({**config.effective(), "cod_min_customer_completed_orders": 1}):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_customer_may_pay_cash(
                _session(delivered=0, abandoned=0, scalar=[0]),
                user=SimpleNamespace(id=uuid4()),
                total=Decimal("500"),
                distance_km=1.0,
            )

    assert exc.value.status_code == 400
    # Names the way out rather than leaving a dead end.
    assert "M-Pesa" in exc.value.detail


@pytest.mark.asyncio
async def test_cash_is_refused_beyond_the_cash_radius():
    """A long trip carrying somebody else's money is more exposure and more
    float committed for longer."""
    with config.temporarily({**config.effective(), "cod_max_distance_km": 2}):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_customer_may_pay_cash(
                _session(), user=SimpleNamespace(id=uuid4()),
                total=Decimal("500"), distance_km=9.0,
            )

    assert "2 km" in exc.value.detail


@pytest.mark.asyncio
async def test_the_console_can_switch_cash_off_entirely():
    with config.temporarily({**config.effective(), "cod_enabled": False}):
        with pytest.raises(HTTPException) as exc:
            await cod_policy.assert_customer_may_pay_cash(
                _session(), user=SimpleNamespace(id=uuid4()),
                total=Decimal("100"), distance_km=1.0,
            )

    assert "not available" in exc.value.detail


# ── Completion, and the sweep ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cash_delivery_needs_a_photo_and_an_mpesa_one_does_not():
    """On a cash order there is no M-Pesa receipt to point at, so the photo is
    the only thing that makes "he never delivered it" decidable."""
    session = _session()

    assert await cod_policy.photo_required(session, SimpleNamespace(payment_method="cash"))
    assert not await cod_policy.photo_required(session, SimpleNamespace(payment_method="mpesa"))

    with config.temporarily({**config.effective(), "cod_require_delivery_photo": False}):
        assert not await cod_policy.photo_required(
            session, SimpleNamespace(payment_method="cash")
        )


def test_the_photo_gate_runs_before_settlement():
    """Settlement is what the `delivered` transition triggers. Checking after it
    would mean the money had already moved on a delivery with no evidence."""
    source = _code_only(BACKEND / "services" / "deliverer_service.py")
    # The colon matters: the first `new_status == 'delivered'` in this file is
    # the state guard, not the branch. And `ast.unparse` normalises every string
    # to single quotes, so matching on double quotes finds nothing.
    body = source.split("if new_status == 'delivered':")[1].split("if order.delivery_type")[0]

    photo_at = body.find("photo_required")
    settle_at = body.find("apply_wallet_delta")
    assert photo_at != -1, "the cash photo gate is gone"
    assert settle_at == -1 or photo_at < settle_at, (
        "money moves before the cash delivery photo is checked"
    )


def test_a_released_cash_order_returns_to_the_pool_rather_than_being_cancelled():
    """The customer still wants their water and the stock is still committed to
    them. Cancelling would revert seven things that should not be reverted."""
    source = _code_only(BACKEND / "services" / "cod_policy.py")
    body = source.split("async def release_unclaimed_cash_orders")[1]

    assert "'unassigned'" in body or '"unassigned"' in body
    assert "revert_order_side_effects" not in body, (
        "the release sweep now cancels the order instead of re-offering it"
    )
    # And the rider is freed, or they stay flagged busy for an order they no
    # longer have.
    assert "is_available = True" in body


def test_the_sweep_claims_rows_the_way_every_other_sweep_does():
    """Several workers may run it, and one bad row must not discard the batch."""
    source = _code_only(BACKEND / "services" / "cod_policy.py")
    body = source.split("async def release_unclaimed_cash_orders")[1]

    assert "skip_locked=True" in body
    assert "session.rollback()" in body


# ── Reachability: a gate nothing calls is not a gate ───────────────────────


def test_every_cash_gate_is_actually_wired_in():
    """Each of these shipped as a function nothing called at least once on this
    platform. The enforcement is only real at the call site."""
    checkout = _code_only(BACKEND / "routes" / "cart_routes.py")
    acceptance = _code_only(BACKEND / "services" / "deliverer_service.py")
    worker = (BACKEND / "worker.py").read_text()
    cron = (BACKEND / "routes" / "cron_routes.py").read_text()

    assert "assert_customer_may_pay_cash" in checkout, "checkout does not gate cash"
    assert "assert_rider_may_accept_cash" in acceptance, "acceptance does not gate cash"
    assert "photo_required" in acceptance, "completion does not require a cash photo"
    assert "release_unclaimed_cash_orders" in worker, "the release sweep has no task"
    assert "release-unclaimed-cash" in cron, "the release sweep has no schedule"


def test_the_trust_check_runs_before_the_float_check():
    """"You need 25 deliveries" is a truer answer than "insufficient balance" to
    a rider who could never take this order at any balance."""
    source = _code_only(BACKEND / "services" / "deliverer_service.py")

    trust_at = source.find("assert_rider_may_accept_cash")
    float_at = source.find("committed_cash_float(session, deliverer.id)")
    assert trust_at != -1 and float_at != -1
    assert trust_at < float_at


def test_the_rider_can_see_why_cash_is_closed_to_them():
    """A rider was shown cash orders they could not accept, with the refusal
    arriving only after they tapped — and no way to tell a temporary limit from
    a permanent one."""
    routes = _code_only(BACKEND / "routes" / "deliverer_routes.py")
    assert "cash-eligibility" in routes

    rider_app = BACKEND.parent / "drop-rider-app"
    if not rider_app.exists():
        pytest.skip("drop-rider-app/ is not present")

    screen = (rider_app / "app" / "(screens)" / "Earnings.tsx").read_text()
    assert "<CashEligibilityCard" in screen, (
        "the eligibility card is imported but never rendered"
    )


def test_the_customer_is_told_before_choosing_cash_not_after():
    """The refusal is identical either way; the only difference is whether the
    customer wasted the trip filling in a phone number first."""
    checkout = _code_only(BACKEND / "routes" / "cart_routes.py")
    assert "payload['cash']" in checkout, "the quote does not state cash availability"
    assert "'available': True" in checkout and "'available': False" in checkout

    customer_app = BACKEND.parent / "drop-customer-app"
    if not customer_app.exists():
        pytest.skip("drop-customer-app/ is not present")

    cart = (customer_app / "app" / "(screens)" / "Cart.tsx").read_text()
    assert "cashAvailable" in cart
    assert "disabled={!cashAvailable}" in cart


def test_no_cash_threshold_is_a_literal_in_the_policy():
    """Every one of these will move with the platform's actual loss experience,
    and none of them is knowable in advance."""
    source = _code_only(BACKEND / "services" / "cod_policy.py")

    for key in (
        "cod_enabled",
        "cod_min_rider_deliveries",
        "cod_min_rider_rating",
        "cod_min_rider_completion_rate",
        "cod_min_rider_account_age_days",
        "cod_max_order_value_standard",
        "cod_max_order_value_platinum",
        "cod_max_concurrent_orders",
        "cod_max_daily_exposure",
        "cod_max_distance_km",
        "cod_min_customer_completed_orders",
        "cod_unclaimed_release_minutes",
        "cod_require_delivery_photo",
    ):
        assert key in source, f"{key} is registered but the policy never reads it"
        assert key in config.SPEC_BY_KEY, f"{key} is not editable from the console"


def test_operations_can_see_the_platforms_own_cash_exposure():
    """The limits capping this were set against a number nobody had looked at.

    `committed_cash_float` answers it per rider, on the rider's own screen. The
    platform's total — how much of its money is on a motorbike right now — was
    only ever a query somebody would have had to write.
    """
    policy = _code_only(BACKEND / "services" / "cod_policy.py")
    routes = _code_only(BACKEND / "routes" / "admin_finance_routes.py")

    assert "async def exposure_summary" in policy
    assert "cash-exposure" in routes

    admin = BACKEND.parent / "drop-admin"
    if not admin.exists():
        pytest.skip("drop-admin/ is not present")

    page = (admin / "app" / "(dashboard)" / "finance" / "reconciliation" / "page.tsx").read_text()
    panel = (
        admin / "app" / "(dashboard)" / "finance" / "reconciliation" / "CashExposure.tsx"
    ).read_text()

    assert "<CashExposurePanel" in page, "the exposure panel is imported but never rendered"
    # Age beside the amount: the release sweep acts on it, and the release
    # window comes from the setting rather than being restated here.
    assert "held_minutes" in panel
    assert "releaseAfterMinutes" in panel
    assert "cod_unclaimed_release_minutes" in page
