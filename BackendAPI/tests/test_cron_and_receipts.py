"""
External scheduling (cron-job.org) and Expo push receipts.

Scheduling moved out of the ARQ worker: its cron only ticks while that one
process is up and alone, so on a platform that sleeps or restarts workers the
auto-cancel and refund sweeps stop with nothing reporting it. cron-job.org owns
the clock, calls an authenticated endpoint, and the endpoint enqueues the same
ARQ task. That makes a missed run visible.

Receipts close the other half of push delivery. A send returns a *ticket*
(accepted by Expo), not a delivery result; `DeviceNotRegistered` normally appears
only in the *receipt*, fetched later. Without this sweep dead tokens stayed
attached to accounts indefinitely.
"""
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from routes import cron_routes
from services import push_receipt_service as receipts


# ── Cron endpoint authorisation ───────────────────────────────────────────


def test_a_wrong_key_is_refused():
    with patch.object(cron_routes, "CRON_SECRET", "correct-horse"):
        with pytest.raises(HTTPException) as exc:
            cron_routes._authorise("wrong", None)
        assert exc.value.status_code == 403


def test_the_key_is_accepted_from_either_the_header_or_the_query():
    """cron-job.org supports custom headers; the query form is the fallback."""
    with patch.object(cron_routes, "CRON_SECRET", "correct-horse"):
        cron_routes._authorise("correct-horse", None)
        cron_routes._authorise(None, "correct-horse")


def test_a_missing_key_is_refused():
    with patch.object(cron_routes, "CRON_SECRET", "correct-horse"):
        with pytest.raises(HTTPException) as exc:
            cron_routes._authorise(None, None)
        assert exc.value.status_code == 403


def test_an_unconfigured_secret_fails_closed_in_production():
    """These endpoints cancel orders and move money. Running them open because
    nobody set the variable is not an acceptable default."""
    with patch.object(cron_routes, "CRON_SECRET", None), patch.object(
        cron_routes, "_IS_DEVELOPMENT", False
    ):
        with pytest.raises(HTTPException) as exc:
            cron_routes._authorise(None, None)
        assert exc.value.status_code == 503


def test_the_secret_is_compared_in_constant_time():
    import inspect

    assert "compare_digest" in inspect.getsource(cron_routes._authorise)


# ── Job wiring ────────────────────────────────────────────────────────────


def test_every_slug_maps_to_a_registered_worker_task():
    """A slug pointing at a function ARQ does not know about would enqueue a job
    the worker silently drops."""
    import worker

    registered = {fn.__name__ for fn in worker.WorkerSettings.functions}
    for slug, task in cron_routes._job_table().items():
        assert task.__name__ in registered, f"{slug} → {task.__name__} is not in WorkerSettings"


def test_the_schedule_covers_every_job_that_used_to_be_an_arq_cron():
    """Nothing may be lost in the move to external scheduling."""
    expected = {
        "flush-gps-logs",
        "resolve-bottle-rejections",
        "cancel-pending-orders",
        "process-refunds",
        "reassign-unassigned-orders",
        "evaluate-platinum-riders",
        # New: neither of these had a schedule before.
        "check-push-receipts",
        "stale-asset-monitor",
    }
    assert set(cron_routes._job_table()) == expected


def test_internal_cron_is_off_unless_explicitly_enabled():
    """Both schedulers running at once would double every sweep."""
    import worker

    assert getattr(worker.WorkerSettings, "cron_jobs", []) == []


@pytest.mark.asyncio
async def test_a_second_invocation_is_skipped_while_one_is_running():
    """cron-job.org retries on failure and can fire again before a slow run
    finishes; overlapping refund sweeps must not both process the queue."""
    task = AsyncMock(return_value="done")
    task.__name__ = "some_task"

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=False)):
        result = await cron_routes._run("process-refunds", task)

    assert result["status"] == "already_running"
    task.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_job_is_enqueued_rather_than_run_in_the_request():
    """A sweep over thousands of rows does not fit in cron-job.org's request
    timeout, and holding the connection makes a slow job look like a failed one."""
    task = AsyncMock()
    task.__name__ = "process_pending_refunds_task"
    pool = AsyncMock()

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), patch(
        "core.redis_client.get_arq_pool", AsyncMock(return_value=pool)
    ):
        result = await cron_routes._run("process-refunds", task)

    assert result["status"] == "enqueued"
    # The task *name* is the contract — it must match a registered worker
    # function. The `_job_id` alongside it is deduplication and is covered
    # separately, so this asserts the name rather than the whole call.
    assert pool.enqueue_job.await_args.args == ("process_pending_refunds_task",)
    task.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_job_still_runs_when_the_queue_is_unavailable():
    """A broken queue should degrade, not silently stop the platform's sweeps."""
    task = AsyncMock(return_value="swept")
    task.__name__ = "process_pending_refunds_task"

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), patch.object(
        cron_routes, "_release", AsyncMock()
    ), patch("core.redis_client.get_arq_pool", AsyncMock(return_value=None)):
        result = await cron_routes._run("process-refunds", task)

    assert result["status"] == "ran_inline"
    task.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_job_returns_500_so_the_scheduler_alerts():
    """Swallowing the error would leave cron-job.org reporting green while the
    sweep did nothing for weeks."""
    task = AsyncMock(side_effect=RuntimeError("boom"))
    task.__name__ = "process_pending_refunds_task"

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), patch.object(
        cron_routes, "_release", AsyncMock()
    ) as release, patch("core.redis_client.get_arq_pool", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await cron_routes._run("process-refunds", task)

    assert exc.value.status_code == 500
    release.assert_awaited_once()  # the lock must not be left held


# ── Push receipts ─────────────────────────────────────────────────────────


class _FakeRedis:
    """Enough of a sorted set for the receipt queue."""

    def __init__(self):
        self.zset: dict[str, float] = {}

    async def zadd(self, _key, mapping):
        self.zset.update(mapping)

    async def zrangebyscore(self, _key, lo, hi, start=0, num=None):
        due = [m for m, score in sorted(self.zset.items(), key=lambda kv: kv[1]) if lo <= score <= hi]
        return due[start : start + num] if num else due

    async def zrem(self, _key, *members):
        for member in members:
            self.zset.pop(member, None)

    async def zremrangebyscore(self, _key, lo, hi):
        doomed = [m for m, score in self.zset.items() if lo <= score <= hi]
        for m in doomed:
            self.zset.pop(m)
        return len(doomed)


@pytest.mark.asyncio
async def test_only_accepted_tickets_are_tracked():
    """A ticket that already errored has no receipt to fetch."""
    redis = _FakeRedis()
    tickets = [
        {"status": "ok", "id": "ticket-1"},
        {"status": "error", "details": {"error": "MessageTooBig"}},
    ]

    with patch("core.redis_client.get_redis", return_value=redis):
        recorded = await receipts.record_tickets(tickets, ["tok-1", "tok-2"])

    assert recorded == 1
    assert json.loads(next(iter(redis.zset)))["id"] == "ticket-1"


@pytest.mark.asyncio
async def test_a_receipt_is_not_fetched_before_it_is_due():
    """Expo needs time to produce receipts; asking immediately returns nothing
    useful and wastes the request."""
    redis = _FakeRedis()

    with patch("core.redis_client.get_redis", return_value=redis):
        await receipts.record_tickets([{"status": "ok", "id": "t1"}], ["tok-1"])
        result = await receipts.process_due_receipts()

    assert result == {"checked": 0, "purged": 0}
    assert len(redis.zset) == 1, "the ticket must stay queued until it is due"


@pytest.mark.asyncio
async def test_an_unregistered_device_has_its_token_purged():
    """The whole point: `DeviceNotRegistered` usually appears only here, so
    without this sweep a token for an uninstalled app is pushed to forever."""
    redis = _FakeRedis()
    redis.zset[json.dumps({"id": "t1", "token": "tok-dead", "first": int(time.time())})] = 0

    body = {"data": {"t1": {"status": "error", "details": {"error": "DeviceNotRegistered"}}}}

    with patch("core.redis_client.get_redis", return_value=redis), patch.object(
        receipts, "_fetch_receipts", AsyncMock(return_value=body["data"])
    ), patch("services.expo_push_service.purge_dead_token", AsyncMock()) as purge:
        result = await receipts.process_due_receipts()

    assert result["purged"] == 1
    purge.assert_awaited_once_with("tok-dead")
    assert redis.zset == {}, "resolved tickets must be dropped"


@pytest.mark.asyncio
async def test_a_message_level_error_does_not_kill_the_token():
    """`MessageTooBig` is about the payload. Purging on it would sign a working
    device out of notifications for a bug in one message."""
    redis = _FakeRedis()
    redis.zset[json.dumps({"id": "t1", "token": "tok-fine", "first": int(time.time())})] = 0

    with patch("core.redis_client.get_redis", return_value=redis), patch.object(
        receipts,
        "_fetch_receipts",
        AsyncMock(return_value={"t1": {"status": "error", "details": {"error": "MessageTooBig"}}}),
    ), patch("services.expo_push_service.purge_dead_token", AsyncMock()) as purge:
        result = await receipts.process_due_receipts()

    assert result["purged"] == 0
    purge.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_fetch_reparks_the_tickets():
    """A transient Expo outage must not lose the cleanup."""
    redis = _FakeRedis()
    redis.zset[json.dumps({"id": "t1", "token": "tok-1", "first": int(time.time())})] = 0

    with patch("core.redis_client.get_redis", return_value=redis), patch.object(
        receipts, "_fetch_receipts", AsyncMock(side_effect=httpx.ConnectError("down"))
    ):
        result = await receipts.process_due_receipts()

    assert result["checked"] == 0
    assert len(redis.zset) == 1
    assert list(redis.zset.values())[0] > time.time(), "re-parked with a later due time"


@pytest.mark.asyncio
async def test_a_ticket_that_never_resolves_is_eventually_abandoned():
    """Re-parking moves the due time forward, so without an origin timestamp an
    unresolvable ticket would be retried for ever."""
    redis = _FakeRedis()
    ancient = int(time.time()) - receipts.RECEIPT_MAX_AGE_SECONDS - 60
    redis.zset[json.dumps({"id": "t1", "token": "tok-1", "first": ancient})] = 0

    with patch("core.redis_client.get_redis", return_value=redis), patch.object(
        receipts, "_fetch_receipts", AsyncMock(side_effect=httpx.ConnectError("down"))
    ):
        await receipts.process_due_receipts()

    assert redis.zset == {}, "tickets older than the max age must be dropped"


@pytest.mark.asyncio
async def test_tickets_are_claimed_before_the_network_call():
    """Two overlapping sweeps must not both act on the same ticket."""
    redis = _FakeRedis()
    redis.zset[json.dumps({"id": "t1", "token": "tok-1", "first": int(time.time())})] = 0

    async def assert_already_claimed(_client, _ids):
        assert redis.zset == {}, "entries must be removed before fetching"
        return {}

    with patch("core.redis_client.get_redis", return_value=redis), patch.object(
        receipts, "_fetch_receipts", assert_already_claimed
    ):
        await receipts.process_due_receipts()


@pytest.mark.asyncio
async def test_receipt_tracking_degrades_quietly_without_redis():
    """Delivery must not depend on the cleanup path being available."""
    with patch("core.redis_client.get_redis", return_value=None):
        assert await receipts.record_tickets([{"status": "ok", "id": "t"}], ["tok"]) == 0
        assert (await receipts.process_due_receipts())["checked"] == 0
        assert await receipts.prune_stale_receipts() == 0


@pytest.mark.asyncio
async def test_sending_a_push_records_its_tickets():
    """The link between the two halves — without this the sweep has nothing."""
    from services import expo_push_service as push

    payload = {"data": [{"status": "ok", "id": "ticket-9"}]}
    response = httpx.Response(200, request=httpx.Request("POST", push.EXPO_PUSH_URL), json=payload)

    with patch.object(push.shared_client, "post", AsyncMock(return_value=response)), patch.object(
        receipts, "record_tickets", AsyncMock()
    ) as record:
        await push._execute_push_chunks(["ExponentPushToken[x]"], "t", "b")

    record.assert_awaited_once_with(payload["data"], ["ExponentPushToken[x]"])


# ── The per-job lock must always be released ──────────────────────────────


@pytest.mark.asyncio
async def test_the_lock_is_released_after_enqueuing():
    """Regression: the enqueue branch returned from inside its own `try`.

    The `finally` that released the lock belonged to the *inline* branch below
    it, so on the enqueue path the lock was never dropped and sat for its full
    600s TTL. Every later tick answered "already_running" — a job scheduled
    every minute actually ran once every ten, while cron-job.org recorded 200s
    throughout.
    """
    released = []
    pool = AsyncMock()
    pool.enqueue_job.return_value = MagicMock()  # a Job, i.e. accepted

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), \
         patch.object(cron_routes, "_release", AsyncMock(side_effect=lambda j: released.append(j))), \
         patch("core.redis_client.get_arq_pool", AsyncMock(return_value=pool)):
        result = await cron_routes._run("flush-gps-logs", MagicMock(__name__="t"))

    assert result["status"] == "enqueued"
    assert released == ["flush-gps-logs"], "the lock outlived the request"


@pytest.mark.asyncio
async def test_the_lock_is_released_when_a_job_fails_inline():
    released = []

    async def boom(_):
        raise RuntimeError("sweep exploded")

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), \
         patch.object(cron_routes, "_release", AsyncMock(side_effect=lambda j: released.append(j))), \
         patch("core.redis_client.get_arq_pool", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await cron_routes._run("process-refunds", boom)

    assert exc.value.status_code == 500
    assert released == ["process-refunds"], "a failed job must not hold its lock"


@pytest.mark.asyncio
async def test_a_retry_of_the_same_tick_is_deduplicated():
    """cron-job.org retries a tick it believes failed; ARQ drops the duplicate."""
    pool = AsyncMock()
    pool.enqueue_job.return_value = None  # ARQ: this _job_id is already queued

    with patch.object(cron_routes, "_claim", AsyncMock(return_value=True)), \
         patch.object(cron_routes, "_release", AsyncMock()), \
         patch("core.redis_client.get_arq_pool", AsyncMock(return_value=pool)):
        result = await cron_routes._run("cancel-pending-orders", MagicMock(__name__="t"))

    assert result["status"] == "already_queued"


def test_the_dedup_id_changes_between_ticks_but_not_within_one():
    with patch.object(cron_routes.time, "time", return_value=1_000_000.0):
        first = cron_routes._dedup_id("flush-gps-logs")
        assert cron_routes._dedup_id("flush-gps-logs") == first, "same minute, same id"
    with patch.object(cron_routes.time, "time", return_value=1_000_060.0):
        assert cron_routes._dedup_id("flush-gps-logs") != first, "next minute, new id"
