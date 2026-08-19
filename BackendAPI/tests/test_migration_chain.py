"""The revision graph has one head, and the gated drop is it.

Two properties, both of which the repository depends on and neither of which
anything checked.

**One head.** `alembic upgrade head` and `scripts/bootstrap_database.py` (which
stamps at `head` by default) both raise outright on a graph with two. A second
head appears the moment somebody writes a revision parented on whatever was
current when they branched rather than on the real head — which has happened
here before: `f9a3b7c2d1e0` forked off `a1b2c3d4e5f6` and needed the mergepoint
`3f40437790a9` to bring it back. That merge is why the graph is single-headed
today, and nothing would say so if the next one were missed.

**The gate is terminal.** `e6b2c8d40f17` drops the legacy single-staff columns
and refuses to run without `ALLOW_STAFF_COLUMN_DROP=true`. A revision parented
on it could only ever run on a deploy that had already accepted that drop, so
new work goes *before* it and the gate is re-parented onto the new work. This
test is what makes that rule enforceable rather than remembered: it fails both
if a second head appears and if the head stops being the gated revision.

It reads the files, not a database — there is no database in this suite.
"""
from __future__ import annotations

import pathlib
import re

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"

#: The revision that must stay last. Named here rather than discovered, because
#: "the head is whatever the head is" would assert nothing at all.
GATED_REVISION = "e6b2c8d40f17"

_REVISION = re.compile(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$", re.M)


def _parents(raw: str) -> list[str]:
    """Every parent named on a `down_revision` line.

    A merge revision carries a **tuple** of them. Reading only the first is how
    a graph with a mergepoint in it reads as forked when it is not — the exact
    mistake that made this file necessary.
    """
    return re.findall(r"['\"]([0-9a-zA-Z_]+)['\"]", raw)


def _graph() -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        rev = _REVISION.search(source)
        down = _DOWN.search(source)
        if not rev:
            continue
        graph[rev.group(1)] = _parents(down.group(1)) if down else []
    return graph


def test_the_scan_finds_the_revisions() -> None:
    """Non-vacuity: an empty graph satisfies every assertion below."""
    graph = _graph()
    assert len(graph) > 50, f"only {len(graph)} revisions parsed — the scan is broken"
    assert GATED_REVISION in graph


def test_the_chain_has_exactly_one_head() -> None:
    graph = _graph()
    referenced = {parent for parents in graph.values() for parent in parents}
    heads = sorted(rev for rev in graph if rev not in referenced)
    assert heads == [GATED_REVISION], (
        f"expected exactly one head ({GATED_REVISION}), found {heads}.\n"
        "A new revision must be parented on the current head. If two branches "
        "genuinely diverged, `alembic merge` brings them back."
    )


def test_nothing_is_parented_on_the_gated_drop() -> None:
    """The rule the head check cannot express on its own.

    A revision after the gate would still leave one head — it would just be the
    wrong one, and it could only ever run on a deploy that had already accepted
    the column drop.
    """
    graph = _graph()
    offenders = [rev for rev, parents in graph.items() if GATED_REVISION in parents]
    assert not offenders, (
        f"{offenders} are parented on the gated drop {GATED_REVISION}. "
        "New work goes before it; re-parent the gate onto the new revision."
    )


def test_every_named_parent_exists() -> None:
    """A typo'd `down_revision` is a chain alembic cannot resolve at all."""
    graph = _graph()
    missing = sorted(
        f"{rev} -> {parent}"
        for rev, parents in graph.items()
        for parent in parents
        if parent not in graph
    )
    assert not missing, "down_revision names a revision that does not exist:\n  " + "\n  ".join(missing)


def test_there_is_exactly_one_base() -> None:
    """Two bases is two disconnected histories, and `upgrade head` runs one."""
    graph = _graph()
    bases = sorted(rev for rev, parents in graph.items() if not parents)
    assert len(bases) == 1, f"expected one base, found {bases}"
