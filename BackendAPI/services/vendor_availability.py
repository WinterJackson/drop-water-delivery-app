"""Whether a store is taking this order right now, and on what terms.

Three controls belong to whoever is standing in the shop — *are we open*, *what
is the smallest order worth preparing*, and *will we take cash today* — and the
platform had no way to hear any of them.

The worst of the three was not the missing ones. `is_online` existed, the
vendor app shipped a swipe control wired to it, and **nothing on the ordering
path ever read it**: a vendor could swipe their store closed, watch the toggle
turn grey, and keep receiving orders. `shift_start`/`shift_end` were in the
same position — on every store since the first migration, rendered on the
console, enforced nowhere. A control that reaches the user but not the platform
is worse than no control, because the person operating it believes it worked.

This module is the only thing that answers the question. Nothing else may
re-derive "is this store accepting", for the same reason `pricing_service` owns
the total and `cod_policy` owns the cash decision: the answer is rendered to a
customer on the store card, checked again at the quote, and checked a third
time under a row lock in `create_order`, and three implementations would
eventually disagree in front of somebody with a full basket.

## Why a pause expires

`is_online` is the indefinite switch, and an indefinite switch is the one people
forget. A vendor taps it during a rush; the rush ends; the store is dark until
somebody notices the next morning, having lost a day's orders to a control they
used correctly. A pause carries its own expiry and the store reopens whether or
not anyone remembers — `resume_expired_pauses` also tells them it happened.

The two are not redundant, and the distinction is visible on the console: a
paused store is a shop that is about to reopen, an offline store is one that
has stopped trading and should be asked why.

## Why the ceilings exist

Every control here is bounded by a `Platform_Settings` row. Self-service with no
bound is not self-service: a store that sets a KSH 50,000 minimum has delisted
itself while still appearing open and still ranking in search, and the customer
who taps through and fills a basket experiences the platform being broken rather
than the shop being shut.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.vendor_model import Vendor
from services import platform_config_service as _config

logger = logging.getLogger(__name__)

#: EAT, no DST. `shift_start`/`shift_end` are bare `Time` columns entered by a
#: shopkeeper in Nairobi; comparing them against a container's UTC clock would
#: shut every store three hours early.
EAT = timezone(timedelta(hours=3))

#: The pause durations the vendor app offers. Here rather than in the app so
#: the ceiling below can bind on them — an app offering a duration the server
#: refuses is a button that always fails.
PAUSE_PRESET_MINUTES = (15, 30, 60, 120, 240)


def _money(value) -> Decimal:
    """Strict. For a value somebody has just typed, where a bad one is a 400."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _stored_minimum(vendor) -> Decimal:
    """Lenient. For the column, where a bad one must not take checkout down.

    Fails to **no minimum**, which is both the column's default and the
    permissive direction. The alternative is a 500 at checkout over an optional
    courtesy a store set for itself — a store's preference is not worth a
    customer's order, and the value is logged rather than swallowed.
    """
    raw = getattr(vendor, "min_order_value", None)
    if raw is None:
        return Decimal("0")
    try:
        return _money(raw)
    except (ArithmeticError, TypeError, ValueError):
        logger.warning(
            "Store %s has an unreadable min_order_value (%r); treating it as no minimum.",
            getattr(vendor, "id", "?"), raw,
        )
        return Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pause_expiry(vendor) -> Optional[datetime]:
    """The running pause's end, as an aware instant, or `None`.

    Naive values are read as UTC: `TIMESTAMP(timezone=True)` gives an aware one
    back, but a fixture, a replica configured differently, or a value that has
    been through JSON will not, and comparing naive to aware raises rather than
    returning a wrong answer — a `TypeError` here would be a 500 on the
    customer's checkout, caused by a store having once tapped Pause.

    Fails to **no pause** for the same reason `_stored_minimum` fails to no
    minimum: a store's own convenience control must not be able to stop the
    platform selling.
    """
    raw = getattr(vendor, "paused_until", None)
    if not isinstance(raw, datetime):
        if raw is not None:
            logger.warning(
                "Store %s has an unreadable paused_until (%r); treating it as not paused.",
                getattr(vendor, "id", "?"), raw,
            )
        return None
    return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class StoreState:
    """Everything a caller needs to decide, explain, or render.

    `reason` is the customer's sentence and is produced *here*, once. Every
    surface renders it verbatim — the apps must never compose their own, because
    these rules move with settings rows and a store's own text, and a sentence
    assembled on a client is a sentence that goes stale silently.
    """

    accepting: bool
    #: open | paused | offline | closed_hours | suspended
    state: str
    reason: Optional[str]
    reopens_at: Optional[datetime]
    accepts_cash: bool
    cash_reason: Optional[str]
    min_order_value: Decimal

    def as_dict(self) -> dict:
        return {
            "accepting": self.accepting,
            "state": self.state,
            "reason": self.reason,
            "reopens_at": self.reopens_at.isoformat() if self.reopens_at else None,
            "accepts_cash": self.accepts_cash,
            "cash_reason": self.cash_reason,
            "min_order_value": str(self.min_order_value),
        }


def _hours_label(shift_start: Optional[time], shift_end: Optional[time]) -> str:
    if not shift_start or not shift_end:
        return ""
    return f"{shift_start.strftime('%H:%M')}–{shift_end.strftime('%H:%M')}"


def _within_hours(vendor, moment: datetime) -> bool:
    """Is `moment` inside the store's opening hours, in EAT?

    An overnight shift (22:00–06:00) is a real thing a water shop by a matatu
    stage does, and `start <= now < end` reads it as *closed all day*. The
    wrap-around case is a union, not a range.
    """
    start = getattr(vendor, "shift_start", None)
    end = getattr(vendor, "shift_end", None)
    if not isinstance(start, time) or not isinstance(end, time) or start == end:
        # Equal endpoints are how "always open" arrives from a form with two
        # untouched fields, and anything that is not a `time` is a store whose
        # hours were never set. Refusing everything would be the opposite
        # reading of both, and this gate closes shops — it must only ever act
        # on hours somebody actually entered.
        return True

    local = moment.astimezone(EAT).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end


async def store_state(session: AsyncSession, vendor, *, moment: Optional[datetime] = None) -> StoreState:
    """The single answer, with the configuration refreshed first.

    Use this from a route. `evaluate` is the same decision against the cached
    snapshot, for a caller that has already refreshed and is about to ask about
    twenty stores at once.
    """
    await _config.ensure_fresh(session)
    return evaluate(vendor, moment=moment)


def evaluate(vendor, *, moment: Optional[datetime] = None) -> StoreState:
    """The decision itself. Read it; never reconstruct it.

    Ordered by how permanent the reason is, so the customer is told the most
    useful thing rather than the first thing that matched: a suspended store is
    not "closed until 07:00".

    Synchronous, against the configuration snapshot this process already holds
    — the convention every pricing and search path already follows. A discovery
    query returning twenty stores evaluates twenty states and makes no further
    round trips.
    """
    now = moment or _now()

    min_order = _stored_minimum(vendor)
    accepts_cash = bool(getattr(vendor, "accepts_cash", True))
    cash_reason: Optional[str] = None
    if accepts_cash is False and not _config.get_bool("vendor_may_decline_cash"):
        # The platform has taken the decision back. Honouring a stored decline
        # after that would leave stores opted out of an offer the platform has
        # decided is not optional, with nothing on any screen explaining why.
        accepts_cash = True
    if not accepts_cash:
        cash_reason = (
            f"{getattr(vendor, 'business_name', 'This store')} is not taking cash "
            "orders at the moment. Pay by M-Pesa and the order goes through "
            "immediately."
        )

    def _state(accepting: bool, state: str, reason: Optional[str], reopens_at=None) -> StoreState:
        return StoreState(
            accepting=accepting,
            state=state,
            reason=reason,
            reopens_at=reopens_at,
            accepts_cash=accepts_cash,
            cash_reason=cash_reason,
            min_order_value=min_order,
        )

    # 1. Suspended by an administrator. Not the vendor's own state and not
    #    theirs to clear, so it outranks everything below it.
    if getattr(vendor, "is_active", True) is False:
        return _state(False, "suspended", "This store is not currently trading.")

    # 2. A pause, while it is still running. Checked against the clock rather
    #    than against a flag, so a worker that never ran cannot leave a store
    #    shut: the expiry is the truth and the sweep only tidies up after it.
    paused_until = _pause_expiry(vendor)
    if paused_until is not None and paused_until > now:
        note = (getattr(vendor, "pause_reason", None) or "").strip()
        local = paused_until.astimezone(EAT).strftime("%H:%M")
        reason = f"Paused until {local}."
        if note:
            reason = f"{reason} {note}"
        return _state(False, "paused", reason, reopens_at=paused_until)

    # 3. The indefinite switch.
    if getattr(vendor, "is_online", True) is False:
        return _state(False, "offline", "This store is closed right now.")

    # 4. Opening hours — off by default, because switching it on
    #    retrospectively closes every store whose hours were never real.
    if _config.get_bool("vendor_hours_enforced") and not _within_hours(vendor, now):
        label = _hours_label(getattr(vendor, "shift_start", None), getattr(vendor, "shift_end", None))
        reason = f"This store is closed right now. Opening hours are {label}." if label else "This store is closed right now."
        return _state(False, "closed_hours", reason)

    return _state(True, "open", None)


async def annotate(session: AsyncSession, vendors) -> None:
    """Stamp the state onto rows about to be serialised for a customer.

    A closed store must **appear** and be marked closed, not disappear. Filtering
    it out of discovery is the tempting version and it is wrong twice: the
    customer looking for the shop they always use concludes it has left the
    platform, and the store that paused for twenty minutes has lost its place in
    everyone's list rather than its next twenty minutes of orders.

    Written onto the instances rather than derived in the response schema so
    there is still exactly one implementation — a `@computed_field` reading the
    columns would be a second one, and the second one is the one that forgets
    `vendor_may_decline_cash`.
    """
    rows = [v for v in (vendors or []) if v is not None]
    if not rows:
        return

    await _config.ensure_fresh(session)
    now = _now()
    for vendor in rows:
        state = evaluate(vendor, moment=now)
        vendor.store_state = state.state
        vendor.store_reason = state.reason
        vendor.is_accepting_orders = state.accepting
        vendor.reopens_at = state.reopens_at


async def assert_store_accepting(session: AsyncSession, vendor) -> StoreState:
    """Checkout gate. 409 — the basket is fine, the shop is shut."""
    state = await store_state(session, vendor)
    if not state.accepting:
        raise HTTPException(status_code=409, detail=state.reason)
    return state


def assert_meets_minimum(vendor, subtotal) -> None:
    """Checkout gate, against the **goods** rather than the total.

    Measured on `product_subtotal` deliberately. A minimum that counted the
    delivery fee would move with the distance, so the same basket would clear
    the store's minimum from one address and fail from another — and it would
    let a customer meet a store's minimum by living further away, which is not
    a thing the store asked for.

    Synchronous and free of configuration, so it can live inside
    `pricing_service.validate_quote` — which is called at the quote, again
    before the STK push, and a third time under `create_order`'s row lock.
    Putting it there rather than beside the other two gates is what makes those
    three call sites free: one implementation, reached by every checkout path
    that already exists and every one that gets added.
    """
    minimum = _stored_minimum(vendor)
    if minimum <= 0:
        return

    goods = _money(subtotal)
    if goods >= minimum:
        return

    short = minimum - goods
    raise HTTPException(
        status_code=400,
        detail=(
            f"{getattr(vendor, 'business_name', 'This store')} has a KSH "
            f"{minimum:,.0f} minimum order. Add KSH {short:,.0f} more to check out."
        ),
    )


# ── The vendor's own writes ───────────────────────────────────────────────


async def set_controls(
    session: AsyncSession,
    vendor,
    *,
    accepts_cash: Optional[bool] = None,
    min_order_value=None,
    pause_minutes: Optional[int] = None,
    pause_reason: Optional[str] = None,
    resume: bool = False,
) -> StoreState:
    """The only writer. Validates against the platform's ceilings first.

    Every field is optional and only what is supplied moves, so the pause
    control and the minimum-order field can be separate screens without either
    silently clearing the other's value — the shape that made
    `preferred_payment_method` overwrite a vendor's payout account every time
    an unrelated screen saved.
    """
    await _config.ensure_fresh(session)

    if accepts_cash is not None:
        if accepts_cash is False and not _config.get_bool("vendor_may_decline_cash"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Cash orders are required on this platform at the moment, so "
                    "stores cannot switch them off. Contact support if you have "
                    "no float to carry them."
                ),
            )
        vendor.accepts_cash = bool(accepts_cash)

    if min_order_value is not None:
        requested = _money(min_order_value)
        if requested < 0:
            raise HTTPException(status_code=400, detail="A minimum order cannot be negative.")
        ceiling = _config.get_decimal("vendor_max_min_order_value")
        if requested > ceiling:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The highest minimum order a store may set is KSH {ceiling:,.0f}. "
                    "A minimum above that hides you from customers who could not "
                    "have met it, without showing you as closed."
                ),
            )
        vendor.min_order_value = requested

    if resume:
        vendor.paused_until = None
        vendor.pause_reason = None
    elif pause_minutes is not None:
        if pause_minutes <= 0:
            raise HTTPException(status_code=400, detail="A pause has to be longer than zero minutes.")
        max_minutes = _config.get_int("vendor_max_pause_hours") * 60
        if pause_minutes > max_minutes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The longest pause is {max_minutes // 60} hours. For longer than "
                    "that, switch the store offline instead — a pause is meant to "
                    "reopen you, and customers are told when it ends."
                ),
            )
        vendor.paused_until = _now() + timedelta(minutes=int(pause_minutes))
        vendor.pause_reason = (pause_reason or "").strip()[:140] or None

    await session.commit()
    await session.refresh(vendor)
    return await store_state(session, vendor)


# ── Telling the store ─────────────────────────────────────────────────────


async def _tell_store(session: AsyncSession, vendor, *, title: str, message: str) -> None:
    """Reach the owner **and** the staff, through the platform's own two paths.

    A store is not one handset. `Vendor.push_token` is the owner's; anyone
    working the counter is a `Vendor_Staff` row with a token of their own, and
    addressing only the first is how a message reaches whoever happens not to
    be in the shop. `queue_push` rather than a bare task, so a rollback
    discards the message along with the change it was announcing.
    """
    from services.notification_service import create_notification, queue_push
    from services.vendor_staff_service import push_tokens_for_store

    await create_notification(
        session=session,
        user_id=vendor.id,
        user_type="vendor",
        title=title,
        message=message,
        message_type="system_alert",
        action_url="/(screens)",
    )

    tokens = [getattr(vendor, "push_token", None)]
    try:
        tokens += await push_tokens_for_store(session, vendor.id)
    except Exception:  # pragma: no cover — a staff read must not lose the owner's push
        logger.exception("Could not read staff push tokens for store %s", vendor.id)

    for token in {t for t in tokens if t}:
        queue_push(session, to=token, title=title, body=message)


# ── The sweep ─────────────────────────────────────────────────────────────


async def resume_expired_pauses(session: AsyncSession) -> dict:
    """Clear pauses that have run out, and tell the vendor they are open again.

    The state is already correct without this — `store_state` compares the
    expiry against the clock, so a worker that never ran cannot leave a store
    shut. This exists for the two things the clock cannot do: clear the column
    so the console does not show a pause that ended yesterday, and **tell the
    vendor**. A shop that paused for twenty minutes and heard nothing has no
    way to know whether it worked, and the usual response to that is to pause
    again.
    """
    now = _now()
    rows = (
        await session.execute(
            select(Vendor)
            .where(Vendor.paused_until.isnot(None), Vendor.paused_until <= now)
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).scalars().all()

    resumed = 0
    for vendor in rows:
        try:
            vendor.paused_until = None
            vendor.pause_reason = None
            # Only worth saying when the store is actually back in business. A
            # vendor who paused and then went offline for the night should not
            # be told they are open.
            if getattr(vendor, "is_online", True) and getattr(vendor, "is_active", True):
                await _tell_store(
                    session,
                    vendor,
                    title="Your store is open again",
                    message="The pause has ended and customers can order from you.",
                )
            await session.commit()
            resumed += 1
        except Exception:
            await session.rollback()
            logger.exception("Could not resume paused store %s", vendor.id)

    return {"stores_resumed": resumed}
