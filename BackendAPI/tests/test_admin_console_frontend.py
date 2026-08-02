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


def test_only_sign_in_is_public():
    """No `/sign-up` route may be public on the admin origin.

    Administrators are invited and bound on first sign-in; there is no
    self-service path into `Admin_Users`. A public registration route here can
    only ever produce a customer account that lands on "you don't have access",
    while putting a sign-up form on the privileged origin.
    """
    import re

    source = (ADMIN / "middleware.ts").read_text()
    # The public list itself, not the import line that also names the helper.
    matcher = re.search(r"createRouteMatcher\(\[(.*?)\]\)", source, re.S)
    assert matcher, "no createRouteMatcher([...]) call found in the middleware"

    routes = matcher.group(1)
    assert "/sign-in" in routes
    assert "sign-up" not in routes, "sign-up must not be a public route on the console"


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
