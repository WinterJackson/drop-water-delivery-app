"""Every build that produces an installable artifact gets its own versionCode.

All three apps set `cli.appVersionSource: "remote"`, which moves the Android
`versionCode` out of `app.json` and into state EAS holds per project. That half
was right — a version number in the repository is one two branches can both
claim, and `app.json` in all three declares no `versionCode` at all.

What was missing is the half that moves it. `appVersionSource: remote` only says
*where* the number lives; `autoIncrement` on a build profile is what advances it.
Without it EAS reads the stored number, uses it, and puts it back unchanged — so
the first three release builds ever made were all `versionCode 1`, and the
counter EAS held was still 1 afterwards.

A repeated versionCode is invisible until it is expensive:

  * The handset compares versionCodes, not commits. Installing build N+1 over
    build N at the same versionCode is neither an upgrade nor a downgrade, so
    `adb install` needs `-d` and the launcher may refuse outright — while
    everyone involved believes the new build is on the phone. Testing the
    previous binary and reporting on it is worse than a failed install.
  * Google Play rejects an upload whose versionCode already exists, at the end
    of a build-and-upload cycle rather than the start.
  * `expo-updates` and the forced-update floor both order releases by version.

`preview` carries it too, and deliberately. Preview is the internal-testing APK
profile — the builds most likely to be installed one over another on the same
handset, which is exactly where two builds sharing a number does its damage. A
profile that produces an artifact somebody installs needs a distinct number, and
`development` is excluded because it builds a dev client that loads JS from a
server rather than an artifact anybody keeps.

This cannot be caught by building. Both configurations build successfully; the
difference only shows up on the second install or the second upload.
"""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

#: Profiles whose output is an artifact somebody installs and keeps. A
#: `development` build is a dev client pointed at a Metro server, so two of them
#: sharing a versionCode costs nothing.
INSTALLABLE_PROFILES = ("preview", "production")


def _eas(app: str) -> dict:
    return json.loads((REPO / app / "eas.json").read_text(encoding="utf-8"))


def test_every_app_keeps_its_version_outside_the_repository():
    """The premise the rest of this file depends on. With `appVersionSource`
    unset or "local", the number comes from `app.json` and `autoIncrement`
    rewrites a tracked file on every build — which two branches then conflict
    over, and which a build from a detached commit silently reverts."""
    wrong = {
        app: _eas(app).get("cli", {}).get("appVersionSource")
        for app in APPS
        if _eas(app).get("cli", {}).get("appVersionSource") != "remote"
    }

    assert not wrong, (
        "these apps do not hold their version remotely, so the version number "
        "is a tracked file two branches can both claim: " + repr(wrong)
    )


def test_no_app_declares_a_version_code_in_app_json():
    """With the source set to remote, a `versionCode` in `app.json` is ignored.
    Leaving one there states a number that nothing reads — the same defect as a
    second lockfile or a second wire-shape declaration, and the next person
    reasonably believes it."""
    offenders = {}
    for app in APPS:
        expo = json.loads((REPO / app / "app.json").read_text(encoding="utf-8"))["expo"]
        declared = (expo.get("android") or {}).get("versionCode")
        if declared is not None:
            offenders[app] = declared

    assert not offenders, (
        "these apps declare an android.versionCode that EAS ignores because the "
        "version is held remotely; delete it rather than maintaining a number "
        "with no effect: " + repr(offenders)
    )


def test_every_installable_profile_advances_the_version():
    """The defect itself. `appVersionSource: remote` says where the number
    lives; `autoIncrement` is what moves it."""
    offenders = []
    for app in APPS:
        build = _eas(app).get("build", {})
        for profile in INSTALLABLE_PROFILES:
            config = build.get(profile)
            if config is None:
                continue
            if config.get("autoIncrement") is not True:
                offenders.append(f"{app}:{profile}")

    assert not offenders, (
        "these profiles produce an installable artifact without advancing the "
        "versionCode, so every build they ever make carries the same number — a "
        "handset cannot tell two of them apart and Play rejects the second "
        "upload:\n  " + "\n  ".join(offenders)
    )
