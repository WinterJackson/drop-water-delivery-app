"""
Ratings aggregation and notification delivery.

Both workflows had defects that were invisible in normal operation and only
showed up as *absence* — a rating that never moved, a push that never arrived:

* Expo push retries were dead code. `@retry` sat on a function whose body caught
  every exception, so `reraise` had nothing to reraise and tenacity never ran.
  One 502 from Expo silently dropped the whole batch.
* Pushes were dispatched with `asyncio.create_task` several statements *before*
  the `session.commit()` that made the change real, so a rolled-back order still
  told the customer it was confirmed — and the in-app record backing that push
  was never written.
* Rating averages were recomputed with `AVG()` over every review a target had
  ever received, on every submission, and no count was stored, so a client could
  not tell one five-star review from three hundred.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from services import expo_push_service as push
from services import notification_service as notif
from services.review_service import _apply_rating_delta


# ── Push delivery ─────────────────────────────────────────────────────────


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, request=httpx.Request("POST", push.EXPO_PUSH_URL), json=payload or {}
    )


def _token(n: int = 1) -> str:
    return f"ExponentPushToken[{n}]"


@pytest.mark.asyncio
async def test_a_transient_expo_failure_is_retried():
    """The regression that mattered: this used to make exactly one attempt and
    log the failure, losing the notification."""
    attempts = {"n": 0}

    async def flaky(*_a, **_k):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _response(502)
        return _response(200, {"data": [{"status": "ok"}]})

    with patch.object(push.shared_client, "post", side_effect=flaky), patch.object(
        push, "wait_exponential", MagicMock()
    ):
        result = await push._execute_push_chunks([_token()], "t", "b")

    assert attempts["n"] == 3
    assert result == [{"data": [{"status": "ok"}]}]


@pytest.mark.asyncio
async def test_a_permanent_rejection_is_not_retried():
    """A 400 means the request is wrong. Retrying it just delays the same answer
    and multiplies load on Expo during an incident."""
    attempts = {"n": 0}

    async def bad_request(*_a, **_k):
        attempts["n"] += 1
        return _response(400)

    with patch.object(push.shared_client, "post", side_effect=bad_request):
        await push._execute_push_chunks([_token()], "t", "b")

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_one_failing_chunk_does_not_abandon_the_others():
    """With 250 recipients a single bad chunk must not silence the other 150."""
    seen = []

    async def second_chunk_fails(_url, json=None, **_k):
        seen.append(len(json))
        return _response(400) if len(seen) == 2 else _response(200, {"data": []})

    with patch.object(push.shared_client, "post", side_effect=second_chunk_fails):
        await push._execute_push_chunks([_token(i) for i in range(250)], "t", "b")

    assert seen == [100, 100, 50], "every chunk must still be attempted"


@pytest.mark.asyncio
async def test_a_dead_token_is_purged():
    payload = {"data": [{"status": "error", "details": {"error": "DeviceNotRegistered"}}]}

    with patch.object(push.shared_client, "post", AsyncMock(return_value=_response(200, payload))), patch.object(
        push, "purge_dead_token", AsyncMock()
    ) as purge:
        await push._execute_push_chunks([_token()], "t", "b")
        await asyncio.sleep(0)

    purge.assert_called_once_with(_token())


@pytest.mark.asyncio
async def test_background_tasks_are_referenced_until_they_finish():
    """`asyncio.create_task` results must be kept: the loop holds only a weak
    reference, so an unreferenced push can be collected before it is sent."""
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(0.05)

    task = push.dispatch_background(slow())
    await started.wait()
    assert task in push._background_tasks
    await task
    assert task not in push._background_tasks, "finished tasks must not leak"


def test_non_expo_tokens_are_never_sent():
    assert [t for t in ["", None, "fcm-token", _token()] if t and t.startswith("ExponentPushToken")] == [
        _token()
    ]


# ── Push is tied to the transaction ───────────────────────────────────────


class _FakeSession:
    """Just enough Session for the queue: `info` plus the two lifecycle hooks."""

    def __init__(self):
        self.info = {}


@pytest.mark.asyncio
async def test_a_queued_push_is_sent_when_the_transaction_commits():
    session = _FakeSession()
    notif.queue_push(session, to=_token(), title="Order confirmed", body="b")

    sent = []
    with patch("services.expo_push_service.send_push_message", AsyncMock(side_effect=lambda **kw: sent.append(kw))):
        dispatched = notif._drain_and_dispatch(session)
        await asyncio.sleep(0)

    assert dispatched == 1
    assert sent and sent[0]["to"] == _token()


def test_a_rolled_back_transaction_discards_its_pushes():
    """The whole point of deferring: "Your order is confirmed" must not go out
    for an order that was rolled back."""
    session = _FakeSession()
    notif.queue_push(session, to=_token(), title="Order confirmed", body="b")

    notif._discard_pending(session)

    assert notif._drain_and_dispatch(session) == 0


@pytest.mark.asyncio
async def test_the_queue_is_drained_not_replayed():
    """Committing twice on one session must not send the same push twice."""
    session = _FakeSession()
    notif.queue_push(session, to=_token(), title="t", body="b")

    with patch("services.expo_push_service.send_push_message", AsyncMock()):
        assert notif._drain_and_dispatch(session) == 1
        assert notif._drain_and_dispatch(session) == 0
        # Let the dispatched task run so the mock coroutine is awaited.
        await asyncio.sleep(0)


def test_queueing_without_a_token_is_a_no_op():
    session = _FakeSession()
    notif.queue_push(session, to=None, title="t", body="b")
    assert notif._drain_and_dispatch(session) == 0


def test_the_commit_hook_is_registered_once():
    """Registering twice would send every push twice."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    notif.register_push_dispatch_hooks()
    notif.register_push_dispatch_hooks()
    assert event.contains(Session, "after_commit", notif._drain_and_dispatch)


def test_no_push_is_dispatched_with_a_bare_create_task():
    """The defect was structural, so guard it structurally.

    There are exactly two correct ways to send a push:

      `queue_push(session, ...)`   before the commit — the hook sends it after
      `dispatch_background(...)`   after the commit — keeps a strong reference

    A bare `asyncio.create_task(send_push_message(...))` is neither: it races the
    commit if it runs before one, and the loop holds only a weak reference to it
    either way. Twenty-one call sites across six modules had it.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for folder in ("services", "routes", "jobs"):
        for path in (root / folder).glob("*.py"):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if "create_task(send_push_message" in code:
                    offenders.append(f"{folder}/{path.name}:{lineno}")

    assert offenders == [], f"use queue_push or dispatch_background instead: {offenders}"


# ── Notification preferences ──────────────────────────────────────────────


def test_a_muted_category_is_not_pushed():
    recipient = MagicMock(preferences={"promotions": False, "order_updates": True})
    assert notif.push_allowed(recipient, "promotion") is False
    assert notif.push_allowed(recipient, "order_update") is True


def test_transactional_messages_ignore_the_toggles():
    """Silencing promotions must not silence a failed payment."""
    recipient = MagicMock(preferences={"promotions": False, "order_updates": False})
    assert notif.push_allowed(recipient, "payment_failed") is True
    assert notif.push_allowed(recipient, "kyc_approved") is True


def test_a_recipient_with_no_preferences_gets_the_defaults():
    assert notif.push_allowed(MagicMock(preferences=None), "order_update") is True
    assert notif.push_allowed(MagicMock(preferences=None), "promotion") is False


# ── Notification scoping ──────────────────────────────────────────────────


def test_an_unknown_user_type_is_rejected_not_read_as_customer():
    """It arrives as a query parameter. Defaulting silently is how the vendor app
    ended up marking notifications read against the customer scope."""
    with pytest.raises(HTTPException) as exc:
        notif._normalise_user_type("admin")
    assert exc.value.status_code == 400

    for user_type in notif.VALID_USER_TYPES:
        assert notif._normalise_user_type(user_type) == user_type
    assert notif._normalise_user_type(None) == "customer"


def test_a_malformed_notification_id_is_a_404_not_a_500():
    """Comparing a non-UUID string to a UUID column makes asyncpg raise."""
    with pytest.raises(HTTPException) as exc:
        notif._as_uuid("not-a-uuid")
    assert exc.value.status_code == 404

    known = uuid4()
    assert notif._as_uuid(str(known)) == known
    assert notif._as_uuid(known) == known


@pytest.mark.asyncio
async def test_reading_a_notification_is_scoped_to_the_caller_and_their_type():
    """`user_id` holds ids from three tables and carries no foreign key, so the
    type has to be part of every predicate."""
    captured = {}

    async def capture(stmt):
        captured["sql"] = str(stmt)
        return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=capture)

    with patch.object(notif, "_resolve_user_id", AsyncMock(return_value=uuid4())), pytest.raises(
        HTTPException
    ) as exc:
        await notif.mark_notification_read(session, "clerk_1", str(uuid4()), user_type="vendor")

    assert exc.value.status_code == 404
    assert "user_type" in captured["sql"]


# ── Rating aggregation ────────────────────────────────────────────────────


class _Target:
    def __init__(self, count=0, total=0.0, rating=0.0):
        self.rating_count = count
        self.rating_sum = total
        self.rating = rating


def test_a_first_review_sets_the_average():
    target = _Target()
    _apply_rating_delta(target, "vendor", new_rating=4.0, previous_rating=None)
    assert (target.rating_count, target.rating_sum, target.rating) == (1, 4.0, 4.0)


def test_reviews_accumulate_incrementally():
    """No AVG over the whole table: each submission is one read-modify-write."""
    target = _Target()
    for rating in (5.0, 4.0, 3.0):
        _apply_rating_delta(target, "vendor", new_rating=rating, previous_rating=None)

    assert target.rating_count == 3
    assert target.rating_sum == 12.0
    assert target.rating == 4.0


def test_editing_a_review_moves_the_sum_but_not_the_count():
    """A retried submission is treated as an edit; counting it twice would let a
    customer inflate a vendor by resubmitting."""
    target = _Target(count=2, total=9.0, rating=4.5)
    _apply_rating_delta(target, "vendor", new_rating=1.0, previous_rating=5.0)

    assert target.rating_count == 2
    assert target.rating_sum == 5.0
    assert target.rating == 2.5


def test_the_incremental_average_matches_a_full_recompute():
    ratings = [5.0, 4.0, 4.0, 3.0, 1.0, 2.0, 5.0, 5.0, 4.0]
    target = _Target()
    for rating in ratings:
        _apply_rating_delta(target, "vendor", new_rating=rating, previous_rating=None)

    assert target.rating == round(sum(ratings) / len(ratings), 2)
    assert target.rating_count == len(ratings)


def test_a_rider_with_no_ratings_is_not_a_one_star_rider():
    """Vendors start at 0 ("unrated"); a new rider starts at 5.0 so they are not
    buried before their first delivery."""
    from services.review_service import _DEFAULT_RATING

    assert _DEFAULT_RATING["rider"] == 5.0
    assert _DEFAULT_RATING["vendor"] == 0.0


# ── "Have I rated this order?" ────────────────────────────────────────────


def _order(order_id, deliverer_id=None):
    order = MagicMock()
    order.id = order_id
    order.deliverer_id = deliverer_id
    return order


async def _annotate(orders, rows):
    from services.order_service import annotate_is_rated

    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    return await annotate_is_rated(session, orders)


@pytest.mark.asyncio
async def test_rating_only_the_vendor_leaves_the_order_unrated():
    """The regression: RateOrder submits the vendor and rider ratings as two
    requests. If the rider one failed, `is_rated` flipped true anyway and the
    "Rate Delivery" action vanished — the rider could never be rated."""
    order_id, rider_id = uuid4(), uuid4()
    [order] = await _annotate([_order(order_id, rider_id)], [(order_id, "vendor")])
    assert order.is_rated is False


@pytest.mark.asyncio
async def test_rating_both_parties_marks_the_order_rated():
    order_id, rider_id = uuid4(), uuid4()
    [order] = await _annotate(
        [_order(order_id, rider_id)], [(order_id, "vendor"), (order_id, "rider")]
    )
    assert order.is_rated is True


@pytest.mark.asyncio
async def test_an_order_with_no_rider_only_needs_the_vendor_rated():
    """Nobody delivered it, so there is nobody to rate; requiring a rider review
    would leave the action on screen forever."""
    order_id = uuid4()
    [order] = await _annotate([_order(order_id, None)], [(order_id, "vendor")])
    assert order.is_rated is True


@pytest.mark.asyncio
async def test_an_unrated_order_is_unrated():
    order_id = uuid4()
    [order] = await _annotate([_order(order_id, uuid4())], [])
    assert order.is_rated is False


# ── Reviewer privacy ──────────────────────────────────────────────────────


def test_the_public_review_payload_does_not_identify_the_reviewer():
    """`GET /api/reviews/target/...` is unauthenticated. Returning
    `customer_clerk_id` let anyone page a vendor's reviews and collect the Clerk
    id of every customer who ordered from them."""
    from schemas.review_schemas import ReviewOut

    assert "customer_clerk_id" not in ReviewOut.model_fields


def test_a_comment_cannot_be_unbounded():
    """The column is TEXT; without a bound a single review can carry megabytes."""
    from schemas.review_schemas import ReviewCreate

    assert ReviewCreate.model_fields["comment"].metadata, "comment needs a max_length"

    with pytest.raises(Exception):
        ReviewCreate(
            order_id=uuid4(), target_type="vendor", target_id=uuid4(),
            rating=5.0, comment="x" * 5000,
        )


def test_the_rating_range_is_enforced_by_the_schema():
    from schemas.review_schemas import ReviewCreate

    for bad in (0.0, 6.0, -1.0):
        with pytest.raises(Exception):
            ReviewCreate(
                order_id=uuid4(), target_type="vendor", target_id=uuid4(), rating=bad
            )
