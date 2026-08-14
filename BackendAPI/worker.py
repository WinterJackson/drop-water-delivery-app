import logging
import os
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


async def release_unclaimed_cash_task(ctx):
    """Free float locked to cash orders nobody delivered.

    Float is committed from the moment a rider accepts until the order reaches a
    terminal state, so one order taken and forgotten locked that money
    indefinitely — and the customer waited on a delivery nobody was bringing.
    Frequent, because both halves of that are time-sensitive: every minute is a
    rider who cannot accept work and a customer who has not been told.
    """
    from dependencies.dependencies import get_db_session
    from services import cod_policy

    async with get_db_session() as session:
        result = await cod_policy.release_unclaimed_cash_orders(session)
    return str(result)


async def resume_paused_stores_task(ctx):
    """Reopen stores whose pause has run out, and tell them it happened.

    The state is already correct without this — `store_state` compares the
    expiry against the clock, so a worker that never ran cannot leave a shop
    shut. What this adds is the notification and a tidy column: a vendor who
    paused for twenty minutes and heard nothing has no way to know it worked,
    and the usual response to that is to pause again.
    """
    from dependencies.dependencies import get_db_session
    from services import vendor_availability

    async with get_db_session() as session:
        result = await vendor_availability.resume_expired_pauses(session)
    return str(result)


async def reconcile_customer_cohorts_task(ctx):
    """Re-derive `Customer_First_Delivery` from the orders table, and repair it.

    The table is written on the delivery path, which makes the growth report a
    join instead of an aggregate over every delivered order there has ever been.
    That fast path depends on every route that can mark an order delivered
    remembering to call `record_acquisition` — and "every path remembers" is the
    assumption this codebase has been caught by before, which is how
    `commission_lost` came to be null on exactly the most common kind of
    cancellation.

    So the hook keeps the table current and this makes it *true*. It is a set
    operation, not a walk: one pass whatever the platform's size.

    The count it returns is the point. Zero means every delivery path is calling
    the hook. A number that keeps coming back means one is not, and that is a
    defect in the code which nothing else would report.
    """
    from dependencies.dependencies import get_db_session
    from services import customer_cohort_service

    async with get_db_session() as session:
        result = await customer_cohort_service.reconcile(session)
    return str(result)


async def deposit_maintenance_task(ctx):
    """The deposit book's nightly upkeep, including the reconciliation.

    One task rather than four schedules, because the order matters: the sweeps
    bring the book up to date and the reconciliation then reads it. Split
    across separate crons they would race, and the reconciliation would report
    drift that the settlement due a minute later was about to remove.
    """
    from jobs.deposit_maintenance import run_deposit_maintenance

    result = await run_deposit_maintenance()
    return str(result)[:400]


async def dispatch_trip_radar_task(ctx, order_id: str, params: dict):
    """Tier 2 of the dispatch escalation, twenty seconds after Tier 1.

    Enqueued with `_defer_by` rather than waited for with `asyncio.sleep` inside
    the API process. The sleep meant a deploy or a restart during the window
    killed the escalation, and the order was only rescued three minutes later by
    the re-offer sweep. Redis survives the restart; the API process does not.

    The job re-checks the order's status before broadcasting, so one accepted
    during the wait is never offered twice.
    """
    from uuid import UUID

    from services.order_service import broadcast_trip_radar

    await broadcast_trip_radar(order_id=UUID(order_id), **params)
    return f"Trip Radar evaluated for order {order_id}"


async def run_broadcast_campaign(ctx, campaign_id: str):
    """Send an admin broadcast to its whole audience, in batches.

    Here rather than in the request because a campaign to ten thousand people
    would time out somewhere around the thirtieth and leave nobody able to say
    how far it got. The service commits per batch and updates the campaign's
    counters as it goes, so a run that dies leaves evidence of what was sent.
    """
    from uuid import UUID

    from dependencies.dependencies import get_db_session
    from services import broadcast_service

    async with get_db_session() as session:
        return await broadcast_service.run_campaign(session, UUID(campaign_id))


class WorkerSettings:
    functions = [
        run_broadcast_campaign,
        send_push_message_task,
        flush_gps_tracking_logs_task,
        auto_resolve_bottle_rejections_task,
        auto_cancel_pending_orders_task,
        evaluate_platinum_riders_task,
        process_pending_refunds_task,
        reassign_unassigned_orders_task,
        check_push_receipts_task,
        stale_asset_monitor_task,
        deposit_maintenance_task,
        release_unclaimed_cash_task,
        resume_paused_stores_task,
        reconcile_customer_cohorts_task,
        dispatch_trip_radar_task,
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
        cron(deposit_maintenance_task, hour=3, minute=30),
        cron(release_unclaimed_cash_task, minute=set(range(0, 60, 10))),
        cron(resume_paused_stores_task, minute=set(range(0, 60, 5))),
        cron(evaluate_platinum_riders_task, hour=0, minute=0),
    ]
    logger.warning("ARQ internal cron enabled — cron-job.org schedules must be paused.")
