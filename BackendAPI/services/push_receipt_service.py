"""
Expo push receipts.

Sending a push returns a **ticket**, which only says Expo accepted the message.
Whether the device actually received it is reported later, by a separate
**receipt** fetched with the ticket id. Most permanent failures — above all
`DeviceNotRegistered`, meaning the app was uninstalled or the token was rotated —
surface only there.

Handling ticket-level errors alone left dead tokens on accounts indefinitely, so
the platform kept paying to push to devices that no longer exist and, worse, a
shared device could keep receiving a previous account's notifications.

The flow:

    send  →  ticket ids parked in Redis with a due time
                     ↓  (cron, a few minutes later)
    getReceipts  →  purge tokens Expo reports as unregistered

Redis is the right store here: these are transient, self-expiring records with no
reporting value. If Redis is unavailable the tickets are simply not recorded —
delivery is unaffected, only the cleanup is skipped.
"""
import json
import logging
import time
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)

EXPO_RECEIPT_URL = "https://exp.host/--/api/v2/push/getReceipts"

# Expo tells you to wait before asking; receipts are not ready immediately.
RECEIPT_DELAY_SECONDS = 15 * 60
# Expo accepts up to 1000 ids per request.
RECEIPT_BATCH_SIZE = 300
# Anything still unresolved after this is abandoned rather than retried forever.
RECEIPT_MAX_AGE_SECONDS = 24 * 60 * 60

_PENDING_KEY = "push:receipts:pending"

# Receipt errors that mean "this token will never work again". Anything else
# (`MessageTooBig`, `MessageRateExceeded`) is about the message, not the token.
_FATAL_TOKEN_ERRORS = {"DeviceNotRegistered"}


async def record_tickets(tickets: list[dict], tokens: list[str]) -> int:
    """Park the ids from a send response so their receipts can be checked later.

    `tickets` and `tokens` are positionally aligned — Expo returns one ticket per
    message, in request order.
    """
    from core.redis_client import get_redis

    redis = get_redis()
    if not redis:
        return 0

    now = time.time()
    due = now + RECEIPT_DELAY_SECONDS
    members = {}
    for ticket, token in zip(tickets, tokens):
        ticket_id = ticket.get("id")
        if ticket.get("status") == "ok" and ticket_id:
            # `first` is the original send time and never moves. The sorted-set
            # score is the *due* time, which a re-park pushes forward — without a
            # separate origin an un-resolvable ticket would be retried forever.
            members[json.dumps({"id": ticket_id, "token": token, "first": round(now)})] = due

    if not members:
        return 0

    try:
        await redis.zadd(_PENDING_KEY, members)
    except Exception as e:
        logger.warning("Could not record push receipt ids: %s", e)
        return 0
    return len(members)


async def _fetch_receipts(client: httpx.AsyncClient, ids: list[str]) -> dict:
    response = await client.post(EXPO_RECEIPT_URL, json={"ids": ids})
    response.raise_for_status()
    return (response.json() or {}).get("data") or {}


async def _purge(tokens: Iterable[str]) -> int:
    from services.expo_push_service import purge_dead_token

    purged = 0
    for token in tokens:
        await purge_dead_token(token)
        purged += 1
    return purged


async def process_due_receipts(limit: int = 3000) -> dict:
    """Fetch receipts that have come due and purge the tokens Expo rejected.

    Safe to run concurrently with itself: entries are removed from the pending
    set before the network call, so two overlapping runs cannot both act on the
    same ticket. A run that crashes mid-flight loses at most one batch of
    cleanup, which the next send re-establishes.
    """
    from core.redis_client import get_redis

    redis = get_redis()
    if not redis:
        return {"checked": 0, "purged": 0, "skipped": "redis unavailable"}

    now = time.time()
    try:
        raw = await redis.zrangebyscore(_PENDING_KEY, 0, now, start=0, num=limit)
    except Exception as e:
        logger.warning("Could not read pending push receipts: %s", e)
        return {"checked": 0, "purged": 0, "skipped": str(e)}

    if not raw:
        return {"checked": 0, "purged": 0}

    # Claim them first so a concurrent run does not process the same ids.
    try:
        await redis.zrem(_PENDING_KEY, *raw)
    except Exception as e:
        logger.warning("Could not claim pending push receipts: %s", e)
        return {"checked": 0, "purged": 0, "skipped": str(e)}

    by_id: dict[str, dict] = {}
    for member in raw:
        try:
            entry = json.loads(member)
            by_id[entry["id"]] = {"token": entry["token"], "first": entry.get("first", now)}
        except (ValueError, KeyError, TypeError):
            continue

    dead_tokens: set[str] = set()
    checked = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        ids = list(by_id)
        for i in range(0, len(ids), RECEIPT_BATCH_SIZE):
            batch = ids[i : i + RECEIPT_BATCH_SIZE]
            try:
                receipts = await _fetch_receipts(client, batch)
            except Exception as e:
                # Re-park this batch so a transient failure does not lose the
                # cleanup, unless the entries are already too old to be useful.
                logger.warning("Receipt fetch failed for %d ids: %s", len(batch), e)
                await _repark(redis, {i: by_id[i] for i in batch})
                continue

            checked += len(batch)
            for ticket_id, receipt in receipts.items():
                if receipt.get("status") != "error":
                    continue
                error = (receipt.get("details") or {}).get("error")
                token = (by_id.get(ticket_id) or {}).get("token")
                if error in _FATAL_TOKEN_ERRORS and token:
                    dead_tokens.add(token)
                else:
                    logger.info("Push receipt error %s: %s", error, receipt.get("message"))

    purged = await _purge(dead_tokens)
    if purged:
        logger.info("Purged %d push token(s) reported unregistered by Expo.", purged)
    return {"checked": checked, "purged": purged}


async def _repark(redis, entries: dict[str, dict]) -> None:
    """Put failed-to-check ids back with a fresh due time.

    Entries older than `RECEIPT_MAX_AGE_SECONDS` are dropped instead: a ticket
    Expo will never resolve must not be retried indefinitely.
    """
    now = time.time()
    members = {}
    for ticket_id, entry in entries.items():
        first = float(entry.get("first") or now)
        if now - first > RECEIPT_MAX_AGE_SECONDS:
            continue
        members[json.dumps({"id": ticket_id, "token": entry["token"], "first": round(first)})] = (
            now + RECEIPT_DELAY_SECONDS
        )
    if not members:
        return
    try:
        await redis.zadd(_PENDING_KEY, members)
    except Exception as e:
        logger.warning("Could not re-park push receipts: %s", e)


async def prune_stale_receipts() -> int:
    """Drop tickets nobody managed to resolve. Keeps the set from growing forever."""
    from core.redis_client import get_redis

    redis = get_redis()
    if not redis:
        return 0
    cutoff = time.time() - RECEIPT_MAX_AGE_SECONDS
    try:
        return await redis.zremrangebyscore(_PENDING_KEY, 0, cutoff) or 0
    except Exception as e:
        logger.warning("Could not prune stale push receipts: %s", e)
        return 0
