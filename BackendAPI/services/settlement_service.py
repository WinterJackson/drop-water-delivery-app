"""
What a rider or vendor may actually withdraw.

`wallet_balance` is the single spendable balance. It is not, however, entirely
free money: when a rider accepts a **cash** order they take on an obligation to
hand the vendor's cut and the platform's cut back out of their own float, settled
at delivery. That commitment exists from the moment they accept, so it must be
deducted from what they can withdraw — otherwise a rider can accept a cash order,
withdraw the float backing it, and leave the platform to fund the vendor.

    available_for_payout = wallet_balance − committed_cash_float

This module owns that arithmetic. Nothing else should re-derive it — the previous
implementation computed withdrawal eligibility from a *derived* sum of `rider_net`
over delivered orders, entirely independent of `wallet_balance`, and the two never
reconciled. That gap is what allowed the same money to be both withdrawn and spent
as float.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_model import Order

logger = logging.getLogger(__name__)

#: An accepted cash order is a live obligation until it reaches a terminal state.
#: `pending_review` and `mismatch_pending` are included deliberately — the rider is
#: still holding goods and the order can still complete.
OPEN_CASH_ORDER_STATUSES = (
    "accepted",
    "preparing",
    "ready",
    "picked_up",
    "pending_review",
    "mismatch_pending",
)


def _money(value) -> Decimal:
    return Decimal(str(value or 0))


async def committed_cash_float(session: AsyncSession, rider_id: UUID) -> Decimal:
    """
    Float this rider has already promised to cash orders they are carrying.

    Equals the amount that will be debited from their wallet when those orders are
    delivered: the vendor's cut plus the platform's cut. The customer's cash covers
    it, but only once the delivery actually completes.
    """
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(Order.vendor_net, 0) + func.coalesce(Order.platform_total, 0)
                ),
                0,
            )
        ).where(
            and_(
                Order.deliverer_id == rider_id,
                Order.payment_method == "cash",
                Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
            )
        )
    )
    return _money(result.scalar())


async def committed_cash_float_for_vendor(session: AsyncSession, vendor_id: UUID) -> Decimal:
    """
    Wholesale equivalent: on a wholesale cash order the vendor's own in-house rider
    collects the cash, and the platform's cut is debited from the *vendor's* wallet
    at delivery. Same reasoning — it is committed from acceptance.
    """
    from models.vendor_model import Vendor, VendorType

    result = await session.execute(
        select(func.coalesce(func.sum(func.coalesce(Order.platform_total, 0)), 0))
        .join(Vendor, Vendor.id == Order.vendor_id)
        .where(
            and_(
                Order.vendor_id == vendor_id,
                Order.payment_method == "cash",
                Vendor.vendor_type == VendorType.wholesale_b2b,
                Order.order_status.in_(OPEN_CASH_ORDER_STATUSES),
            )
        )
    )
    return _money(result.scalar())


async def available_for_payout(
    session: AsyncSession, *, provider_id: UUID, provider_type: str, wallet_balance
) -> Decimal:
    """
    Withdrawable amount: the balance minus obligations already committed to open
    cash orders. Never negative — a rider who owes more than they hold has nothing
    available, and the debt shows as a negative `wallet_balance` rather than as a
    negative allowance.
    """
    balance = _money(wallet_balance)

    if provider_type == "rider":
        committed = await committed_cash_float(session, provider_id)
    elif provider_type == "vendor":
        committed = await committed_cash_float_for_vendor(session, provider_id)
    else:
        committed = Decimal("0")

    return max(Decimal("0"), balance - committed)


async def cash_float_required(order: Order) -> Decimal:
    """Float a rider must hold to accept this cash order."""
    return _money(order.vendor_net) + _money(order.platform_total)
