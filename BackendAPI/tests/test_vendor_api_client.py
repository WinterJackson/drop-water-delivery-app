"""
The vendor app talks to the backend through one client, and names its store.

`drop-vendor-app/API/` used to contain nothing but `routes/`. Forty-eight raw
`fetch` calls were spread across nine query hooks and seventeen screens, each
handling failure differently or not at all:

    throw new Error("Failed to fetch orders")
    throw new Error("Network response was not ok")
    if (res.ok) { ... }                      # and no `else` whatsoever

The platform guide says the opposite — show the backend's `detail`, never the
transport's own words — and both other apps had already been migrated. The
consequences were not only cosmetic. `fetch` has no default timeout, so a hung
request hung forever behind a skeleton. The 401 sign-out was copy-pasted at
about a dozen sites and missing from the rest. Several mutations checked
`res.ok`, and on `false` did nothing at all: `Products.tsx` refetched after a
refused delete, the product reappeared, and the vendor was told nothing.

The second rule is `X-Store-Id`. A `Vendor` row is a *store*, and one account may
own several — `GET /api/vendor/stores` exists to list them, and the dashboard has
had a switcher since its first version. Selecting a store moved a highlight and
nothing else: `handleSelectStore` held the id in `useState` beside the comment
`// Future: refetch dashboard with new store context`. Every request went to
whichever row the database returned first. The header is set in exactly one
place, so a hook that bypasses the client silently acts on the wrong store.

These are structural, in the style of `test_places_proxy`'s Google-key scan and
`test_rider_api_client`: the defect is "somebody added another one", which no
unit test can catch.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDOR = REPO / "drop-vendor-app"

#: The only file allowed to call `fetch` directly is the one that wraps it.
FETCH_ALLOWED = {"API/apiFetch.ts"}

pytestmark = pytest.mark.skipif(not VENDOR.exists(), reason="vendor app not in this checkout")


def _sources():
    for directory in ("app", "components", "hooks", "services", "stores", "utils", "Helpers", "API", "lib", "config"):
        root = VENDOR / directory
        if not root.exists():
            continue
        for path in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
            if "node_modules" in path.parts:
                continue
            yield path


def _code_lines(path: pathlib.Path):
    """Lines that are actually code — prose describing the rule is not a breach."""
    for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        yield i, line


def test_nothing_in_the_vendor_app_calls_fetch_directly():
    pattern = re.compile(r"(?<![A-Za-z.])fetch\s*\(")
    offenders = []
    for path in _sources():
        rel = path.relative_to(VENDOR).as_posix()
        if rel in FETCH_ALLOWED:
            continue
        for lineno, line in _code_lines(path):
            # `NetInfo.fetch()` is a device API, not an HTTP call.
            if "NetInfo" in line:
                continue
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "use `useApiRequest` (React) or `apiFetch` (outside React) — a raw fetch "
        f"has no timeout, no 401 handling, no error normalisation and no store scope: {offenders}"
    )


def test_no_screen_shows_the_user_an_http_status():
    """`Failed to fetch orders: 404` is not a sentence anyone can act on."""
    pattern = re.compile(r"(Error|error)\s*\(\s*[`\"'][^`\"']*\$\{\s*res(ponse)?\.status")
    offenders = []
    for path in _sources():
        for lineno, line in _code_lines(path):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(VENDOR).as_posix()}:{lineno}")
    assert offenders == [], f"surface the backend's `detail` via errorMessage(): {offenders}"


def test_the_client_sends_the_active_store_on_every_request():
    """One place sets `X-Store-Id`, and it reads the persisted selection.

    Setting it per-call would mean every new hook is one forgotten header away
    from quietly operating a different branch of the business.
    """
    client = (VENDOR / "API" / "useApiClient.ts").read_text()
    assert "useActiveStore" in client, "the client must read the selected store"
    assert "storeId" in client, "the client must pass the store through to apiFetch"

    fetcher = (VENDOR / "API" / "apiFetch.ts").read_text()
    assert '"X-Store-Id"' in fetcher, "apiFetch must send the store as a header"


def test_only_the_store_list_opts_out_of_store_scoping():
    """`allStores` widens a request, so it needs to stay a deliberate rarity.

    `GET /api/vendor/stores` is the one endpoint whose purpose is to return the
    others; scoping it would narrow it to the store the switcher is trying to
    move away from. Anything else using this flag is reaching past the boundary.
    """
    offenders = []
    for path in _sources():
        rel = path.relative_to(VENDOR).as_posix()
        if rel == "API/useApiClient.ts":
            continue
        for lineno, line in _code_lines(path):
            if "allStores" in line:
                offenders.append((rel, lineno, line.strip()))

    for rel, lineno, line in offenders:
        assert "GetStores" in line, (
            f"{rel}:{lineno} opts out of store scoping without being the store "
            f"list — it will read another store's data: {line}"
        )


def test_switching_stores_empties_the_query_cache():
    """Requests are scoped by header, so React Query cannot tell the two apart.

    `["vendorOrders"]` means "the active store's orders". Without this, switching
    served the previous store's orders, products and wallet under the new store's
    name — silently, and looking entirely plausible.
    """
    hook = VENDOR / "hooks" / "useStoreScopedCache.ts"
    assert hook.exists(), "useStoreScopedCache is what makes the switch safe"
    assert "queryClient.clear()" in hook.read_text()

    layout = (VENDOR / "app" / "(screens)" / "_layout.tsx").read_text()
    assert "useStoreScopedCache()" in layout, "it has to be mounted to do anything"


def test_the_store_switcher_is_not_still_a_placeholder():
    """The switcher shipped with `// Future: refetch dashboard with new store context`."""
    path = VENDOR / "app" / "(screens)" / "index.tsx"
    # Code lines only: the comment explaining what the placeholder *was* is not
    # itself a placeholder.
    code = "\n".join(line for _, line in _code_lines(path))
    assert "// Future:" not in code
    assert "setActiveStore" in code, "selecting a store must change the active store"


def test_wallet_transactions_name_the_ledger_they_want():
    """`WalletTransaction.user_id` holds ids from three tables and has no FK.

    The backend filters on `user_type`, which defaults to `"customer"`. Every
    call from this app omitted it, so the vendor's transaction list queried the
    customer ledger for a clerk id with no customer rows and came back empty —
    the screen rendered "No transactions yet" over a wallet with a live balance.
    """
    source = (VENDOR / "hooks" / "queries" / "useWallet.ts").read_text()
    assert "user_type" in source and "vendor" in source


def test_the_push_token_is_cleared_for_the_vendor_row():
    """`DELETE /api/auth/push-token` defaults to `app_type=customer`.

    Without the parameter it 404'd, and the token stayed registered against the
    store — so on a shared till device the next person to sign in kept receiving
    the previous vendor's incoming-order notifications, which is the exact
    failure the call exists to prevent.
    """
    source = (VENDOR / "hooks" / "usePushNotifications.ts").read_text()
    tree_ok = "app_type=vendor" in source
    assert tree_ok, "clearPushToken must pass ?app_type=vendor"


def test_no_image_is_stored_as_a_base64_data_uri():
    """`profile_pic` used to receive `data:image/jpeg;base64,…` from the picker.

    A megabyte or two of base64 was written into the column and then returned
    inside every profile response, to the vendor app and to every customer
    browsing the store.
    """
    offenders = []
    for path in _sources():
        for lineno, line in _code_lines(path):
            if "base64," in line and ("profile_pic" in line or "image_url" in line):
                offenders.append(f"{path.relative_to(VENDOR).as_posix()}:{lineno}")
    assert offenders == [], f"upload through SecureUpload and store the S3 key: {offenders}"


def test_uploads_go_through_our_own_backend():
    """The app shipped an *unsigned* Cloudinary preset.

    `upload_preset: 'drop_uploads'` with no signature is a public write endpoint:
    anyone who unzips the APK can upload arbitrary files to the account, from any
    machine, at the owner's expense — and revoking it means deleting the preset
    for every vendor at once.
    """
    offenders = []
    for path in _sources():
        for lineno, line in _code_lines(path):
            if "cloudinary" in line.lower() or "upload_preset" in line:
                offenders.append(f"{path.relative_to(VENDOR).as_posix()}:{lineno}")
    assert offenders == [], f"use POST /api/vendor/upload-image: {offenders}"


def test_paginated_screens_read_the_real_envelope():
    """The server no longer answers `{"pages": [...]}`.

    That shape was the API imitating React Query's `InfiniteData`. Consumers
    unwrapped `data.pages[0]`, so the second page replaced the first in one
    caller, and "is there more?" was guessed from the page length.
    """
    offenders = []
    for path in _sources():
        rel = path.relative_to(VENDOR).as_posix()
        for lineno, line in _code_lines(path):
            if re.search(r"data\.pages\s*\?\?\.\[0\]|data\.pages\s*\[\s*0\s*\]|data\.pages\?\.\[0\]", line):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], f"read `items` / `has_more` from the response: {offenders}"


def test_the_client_still_signs_out_on_401():
    """The one behaviour that must survive the migration off per-hook fetches."""
    client = (VENDOR / "API" / "useApiClient.ts").read_text()
    assert "signOut" in client and "401" in client
