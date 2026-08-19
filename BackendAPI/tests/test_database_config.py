"""The database URL is resolved in one place, and TLS cannot be turned off.

Two rules, both learned by moving this platform off Neon and onto Supabase.

**One resolver.** The DSN was read as `os.getenv("NEONDB_URL")` in seven places.
That is survivable while the name is right and fatal when it changes: renaming it
meant finding all seven, and the one that got missed would have been a script
that still worked on a developer's machine — where the old variable lingers in a
shell — and failed nowhere else. `db/session.database_url()` is the one reader,
and it accepts the old name as a deprecated fallback so that renaming the
variable and updating a deployment need not be the same event.

**TLS is a choice about the trust anchor, never about whether to verify.**
Supabase's pooler is issued by a private CA no system trust store carries, so
`ssl=True` fails against it. The reflex fix is `ssl="require"`, which encrypts
and verifies nothing — and the difference between those two is the difference
between somebody being unable to read this connection and somebody being unable
to *be* the far end of it. What crosses it is every customer record, every
rider's identity-document reference and every wallet movement on the platform.
"""

import ast
import os
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Where the DSN may legitimately be read from the environment.
THE_RESOLVER = "db/session.py"

SOURCE_DIRS = ("services", "routes", "jobs", "scripts", "db", "core", "seed")


def _python_files():
    for directory in SOURCE_DIRS:
        root = BACKEND / directory
        if root.exists():
            yield from sorted(root.rglob("*.py"))


def test_the_database_url_is_read_in_one_place():
    """No module resolves the DSN for itself.

    Seven did. The rename that moved this platform to Supabase had to touch every
    one of them, and a missed reader is invisible on any machine where the old
    variable is still exported.
    """
    offenders = []
    for path in _python_files():
        relative = path.relative_to(BACKEND).as_posix()
        if relative == THE_RESOLVER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = ast.unparse(node.func)
            if target not in {"os.getenv", "os.environ.get"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value in {"DATABASE_URL", "NEONDB_URL"}:
                offenders.append(f"{relative}:{node.lineno}")

    assert not offenders, (
        "The database URL is read from the environment outside "
        f"`{THE_RESOLVER}`. There is one resolver — `db.session.database_url()` "
        "— and it exists so that renaming the variable is one edit rather than "
        "seven:\n  " + "\n  ".join(offenders)
    )


def test_the_deprecated_name_still_resolves_and_the_new_one_wins():
    """Renaming a variable and updating a deployment are two events.

    Whichever happens second must not be an outage: a deploy carrying only the
    new name has to start against an environment still holding the old one.
    """
    from db.session import database_url

    original = {k: os.environ.get(k) for k in ("DATABASE_URL", "NEONDB_URL")}
    try:
        os.environ.pop("DATABASE_URL", None)
        os.environ["NEONDB_URL"] = "postgresql+asyncpg://legacy/db"
        assert database_url() == "postgresql+asyncpg://legacy/db", (
            "The deprecated `NEONDB_URL` no longer resolves, so a deployment "
            "that has not been updated yet fails to boot."
        )

        os.environ["DATABASE_URL"] = "postgresql+asyncpg://current/db"
        assert database_url() == "postgresql+asyncpg://current/db", (
            "`NEONDB_URL` outranks `DATABASE_URL`, so the migration can never "
            "be finished by adding the new name."
        )

        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("NEONDB_URL", None)
        assert database_url() is None
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql+asyncpg://u:p@aws-0-eu-central-1.pooler.supabase.com:5432/postgres", True),
        ("postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb", True),
        ("postgresql+asyncpg://u:p@db.example.supabase.co:5432/postgres", True),
        ("postgresql+asyncpg://drop:drop@localhost:5434/drop", False),
        ("postgresql+asyncpg://drop:drop@127.0.0.1:5434/drop", False),
    ],
)
def test_tls_is_required_for_every_host_except_loopback(url: str, expected: bool):
    """Derived from the host, not configured.

    An env var would be a switch somebody could set for a remote database, and
    the whole point is that there is no such switch. Loopback is the only case
    where an unencrypted connection stays inside one machine.
    """
    from db.session import _requires_tls

    assert _requires_tls(url) is expected


def test_no_setting_can_disable_certificate_verification():
    """`DB_SSL_ROOT_CERT` chooses *what* to verify against, never *whether* to.

    The reflex fix for Supabase's private CA is `ssl="require"` — encrypt, ask no
    questions. This asserts the code offers no way to reach that state: with the
    variable unset the connection verifies against the system trust store, and
    with it set it verifies against the named bundle.
    """
    import ssl

    from db.session import _tls_context

    original = os.environ.get("DB_SSL_ROOT_CERT")
    try:
        os.environ.pop("DB_SSL_ROOT_CERT", None)
        assert _tls_context() is True, (
            "Unset, TLS must fall back to the system trust store — verified."
        )

        os.environ["DB_SSL_ROOT_CERT"] = "certs/supabase-root-2021.crt"
        context = _tls_context()
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED, "verification was disabled"
        assert context.check_hostname is True, "hostname checking was disabled"
    finally:
        if original is None:
            os.environ.pop("DB_SSL_ROOT_CERT", None)
        else:
            os.environ["DB_SSL_ROOT_CERT"] = original


def test_a_missing_ca_bundle_raises_rather_than_falling_back():
    """A silent fallback to the system store would connect against a
    publicly-rooted provider and fail only against the one the variable was set
    for — at whatever hour that deploy happened."""
    from db.session import _tls_context

    original = os.environ.get("DB_SSL_ROOT_CERT")
    try:
        os.environ["DB_SSL_ROOT_CERT"] = "certs/definitely-not-here.crt"
        with pytest.raises(RuntimeError, match="does not exist"):
            _tls_context()
    finally:
        if original is None:
            os.environ.pop("DB_SSL_ROOT_CERT", None)
        else:
            os.environ["DB_SSL_ROOT_CERT"] = original


def test_the_supabase_ca_is_committed_and_current():
    """Render needs the bundle on disk. A CA certificate is public by
    construction, so it is committed rather than configured."""
    from datetime import datetime, timezone

    bundle = BACKEND / "certs" / "supabase-root-2021.crt"
    assert bundle.exists(), f"{bundle} is missing; every Supabase deploy fails to connect"

    text = bundle.read_text(encoding="utf-8")
    assert "BEGIN CERTIFICATE" in text

    # Expiry is worth failing on early: the symptom otherwise is every database
    # connection refusing at once, on a date nobody chose.
    try:
        from cryptography import x509
    except ImportError:
        pytest.skip("cryptography is not installed")

    certificate = x509.load_pem_x509_certificate(bundle.read_bytes())
    remaining = certificate.not_valid_after_utc - datetime.now(timezone.utc)
    assert remaining.days > 90, (
        f"The Supabase CA expires in {remaining.days} days. Download the current "
        "one from Project Settings → Database → SSL Configuration."
    )
