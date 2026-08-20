"""Every socket the apps open can actually connect, and notices when it stops.

Four defects, and every one of them is silent from both ends — the socket
either never opens or stops delivering while still looking connected, and
nothing errors, nothing logs, and the screen simply stops changing.

* **No token.** `_authenticate_ws` closes an unauthenticated socket with 1008
  before the first frame. The vendor's live-tracking map built its URL without
  `?token=`, so it has never shown a moving rider — for every order, always.
  The customer app had the identical bug and fixed it in `useRiderTracking`;
  nothing stopped the vendor's copy from staying broken.

* **Two answers to "where is the socket".** `useWebSocket` derived the origin by
  splitting a REST path on `/api/` and calling `.replace('http', 'ws')`
  unanchored. Both halves fail open: a base URL that stops containing `/api/`
  yields the whole REST URL, and the unanchored replace rewrites the first
  `http` anywhere in the string.

* **Half-open sockets.** A mobile connection can survive a cell handover on
  paper — `readyState` stays `OPEN`, `onclose` never fires — while nothing gets
  through. Without a liveness check the client believes it is live forever. The
  server already sends `{"action":"heartbeat"}` after 30s of silence and acks
  every `auth_refresh`, so the signal to watch was there all along.

* **Reconnecting only on `onclose`.** A brief drop left the socket down for up
  to a minute after connectivity had already returned. Only the customer app
  listened to NetInfo.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = pathlib.Path(__file__).resolve().parents[1]

APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

#: Every module that opens a socket, per app.
SOCKET_MODULES = {
    "drop-customer-app": ("hooks/useWebSocket.ts", "hooks/queries/useRiderTracking.ts"),
    "drop-rider-app": ("hooks/useWebSocket.ts",),
    "drop-vendor-app": ("hooks/useWebSocket.ts", "hooks/useOrderTracking.ts"),
}


def _code_only(source: str) -> str:
    """TypeScript with comments stripped.

    Mandatory for every "must not appear" assertion below: the docblock that
    explains why a derivation was removed has to name the derivation. Without
    this, fixing the bug and documenting the fix is what fails the test.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _sources(app: str) -> dict[str, str]:
    out = {}
    for rel in SOCKET_MODULES[app]:
        path = ROOT / app / rel
        assert path.exists(), f"{app}/{rel} is missing"
        out[rel] = path.read_text()
    return out


def _all_app_files(app: str) -> list[pathlib.Path]:
    base = ROOT / app
    return [
        p
        for d in ("app", "components", "hooks", "services", "utils", "lib", "API", "context")
        if (base / d).is_dir()
        for p in (base / d).rglob("*.ts*")
        if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts
    ]


# ── The token ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("app", APPS)
def test_every_socket_url_carries_a_token(app):
    """`_authenticate_ws` closes a tokenless socket with 1008, before any frame.

    So a `new WebSocket(...)` whose URL has no `token=` is not a socket with an
    auth problem — it is a socket that has never once delivered a message.
    """
    offenders = []
    for path in _all_app_files(app):
        source = _code_only(path.read_text())
        for match in re.finditer(r"new WebSocket\(\s*([^)]+?)\s*\)", source, re.S):
            url = match.group(1).strip()
            if "token=" in url:
                continue
            # One level of indirection: `const wsUrl = \`…?token=…\`` then
            # `new WebSocket(wsUrl)`. Resolve the identifier before judging it.
            if re.fullmatch(r"[A-Za-z_$][\w$]*", url):
                assigned = re.search(
                    rf"(?:const|let|var)\s+{re.escape(url)}\s*=\s*([^;]+);", source
                )
                if assigned and "token=" in assigned.group(1):
                    continue
            offenders.append(f"{path.relative_to(ROOT / app)}: {url[:80]}")

    assert not offenders, (
        f"{app} opens sockets with no `?token=` — the server closes each of "
        "these with 1008 before the first frame:\n  " + "\n  ".join(offenders)
    )


def test_the_server_still_refuses_a_tokenless_socket():
    """The assumption the test above rests on. If this ever stops being true,
    the rule changes rather than quietly protecting nothing."""
    source = (BACKEND / "routes" / "websocket_routes.py").read_text()
    assert re.search(
        r"async def _authenticate_ws.*?if not token:.*?await websocket\.close\(code=1008",
        source,
        re.S,
    ), "the socket authenticator no longer refuses a missing token"


# ── The origin ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("app", APPS)
def test_the_socket_origin_is_declared_once_beside_the_routes(app):
    for rel, source in _sources(app).items():
        assert "WS_BASE_URL" in source, (
            f"{app}/{rel} does not use the shared WS_BASE_URL"
        )


@pytest.mark.parametrize("app", APPS)
def test_no_module_derives_a_socket_origin_by_hand(app):
    """One question, one answer.

    `.replace('http', 'ws')` unanchored and `split('/api/')[0]` both fail open
    to something that looks plausible and is wrong.
    """
    offenders = []
    for path in _all_app_files(app):
        source = _code_only(path.read_text())
        if re.search(r"""\.replace\(\s*['"]http['"]\s*,\s*['"]ws['"]\s*\)""", source):
            offenders.append(f"{path.relative_to(ROOT / app)}: unanchored http→ws replace")
        if "split('/api/')" in source or 'split("/api/")' in source:
            offenders.append(f"{path.relative_to(ROOT / app)}: origin split out of a REST path")

    assert not offenders, (
        f"{app} builds a socket origin by hand — use WS_BASE_URL:\n  "
        + "\n  ".join(offenders)
    )


# ── Liveness and recovery ─────────────────────────────────────────────────


@pytest.mark.parametrize("app", APPS)
def test_every_socket_notices_when_it_goes_quiet(app):
    """A socket that stops delivering while `readyState` still says OPEN.

    The client must measure silence, not trust the flag.
    """
    for rel, source in _sources(app).items():
        assert "lastMessageAtRef" in source, (
            f"{app}/{rel} does not record when it last heard anything"
        )
        assert re.search(r"LIVENESS_TIMEOUT_MS|LIVENESS_TIMEOUT", source), (
            f"{app}/{rel} has no liveness timeout — a half-open socket would "
            "never be noticed"
        )


@pytest.mark.parametrize("app", APPS)
def test_every_socket_reconnects_when_the_network_returns(app):
    """`onclose` plus backoff alone left the socket down for up to a minute
    after connectivity was already back — long enough to miss the offer, the
    status change or the position the screen exists to show."""
    for rel, source in _sources(app).items():
        assert "NetInfo.addEventListener" in source, (
            f"{app}/{rel} does not reconnect on a connectivity change"
        )


@pytest.mark.parametrize("app", APPS)
def test_no_socket_gives_up_permanently(app):
    """Exhausting the backoff ladder must slow the retries, not end them.

    Stopping outright left a foregrounded app on a working network with a
    screen that had silently stopped updating and no way back short of
    navigating away.
    """
    for rel, source in _sources(app).items():
        assert re.search(r"IDLE_RETRY_MS|IDLE_RETRY", source), (
            f"{app}/{rel} stops reconnecting for good once its attempts run out"
        )


@pytest.mark.parametrize("app", APPS)
def test_the_mounted_guard_is_established_before_anything_connects(app):
    """Effects run in declaration order.

    With the mount guard declared last, a remount — Fast Refresh, StrictMode's
    double-invoke, any unmount/mount of the screen — ran `connect()` while
    `mountedRef` was still `false` from the previous teardown. Every early
    return fired and the socket silently never opened.
    """
    source = (ROOT / app / "hooks/useWebSocket.ts").read_text()

    guard = source.index("mountedRef.current = true")
    first_connect_call = source.index("connect();")

    assert guard < first_connect_call, (
        f"{app}: the mounted guard is set after the first connect() call, so a "
        "remount opens no socket at all"
    )


# ── The in-band token refresh ─────────────────────────────────────────────


@pytest.mark.parametrize("app", APPS)
def test_the_auth_refresh_asks_clerk_for_an_uncached_token(app):
    """A refresh that re-sends the token the socket already has extends nothing.

    Clerk session tokens live exactly 60s — Clerk's own guard is
    `Leeway can not exceed the token lifespan (60 seconds)` — and a bare
    `getToken()` returns the **cached** token whenever it has more than ~10s
    left. So refreshing at the 30s half-life handed the server back the very
    token it opened with: `_handle_auth_refresh` re-verified it, wrote the same
    `exp` into the session dict, acked `auth_refreshed` with that same `exp`,
    and extended nothing at all.

    `_close_if_token_expired` then closed the socket at its original expiry and
    the client reconnected one backoff step later — measured on the customer app
    at a 63.7s mean period (60s of token plus the 3-4s first backoff step),
    every socket, for ever. That is precisely the reconnect storm the in-band
    refresh exists to avoid, and the ~3.5s hole in each cycle drops any order
    update pushed while nothing is subscribed.

    So the refresh call must pass `skipCache`. The *connect* path deliberately
    does not: during a reconnect storm the cache is the thing keeping the app
    from minting a token per attempt, and a short-lived cached token there costs
    one self-correcting cycle rather than a permanent loop.
    """
    source = _code_only(_sources(app)["hooks/useWebSocket.ts"])

    refreshes = re.findall(
        r"getTokenRef\.current\(([^)]*)\)\s*;?\s*\n?\s*if\s*\(\s*fresh\s*\)", source
    )
    assert refreshes, (
        f"{app}/hooks/useWebSocket.ts: could not find the auth-refresh token "
        "call. If it moved, move this guard with it."
    )
    for args in refreshes:
        assert "skipCache" in args and "true" in args, (
            f"{app}/hooks/useWebSocket.ts refreshes the socket token with "
            f"`getTokenRef.current({args.strip()})`. Clerk serves a cached token "
            "for the first ~50s of its 60s life, so this re-sends the token the "
            "socket already holds and the server extends nothing — the socket is "
            "closed at its original `exp` and rebuilt roughly once a minute, for "
            "ever. Pass `{ skipCache: true }`."
        )


@pytest.mark.parametrize("app", APPS)
def test_the_refresh_runs_well_inside_the_token_lifetime(app):
    """A 60s token refreshed on a >=60s cadence has already expired.

    The margin is what makes the refresh a refresh rather than a race against
    `_close_if_token_expired`, which closes the moment `time.time() >= exp`.
    """
    source = _code_only(_sources(app)["hooks/useWebSocket.ts"])
    match = re.search(r"AUTH_REFRESH_INTERVAL_MS\s*=\s*([\d_]+)", source)
    assert match, f"{app}/hooks/useWebSocket.ts declares no AUTH_REFRESH_INTERVAL_MS"
    interval_ms = int(match.group(1).replace("_", ""))
    assert interval_ms <= 45_000, (
        f"{app} refreshes its socket token every {interval_ms / 1000:.0f}s. A "
        "Clerk session token lives 60s and the server closes on expiry, so this "
        "leaves no margin for a slow mint."
    )


def test_the_server_still_extends_the_session_from_the_refreshed_token():
    """The other half of the contract the client test above depends on.

    `_handle_auth_refresh` has to write the *new* payload over the session dict
    the socket loop holds — `_token_expired` reads `exp` back out of that same
    dict on every iteration. Re-binding a local instead would ack the refresh
    and still close the socket on the old expiry, which is the failure the
    client-side bug imitated.
    """
    source = (BACKEND / "routes" / "websocket_routes.py").read_text()
    body = re.search(
        r"async def _handle_auth_refresh\(.*?\n(?=\n?async def |\n?def )", source, re.S
    )
    assert body, "_handle_auth_refresh has moved or been renamed"
    assert "user.update(payload)" in body.group(0), (
        "_handle_auth_refresh must mutate the session dict in place — the socket "
        "loop holds a reference to it and reads `exp` from it every iteration."
    )
