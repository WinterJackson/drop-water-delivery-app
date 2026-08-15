"""Structural checks on `drop-admin/`.

They live here, with the other structural tests, because this is where the
build already runs a test suite — a lint rule nobody executes is a comment.

Two kinds of thing are checked:

* **Security invariants that TypeScript cannot express.** The token must never
  reach the browser; identity documents must never go through Next's image
  optimiser. Both are one careless import away and neither is a type error.
* **Accessibility invariants that survive a redesign.** A focus trap deleted
  during a refactor produces a dialog that still looks correct.
"""
import pathlib
import re

import pytest

ADMIN = pathlib.Path(__file__).resolve().parent.parent.parent / "drop-admin"

pytestmark = pytest.mark.skipif(not ADMIN.exists(), reason="drop-admin/ is not present")


def _sources(*globs: str) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pattern in globs or ("**/*.tsx", "**/*.ts"):
        for path in ADMIN.glob(pattern):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            files.append(path)
    return files


def _code_only(path: pathlib.Path) -> str:
    """Source with JSX and line comments removed.

    These files document *why* they avoid `next/image` and use a plain `<img>`,
    naming both — so a plain substring scan flags the explanation as the
    offence. Only real markup counts.
    """
    text = path.read_text(errors="ignore")
    text = re.sub(r"\{/\*.*?\*/\}", "", text, flags=re.S)   # {/* JSX comment */}
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)         # /* block comment */
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)          # // line comment
    return text


def _client_components() -> list[pathlib.Path]:
    return [p for p in _sources() if p.read_text(errors="ignore").lstrip().startswith('"use client"')]


# ── The token must not reach the browser ──────────────────────────────────


def test_no_client_component_imports_the_server_api_client():
    """`lib/api/server.ts` is marked `server-only`, so this is already a build
    error — asserted here as well because the failure message is the reason,
    not just the rule.

    This console renders national ID photographs. An XSS on any page of it must
    not also hand over an admin API token.
    """
    offenders = [
        path.relative_to(ADMIN).as_posix()
        for path in _client_components()
        if "@/lib/api/server" in path.read_text(errors="ignore")
    ]
    assert offenders == [], (
        f"client components importing the server API client: {offenders}"
    )


def test_the_backend_url_is_never_exposed_to_the_browser():
    """`NEXT_PUBLIC_BACKEND_*` would be inlined into the client bundle and would
    invite someone to call FastAPI directly, handing the token to the browser
    along with it."""
    offenders = []
    for path in _sources():
        text = _code_only(path)
        if re.search(r"NEXT_PUBLIC_[A-Z_]*BACKEND", text):
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], f"backend URL exposed to the client in: {offenders}"


def test_no_raw_fetch_to_the_backend_outside_the_api_layer():
    """Every backend call goes through `lib/api/server.ts` or the export route
    handler, both of which attach the token server-side. A stray `fetch` to the
    API is either unauthenticated or a token in the wrong place."""
    allowed = {"lib/api/server.ts", "app/api/export/route.ts"}
    offenders = []
    for path in _sources():
        relative = path.relative_to(ADMIN).as_posix()
        if relative in allowed:
            continue
        text = path.read_text(errors="ignore")
        if re.search(r"\bfetch\(\s*[`\"']?\$?\{?BACKEND", text) or "BACKEND_BASE_URL" in text:
            offenders.append(relative)
    assert offenders == [], f"raw backend calls outside the API layer: {offenders}"


# ── Personal data must not be cached ──────────────────────────────────────


def test_identity_documents_never_go_through_the_image_optimiser():
    """`next/image` fetches and caches on the server, which turns a 5-minute
    presigned link into a stored copy of somebody's national ID.

    The KYC and dispute screens use a plain `<img>` deliberately.
    """
    for name in ("operations/kyc/ReviewCard.tsx", "operations/disputes/DisputeCard.tsx"):
        path = ADMIN / "app" / "(dashboard)" / name
        assert path.exists(), f"{name} has moved; update this test"
        code = _code_only(path)
        assert not re.search(r"""from\s+["']next/image["']""", code), (
            f"{name} imports next/image — identity documents would be cached server-side"
        )
        assert "<img" in code


def test_every_requested_image_quality_is_configured():
    """An `<Image quality={n}>` must name a value `next.config.ts` allows.

    Next 16 stopped honouring arbitrary qualities. The quality is part of the
    optimiser's cache key and reachable from the query string, so an open range
    lets anyone mint unlimited re-encodes of the same file; the allowlist is the
    fix. An unlisted value is **not** an error — the image is served at the
    default and a warning goes to a log nobody is reading, which is how the
    sign-in hero spent its life asking for 90 and rendering at 75.
    """
    config = (ADMIN / "next.config.ts").read_text()
    listed = re.search(r"qualities:\s*\[([^\]]*)\]", config)
    allowed = {int(n) for n in re.findall(r"\d+", listed.group(1))} if listed else {75}

    offenders = []
    for path in _sources("app/**/*.tsx", "components/**/*.tsx"):
        for requested in re.findall(r"quality=\{(\d+)\}", _code_only(path)):
            if int(requested) not in allowed:
                offenders.append(f"{path.relative_to(ADMIN).as_posix()}: quality={requested}")
    assert offenders == [], (
        f"these ask for a quality next.config.ts does not list ({sorted(allowed)}); "
        f"they render at the default instead: {offenders}"
    )


# ── Accessibility ─────────────────────────────────────────────────────────


def test_the_focus_trap_actually_traps_and_restores():
    """`aria-modal="true"` is a promise that focus cannot leave the dialog.

    Without a trap it is simply untrue: Tab walks out into the page behind the
    overlay, which is fully interactive to the keyboard while looking inert.
    Restoring focus on close matters just as much — otherwise a keyboard user
    is dumped at the top of the document every time.

    One implementation, shared. Two copies is how one of them loses its trap in
    a refactor and nobody notices for a year.
    """
    source = (ADMIN / "lib" / "hooks" / "useFocusTrap.ts").read_text()
    assert 'event.key !== "Tab"' in source, "the hook does not intercept Tab"
    assert "openerRef" in source, "focus is not restored to the opener on close"
    assert 'event.key === "Escape"' in source, "Escape is not handled"


def test_every_modal_overlay_uses_the_shared_focus_trap():
    """Anything claiming `aria-modal` must actually behave like a modal."""
    offenders = []
    for path in _sources("**/*.tsx"):
        code = _code_only(path)
        if 'aria-modal="true"' not in code:
            continue
        if "useFocusTrap" not in code:
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], (
        f"these claim aria-modal but do not trap focus: {offenders}"
    )


#: `window.confirm` / `.prompt` / `.alert`, however they are reached. The
#: `window.` prefix is optional in a browser, so a bare `confirm(` counts too —
#: and `globalThis.prompt(` is the same call by a third spelling.
_NATIVE_DIALOG = re.compile(
    r"(?:\b(?:window|globalThis|self)\s*\.\s*)?\b(?:confirm|prompt|alert)\s*\(",
)

#: Names that merely *contain* one of those words. `confirmLabel`, `confirmText`
#: and a local `confirm()` handler are all live in this codebase, and the regex
#: above deliberately does not try to distinguish them by shape.
_NOT_A_DIALOG = re.compile(r"[A-Za-z0-9_$.]\s*$")


def test_no_native_browser_dialogs():
    """A grey Chrome box is not this console's UI, and it is not merely ugly.

    Three screens used them — removing an administrator, revealing a customer's
    contact details, revealing a rider's identity documents — and every one of
    the five problems below applies to at least one:

    * They ignore the theme entirely. Light system chrome lands over a dark
      console at the moment an operator is deciding whether to trust the screen.
    * `prompt` cannot validate. Two of the three collected a **reason that is
      written to `Admin_Audit_Log`**, against endpoints that refuse an empty
      one — so the operator found out from a red error afterwards.
    * They block the tab synchronously. React, every in-flight request and
      `IdleTimeout` are all frozen behind one; the console cannot warn about,
      or act on, an idle session while a dialog is up.
    * They are suppressible. "Prevent this page from creating additional
      dialogs" makes `confirm` return `false` and `prompt` return `null`
      **without showing anything**, so the button reads as broken.
    * They take a string. There is nowhere to put the subject's name, the
      consequence, or a danger tone on the button that does the damage.

    `components/ui/ConfirmDialog.tsx` is the replacement, and it is themed,
    focus-trapped and audited-reason-aware.
    """
    offenders = []
    for path in _sources("**/*.tsx", "**/*.ts"):
        code = _code_only(path)
        # Strings too: the prose in these files names the calls it replaced.
        code = re.sub(r"""(['"`])(?:\\.|(?!\1).)*\1""", '""', code, flags=re.S)
        for match in _NATIVE_DIALOG.finditer(code):
            # `foo.confirm(` where `foo` is not a global, or `onConfirm(` — the
            # character before the match tells them apart.
            if _NOT_A_DIALOG.search(code[: match.start()]):
                continue
            offenders.append(f"{path.relative_to(ADMIN).as_posix()}: {match.group(0)}")

    assert offenders == [], (
        "native browser dialogs in the console — use `ConfirmDialog`:\n  "
        + "\n  ".join(offenders)
    )


def test_the_confirm_dialog_is_a_real_modal():
    """It replaces a *blocking* browser dialog, so it has to behave like one.

    A themed box that Tab walks straight out of is a worse confirmation than the
    grey one it replaced: the page behind it is dimmed, looks inert, and is
    fully operable by keyboard.
    """
    source = (ADMIN / "components" / "ui" / "ConfirmDialog.tsx").read_text()
    assert 'role="alertdialog"' in source
    assert 'aria-modal="true"' in source
    assert "useFocusTrap" in source
    # Escape and the backdrop both cancel, as a browser dialog's Escape does.
    assert "onEscape" in source


def test_the_confirm_dialog_locks_the_page_behind_it():
    """The palette and the mobile drawer both take this lock, and below `sm`
    this is a bottom sheet the thumb is already resting on — a page that scrolls
    underneath one is how a confirmation gets dismissed by a scroll gesture."""
    source = (ADMIN / "components" / "ui" / "ConfirmDialog.tsx").read_text()
    assert 'document.body.style.overflow = "hidden"' in source
    # And restores what was there, rather than assuming "".
    assert "document.body.style.overflow = previous" in source


def test_the_confirm_dialog_focuses_cancel_not_the_destructive_button():
    """Two rules at once.

    An `alertdialog` that never receives focus may not be announced at all — and
    with no reason field there is nothing autofocusable in it. But the button
    that receives that focus must not be the one that does the damage: a
    confirmation one Return away from an accidental open is not a confirmation.
    """
    source = (ADMIN / "components" / "ui" / "ConfirmDialog.tsx").read_text()
    assert "cancelRef" in source
    assert "cancelRef.current?.focus()" in source
    assert re.search(r"<Button\s+ref=\{cancelRef\}", source), (
        "the focused-on-open button must be Cancel"
    )


def test_an_audited_reason_cannot_be_submitted_empty():
    """`revealContact` and `revealDocuments` are audited *before* the URLs are
    minted, and the backend refuses a blank reason. The dialog must not let one
    be sent — `window.prompt` returned `""` happily, which is how an operator
    learned the rule from a 400."""
    source = (ADMIN / "components" / "ui" / "ConfirmDialog.tsx").read_text()
    assert "trim()" in source, "the reason must be trimmed before it is judged"
    assert re.search(r"blocked\s*=", source), "there must be a disabled-until-typed rule"
    assert "disabled={pending || blocked}" in source


def test_every_reveal_states_that_it_is_recorded():
    """The reason field is the only thing standing between an operator and
    somebody's national ID, so the dialog says where it goes. A prompt that does
    not mention the audit log reads as a formality to type "asdf" into."""
    for relative in (
        "app/(dashboard)/operations/kyc/ReviewCard.tsx",
        "app/(dashboard)/people/[kind]/[id]/AccountActions.tsx",
    ):
        source = (ADMIN / relative).read_text()
        assert "Recorded against your account" in source, relative
        assert "reason={{" in source, f"{relative} reveals without asking why"


def test_the_palette_announces_its_results():
    """A listbox that swaps contents silently is invisible to a screen reader."""
    source = (ADMIN / "components" / "shell" / "CommandPalette.tsx").read_text()
    assert 'aria-live="polite"' in source
    assert 'role="combobox"' in source
    assert "aria-activedescendant" in source


def test_every_image_has_alternative_text():
    offenders = []
    for path in _sources("**/*.tsx"):
        for match in re.finditer(r"<img\b[^>]*>", _code_only(path), re.S):
            if "alt=" not in match.group(0):
                offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], f"images without alt text: {offenders}"


def test_no_positive_tabindex():
    """A positive tabindex takes an element out of document order and reorders
    the whole page's tab sequence around it."""
    offenders = [
        path.relative_to(ADMIN).as_posix()
        for path in _sources("**/*.tsx")
        if re.search(r"tabIndex=\{\s*[1-9]", path.read_text(errors="ignore"))
    ]
    assert offenders == [], f"positive tabIndex in: {offenders}"


def test_no_click_handlers_on_non_interactive_elements():
    """A `div` with an `onClick` is invisible to the keyboard and to assistive
    technology. The overlay in `Nav` is a real `<button>` for this reason."""
    offenders = []
    for path in _sources("**/*.tsx"):
        text = _code_only(path)
        for match in re.finditer(r"<(div|span|li|td|tr)\b[^>]*onClick", text, re.S):
            fragment = match.group(0)
            # Exempt two deliberate patterns, both of which keep a keyboard path:
            #   * a decorative backdrop (`aria-hidden` + `tabIndex={-1}`);
            #   * an element carrying an explicit ARIA `role`, which is no
            #     longer "non-interactive" — the dialog's click-outside-to-close
            #     is a convenience and Escape is asserted separately.
            if "aria-hidden" in fragment or "role=" in fragment:
                continue
            offenders.append(f"{path.relative_to(ADMIN).as_posix()}: <{match.group(1)}>")
    assert offenders == [], f"click handlers on non-interactive elements: {offenders}"


def test_every_data_table_has_a_caption_and_scoped_headers():
    """A table without `scope` on its headers is read as a grid of unlabelled
    cells. The caption is what tells a screen-reader user which table they have
    landed in."""
    offenders = []
    for path in _sources("**/*.tsx"):
        text = path.read_text(errors="ignore")
        if "<table" not in text:
            continue
        relative = path.relative_to(ADMIN).as_posix()
        if "<caption" not in text:
            offenders.append(f"{relative}: no <caption>")
        if "<th" in text and 'scope="' not in text:
            offenders.append(f"{relative}: <th> without scope")
    assert offenders == [], offenders


def test_wide_content_scrolls_inside_its_own_container():
    """The page body must never scroll sideways on a phone.

    Every table in the console is wrapped in `.scroll-x`; operations staff
    triage the KYC queue on a phone.
    """
    offenders = []
    for path in _sources("**/*.tsx"):
        text = path.read_text(errors="ignore")
        if "<table" not in text:
            continue
        if "scroll-x" not in text:
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], f"tables not wrapped in a horizontal scroll container: {offenders}"


#: The navigation surfaces, all painted in `--chrome`.
CHROME_SURFACES = ("Sidebar.tsx", "Header.tsx", "MobileNav.tsx", "NavList.tsx")

#: Tokens whose *value is chosen against `--surface`*. Correct everywhere else
#: in the console and wrong on any of the surfaces above.
SURFACE_TUNED = ("text-muted", "border-default", "hover:bg-surface-muted")


def test_the_chrome_surfaces_use_no_surface_tuned_token():
    """`--chrome` is the accent, and text on it has 4.62:1 in light mode with
    nothing to spare.

    `text-muted` is `--foreground-muted`, a value picked to sit quietly on
    `--surface`. On the accent panel it measures about 1.7:1 — not "a bit
    low", unreadable. The same goes for `border-default`, which vanishes.

    This is the failure mode that reappears every time somebody adds a row to
    the sidebar by copying one from a page, because the class is right
    everywhere else in the console and looks right in the diff.
    """
    offenders = []
    for name in CHROME_SURFACES:
        path = ADMIN / "components" / "shell" / name
        text = _code_only(path)
        for token in SURFACE_TUNED:
            if re.search(rf"\b{re.escape(token)}\b", text):
                offenders.append(f"{name}: {token}")
    assert offenders == [], (
        "surface-tuned tokens on the accent chrome — use the --chrome-* set: "
        f"{offenders}"
    )


def test_every_chrome_token_resolves_in_both_themes():
    """A chrome token either derives from something the dark blocks redefine,
    or is redefined there itself.

    `--chrome-hover` is the one written as a literal `oklch()`, because hover
    has to move the ground *away* from the text and that is a different
    direction in each theme — darker under light mode's near-white, lighter
    under dark mode's near-black. Defined once, it would be a hover state that
    reduces contrast in whichever theme it was not written for, which is
    exactly the sort of thing that looks fine to whoever added it.
    """
    css = (ADMIN / "app" / "globals.css").read_text()

    declared = re.findall(r"^\s*(--chrome[\w-]*):\s*([^;]+);", css, re.M)
    assert declared, "the chrome token set has gone"

    # Only the *colour* tokens. `--chrome-inset` is a length — one geometry for
    # both themes is the point of it, and demanding a dark-mode value for it
    # would be demanding the wrong thing. A token derived through `var()` or
    # `color-mix()` re-resolves on its own, so only a literal colour needs
    # saying twice.
    literal = {
        name
        for name, value in declared
        if re.match(r"(oklch|rgb|hsl|lab|lch|color)\(|#[0-9a-f]{3}", value.strip(), re.I)
    }
    assert literal, "no chrome colour is written as a literal; --chrome-hover must be"

    dark_blocks = re.findall(
        r"(?:@media \(prefers-color-scheme: dark\)|:root\[data-theme=\"dark\"\])(.*?)\n  \}",
        css,
        re.S,
    )
    assert len(dark_blocks) == 2, f"expected two dark blocks, found {len(dark_blocks)}"

    for index, block in enumerate(dark_blocks):
        missing = [name for name in literal if f"{name}:" not in block]
        assert missing == [], (
            f"dark block {index} never redefines {missing} — the light value "
            "would be used on the dark panel"
        )


def test_a_variant_is_never_put_in_front_of_a_hand_written_class():
    """Tailwind only generates variants for utilities it knows about.

    A plain `.text-muted { … }` rule works written on its own and compiles to
    **nothing at all** the moment a variant is put in front of it. There is no
    error and nothing to see: the class is in the markup, the base class
    exists, and the page looks right.

    It was live in 35 places. `placeholder:text-muted` on the shared input
    primitive, so every field in the console fell back to the browser's
    washed-out default placeholder; and `hover:bg-surface-muted` on the row of
    every list screen there is, so no table row had ever highlighted under the
    pointer — on a console whose main activity is scanning a queue and clicking
    the right line.

    The fix is to declare them with `@utility`, which makes every variant work
    at no call site's expense. This test is the thing that keeps the next
    semantic utility from being added the old way.
    """
    css = re.sub(
        r"/\*.*?\*/", "", (ADMIN / "app" / "globals.css").read_text(), flags=re.S
    )

    proper = set(re.findall(r"^@utility\s+([\w-]+)", css, re.M))
    assert proper, "globals.css declares no @utility; they have been reverted"

    # Bare class rules — anything Tailwind will not attach a variant to.
    bare = set(re.findall(r"^\s*\.([a-z][\w-]*)\s*(?:,|\{)", css, re.M)) - proper

    offenders = []
    for path in _sources("**/*.tsx", "**/*.ts"):
        text = _code_only(path)
        for variant, name in re.findall(r"\b([a-z][\w-]*):([a-z][\w-]*)\b", text):
            if name in bare:
                offenders.append(f"{path.relative_to(ADMIN).as_posix()}: {variant}:{name}")

    assert offenders == [], (
        "variant applied to a hand-written class — it compiles to nothing. "
        f"Declare it with @utility instead: {sorted(set(offenders))}"
    )


def test_the_thin_scrollbar_does_not_cancel_itself():
    """`scrollbar-width` and `::-webkit-scrollbar` are mutually exclusive.

    Chrome implements the standard properties, and the presence of
    `scrollbar-width` makes it ignore the `::-webkit-` rules entirely — so
    declaring both gives the browser's full default scrollbar, arrow buttons
    included, which is what shipped the first time. The standard half has to
    stay fenced behind a query that is false wherever the pseudo-element
    exists.
    """
    # Comments stripped first, and for the usual reason: the stylesheet
    # explains *why* `scrollbar-width` cannot sit outside the fence, naming it,
    # so a plain scan flags the explanation as the offence. Same rule as
    # `_code_only`, which only knows how to read TypeScript.
    css = re.sub(
        r"/\*.*?\*/", "", (ADMIN / "app" / "globals.css").read_text(), flags=re.S
    )

    assert "::-webkit-scrollbar" in css, "the 2px scrollbar rule has gone"

    fence = r"@supports not selector\(::-webkit-scrollbar\)\s*\{.*?\n  \}"
    assert re.search(fence, css, re.S), "scrollbar-width is not fenced behind @supports"

    outside = re.sub(fence, "", css, flags=re.S)
    for property_name in ("scrollbar-width", "scrollbar-color"):
        assert property_name not in outside, (
            f"{property_name} is declared outside the @supports fence; "
            "Chrome will drop the ::-webkit-scrollbar sizing"
        )


def test_dark_mode_is_expressed_once_in_tokens_not_per_element():
    """Semantic tokens (`bg-surface`, `text-muted`) rather than
    `bg-white dark:bg-neutral-900` at every call site — which is how the two
    themes drift apart."""
    offenders = []
    for path in _sources("**/*.tsx"):
        text = _code_only(path)
        if re.search(r"\bdark:", text):
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], (
        f"per-element dark: variants instead of semantic tokens: {offenders}"
    )


# ── Navigation ────────────────────────────────────────────────────────────


def _nav_config() -> str:
    return (ADMIN / "components" / "shell" / "nav-config.ts").read_text()


def test_every_dashboard_page_is_reachable_from_the_navigation():
    """A page nobody can navigate to is a queue that silently stops being worked.

    Walks the App Router tree and checks each concrete route appears in the nav
    config. Dynamic segments are excluded: `/people/[kind]` is reached through
    the three literal hrefs the config already lists, and a detail page is
    reached from its own list.
    """
    dashboard = ADMIN / "app" / "(dashboard)"
    config = _nav_config()

    missing = []
    for page in dashboard.rglob("page.tsx"):
        relative = page.parent.relative_to(dashboard).as_posix()
        if relative == ".":
            route = "/"
        else:
            route = f"/{relative}"
        if "[" in route:  # dynamic — reached via its list page
            continue
        if f'"{route}"' not in config:
            missing.append(route)

    assert missing == [], f"pages with no navigation entry: {missing}"


def test_every_dashboard_page_checks_the_capability_it_needs():
    """A page that renders and *then* gets refused reads as a broken console.

    Twelve pages did exactly that: the heading painted, the queries fired, and
    the caller got "Couldn't load — 403 Forbidden" — so the person without
    `finance.read` reported an outage instead of asking for the capability.

    This is **not** access control and never was: `require_admin(...)` on the
    backend is the only check that decides anything, and this one would gain a
    caller nothing to bypass. It is the difference between being told no and
    being shown a stack of failed requests.

    `pageAccess` reads the permission out of `nav-config`, so a page and the
    sidebar entry that hides it can never disagree about which capability it
    needs. A page may also gate inline with `can(me, ...)` where it renders a
    partly-permitted screen — the growth page shows the cohorts to anyone with
    `analytics.read` and only gates the spend editor.
    """
    dashboard = ADMIN / "app" / "(dashboard)"

    ungated = []
    for page in dashboard.rglob("page.tsx"):
        source = page.read_text()
        if "pageAccess(" in source or "can(" in source:
            continue
        ungated.append(page.relative_to(ADMIN).as_posix())

    assert ungated == [], (
        "dashboard pages with no capability check — gate with `pageAccess()` "
        f"from `lib/page-access`, or `can(me, ...)` for a partial screen: {ungated}"
    )


def test_the_page_gate_reads_its_permission_from_the_nav_config():
    """One declaration per destination, or the two drift.

    A page hidden from the sidebar but openable by URL is the same defect as a
    page offered and then refused, and hand-writing the permission in both
    places is how a route acquires one.
    """
    helper = (ADMIN / "lib" / "page-access.ts").read_text()

    assert "server-only" in helper, (
        "page-access reaches the admin API, so it must never be importable from "
        "a Client Component"
    )
    assert "NAV_ITEMS" in helper, (
        "the page gate must read its permission from nav-config, not take one "
        "as an argument"
    )
    # Fails closed: an unidentifiable caller is refused, not admitted.
    assert "if (!me)" in helper and "allowed: false" in helper


def test_the_navigation_is_declared_once():
    """The sidebar, the drawer, the bottom bar and the breadcrumb all render
    from `nav-config.ts`.

    Three hand-maintained copies of the same routes is how an entry gains a
    capability check in one place and keeps offering itself in the other two.
    """
    for name in ("Sidebar.tsx", "MobileNav.tsx", "Header.tsx"):
        source = (ADMIN / "components" / "shell" / name).read_text()
        assert "nav-config" in source, f"{name} does not use the shared nav config"

    # And nothing else hard-codes a route list.
    offenders = []
    for path in _sources("components/shell/*.tsx"):
        if path.name in {"nav-config.ts", "NavList.tsx"}:
            continue
        code = _code_only(path)
        if 'href="/operations/' in code or 'href="/people/' in code:
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], f"hard-coded nav routes outside the config: {offenders}"


def test_the_bottom_bar_leaves_room_for_more():
    """The tab bar is capped so the last slot can always be "More".

    A bar that silently drops the pages someone happens to have permission for
    is worse than one extra tap — the dropped page is invisible rather than
    merely further away.
    """
    config = _nav_config()
    assert "limit = 4" in config, "the tab bar cap has moved; re-check the More slot"

    mobile = (ADMIN / "components" / "shell" / "MobileNav.tsx").read_text()
    assert "tabs.length + 1" in mobile, "the grid does not reserve a column for More"
    assert 'aria-label="More pages"' in mobile


def test_icon_only_navigation_still_has_accessible_names():
    """The bottom bar draws no text by request. That must not mean unlabelled:
    every tab carries the word its label would have shown."""
    source = (ADMIN / "components" / "shell" / "MobileNav.tsx").read_text()
    assert "aria-label={item.label}" in source, "tabs have no accessible name"
    assert "sr-only" in source, "the short label is not announced"
    assert 'aria-current={active ? "page" : undefined}' in source


def test_the_bottom_bar_clears_the_home_indicator():
    """A fixed bar without the safe-area inset sits under the iPhone home
    indicator, and its last row of content sits under the bar."""
    source = (ADMIN / "components" / "shell" / "MobileNav.tsx").read_text()
    assert "pb-safe" in source, "the tab bar ignores the safe-area inset"

    layout = (ADMIN / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert "pb-tabbar" in layout, "main content is not padded clear of the tab bar"

    css = (ADMIN / "app" / "globals.css").read_text()
    assert "env(safe-area-inset-bottom" in css


def test_the_shell_survives_the_badge_endpoint_failing():
    """Badges are decoration. A slow or refused count must not blank the whole
    console — the payout nobody has approved is still the point of the page."""
    layout = (ADMIN / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert "NO_COUNTS" in layout
    assert "catch" in layout.split("nav/counts")[1][:200], (
        "the nav counts fetch is not guarded"
    )


def test_a_missing_count_is_not_rendered_as_zero():
    """The backend omits a queue the caller may not open, and sends `0` for one
    that is genuinely empty. Rendering the two the same way either invents a
    badge for a page that would refuse them, or hides that a queue is clear."""
    source = (ADMIN / "components" / "shell" / "NavList.tsx").read_text()
    assert "count !== undefined && count > 0" in source, (
        "an absent count is not distinguished from zero"
    )


# ── Server Actions ────────────────────────────────────────────────────────


def test_use_server_modules_only_export_async_functions():
    """A `"use server"` module may only export async function *declarations*.

    `export const foo = () => …` compiles to a module with no exports at all —
    it typechecks cleanly and fails at build time with a confusing message.
    """
    offenders = []
    for path in _sources("**/*.ts"):
        text = path.read_text(errors="ignore")
        if not text.lstrip().startswith('"use server"'):
            continue
        for line in text.splitlines():
            if not line.startswith("export "):
                continue
            if line.startswith("export type ") or line.startswith("export interface "):
                continue
            if not line.startswith("export async function "):
                offenders.append(f"{path.relative_to(ADMIN).as_posix()}: {line.strip()[:60]}")
    assert offenders == [], offenders


# ── Authentication ────────────────────────────────────────────────────────


def _request_gate() -> pathlib.Path:
    """The one file Next.js runs in front of every request.

    Next 16 renamed the convention from `middleware.ts` to `proxy.ts`. Both
    names still resolve, which is the trap: leaving the old file behind gets a
    deprecation warning on every boot, and *adding* the new one without deleting
    the old gives the console two gates where only one runs — the sign-in route
    list would then be edited in a file Next never reads, and the page that
    looked protected would be open.
    """
    present = [name for name in ("proxy.ts", "middleware.ts") if (ADMIN / name).exists()]
    assert present, "the console has no proxy.ts — every route is unauthenticated"
    assert present == ["proxy.ts"], (
        f"expected proxy.ts alone, found {present}. Next 16 renamed the middleware "
        "convention; two gate files means one of them is not the one running."
    )
    return ADMIN / present[0]


def test_only_sign_in_is_public():
    """No `/sign-up` route may be public on the admin origin.

    Administrators are invited and bound on first sign-in; there is no
    self-service path into `Admin_Users`. A public registration route here can
    only ever produce a customer account that lands on "you don't have access",
    while putting a sign-up form on the privileged origin.
    """
    source = _request_gate().read_text()
    # The public list itself, not the import line that also names the helper.
    matcher = re.search(r"createRouteMatcher\(\[(.*?)\]\)", source, re.S)
    assert matcher, "no createRouteMatcher([...]) call found in the request gate"

    routes = matcher.group(1)
    assert "/sign-in" in routes
    assert "sign-up" not in routes, "sign-up must not be a public route on the console"


def test_the_request_gate_protects_everything_it_does_not_name_public():
    """The gate must *default* to protected.

    `if (isPublic(request)) return;` reads almost identically to the correct
    form and inverts the whole console: every route not explicitly listed as
    public would fall through unauthenticated. The matcher decides what is
    exempt; everything else has to reach `auth.protect()`.
    """
    source = _request_gate().read_text()
    assert "auth.protect()" in source, "the request gate never calls auth.protect()"
    assert re.search(r"if\s*\(\s*!\s*isPublic\(", source), (
        "the gate must protect what the public matcher does *not* match"
    )


def test_the_request_gate_declares_no_runtime():
    """A proxy always runs on Node.js, and Next refuses route segment config here.

    Carrying `export const runtime` across from the middleware era is an error
    in a production build and a line that has quietly stopped meaning anything
    in dev.
    """
    source = _request_gate().read_text()
    assert not re.search(r"export\s+const\s+runtime\b", source), (
        "route segment config is not allowed in proxy.ts — a proxy is always Node.js"
    )


def test_the_console_signs_an_idle_administrator_out():
    """Clerk sessions last days. This console reads national IDs and releases
    payouts, and it is used on shared desks — an unattended tab needs no
    attacker at all.

    The warning matters as much as the timeout: signing somebody out mid-word
    while they type a suspension reason loses their work.
    """
    source = (ADMIN / "components" / "shell" / "IdleTimeout.tsx").read_text()

    assert "signOut" in source
    assert 'aria-modal="true"' in source and "useFocusTrap" in source
    # Wall-clock, not a decrementing counter: a throttled background tab would
    # otherwise resume the countdown an hour later and keep the session open.
    assert "Date.now()" in source

    # Mounted once for the whole console, or navigating would reset the clock.
    layout = (ADMIN / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert "<IdleTimeout />" in layout


def test_the_dead_end_screens_offer_a_real_sign_out():
    """"Sign in with a different account" as a link to `/sign-in` does nothing
    when a session already exists — Clerk sees one and returns the caller to the
    page that refused them. Somebody signed in with their customer account was
    stuck in that loop with no way out but clearing cookies."""
    layout = (ADMIN / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert "SignOutButton" in layout
    assert 'href="/sign-in"' not in layout, "a link cannot end an existing session"


# ── Maps: Google, and only the SDK ────────────────────────────────────────


def test_the_basemap_is_google_not_openstreetmap():
    """Every map on this platform is Google. MapLibre with OSM raster tiles was
    used here briefly because it needs no key; it is the only surface that ever
    differed from the three apps, and a console that draws a different map from
    the one riders see is a console people stop trusting."""
    offenders = []
    for path in _sources("**/*.ts", "**/*.tsx", "**/*.css", "package.json"):
        text = _code_only(path) if path.suffix in {".ts", ".tsx"} else path.read_text(errors="ignore")
        if re.search(r"maplibre|openstreetmap|tile\.osm|basemaps\.cartocdn", text, re.I):
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert offenders == [], f"non-Google basemap referenced in: {offenders}"


def test_the_browser_key_can_only_load_the_maps_sdk():
    """The browser key is public by necessity — the browser draws the map. What
    keeps that from being a billing incident is that it is an *SDK* key: it loads
    `maps/api/js` and nothing else. A client-side call to Directions, Places or
    Geocoding would need a web-service key, and those stay behind
    `routes/maps_routes.py`. This test is the line between the two."""
    loader = (ADMIN / "lib" / "maps" / "google-maps.ts").read_text()

    urls = re.findall(r"https://maps\.googleapis\.com[^\s\"'`]*", loader)
    assert urls, "the loader no longer names a Google endpoint — has it moved?"
    for url in urls:
        assert "/maps/api/js" in url, f"browser code calling a Google web service: {url}"

    for path in _sources("**/*.ts", "**/*.tsx"):
        text = _code_only(path)
        forbidden = re.findall(
            r"maps\.googleapis\.com/maps/api/(?:directions|geocode|distancematrix|place)", text
        )
        assert forbidden == [], (
            f"{path.relative_to(ADMIN).as_posix()} calls a Google web service from the client"
        )


def test_the_map_refetches_on_idle_not_on_every_frame():
    """`bounds_changed` fires on every animation frame of a drag — one request
    per frame, against a viewport query that hits PostGIS. `idle` fires once,
    when the map has settled."""
    source = (ADMIN / "app" / "(dashboard)" / "operations" / "map" / "OperationsMap.tsx").read_text()
    assert 'addListener("idle"' in source
    assert "bounds_changed" not in _code_only(
        ADMIN / "app" / "(dashboard)" / "operations" / "map" / "OperationsMap.tsx"
    )


def test_the_maps_loader_waits_for_the_callback_not_the_script_load_event():
    """`loading=async` returns a *bootstrap*, not the API.

    The `<script>` element's `load` event fires when that bootstrap arrives, at
    which point `google.maps` exists as an object but `google.maps.Map` is still
    `undefined` — so treating `load` as "ready" produces
    `google.maps.Map is not a constructor` on the first render, and only on a
    cold cache, which is why it survives a dev session and breaks in production.

    `callback=` is the documented ready signal. This test pins it, because the
    broken version looks completely reasonable.
    """
    loader = (ADMIN / "lib" / "maps" / "google-maps.ts").read_text()

    assert "callback=" in loader, "the loader no longer passes a callback to the bootstrap"

    if "loading=async" in loader:
        assert "callback=" in loader, "loading=async requires callback= to know when Map exists"

    code = _code_only(ADMIN / "lib" / "maps" / "google-maps.ts")
    assert 'addEventListener("load"' not in code, (
        "the script's load event fires before google.maps.Map is defined — "
        "resolve on the callback instead"
    )


def test_a_missing_maps_key_explains_itself():
    """Every other screen works without the key, so a blank rectangle here reads
    as a broken backend rather than an unset variable."""
    source = (ADMIN / "app" / "(dashboard)" / "operations" / "map" / "OperationsMap.tsx").read_text()
    assert "loadError" in source, "the load failure is not surfaced at all"
    loader = (ADMIN / "lib" / "maps" / "google-maps.ts").read_text()
    assert "NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY is not set" in loader


def test_no_operational_page_is_only_a_table():
    """Every queue page must carry aggregate context, not just rows.

    A list answers "what is in the queue" and never "is the queue healthy",
    which is the only question a supervisor has. Eight of thirteen pages were a
    table and a search box; this fails the build if one regresses to that.

    `Stat` is the marker because it is what the shared header is built from —
    a page that renders one is a page that has told the reader something about
    the shape of the work, not just its contents.
    """
    QUEUE_PAGES = [
        "operations/orders",
        "operations/kyc",
        "operations/vendors",
        "operations/disputes",
        "finance/payouts",
        "finance/reconciliation",
        "support",
        "people/[kind]",
        "platform/audit",
    ]

    bare = []
    for route in QUEUE_PAGES:
        path = ADMIN / "app" / "(dashboard)" / route / "page.tsx"
        if not path.exists():
            bare.append(f"{route} (missing)")
            continue
        if "<Stat" not in path.read_text():
            bare.append(route)

    assert bare == [], f"these queue pages render no aggregate: {bare}"


def test_queue_headers_never_coerce_a_missing_figure_to_zero():
    """`/queues/stats` omits any queue the caller may not open, and returns null
    for a figure that is genuinely unanswerable — no oldest item because nothing
    waits, no approval rate because nothing was decided.

    `?? 0` on either would invent a number: a header reading "0 waiting" above a
    page that would refuse the caller, or "0%" approval where the truth is that
    no decision has ever been made.
    """
    import re

    offenders = []
    for path in _sources("app/(dashboard)/**/page.tsx"):
        text = _code_only(path)
        for match in re.finditer(r"(stats|counts)\.\w+[\w.]*\s*\?\?\s*0", text):
            offenders.append(f"{path.relative_to(ADMIN).as_posix()}: {match.group(0)}")

    assert offenders == [], f"queue figures coerced to zero: {offenders}"


def test_a_customised_setting_states_what_the_platform_ships():
    """"Customised" alone cannot tell a decision from a leftover.

    A `Platform_Settings` row outranks the shipped default forever, so a value
    left behind by an older release keeps pricing every order while the source
    says something else. The only place that is visible to the person who can
    fix it is this screen, so it has to say both figures — and offer the
    shipped one in one click, through the same validated, reasoned save as any
    other change.
    """
    source = _code_only(ADMIN / "app" / "(dashboard)" / "platform" / "pricing" / "PricingEditor.tsx")

    assert "setting.default" in source, (
        "the editor no longer reads the shipped default, so a stored row "
        "holding an old one is invisible"
    )
    assert "The platform ships" in source
    assert "Use the shipped value" in source
    assert "set(setting.key, setting.default)" in source, (
        "reverting to the shipped value must go through the normal draft, so "
        "it is previewed and saved with a reason like any other change"
    )


# ── Lists, and the three things every one of them must do ─────────────────
#
# Nineteen list screens were written independently and drifted into three
# distinct defects: seventeen of them discarded the `next_cursor` the API was
# already returning and silently showed the first page as if it were the whole
# table; six had a search box, each one a full-page GET form with a submit
# button; and the filters were tabs, selects or nothing depending on the screen.
# These keep all three from coming back one page at a time.


def _list_pages() -> list[pathlib.Path]:
    """Dashboard pages that read paginated state.

    Identified by their use of `readPageState` rather than by a hand-kept list —
    a list of filenames in a test is a list that rots the first time somebody
    adds a screen and does not think to update it.
    """
    return [
        path
        for path in _sources("app/(dashboard)/**/page.tsx")
        if "readPageState" in path.read_text()
    ]


def test_every_list_page_actually_pages():
    """A page that reads pagination state must render a pager.

    Reading `readPageState` and then never rendering `<Pagination>` is the
    original defect in a new costume: the cursor is parsed, the page size is
    honoured, and the person still has no way to reach row 26.
    """
    missing = [
        path.relative_to(ADMIN).as_posix()
        for path in _list_pages()
        if "<Pagination" not in path.read_text()
    ]
    assert not missing, (
        "these list pages read pagination state but render no pager, so only "
        f"the first page is reachable: {missing}"
    )


def test_a_paged_request_always_asks_for_the_page_it_is_showing():
    """`limit` and `cursor` both have to reach the API.

    Sending neither leaves the backend on its own default and pinned to page 1 —
    which is exactly what every one of these screens did before. Sending `limit`
    without `cursor` is worse than it looks: the page-size control appears to
    work while Next silently re-serves the first rows.
    """
    incomplete = []
    for path in _list_pages():
        source = path.read_text()
        if "limit" not in source or "cursor" not in source:
            incomplete.append(path.relative_to(ADMIN).as_posix())
    assert not incomplete, (
        "these pages parse pagination state but never send `limit` and `cursor` "
        f"to the API: {incomplete}"
    )


def test_no_list_page_hand_rolls_its_own_search_form():
    """Search goes through `TableToolbar`, not a per-page GET form.

    The hand-written forms are why searching meant type, click Search, wait for
    a full document navigation. They also each spelled the reset differently, so
    searching from page 3 kept the page-3 cursor and searched the wrong slice.
    """
    offenders = []
    for path in _sources("app/(dashboard)/**/*.tsx"):
        source = path.read_text()
        if 'method="GET"' in source and "TableToolbar" not in source:
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert not offenders, (
        "these render their own GET search form instead of `TableToolbar`: "
        f"{offenders}"
    )


def test_the_toolbar_resets_the_cursor_when_the_query_changes():
    """A new search must start at page 1.

    A keyset cursor is a value comparison, not an index, so carrying a stale one
    into a different result set does not error — it lands somewhere plausible in
    the middle of the new results, which is the worst of the three things it
    could do. `TableToolbar.commit` therefore rebuilds the query string from
    `keep` and the filters and never copies `cursor` or `back` across.
    """
    toolbar = (ADMIN / "components/table/TableToolbar.tsx").read_text()
    commit = toolbar[toolbar.index("const commit ="):]
    commit = commit[: commit.index("const timer")]
    for carried in ("cursor", "back"):
        assert carried not in commit, (
            f"`TableToolbar.commit` carries `{carried}` into the new query; a "
            "changed search or filter must return to the first page"
        )


def test_the_mobile_layout_can_page_too():
    """A pager inside a `md:`-only table does not exist on a phone.

    Several of these screens render a table above `md` and a stack of cards
    below it. A pager placed inside the table's own card is invisible at exactly
    the width where it matters most, because fewer rows fit on the screen.
    """
    offenders = []
    for path in _list_pages():
        source = path.read_text()
        if "md:hidden" not in source:
            continue  # no separate card layout, so nothing to miss
        marker = 'className="hidden overflow-hidden md:block"'
        if marker not in source:
            continue  # the table is not desktop-only, so its pager is not either

        # Where the pager is actually *rendered*, not where the component is
        # named. Several pages build it once into a `pager` constant and render
        # it twice; counting `<Pagination` alone reports those as having one.
        sites = [i for i in range(len(source)) if source.startswith("<Pagination", i)]
        if "const pager" in source:
            sites += [i for i in range(len(source)) if source.startswith("{pager}", i)]

        # Reachable below `md` if it is rendered more than once, or rendered
        # before the desktop-only table begins — a pager above the table is
        # still a pager on a phone.
        desktop_starts = source.index(marker)
        if len(sites) < 2 and not any(site < desktop_starts for site in sites):
            offenders.append(path.relative_to(ADMIN).as_posix())
    assert not offenders, (
        "these render their only pager inside a desktop-only table, so the card "
        f"layout below `md` cannot be paged: {offenders}"
    )
