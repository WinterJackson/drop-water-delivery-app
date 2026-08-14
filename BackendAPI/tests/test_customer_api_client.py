"""
The customer app talks to the backend through one client.

The rider and vendor apps each have a test like this one. This app did not, and
the gap is the whole story: every raw `fetch` that survived anywhere in the three
apps survived *here*, and the two patterns the other apps had explicitly removed
were both still live in this one.

    components/map/PlacesAutocomplete.tsx   raw fetch — the rider's copy of the
                                            same component had been migrated
    Helpers/imageUpload.ts                  POST to Cloudinary with an unsigned
                                            preset — the exact path
                                            `drop-vendor-app/CLAUDE.md` says
                                            never to use, with the cloud name
                                            and preset hardcoded as fallbacks
    utils/appUpdate.ts                      raw fetch, so the forced-update check
                                            had no timeout

None of them failed anything, because nothing was looking. A guard covering two
of three apps does not enforce a platform rule; it enforces it in two places and
leaves the third to drift, which is precisely what happened. The customer app is
also the one with the most users on it.

What a raw `fetch` costs here is the same as everywhere else: no timeout, so a
request that never completes never rejects and the caller's `await` never
returns; no HTTPS enforcement; and no `ApiError`, so the backend's own `detail`
never reaches the toast and the customer is shown a transport error instead.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CUSTOMER = REPO / "drop-customer-app"

#: The only file allowed to call `fetch` directly is the one that wraps it.
#: `API/useApiClient.ts` uses axios, so it does not appear here at all.
FETCH_ALLOWED = {"API/apiFetch.ts"}

#: Third-party upload hosts. Not a style preference: an unsigned preset shipped
#: in an APK is a public write endpoint that cannot be revoked for one abuser,
#: and an upload that does not pass through the backend is not authenticated,
#: not size-capped and not content-sniffed.
THIRD_PARTY_UPLOADS = re.compile(
    r"api\.cloudinary\.com|upload_preset|CLOUDINARY", re.IGNORECASE
)

#: `NetInfo.fetch()` is a device API, not an HTTP call — the apps call
#: `NetInfo.refresh()` instead so that this scan does not have to special-case a
#: method name. Anything else preceded by a dot is a member call.
RAW_FETCH = re.compile(r"(?<![A-Za-z.])fetch\s*\(")

pytestmark = pytest.mark.skipif(
    not CUSTOMER.exists(), reason="customer app not in this checkout"
)


def _sources():
    for directory in ("app", "components", "hooks", "stores", "utils", "Helpers", "API", "config", "context", "lib"):
        root = CUSTOMER / directory
        if not root.exists():
            continue
        for path in sorted(list(root.rglob("*.ts")) + list(root.rglob("*.tsx"))):
            if "node_modules" in path.parts:
                continue
            yield path


def _without_comments(source: str) -> str:
    """Strip comments, keeping string literals.

    A file may legitimately *describe* the thing it no longer does — this module
    does exactly that, and so does `API/apiFetch.ts`. Matching prose would make
    the guard fire on its own explanation.
    """
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_no_screen_or_hook_calls_fetch_directly():
    offenders = []
    for path in _sources():
        relative = path.relative_to(CUSTOMER).as_posix()
        if relative in FETCH_ALLOWED:
            continue
        code = _without_comments(path.read_text(errors="ignore"))
        for match in RAW_FETCH.finditer(code):
            line = code[: match.start()].count("\n") + 1
            offenders.append(f"{relative}:{line}")

    assert not offenders, (
        "Raw `fetch` has no timeout, no HTTPS enforcement and no error "
        "normalisation, so the backend's own message never reaches the customer. "
        "Use `useApiRequest()` in React, or `apiFetch` outside it:\n  "
        + "\n  ".join(offenders)
    )


def test_nothing_uploads_to_a_third_party_host():
    """Images go to our own backend, which stores the S3 key.

    `POST /api/auth/upload-profile-pic` is the customer's counterpart to the
    vendor's `/upload-image`, and it exists so that this app does not need an
    unsigned write credential in its bundle.
    """
    offenders = []
    for path in _sources():
        code = _without_comments(path.read_text(errors="ignore"))
        if THIRD_PARTY_UPLOADS.search(code):
            offenders.append(path.relative_to(CUSTOMER).as_posix())

    assert not offenders, (
        "An unsigned upload preset in a shipped bundle is a public write endpoint "
        "for anyone who unzips the APK, billed to the account owner and revocable "
        "only by deleting it for every user at once. Upload through the backend:\n  "
        + "\n  ".join(offenders)
    )


def test_the_env_template_does_not_still_offer_the_credential():
    """A removed integration whose keys are still documented invites its return."""
    template = CUSTOMER / ".env.example"
    if not template.exists():
        pytest.skip(".env.example not in this checkout")
    assert "CLOUDINARY" not in template.read_text(), (
        ".env.example still documents the Cloudinary upload preset — and described "
        "it as 'safe to ship'. The next person to wire up an upload will use it."
    )


def test_the_scanner_recognises_a_raw_fetch_and_ignores_prose():
    """A guard that matches nothing passes for the wrong reason."""
    assert RAW_FETCH.search("const res = await fetch(url)")
    assert RAW_FETCH.search("return fetch(`${BASE}/x`)")
    # Member calls are somebody else's API, not an HTTP request.
    assert not RAW_FETCH.search("await NetInfo.fetch()")
    assert not RAW_FETCH.search("queryClient.prefetchQuery(...)")
    assert not RAW_FETCH.search("const { refetch } = useQuery()")
    # Prose describing the banned call must not trip it.
    assert not RAW_FETCH.search(_without_comments("// a raw fetch( is banned here"))
    assert not RAW_FETCH.search(_without_comments("/* uses fetch( internally */"))
