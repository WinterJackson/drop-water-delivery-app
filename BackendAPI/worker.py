import asyncio
import logging
import os
from arq import Worker
from arq.connections import RedisSettings
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ARQ Redis Settings mapping to the app's REDIS_URL
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# Extract host, port, db from URL to construct RedisSettings (simplistic parse for standard upstash/redis urls)
# Upstash uses rediss:// and requires ssl=True in standard redis, but for ARQ it accepts standard redis.asyncio pool.
# We will just pass the from_url connection pool to ARQ if possible, or use standard RedisSettings.from_url() in a custom way.
# ARQ has RedisSettings.from_dsn(redis_url) but we have to ensure it handles "rediss://" correctly.
# According to ARQ docs: RedisSettings.from_dsn(url) handles standard urls.

# If the URL is an upstash rediss:// url, ARQ might complain if it doesn't recognize it.
if redis_url.startswith("rediss://"):
    # Upstash typically doesn't need strict SSL cert checks in Python redis driver, but passing the DSN usually works.
    pass

redis_settings = RedisSettings.from_dsn(redis_url)

# --- Background Task Functions ---

async def startup(ctx):
    logger.info("ARQ Worker starting up...")

async def shutdown(ctx):
    logger.info("ARQ Worker shutting down...")

async def send_push_message_task(ctx, to_tokens, title, body, data=None):
    from services.expo_push_service import _execute_push_chunks
    logger.info(f"ARQ Worker Processing Push Notification to {len(to_tokens)} recipients.")
    await _execute_push_chunks(to_tokens, title, body, data)
    return f"Processed {len(to_tokens)} tokens"

async def flush_gps_tracking_logs_task(ctx):
    from services.deliverer_service import flush_tracking_logs
    await flush_tracking_logs()
    return "Flushed tracking logs"

async def auto_resolve_bottle_rejections_task(ctx):
    from jobs.auto_resolve_bottle_rejections import run_auto_resolve_bottle_rejections
    await run_auto_resolve_bottle_rejections()
    return "Swept bottle rejections"

async def auto_cancel_pending_orders_task(ctx):
    from jobs.auto_cancel_pending_orders import run_auto_cancel_orders
    await run_auto_cancel_orders()
    return "Auto-cancelled pending orders"

async def evaluate_platinum_riders_task(ctx):
    from jobs.rider_tier_job import evaluate_platinum_riders
    await evaluate_platinum_riders()
    return "Evaluated platinum riders"

async def process_pending_refunds_task(ctx):
    """Reverse M-Pesa payments for orders cancelled after payment.

    Customer cancellation flags the order `refund_pending`; without this job the
    only way a refund ever ran was an operator remembering to POST the admin
    endpoint. The underlying sweep claims rows with FOR UPDATE SKIP LOCKED, so it
    is safe even if several workers tick at once.
    """
    from dependencies.dependencies import get_db_session
    from services.refund_service import process_all_pending_refunds

    async with get_db_session() as session:
        result = await process_all_pending_refunds(session)
    return result.get("message", "Processed refunds")

async def reassign_unassigned_orders_task(ctx):
    """Re-offer orders that the 20-second tiered dispatch failed to place.

    Previously only ran when a rider happened to toggle their availability, so an
    order nobody accepted could sit `unassigned` indefinitely.
    """
    from dependencies.dependencies import get_db_session
    from services.order_service import reassign_unassigned_orders

    async with get_db_session() as session:
        result = await reassign_unassigned_orders(session)
    return f"Re-offered {result.get('reassigned', 0)} unassigned order(s)"

async def check_push_receipts_task(ctx):
    """Resolve Expo push receipts and purge tokens Expo reports as unregistered.

    A send returns a *ticket* (accepted), not a delivery result. `DeviceNotRegistered`
    — an uninstalled app or a rotated token — is normally only visible in the
    *receipt*, fetched later, so without this sweep dead tokens stayed attached to
    accounts forever.
    """
    from services.push_receipt_service import process_due_receipts, prune_stale_receipts

    pruned = await prune_stale_receipts()
    result = await process_due_receipts()
    return f"Checked {result.get('checked', 0)} receipt(s), purged {result.get('purged', 0)}, pruned {pruned}"


async def stale_asset_monitor_task(ctx):
    from jobs.stale_asset_monitor import run_stale_asset_monitor
    await run_stale_asset_monitor()
    return "Swept stale assets"


class WorkerSettings:
    functions = [
        send_push_message_task,
        flush_gps_tracking_logs_task,
        auto_resolve_bottle_rejections_task,
        auto_cancel_pending_orders_task,
        evaluate_platinum_riders_task,
        process_pending_refunds_task,
        reassign_unassigned_orders_task,
        check_push_receipts_task,
        stale_asset_monitor_task,
    ]
    redis_settings = redis_settings
    on_startup = startup
    on_shutdown = shutdown
    # Automatically execute cron jobs
    cron_jobs = []
    # Belt and braces against duplicate cron execution if more than one worker is
    # ever running: ARQ takes a Redis lock per cron job keyed on the scheduled
    # second, so only one worker performs each tick.
    max_jobs = 20

# ── Scheduling lives outside this process ────────────────────────────────
# The schedule is owned by cron-job.org, which calls `POST /api/cron/{slug}`;
# that endpoint enqueues the task below and the worker executes it. See
# `routes/cron_routes.py` and `docs/cron-jobs.md`.
#
# ARQ's own scheduler only ticks while this worker is up and alone. If it is
# asleep, restarting, or scaled to two replicas, the schedule either stops with
# nothing reporting it or fires twice. An external scheduler makes missed runs
# visible and alertable, which for the auto-cancel and refund sweeps is the
# difference between a delayed refund and one nobody ever notices.
#
# Set `ARQ_INTERNAL_CRON=1` to restore the in-process schedule — useful on a
# single dev machine with no public URL for cron-job.org to reach.
if os.getenv("ARQ_INTERNAL_CRON", "0").lower() in ("1", "true", "yes"):
    from arq.cron import cron

    WorkerSettings.cron_jobs = [
        cron(flush_gps_tracking_logs_task, second=set(range(0, 60, 10))),
        cron(auto_resolve_bottle_rejections_task, second=0),
        cron(auto_cancel_pending_orders_task, minute=set(range(0, 60, 5))),
        cron(process_pending_refunds_task, minute=set(range(0, 60, 2))),
        cron(reassign_unassigned_orders_task, minute=set(range(0, 60, 3))),
        cron(check_push_receipts_task, minute=set(range(0, 60, 10))),
        cron(stale_asset_monitor_task, hour=3, minute=0),
        cron(evaluate_platinum_riders_task, hour=0, minute=0),
    ]
    logger.warning("ARQ internal cron enabled — cron-job.org schedules must be paused.")
