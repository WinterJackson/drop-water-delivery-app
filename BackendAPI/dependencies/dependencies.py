from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import AsyncSessionLocal


async def _refresh_platform_config(session: AsyncSession) -> None:
    """Bring this process's business configuration up to date, once per request.

    The pricing and discovery code reads the configuration **synchronously** —
    `DispatchPolicy.get_delivery_fee`, `calculate_revenue_splits` and
    `discoverable_vendor` are pure functions called from routes, from the seeder
    and from tests, and threading an `await` through all of them to fetch a rate
    would be a large change for no gain.

    So the refresh happens here instead: one cheap Redis GET at the start of
    every request that touches the database, and a single-table SELECT only when
    something has actually changed. Doing it here rather than at each pricing
    call site is what stops a new endpoint quietly serving last week's fees.

    It must never take a request down. If the settings table or Redis is
    unreachable the process keeps the snapshot it has, or falls back to the
    values the platform shipped with — both better than a 500 on every route.
    """
    try:
        from services import platform_config_service

        await platform_config_service.ensure_fresh(session)
    except Exception:  # pragma: no cover — defensive; the service logs the cause
        pass


async def get_db():
  async with AsyncSessionLocal() as session:
    try:
      await _refresh_platform_config(session)
      yield session
    except Exception:
      await session.rollback()
      raise


@asynccontextmanager
async def get_db_session():
    """Standalone async context manager for non-FastAPI contexts (WebSocket, background tasks)."""
    async with AsyncSessionLocal() as session:
        try:
            await _refresh_platform_config(session)
            yield session
        except Exception:
            await session.rollback()
            raise
