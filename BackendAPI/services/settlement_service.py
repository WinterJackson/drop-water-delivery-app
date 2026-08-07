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
    from models.vendor_model import Vendor, VendorBusinessType

    result = await session.execute(
        select(func.coalesce(func.sum(func.coalesce(Order.platform_total, 0)), 0))
        .join(Vendor, Vendor.id == Order.vendor_id)
        .where(
            and_(
                Order.vendor_id == vendor_id,
                Order.payment_method == "cash",
                Vendor.vendor_type == VendorBusinessType.wholesale_b2b,
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


# ── The withdrawal schedule ───────────────────────────────────────────────
#
# One definition, read by both withdrawal endpoints. There were two: `POST
# /api/payouts/request` used 250/500/1000 with the fee waived on the *amount*
# requested, and `POST /api/wallet/withdraw` used a flat 500 with the fee waived
# on the *balance* held. The same withdrawal therefore cost a different amount
# depending on which one the app happened to call, and only the first subtracted
# committed cash float — so a rider refused by one endpoint could take the same
# money out of the other, spend the float backing their open cash orders, and
# deliver into a negative balance the platform had no way to collect.


async def withdrawal_terms(
    session: AsyncSession, *, provider_type: str, vendor_type: str | None = None
) -> tuple[Decimal, Decimal, Decimal]:
    """`(minimum, fee, fee_waiver_threshold)` for this kind of account.

    All three come from `Platform_Settings`, so the console owns them like every
    other business figure.
    """
    from services import platform_config_service as config

    await config.ensure_fresh(session)

    fee = config.get_decimal("payout_transaction_fee")

    if provider_type == "rider":
        return (
            config.get_decimal("payout_min_rider"),
            fee,
            config.get_decimal("payout_fee_waiver_rider"),
        )

    if provider_type == "vendor" and vendor_type == "wholesale_b2b":
        return (
            config.get_decimal("payout_min_wholesale_vendor"),
            fee,
            config.get_decimal("payout_fee_waiver_wholesale_vendor"),
        )

    if provider_type == "vendor":
        return (
            config.get_decimal("payout_min_retail_vendor"),
            fee,
            config.get_decimal("payout_fee_waiver_retail_vendor"),
        )

    # A customer withdrawing unspent wallet credit. No minimum beyond the fee
    # and no fee — it is their own money coming back, not earnings.
    return (Decimal("1"), Decimal("0"), Decimal("0"))


def fee_for(amount: Decimal, fee: Decimal, waiver_threshold: Decimal) -> Decimal:
    """The fee actually charged, waived at or above the threshold.

    Keyed on the **amount withdrawn**, never the balance held. Waiving on the
    balance rewards sitting on money rather than making a larger withdrawal,
    which is the opposite of what the waiver is for — the platform pays one
    M-Pesa B2C tariff per disbursement, so it wants fewer, bigger ones.
    """
    return Decimal("0") if amount >= waiver_threshold else fee


async def assert_withdrawable(
    session: AsyncSession,
    *,
    provider_id: UUID,
    provider_type: str,
    wallet_balance,
    amount: Decimal,
) -> Decimal:
    """Refuse a withdrawal that the committed cash float does not cover.

    Returns the available balance. Raises a 400 naming the committed figure,
    because a rider staring at a balance they cannot withdraw with no
    explanation opens a support ticket every time.
    """
    from fastapi import HTTPException

    available = await available_for_payout(
        session,
        provider_id=provider_id,
        provider_type=provider_type,
        wallet_balance=wallet_balance,
    )
    if amount <= available:
        return available

    if provider_type == "vendor":
        committed = await committed_cash_float_for_vendor(session, provider_id)
    elif provider_type == "rider":
        committed = await committed_cash_float(session, provider_id)
    else:
        committed = Decimal("0")

    detail = f"Insufficient balance. Available: KSH {available:.2f}"
    if committed > 0:
        detail += (
            f" (KSH {committed:.2f} of your KSH {_money(wallet_balance):.2f} is held "
            "as float for cash orders you are carrying, and is released when you "
            "deliver them)"
        )
    raise HTTPException(status_code=400, detail=detail + ".")
