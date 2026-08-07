"""
Refundable bottle deposits held against customers.

This is the third bottle relationship on the platform, and until now the only one
with no accounting at all:

| Relationship | Owner |
|---|---|
| Rider holds a vendor's empties | `bottle_ledger_service` |
| Rider owes a vendor, in aggregate | `admin_bottle_service` |
| **Customer has paid a deposit and holds a bottle** | **here** |

A deposit is charged by `pricing_service` whenever the customer keeps the bottle
(`keep_my_bottle`) or has no empty to swap (their first order). That money is
folded into `vendor_net` and paid to the vendor. What was missing is the other
side of the entry: the platform's obligation to give it back.

Without it the platform could not answer "how much deposit has this customer
paid?", there was no way to return one, and `Order` did not even record the
amount charged — it existed only inside a number that had already been added to
somebody else's payout.

Invariant
---------
For every customer:

    bottle_deposit_balance  is the money owed back
    bottles_held            is how many bottles that covers

They are two views of one fact. `_apply` is the only function that writes either,
and it always writes both — the same discipline `bottle_ledger_service` applies
to the rider side, for the same reason.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_model import User

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _apply(user: User, *, amount: Decimal, bottles: int) -> None:
    """Move both counters together. Never call one alone.

    Clamped at zero on both axes: the balance is a liability, and a negative
    liability rendered in the customer's app would read as the platform owing
    them a debt they do not have.
    """
    current_money = _money(getattr(user, "bottle_deposit_balance", 0))
    current_count = int(getattr(user, "bottles_held", 0) or 0)

    user.bottle_deposit_balance = max(ZERO, current_money + amount)
    user.bottles_held = max(0, current_count + bottles)


def bottles_in(items: Iterable) -> int:
    """How many deposit-bearing bottles are in this set of order items.

    Only capacities with a configured deposit count. A dispenser or an accessory
    carries no deposit and is not a bottle the customer is holding, so counting
    it would overstate what the platform owes.
    """
    from services.pricing_service import bottle_deposit_for

    total = 0
    for item in items:
        product = getattr(item, "product", None)
        if product is None:
            continue
        try:
            capacity = int(Decimal(str(getattr(product, "capacity", 0) or 0)))
        except (ValueError, TypeError):
            continue
        if capacity <= 0:
            continue
        if bottle_deposit_for(capacity) is None:
            continue
        total += int(item.quantity or 0)
    return total


async def accrue_deposit(
    session: AsyncSession, *, user: User, amount, bottles: int, order_id=None
) -> None:
    """The customer has paid a deposit and is holding the bottles it covers.

    Called from `create_order`, in the same transaction as the charge, so the
    liability and the payment cannot be recorded apart.
    """
    charged = _money(amount)
    if charged <= ZERO or bottles <= 0:
        return

    _apply(user, amount=charged, bottles=bottles)
    logger.info(
        "Deposit of KSH %s accrued for %s bottle(s) to customer %s (order %s)",
        charged, bottles, user.id, order_id,
    )


async def release_deposit(
    session: AsyncSession, *, user: User, amount, bottles: int, order_id=None
) -> None:
    """Reverse an accrual: the order that charged the deposit was cancelled.

    Not a refund — the customer never received the bottle, so there is nothing to
    give back and nothing to hold. The wallet side is handled by the caller's
    refund path.
    """
    released = _money(amount)
    if released <= ZERO and bottles <= 0:
        return

    _apply(user, amount=-released, bottles=-bottles)
    logger.info(
        "Deposit of KSH %s released for customer %s (cancelled order %s)",
        released, user.id, order_id,
    )


async def refund_deposit(
    session: AsyncSession,
    *,
    customer_id,
    bottles: int,
    actor: str,
    reason: str,
) -> dict:
    """Return a deposit because the customer handed the bottles back.

    Credits their wallet rather than disbursing cash: the platform already holds
    the money as a liability, and a wallet credit is spendable immediately, is
    withdrawable through the normal payout path, and leaves a ledger row that
    explains itself. A B2C disbursement here would be a second money-movement
    path for the same obligation.

    Refuses to return more than is held. The bottle-ledger settlement learned
    this the expensive way: clamping to zero made a typo indistinguishable from
    a legitimate return, and reported success either way.
    """
    if bottles <= 0:
        raise HTTPException(status_code=400, detail="Enter at least one bottle to return.")

    user = (
        await session.execute(
            select(User).where(User.id == customer_id).with_for_update()
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    held = int(user.bottles_held or 0)
    if bottles > held:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This customer holds {held} bottle(s) on deposit; "
                f"cannot return {bottles}."
            ),
        )

    balance = _money(user.bottle_deposit_balance)
    # Per-bottle average rather than the current schedule: the customer is owed
    # what they actually paid, and the deposit schedule may have changed since.
    # Returning every bottle returns the whole balance, with no rounding residue
    # stranded on the account.
    if bottles == held:
        amount = balance
    else:
        amount = _money(balance * Decimal(bottles) / Decimal(held))

    from models.wallet_transaction_model import TransactionType
    from services.wallet_service import apply_wallet_delta

    _apply(user, amount=-amount, bottles=-bottles)

    await apply_wallet_delta(
        session,
        owner=user,
        clerk_id=user.clerk_id,
        user_type="customer",
        amount=amount,
        transaction_type=TransactionType.refund,
        description=f"Bottle deposit returned ({bottles} bottle(s)) — {reason}",
    )

    logger.info(
        "Deposit refund of KSH %s for %s bottle(s) to customer %s by %s",
        amount, bottles, customer_id, actor,
    )

    return {
        "customer_id": str(customer_id),
        "bottles_returned": bottles,
        "amount_refunded": str(amount),
        "bottles_still_held": int(user.bottles_held or 0),
        "deposit_balance": str(_money(user.bottle_deposit_balance)),
    }
