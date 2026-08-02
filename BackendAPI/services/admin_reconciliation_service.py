"""The dead-letter queue for payment callbacks, made legible.

`failed_webhooks` is written by `cart_routes` when an M-Pesa callback raises. It
has been write-only since it was added: nothing read it, so a callback that
failed meant a customer had **paid Safaricom while their order stayed
`pending`**, and the first anyone heard was a complaint.

The payload is stored redacted, but `utils.redaction.redact_payload` only masks
the phone number — `CheckoutRequestID`, `Amount`, `MpesaReceiptNumber` and the
result code all survive. That is enough to identify the payment, find the order
and settle it, which is what this module extracts.

## Why there is no "replay" button here

Re-invoking the callback handler would be a **second path that moves money**, and
this platform refuses those on principle: `admin_orders_routes` deliberately
excludes refunding for the same reason, leaving `refund_service` to own the
reversal and its idempotency key. A replay that raced the reconciliation sweep,
or ran twice because someone double-clicked, would credit a wallet twice.

So this is a triage screen. It tells an administrator exactly which payment
failed, what it was worth, whether a `payments` row exists for it and what state
the order is in — then hands them the existing, single-path tools to fix it.
`resolve` records the human decision; it does not touch a balance.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.failed_webhook_model import FailedWebhook
from models.order_model import Order
from models.payment_model import Payment

logger = logging.getLogger(__name__)

#: Beyond this a failed callback is not a blip, it is money nobody has chased.
STALE_AFTER_HOURS = 24


def _items(callback: dict) -> dict[str, Any]:
    """Flatten M-Pesa's `CallbackMetadata.Item` list into a mapping.

    Safaricom sends `[{"Name": "Amount", "Value": 100}, …]` rather than an
    object, and the items present vary with the result code — a failed payment
    carries no receipt at all.
    """
    metadata = (callback.get("CallbackMetadata") or {}).get("Item") or []
    out: dict[str, Any] = {}
    for item in metadata:
        if isinstance(item, dict) and "Name" in item:
            out[item["Name"]] = item.get("Value")
    return out


def parse_payload(raw: str) -> dict[str, Any]:
    """Pull the identifying fields out of a stored callback.

    Never raises. A payload that cannot be parsed is still a row an
    administrator has to see — returning nothing but the raw text is far better
    than dropping it from the list because `json.loads` failed.
    """
    parsed: dict[str, Any] = {
        "checkout_request_id": None,
        "merchant_request_id": None,
        "result_code": None,
        "result_desc": None,
        "amount": None,
        "receipt": None,
        "parse_error": None,
    }

    try:
        data = json.loads(raw)
        callback = ((data.get("Body") or {}).get("stkCallback")) or {}

        parsed["checkout_request_id"] = callback.get("CheckoutRequestID")
        parsed["merchant_request_id"] = callback.get("MerchantRequestID")
        parsed["result_code"] = callback.get("ResultCode")
        parsed["result_desc"] = callback.get("ResultDesc")

        items = _items(callback)
        amount = items.get("Amount")
        if amount is not None:
            parsed["amount"] = str(Decimal(str(amount)).quantize(Decimal("0.01")))
        parsed["receipt"] = items.get("MpesaReceiptNumber")
    except Exception as exc:  # noqa: BLE001 — a bad payload must still be listed
        parsed["parse_error"] = type(exc).__name__

    return parsed


async def _link(db: AsyncSession, checkout_request_id: str | None) -> dict[str, Any]:
    """Find the payment and order this callback was about.

    This is the whole value of the screen. "A callback failed" is not actionable;
    "this callback failed, the payment row says `pending`, and order 8f3c is
    still unpaid four hours later" is a thing somebody can go and fix.
    """
    if not checkout_request_id:
        return {"payment": None, "order": None}

    payment = (
        await db.execute(
            select(Payment).where(Payment.checkout_request_id == checkout_request_id)
        )
    ).scalars().first()

    if payment is None:
        # No payments row at all: the callback failed before one was written, so
        # nothing on this platform records that the customer was charged.
        return {"payment": None, "order": None}

    order = await db.get(Order, payment.order_id) if payment.order_id else None

    return {
        "payment": {
            "id": str(payment.id),
            "status": payment.status,
            "amount": str(Decimal(payment.amount or 0).quantize(Decimal("0.01"))),
            "receipt": payment.mpesa_receipt,
            "failure_reason": payment.failure_reason,
        },
        "order": (
            {
                "id": str(order.id),
                "status": order.order_status,
                "payment_status": order.payment_status,
                "total": str(Decimal(order.total_amount or 0).quantize(Decimal("0.01"))),
            }
            if order is not None
            else None
        ),
    }


async def list_failures(
    db: AsyncSession,
    *,
    resolved: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(FailedWebhook)
            .where(FailedWebhook.resolved.is_(resolved))
            .order_by(FailedWebhook.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []

    for row in rows:
        parsed = parse_payload(row.payload or "")
        created = row.created_at
        age_minutes = (
            round((now - created).total_seconds() / 60) if created else None
        )

        out.append(
            {
                "id": str(row.id),
                "source": row.source,
                "error_message": row.error_message,
                "resolved": bool(row.resolved),
                "created_at": created.isoformat() if created else None,
                "age_minutes": age_minutes,
                **parsed,
                **await _link(db, parsed["checkout_request_id"]),
            }
        )

    return out


async def summary(db: AsyncSession) -> dict[str, Any]:
    """Counts for the header and the nav badge."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(hours=STALE_AFTER_HOURS)

    async def count(*where) -> int:
        query = select(func.count(FailedWebhook.id))
        for clause in where:
            query = query.where(clause)
        return int((await db.execute(query)).scalar() or 0)

    open_rows = (
        await db.execute(
            select(FailedWebhook).where(FailedWebhook.resolved.is_(False))
        )
    ).scalars().all()

    # Summed from the payloads rather than from `payments`, deliberately: the
    # cases that matter most are exactly the ones where no payments row was ever
    # written, and those would total zero if this joined instead of parsed.
    at_risk = Decimal("0")
    unparseable = 0
    for row in open_rows:
        parsed = parse_payload(row.payload or "")
        if parsed["parse_error"]:
            unparseable += 1
        if parsed["amount"]:
            at_risk += Decimal(parsed["amount"])

    oldest = (
        await db.execute(
            select(func.min(FailedWebhook.created_at)).where(
                FailedWebhook.resolved.is_(False)
            )
        )
    ).scalar()

    return {
        "open": len(open_rows),
        "resolved": await count(FailedWebhook.resolved.is_(True)),
        "stale": await count(
            FailedWebhook.resolved.is_(False), FailedWebhook.created_at < stale_before
        ),
        "unparseable": unparseable,
        "amount_at_risk": str(at_risk.quantize(Decimal("0.01"))),
        "oldest_age_minutes": (
            round((now - oldest).total_seconds() / 60) if oldest else None
        ),
        "stale_after_hours": STALE_AFTER_HOURS,
    }


async def resolve(db: AsyncSession, webhook_id: str) -> FailedWebhook | None:
    """Mark one entry handled.

    Records that a human dealt with it. It moves no money and touches no order —
    the administrator does that through the ordinary tools, and this is the note
    saying they did.
    """
    row = await db.get(FailedWebhook, webhook_id)
    if row is None:
        return None
    row.resolved = True
    return row
