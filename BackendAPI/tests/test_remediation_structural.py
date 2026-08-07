"""
Structural guards for the remaining audit findings.

Each of these is a rule spread across several files that nobody will remember in
six months, including the person who wrote it. A unit test proves the call sites
that exist today are right and says nothing about the next one — which is how
every defect below came to exist in the first place.
"""
import ast
import pathlib

import pytest

from services import platform_config_service as config

SERVICES = pathlib.Path("services")
ROUTES = pathlib.Path("routes")
JOBS = pathlib.Path("jobs")


def _function(path: pathlib.Path, name: str):
    tree = ast.parse(path.read_text())
    found = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )
    assert found is not None, f"{name} not found in {path}"
    return found


def _calls(node) -> set[str]:
    return {
        call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    }


def _code_only(path: pathlib.Path) -> str:
    """The module's source with comments and docstrings removed.

    Several of the assertions below search for a string that must *not* appear —
    a hardcoded interval, a dropped column name. The explanation of why it was
    removed inevitably names it, so a naive search matches the very comment
    documenting the fix. `ast.unparse` on a tree with docstrings stripped gives
    back executable code and nothing else.

    The settlement suite hit this exact trap: both the page and the button
    component *explain* why there is no Retry button, and the test matched the
    explanation.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── F-13: products are withdrawn, never deleted ───────────────────────────

#: Every module that reads `Products` for a customer or a vendor choosing what to
#: sell. Admin and analytics modules are excluded deliberately — a withdrawn
#: product still has to appear in a report about the orders that contain it.
PRODUCT_READ_PATHS = [
    SERVICES / "product_service.py",
    SERVICES / "query_service.py",
    SERVICES / "vendor_management_service.py",
]


@pytest.mark.parametrize("path", PRODUCT_READ_PATHS, ids=lambda p: p.name)
def test_every_catalogue_read_excludes_withdrawn_products(path: pathlib.Path):
    """Counted per read, not per file.

    A file-level "does the word appear anywhere" check passes with one query
    still returning withdrawn rows — the trap the review-moderation test
    documents. Matching per *statement* is too tight in the other direction:
    `get_vendor_products` accumulates a `conditions` list over several branches
    and applies it with `and_(*conditions)`, which is correct and idiomatic, and
    a statement-level matcher cannot see it.

    So: every function must mention the filter at least once per `select(Product)`
    it contains. A function with two product reads and one filter still fails,
    which is the case that actually matters.
    """
    tree = ast.parse(path.read_text())

    #: Reads that legitimately see withdrawn rows, each named and justified.
    EXEMPT = {
        # The vendor is withdrawing this very product; it must be found first.
        "delete_product",
        # Restoring stock on a cancelled order touches products by id. A
        # withdrawn product still has to take its stock back, or the count is
        # permanently wrong on a row somebody may later restore.
        "restore_order_stock",
        "_restore_order_stock",
    }

    offenders = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name in EXEMPT:
            continue

        reads = sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "select"
            and any(getattr(arg, "id", "") == "Product" for arg in node.args)
        )
        if not reads:
            continue

        source = ast.unparse(function)
        filters = source.count("live_product") + source.count("deleted_at")
        if filters < reads:
            offenders.append(f"{function.name}: {reads} read(s), {filters} filter(s)")

    assert not offenders, (
        f"{path} selects Product without filtering withdrawn rows in: {offenders}.\n\n"
        "A product is withdrawn by setting `deleted_at`, not by deleting the row — "
        "`Order_Items` references it and the bottle ledger reads its capacity. "
        "Add `live_product()` from `services.product_service` to the WHERE clause."
    )


def test_deleting_a_product_sets_deleted_at_rather_than_removing_the_row():
    """`Order_Items.product_id` has no `ondelete`, so a hard delete of a product
    that has ever sold is a foreign-key violation the vendor sees as a bare 500."""
    delete = _function(SERVICES / "vendor_management_service.py", "delete_product")
    source = ast.unparse(delete)

    assert "deleted_at" in source
    assert "session.delete" not in source, (
        "delete_product still hard-deletes. Set `deleted_at` instead."
    )


# ── F-05: every dispatch tier filters on distance ─────────────────────────


def test_tier_one_dispatch_is_bounded_by_distance():
    """The strongest offer the platform sends was the one with no geographic filter.

    Registration bounds a rider's *base*, not where they are now: a rider
    registered in Ngong and currently in Mombasa received the Tier 1 push.
    """
    dispatch = _function(SERVICES / "order_service.py", "dispatch_order_to_riders")
    source = ast.unparse(dispatch)

    assert "rider_search_bounds" in source, (
        "Tier 1 does not use `rider_search_bounds`, so it is not filtering on "
        "distance. Tiers 2 and 3 both do."
    )
    assert "h3_index_res8" in source
    assert "ST_Distance" in source


def test_all_three_tiers_share_one_definition_of_nearby():
    """One helper, so a radius change cannot reach two tiers and miss the third."""
    source = (SERVICES / "order_service.py").read_text()
    assert source.count("rider_search_bounds(") >= 2


def test_the_fallback_rider_scan_can_use_the_spatial_index():
    """`ST_DWithin`, not `ST_Distance <= …`.

    The second form forces the distance to be computed for every rider row on
    the platform before anything can be discarded — a sequential scan on exactly
    the dispatches that find nobody nearby.
    """
    closest = _function(SERVICES / "order_service.py", "get_closest_deliverer")
    source = ast.unparse(closest)
    assert "ST_DWithin" in source, (
        "the fallback scan is not index-assisted; use ST_DWithin for the bound "
        "and keep ST_Distance only for the ORDER BY"
    )


# ── F-07: Tier 2 escalation survives a restart ────────────────────────────


def test_the_tier_two_escalation_is_queued_not_slept_through():
    """An `asyncio.sleep` in an API background task dies with the process.

    A deploy during the twenty-second window killed the escalation outright, and
    the order was only rescued three minutes later by the re-offer sweep.
    """
    dispatch = _function(SERVICES / "order_service.py", "dispatch_order_to_riders")
    assert "_schedule_trip_radar" in _calls(dispatch)

    worker = pathlib.Path("worker.py").read_text()
    assert "dispatch_trip_radar_task" in worker
    # And registered, or the queue accepts a job nothing will ever run.
    functions_block = worker[worker.index("functions = ["):]
    assert "dispatch_trip_radar_task" in functions_block[: functions_block.index("]")]


def test_the_radar_broadcast_rechecks_the_order_before_sending():
    """It runs up to twenty seconds after the decision to schedule it.

    An order claimed during the wait must never be broadcast a second time.
    """
    broadcast = _function(SERVICES / "order_service.py", "broadcast_trip_radar")
    source = ast.unparse(broadcast)
    assert "unassigned" in source and "deliverer_id" in source


# ── F-09: every balance movement goes through the ledger ──────────────────

#: Modules that move money. `wallet_service` is excluded: it *is* the ledger.
BALANCE_WRITERS = [
    SERVICES / "deliverer_service.py",
    SERVICES / "order_service.py",
    SERVICES / "payout_service.py",
    SERVICES / "customer_bottle_service.py",
]


@pytest.mark.parametrize("path", BALANCE_WRITERS, ids=lambda p: p.name)
def test_no_module_assigns_a_wallet_balance_directly(path: pathlib.Path):
    """`apply_wallet_delta` moves the balance and writes the row as one operation.

    The loyalty cashback was a bare `customer.wallet_balance += 10.0`: a float
    added to a `Numeric` column with no `WalletTransaction` behind it, so summing
    a customer's ledger no longer reproduced their balance.
    """
    tree = ast.parse(path.read_text())

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not (isinstance(target, ast.Attribute) and target.attr == "wallet_balance"):
                continue
            # `create_order` re-seats the balance to the value it read under the
            # row lock before applying the delta. That is a restore, not a
            # movement, and the delta immediately after it is what moves money.
            if isinstance(node, ast.Assign) and "locked_balance" in ast.unparse(node.value):
                continue
            offenders.append(f"line {node.lineno}: {ast.unparse(node)}")

    assert not offenders, (
        f"{path} writes wallet_balance directly at {offenders}.\n\n"
        "Use `wallet_service.apply_wallet_delta`, which moves the balance and "
        "appends the signed WalletTransaction together — never one without the other."
    )


def test_the_loyalty_cashback_is_a_setting_and_goes_through_the_ledger():
    update = _function(SERVICES / "deliverer_service.py", "update_delivery_status")
    source = ast.unparse(update)

    assert "loyalty_cashback_per_delivery" in source
    assert "apply_wallet_delta" in source
    assert "loyalty_cashback_per_delivery" in config.SPEC_BY_KEY


# ── F-04 / F-11: no business figure is a literal ──────────────────────────


def test_the_mismatch_charge_is_derived_from_the_staircase_setting():
    """It was a flat `charge = 30.0`, unrelated to `staircase_surcharge_per_floor`
    and applied regardless of how many floors were actually climbed."""
    resolve = _function(SERVICES / "order_service.py", "resolve_address_mismatch")
    source = ast.unparse(resolve)

    assert "staircase_surcharge_per_floor" in source
    assert "staircase_free_floors" in source
    assert "30.0" not in source and "charge = 30" not in source


def test_the_auto_cancel_age_comes_from_the_settings_table():
    """It was `INTERVAL '15 minutes'`, hardcoded beside an editable console field
    that was wired to nothing — so raising the setting changed nothing."""
    source = _code_only(JOBS / "auto_cancel_pending_orders.py")
    assert "order_auto_cancel_minutes" in source
    assert "15 minutes" not in source


def test_the_stale_threshold_comes_from_the_settings_table():
    source = _code_only(ROUTES / "admin_orders_routes.py")
    assert "order_stale_after_minutes" in source


def test_the_kyc_target_is_actually_measured_against():
    """`rider_kyc_sla_hours` was editable and read by nothing."""
    source = _code_only(SERVICES / "admin_queue_service.py")
    assert "rider_kyc_sla_hours" in source
    # `_code_only` re-unparses the AST, which normalises string quoting — match
    # the key itself rather than the quotes it happened to be written with.
    assert "overdue" in source


def test_cancelling_before_the_board_flags_it_is_refused():
    """Orders would be cancelled before anyone was told they were stuck."""
    with pytest.raises(ValueError, match="cancelled before they were ever flagged"):
        config.validate_all(
            {"order_auto_cancel_minutes": 60, "order_stale_after_minutes": 45}
        )


# ── F-10: the stale-asset job reads a column that exists ──────────────────


def test_the_stale_asset_monitor_reads_a_real_column():
    """It read `User.empty_bottles_held`, dropped by migration `3ba669eb21f3`.

    That is an `AttributeError` on every run — the job had never sent a single
    message and never could, which from the outside looked like "no matches".
    """
    from models.user_model import User

    source = _code_only(JOBS / "stale_asset_monitor.py")
    assert "empty_bottles_held" not in source
    assert "bottles_held" in source
    assert hasattr(User, "bottles_held")


# ── The reversal path, in one place ───────────────────────────────────────

#: Every path that takes an order out of the flow. All six previously carried
#: their own subset of the reversal, and `commission_lost` was missing from the
#: vendor's own reject — the most common kind.
REVERSAL_SITES = [
    (SERVICES / "order_service.py", "cancel_customer_order"),
    (SERVICES / "vendor_management_service.py", "cancel_order"),
    (SERVICES / "vendor_management_service.py", "update_order_status"),
    (SERVICES / "deliverer_service.py", "cancel_delivery"),
    (JOBS / "auto_cancel_pending_orders.py", "run_auto_cancel_orders"),
    (JOBS / "auto_resolve_bottle_rejections.py", "run_auto_resolve_bottle_rejections"),
]


@pytest.mark.parametrize(
    "path,function_name", REVERSAL_SITES, ids=[f"{p.stem}::{n}" for p, n in REVERSAL_SITES]
)
def test_every_reversal_path_uses_the_shared_helper(path: pathlib.Path, function_name: str):
    node = _function(path, function_name)
    assert "revert_order_side_effects" in _calls(node), (
        f"{path}::{function_name} reverses an order without "
        "`order_service.revert_order_side_effects`.\n\n"
        "Cancelling is seven things, not one: stock, the wallet credit, the "
        "settled debt, the bottle deposit, the welcome offer, the refund flag "
        "and `commission_lost`. Six call sites each remembering a different "
        "subset is how `commission_lost` came to be null on every vendor reject."
    )


def test_the_reversal_helper_restores_the_settled_debt():
    """The customer is refunded the total that included it, so it is still owed.

    Without this, a customer could clear a penalty by placing an order and
    immediately cancelling it.
    """
    revert = _function(SERVICES / "order_service.py", "revert_order_side_effects")
    source = ast.unparse(revert)

    assert "debt_settlement" in source
    assert "debt_balance" in source
    assert "commission_lost" in source
    assert "bottle_deposit" in source
