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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bottle_return_model import (
    OPEN_STATUSES,
    BottleReturnRequest,
    BottleReturnStatus,
)
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

    Also stamps `deposit_last_activity_at`, which is what dormancy is measured
    from. Measuring it from `last_order_date` would convert the deposit of a
    customer who orders every week on `exchange` and simply never touches it.
    """
    current_money = _money(getattr(user, "bottle_deposit_balance", 0))
    current_count = int(getattr(user, "bottles_held", 0) or 0)

    user.bottle_deposit_balance = max(ZERO, current_money + amount)
    user.bottles_held = max(0, current_count + bottles)
    user.deposit_last_activity_at = datetime.now(timezone.utc)
    # A movement is a sign of life; the next dormancy warning starts from
    # scratch rather than from a latch set two years ago.
    user.deposit_dormancy_warned_at = None


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

    # One implementation of what a bottle is worth back, shared with the rider
    # collection path. Two would drift, and the console and the rider app
    # quoting different figures for the same handover is a dispute the platform
    # cannot win.
    amount = await _return_bottles(
        session,
        user=user,
        bottles=bottles,
        description=f"Bottle deposit returned ({bottles} bottle(s)) — {reason}",
        origin="console",
        actor_email=actor,
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


# ── How many bottles one account may hold ─────────────────────────────────


async def bottle_ceiling(session: AsyncSession, user: User) -> int:
    """The most deposit-bearing bottles this account may hold at once.

    Unlimited bottles is unlimited liability, and an unlimited-size target for
    anyone who works out that the deposit is the cheapest way to acquire a
    twenty-litre bottle at cost. A commercial account legitimately holds more
    than a household, which is why the ceiling is two settings and not one.
    """
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    key = (
        "max_bottles_held_commercial"
        if bool(getattr(user, "is_commercial", False))
        else "max_bottles_held_household"
    )
    return config.get_int(key)


async def assert_can_hold(session: AsyncSession, *, user: User, additional: int) -> None:
    """Refuse an order that would put this account over its bottle ceiling.

    Raised at quote time so the customer is told before they pay, not after.
    The message names the ceiling and the way out — a refusal a customer cannot
    act on is a support ticket.
    """
    if additional <= 0:
        return

    ceiling = await bottle_ceiling(session, user)
    held = int(getattr(user, "bottles_held", 0) or 0)
    if held + additional <= ceiling:
        return

    raise HTTPException(
        status_code=400,
        detail=(
            f"This would leave you holding {held + additional} bottles on deposit, "
            f"and the limit is {ceiling}. Return some of the {held} you already "
            "have and the deposit comes straight back to your wallet."
        ),
    )


# ── Credit that buys water but not a withdrawal ───────────────────────────


async def _credit_returned_deposit(
    session: AsyncSession, *, user: User, amount: Decimal, description: str
) -> None:
    """Put a returned deposit back on the customer's wallet.

    Restricted unless an administrator has decided otherwise. The money is
    spendable on the next order immediately — it is not held back from the
    customer in any way they will notice — but it cannot be withdrawn as cash,
    because a deposit that can be is a money-transfer service: pay KSH 300 by
    M-Pesa, hand the bottle back, take KSH 300 out to a different phone. With
    the welcome discount applied to the deposit that round trip cleared a
    profit, so it would have been farmed rather than merely possible.
    """
    from models.wallet_transaction_model import TransactionType
    from services import platform_config_service as config
    from services.wallet_service import apply_wallet_delta

    if amount <= ZERO:
        return

    await config.ensure_fresh(session)
    withdrawable = config.get_bool("deposit_refund_is_withdrawable")

    await apply_wallet_delta(
        session,
        owner=user,
        clerk_id=user.clerk_id,
        user_type="customer",
        amount=amount,
        transaction_type=TransactionType.refund,
        description=description,
    )

    if not withdrawable:
        current = _money(getattr(user, "non_withdrawable_balance", 0))
        user.non_withdrawable_balance = current + amount


def _amount_for(user: User, bottles: int) -> Decimal:
    """What this customer is owed for handing back `bottles` of theirs.

    A per-bottle average of what they actually paid, not the current schedule:
    the deposit for a 20 L bottle may have been 250 when they paid it and 300
    today, and they are owed the 250. Returning *all* of them returns the whole
    balance, so no rounding residue is ever stranded on the account.
    """
    balance = _money(user.bottle_deposit_balance)
    held = int(user.bottles_held or 0)
    if held <= 0:
        return ZERO
    if bottles >= held:
        return balance
    return _money(balance * Decimal(bottles) / Decimal(held))


async def _return_bottles(
    session: AsyncSession,
    *,
    user: User,
    bottles: int,
    description: str,
    request: BottleReturnRequest | None = None,
    origin: str = "collection",
    actor_email: str | None = None,
) -> Decimal:
    """The money half of a return, shared by every path that performs one.

    The console's manual return and the rider's collection must agree to the
    shilling on what a bottle is worth back, and they will not stay in
    agreement if each does its own arithmetic. This is that arithmetic.

    It also guarantees the **record**. Every deposit that goes back leaves a
    settled `BottleReturnRequest`, whether a rider collected it, an
    administrator returned it or the dormancy sweep converted it — one place to
    answer "what have we given back", and the other side of the entry the
    nightly reconciliation subtracts. Without it the console and the sweep each
    reduced the liability against nothing, and the book reported growing drift
    that was indistinguishable from a real accrual bug.
    """
    amount = _amount_for(user, bottles)
    _apply(user, amount=-amount, bottles=-bottles)
    await _credit_returned_deposit(
        session, user=user, amount=amount, description=description
    )

    if request is None:
        request = BottleReturnRequest(
            customer_id=user.id,
            bottles_requested=bottles,
            origin=origin,
            status=BottleReturnStatus.SETTLED.value,
            resolved_by_email=actor_email,
            resolution_note=description,
        )
        session.add(request)
        request.bottles_settled = bottles
        request.amount_refunded = amount
        request.settled_at = datetime.now(timezone.utc)

    return amount


# ── The handover: request, two confirmations, settlement ──────────────────
#
# The two confirmations are not symmetric, and the asymmetry is the design.
# See `models/bottle_return_model.py` for the reasoning; in short, a timeout
# resolves in favour of whichever side put a physical asset at risk, because
# that is the only side with anything to lose by lying.


async def _config(session: AsyncSession):
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    return config


async def open_request_for(session: AsyncSession, customer_id) -> BottleReturnRequest | None:
    """The customer's live request, if they have one."""
    return (
        await session.execute(
            select(BottleReturnRequest).where(
                and_(
                    BottleReturnRequest.customer_id == customer_id,
                    BottleReturnRequest.status.in_([s.value for s in OPEN_STATUSES]),
                )
            ).order_by(BottleReturnRequest.created_at.desc())
        )
    ).scalars().first()


async def request_return(
    session: AsyncSession, *, customer_id, bottles: int
) -> BottleReturnRequest:
    """The customer asks for their bottles to be collected.

    One open request per customer. A second would let somebody raise six
    requests for the same four bottles and settle whichever a rider reached
    first, and there is no legitimate reason to need two.
    """
    if bottles <= 0:
        raise HTTPException(status_code=400, detail="Say how many bottles you want collected.")

    user = (
        await session.execute(
            select(User).where(User.id == customer_id).with_for_update()
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    held = int(user.bottles_held or 0)
    if held <= 0:
        raise HTTPException(
            status_code=400,
            detail="You are not holding any bottles on deposit at the moment.",
        )
    if bottles > held:
        raise HTTPException(
            status_code=400,
            detail=f"You are holding {held} bottle(s) on deposit; you cannot return {bottles}.",
        )

    existing = await open_request_for(session, customer_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a collection booked. Cancel it first if you want to change it.",
        )

    config = await _config(session)
    window = config.get_int("deposit_return_window_hours")

    request = BottleReturnRequest(
        customer_id=customer_id,
        bottles_requested=bottles,
        status=BottleReturnStatus.REQUESTED.value,
        # Stored rather than computed on read: changing the setting must not
        # retroactively expire a collection somebody is in the middle of.
        expires_at=datetime.now(timezone.utc) + timedelta(hours=window),
    )
    session.add(request)
    await session.flush()

    logger.info(
        "Bottle return requested by customer %s for %s bottle(s) (request %s)",
        customer_id, bottles, request.id,
    )
    return request


async def assign_rider(
    session: AsyncSession, *, request_id, rider_id, vendor_id=None, order_id=None
) -> BottleReturnRequest:
    """A rider takes the collection on.

    `vendor_id` is where the bottles will be handed in. It may be deferred to
    confirmation for a standalone pickup, but it must exist before settlement —
    a returned bottle the ledger cannot attribute is one the platform has quietly
    stopped counting.
    """
    request = await _locked_request(session, request_id)

    if request.status not in (BottleReturnStatus.REQUESTED.value,):
        raise HTTPException(
            status_code=409,
            detail="Another rider has already taken this collection.",
        )

    request.rider_id = rider_id
    request.vendor_id = vendor_id or request.vendor_id
    request.order_id = order_id or request.order_id
    request.status = BottleReturnStatus.ASSIGNED.value
    return request


async def _locked_request(session: AsyncSession, request_id) -> BottleReturnRequest:
    request = (
        await session.execute(
            select(BottleReturnRequest)
            .where(BottleReturnRequest.id == request_id)
            .with_for_update()
        )
    ).scalars().first()
    if request is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return request


async def confirm_handover(
    session: AsyncSession,
    *,
    request_id,
    bottles: int,
    by: str,
    actor_id,
    vendor_id=None,
) -> dict:
    """One side states how many bottles actually changed hands.

    `by` is `"customer"` or `"rider"`. When both have stated the **same** count
    the deposit is returned immediately. When they differ it becomes a dispute
    for a human — never a split of the difference, because a rider who learns
    that claiming one fewer each time costs nobody anything will do exactly
    that, and it would take months to notice.
    """
    if by not in ("customer", "rider"):
        raise ValueError(f"Unknown confirming party {by!r}")
    if bottles < 0:
        raise HTTPException(status_code=400, detail="A bottle count cannot be negative.")

    request = await _locked_request(session, request_id)

    if request.status not in [s.value for s in OPEN_STATUSES]:
        # Settled, disputed, expired or cancelled. A retried tap from an offline
        # queue must not pay a second time.
        raise HTTPException(
            status_code=409,
            detail="This collection has already been closed.",
        )

    if by == "customer":
        if request.customer_id != actor_id:
            raise HTTPException(status_code=403, detail="This is not your collection.")
        request.bottles_stated_by_customer = bottles
        request.customer_confirmed_at = datetime.now(timezone.utc)
    else:
        if request.rider_id not in (None, actor_id):
            raise HTTPException(status_code=403, detail="This collection is assigned to another rider.")
        request.rider_id = actor_id
        request.vendor_id = vendor_id or request.vendor_id
        request.bottles_stated_by_rider = bottles
        request.rider_confirmed_at = datetime.now(timezone.utc)

    stated_customer = request.bottles_stated_by_customer
    stated_rider = request.bottles_stated_by_rider

    if stated_customer is None or stated_rider is None:
        request.status = BottleReturnStatus.AWAITING_COUNTERPARTY.value
        return {
            "status": request.status,
            "waiting_on": "rider" if stated_rider is None else "customer",
            "request_id": str(request.id),
        }

    if stated_customer != stated_rider:
        request.status = BottleReturnStatus.DISPUTED.value
        request.resolution_note = (
            f"The customer counted {stated_customer} bottle(s) and the rider counted "
            f"{stated_rider}. Nothing has moved until somebody checks."
        )
        logger.warning(
            "Bottle return %s disputed: customer %s vs rider %s",
            request.id, stated_customer, stated_rider,
        )
        await _tell_customer(
            session, request.customer_id,
            title="We need to check your collection",
            message=(
                f"You counted {stated_customer} bottle(s) and the rider counted "
                f"{stated_rider}. Nothing has moved and your deposit is safe — "
                "somebody is looking at it now."
            ),
        )
        return {
            "status": request.status,
            "request_id": str(request.id),
            "detail": request.resolution_note,
        }

    return await settle_return(session, request=request, bottles=stated_rider, reason="both parties confirmed")


async def settle_return(
    session: AsyncSession, *, request: BottleReturnRequest, bottles: int, reason: str
) -> dict:
    """Move the money and the bottles. The only place a collection pays out.

    Three things happen together or not at all: the customer's deposit position
    falls, their wallet rises by what they actually paid for those bottles, and
    the rider's ledger records that they are now holding them. Doing the first
    two without the third is how a bottle leaves every count on the platform
    while still physically existing in somebody's pannier.
    """
    user = (
        await session.execute(
            select(User).where(User.id == request.customer_id).with_for_update()
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    held = int(user.bottles_held or 0)
    if bottles > held:
        # The customer's position moved between the request and the handover —
        # they ordered again, or an administrator already returned some. Settle
        # what is actually there rather than refusing, and say so.
        logger.warning(
            "Bottle return %s claims %s bottle(s) but customer %s holds %s; settling the lower.",
            request.id, bottles, user.id, held,
        )
        bottles = held

    if bottles <= 0:
        request.status = BottleReturnStatus.DISPUTED.value
        request.resolution_note = (
            "This account was not holding any bottles on deposit when the "
            "collection was confirmed."
        )
        return {"status": request.status, "request_id": str(request.id),
                "detail": request.resolution_note}

    amount = await _return_bottles(
        session,
        user=user,
        bottles=bottles,
        description=f"Bottle deposit returned ({bottles} bottle(s)) — {reason}",
        request=request,
    )

    await _record_rider_holding(session, request=request, bottles=bottles)

    request.bottles_settled = bottles
    request.amount_refunded = amount
    request.settled_at = datetime.now(timezone.utc)
    request.status = BottleReturnStatus.SETTLED.value

    logger.info(
        "Bottle return %s settled: %s bottle(s), KSH %s to customer %s (%s)",
        request.id, bottles, amount, user.id, reason,
    )

    return {
        "status": request.status,
        "request_id": str(request.id),
        "bottles_returned": bottles,
        "amount_refunded": str(amount),
        "bottles_still_held": int(user.bottles_held or 0),
        "deposit_balance": str(_money(user.bottle_deposit_balance)),
    }


async def _record_rider_holding(
    session: AsyncSession, *, request: BottleReturnRequest, bottles: int
) -> None:
    """The rider now holds these bottles and owes them to a store.

    Skipped, loudly, when the collection never named a vendor. The alternative —
    refusing to settle — would hold the customer's money hostage to a field the
    rider app failed to send, which punishes the wrong person. The nightly
    reconciliation counts these, so a client that stops sending it shows up as a
    number rather than as silence.
    """
    from models.bottle_ledger_model import BottleLedgerEntry, BottleLedgerEntryType

    from models.vendor_model import Vendor

    if request.rider_id is None or request.vendor_id is None:
        logger.error(
            "Bottle return %s settled with no %s; %s bottle(s) are outside the ledger.",
            request.id,
            "rider" if request.rider_id is None else "destination store",
            bottles,
        )
        return

    # The store is named by the client, and `bottle_ledger_entries.vendor_id` is
    # a real foreign key. An id that does not resolve would raise at flush —
    # *after* the wallet credit above — so the whole transaction rolls back and
    # the customer's deposit is not returned, over a field they had no part in.
    # Checked here so a bad id costs a ledger row and a loud log, never the
    # refund. The nightly reconciliation counts what this skips.
    exists = (
        await session.execute(select(Vendor.id).where(Vendor.id == request.vendor_id))
    ).scalar()
    if exists is None:
        logger.error(
            "Bottle return %s names store %s, which does not exist; %s bottle(s) "
            "are outside the ledger.",
            request.id, request.vendor_id, bottles,
        )
        request.vendor_id = None
        return

    capacity, basis = await _returned_capacity(session, request.customer_id)

    session.add(
        BottleLedgerEntry(
            rider_id=request.rider_id,
            vendor_id=request.vendor_id,
            order_id=request.order_id,
            capacity_litres=capacity,
            quantity=bottles,
            entry_type=BottleLedgerEntryType.DEPOSIT_RETURN,
            note=f"Deposit return {request.id} collected from customer ({basis})",
        )
    )


async def _returned_capacity(session: AsyncSession, customer_id) -> tuple[int, str]:
    """What size the bottles coming back are, and how we know.

    `bottles_held` is one integer with no size breakdown, so the capacity has to
    be inferred. It was a hardcoded 20 — which is wrong for every household on
    10 L, and wrong in the direction that matters: `bottle_ledger_service` keeps
    a counter per capacity and values it at that capacity's deposit, so a 10 L
    return recorded as 20 L overstates the float against that store by the
    difference and understates the 10 L pool by the same bottles.

    Inferred from what the customer actually took a deposit on, which is a fact
    the platform holds. A household orders one size, so this is exact in the
    ordinary case. The basis is written into the ledger note either way, because
    an inferred figure that does not say it is inferred is one somebody will
    later treat as measured.
    """
    from models.order_model import Order, OrderItem
    from models.product_model import Product

    capacity = (
        await session.execute(
            select(Product.capacity)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                and_(
                    Order.customer_id == customer_id,
                    Order.bottle_deposit > 0,
                    Order.order_status != "cancelled",
                    Product.capacity != None,  # noqa: E711
                )
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
    ).scalar()

    if capacity:
        return int(capacity), "capacity from their last deposit-bearing order"

    # No deposit-bearing order on record — an opening balance, or a migration.
    # Fall back to the largest capacity the platform prices, which is the
    # conservative direction: it never *understates* what a store is owed.
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    schedule = config.get("bottle_deposit_by_capacity") or {}
    sizes = [int(key) for key in schedule if str(key).isdigit()]
    fallback = max(sizes) if sizes else 20
    logger.warning(
        "Deposit return for customer %s has no priced order to infer capacity from; "
        "recording %sL.", customer_id, fallback,
    )
    return fallback, f"assumed {fallback}L — no deposit-bearing order on record"


async def cancel_request(session: AsyncSession, *, request_id, customer_id) -> dict:
    """The customer changes their mind. Only before anybody has confirmed."""
    request = await _locked_request(session, request_id)
    if request.customer_id != customer_id:
        raise HTTPException(status_code=403, detail="This is not your collection.")
    if request.status not in [s.value for s in OPEN_STATUSES]:
        raise HTTPException(status_code=409, detail="This collection has already been closed.")
    if request.rider_confirmed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="A rider has already collected these bottles. Contact support if that is wrong.",
        )

    request.status = BottleReturnStatus.CANCELLED.value
    return {"status": request.status, "request_id": str(request.id)}


async def _tell_customer(session: AsyncSession, customer_id, *, title: str, message: str) -> None:
    """Say what happened, through the platform's own two paths.

    A collection that quietly changes status is the worst version of this
    feature: somebody is waiting on money, and silence reads as the platform
    keeping it. `queue_push` rather than a bare task, so a rollback discards the
    message along with the change it was announcing.
    """
    from services.notification_service import create_notification, queue_push

    token = (
        await session.execute(select(User.push_token).where(User.id == customer_id))
    ).scalar()

    await create_notification(
        session=session,
        user_id=customer_id,
        user_type="customer",
        title=title,
        message=message,
        message_type="system_alert",
        action_url="/(screens)/BottleWallet",
    )
    queue_push(session, to=token, title=title, body=message)


# ── The sweeps ────────────────────────────────────────────────────────────


async def settle_one_sided_confirmations(session: AsyncSession) -> dict:
    """Pay out collections the rider confirmed and the customer never did.

    The one-sided settlement the design permits, and only in this direction.
    The rider has stated they took possession of a physical asset and is
    carrying it on their own ledger; a statement against one's own interest is
    evidence. The reverse case — the customer alone — is deliberately absent
    from this function and is swept into `DISPUTED` below.
    """
    config = await _config(session)
    minutes = config.get_int("deposit_return_auto_settle_minutes")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    rows = (
        await session.execute(
            select(BottleReturnRequest)
            .where(
                and_(
                    BottleReturnRequest.status == BottleReturnStatus.AWAITING_COUNTERPARTY.value,
                    BottleReturnRequest.rider_confirmed_at != None,   # noqa: E711
                    BottleReturnRequest.customer_confirmed_at == None,  # noqa: E711
                    BottleReturnRequest.rider_confirmed_at < cutoff,
                )
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).scalars().all()

    settled = 0
    for request in rows:
        # Per item, so one bad row cannot discard the batch — the same
        # discipline every sweep on this platform follows.
        try:
            outcome = await settle_return(
                session,
                request=request,
                bottles=int(request.bottles_stated_by_rider or 0),
                reason="the rider confirmed collection and the confirmation window elapsed",
            )
            if outcome.get("status") == BottleReturnStatus.SETTLED.value:
                await _tell_customer(
                    session, request.customer_id,
                    title="Deposit returned",
                    message=(
                        f"KSH {outcome.get('amount_refunded')} is back in your "
                        f"wallet for {outcome.get('bottles_returned')} bottle(s). "
                        "Spend it on your next order."
                    ),
                )
            await session.commit()
            settled += 1
        except Exception:
            await session.rollback()
            logger.exception("Could not auto-settle bottle return %s", request.id)

    return {"auto_settled": settled}


async def escalate_one_sided_customer_claims(session: AsyncSession) -> dict:
    """A customer confirmed and no rider ever did. This goes to a human.

    Never auto-settled, at any interval. A timer that pays out a unilateral
    claim is a timer that pays anybody willing to wait for it, and the whole
    reason two confirmations exist is that one tap is not evidence that bottles
    moved.
    """
    config = await _config(session)
    minutes = config.get_int("deposit_return_auto_settle_minutes")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    rows = (
        await session.execute(
            select(BottleReturnRequest)
            .where(
                and_(
                    BottleReturnRequest.status == BottleReturnStatus.AWAITING_COUNTERPARTY.value,
                    BottleReturnRequest.customer_confirmed_at != None,  # noqa: E711
                    BottleReturnRequest.rider_confirmed_at == None,     # noqa: E711
                    BottleReturnRequest.customer_confirmed_at < cutoff,
                )
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).scalars().all()

    for request in rows:
        request.status = BottleReturnStatus.DISPUTED.value
        request.resolution_note = (
            "The customer confirmed handing bottles over and no rider confirmed "
            "collecting them. Somebody needs to check what happened; no money "
            "has moved."
        )
        await _tell_customer(
            session, request.customer_id,
            title="We are checking your collection",
            message=(
                "You confirmed handing your bottles over but the rider has not "
                "confirmed collecting them. Your deposit is safe and somebody "
                "is looking into it."
            ),
        )
    if rows:
        await session.commit()

    return {"escalated": len(rows)}


async def expire_stale_requests(session: AsyncSession) -> dict:
    """Close requests nobody ever acted on. Nothing moves.

    The customer keeps their bottles and their deposit — an expiry is the
    platform admitting it did not turn up, not a forfeiture.
    """
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(BottleReturnRequest)
            .where(
                and_(
                    BottleReturnRequest.status.in_([
                        BottleReturnStatus.REQUESTED.value,
                        BottleReturnStatus.ASSIGNED.value,
                    ]),
                    BottleReturnRequest.expires_at != None,  # noqa: E711
                    BottleReturnRequest.expires_at < now,
                )
            )
            .with_for_update(skip_locked=True)
            .limit(500)
        )
    ).scalars().all()

    for request in rows:
        request.status = BottleReturnStatus.EXPIRED.value
        request.resolution_note = (
            "Nobody collected these in time. You still have the bottles and the "
            "deposit — book another collection whenever suits you."
        )
        await _tell_customer(
            session, request.customer_id,
            title="Nobody collected your bottles",
            message=(
                "We did not get to your bottle collection in time. You still "
                "have the bottles and the deposit — book another whenever suits."
            ),
        )
    if rows:
        await session.commit()

    return {"expired": len(rows)}


# ── What the platform owes, and how old it is ─────────────────────────────

#: Days since the deposit last moved. The last bucket is the one that matters:
#: a deposit nobody has touched in a year is a bottle that is not coming back
#: and a liability that will never be called, and the platform should know the
#: size of both before it decides what to do about either.
AGEING_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("0-30 days", 30),
    ("31-90 days", 90),
    ("91-180 days", 180),
    ("181-365 days", 365),
    ("over a year", None),
)


async def liability_summary(session: AsyncSession) -> dict:
    """Total deposit liability, aged.

    One figure is not enough to act on. "KSH 400,000 outstanding" says nothing
    about whether the platform is running a healthy circulating pool or has
    quietly sold four hundred bottles at cost.
    """
    now = datetime.now(timezone.utc)

    total_money, total_bottles, accounts = (
        await session.execute(
            select(
                func.coalesce(func.sum(User.bottle_deposit_balance), 0),
                func.coalesce(func.sum(User.bottles_held), 0),
                func.count(User.id),
            ).where(User.bottle_deposit_balance > 0)
        )
    ).one()

    buckets = []
    lower = 0
    for label, upper in AGEING_BUCKETS:
        conditions = [User.bottle_deposit_balance > 0]
        floor = now - timedelta(days=upper) if upper is not None else None
        ceiling = now - timedelta(days=lower)

        # A null `deposit_last_activity_at` is treated as the oldest bucket: it
        # means nothing has stamped this account since the column existed, which
        # is the definition of untouched.
        if floor is not None:
            conditions.append(User.deposit_last_activity_at > floor)
            conditions.append(User.deposit_last_activity_at <= ceiling)
        else:
            conditions.append(
                (User.deposit_last_activity_at <= ceiling)
                | (User.deposit_last_activity_at == None)  # noqa: E711
            )

        money, bottles, count = (
            await session.execute(
                select(
                    func.coalesce(func.sum(User.bottle_deposit_balance), 0),
                    func.coalesce(func.sum(User.bottles_held), 0),
                    func.count(User.id),
                ).where(and_(*conditions))
            )
        ).one()

        buckets.append({
            "label": label,
            "amount": str(_money(money)),
            "bottles": int(bottles or 0),
            "accounts": int(count or 0),
        })
        lower = upper or lower

    return {
        "total_liability": str(_money(total_money)),
        "total_bottles": int(total_bottles or 0),
        "accounts_holding": int(accounts or 0),
        "buckets": buckets,
    }
