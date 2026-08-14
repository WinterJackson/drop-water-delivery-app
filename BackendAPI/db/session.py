from sqlalchemy.orm import sessionmaker, declarative_base
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import AsyncAdaptedQueuePool


from dotenv import load_dotenv

load_dotenv()  # Load variables from .env


DATABASE_URL = os.getenv("NEONDB_URL")

# asyncpg does not accept sslmode/channel_binding as URL query params — strip them
if DATABASE_URL:
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
    connect_args={"ssl": True, "server_settings": _SERVER_SETTINGS},
)
AsyncSessionLocal = sessionmaker (bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False)

Base = declarative_base()

# There is deliberately no `create_all` helper here. The schema is owned by
# Alembic — the repository head `e6b2c8d40f17` is gated on purpose, and a
# `Base.metadata.create_all` would build a database that no migration has ever
# run against, silently diverging from every deployed one.