"""
Scheduled work, triggered externally by cron-job.org.

**Why not ARQ's own scheduler.** ARQ crons only fire while `arq
worker.WorkerSettings` is running, so the schedule is coupled to a process that
has to be up, alone, and healthy. On a platform that sleeps or restarts workers
the schedule silently stops, and nothing reports that it has. Moving the *clock*
to cron-job.org makes the schedule external and observable: it shows failures,
alerts on them, and retries. The worker still does the *work* — these endpoints
only enqueue.

**The endpoint enqueues, it does not execute.** cron-job.org gives a request
around 30 seconds; a sweep over thousands of rows does not fit, and holding the
connection open would make a slow job look like a failed one. Each endpoint hands
the job to ARQ and returns `202` immediately. When Redis is unreachable the job
runs inline as a fallback so a broken queue degrades rather than stops.

**Security.** These endpoints mutate orders, money and tokens, so they are as
sensitive as any authenticated route, but no user is signed in. They are guarded
by a shared secret compared in constant time, accepted either as the
`X-Cron-Key` header or a `key` query parameter — cron-job.org supports custom
headers, and the query form is the fallback. Without `CRON_SECRET` configured the
router refuses every request outside development rather than running open.

**Overlap.** cron-job.org retries on failure and can fire again before a slow run
finishes. Every job takes a short Redis lock so a second invocation returns
`already running` instead of double-processing.
"""
import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from core.redis_client import redis_limiter as limiter

logger = logging.getLogger(__name__)

router = APIRouter()

CRON_SECRET = os.getenv("CRON_SECRET")
_IS_DEVELOPMENT = os.getenv("ENV", "development").lower() == "development"

# How long a job may hold its lock before another invocation is allowed to try.
# Longer than any sweep should take, short enough that a crashed run recovers.
_LOCK_TTL_SECONDS = 600


def _authorise(header_key: Optional[str], query_key: Optional[str]) -> None:
    """Constant-time check of the shared secret; fail closed if unconfigured."""
    if not CRON_SECRET:
        if _IS_DEVELOPMENT:
            logger.warning("CRON_SECRET is not set — cron endpoints are unguarded in development.")
            return
        # Refusing is the only safe answer: these endpoints cancel orders and
        # move money, and an unset secret would leave them open to the internet.
        raise HTTPException(status_code=503, detail="Scheduled tasks are not configured.")

    supplied = header_key or query_key or ""
    if not hmac.compare_digest(supplied, CRON_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")


async def _claim(job: str) -> bool:
    """Take the per-job lock. False when another run already holds it."""
    from core.redis_client import get_redis

    redis = get_redis()
    if not redis:
        # No Redis means no lock and no queue; the inline fallback below still
        # runs the job, which is better than skipping it entirely.
        return True
    try:
        return bool(await redis.set(f"cron:lock:{job}", "1", ex=_LOCK_TTL_SECONDS, nx=True))
    except Exception as e:
        logger.warning("Could not take cron lock for %s: %s", job, e)
        return True


async def _release(job: str) -> None:
    from core.redis_client import get_redis

    redis = get_redis()
    if not redis:
        return
    try:
        await redis.delete(f"cron:lock:{job}")
    except Exception:
        pass


async def _run(job: str, task) -> dict:
    """Enqueue the ARQ task, falling back to running it inline if ARQ is down."""
    if not await _claim(job):
        logger.info("Cron job %s is already running; skipping this tick.", job)
        return {"job": job, "status": "already_running"}

    try:
        from core.redis_client import get_arq_pool

        pool = await get_arq_pool()
        if pool:
            await pool.enqueue_job(task.__name__)
            return {"job": job, "status": "enqueued"}
    except Exception as e:
        logger.warning("Could not enqueue %s (%s); running inline.", job, e)

    try:
        # ARQ passes a context dict as the first argument; none of these tasks
        # read it, so `None` is safe and keeps one definition of each job.
        result = await task(None)
        return {"job": job, "status": "ran_inline", "result": str(result)[:200]}
    except Exception as e:
        logger.error("Cron job %s failed: %s", job, e, exc_info=True)
        # 500 so cron-job.org records the failure and alerts, rather than the
        # schedule quietly doing nothing for weeks.
        raise HTTPException(status_code=500, detail=f"{job} failed")
    finally:
        await _release(job)


# ── Job definitions ───────────────────────────────────────────────────────
# `slug` is what goes in the cron-job.org URL. Keep them stable: changing one
# silently stops that schedule.
#
# The value is the ARQ task itself, so the enqueued name and the inline fallback
# can never drift apart — an inline copy of each job's imports was already wrong
# for two of them before this was written.

def _job_table() -> dict:
    import worker

    return {
        "flush-gps-logs": worker.flush_gps_tracking_logs_task,
        "resolve-bottle-rejections": worker.auto_resolve_bottle_rejections_task,
        "cancel-pending-orders": worker.auto_cancel_pending_orders_task,
        "process-refunds": worker.process_pending_refunds_task,
        "reassign-unassigned-orders": worker.reassign_unassigned_orders_task,
        "evaluate-platinum-riders": worker.evaluate_platinum_riders_task,
        "check-push-receipts": worker.check_push_receipts_task,
        "stale-asset-monitor": worker.stale_asset_monitor_task,
    }


@router.get("/jobs")
@limiter.limit("30/minute")
async def list_jobs(
    request: Request,
    x_cron_key: Optional[str] = Header(None, alias="X-Cron-Key"),
    key: Optional[str] = Query(None),
):
    """The slugs to point cron-job.org at. Handy for verifying the secret works."""
    _authorise(x_cron_key, key)
    return {"jobs": sorted(_job_table())}


@router.post("/{job}")
@router.get("/{job}", include_in_schema=False)  # cron-job.org defaults to GET
@limiter.limit("120/minute")
async def run_job(
    request: Request,
    job: str,
    x_cron_key: Optional[str] = Header(None, alias="X-Cron-Key"),
    key: Optional[str] = Query(None),
):
    _authorise(x_cron_key, key)

    task = _job_table().get(job)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job}'")

    return await _run(job, task)
