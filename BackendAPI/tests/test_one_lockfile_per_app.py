"""An app declares one lockfile, so one package manager can be resolved.

`drop-customer-app` carried both `pnpm-lock.yaml` and `package-lock.json`, and
nothing anywhere chose between them. Every command a developer runs names its
manager — `pnpm install` locally, `pnpm/action-setup` in `.github/workflows/ci.yml`
— so both read the pnpm lockfile and the npm one was never opened by anything.
It sat two months stale (2026-06-16 against 2026-08-15) with nothing to notice.

EAS Build is the one consumer that *infers* the manager from the files present,
and it resolves npm first. So the release build ran `npm ci --include=dev`
against a lockfile two months out of step with `package.json`, which `npm ci`
refuses by design. Three production builds errored in the "Install dependencies"
phase — eight seconds each, with a message naming only the phase — while the
rider and vendor apps, which carry a pnpm lockfile alone, built from the same
commit without complaint.

This is the second-table defect the guide describes for wire shapes, one layer
down: two declarations of the same thing, a consumer that silently picks one,
and the copy nobody reads drifting freely because nothing reads it. Resolving it
is not a matter of keeping the two in sync — the app has one package manager,
and the lockfile of any other is a file whose only possible effect is to be
picked by mistake.

The apps' own suites cannot catch this: `pnpm install` succeeds either way. It
has to be asserted about the files.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app", "drop-admin")

# Every lockfile a Node package manager writes, with the manager it commits the
# project to. `pnpm-lock.yaml` is this repository's choice, in all four surfaces.
LOCKFILES = {
    "pnpm-lock.yaml": "pnpm",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "bun.lock": "bun",
}

EXPECTED = "pnpm-lock.yaml"


def _lockfiles(app: str) -> list[str]:
    return sorted(name for name in LOCKFILES if (REPO / app / name).is_file())


def test_no_app_declares_two_package_managers():
    offenders = {app: found for app in APPS if len(found := _lockfiles(app)) > 1}

    assert not offenders, (
        "these surfaces carry more than one lockfile. Every command written down "
        "names its own manager, so the extra one is read by nothing here and "
        "drifts — until EAS Build, which infers the manager from the files "
        "present and resolves npm before pnpm, runs the stale one and fails the "
        "release build in the Install dependencies phase:\n  "
        + "\n  ".join(
            f"{app}: {', '.join(f'{f} ({LOCKFILES[f]})' for f in found)}"
            for app, found in offenders.items()
        )
    )


def test_every_app_has_the_lockfile_its_tooling_actually_uses():
    """The other half: a surface with *no* pnpm lockfile is one where
    `--frozen-lockfile` has nothing to freeze, and CI resolves fresh versions on
    every run."""
    missing = [app for app in APPS if not (REPO / app / EXPECTED).is_file()]

    assert not missing, (
        f"these surfaces have no {EXPECTED}, so nothing pins their dependency "
        "tree and every install may resolve differently: " + ", ".join(missing)
    )


def test_a_stray_lockfile_cannot_be_reintroduced_by_being_untracked():
    """`.gitignore`-ing the stray file would hide it from review while leaving it
    on the machine that generated it — and EAS uploads from the git working
    copy, so an ignored lockfile is absent from the build and a tracked one is
    present. Either state has to be visible here, which means asserting about
    the filesystem rather than about git."""
    for app in APPS:
        found = _lockfiles(app)
        assert found == [EXPECTED], (
            f"{app} resolves to {found or 'no lockfile'}; expected exactly "
            f"[{EXPECTED!r}]. Delete the others rather than ignoring them — a "
            "lockfile for a manager nothing runs has no effect except to be "
            "chosen by a tool that infers."
        )
