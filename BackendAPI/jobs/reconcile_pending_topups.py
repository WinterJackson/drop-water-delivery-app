"""Settle wallet top-ups whose Safaricom callback never arrived.

Every M-Pesa wallet top-up was pushed with the **order** callback URL, because
`initiate_stk_push` read one module-level `MPESA_CALLBACK_URL` and both callers
inherited it. `/api/cart/mpesa/callback` resolves a `CheckoutRequestID` against
`Orders`; a top-up writes a `WalletTransaction` and no order, so the handler
found nothing and returned **400** — which is a retry instruction to Safaricom,
not an acknowledgement. The customer's money left their phone, the transaction
stayed `pending`, and nothing anywhere noticed: `handle_mpesa_topup_callback`
was correct and live, and had never once been called.

Correcting the URL stops it happening again. It does nothing for the money
already taken, and there was no poll, no sweep and no reconciliation to find it
— so this sweep exists to recover that residue and, from then on, to catch the
ordinary case of Safaricom exhausting its retries against a restart.

Deliberately conservative, because both mistakes here are expensive:

* **Only rows Safaricom positively resolves.** A query that cannot answer —
  Daraja unreachable, no result code yet, the prompt still on the handset —
  leaves the row untouched for the next run. "We could not find out" is not a
  reason to credit a wallet, and it is not a reason to write a payment off.
* **A grace period before the first query.** Safaricom will not answer for a
  push that is still live, and a customer typing their PIN is not a stranded
  transaction.
* **An upper bound.** Daraja stops answering for old CheckoutRequestIDs, so a
  row past `topup_reconcile_max_age_hours` is escalated to a human rather than
  retried forever against an endpoint that will never resolve it.

Claims rows with `FOR UPDATE SKIP LOCKED` and commits per row, so several
workers may run it and one bad row cannot discard the batch.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import sentry_sdk
from sqlalchemy import select, and_

from dependencies.dependencies import get_db_session
from models.wallet_transaction_model import (
    TransactionStatus,
    TransactionType,
    WalletTransaction,
)
from services import platform_config_service
from services.payment_service import query_stk_status
from services.wallet_service import settle_pending_topup_from_query

logger = logging.getLogger(__name__)

#: Long enough that the STK prompt has certainly expired. Safaricom's own
#: prompt times out at about 60 seconds; below this the query only ever
#: answers "still processing" and we would be spending Daraja calls to learn
#: nothing.
MIN_AGE_MINUTES = 10


def _escalate_unresolved(transaction: WalletTransaction) -> None:
    """A top-up nobody can now resolve, reported where somebody will see it.

    Tagged rather than logged, for the reason the cohort reconciliation is:
    one of these after a restart is expected, and the same count returning
    every run is the signal — which nobody spots in a cron output they do not
    tail. Reporting must never break the sweep, so every failure here is
    swallowed.
    """
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_context(
                "topup_reconciliation",
                {
                    "checkout_request_id": transaction.reference_id,
                    "amount": str(transaction.amount),
                    "user_type": getattr(transaction.user_type, "value", transaction.user_type),
                    "wallet_owner_id": str(transaction.wallet_owner_id),
                    "created_at": str(transaction.created_at),
                },
            )
            scope.set_tag("reconciliation", "wallet_topups")
            scope.level = "error"
            sentry_sdk.capture_message(
                "Wallet top-up unresolved past the reconciliation window — "
                "check the M-Pesa statement before crediting or refunding",
            )
    except Exception:  # pragma: no cover - reporting must never break the sweep
        logger.debug("Could not report an unresolved top-up to Sentry", exc_info=True)


async def run_reconcile_pending_topups(batch_size: int = 100):
    logger.info("Running pending top-up reconciliation...")

    async with get_db_session() as session:
        await platform_config_service.ensure_fresh(session)
        max_age_hours = platform_config_service.get_int("topup_reconcile_max_age_hours")

    now = datetime.now(timezone.utc)
    # `created_at < cutoff` rather than `now() - created_at > interval`: the two
    # are arithmetically identical and only one lets Postgres seek the index on
    # the column instead of evaluating a subtraction per candidate row.
    young_cutoff = now - timedelta(minutes=MIN_AGE_MINUTES)
    old_cutoff = now - timedelta(hours=max_age_hours)

    settled = failed = abandoned = 0

    async with get_db_session() as session:
        query = (
            select(WalletTransaction)
            .where(
                and_(
                    WalletTransaction.transaction_type == TransactionType.top_up,
                    WalletTransaction.status == TransactionStatus.pending,
                    WalletTransaction.created_at < young_cutoff,
                    WalletTransaction.reference_id.isnot(None),
                )
            )
            .order_by(WalletTransaction.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = (await session.execute(query)).scalars().all()

        if not rows:
            logger.info("No pending top-ups to reconcile.")
            return {"settled": 0, "failed": 0, "abandoned": 0}

        for transaction in rows:
            try:
                # Re-check under the lock: a real callback may have landed
                # between the select and here.
                if transaction.status != TransactionStatus.pending:
                    continue

                created = transaction.created_at
                if created is not None and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)

                if created is not None and created < old_cutoff:
                    # Past the window in which Daraja will resolve it. Escalated
                    # rather than logged: this is a customer who may well have
                    # paid, and the only remaining answer is a human reading the
                    # M-Pesa statement. Left `pending` on purpose — writing it
                    # off would assert something nobody knows.
                    abandoned += 1
                    _escalate_unresolved(transaction)
                    continue

                outcome = await query_stk_status(transaction.reference_id)
                if outcome["state"] == "pending":
                    # Could not find out. Not a reason to move money either way.
                    continue

                result = await settle_pending_topup_from_query(
                    session, transaction, outcome
                )
                if result.get("status") == "success":
                    settled += 1
                elif result.get("status") == "failed":
                    failed += 1
            except Exception as e:
                logger.error(
                    "Failed to reconcile top-up %s: %s",
                    transaction.reference_id, e, exc_info=True,
                )
                await session.rollback()

    logger.info(
        "Top-up reconciliation finished. settled=%s failed=%s abandoned=%s",
        settled, failed, abandoned,
    )
    return {"settled": settled, "failed": failed, "abandoned": abandoned}


if __name__ == "__main__":
    asyncio.run(run_reconcile_pending_topups())
