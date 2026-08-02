"""
Expo push delivery.

Two rules govern everything here:

1. **A dropped push is a lost notification.** There is no retry queue beyond this
   module, so a transient failure talking to Expo must be retried rather than
   logged and forgotten.
2. **Never fire a coroutine and walk away.** `asyncio.create_task` returns a task
   the caller must keep referenced; the event loop only holds a weak reference,
   so an unreferenced task can be garbage-collected mid-flight. Use
   `dispatch_background` so the reference is held until completion.
"""
import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy import update
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
CHUNK_SIZE = 100

# Strong references to in-flight fire-and-forget tasks. Without this the loop
# holds only a weak reference and a push can vanish before it is sent.
_background_tasks: set[asyncio.Task] = set()


def dispatch_background(coro) -> asyncio.Task:
    """Run `coro` detached, keeping it referenced until it finishes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def purge_dead_token(token: str):
    """Detach a token Expo has told us no longer exists on any device."""
    try:
        from dependencies.dependencies import get_db_session
        from models.deliverer_model import Deliverer
        from models.user_model import User
        from models.vendor_model import Vendor

        async with get_db_session() as session:
            await session.execute(update(User).where(User.push_token == token).values(push_token=None))
            await session.execute(update(Vendor).where(Vendor.push_token == token).values(push_token=None))
            # Staff tokens live on the membership row now, so one dead token
            # can be held by several people across several stores.
            from models.vendor_staff_model import VendorStaff

            await session.execute(
                update(VendorStaff).where(VendorStaff.push_token == token).values(push_token=None)
            )
            await session.execute(update(Deliverer).where(Deliverer.push_token == token).values(push_token=None))
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to purge dead token from DB: {e}")


shared_client = httpx.AsyncClient(timeout=10.0)


class _TransientPushError(Exception):
    """Expo was unreachable or returned 5xx/429 — worth another attempt."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(_TransientPushError),
    reraise=True,
)
async def _post_chunk(messages: list[dict]) -> dict:
    """POST one chunk of ≤100 messages, retrying only what retrying can fix.

    The retry decorator used to sit on the whole loop while a bare
    `except Exception` inside swallowed every error, so `reraise` had nothing to
    reraise and tenacity never ran: one 502 from Expo silently dropped the batch.
    Raising `_TransientPushError` is what actually drives the retry.

    A 4xx other than 429 means the request itself is wrong; retrying it just
    delays the same rejection, so it is raised as-is and handled by the caller.
    """
    try:
        response = await shared_client.post(EXPO_PUSH_URL, json=messages)
    except httpx.RequestError as e:
        raise _TransientPushError(f"transport failure: {e}") from e

    if response.status_code >= 500 or response.status_code == 429:
        raise _TransientPushError(f"Expo returned {response.status_code}")

    response.raise_for_status()
    return response.json()


def _handle_ticket_errors(chunk: list[str], payload: dict) -> None:
    """Act on per-message tickets. Expo returns them in request order."""
    tickets = (payload or {}).get("data") or []
    for idx, ticket in enumerate(tickets):
        if ticket.get("status") != "error" or idx >= len(chunk):
            continue
        error_type = (ticket.get("details") or {}).get("error")
        if error_type == "DeviceNotRegistered":
            logger.info("Push token is dead (DeviceNotRegistered); purging.")
            dispatch_background(purge_dead_token(chunk[idx]))
        else:
            logger.warning("Expo rejected a push: %s — %s", error_type, ticket.get("message"))


async def _execute_push_chunks(
    tokens: list[str], title: str, body: str, data: Optional[dict] = None
):
    """Send to every token in chunks of 100. Runs inside the ARQ worker."""
    valid_tokens = [t for t in tokens if t and t.startswith("ExponentPushToken")]
    if not valid_tokens:
        return None

    all_responses = []
    for i in range(0, len(valid_tokens), CHUNK_SIZE):
        chunk = valid_tokens[i : i + CHUNK_SIZE]
        messages = [
            {
                "to": to,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
                # Both apps create a channel called "default" on Android; naming
                # it here keeps the notification at the importance the channel
                # was registered with instead of the system fallback.
                "channelId": "default",
                "priority": "high",
            }
            for to in chunk
        ]

        try:
            payload = await _post_chunk(messages)
        except Exception as e:
            # One bad chunk must not abandon the rest of the recipients.
            logger.error("Push chunk failed after retries: %s", e, exc_info=True)
            continue

        all_responses.append(payload)
        _handle_ticket_errors(chunk, payload)

        # A ticket only means Expo accepted the message. Whether the device got
        # it is reported later, by receipt — which is where `DeviceNotRegistered`
        # usually appears. Park the ids for the receipt sweep to collect.
        try:
            from services.push_receipt_service import record_tickets

            await record_tickets((payload or {}).get("data") or [], chunk)
        except Exception as e:
            logger.warning("Could not record push tickets for receipt checking: %s", e)

    return all_responses


async def send_chunked_push_messages(
    tokens: list[str], title: str, body: str, data: Optional[dict] = None
):
    """Hand the batch to ARQ, falling back to sending inline if it is unavailable."""
    valid_tokens = [t for t in tokens if t and t.startswith("ExponentPushToken")]
    if not valid_tokens:
        return None

    try:
        from core.redis_client import get_arq_pool

        pool = await get_arq_pool()
        if pool:
            await pool.enqueue_job("send_push_message_task", valid_tokens, title, body, data)
            logger.info(f"Enqueued {len(valid_tokens)} push notifications to ARQ.")
            return True
    except Exception as e:
        logger.error(f"Failed to enqueue push message to ARQ: {e}")

    logger.warning("ARQ unavailable — sending push notifications inline.")
    await _execute_push_chunks(valid_tokens, title, body, data)
    return True


async def send_push_message(to: str, title: str, body: str, data: Optional[dict] = None):
    """Backwards compatible single-token push. Enqueues via ARQ."""
    if not to or not to.startswith("ExponentPushToken"):
        logger.warning("Invalid push token supplied; skipping push.")
        return None

    return await send_chunked_push_messages([to], title, body, data)
