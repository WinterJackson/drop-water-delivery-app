"""Nothing renders underneath the floating tab bar.

Each app draws its navigation as an absolutely-positioned pill in
`app/(screens)/_layout.tsx`. It is not a `Stack.Screen`, it is not in the layout
flow, and it therefore reserves no space at all: every screen in that group
scrolls *underneath* it unless the screen leaves room. Nothing warns you when
one forgets, because the overlap only appears once there is enough data to reach
the bottom of the list — which on a fresh account, or a seeded dev database, is
usually never.

Seventy screens each carried their own guess, and seven different values were in
use: `120`, `100`, `60`, `40`, `24`, `120 + insets.bottom + 16`, and nothing at
all. The small ones clipped real content — the last wallet transaction in all
three apps sat behind the bar with no way to scroll it clear, and the customer's
live-tracking sheet had an order row cut in half by it.

`constants/layout.ts` holds the bar's geometry once and `useTabBarClearance()`
derives the padding from it, including `insets.bottom`, which is the one term a
screen cannot hardcode.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

SCROLLERS = (
    "ScrollView", "FlatList", "FlashList", "SectionList",
    "KeyboardAwareScrollView", "Animated.ScrollView", "Animated.FlatList",
)
TAG = re.compile(r"<(" + "|".join(s.replace(".", r"\.") for s in SCROLLERS) + r")\b")


def _screens(app: str) -> list[pathlib.Path]:
    base = ROOT / app / "app" / "(screens)"
    return [p for p in base.rglob("*.tsx") if p.name != "_layout.tsx"]


def _opening_tag(src: str, start: int) -> str:
    """The opening tag at `start`, brace/quote/comment aware.

    JSX props routinely contain nested elements, template literals and prose
    with apostrophes, so a naive scan to the first `>` finds the wrong one.
    """
    name = re.match(r"<[\w.]+", src[start:])
    i = start + (name.end() if name else 1)
    if src[i:i + 1] == "<":  # explicit generic: <SectionList<{...}> ...>
        depth = 0
        while i < len(src):
            if src[i] == "<":
                depth += 1
            elif src[i] == ">":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    depth = 0
    while i < len(src):
        c = src[i]
        if c == "/" and src[i + 1:i + 2] == "/":
            i = src.find("\n", i)
            if i < 0:
                break
            continue
        if c == "/" and src[i + 1:i + 2] == "*":
            i = src.find("*/", i) + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c in "\"`":
            q, i = c, i + 1
            while i < len(src) and src[i] != q:
                i += 2 if src[i] == "\\" else 1
        elif c == ">" and depth == 0:
            return src[start:i + 1]
        i += 1
    return src[start:start + 400]


def _is_jsx(src: str, at: int) -> bool:
    """`useRef<ScrollView>(null)` is a type argument, not an element."""
    before = src[:at].rstrip()
    return not before or before[-1] in "({[,=>&|?:;\n}"


@pytest.mark.parametrize("app", APPS)
def test_every_vertical_scroller_clears_the_tab_bar(app):
    offenders = []
    for path in _screens(app):
        src = path.read_text()
        for m in TAG.finditer(src):
            if not _is_jsx(src, m.start()):
                continue
            tag = _opening_tag(src, m.start())
            # A horizontal scroller has no bottom edge to protect.
            if re.search(r"\bhorizontal\b(?!\s*=\s*\{?\s*false)", tag):
                continue
            if "tabBarClearance" in tag:
                continue
            # `contentContainerStyle={someStyle}` — resolve the identifier.
            ref = re.search(r"contentContainerStyle=\{(\w+)\}", tag)
            if ref:
                decl = re.search(
                    rf"const\s+{re.escape(ref.group(1))}\s*=(.*?)(?:\n\s*(?:const|function|return)\b)",
                    src, re.S,
                )
                if decl and "tabBarClearance" in decl.group(1):
                    continue
            # An ancestor may carry the clearance instead — a fixed-height sheet
            # has to shorten its *container*, because padding a scroller's
            # content only extends how far it scrolls and still lets rows render
            # under the bar at rest. Those say so, in one greppable line.
            preceding = src[max(0, m.start() - 400):m.start()]
            if "tab-bar-clearance:" in preceding:
                continue
            line = src[:m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT / app)}:{line} <{m.group(1)}>")

    assert not offenders, (
        f"{app}: these scrollers do not reserve room for the floating tab bar, so "
        "their last rows render underneath it:\n  "
        + "\n  ".join(offenders)
        + "\n\nGive each `contentContainerStyle={{ paddingBottom: tabBarClearance }}` "
        "from `useTabBarClearance()` in `constants/layout.ts`."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_declared_geometry_matches_the_bar_it_describes(app):
    """The constant is only useful while it still describes the real bar.

    `constants/layout.ts` cannot see `_layout.tsx`, so a redesign that changes
    the pill's height or offset would leave every screen padding for the old one
    — under-padding again, silently, everywhere at once.
    """
    layout = (ROOT / app / "app" / "(screens)" / "_layout.tsx").read_text()
    constants = (ROOT / app / "constants" / "layout.ts").read_text()

    bar_height = re.search(r"h-\[(\d+)px\]", layout)
    assert bar_height, f"{app}: could not find the tab bar's height in _layout.tsx"
    declared_height = re.search(r"TAB_BAR_HEIGHT\s*=\s*(\d+)", constants)
    assert declared_height, f"{app}: constants/layout.ts declares no TAB_BAR_HEIGHT"
    assert bar_height.group(1) == declared_height.group(1), (
        f"{app}: the tab bar is {bar_height.group(1)}px tall but constants/layout.ts "
        f"says {declared_height.group(1)}px. Every screen is padding for the wrong bar."
    )

    offset = re.search(r"bottom:\s*insets\.bottom\s*\+\s*(\d+)", layout)
    assert offset, f"{app}: the tab bar no longer sits at `insets.bottom + n`"
    declared_offset = re.search(r"TAB_BAR_OFFSET\s*=\s*(\d+)", constants)
    assert declared_offset, f"{app}: constants/layout.ts declares no TAB_BAR_OFFSET"
    assert offset.group(1) == declared_offset.group(1), (
        f"{app}: the bar sits {offset.group(1)}px above the safe area but "
        f"constants/layout.ts says {declared_offset.group(1)}px."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_clearance_accounts_for_the_safe_area(app):
    """`insets.bottom` is the term a screen cannot hardcode.

    It is the reason a flat `120` was right on one handset and too small on the
    next, and it is why this is a hook rather than a constant.
    """
    constants = (ROOT / app / "constants" / "layout.ts").read_text()
    body = re.search(r"export function useTabBarClearance.*", constants, re.S)
    assert body, f"{app}: constants/layout.ts exports no useTabBarClearance"
    assert "insets.bottom" in body.group(0), (
        f"{app}: useTabBarClearance ignores the safe-area inset, so the padding is "
        "wrong by the height of the gesture bar on every device that has one."
    )
