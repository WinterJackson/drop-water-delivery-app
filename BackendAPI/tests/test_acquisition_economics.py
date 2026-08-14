"""What a customer costs, and whether they pay it back.

`retention_cohorts` has always answered *do customers come back*. It does not
answer the question a business acts on — **whether the ones who came back paid
back what it cost to get them** — and the platform has had every input for that
on every order since the first one. `welcome_discount` is real acquisition
spend, recorded per order, summed nowhere.

The tests here fall into three groups, and the second is the reason this file is
worth reading:

1. The arithmetic is right — cohorts, cumulative contribution, payback.
2. **The dishonest answers are refused.** A CAC assembled only from the half the
   platform can measure is precise, confident, and typically wrong by an order
   of magnitude *in the direction that makes acquisition look cheap*. So is an
   average payback taken over cohorts too young to have paid back, and so is a
   window that silently discards money spent in a month that acquired nobody.
   Each of those is a number somebody would raise a budget against.
3. Nothing is projected. Every figure is money that has already moved.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services import admin_growth_service as growth

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings — needed by any "must not appear" assertion,
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


def _month(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _session(cohort_rows, spend_rows=()):
    """A session that answers by *shape* rather than by call order.

    Ordering the answers was the obvious way to write this and it broke the
    moment `acquisition_summary` was changed to read the spend table once and
    hand the map down — a legitimate improvement that a positional harness turns
    into a spurious failure. Matching on the statement keeps the test about the
    arithmetic rather than about how many queries the service happens to issue.
    """
    session = AsyncMock()

    def _execute(statement, *args, **kwargs):
        result = MagicMock()
        text = str(statement)
        result.all.return_value = (
            list(spend_rows) if "Acquisition_Spend" in text else list(cohort_rows)
        )
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


# ── The arithmetic ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cohort_reports_its_size_retention_and_cumulative_contribution():
    """Ten customers in March; six of them ordered again in April."""
    cohort = _month(2026, 3)
    rows = [
        # (cohort, active month, distinct customers, platform_net, welcome_discount)
        (cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("900")),
        (cohort, _month(2026, 4), 6, Decimal("800"), Decimal("0")),
    ]

    result = await growth.cohort_economics(_session(rows), months=12)
    [entry] = result["cohorts"]

    assert entry["size"] == 10
    assert entry["months"][0]["retention_pct"] == "100.0"
    assert entry["months"][1]["retention_pct"] == "60.0"
    # Cumulative, not per-month: 1000 then 1800, and 180 per customer.
    assert entry["months"][1]["cumulative_net"] == "1800.00"
    assert entry["months"][1]["cumulative_per_customer"] == "180.00"
    assert entry["realised_per_customer"] == "180.00"


@pytest.mark.asyncio
async def test_payback_is_the_first_month_the_cohort_covers_what_it_cost():
    """KSH 90 each to acquire; 100 back in month zero. Paid back in M0."""
    cohort = _month(2026, 3)
    rows = [
        (cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("900")),
        (cohort, _month(2026, 4), 6, Decimal("800"), Decimal("0")),
    ]

    [entry] = (await growth.cohort_economics(_session(rows), months=12))["cohorts"]

    assert entry["cac"]["measured"] == "90.00"
    assert entry["payback_month"] == 0


@pytest.mark.asyncio
async def test_a_cohort_that_has_not_paid_back_says_so_rather_than_reporting_zero():
    """`None` is a fact about a young cohort, not a failure.

    Reporting 0, or the last month, would make every cohort look as though it
    had paid back — and the screen colours the cell green off this.
    """
    cohort = _month(2026, 7)
    rows = [(cohort, _month(2026, 7), 10, Decimal("50"), Decimal("900"))]

    [entry] = (await growth.cohort_economics(_session(rows), months=12))["cohorts"]

    assert entry["cac"]["measured"] == "90.00"
    assert entry["months"][0]["cumulative_per_customer"] == "5.00"
    assert entry["payback_month"] is None


@pytest.mark.asyncio
async def test_a_month_the_cohort_did_not_trade_carries_the_cumulative_forward():
    """A gap is not a reset.

    Month 1 with no orders must still show month 0's cumulative total, or the
    grid reads as though the cohort gave the money back.
    """
    cohort = _month(2026, 3)
    rows = [
        (cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("0")),
        (cohort, _month(2026, 5), 4, Decimal("400"), Decimal("0")),
    ]

    [entry] = (await growth.cohort_economics(_session(rows), months=12))["cohorts"]

    assert [m["month"] for m in entry["months"]] == [0, 1, 2]
    assert entry["months"][1]["customers"] == 0
    assert entry["months"][1]["cumulative_net"] == "1000.00"
    assert entry["months"][2]["cumulative_net"] == "1400.00"


@pytest.mark.asyncio
async def test_a_cohort_with_no_month_zero_is_dropped():
    """It is not a cohort — every customer in it was acquired in a month whose
    first delivery this window never saw. Keeping it would divide by zero, or
    report a cohort of size 0 with a contribution."""
    cohort = _month(2026, 3)
    rows = [(cohort, _month(2026, 5), 4, Decimal("400"), Decimal("0"))]

    assert (await growth.cohort_economics(_session(rows), months=12))["cohorts"] == []


# ── The dishonest answers ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_measured_and_entered_acquisition_cost_are_never_merged_silently():
    """The platform can prove one and cannot see the other.

    A cohort with nothing entered must be marked as such. Rendering its measured
    CAC as *the* CAC is how a screen reports that acquisition costs KSH 90 when
    it cost KSH 900, on figures that are every one of them real.
    """
    cohort = _month(2026, 3)
    rows = [(cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("900"))]

    [entry] = (await growth.cohort_economics(_session(rows), months=12))["cohorts"]

    assert entry["cac"]["has_entered_spend"] is False
    assert entry["cac"]["entered"] is None
    assert entry["cac"]["blended"] == entry["cac"]["measured"]


@pytest.mark.asyncio
async def test_entered_spend_raises_the_blended_cac_above_the_measured_one():
    cohort = _month(2026, 3)
    rows = [(cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("900"))]
    spend = [(date(2026, 3, 1), Decimal("5000"))]

    [entry] = (await growth.cohort_economics(_session(rows, spend), months=12))["cohorts"]

    assert entry["cac"]["measured"] == "90.00"
    assert entry["cac"]["entered"] == "500.00"
    assert entry["cac"]["blended"] == "590.00"
    assert entry["cac"]["has_entered_spend"] is True


@pytest.mark.asyncio
async def test_spend_in_a_month_that_acquired_nobody_is_counted_and_named():
    """The single most important month on the screen.

    Summing entered spend per *cohort* is the obvious way to write this, and it
    silently discards every shilling spent in a month with no acquisitions —
    which is the definition of acquisition not working. The arithmetic that
    hides it is the arithmetic that flatters.
    """
    cohort = _month(2026, 3)
    rows = [(cohort, _month(2026, 3), 10, Decimal("1000"), Decimal("0"))]
    spend = [
        (date(2026, 3, 1), Decimal("1000")),
        (date(2026, 4, 1), Decimal("5000")),   # April acquired nobody
    ]

    summary = await growth.acquisition_summary(_session(rows, spend), months=12)

    assert summary["entered_spend"] == "6000.00", "April's spend was dropped"
    assert summary["unattributed_spend"] == "5000.00"
    # And it is in the blended CAC: 6000 over 10 customers, not 1000 over 10.
    assert summary["blended_cac"] == "600.00"


@pytest.mark.asyncio
async def test_median_payback_counts_only_cohorts_that_have_actually_paid_back():
    """Averaging in a cohort that has not paid back reports a payback period
    shorter than any cohort has ever achieved — the most persuasive kind of
    wrong number, because it is arithmetically defensible and false."""
    rows = [
        # KSH 100 each to acquire; 40, then 40, then 40 — covered in M2.
        (_month(2026, 1), _month(2026, 1), 10, Decimal("400"), Decimal("1000")),
        (_month(2026, 1), _month(2026, 2), 8, Decimal("400"), Decimal("0")),
        (_month(2026, 1), _month(2026, 3), 6, Decimal("400"), Decimal("0")),
        # KSH 90 each, KSH 1 back. Nowhere near paying back.
        (_month(2026, 6), _month(2026, 6), 10, Decimal("10"), Decimal("900")),
    ]

    summary = await growth.acquisition_summary(_session(rows), months=12)

    assert summary["cohorts_paid_back"] == 1
    # The median of the cohorts that *have* paid back is 2. Counting the second
    # cohort as though it had paid back in month 0 — the tempting `or 0` — gives
    # 1.0, a payback period faster than any cohort on this platform has ever
    # achieved, computed from real numbers.
    assert summary["median_payback_month"] == 2.0


@pytest.mark.asyncio
async def test_no_customers_reports_no_cac_rather_than_zero():
    """A CAC of zero reads as "free", and free is a claim."""
    summary = await growth.acquisition_summary(_session([]), months=12)

    assert summary["customers_acquired"] == 0
    assert summary["measured_cac"] is None
    assert summary["blended_cac"] is None


@pytest.mark.asyncio
async def test_the_summary_says_how_much_of_the_window_has_entered_spend():
    """So a screen can say "nothing recorded" instead of rendering a blended CAC
    that is a measured one under a different name."""
    rows = [(_month(2026, 3), _month(2026, 3), 10, Decimal("1000"), Decimal("900"))]

    blank = await growth.acquisition_summary(_session(rows), months=12)
    assert blank["months_with_entered_spend"] == 0
    assert blank["blended_cac"] == blank["measured_cac"]

    filled = await growth.acquisition_summary(
        _session(rows, [(date(2026, 3, 1), Decimal("5000"))]), months=12
    )
    assert filled["months_with_entered_spend"] == 1
    assert Decimal(filled["blended_cac"]) > Decimal(filled["measured_cac"])


# ── Entering the half the database cannot see ─────────────────────────────


def _writer():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=uuid4())))
    return session


@pytest.mark.asyncio
async def test_any_day_in_a_month_is_stored_as_the_first():
    """"2026-08-14" and "2026-08-01" meaning the same month is exactly how this
    table ends up holding two rows for August that nobody can reconcile."""
    result = await growth.record_spend(
        _writer(), period_month=date(2026, 8, 14), channel="Ads", amount=Decimal("100")
    )
    assert result["period_month"] == "2026-08-01"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,kwargs,phrase",
    [
        ("no channel", dict(channel="   ", amount=Decimal("1")), "channel"),
        ("negative", dict(channel="Ads", amount=Decimal("-1")), "negative"),
    ],
)
async def test_a_meaningless_entry_is_refused(label, kwargs, phrase):
    with pytest.raises(HTTPException) as exc:
        await growth.record_spend(_writer(), period_month=date(2026, 8, 1), **kwargs)
    assert phrase in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_spend_cannot_be_recorded_against_a_future_month():
    """A month that has not happened cannot have been spent in, and spend filed
    forward silently lowers the CAC of every month between now and then."""
    ahead = datetime.now(timezone.utc) + timedelta(days=400)
    with pytest.raises(HTTPException) as exc:
        await growth.record_spend(
            _writer(), period_month=ahead.date(), channel="Ads", amount=Decimal("1")
        )
    assert "not happened" in exc.value.detail


@pytest.mark.asyncio
async def test_recording_the_same_month_and_channel_replaces_rather_than_adds():
    """A CAC that doubles overnight is indistinguishable from a bad month, which
    is the worst kind of wrong number because it prompts a decision."""
    session = _writer()
    await growth.record_spend(
        session, period_month=date(2026, 8, 1), channel="Ads", amount=Decimal("100")
    )
    statement = str(session.execute.await_args[0][0])
    assert "ON CONFLICT" in statement.upper()


# ── Structural ────────────────────────────────────────────────────────────


def test_contribution_is_platform_net_and_is_never_re_derived():
    """`platform_net` is frozen on the order when it was placed.

    Recomputing it from today's commission settings would restate what a cohort
    earned last March every time somebody moved a rate — and the whole reason
    those splits are frozen on the row is that the money already agreed stays
    agreed.
    """
    source = _code_only(BACKEND / "services/admin_growth_service.py")

    assert "platform_net" in source
    for re_derivation in ("platform_total", "vendor_commission", "rider_commission"):
        assert re_derivation not in source, (
            f"the growth service reads {re_derivation}, which means it is "
            "rebuilding a contribution figure the order already carries"
        )


def test_a_cohort_is_a_first_delivered_order_not_a_signup():
    """An account that never received water was not acquired, and a signup
    cohort makes every retention figure look worse than the business is.

    The `MIN()` this used to look for in `admin_growth_service` now lives in
    `customer_cohort_service._derived_query`, which is the one place the
    definition is written: the table is backfilled from it, reconciled against it
    nightly, and the report reads the table. The invariant did not move — only the
    module did — so this follows it rather than being relaxed.
    `tests/test_customer_cohorts.py` checks the derivation itself in detail.
    """
    assert growth.ACQUIRED_STATUS == "delivered"

    source = _code_only(BACKEND / "services/customer_cohort_service.py")
    assert "func.min" in source, "the cohort must be the customer's *first* delivered order"

    report = _code_only(BACKEND / "services/admin_growth_service.py")
    assert "customer_cohort_service" in report, (
        "the growth report no longer reads the cohort table; if it has gone back "
        "to deriving cohorts live, that is a full scan of Orders per page load"
    )


@pytest.mark.asyncio
async def test_the_cohort_month_is_taken_over_all_history_not_the_window():
    """A `MIN()` computed inside the window would re-acquire a two-year customer
    into this month's cohort — inventing new customers out of loyal ones, and
    flattering both the growth figure and the CAC."""
    session = AsyncMock()
    await growth._first_delivered_month(session)

    # The subquery filters on status only; the window is applied to its result.
    source = _code_only(BACKEND / "services/admin_growth_service.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_first_delivered_month":
            body = ast.unparse(node)
            assert "created_at >=" not in body and "start" not in body, (
                "the first-delivery subquery is bounded by the window, so a "
                "long-standing customer would be re-acquired into it"
            )
            return
    pytest.fail("_first_delivered_month not found")


def test_nothing_is_projected():
    """An LTV extrapolated from four months is a guess wearing a number's
    clothes, and it is the number people raise budgets against."""
    source = _code_only(BACKEND / "services/admin_growth_service.py")

    for forecast in ("projected", "forecast", "extrapolat", "predicted_ltv"):
        assert forecast not in source.lower(), (
            f"the growth service produces a {forecast!r} figure; every number "
            "here must be money that has already moved"
        )
    assert "realised_per_customer" in source, (
        "the realised figure must be named as realised, or somebody will read "
        "it as a forecast"
    )


def test_entering_spend_is_a_settings_decision_and_is_audited():
    """A figure that moves every CAC on the console is a decision about the
    business, not a report — and a number that changed with nothing recording
    who changed it is a number nobody will trust enough to act on."""
    tree = ast.parse((BACKEND / "routes/admin_analytics_routes.py").read_text())

    seen = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                path = dec.args[0].value
                if isinstance(path, str) and path.startswith("/growth/spend"):
                    seen[(dec.func.attr.upper(), path)] = ast.unparse(node)

    writes = [(k, v) for k, v in seen.items() if k[0] in ("PUT", "DELETE")]
    assert writes, "the spend write endpoints are missing"
    for (method, path), body in writes:
        assert "PERM_SETTINGS_MANAGE" in body, f"{method} {path} is not a settings decision"
        assert "record_audit" in body, f"{method} {path} changes a CAC without an audit row"
        assert "db.commit" in body, (
            f"{method} {path} does not commit, so the audit row and the change "
            "cannot land together"
        )


def test_the_deletion_audit_records_what_was_removed():
    """A hole in the CAC series with no record of what filled it is one nobody
    can later explain."""
    tree = ast.parse((BACKEND / "routes/admin_analytics_routes.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "growth_delete_spend":
            assert "before=" in ast.unparse(node)
            return
    pytest.fail("growth_delete_spend not found")


def test_the_console_renders_the_measured_only_caveat():
    """The warning is the point of the screen.

    A blended CAC over a window with nothing entered is a measured CAC under a
    misleading name, and it makes acquisition look cheaper than it is. If the
    caveat is ever dropped, the page becomes the thing this phase exists to
    prevent.
    """
    console = BACKEND.parent / "drop-admin/app/(dashboard)/analytics/growth"
    summary = (console / "CohortEconomics.tsx").read_text()

    assert "months_with_entered_spend" in summary
    assert "measured only" in summary
    assert "unattributed_spend" in summary, (
        "the page does not surface spend from months that acquired nobody"
    )


def test_the_acquisition_page_is_declared_in_the_nav():
    """Every destination is declared once; a page nobody can reach is a page
    nobody reads."""
    nav = (BACKEND.parent / "drop-admin/components/shell/nav-config.ts").read_text()
    assert '"/analytics/growth"' in nav
