"""No app states the service radius.

The radius is a settings row — `retail_max_distance_km` and
`wholesale_max_distance_km` — and it is *all* of what discovery searches, what
checkout enforces, what the rider search covers and the circle each app draws.
An app that writes the figure into copy is stating a number it cannot know is
current, and the sentence becomes false the moment an administrator moves the
setting.

It has happened twice already. The rider app said "within a 2KM radius", which
is why `operation_radius_km` is now served on the rider profile. The vendor's
map drew a circle from a vendor-writable column no dispatch path read. And the
customer app's location prompt — the screen whose entire job is to explain why
the address matters — said "Drop delivers within 2.5 km for refills and 15 km
for wholesale".

Comment lines are skipped on purpose: four of them document exactly these past
defects and quote the figures while doing so, and a guard that fired on the
notes explaining the bug would be worse than no guard.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
APPS = ("drop-customer-app", "drop-vendor-app", "drop-rider-app")

#: A distance figure in kilometres: "2.5 km", "15km", "2 KM".
_DISTANCE = re.compile(r"\d+(\.\d+)?\s*km\b", re.IGNORECASE)

#: ...but only where the line is *about* delivery coverage. A rider filtering
#: their own radar to "< 5KM" is choosing how far they want to ride, which is
#: neither the platform's radius nor a claim about it, and 5 is not either
#: configured figure. Requiring the delivery vocabulary keeps the guard on the
#: defect instead of on every number with a unit after it.
_ABOUT_COVERAGE = re.compile(
    r"deliver|radius|serve|reach|wholesale|refill|coverage|within",
    re.IGNORECASE,
)


def _sources(app: str):
    for folder in ("app", "components"):
        base = ROOT / app / folder
        if base.exists():
            yield from base.rglob("*.tsx")


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("//", "*", "/*", "{/*"))


@pytest.mark.parametrize("app", APPS)
def test_no_app_writes_the_service_radius_into_copy(app):
    offences = []
    for path in _sources(app):
        inside_block_comment = False
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if inside_block_comment:
                if "*/" in stripped:
                    inside_block_comment = False
                continue
            if stripped.startswith(("/*", "{/*")) and "*/" not in stripped:
                inside_block_comment = True
                continue
            if _is_comment(line):
                continue
            if _DISTANCE.search(line) and _ABOUT_COVERAGE.search(line):
                offences.append(f"{path.relative_to(ROOT)}:{number}: {stripped[:100]}")
    assert not offences, (
        "The service radius is a settings row and no app states it. Read it "
        "from the server, or write copy that does not quote a figure:\n  "
        + "\n  ".join(offences)
    )


def test_the_guard_still_catches_the_sentence_it_was_written_for():
    """Non-vacuity, against the exact copy that shipped."""
    shipped = "Drop delivers within 2.5 km for refills and 15 km for wholesale"
    assert _DISTANCE.search(shipped) and _ABOUT_COVERAGE.search(shipped)


def test_the_guard_leaves_a_riders_own_filter_alone():
    """It must not fire on the rider radar filter, which is not a claim."""
    label = 'type FilterType = "ALL" | "< 5KM" | "HIGH PAYOUT";'
    assert _DISTANCE.search(label)
    assert not _ABOUT_COVERAGE.search(label)
