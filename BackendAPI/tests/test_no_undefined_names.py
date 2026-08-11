"""No module references a name it never defined or imported.

This catches the class of defect that is invisible until a user reaches the
line. `order_service.cancel_customer_order` called `func.count(...)` while
`func` was never imported — `from sqlalchemy import select, and_, update`. The
module imported fine, every test passed, and the branch was live: the free
cancellation allowance defaults to **1**, so `allowance > 0` is true on a
default deployment, and a customer cancelling an order that had reached
`preparing`, `ready` or `picked_up` got a `NameError` and a 500 instead of a
cancellation.

Nothing else finds it. It is not a syntax error, not an import error, and no
test exercised that branch — the only signal was a user failing to cancel an
order they were entitled to cancel.

Scoped to the packages that serve requests. Deliberately not `alembic/`, whose
migration modules are executed by Alembic with its own globals, nor `tests/`.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: Everything that runs while answering a request or a job.
CHECKED = ("routes", "services", "jobs", "utils", "schemas", "dependencies", "core", "db")


def _pyflakes(paths: list[str]) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", *paths],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    if "No module named" in result.stderr:
        pytest.skip("pyflakes is not installed in this environment")
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_no_module_uses_an_undefined_name():
    """The one that bit: a name used and never bound."""
    targets = [d for d in CHECKED if (BACKEND / d).is_dir()] + ["main.py", "worker.py"]
    offenders = [
        line for line in _pyflakes(targets)
        if "undefined name" in line or "local variable" in line and "referenced before" in line
    ]

    assert not offenders, (
        "names used but never defined or imported — each one is a NameError the "
        "moment that line is reached:\n  " + "\n  ".join(offenders)
    )


def test_no_module_shadows_an_import_it_already_has():
    """A second `from x import y` inside a function is a smell, not a fault —
    but re-importing a name the module already has at the top means one of the
    two is stale, and which one wins depends on where you are in the file."""
    targets = [d for d in CHECKED if (BACKEND / d).is_dir()] + ["main.py", "worker.py"]
    offenders = [line for line in _pyflakes(targets) if "redefinition of unused" in line]

    assert not offenders, (
        "a name is imported twice in one module; delete the inner import:\n  "
        + "\n  ".join(offenders)
    )


def test_no_function_computes_a_value_it_never_uses():
    """An assigned-and-unused local is usually a line that was meant to be used.

    `payout_service` computed `available_balance` and then checked something
    else; `deliverer_service` built two reason lists and consulted neither.
    Each is either dead work or a check that quietly stopped happening.
    """
    targets = [d for d in CHECKED if (BACKEND / d).is_dir()] + ["main.py", "worker.py"]
    offenders = [
        line for line in _pyflakes(targets)
        if "assigned to but never used" in line
    ]

    assert not offenders, (
        "locals computed and never read — dead work, or a check that stopped "
        "being made:\n  " + "\n  ".join(offenders)
    )
