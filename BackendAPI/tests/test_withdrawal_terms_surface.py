"""
What a rider or vendor is *told* about a withdrawal matches what they are charged.

Three business figures governed every cashout — the minimum, the fee, and the
threshold that waives the fee — and all three were literals in the apps while
`settlement_service.withdrawal_terms` read them from `Platform_Settings`. So the
console could change what a withdrawal cost and not what the person was told it
would cost.

Worse than stale: the *rule* was wrong. `fee_for` waives on the **amount
withdrawn**; both apps measured the **balance held**, drew a progress bar of
`balance / threshold`, and told people to keep money in the wallet to earn a free
withdrawal. A rider sitting on KSH 1,200 who withdrew KSH 600 was shown "Zero
Network Fee Applied!" and charged the fee. It also inverts the waiver's purpose —
the platform pays one M-Pesa B2C tariff per disbursement, so it wants fewer,
larger withdrawals, not larger idle balances.

The same pass found Platinum's *reward* configurable
(`gig_platinum_rider_commission_rate`) while its *requirement* was `>= 20` over
`days=7` inside the nightly job, with the rider app stating `20` and "7 days" as
literals of its own.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RIDER = REPO / "drop-rider-app"
VENDOR = REPO / "drop-vendor-app"

pytestmark = pytest.mark.skipif(
    not (RIDER.exists() and VENDOR.exists()),
    reason="the apps are not in this checkout",
)

CASHOUT = RIDER / "app/(screens)/Cashout.tsx"
WALLET = VENDOR / "app/(screens)/WalletScreen.tsx"
PERFORMANCE = RIDER / "app/(screens)/Performance.tsx"


def _code_only(path: pathlib.Path) -> str:
    """TypeScript with comments stripped.

    Every "must not appear" assertion below needs this: the comment recording
    why a literal was removed has to name the literal.
    """
    source = path.read_text()
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ── The three figures come from the server ────────────────────────────────


def test_both_wallet_summaries_return_the_withdrawal_terms():
    """From `withdrawal_terms`, which is what the withdrawal itself calls — so
    the quoted rule and the applied rule cannot be two implementations."""
    for module in ("routes/deliverer_routes.py", "routes/vendor_management_routes.py"):
        source = (REPO / "BackendAPI" / module).read_text()
        assert "withdrawal_terms" in source, f"{module} does not read the terms"
        assert '"fee_waiver_threshold"' in source, f"{module} does not return them"


def test_the_vendor_terms_are_scoped_to_the_stores_type():
    """Wholesale and retail have different minimums and waivers. An owner
    holding one of each would otherwise be shown whichever row came back
    first."""
    source = (REPO / "BackendAPI" / "routes" / "vendor_management_routes.py").read_text()
    assert re.search(
        r"withdrawal_terms\(\s*db,\s*provider_type=\"vendor\",\s*vendor_type=vendor\.vendor_type",
        source,
    ), "the vendor's withdrawal terms are not scoped to its own type"


@pytest.mark.parametrize("screen", [CASHOUT, WALLET], ids=["rider", "vendor"])
def test_no_screen_hardcodes_a_withdrawal_figure(screen):
    source = _code_only(screen)

    # The literals that were there: 500 minimum, 15 fee, 1000/2500/5000 waivers.
    assert not re.search(r"freeCashoutThreshold\s*=\s*\d", source), (
        "the fee-waiver threshold is a literal again"
    )
    assert not re.search(r"Number\(withdrawAmount\)\s*<\s*\d", source), (
        "the withdrawal minimum is a literal again"
    )
    assert "KSH 15" not in source, "the transaction fee is a literal again"
    assert "withdrawal?.fee_waiver_threshold" in source
    assert "withdrawal?.minimum" in source


# ── The waiver is about the amount, not the balance ───────────────────────


@pytest.mark.parametrize("screen", [CASHOUT, WALLET], ids=["rider", "vendor"])
def test_the_fee_is_computed_from_the_amount_entered(screen):
    """`settlement_service.fee_for(amount, fee, threshold)`. Anything keyed on
    the balance is quoting a different rule from the one that will be applied."""
    source = _code_only(screen)
    assert "amountEntered" in source, f"{screen.name} does not read the entered amount"
    assert re.search(
        r"compareMoney\(\s*amountEntered,\s*freeCashoutThreshold\s*\)\s*>=\s*0", source
    ), f"{screen.name} does not decide the fee on the amount"


@pytest.mark.parametrize("screen", [CASHOUT, WALLET], ids=["rider", "vendor"])
def test_no_screen_tells_anyone_to_hoard_a_balance_for_a_free_withdrawal(screen):
    """The exact sentence that was wrong, and the shape of it.

    "Keep KSH X more in your float balance to unlock zero-fee withdrawals"
    describes a rule the platform does not implement and would not want to.
    """
    source = _code_only(screen)
    assert "in your float balance to unlock" not in source
    assert not re.search(r"freeCashoutThreshold\s*-\s*balance\b", source)
    assert not re.search(r"subtractMoney\(\s*freeCashoutThreshold,\s*balance\s*\)", source)


@pytest.mark.parametrize("screen", [CASHOUT, WALLET], ids=["rider", "vendor"])
def test_the_progress_bar_measures_what_is_withdrawable(screen):
    """Not the raw balance. Float committed to open cash orders cannot be
    withdrawn at any size, so a goal measured against the balance promises a
    free withdrawal the person cannot actually make."""
    source = _code_only(screen)
    assert not re.search(r"moneyRatio\(\s*balance\s*,", source), (
        "the progress bar is measuring the raw balance again"
    )


# ── Platinum: the requirement is a row, like the reward ───────────────────


def test_both_halves_of_the_platinum_rule_are_settings():
    from services.platform_config_service import SPEC_BY_KEY

    for key in ("platinum_min_deliveries", "platinum_window_days"):
        assert key in SPEC_BY_KEY, f"{key} is not a setting"
        spec = SPEC_BY_KEY[key]
        assert spec.label, f"{key} has no label — the console renders the raw key"
        assert spec.help, f"{key} has no help text"

    # The reward was already configurable; that is the point of the pairing.
    assert "gig_platinum_rider_commission_rate" in SPEC_BY_KEY


def test_the_nightly_job_reads_them_rather_than_a_literal():
    import ast

    source = (REPO / "BackendAPI" / "jobs" / "rider_tier_job.py").read_text()
    tree = ast.parse(source)
    # Docstrings out: the one on `evaluate_platinum_riders` explains what the
    # literals *were*, and therefore names them. Same trap the settlement,
    # remediation and support suites each hit.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    code = ast.unparse(tree)

    assert "platinum_min_deliveries" in code
    assert "platinum_window_days" in code
    assert ">= 20" not in code, "the promotion threshold is a literal again"
    assert "timedelta(days=7)" not in code, "the window is a literal again"


def test_the_rider_app_states_the_rule_the_job_applies():
    """The app said "complete 20 more deliveries in the last 7 days" from
    literals of its own, so raising the bar on the console would have kept
    quoting the old number while demoting riders against the new one."""
    source = _code_only(PERFORMANCE)

    assert "platinum_target" in source
    assert "platinum_window_days" in source
    assert "/ 20" not in source, "the target is a literal again"
    assert "deliveriesLast7Days / 20" not in source
    assert "in the last 7 days" not in source, "the window is a literal again"


def test_earnings_reports_progress_over_the_window_that_decides_the_tier():
    """Counting progress over a different period from the one the job evaluates
    is how a rider reaches the target on screen and is demoted anyway."""
    source = (REPO / "BackendAPI" / "services" / "deliverer_service.py").read_text()

    assert '"platinum_target"' in source
    assert '"platinum_window_days"' in source
    assert re.search(
        r"timedelta\(\s*days=config\.get_int\(\"platinum_window_days\"\)\s*\)", source
    ), "the earnings window is not the configured Platinum window"
