"""One typeface system across the four surfaces, enforced from the source.

Karla for body and UI, Fredoka for headings capped at 600, JetBrains Mono for
figures and identifiers. Every failure this file catches is silent at build
time and invisible in a screenshot taken on the machine that introduced it:

- **A weight utility with no family behind it.** `font-bold` sets
  `fontWeight: '700'` and names no face, so React Native renders the *system*
  font and thickens it. It looks deliberate, it looks bold, and it is Roboto on
  one handset and San Francisco on another. `font-sans-bold` names Karla's real
  Bold. There is no `font-synthesis-weight` in React Native — naming the face is
  the only mechanism there is.

- **A `<Text>` that names no family at all.** React Native has no cascade, so
  every element that says nothing falls back to the system font. The apps are
  ~1,700 such elements; the default is supplied by the wrapper in
  `components/ui/Text.tsx`, which is only in force while everything imports
  `Text` from there rather than straight from `react-native`.

- **A self-referential `--font-mono`.** `--font-mono: var(--font-mono, …)` is a
  cycle, and CSS drops a cyclic custom property at computed-value time, leaving
  the console with no monospace font whatsoever. It cannot fail a build.

- **Fredoka above 600.** Its heavy weights read as a children's brand. Loading
  one is what makes it reachable, so the cap is enforced where the faces are
  registered.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")
ADMIN = "drop-admin"

SKIP_DIRS = {"node_modules", "dist", ".expo", "android", "ios", "build", ".next"}

WRAPPER = "components/ui/Text.tsx"

#: Weights the platform loads for each family, and nothing else.
KARLA = ("200ExtraLight", "300Light", "400Regular", "500Medium",
         "600SemiBold", "700Bold", "800ExtraBold")
FREDOKA = ("400Regular", "500Medium", "600SemiBold")

#: A bare weight utility: sets `fontWeight` and names no face.
BARE_WEIGHT = re.compile(
    r"(?<![\w-])font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black)"
    r"(?![\w-])"
)


def _sources(app: str, suffixes: tuple[str, ...] = (".tsx",)) -> list[pathlib.Path]:
    root = ROOT / app
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.suffix in suffixes and not any(part in SKIP_DIRS for part in p.parts)
    ]


def _code_only(source: str) -> str:
    """Blank out comment bodies, preserving newlines so line numbers survive.

    The comment explaining why `font-bold` is wrong contains `font-bold`. Every
    "must not appear" assertion below has to read code, not prose.
    """
    out = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), source, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), out)


# ── The three apps ────────────────────────────────────────────────────────


@pytest.mark.parametrize("app", APPS)
def test_every_weight_utility_names_a_real_face(app: str) -> None:
    """No `font-bold`. React Native fakes it off the system font."""
    offenders: list[str] = []
    for path in _sources(app):
        code = _code_only(path.read_text())
        for match in BARE_WEIGHT.finditer(code):
            line = code[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line} {match.group(0)}")

    assert not offenders, (
        f"{app}: {len(offenders)} weight utilities name no font family, so React "
        "Native renders the system face and thickens it. Use the per-weight "
        "token instead — font-bold -> font-sans-bold.\n  "
        + "\n  ".join(offenders[:20])
    )


@pytest.mark.parametrize("app", APPS)
def test_text_is_imported_from_the_wrapper(app: str) -> None:
    """`Text`/`TextInput` come from the wrapper that supplies the default face.

    Importing straight from react-native gets an element with no family on it,
    which renders in the system font and cannot be spotted in review.
    """
    pattern = re.compile(
        r"import\s*\{([^}]*)\}\s*from\s*['\"]react-native['\"]", re.S
    )
    offenders: list[str] = []
    for path in _sources(app, (".ts", ".tsx")):
        if path.relative_to(ROOT / app).as_posix() == WRAPPER:
            continue
        code = _code_only(path.read_text())
        for match in pattern.finditer(code):
            names = {n.strip() for n in match.group(1).split(",")}
            for banned in ("Text", "TextInput"):
                if banned in names:
                    line = code[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(ROOT)}:{line} {banned}")

    assert not offenders, (
        f"{app}: imported from react-native instead of '@/components/ui/Text', "
        "so these render in the system font.\n  " + "\n  ".join(offenders[:20])
    )


@pytest.mark.parametrize("app", APPS)
def test_the_wrapper_still_supplies_a_default_family(app: str) -> None:
    """The wrapper is the whole mechanism; assert it still does the job."""
    source = (ROOT / app / WRAPPER).read_text()
    assert "font-sans" in source, f"{app}: the wrapper names no default family"
    for component in ("RNText", "RNTextInput"):
        assert f"<{component}" in source, f"{app}: the wrapper stopped rendering {component}"
    assert "withDefaultFont(className)" in source, (
        f"{app}: the wrapper no longer routes className through the default"
    )


@pytest.mark.parametrize("app", APPS)
def test_a_stylesheet_never_sets_a_weight_without_a_face(app: str) -> None:
    """`fontWeight` in a StyleSheet is the same defect, one layer down.

    These sit under the wrapper, so they inherit Karla Regular from the
    className and then ask the OS to thicken it — the faked bold returns.
    """
    offenders: list[str] = []
    for path in _sources(app, (".ts", ".tsx")):
        code = _code_only(path.read_text())
        for match in re.finditer(r"fontWeight\s*:", code):
            line = code[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")

    assert not offenders, (
        f"{app}: fontWeight in a StyleSheet has no face behind it. Name the "
        "registered family instead — fontWeight: '700' -> fontFamily: "
        "'Karla_700Bold'.\n  " + "\n  ".join(offenders[:20])
    )


@pytest.mark.parametrize("app", APPS)
def test_every_face_the_apps_name_is_registered(app: str) -> None:
    """A `fontFamily` string that was never loaded silently renders as system."""
    layout = (ROOT / app / "app/_layout.tsx").read_text()
    registered = set(re.findall(r"(Karla_\w+|Fredoka_\w+|JetBrainsMono_\w+)", layout))

    named: set[str] = set()
    for path in _sources(app, (".ts", ".tsx")):
        named |= set(
            re.findall(
                r"fontFamily\s*:\s*['\"](Karla_\w+|Fredoka_\w+|JetBrainsMono_\w+)['\"]",
                _code_only(path.read_text()),
            )
        )

    missing = sorted(named - registered)
    assert not missing, f"{app}: named but never registered in app/_layout.tsx: {missing}"


@pytest.mark.parametrize("app", APPS)
def test_fredoka_stops_at_600(app: str) -> None:
    """The cap is enforced where the faces are loaded — the only gate there is."""
    layout = (ROOT / app / "app/_layout.tsx").read_text()
    loaded = set(re.findall(r"Fredoka_(\w+)", layout))
    assert loaded == set(FREDOKA), (
        f"{app}: Fredoka is loaded at {sorted(loaded)}; the platform caps it at "
        f"{list(FREDOKA)}. Its heavier weights read as a children's brand."
    )
    heavier = {w for w in loaded if re.match(r"(700|800|900)", w)}
    assert not heavier, f"{app}: Fredoka above 600 is registered: {sorted(heavier)}"


@pytest.mark.parametrize("app", APPS)
def test_the_tailwind_tokens_cover_every_registered_weight(app: str) -> None:
    """A token per real file, so a class can never ask for a face that is faked."""
    # Comments first: the docblock above these tokens explains that there is no
    # `font-heading-bold`, which is the very string asserted absent below.
    config = _code_only((ROOT / app / "tailwind.config.js").read_text())
    for expected in ("sans", "sans-medium", "sans-semibold", "sans-bold",
                     "heading", "heading-semibold", "mono"):
        key = f'"{expected}"' if "-" in expected else f"{expected}:"
        assert key in config, f"{app}: tailwind.config.js has no `{expected}` font token"
    assert "heading-bold" not in config, (
        f"{app}: `heading-bold` implies a Fredoka 700 the platform does not load"
    )


@pytest.mark.parametrize("app", APPS)
def test_inter_is_gone(app: str) -> None:
    """Two body faces is how two screens quietly stop matching."""
    offenders = [
        str(path.relative_to(ROOT))
        for path in _sources(app, (".ts", ".tsx"))
        if re.search(r"Inter[_-]\w+", _code_only(path.read_text()))
    ]
    assert not offenders, f"{app}: still names Inter: {offenders}"

    left_behind = sorted(p.name for p in (ROOT / app / "assets/fonts").glob("Inter*"))
    assert not left_behind, f"{app}: unreferenced Inter files still shipped: {left_behind}"


# ── The console ───────────────────────────────────────────────────────────


def _globals_css() -> str:
    return (ROOT / ADMIN / "app/globals.css").read_text()


def test_the_console_maps_all_three_families() -> None:
    css = _globals_css()
    for token, expected in (
        ("--font-sans", "--font-karla"),
        ("--font-heading", "--font-fredoka"),
        ("--font-mono", "--font-jetbrains-mono"),
    ):
        match = re.search(rf"^\s*{re.escape(token)}:\s*([^;]+);", css, re.M)
        assert match, f"globals.css declares no {token}"
        assert expected in match.group(1), f"{token} does not resolve to {expected}"


def test_no_font_token_refers_to_itself() -> None:
    """`--font-mono: var(--font-mono, …)` is a cycle CSS discards in silence.

    The page then has no monospace font at all, and nothing anywhere reports it.
    """
    for match in re.finditer(r"^\s*(--font-[\w-]+):\s*([^;]+);", _globals_css(), re.M):
        name, value = match.group(1), match.group(2)
        assert f"var({name}" not in value, (
            f"{name} is defined in terms of itself. CSS drops a cyclic custom "
            "property, so this leaves the console with no font for that role."
        )


def test_headings_use_the_heading_face_and_never_a_faked_weight() -> None:
    css = _globals_css()
    rule = re.search(r"h1,\s*h2,\s*h3,\s*h4,\s*h5,\s*h6\s*\{([^}]*)\}", css, re.S)
    assert rule, "globals.css no longer styles h1–h6"
    body = rule.group(1)
    assert "var(--font-heading)" in body, "headings do not use the heading face"
    assert "font-synthesis-weight: none" in body, (
        "without this a `font-bold` heading is a browser-thickened 600, which "
        "defeats capping Fredoka at 600 in the first place"
    )


def test_the_console_loads_fredoka_capped_at_600() -> None:
    layout = (ROOT / ADMIN / "app/layout.tsx").read_text()
    block = re.search(r"Fredoka\(\{(.*?)\}\)", layout, re.S)
    assert block, "app/layout.tsx no longer loads Fredoka"
    weights = set(re.findall(r'"(\d{3})"', block.group(1)))
    assert weights == {"400", "500", "600"}, (
        f"the console loads Fredoka at {sorted(weights)}; the platform caps it at 400/500/600"
    )


def test_the_console_names_no_font_it_does_not_load() -> None:
    """`--font-sans` pointed at `--font-inter`, which nothing defined — so the
    console had never once rendered in its intended face, and every fallback
    chain was quietly doing the work."""
    css = _globals_css()
    layout = (ROOT / ADMIN / "app/layout.tsx").read_text()
    defined = set(re.findall(r'variable:\s*"(--font-[\w-]+)"', layout))
    defined |= {m.group(1) for m in re.finditer(r"^\s*(--font-[\w-]+):", css, re.M)}

    referenced = set(re.findall(r"var\((--font-[\w-]+)", css))
    missing = sorted(referenced - defined)
    assert not missing, f"globals.css references undefined font variables: {missing}"
