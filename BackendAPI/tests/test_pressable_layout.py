"""`PressableScale` may not impose a layout its caller cannot override.

It wraps every tappable surface in all three apps — roughly 1,100 of them — and
merges a base style **ahead of** the caller's `className`. In React Native a
style array is last-wins, and NativeWind's class styles land before that base,
so anything written into the base is not a default: it is an override the caller
cannot see, cannot beat, and gets no warning about.

The base used to read:

    { minHeight: 44, minWidth: 44, justifyContent: 'center' }

which looks like "centre the child inside the 44px touch target", and is exactly
that in the default column direction. But `justifyContent` follows
`flexDirection`, so the moment a caller passes `flex-row` it becomes the
*horizontal* axis and silently discards their own `justify-*`:

* All nine rows of the customer's Settings screen — and `Privacy & Security`,
  and the vendor's and rider's dashboard cards, ten `justify-between` rows in
  all — rendered as a centred cluster with the chevron glued to the label
  instead of pinned to the right edge.
* `Cart.tsx`'s checkout backdrop asks for `justify-end`, which is what makes a
  bottom sheet sit on the bottom. Forced to `center`, the whole checkout sheet
  floated in the middle of the screen with dead space beneath it — on the screen
  where the customer pays.

The rule is narrow on purpose. A caller who states a `justify-*` keeps it; a
caller who states nothing keeps the centring they have always had, so the 97
elements asking for `justify-center` are untouched. An explicit `style` prop
already won, because it merges after the base.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

#: Properties whose meaning depends on the caller's flex direction, or which
#: place the caller's children. None of these may be imposed unconditionally.
LAYOUT_PROPERTIES = (
    "justifyContent",
    "alignItems",
    "alignContent",
    "flexDirection",
    "flexWrap",
)


def _source(app: str) -> str:
    path = ROOT / app / "components" / "ui" / "PressableScale.tsx"
    assert path.exists(), f"{app} has no PressableScale"
    return path.read_text()


def _style_array(source: str) -> str:
    """The `style={[ ... ]}` array passed to the underlying pressable."""
    match = re.search(r"style=\{\[(.*?)\]\}", source, re.S)
    assert match, "PressableScale no longer passes a style array — re-read this guard"
    return match.group(1)


def _unconditional_objects(style_array: str) -> list[str]:
    """Object literals in the array that are not behind a conditional.

    A ternary is how a *default* is expressed here: applied only when the caller
    has not spoken. Anything else in the array lands on every render.
    """
    out, depth, current = [], 0, []
    for char in style_array:
        if char == "," and depth == 0:
            out.append("".join(current))
            current = []
            continue
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        current.append(char)
    out.append("".join(current))
    return [e.strip() for e in out if e.strip() and "?" not in e]


@pytest.mark.parametrize("app", APPS)
def test_the_base_style_imposes_no_layout(app):
    """The touch target is a box. A box is not a layout."""
    source = _source(app)
    offenders = []
    for element in _unconditional_objects(_style_array(source)):
        # Resolve a named constant to its declaration before judging it.
        body = element
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", element):
            declared = re.search(
                rf"const\s+{re.escape(element)}\s*=\s*(\{{.*?\}})", source, re.S
            )
            assert declared, f"{app}: {element} is passed to style but never declared"
            body = declared.group(1)
        for prop in LAYOUT_PROPERTIES:
            if prop in body:
                offenders.append(f"{element.splitlines()[0][:60]} sets {prop}")

    assert not offenders, (
        f"{app}/components/ui/PressableScale.tsx imposes layout on every caller:\n  "
        + "\n  ".join(offenders)
        + "\n\nThis base merges ahead of the caller's className and wins, so a "
        "layout property here silently overrides every `justify-*` and "
        "`flex-row` the app passes. Apply it only when the caller has not "
        "stated one."
    )


@pytest.mark.parametrize("app", APPS)
def test_centring_survives_as_a_default_for_callers_who_ask_for_nothing(app):
    """Removing the override must not silently remove the centring too.

    97 of the ~109 `PressableScale`s that mention a `justify-` ask for
    `justify-center`, and far more pass no `justify-` at all and rely on the
    default to centre an icon inside the 44px minimum. Deleting the property
    outright would top-align every one of them.
    """
    source = _source(app)
    assert re.search(r"justifyContent:\s*'center'", source), (
        f"{app}: PressableScale no longer centres by default. Callers that pass "
        "no justification rely on it to centre their content inside the 44px "
        "touch-target minimum."
    )
    assert re.search(r"className.*\?\s*null\s*:|null\s*:.*justifyContent", source, re.S), (
        f"{app}: the centring default is no longer conditional on what the "
        "caller asked for."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_touch_target_minimum_is_still_enforced(app):
    """The reason the base style exists at all. 44pt is the accessibility floor."""
    source = _source(app)
    assert "minHeight: 44" in source and "minWidth: 44" in source, (
        f"{app}: PressableScale no longer guarantees a 44pt touch target."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_scanner_would_catch_the_defect_it_was_written_for(app):
    """Non-vacuity, against the exact shape that shipped.

    Without this, a rewrite that stops matching the style array passes by
    finding nothing rather than by being correct.
    """
    shipped = "{ minHeight: 44, minWidth: 44, justifyContent: 'center' }, // Minimum touch target"
    found = [
        prop
        for element in _unconditional_objects(shipped)
        for prop in LAYOUT_PROPERTIES
        if prop in element
    ]
    assert found == ["justifyContent"], (
        "the scanner no longer recognises the original defect; it would now pass "
        "on the very code it was written to reject"
    )
