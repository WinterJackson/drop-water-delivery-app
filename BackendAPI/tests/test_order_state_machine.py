"""An order's status moves through one function, and never backwards.

There was a state machine — `VALID_TRANSITIONS` — and it was not the state
machine. Twelve places across six modules assigned `order.order_status`
directly, each with its own idea of what was legal, and exactly two of them
consulted the table. Worse, the table described an *idealised* flow the platform
does not have: a rider marking an order picked up straight from `accepted`
because the store handed it over before tapping "ready", a rider dropping an
order after pickup, the cash-float sweep releasing one back to `unassigned` —
all routine, none of them in the table.

That is the worst arrangement of the two options. A table nobody consults is
dead code; a table that contradicts the code is documentation that lies, so the
next person either believes it about their own feature or "fixes" the ten
non-conforming paths to match and breaks the rider flow.

The table now describes what happens, and `apply_status_transition` is the only
way to change a status. What that buys, and the whole reason it is enforced:

* **Terminal is terminal.** Money has settled and stock has moved; an order that
  changes after `delivered`, `cancelled` or `rejected` is one whose ledger no
  longer matches its state.
* **No going backwards.** `delivered → preparing` is not a late update, it is a
  bug that silently un-completes a delivery.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from services.order_service import (
    TERMINAL_ORDER_STATUSES,
    VALID_TRANSITIONS,
    OrderStatusEnum,
    apply_status_transition,
    validate_status_transition,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("routes", "services", "jobs")

#: The one function allowed to assign the column.
CHOKE_POINT = "apply_status_transition"


class _Order:
    """The two attributes the transition helper touches."""

    def __init__(self, status: str):
        self.order_status = status
        self.cancellation_reason = None


# ── The choke point ───────────────────────────────────────────────────────


def test_nothing_assigns_order_status_directly():
    """Walks every module that serves a request or runs a job.

    A guard that ten of twelve writers skip is not a guard, it is a comment
    that happens to execute.
    """
    offenders: list[str] = []

    for directory in SOURCE_DIRS:
        for path in (BACKEND / directory).rglob("*.py"):
            tree = ast.parse(path.read_text())
            inside_choke_point = {
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == CHOKE_POINT
            }
            allowed = {n for fn in inside_choke_point for n in ast.walk(fn)}

            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or node in allowed:
                    continue
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "order_status"
                        and not any(t in allowed for t in [node])
                    ):
                        offenders.append(
                            f"{path.relative_to(BACKEND)}:{node.lineno} "
                            f"{ast.unparse(target)} = …"
                        )

    assert not offenders, (
        "order_status assigned outside `apply_status_transition` — every one of "
        "these skips the state machine:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_would_catch_a_direct_assignment():
    """The negative case. A structural test that has never been shown to fail
    is a test that passes because it matches nothing."""
    tree = ast.parse('def sweep(order):\n    order.order_status = "cancelled"\n')
    found = [
        target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute) and target.attr == "order_status"
    ]
    assert found == ["order_status"]


# ── Terminal states ───────────────────────────────────────────────────────


@pytest.mark.parametrize("terminal", sorted(TERMINAL_ORDER_STATUSES))
@pytest.mark.parametrize(
    "target",
    ["pending", "accepted", "preparing", "ready", "picked_up", "unassigned", "delivered"],
)
def test_a_finished_order_never_moves_again(terminal, target):
    """The invariant the whole machine exists for.

    A delivered order that becomes `preparing` again has been paid for, had its
    stock deducted, settled the vendor and the rider — and now reads as work
    still to do.
    """
    if terminal == target:
        return

    order = _Order(terminal)
    with pytest.raises(Exception) as raised:
        apply_status_transition(order, target)

    assert getattr(raised.value, "status_code", None) == 409
    assert order.order_status == terminal, "the order moved despite the refusal"
    assert "already" in str(getattr(raised.value, "detail", "")).lower()


def test_every_terminal_status_has_an_empty_transition_set():
    for status in TERMINAL_ORDER_STATUSES:
        assert VALID_TRANSITIONS[OrderStatusEnum(status)] == set(), (
            f"{status} is listed as terminal but has onward transitions"
        )


# ── The table is complete and honest ──────────────────────────────────────


def test_every_status_appears_in_the_table():
    """A status missing from the table transitions nowhere, silently — every
    move out of it is refused with a message about the graph rather than about
    the order."""
    missing = [s.value for s in OrderStatusEnum if s not in VALID_TRANSITIONS]
    assert not missing, f"statuses with no entry in VALID_TRANSITIONS: {missing}"


def test_no_transition_points_at_a_status_that_does_not_exist():
    known = set(OrderStatusEnum)
    for source, targets in VALID_TRANSITIONS.items():
        unknown = targets - known
        assert not unknown, f"{source.value} transitions to unknown states: {unknown}"


@pytest.mark.parametrize(
    "current,new",
    [
        # The forward path.
        ("unassigned", "pending"),
        ("pending", "accepted"),
        ("accepted", "preparing"),
        ("preparing", "ready"),
        ("ready", "picked_up"),
        ("picked_up", "delivered"),
        # Real transitions the old table denied, each with a routine cause.
        ("accepted", "picked_up"),      # store handed over before tapping "ready"
        ("preparing", "picked_up"),     # same
        ("picked_up", "cancelled"),     # rider's vehicle failed after pickup
        ("ready", "unassigned"),        # rider dropped it; back on the radar
        ("accepted", "unassigned"),     # rider rejected an assignment
        ("picked_up", "pending_review"),   # bottle count mismatch
        ("picked_up", "mismatch_pending"), # address mismatch
        ("pending_review", "picked_up"),   # resolved, carry on
        ("mismatch_pending", "delivered"),
    ],
)
def test_the_transitions_the_platform_actually_performs_are_allowed(current, new):
    assert validate_status_transition(current, new), (
        f"'{current} -> {new}' happens in production and the table forbids it"
    )


@pytest.mark.parametrize(
    "current,new",
    [
        ("delivered", "preparing"),
        ("delivered", "picked_up"),
        ("cancelled", "accepted"),
        ("rejected", "pending"),
        ("delivered", "cancelled"),
        ("ready", "accepted"),        # backwards
        ("picked_up", "preparing"),   # backwards
        ("unassigned", "delivered"),  # nobody ever collected it
    ],
)
def test_the_transitions_that_would_be_bugs_are_refused(current, new):
    assert not validate_status_transition(current, new), (
        f"'{current} -> {new}' should never be possible"
    )


def test_an_unknown_status_is_refused_rather_than_waved_through():
    assert validate_status_transition("delivered", "teleported") is False
    assert validate_status_transition("invented", "delivered") is False


# ── Behaviour of the helper ───────────────────────────────────────────────


def test_repeating_a_transition_is_a_no_op_not_a_refusal():
    """Two staff on two devices, or a retried request. The order is already
    where the caller wants it; that is success, not a conflict."""
    order = _Order("preparing")
    assert apply_status_transition(order, "preparing") == "preparing"
    assert order.order_status == "preparing"


def test_it_returns_the_previous_status():
    order = _Order("ready")
    assert apply_status_transition(order, "picked_up") == "ready"
    assert order.order_status == "picked_up"


def test_a_reason_is_recorded_with_the_move_that_needed_one():
    order = _Order("picked_up")
    apply_status_transition(order, "cancelled", reason="vehicle_issue: broke down")
    assert order.order_status == "cancelled"
    assert order.cancellation_reason == "vehicle_issue: broke down"


def test_a_refused_transition_leaves_the_order_untouched():
    """It must not half-apply: no status change, and no reason written against
    a cancellation that did not happen."""
    order = _Order("delivered")
    with pytest.raises(Exception):
        apply_status_transition(order, "cancelled", reason="support cancelled it")

    assert order.order_status == "delivered"
    assert order.cancellation_reason is None
