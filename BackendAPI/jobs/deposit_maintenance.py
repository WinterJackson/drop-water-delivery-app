"""Nightly upkeep on the deposit book: sweeps, dormancy, and reconciliation.

Four jobs, one schedule, because they are all answering the same question — is
what the platform believes it owes still true?

1. **Expire** collections nobody turned up for. Nothing moves; the customer
   keeps the bottles and the deposit.
2. **Settle** collections the rider confirmed and the customer never did, and
   **escalate** the reverse. The asymmetry is the design — see
   `models/bottle_return_model.py`.
3. **Convert** deposits nobody has touched in eighteen months, after two
   warnings, into wallet credit. The value stays with the customer as water.
4. **Reconcile** the deposit book against the orders that created it.

## Why the reconciliation is the important one

Every other part of this platform can be wrong loudly. A deposit book goes wrong
*quietly*: nobody complains that they were not refunded a deposit they forgot
they paid, so the first symptom of a broken accrual is the annual accounts.

Three figures that must agree, checked nightly:

    A  sum(Users.bottle_deposit_balance)          what we say we owe
    B  sum(Orders.bottle_deposit) − returned      what we actually took, net
    C  every account's money and bottle count      the two views of one fact

`A ≠ B` means an accrual or a return moved one side and not the other.
`C` catches the same defect per account, which is what makes it actionable —
"the book is out by KSH 900" is not something anyone can chase, and "these four
accounts hold bottles against a zero balance" is.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from dependencies.dependencies import get_db_session
from models.bottle_return_model import BottleReturnRequest, BottleReturnStatus
from models.order_model import Order
from models.user_model import User
from services import customer_bottle_service as deposits
from services.notification_service import create_notification, queue_push

logger = logging.getLogger(__name__)


async def _config(session):
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    return config


# ── Dormancy ──────────────────────────────────────────────────────────────


async def warn_and_convert_dormant_deposits() -> dict:
    """Two warnings, then the deposit becomes store credit.

    Not a forfeiture, and the distinction matters both ethically and legally:
    the customer keeps every shilling, as wallet credit they can spend on water.
    What the platform recovers is the *bottle* — after eighteen months of
    silence it is not coming back, and carrying it as a returnable asset
    overstates the pool and understates the loss.

    The warnings are the point. A conversion nobody was told about is a
    confiscation with extra steps, which is why the migration that added
    `deposit_last_activity_at` started everybody's clock at zero rather than
    backfilling from their last order — that would have converted long-dormant
    accounts on the first run with no warning ever sent.
    """
    warned = 0
    converted = Decimal("0")
    converted_accounts = 0

    async with get_db_session() as session:
        config = await _config(session)
        dormant_days = config.get_int("deposit_dormant_after_days")
        warn_days = config.get_int("deposit_dormancy_warning_days")

        now = datetime.now(timezone.utc)
        convert_before = now - timedelta(days=dormant_days)
        first_warning_before = now - timedelta(days=dormant_days - warn_days)

        # ── The warnings ──
        due_a_warning = (
            await session.execute(
                select(User).where(
                    and_(
                        User.bottle_deposit_balance > 0,
                        User.deposit_last_activity_at != None,      # noqa: E711
                        User.deposit_last_activity_at < first_warning_before,
                        User.deposit_last_activity_at >= convert_before,
                        User.deposit_dormancy_warned_at == None,    # noqa: E711
                    )
                ).limit(500)
            )
        ).scalars().all()

        for user in due_a_warning:
            due = (user.deposit_last_activity_at + timedelta(days=dormant_days)).date()
            title = "Your bottle deposit"
            message = (
                f"You have KSH {Decimal(str(user.bottle_deposit_balance or 0)):.2f} on "
                f"deposit for {int(user.bottles_held or 0)} bottle(s). If we do not hear "
                f"from you by {due}, it becomes wallet credit you can spend on water. "
                "Book a collection any time and we will bring it back as cash you can "
                "spend right away."
            )
            await create_notification(
                session=session, user_id=user.id, user_type="customer",
                title=title, message=message, message_type="system_alert",
                action_url="/(screens)/BottleWallet",
            )
            queue_push(session, to=user.push_token, title=title, body=message)
            user.deposit_dormancy_warned_at = now
            warned += 1

        if due_a_warning:
            await session.commit()

        # ── The conversion ──
        # Only accounts that were actually warned. An account whose warning
        # failed to send must not be converted on the strength of a timer; it
        # simply waits for the next run, which is the safe direction to fail.
        dormant = (
            await session.execute(
                select(User).where(
                    and_(
                        User.bottle_deposit_balance > 0,
                        User.deposit_last_activity_at != None,     # noqa: E711
                        User.deposit_last_activity_at < convert_before,
                        User.deposit_dormancy_warned_at != None,   # noqa: E711
                    )
                ).with_for_update(skip_locked=True).limit(200)
            )
        ).scalars().all()

        for user in dormant:
            try:
                amount = Decimal(str(user.bottle_deposit_balance or 0))
                bottles = int(user.bottles_held or 0)
                # `_return_bottles` is the shared implementation: it moves both
                # counters, credits the wallet and applies the restriction. The
                # customer is being given their money, not charged — the only
                # thing they lose is a bottle they stopped having.
                await deposits._return_bottles(
                    session, user=user, bottles=bottles,
                    description="Dormant bottle deposit converted to wallet credit",
                    origin="dormancy",
                )
                title = "Deposit converted to credit"
                message = (
                    f"KSH {amount:.2f} of bottle deposit is now wallet credit on your "
                    "account. Spend it on any order — it does not expire."
                )
                await create_notification(
                    session=session, user_id=user.id, user_type="customer",
                    title=title, message=message, message_type="system_alert",
                    action_url="/(screens)/BottleWallet",
                )
                queue_push(session, to=user.push_token, title=title, body=message)
                await session.commit()
                converted += amount
                converted_accounts += 1
            except Exception:
                await session.rollback()
                logger.exception("Could not convert dormant deposit for customer %s", user.id)

    result = {
        "warned": warned,
        "converted_accounts": converted_accounts,
        "converted_amount": str(converted),
    }
    logger.info("Deposit dormancy sweep: %s", result)
    return result


# ── Reconciliation ────────────────────────────────────────────────────────


async def reconcile_deposit_book() -> dict:
    """Check what the platform says it owes against what it actually took.

    Reports rather than repairs. An automatic correction here would paper over
    the accrual bug that caused the drift and leave the platform confident in a
    number it has silently rewritten — the whole value of this job is that the
    figure it produces is one nobody has adjusted.
    """
    async with get_db_session() as session:
        config = await _config(session)
        tolerance = config.get_decimal("deposit_reconciliation_tolerance")

        # A — what we say we owe.
        liability = Decimal(str((
            await session.execute(
                select(func.coalesce(func.sum(User.bottle_deposit_balance), 0))
            )
        ).scalar() or 0))

        # B — what we took on orders that were not cancelled.
        charged = Decimal(str((
            await session.execute(
                select(func.coalesce(func.sum(Order.bottle_deposit), 0))
                .where(Order.order_status != "cancelled")
            )
        ).scalar() or 0))

        # …less what has been given back, from the returns themselves. Read from
        # `Bottle_Return_Requests` and not from wallet rows: a wallet
        # description is prose and matching on it would break the first time
        # somebody rewords a message.
        returned = Decimal(str((
            await session.execute(
                select(func.coalesce(func.sum(BottleReturnRequest.amount_refunded), 0))
                .where(BottleReturnRequest.status == BottleReturnStatus.SETTLED.value)
            )
        ).scalar() or 0))

        expected = charged - returned
        drift = liability - expected

        # C — the two views of one fact, per account.
        incoherent = int((
            await session.execute(
                select(func.count(User.id)).where(
                    or_(
                        and_(User.bottles_held > 0, User.bottle_deposit_balance <= 0),
                        and_(User.bottle_deposit_balance > 0, User.bottles_held <= 0),
                    )
                )
            )
        ).scalar() or 0)

        # Settlements that never reached the rider's ledger, because the
        # collection named no destination store. Logged as an error at the time;
        # counted here so a client that stops sending the field shows up as a
        # number rather than as silence.
        unattributed = int((
            await session.execute(
                select(func.count(BottleReturnRequest.id)).where(
                    and_(
                        BottleReturnRequest.status == BottleReturnStatus.SETTLED.value,
                        # Only a rider collection *has* a destination store. A
                        # console return and a dormancy conversion never move a
                        # physical bottle, so faulting them for having no vendor
                        # would make this counter permanently non-zero and
                        # therefore permanently ignored.
                        BottleReturnRequest.origin == "collection",
                        BottleReturnRequest.vendor_id == None,   # noqa: E711
                    )
                )
            )
        ).scalar() or 0)

        healthy = abs(drift) <= tolerance and incoherent == 0 and unattributed == 0

        report = {
            "liability": str(liability),
            "charged_net_of_returns": str(expected),
            "drift": str(drift),
            "tolerance": str(tolerance),
            "accounts_incoherent": incoherent,
            "settlements_without_a_store": unattributed,
            "healthy": healthy,
        }

    if healthy:
        logger.info("Deposit reconciliation clean: %s", report)
    else:
        # Loud, and at ERROR, because the failure mode this exists to catch is
        # one nobody complains about — a customer does not chase a deposit they
        # have forgotten paying.
        logger.error("DEPOSIT RECONCILIATION FAILED: %s", report)

    return report


# ── The sweeps, wrapped for the scheduler ─────────────────────────────────


async def run_deposit_maintenance() -> dict:
    """Everything the deposit book needs done once a day, in dependency order.

    Expiry and settlement first, so the reconciliation reads a book that has
    already been brought up to date rather than reporting drift the next step
    was about to fix.
    """
    async with get_db_session() as session:
        expired = await deposits.expire_stale_requests(session)
        settled = await deposits.settle_one_sided_confirmations(session)
        escalated = await deposits.escalate_one_sided_customer_claims(session)

    dormancy = await warn_and_convert_dormant_deposits()
    reconciliation = await reconcile_deposit_book()

    return {
        **expired,
        **settled,
        **escalated,
        "dormancy": dormancy,
        "reconciliation": reconciliation,
    }
