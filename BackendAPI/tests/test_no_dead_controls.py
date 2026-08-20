"""A control that opens a panel has a panel to open.

`Profile.tsx` drives one `@gorhom/bottom-sheet` from a single state variable:
a row calls `setBottomSheetData("x")` and the sheet body renders whichever
`bottomSheetData === "x"` block matches. Five rows set a key. Only two keys —
`edit-profile` and `favourites` — had a body.

So **Privacy, Settings and Help each raised an empty sheet**. Nothing errored,
nothing logged, and `tsc` was happy because the state is typed `string`: the row
animated, the haptic fired, and the customer was left looking at an empty panel
on the screen where they go to change their password or ask for help. All three
destinations already existed and were reachable two taps away from Settings.

This is the same shape as a `<Stack.Screen>` with no file behind it, and the
same shape as the route table this repo already enforces — a name that one half
of the code writes and the other half never reads.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")


def _files(app: str) -> list[pathlib.Path]:
    base = ROOT / app / "app"
    return [p for p in base.rglob("*.tsx")] if base.is_dir() else []


@pytest.mark.parametrize("app", APPS)
def test_every_sheet_key_that_is_set_has_a_body(app):
    offenders = []
    for path in _files(app):
        src = path.read_text()
        if "setBottomSheetData" not in src:
            continue
        set_keys = set(re.findall(r'setBottomSheetData\(\s*["\']([\w-]+)["\']', src))
        rendered = set(re.findall(r'bottomSheetData\s*===\s*["\']([\w-]+)["\']', src))
        dead = sorted(set_keys - rendered)
        if dead:
            offenders.append(
                f"{path.relative_to(ROOT / app)}: opens the sheet as {dead} "
                f"but only renders {sorted(rendered)}"
            )

    assert not offenders, (
        f"{app}: these controls open a bottom sheet with nothing in it:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither render a body for the key or route the control at the screen "
        "that already does the job."
    )


def test_the_scanner_would_catch_the_shape_that_shipped():
    """Non-vacuity, against the exact code that was on Profile.

    Without this, renaming the state variable would make the check pass by
    matching nothing rather than by the defect being gone.
    """
    shipped = """
        onPress={() => { setBottomSheetData("privacy"); }}
        onPress={() => { setBottomSheetData("favourites"); }}
        {bottomSheetData === "favourites" && <Favourites />}
    """
    set_keys = set(re.findall(r'setBottomSheetData\(\s*["\']([\w-]+)["\']', shipped))
    rendered = set(re.findall(r'bottomSheetData\s*===\s*["\']([\w-]+)["\']', shipped))
    assert sorted(set_keys - rendered) == ["privacy"], (
        "the scanner no longer recognises a set-but-never-rendered sheet key"
    )
