from sqlalchemy.orm import sessionmaker, declarative_base
import os
import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.engine import make_url


from dotenv import load_dotenv

load_dotenv()  # Load variables from .env


#: The variable this platform's database URL has always been read from, kept
#: readable so a deployment that has not been updated yet still starts.
#:
#: It named a vendor. The platform moved off Neon to Supabase and the name
#: became a statement that is simply false — the next person reads `NEONDB_URL`
#: and goes looking for a Neon project. A configuration key that names the wrong
#: system is the same defect as a comment that describes code it no longer
#: matches, and this codebase treats those as defects.
LEGACY_URL_VAR = "NEONDB_URL"


def database_url() -> str | None:
    """The configured database DSN, or `None`.

    `DATABASE_URL` is the name. `NEONDB_URL` is still read, because renaming a
    variable and updating the deployment are two separate events and whichever
    happens second must not be an outage: a deploy carrying only the new name
    must start against an environment still holding the old one.

    The new name wins when both are set, so the migration is finished by adding
    the new one rather than by removing the old one in the same breath.
    """
    return os.getenv("DATABASE_URL") or os.getenv(LEGACY_URL_VAR)


DATABASE_URL = database_url()

# Say which variable is missing, rather than letting SQLAlchemy say it is not a
# URL. Unset, `create_async_engine(None)` raises
#
#     sqlalchemy.exc.ArgumentError: Expected string or URL object, got None
#
# thirty frames down a traceback that names five libraries and not the one thing
# the reader can act on. The engine is built at module scope, so this is an
# *import* failure: every module that touches a model fails to load, and the
# first thing anybody sees is `conftest.py` failing to import.
#
# It cost a CI run to diagnose for exactly that reason — the value comes from
# `.env`, which is gitignored, so every developer machine had it and the one
# environment without it was the only one that mattered.
#
# No default, deliberately. A fallback DSN would let a misconfigured deployment
# start and then fail per-request against a database nobody meant to use; this
# is the same fail-closed posture as `core/security.py` refusing to boot without
# its Clerk variables. Tests need no database — `conftest.py` yields an
# `AsyncMock` — but they do need this module to import, so CI sets a
# syntactically valid DSN that points nowhere.
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. The API cannot start without a database URL. "
        "Set it in BackendAPI/.env locally, or in the service environment on "
        "Render. For a test or build environment that needs no real database, "
        "any valid DSN will do: postgresql+asyncpg://ci:ci@localhost:5432/ci"
    )

# asyncpg does not accept sslmode/channel_binding as URL query params — strip them
DATABASE_URL = DATABASE_URL.split("?")[0]

# ── Timeouts ────────────────────────────────────────────────────────────────
#
# Both are set on the *server* at connect time, so they apply to every statement
# on the connection whether or not the code that issued it remembered to think
# about them. Neither existed, and their absence has the same shape as the pool
# being too small, because it is how the pool empties:
#
#   * `statement_timeout` — one pathological query (an unbounded console
#     aggregate, a missing index on a table that has since grown) holds its
#     connection until it finishes. Fifteen of those and the API stops answering
#     anything at all. Pool exhaustion does not present as a slow endpoint; it
#     presents as the whole service hanging, which is why it is worth failing one
#     query to prevent.
#   * `lock_timeout` — the contended paths here take rows with
#     `SELECT … FOR UPDATE`: accepting an order, moving a wallet, settling
#     bottles. Behind a transaction that has stalled, those wait forever by
#     default. Failing fast turns a platform-wide stall into one 500 the client
#     already knows how to retry.
#
# The worker gets a longer statement ceiling below: a nightly reconciliation
# legitimately runs for minutes, and a request never should.
STATEMENT_TIMEOUT_MS = os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000")
LOCK_TIMEOUT_MS = os.getenv("DB_LOCK_TIMEOUT_MS", "5000")

_SERVER_SETTINGS = {
    "statement_timeout": STATEMENT_TIMEOUT_MS,
    "lock_timeout": LOCK_TIMEOUT_MS,
    # Names this connection in `pg_stat_activity`. When the pool *is* exhausted,
    # the first question is which process is holding it.
    "application_name": os.getenv("DB_APPLICATION_NAME", "drop-api"),
}

def _requires_tls(url: str) -> bool:
    """Whether to demand TLS on the way to Postgres.

    `ssl=True` was hardcoded, which is right for every managed provider — Neon,
    Supabase, Aiven all refuse a plaintext connection and should — and refuses
    to connect at all to a Postgres on this machine, which serves no TLS. That
    single literal is what made the codebase unable to run against a local
    database, which in turn is why the test suite has always pointed at a
    managed one and why running `pytest` bills somebody.

    Decided from the host rather than an env var, so it cannot be *switched off*
    for a remote database by mistake: loopback is the only case where an
    unencrypted connection stays inside one machine and there is nothing to
    intercept. Anything else keeps TLS, whatever the caller thinks.
    """
    host = (make_url(url).host or "").lower()
    return host not in {"localhost", "127.0.0.1", "::1", ""}


def _tls_context():
    """The TLS setting for a remote database: verified, and verified against what.

    `ssl=True` means "encrypt and verify against the system trust store", which
    is correct for a provider whose certificate chains to a public CA — Neon
    does. Supabase's connection pooler does not: it serves a leaf issued by
    `Supabase Intermediate 2021 CA` under a private `Supabase Root 2021 CA`,
    which no system trust store carries, so verification fails outright with
    `self-signed certificate in certificate chain`.

    The tempting fix is to stop verifying — `ssl="require"` encrypts and asks no
    questions, and it is what most write-ups reach for. It is the wrong trade
    on this database. Encryption without verification stops somebody reading the
    connection and does nothing about somebody *being* the other end of it, and
    what travels over this one is every customer record, every rider's national
    ID reference and every wallet movement on the platform.

    So `DB_SSL_ROOT_CERT` names a CA bundle to verify against instead of the
    system store. Set it for Supabase (`certs/supabase-root-2021.crt`, committed
    — a CA certificate is public by design), leave it unset for a provider with
    a publicly-rooted chain. Either way the connection is verified; the variable
    only chooses the trust anchor, and there is deliberately no value of it that
    turns verification off.
    """
    root_cert = os.getenv("DB_SSL_ROOT_CERT")
    if not root_cert:
        return True

    path = root_cert if os.path.isabs(root_cert) else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), root_cert
    )
    if not os.path.exists(path):
        # Failing here beats falling back to the system store: a silent fallback
        # would connect fine against Neon and fail only on the provider the
        # variable was set for, at whatever hour that deploy happened.
        raise RuntimeError(
            f"DB_SSL_ROOT_CERT points at {path}, which does not exist. "
            "It must name a CA bundle readable by the process."
        )

    context = ssl.create_default_context(cafile=path)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


_CONNECT_ARGS: dict = {"server_settings": _SERVER_SETTINGS}
if _requires_tls(DATABASE_URL):
    _CONNECT_ARGS["ssl"] = _tls_context()

#: The same arguments, under a name other modules may import.
#:
#: `alembic/env.py` builds its *own* engine from `DATABASE_URL` alone, so
#: without this it connected with asyncpg's defaults: no CA bundle, and
#: therefore no verification of the server on the other end. Against
#: Supabase that is the difference between a verified connection and an
#: encrypted one to whoever answered — over a link carrying every customer
#: record and every wallet movement. `scripts/predeploy.py` drives
#: `command.upgrade` through that same file, so it inherited the gap too.
CONNECT_ARGS: dict = _CONNECT_ARGS

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # F-031 FIX
    pool_pre_ping=True,
    pool_recycle=1800,
    poolclass=AsyncAdaptedQueuePool,  # F-027 FIX: real pool, not NullPool
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    # Wait this long for a free connection, then fail. Unset, SQLAlchemy waits 30
    # seconds — long enough that the client has already timed out and retried,
    # which adds a *second* request queuing for the same exhausted pool. Failing
    # in five gives the caller an error it can surface instead of a hang.
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "5")),
    connect_args=_CONNECT_ARGS,
)
AsyncSessionLocal = sessionmaker (bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False)

Base = declarative_base()

# There is deliberately no `create_all` helper here. The schema is owned by
# Alembic — the repository head `e6b2c8d40f17` is gated on purpose, and a
# `Base.metadata.create_all` would build a database that no migration has ever
# run against, silently diverging from every deployed one.