"""No route group redirects into itself, and no redirect is unconditional.

**What broke.** Sign-in worked, and the app then showed "Something went wrong"
— React's "Maximum update depth exceeded", caught by `ErrorBoundary` — with the
account, the token and the session all perfectly fine.

Two files, each reasonable alone:

    app/(Auth)/sign-in/screen.tsx   if (isSignedIn) return <Redirect href="/" />
    app/(Auth)/index.tsx            return <Redirect href="/(Auth)/sign-in/screen" />

Expo Router resolves a path **relative to the group the caller is already in**.
So `/` from inside `(Auth)` resolved to `app/(Auth)/index.tsx`, not to
`app/index.tsx` — and that file sent the caller straight back to the sign-in
screen. Sign-in → group index → sign-in, a two-node cycle that never left the
group, while `app/index.tsx` (which would have routed correctly, and did fire
once) was never reached again.

`<Redirect>` issues `router.replace()` from an effect on **every render**, not
once per mount, so neither side ever settled.

**What is *not* the rule.** A group index is not inherently wrong:
`app/index.tsx` and `app/(screens)/index.tsx` have always coexisted here, and
navigating to a group by name (`router.push("/(screens)")`) is a supported,
widely-used pattern. An earlier version of this file asserted both of those were
defects and was wrong — it failed on twenty legitimate call sites. The rule is
narrower and is about a *cycle*: a group's index must not forward into its own
group, because a screen in that group redirecting to `/` lands right back on it.

The fix deleted `(Auth)/index.tsx` in all three apps and pointed every caller at
the screen it actually wanted, so `/` from inside `(Auth)` now falls through to
`app/index.tsx`, which owns the decision and terminates.

**Guarding the redirect was not enough.** Making `(Auth)/index.tsx` return
`null` when signed in stopped the loop and produced a blank screen instead,
because that file was still what `/` resolved to. A dead end is a quieter bug
than a crash, not a smaller one.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

SKIP_PARTS = {"node_modules", ".expo", "android", "ios", "dist", "__tests__"}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
_GROUP_DIR = re.compile(r"^\((?P<name>.+)\)$")

_COMPONENT = re.compile(
    r"export\s+default\s+function\s+\w*\s*\([^)]*\)\s*\{(?P<body>.*)", re.S
)
_RETURNS_REDIRECT = re.compile(r"return\s*\(?\s*<Redirect\b")
_GUARD = re.compile(r"\bif\s*\(|\?\s*\(?\s*<Redirect\b|&&\s*\(?\s*<Redirect\b")
#: A `<Redirect>` destination — an *automatic* navigation, issued on render.
#:
#: Deliberately not `router.push` / `.replace` / `.navigate`. Those run from an
#: event handler, so they happen once when somebody taps something and cannot
#: cycle. Every screen in `(screens)` pushes to its siblings — that is the app's
#: own navigation, and an earlier version of this rule failed on eleven such
#: call sites while the actual defect was a redirect that fired on every render
#: with nobody touching the device.
_REDIRECT_TARGET = re.compile(r"""<Redirect\b[^>]*?href=\{?\s*['"](?P<to>/[^'"]*)['"]""")


def _strip_comments(src: str) -> str:
    """Comments are documentation, not code — these fixes quote the defective
    line in their own docstrings so the next reader knows what was wrong."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", src))


def _routes(app: str) -> list[pathlib.Path]:
    approot = REPO / app / "app"
    if not approot.is_dir():
        return []
    return sorted(
        p for p in approot.rglob("*.tsx")
        if not any(part in SKIP_PARTS for part in p.parts)
        and p.name != "_layout.tsx"
        and not p.name.startswith("+")
    )


def _group_of(route: pathlib.Path, approot: pathlib.Path) -> str | None:
    """The first `(group)` segment a route lives under, if any."""
    for part in route.relative_to(approot).parts:
        m = _GROUP_DIR.match(part)
        if m:
            return m.group("name")
    return None


def test_no_group_index_forwards_into_its_own_group():
    """The cycle that actually broke sign-in.

    `(Auth)/index.tsx` forwarding to `/(Auth)/sign-in/screen` is only half of
    it, but it is the half that can be seen from one file — and removing it
    breaks the cycle, because the sign-in screen's `/` then falls through to
    `app/index.tsx`.
    """
    offenders: list[str] = []

    for app in APPS:
        approot = REPO / app / "app"
        for route in _routes(app):
            if route.name != "index.tsx":
                continue
            group = _group_of(route, approot)
            if group is None:
                continue  # the root index is the one that *should* decide
            src = _strip_comments(route.read_text(encoding="utf-8", errors="replace"))
            for m in _REDIRECT_TARGET.finditer(src):
                if m.group("to").startswith(f"/({group})"):
                    offenders.append(
                        f"{route.relative_to(REPO)} -> {m.group('to')} "
                        f"(inside its own group '({group})')"
                    )

    assert not offenders, (
        "a group's index route forwards into its own group. Expo Router "
        "resolves a path relative to the group the caller is already in, so a "
        "screen in that group redirecting to '/' lands back on this file and "
        "the two redirect into each other until React throws 'Maximum update "
        "depth exceeded':\n  " + "\n  ".join(offenders)
    )


def test_every_redirecting_route_decides_whether_to_redirect():
    """`<Redirect>` re-navigates on every render, so a route that renders one
    unconditionally never settles."""
    offenders: list[str] = []

    for app in APPS:
        for route in _routes(app):
            src = _strip_comments(route.read_text(encoding="utf-8", errors="replace"))
            if "<Redirect" not in src:
                continue
            match = _COMPONENT.search(src)
            if match is None or not _RETURNS_REDIRECT.search(match.group("body")):
                continue
            if _GUARD.search(match.group("body")):
                continue
            offenders.append(str(route.relative_to(REPO)))

    assert not offenders, (
        "these routes render <Redirect> unconditionally, so they re-issue "
        "router.replace() on every render for as long as they are mounted:\n  "
        + "\n  ".join(offenders)
    )


def test_the_auth_group_has_no_index_route():
    """Named directly, because this is the file that broke and the rule above
    would stop covering it the moment somebody re-added it with a different
    destination."""
    present = [
        app for app in APPS if (REPO / app / "app" / "(Auth)" / "index.tsx").is_file()
    ]
    assert not present, (
        "(Auth)/index.tsx is back in: " + ", ".join(present) + ". A screen inside "
        "(Auth) that redirects to '/' resolves to this file rather than to "
        "app/index.tsx, which is the cycle that broke sign-in. Send callers to "
        "/(Auth)/sign-in/screen instead."
    )


def test_the_guards_can_still_see_the_defect():
    """Non-vacuity, without editing an app."""
    def flags(src: str) -> bool:
        src = _strip_comments(src)
        m = _COMPONENT.search(src)
        if m is None or not _RETURNS_REDIRECT.search(m.group("body")):
            return False
        return not _GUARD.search(m.group("body"))

    assert flags('export default function A() {\n  return <Redirect href="/x" />;\n}')
    assert not flags(
        'export default function A() {\n  if (x) return null;\n  return <Redirect href="/x" />;\n}'
    )
    assert not flags(
        '/** was: return <Redirect href="/x" />; */\n'
        'export default function A() {\n  if (x) return null;\n  return <Redirect href="/x" />;\n}'
    ), "the guard reads a comment as code"

    # The self-forwarding rule must fire on the shipped shape and not on a
    # sibling group, which is legitimate (`app/index.tsx` -> `/(screens)`).
    shipped = '<Redirect href="/(Auth)/sign-in/screen" />'
    assert _REDIRECT_TARGET.search(shipped).group("to").startswith("/(Auth)")
    sibling = '<Redirect href="/(screens)" />'
    assert not _REDIRECT_TARGET.search(sibling).group("to").startswith("/(Auth)")
