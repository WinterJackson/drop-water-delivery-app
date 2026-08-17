"""Each surface reports crashes to its own Sentry project, and builds carry one.

Two defects, and neither produced an error anywhere:

**All four surfaces shared one DSN — the backend's.** `EXPO_PUBLIC_` inlines a
value into the JS bundle, so the key for the project holding every server error
shipped inside three mobile apps. A DSN is a *write* endpoint: anyone who
unzipped an APK could inject events into the server's error stream, or exhaust
its quota until real errors were dropped. Beyond that, one stream for four
surfaces means "the rider app is crashing" and "the API is throwing" are the
same inbox, and no alert rule can distinguish them.

**No production build carried a DSN at all.** The `production` profile in each
`eas.json` pinned the Clerk key and the backend URL and nothing else, so unless
somebody had set `EXPO_PUBLIC_SENTRY_DSN` in EAS-hosted state, `initSentry`'s
`if (process.env.EXPO_PUBLIC_SENTRY_DSN)` was false, `Sentry.init` never ran,
and `captureError` became a silent no-op — including the call in
`ErrorBoundary.componentDidCatch`, which is the only place that class of error
is observable at all. The boundary still swallowed the crash. Nothing recorded
it.

Pinned in `eas.json` rather than EAS-hosted deliberately: the value is inlined
into the bundle and therefore public either way, so hiding it in Expo's service
protects nothing while making the build depend on state no reviewer can see —
which is exactly how the gap opened. `test_crash_reporting.py` asserts the
*call sites* still report; this asserts they have somewhere to report to.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

_DSN_LINE = re.compile(r'^\s*(?:EXPO_PUBLIC_)?SENTRY_DSN\s*=\s*"?([^"\n]+)"?', re.M)


def _env_dsn(path: pathlib.Path) -> str | None:
    if not path.is_file():
        return None
    match = _DSN_LINE.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def _profile_env(app: str) -> dict:
    data = json.loads((REPO / app / "eas.json").read_text(encoding="utf-8"))
    return data.get("build", {}).get("production", {}).get("env", {}) or {}


def _project_id(dsn: str) -> str:
    """The trailing path segment — Sentry's project id."""
    return dsn.rstrip("/").rsplit("/", 1)[-1]


def test_every_production_profile_pins_a_sentry_dsn():
    missing = [app for app in APPS if not _profile_env(app).get("EXPO_PUBLIC_SENTRY_DSN")]

    assert not missing, (
        "these apps build without crash reporting — ErrorBoundary swallows the "
        "crash and nothing records it: " + ", ".join(missing)
    )


def test_no_two_surfaces_share_a_sentry_project():
    """The defect stated directly rather than by its symptom."""
    dsns = {app: _profile_env(app)["EXPO_PUBLIC_SENTRY_DSN"] for app in APPS}
    backend = _env_dsn(REPO / "BackendAPI" / ".env")
    if backend:
        dsns["BackendAPI"] = backend

    by_project: dict[str, list[str]] = {}
    for surface, dsn in dsns.items():
        by_project.setdefault(_project_id(dsn), []).append(surface)

    shared = {p: s for p, s in by_project.items() if len(s) > 1}

    assert not shared, (
        "these surfaces report into one Sentry project, so no alert rule can "
        "tell them apart and one surface's volume drops another's events:\n  "
        + "\n  ".join(f"project {p} ← {surfaces}" for p, surfaces in shared.items())
    )


def test_no_app_ships_the_backends_dsn():
    """The specific exposure: a server-error write endpoint inside an APK."""
    backend = _env_dsn(REPO / "BackendAPI" / ".env")
    if backend is None:
        return  # no local backend env to compare against

    offenders = [
        app for app in APPS
        if _project_id(_profile_env(app)["EXPO_PUBLIC_SENTRY_DSN"]) == _project_id(backend)
    ]

    assert not offenders, (
        "the backend's Sentry project is reachable from a shipped app bundle; "
        "anyone with the APK can write to the server's error stream: "
        + ", ".join(offenders)
    )


def test_each_apps_local_env_matches_what_it_builds_with():
    """A local DSN that differs from the build's sends development crashes to
    a project nobody watches — and makes the build's value untestable by
    running the app."""
    mismatched = []
    for app in APPS:
        local = _env_dsn(REPO / app / ".env")
        built = _profile_env(app)["EXPO_PUBLIC_SENTRY_DSN"]
        if local is not None and local != built:
            mismatched.append(f"{app}: .env={_project_id(local)} eas.json={_project_id(built)}")

    assert not mismatched, "local and build DSNs disagree:\n  " + "\n  ".join(mismatched)
