"""A control with nothing but an icon in it still has to say what it does.

React Native builds an accessible name out of a touchable's `<Text>` children,
so most of this platform's buttons announce themselves for free — "Accept",
"Withdraw", "Mark as Ready". The ones that do not are the icon-only controls,
and there were 52 across the three apps: every password-visibility toggle, every
sheet's close button, the send button on all three support threads, the stock
steppers and edit/withdraw buttons on the vendor's product list, the map's
recentre control, the photo-removal buttons on a rider's bottle rejection.

To a screen reader each was announced as "button", with nothing else. On the
vendor's product list that is five unlabelled buttons per row, repeated down the
screen — including the one that withdraws a product from the catalogue.

The admin console has enforced the same rule from the other direction since its
icon-only tab bar shipped, quoted in `drop-admin/CLAUDE.md`: *icons only by
request … each carries `aria-label` plus an `sr-only` short label, so a screen
reader announces the word the label would have shown.* This is that rule for the
three apps.

`PressableScale` already defaults `accessibilityRole="button"` in all three, so
a label is the only thing missing there; a bare `TouchableOpacity` needs both.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

TOUCHABLES = (
    "PressableScale",
    "TouchableOpacity",
    "TouchableHighlight",
    "TouchableWithoutFeedback",
    "Pressable",
)

ICONS = (
    "Ionicons", "MaterialIcons", "MaterialCommunityIcons", "FontAwesome",
    "FontAwesome5", "FontAwesome6", "Feather", "AntDesign", "Entypo", "Octicons",
)


def _open_tag_end(source: str, start: int) -> int:
    """Index just past the `>` that closes the opening tag at `start`.

    It has to track braces and strings. `onPress={() => close()}` contains a
    `>`, and half the controls on the platform are written that way — a naive
    `source.find(">")` ends the tag inside the arrow function and reads the
    attributes off the end of it, which is how an early version of this check
    reported four *labelled* controls as unlabelled.
    """
    index, depth, quote = start, 0, None
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0 and char == ">":
            return index + 1
        index += 1
    return len(source)


def _element_end(source: str, tag: str, body_start: int) -> int:
    """Index of the matching `</Tag>`, honouring one tag nested in another."""
    depth, index = 1, body_start
    opening, closing = re.compile(rf"<{tag}\b"), re.compile(rf"</{tag}>")
    while index < len(source) and depth:
        nested, close = opening.search(source, index), closing.search(source, index)
        if not close:
            return len(source)
        if nested and nested.start() < close.start():
            depth += 1
            index = nested.end()
        else:
            depth -= 1
            index = close.end()
    return index


def unnamed_icon_controls(source: str, label: str) -> list[str]:
    """Touchables in `source` holding an icon, no text, and no label."""
    found: list[str] = []
    for tag in TOUCHABLES:
        for match in re.finditer(rf"<{tag}\b", source):
            head_end = _open_tag_end(source, match.start())
            head = source[match.start():head_end]
            body = (
                ""
                if head.rstrip().endswith("/>")
                else source[head_end:_element_end(source, tag, head_end)]
            )

            if "accessibilityLabel" in head:
                continue
            if not any(f"<{icon}" in body for icon in ICONS):
                continue
            # A `<Text>` child is an accessible name already, and `title=` /
            # `label=` are the same thing passed as a prop.
            if "<Text" in body or "title=" in head or "label=" in head:
                continue

            line = source[: match.start()].count("\n") + 1
            found.append(f"{label}:{line} <{tag}>")
    return found


def _screens(app: str) -> list[pathlib.Path]:
    base = ROOT / app
    return [
        path
        for directory in ("app", "components")
        if (base / directory).is_dir()
        for path in (base / directory).rglob("*.tsx")
        if "node_modules" not in path.parts
    ]


@pytest.mark.parametrize("app", APPS)
def test_every_icon_only_control_says_what_it_does(app):
    offenders: list[str] = []
    for path in sorted(_screens(app)):
        offenders += unnamed_icon_controls(
            path.read_text(errors="ignore"), str(path.relative_to(ROOT / app))
        )

    assert not offenders, (
        f"{app}: a control with only an icon in it and no accessibilityLabel — "
        'a screen reader announces each of these as "button" and nothing '
        "else:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("app", APPS)
def test_the_shared_touchable_still_supplies_the_role(app):
    """Why the rule above asks for a label and not also a role.

    `PressableScale` defaults `accessibilityRole="button"`, so every control
    built on it is already announced as a button. If that default ever goes, a
    label alone stops being enough and this rule needs the role adding.
    """
    source = (ROOT / app / "components/ui/PressableScale.tsx").read_text()
    assert re.search(
        r"""accessibilityRole\s*=\s*['"]button['"]""", source
    ), f"{app}: PressableScale no longer defaults its accessibility role"


# ── The detector ──────────────────────────────────────────────────────────


def test_it_catches_an_unlabelled_icon_button():
    """The negative case. Without it this file passes by matching nothing."""
    caught = unnamed_icon_controls(
        '<PressableScale onPress={close}>\n'
        '  <Ionicons name="close" size={20} />\n'
        "</PressableScale>\n",
        "sample.tsx",
    )
    assert len(caught) == 1


def test_it_accepts_a_labelled_one():
    assert unnamed_icon_controls(
        '<PressableScale onPress={close} accessibilityLabel="Close">\n'
        '  <Ionicons name="close" size={20} />\n'
        "</PressableScale>\n",
        "sample.tsx",
    ) == []


def test_a_label_after_an_arrow_function_is_still_seen():
    """The bug this detector was written around.

    `() =>` puts a `>` inside the opening tag. A detector that stops there reads
    no attributes at all and reports every labelled control on the platform.
    """
    assert unnamed_icon_controls(
        '<PressableScale\n'
        '  onPress={() => setShown(!shown)}\n'
        '  accessibilityLabel={shown ? "Hide password" : "Show password"}\n'
        ">\n"
        '  <Ionicons name="eye" size={20} />\n'
        "</PressableScale>\n",
        "sample.tsx",
    ) == []


def test_a_control_with_words_in_it_needs_no_label():
    """An icon beside text is not an icon-only control — the text is the name,
    and a label would override it with something less specific."""
    assert unnamed_icon_controls(
        "<PressableScale onPress={submit}>\n"
        '  <Ionicons name="checkmark" size={20} />\n'
        "  <Text>Mark as Ready</Text>\n"
        "</PressableScale>\n",
        "sample.tsx",
    ) == []


def test_a_nested_touchable_does_not_swallow_the_outer_one():
    """`_element_end` counts depth. Reading to the first `</PressableScale>`
    would end the outer element early and miss whatever came after it."""
    caught = unnamed_icon_controls(
        "<PressableScale onPress={a}>\n"
        '  <PressableScale onPress={b} accessibilityLabel="Inner">\n'
        '    <Ionicons name="add" size={20} />\n'
        "  </PressableScale>\n"
        '  <Ionicons name="remove" size={20} />\n'
        "</PressableScale>\n",
        "sample.tsx",
    )
    assert len(caught) == 1 and caught[0].startswith("sample.tsx:1")
