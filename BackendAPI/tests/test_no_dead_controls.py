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


# ---------------------------------------------------------------------------
# A declared route is a route something navigates to.
# ---------------------------------------------------------------------------


def _screen_sources(app: str) -> dict[pathlib.Path, str]:
    base = ROOT / app
    out: dict[pathlib.Path, str] = {}
    for sub in ("app", "components", "hooks"):
        d = base / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*.ts*"):
            if "__tests__" in p.parts:
                continue
            out[p] = p.read_text()
    return out


@pytest.mark.parametrize("app", APPS)
def test_every_declared_screen_is_navigated_to(app):
    """A `<Stack.Screen>` nothing pushes is dead code that typechecks.

    `Profile.tsx` in the customer app became exactly that. It was reached from
    one place — the wallet pill on the home header — and when that pill was
    repointed at the wallet screen whose balance it shows, a fully built screen
    carrying the favourites list, the edit-profile sheet and the theme toggle
    stopped being reachable at all. Nothing failed: the route stayed declared,
    the file stayed compiled, `tsc` stayed happy, and the only symptom was that
    no sequence of taps could arrive there.

    That is the same shape as the route table this repo already enforces from
    the other end, and as `setBottomSheetData` above: a name one half of the
    code writes and the other half never reads.

    Dynamic segments are exempt — those are pushed with an interpolated id, and
    the route contract covers them. `index` is exempt because it is the group's
    own entry.
    """
    layout = ROOT / app / "app" / "(screens)" / "_layout.tsx"
    if not layout.is_file():
        pytest.skip(f"{app} has no (screens) layout")

    declared = re.findall(r'<Stack\.Screen\s+name="([^"]+)"', layout.read_text())
    assert declared, f"{app}: no screens declared — the pattern has stopped matching"

    sources = _screen_sources(app)
    orphans = []
    for name in declared:
        if "[" in name or name == "index":
            continue
        # A push may carry a query string (`/repeat-order?vendorId=…`) or a
        # further segment, so the name may be followed by a quote, a slash or
        # a question mark — but not by more word characters, or `Products`
        # would be satisfied by `manageProducts`.
        pattern = rf'["\'`][^"\'`]*/{re.escape(name)}(?=["\'`/?])'
        if not any(
            re.search(pattern, src)
            for path, src in sources.items()
            if f"(screens)/{name}" not in str(path).replace("\\", "/")
        ):
            orphans.append(name)

    assert not orphans, (
        f"{app}: these routes are declared and nothing navigates to them, so no "
        f"sequence of taps reaches them: {orphans}"
    )
