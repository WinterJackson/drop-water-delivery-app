"""`Customer_First_Delivery` must keep saying what the `MIN()` said.

The growth report used to derive a customer's cohort live, by grouping every
delivered order that had ever existed. That is now a materialised table, which is
a straight trade: a query that could only get slower for a value that has to stay
exactly equal to what the query produced.

Everything here defends that equality. A materialised figure that drifts from its
definition is worse than the slow query, because it is fast, confident and wrong
— and it is wrong on the screen people raise budgets against.
"""
import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
    return (BACKEND / relative).read_text()


def _code(text: str) -> str:
    """Source with comments and string bodies blanked, line numbers preserved.

    Every module here documents the defect it avoids, naming the forbidden
    construct in prose, so a plain substring scan flags the explanation as the
    offence. Only real code counts.

    Two passes, and the split between them is the whole subtlety. A **docstring**
    spans lines that are pure prose, so those lines are blanked outright — a
    per-line regex cannot see where such a string began. Every other string is
    blanked *within* its line by the regex, because the line also holds code:
    blanking the whole line for `X = "delivered"` would delete the assignment
    along with the literal, which is how the first version of this helper quietly
    removed the very statements it was meant to inspect.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    if tree is not None:
        docstring_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
                and first.lineno
                and first.end_lineno
            ):
                docstring_lines.update(range(first.lineno, first.end_lineno + 1))
        text = "\n".join(
            "" if n in docstring_lines else line
            for n, line in enumerate(text.split("\n"), 1)
        )

    out = []
    for line in text.split("\n"):
        without_comment = re.sub(r"(#|//).*$", "", line)
        blanked = re.sub(r'''("""|\'\'\'|"|\')(?:\\.|(?!\1).)*\1''', '""', without_comment)
        out.append(blanked)
    return "\n".join(out)


def _without_comments(text: str) -> str:
    """Comments and docstrings removed; **string literals kept**.

    `_code` blanks string bodies, which is right when the forbidden thing is a
    construct and the prose merely names it. It is exactly wrong when the thing
    being looked for *is* a literal — a status of `"delivered"`, a cron slug — and
    searching blanked source for one finds nothing, forever, silently. Two
    strippers because there are two questions, not because one of them is a
    workaround.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "\n".join(re.sub(r"#.*$", "", line) for line in text.split("\n"))

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.lineno
            and first.end_lineno
        ):
            docstring_lines.update(range(first.lineno, first.end_lineno + 1))

    return "\n".join(
        "" if n in docstring_lines else re.sub(r"#.*$", "", line)
        for n, line in enumerate(text.split("\n"), 1)
    )


# ── The definition ────────────────────────────────────────────────────────


def test_the_cohort_is_still_the_earliest_delivered_order_over_all_history():
    """Three clauses, each of which was argued for and any of which silently
    changes every figure on the growth screen if it moves:

    * `delivered` — an account that never received water was not acquired;
    * `MIN(created_at)` — when they *ordered*, so a delivery slipping into the
      next month cannot move a customer into the next cohort;
    * no window — a `MIN()` bounded by the report's own range re-acquires a
      two-year customer into this month, inventing new customers out of loyal
      ones.
    """
    source = _code(_source("services/customer_cohort_service.py"))
    tree = ast.parse(source)
    derived = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_derived_query"),
        None,
    )
    assert derived is not None, "_derived_query has moved; this table has no definition to check"
    body = ast.unparse(derived)

    assert "func.min(Order.created_at)" in body, (
        "the cohort must be the MIN of created_at — truncating first picks an "
        "arbitrary order within the earliest month"
    )
    assert "ACQUIRED_STATUS" in body
    assert "created_at >=" not in body and "start" not in body, (
        "the derivation is bounded by a window, so a long-standing customer "
        "would be re-acquired into it"
    )


def test_the_backfill_is_the_same_definition_as_the_service():
    """The migration seeds the table and the sweep repairs it. If those two
    disagree, the table oscillates between them on every deploy and every night,
    and no figure on the screen is reproducible."""
    migration = _source("alembic/versions/b8e1d47f3a92_customer_first_delivery.py")
    backfill = migration[migration.find("INSERT INTO") :]
    assert "MIN(o.created_at)" in backfill
    assert "order_status = 'delivered'" in backfill
    assert "GROUP BY o.customer_id" in backfill
    # The window would be the defect; assert it is absent from the backfill.
    assert "INTERVAL" not in backfill.upper()


def test_the_report_and_the_table_agree_on_what_acquired_means():
    """`ACQUIRED_STATUS` is imported, not restated.

    Two literals is how the table fills from one definition and the report reads
    it under another — and the mismatch shows up as a cohort that is simply
    empty, which reads as a bad month rather than a bug.
    """
    source = _code(_source("services/admin_growth_service.py"))
    assert "customer_cohort_service.ACQUIRED_STATUS" in source, (
        "admin_growth_service restates the acquired status instead of importing it"
    )


# ── The write ─────────────────────────────────────────────────────────────


def test_the_acquisition_write_only_ever_moves_the_cohort_earlier():
    """First-wins is the obvious hook and it is wrong.

    Orders do not reach `delivered` in `created_at` order: one placed in January
    and disputed until March is delivered after one placed in February. Without
    the predicate, the later delivery overwrites the earlier record and the
    customer sits in the wrong cohort permanently, contradicted by an order in
    the same table.
    """
    source = _code(_source("services/customer_cohort_service.py"))
    tree = ast.parse(source)
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "record_acquisition"),
        None,
    )
    assert fn is not None, "record_acquisition has moved; update this test"
    body = ast.unparse(fn)

    assert "on_conflict_do_update" in body, "the write is not idempotent"
    assert "where=" in body and "first_order_at" in body, (
        "the upsert has no guard, so a later delivery overwrites the first one"
    )


#: The one status that means a customer has been acquired.
_DELIVERED = "delivered"

#: Statuses whose presence in a list literal marks it as a *status whitelist*
#: rather than any other list of strings. A function that declares one and omits
#: `delivered` has proved it cannot deliver.
_STATUS_WORDS = {"accepted", "cancelled", "ready", "preparing", "rejected", "unassigned"}


def _status_argument(call: ast.Call):
    """The status `apply_status_transition` is being asked to move to."""
    if len(call.args) >= 2:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg in ("new_status", "status"):
            return keyword.value
    return None


def _cannot_deliver(function: ast.AST) -> bool:
    """True when the function declares a status whitelist that excludes `delivered`.

    This is what exempts `vendor_management_service.update_order_status`, which
    passes a *variable* to `apply_status_transition` and would otherwise have to
    be read as a possible delivery path. Its `valid_statuses` list is the proof
    that it is not — and if somebody ever adds `delivered` to that list, this
    stops exempting it and the guard starts demanding the hook. Which is exactly
    the behaviour wanted: the exemption is derived from the code, not asserted
    about it.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            continue
        values = {
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        if len(values) >= 3 and _DELIVERED not in values and values & _STATUS_WORDS:
            return True
    return False


def _delivery_paths() -> list[tuple[str, str, bool]]:
    """Every function that can move an order to `delivered`, found rather than listed.

    `(location, function name, calls the hook)`. Three cases, and the third is the
    reason this is AST rather than a grep:

    * the status is the literal `"delivered"` — the SMS fallback;
    * the status is a **variable**, so the function may or may not deliver. Unless
      it proves otherwise with a whitelist, it counts;
    * the status cannot be resolved at all — counts, because a guard that is
      unsure must fail closed. An unresolvable call is a refactor this test
      should be re-read against, not waved through.
    """
    found: list[tuple[str, str, bool]] = []
    for folder in ("routes", "services", "jobs"):
        for path in (BACKEND / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                body = ast.unparse(function)
                for call in ast.walk(function):
                    if not isinstance(call, ast.Call):
                        continue
                    name = (
                        call.func.attr
                        if isinstance(call.func, ast.Attribute)
                        else getattr(call.func, "id", "")
                    )
                    if name != "apply_status_transition":
                        continue

                    argument = _status_argument(call)
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        delivers = argument.value == _DELIVERED
                    elif argument is None:
                        delivers = True
                    else:
                        delivers = not _cannot_deliver(function)

                    if delivers:
                        found.append(
                            (
                                f"{path.relative_to(BACKEND)}:{call.lineno}",
                                function.name,
                                "record_acquisition" in body,
                            )
                        )
    return found


def test_every_path_that_delivers_an_order_records_the_acquisition():
    """A route that marks an order delivered without recording the acquisition
    is a **build failure**, not something to notice in a sweep the next morning.

    This is the point of the whole guard, and the first version of it got this
    wrong: it iterated two hardcoded file paths. That checks the two delivery
    paths that existed when it was written and is blind to a third — which is
    precisely the case the nightly reconciliation was there to catch, a day late,
    in a count somebody has to be watching. A runbook note is the weakest form of
    a guarantee this codebase has a habit of making structural.

    So the paths are **discovered**. Every call to `apply_status_transition` in
    `routes/`, `services/` and `jobs/` is classified by the status it moves to,
    and anything that can reach `delivered` must call `record_acquisition`. The
    reconciliation stays, because data can still drift for reasons that are not
    code — but a missing call site now fails CI instead of quietly understating
    acquisition until somebody reads a number.
    """
    paths = _delivery_paths()

    assert len(paths) >= 2, (
        f"only {len(paths)} delivery path(s) discovered. Two are known to exist "
        "(the rider completing a delivery, and the SMS fallback), so the scan has "
        "stopped matching and this test is passing vacuously."
    )

    offenders = [
        f"{where} {function}() moves an order to '{_DELIVERED}' without calling "
        "record_acquisition — this customer would never appear in a cohort"
        for where, function, hooked in paths
        if not hooked
    ]
    assert offenders == [], offenders


def test_the_delivery_path_scan_still_sees_the_paths_it_is_meant_to_cover():
    """Pins the discovery to the two paths known to exist.

    Without this, a change that made `_delivery_paths` return nothing at all
    would leave the test above passing — the failure mode every source-scanning
    guard in this suite is written to avoid.
    """
    located = {where.split(":")[0] for where, _function, _hooked in _delivery_paths()}
    assert "services/deliverer_service.py" in located, (
        "the rider's delivery completion is no longer recognised as a delivery path"
    )
    assert "routes/sms_routes.py" in located, (
        "the SMS fallback is no longer recognised as a delivery path"
    )


def test_a_new_delivery_path_without_the_hook_would_be_caught():
    """The property the whole guard exists for, checked against synthetic code
    rather than by breaking a real module.

    Three shapes a future delivery path could take, and each must be classified
    as one: a literal `"delivered"`, a variable with nothing constraining it, and
    a call whose status argument cannot be resolved at all.
    """
    def classify(source: str) -> bool:
        """True when this function counts as a delivery path."""
        function = ast.parse(source).body[0]
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            if name != "apply_status_transition":
                continue
            argument = _status_argument(call)
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                return argument.value == _DELIVERED
            if argument is None:
                return True
            return not _cannot_deliver(function)
        return False

    assert classify(
        'def complete(order):\n    apply_status_transition(order, "delivered")'
    ), "a literal delivery is not recognised as a delivery path"

    assert classify(
        "def complete(order, status):\n    apply_status_transition(order, status)"
    ), "an unconstrained variable is not recognised as a possible delivery path"

    assert classify(
        "def complete(order):\n    apply_status_transition(order)"
    ), "an unresolvable status must fail closed, not be waved through"

    assert not classify(
        'def touch(order):\n    apply_status_transition(order, "cancelled")'
    ), "a cancellation is being treated as an acquisition"

    assert not classify(
        "def unrelated(order):\n    order.save()"
    ), "a function that never transitions is being treated as a delivery path"


def test_a_status_whitelist_is_what_exempts_a_variable_transition():
    """`vendor_management_service.update_order_status` passes a variable, and is
    exempt only because its `valid_statuses` list excludes `delivered`.

    That exemption is derived from the code rather than asserted about it: add
    `delivered` to that list and the guard immediately starts demanding the hook.
    This test is here so the mechanism cannot rot into an unconditional pass.
    """
    source = _source("services/vendor_management_service.py")
    tree = ast.parse(source)
    function = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "update_order_status"
        ),
        None,
    )
    assert function is not None, "update_order_status has moved; update this test"
    assert _cannot_deliver(function), (
        "the vendor status whitelist no longer proves this path cannot deliver"
    )

    # And the mechanism must actually discriminate: a function with no whitelist
    # must not be exempt.
    bare = ast.parse("def f(order, status):\n    apply_status_transition(order, status)").body[0]
    assert not _cannot_deliver(bare), "_cannot_deliver exempts a function that proves nothing"


def test_the_acquisition_write_cannot_fail_a_delivery():
    """The rider is at the door and the money is moving. A growth figure is not
    worth failing that over, and `reconcile` exists precisely so it does not have
    to be."""
    source = _code(_source("services/customer_cohort_service.py"))
    tree = ast.parse(source)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "record_acquisition"
    )
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
        "record_acquisition can raise, which would fail the delivery that called it"
    )


# ── The sweep ─────────────────────────────────────────────────────────────


def test_the_reconciliation_is_a_set_operation_not_a_walk():
    """One round trip per customer is fifty thousand round trips at target scale.

    The first version of `reconcile` did exactly that and `test_query_shape.py`
    refused it. Kept here as well because that guard covers request paths, and
    this is the reason the rule matters for a sweep too.
    """
    source = _code(_source("services/customer_cohort_service.py"))
    tree = ast.parse(source)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "reconcile"
    )
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.While)):
            inner = ast.unparse(node)
            assert "session.execute" not in inner, (
                "reconcile issues a query inside a loop; derive and repair in one statement"
            )


def test_the_reconciliation_is_scheduled_and_reports_what_it_changed():
    """A sweep nobody runs is a comment, and one that repairs silently hides the
    defect it is repairing: steady drift means a delivery path is not calling the
    hook, which is a code defect nothing else would report."""
    worker = _without_comments(_source("worker.py"))
    assert "reconcile_customer_cohorts_task" in worker
    functions = worker[worker.find("functions = ") :]
    assert "reconcile_customer_cohorts_task" in functions, (
        "the task exists but is not registered with ARQ, so nothing can enqueue it"
    )

    cron = _without_comments(_source("routes/cron_routes.py"))
    assert "reconcile-customer-cohorts" in cron, "no cron slug points at the reconciliation"

    service = _without_comments(_source("services/customer_cohort_service.py"))
    tree = ast.parse(service)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "reconcile"
    )
    body = ast.unparse(fn)
    assert "_escalate" in body, "reconcile repairs drift without reporting it"
    assert "return" in body and "corrected" in body


def test_drift_escalates_instead_of_only_being_logged():
    """A log line in a nightly cron is not an alert.

    It goes to a stream nobody tails, on a schedule nobody watches, about a
    condition whose whole significance is that it *repeats* — so the only person
    who would notice is one already looking. The counts go to Sentry, tagged, so
    they can be alerted on and trended.

    And the reporting cannot break the repair: the sweep's job is to fix the
    table, and failing that because Sentry was unreachable would trade a
    reporting problem for a data one.
    """
    source = _without_comments(_source("services/customer_cohort_service.py"))
    tree = ast.parse(source)
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_escalate"),
        None,
    )
    assert fn is not None, "_escalate has moved; drift may no longer reach anybody"

    body = ast.unparse(fn)
    assert "capture_message" in body, "drift is not reported anywhere a person will see it"
    assert "set_tag" in body, "drift is reported untagged, so it cannot be alerted on or trended"
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
        "_escalate can raise, which would fail the sweep that was doing the repair"
    )


# ── Non-vacuity ───────────────────────────────────────────────────────────


def test_the_comment_blanking_does_not_hide_real_code():
    sample = 'x = 1  # func.min(Order.created_at)\ny = "on_conflict_do_update"\nz = func.min(Order.created_at)'
    blanked = _code(sample)
    assert "func.min(Order.created_at)" in blanked.split("\n")[2]
    assert "func.min" not in blanked.split("\n")[0]
    assert "on_conflict" not in blanked.split("\n")[1]

    multiline = '"""Explaining\nfunc.min(Order.created_at) here.\n"""\nkeep = 1'
    assert "func.min" not in _code(multiline)
    assert "keep = 1" in _code(multiline)
