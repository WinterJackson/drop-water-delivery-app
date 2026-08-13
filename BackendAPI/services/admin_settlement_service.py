"""Refunds, payouts and the platform's cash exposure.

Three things that move money without a person pressing anything, and none of
them had a reader.

## Refunds

`refund_service` sweeps orders in `refund_pending`, calls the M-Pesa reversal
API, and moves them to `refund_processing`, then `refunded` or `refund_failed`.
Nothing surfaced any of those states. `refund_failed` is the one that matters:
the customer paid, the order was cancelled, and the money did not come back — and
the only trace is a column on a row nobody queries. Those customers do not write
in; they stop using the platform.

`refund_processing` is the second: the reversal was accepted by Safaricom and the
result callback never arrived. It is indistinguishable from a completed refund
except by age, which is why age is the whole signal here.

## Payouts

Two invariants that were declared in `payout_service` and checked by nothing:

* **A failed payout must have been refunded to the wallet.** The debit happens up
  front so the money cannot be spent twice while the B2C call is in flight, which
  makes the refund on failure mandatory — without it a failed payout silently
  confiscates the amount. `_refund_failed_payout` writes a `refund`
  `WalletTransaction` with `reference_id = payout.id`, so the check is a left
  join, and a `failed` payout with no matching row is money that vanished.
* **A completed payout should carry an M-Pesa receipt.** `completed` with no
  receipt means the platform recorded a disbursement it cannot evidence.

## Cash float

`committed_cash_float` gates every withdrawal and is computed per provider, one
at a time, so the platform's total cash-at-risk has never been visible. It is the
money customers are holding in notes against orders already accepted — the
platform's largest uninsured exposure and, until this, an unknown one.

## Data honesty

`payouts` and `WalletTransactions` are both empty on this deployment, and no
order has reached any refund state. Everything below is ordinary aggregation over
those tables and was exercised against fixtures; none of it has been observed
against real settlement volume, and `STUCK_AFTER_HOURS` in particular is a first
estimate rather than a figure drawn from how long Safaricom actually takes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import String, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from utils import keyset

from models.deliverer_model import Deliverer
from models.order_model import Order
from models.payout_model import Payout
from models.user_model import User
from models.vendor_model import Vendor, VendorBusinessType
from models.wallet_transaction_model import TransactionType, WalletTransaction
from services.settlement_service import OPEN_CASH_ORDER_STATUSES

#: Past this, an in-flight reversal or disbursement has almost certainly lost its
#: callback rather than merely being slow. Safaricom settles B2C in minutes; six
#: hours is generous on purpose, because a false "stuck" sends somebody chasing a
#: payment that is about to land.
STUCK_AFTER_HOURS = 6

REFUND_STATES = ("refund_pending", "refund_processing", "refunded", "refund_failed")

#: The refund states where the customer is still out of pocket.
REFUND_OUTSTANDING = ("refund_pending", "refund_processing", "refund_failed")


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def _hours_since(moment: datetime | None) -> float | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - moment).total_seconds() / 3600, 1)


async def refunds(
    db: AsyncSession, *, limit: int = 100, cursor: str | None = None
) -> dict[str, Any]:
    """Where every cancelled-and-paid order stands with its money."""
    rows = (
        await db.execute(
            select(
                Order.payment_status,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .where(Order.payment_status.in_(REFUND_STATES))
            .group_by(Order.payment_status)
        )
    ).all()

    by_state = {
        state: {"count": 0, "amount": Decimal("0")} for state in REFUND_STATES
    }
    for state, count, amount in rows:
        by_state[state] = {"count": int(count or 0), "amount": Decimal(str(amount or 0))}

    outstanding = sum(
        (by_state[state]["amount"] for state in REFUND_OUTSTANDING), Decimal("0")
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STUCK_AFTER_HOURS)
    stuck = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.payment_status == "refund_processing",
                    Order.updated_at < cutoff,
                )
            )
        ).scalar()
        or 0
    )

    # Failed first, then the oldest in flight: a failed refund is a customer who
    # has already been let down, and it stays failed until somebody acts.
    #
    # The rank column is selected as well as ordered by, so the cursor can carry
    # it — paging past the last failed refund must not land back among them.
    failed_first = (Order.payment_status == "refund_failed").label("failed_first")
    outstanding_query = (
        select(Order, User.full_name, User.phone_number, failed_first)
        .outerjoin(User, User.id == Order.customer_id)
        .where(Order.payment_status.in_(REFUND_OUTSTANDING))
    )
    # Ascending on time — oldest first — but the rank must stay descending, so
    # the two are expressed as one ordering with the rank inverted rather than
    # as two `keyset.Order`s, which cannot be combined.
    ranking = keyset.Order(
        (Order.payment_status != "refund_failed").label("failed_first"),
        Order.updated_at,
        Order.id,
        descending=False,
    )
    items, next_cursor = keyset.split(
        (await db.execute(keyset.seek(outstanding_query, ranking, cursor).limit(limit + 1))).all(),
        limit,
        ranking,
    )

    return {
        "summary": {
            "pending": by_state["refund_pending"]["count"],
            "processing": by_state["refund_processing"]["count"],
            "failed": by_state["refund_failed"]["count"],
            "refunded": by_state["refunded"]["count"],
            "stuck_processing": stuck,
            "stuck_after_hours": STUCK_AFTER_HOURS,
            "outstanding_amount": _money(outstanding),
            "failed_amount": _money(by_state["refund_failed"]["amount"]),
            "refunded_amount": _money(by_state["refunded"]["amount"]),
        },
        "items": [
            {
                "order_id": str(order.id),
                "status": order.payment_status,
                "amount": _money(order.total_amount),
                "customer": name,
                "phone": phone,
                "order_status": order.order_status,
                "hours_since_update": _hours_since(order.updated_at),
                "stuck": order.payment_status == "refund_processing"
                and (_hours_since(order.updated_at) or 0) >= STUCK_AFTER_HOURS,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            for order, name, phone, _ in items
        ],
        "next_cursor": next_cursor,
        # Known without a second query: the summary above is a GROUP BY over
        # every outstanding row, so the population is already counted.
        "total": (
            by_state["refund_pending"]["count"]
            + by_state["refund_processing"]["count"]
            + by_state["refund_failed"]["count"]
        ),
    }


async def payouts(db: AsyncSession, *, limit: int = 100) -> dict[str, Any]:
    """Disbursements, and the two ways one can go wrong quietly."""
    rows = (
        await db.execute(
            select(
                Payout.status,
                func.count(Payout.id),
                func.coalesce(func.sum(Payout.amount), 0),
            ).group_by(Payout.status)
        )
    ).all()
    by_status = {
        status: {"count": int(count or 0), "amount": Decimal(str(amount or 0))}
        for status, count, amount in rows
    }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STUCK_AFTER_HOURS)

    #: Sent to M-Pesa and never confirmed. The money may or may not have left.
    stuck_rows = (
        await db.execute(
            select(Payout)
            .where(Payout.status == "processing", Payout.updated_at < cutoff)
            .order_by(Payout.updated_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    #: Recorded as paid with nothing to evidence it.
    unreceipted = (
        await db.execute(
            select(Payout)
            .where(Payout.status == "completed", Payout.mpesa_receipt.is_(None))
            .order_by(Payout.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    #: The invariant `payout_service` declares and nothing checked: a failed
    #: payout must have returned the debited amount to the wallet.
    refund_exists = (
        select(WalletTransaction.id)
        .where(
            # `reference_id` is a String and `Payout.id` a UUID — the cast is
            # what makes this correlate rather than raise.
            WalletTransaction.reference_id == func.cast(Payout.id, String),
            WalletTransaction.transaction_type == TransactionType.refund,
        )
        .exists()
    )
    unrefunded = (
        await db.execute(
            select(Payout)
            .where(Payout.status == "failed", ~refund_exists)
            .order_by(Payout.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    async def _named(payout: Payout) -> str | None:
        model = Vendor if payout.provider_type == "vendor" else Deliverer
        column = Vendor.business_name if payout.provider_type == "vendor" else Deliverer.name
        return (
            await db.execute(select(column).where(model.id == payout.provider_id))
        ).scalar()

    def _row(payout: Payout, name: str | None) -> dict[str, Any]:
        return {
            "id": str(payout.id),
            "provider_type": payout.provider_type,
            "provider_id": str(payout.provider_id),
            "provider_name": name,
            "amount": _money(payout.amount),
            "status": payout.status,
            # Never the account number: this screen is read by anyone with
            # finance.read, and the destination is encrypted at rest for a reason.
            "has_receipt": payout.mpesa_receipt is not None,
            "conversation_id": payout.conversation_id,
            "failure_reason": payout.failure_reason,
            "hours_since_update": _hours_since(payout.updated_at),
            "created_at": payout.created_at.isoformat() if payout.created_at else None,
        }

    async def _rows(items: list[Payout]) -> list[dict[str, Any]]:
        return [_row(payout, await _named(payout)) for payout in items]

    unrefunded_amount = sum(
        (Decimal(str(payout.amount or 0)) for payout in unrefunded), Decimal("0")
    )

    return {
        "summary": {
            "pending": by_status.get("pending", {}).get("count", 0),
            "processing": by_status.get("processing", {}).get("count", 0),
            "completed": by_status.get("completed", {}).get("count", 0),
            "failed": by_status.get("failed", {}).get("count", 0),
            "completed_amount": _money(by_status.get("completed", {}).get("amount", 0)),
            "in_flight_amount": _money(
                by_status.get("processing", {}).get("amount", 0)
                + by_status.get("pending", {}).get("amount", 0)
            ),
            "stuck": len(stuck_rows),
            "stuck_after_hours": STUCK_AFTER_HOURS,
            "unreceipted": len(unreceipted),
            "unrefunded_failures": len(unrefunded),
            "unrefunded_amount": _money(unrefunded_amount),
        },
        "stuck": await _rows(stuck_rows),
        "unreceipted": await _rows(unreceipted),
        "unrefunded": await _rows(unrefunded),
    }


async def cash_exposure(db: AsyncSession) -> dict[str, Any]:
    """Cash customers are holding against orders already accepted.

    `settlement_service` computes this one provider at a time to gate a
    withdrawal. The same arithmetic, aggregated: for riders, the vendor's cut
    plus the platform's; for wholesale vendors whose own rider collects, the
    platform's cut alone. Duplicating the expressions here rather than calling
    the per-provider function 51 times is the trade — and the two must be read
    together, because a divergence would be invisible until a withdrawal was
    wrongly allowed.
    """
    rider_float = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(Order.vendor_net, 0)
                        + func.coalesce(Order.platform_total, 0)
                    ),
                    0,
                ),
                func.count(func.distinct(Order.deliverer_id)),
                func.count(Order.id),
            ).where(
                and_(
                    Order.deliverer_id.isnot(None),
                    Order.payment_method == "cash",
                    Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
                )
            )
        )
    ).one()

    vendor_float = (
        await db.execute(
            select(
                func.coalesce(func.sum(func.coalesce(Order.platform_total, 0)), 0),
                func.count(func.distinct(Order.vendor_id)),
            )
            .join(Vendor, Vendor.id == Order.vendor_id)
            .where(
                and_(
                    Order.payment_method == "cash",
                    Vendor.vendor_type == VendorBusinessType.wholesale_b2b,
                    Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
                )
            )
        )
    ).one()

    #: Negative balances are a rider who owes the platform more than they hold —
    #: usually cash collected and not remitted. It is a debt, not an allowance.
    negative = (
        await db.execute(
            select(
                func.count(Deliverer.id),
                func.coalesce(func.sum(Deliverer.wallet_balance), 0),
            ).where(Deliverer.wallet_balance < 0)
        )
    ).one()

    payable = (
        await db.execute(
            select(func.coalesce(func.sum(Deliverer.wallet_balance), 0)).where(
                Deliverer.wallet_balance > 0
            )
        )
    ).scalar()
    vendor_payable = (
        await db.execute(
            select(func.coalesce(func.sum(Vendor.wallet_balance), 0)).where(
                Vendor.wallet_balance > 0
            )
        )
    ).scalar()

    return {
        "rider_float": _money(rider_float[0]),
        "riders_carrying": int(rider_float[1] or 0),
        "open_cash_orders": int(rider_float[2] or 0),
        "vendor_float": _money(vendor_float[0]),
        "vendors_carrying": int(vendor_float[1] or 0),
        "total_float": _money(Decimal(str(rider_float[0] or 0)) + Decimal(str(vendor_float[0] or 0))),
        "riders_in_debt": int(negative[0] or 0),
        "debt_total": _money(abs(Decimal(str(negative[1] or 0)))),
        "wallet_liability": _money(
            Decimal(str(payable or 0)) + Decimal(str(vendor_payable or 0))
        ),
    }
