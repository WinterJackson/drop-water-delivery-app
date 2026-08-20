"""An email never fails the transaction that earned it.

`POST /api/auth/create_user` committed the account row and then called
`send_welcome_email` bare. `email_service._send` is wrapped in `tenacity`, so a
provider that is rate-limiting, down, or refusing the address gets retried
*inside the request* and then raises — and the caller sees
"500: Internal server error. Please try again later." at the moment they
finished onboarding, with their account already in the database.

Reproduced end to end against a running API: the `Users` row was written and
committed, `RetryError[ValidationError]` came back out of the mailer, and the
request returned 500. It self-heals only for someone who retries, because the
second attempt takes the `existing_user` branch.

All three registration routes had it — customer, vendor and rider — while
`admin_support_routes` and `broadcast_service` already wrapped their sends,
with the reasoning written down: the committed record is what matters and the
message is best effort. This is the same rule the platform applies to pushes
via `queue_push` / `dispatch_background`.

The check is AST-based rather than a text match: it asks whether the call sits
inside a `try`, which is the property that actually matters, and so cannot fire
on a call that is legitimately guarded in some other shape.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDERS = ("routes", "services", "jobs")

#: The wrapper that makes a send best-effort. A call handed to it is guarded.
WRAPPER = "_best_effort_email"


def _is_email_send(node: ast.Call) -> bool:
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name.startswith("send_") and name.endswith(("_email", "_approved"))


def _modules():
    for folder in FOLDERS:
        base = ROOT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            yield path


def _unguarded(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    # Mark every node that sits inside a `try` body, and every call that is
    # being handed to the best-effort wrapper.
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    guarded.add(id(inner))
        if isinstance(node, ast.Call):
            callee = node.func
            callee_name = (
                callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            )
            if callee_name == WRAPPER:
                for arg in node.args:
                    guarded.add(id(arg))

    offences = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_email_send(node) and id(node) not in guarded:
            try:
                label = path.relative_to(ROOT)
            except ValueError:  # a synthetic file from the non-vacuity tests
                label = path
            offences.append(f"{label}:{node.lineno}")
    return offences


@pytest.mark.parametrize("path", list(_modules()), ids=lambda p: str(p.name))
def test_every_email_send_is_guarded(path):
    offences = _unguarded(path)
    assert not offences, (
        "This send can raise and fail a request whose work is already "
        "committed. Wrap it in try/except or hand it to "
        f"`{WRAPPER}`:\n  " + "\n  ".join(offences)
    )


def test_the_check_can_actually_see_an_unguarded_send(tmp_path):
    """Non-vacuity: the shape this guard exists to catch must trip it."""
    bad = tmp_path / "bad.py"
    bad.write_text("send_welcome_email(to='a@b.c')\n")
    assert _unguarded(bad), "the guard no longer detects a bare send"


def test_a_guarded_send_is_accepted(tmp_path):
    """And the two legitimate shapes must not trip it."""
    ok = tmp_path / "ok.py"
    ok.write_text(
        "try:\n"
        "    send_welcome_email(to='a@b.c')\n"
        "except Exception:\n"
        "    pass\n"
        "_best_effort_email(send_welcome_email, to='a@b.c')\n"
    )
    assert not _unguarded(ok)
