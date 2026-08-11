"""A crash that breaks a screen is reported, in all three apps.

`ErrorBoundary.componentDidCatch` is the only place a fatal render error is
observable. The boundary catches it, renders a fallback, and the app carries on
looking healthy — so if that method does not report, the one class of error that
actually breaks a screen for a real user is the only class that never reaches
Sentry. It is invisible from the outside by construction: nothing crashes, no
request fails, and the logs are clean.

The vendor app's boundary carried `// TODO: In production, report to
Sentry/Crashlytics` while `utils/sentry.ts` was initialised and working, and
that is the app where a broken screen costs a shop its orders.

Structural rather than behavioural: there is no way to make a React Native
boundary catch inside pytest, and a check that the reporting *call* is present
is exactly the invariant that was broken.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

BOUNDARY = "components/common/ErrorBoundary.tsx"
SENTRY = "utils/sentry.ts"


def _boundary(app: str) -> str:
    path = ROOT / app / BOUNDARY
    assert path.exists(), f"{app} has no {BOUNDARY}"
    return path.read_text()


def _did_catch_body(source: str) -> str:
    """The body of `componentDidCatch`, up to the closing brace at its indent."""
    start = source.index("componentDidCatch(")
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
    raise AssertionError("componentDidCatch body never closed")


@pytest.mark.parametrize("app", APPS)
def test_the_error_boundary_reports_the_crash(app):
    body = _did_catch_body(_boundary(app))

    assert "captureError(" in body, (
        f"{app}'s ErrorBoundary.componentDidCatch does not call captureError. "
        "The boundary swallows the crash, so this is the only place a fatal "
        "render error can be reported from."
    )
    assert "componentStack" in body, (
        f"{app} reports the error without the component stack — the one piece "
        "of context that says which screen broke."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_boundary_imports_the_reporter_it_calls(app):
    source = _boundary(app)
    assert re.search(r"import \{[^}]*\bcaptureError\b[^}]*\} from ['\"]@/utils/sentry['\"]", source), (
        f"{app}'s ErrorBoundary calls captureError without importing it."
    )


@pytest.mark.parametrize("app", APPS)
def test_no_app_still_carries_a_todo_instead_of_reporting(app):
    """The specific shape the vendor app was in: a comment where a call belongs.

    A commented-out `Sentry.captureException` reads, to anybody skimming, as
    reporting that is present and merely disabled.
    """
    body = _did_catch_body(_boundary(app))
    lowered = body.lower()

    assert "todo" not in lowered, f"{app}'s componentDidCatch still carries a TODO"
    assert "sentry.captureexception" not in lowered.replace(" ", ""), (
        f"{app} has a commented-out or direct Sentry call in componentDidCatch "
        "— go through `captureError`, which no-ops when the DSN is unset."
    )


@pytest.mark.parametrize("app", APPS)
def test_every_app_actually_initialises_sentry(app):
    """Reporting into an uninitialised SDK is the same silence, one layer down."""
    sentry = ROOT / app / SENTRY
    assert sentry.exists(), f"{app} has no {SENTRY}"
    assert "export function captureError" in sentry.read_text(), (
        f"{app}'s {SENTRY} does not export captureError"
    )

    layout = (ROOT / app / "app/_layout.tsx").read_text()
    assert "initSentry" in layout, (
        f"{app} never calls initSentry from its root layout, so captureError "
        "reports into an SDK that was never started."
    )
