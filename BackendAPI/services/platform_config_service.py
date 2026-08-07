"""The business model, as data.

Every number the platform earns from used to be a Python constant. Changing the
retail service fee meant editing `order_service.py`, opening a pull request and
waiting for a deploy — so in practice nobody changed anything, and the pricing
was whatever a developer typed once.

## How a change reaches the three apps

It already does. The customer app renders `POST /api/cart/quote` **verbatim** —
`pricing_service.compute_order_quote` is the single source of truth for what an
order costs, and it reads this module. So a fee changed here is live on the next
quote, in every app, with no client release and no App Store review.

The vendor and rider apps see it through the same route: their earnings come
from the order's stored splits, which are computed by the same quote.

## Why it cannot rewrite history

`calculate_revenue_splits` runs at **quote time** and its output is written to
the order's `vendor_commission`, `service_fee`, `rider_commission`,
`platform_total`, `vendor_net` and `rider_net` columns. `settlement_service`
pays out from those columns, never by recomputing. Raising a commission today
therefore cannot change what is owed on an order placed yesterday.

That property is what makes this safe to hand to an administrator, and it is
worth not breaking: if settlement ever starts recomputing from live config,
every in-flight order silently reprices mid-delivery.

## Reads are synchronous, refreshes are not

The pricing functions (`calculate_revenue_splits`, `service_fee_for`,
`is_surge_active`, `DispatchPolicy.get_delivery_fee`) are pure and synchronous,
and are called from routes, from the seeder and from tests. Threading an
`await` through all of them to fetch a rate would be a large change for no gain.

So: `ensure_fresh(session)` is awaited once at the top of a request that is
about to price something, and `get(...)` is a synchronous dictionary read
afterwards. Between those two points the configuration cannot change, which is
also what makes a single quote internally consistent.

Propagation across processes (the API and the ARQ worker are separate) rides on
a Redis version counter: a write bumps it, and the next `ensure_fresh` anywhere
sees the new number and reloads. With Redis down it degrades to a TTL, so the
worst case is `CACHE_TTL_SECONDS` of staleness rather than an unbounded one.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import get_redis
from models.platform_setting_model import PlatformSetting, PlatformSettingHistory

logger = logging.getLogger(__name__)

#: How long a loaded snapshot is trusted without re-checking. Only reached when
#: Redis is unavailable — normally the version counter invalidates sooner.
CACHE_TTL_SECONDS = 30

#: Bumped on every write; read on every `ensure_fresh`.
VERSION_KEY = "drop:platform_config:version"


# ── The registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SettingSpec:
    """One configurable value, and the rules for changing it.

    `minimum`/`maximum` are not decoration. This is a screen where a typo moves
    real money: entering `50` in a field that wants `0.05` would set a 5000%
    commission, and the first anyone would know is a vendor being paid a
    negative amount. The bounds make that a refusal with a sentence rather than
    a support incident.
    """

    key: str
    group: str
    label: str
    help: str
    #: rate | money | int | bool | windows | deposits
    kind: str
    default: Any
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    #: Shown beside the input, e.g. "KSH" or "% of product price".
    unit: str = ""


def _rate(key, group, label, help, default, maximum=1.0, unit="fraction of 1.0"):
    return SettingSpec(key, group, label, help, "rate", default, 0.0, maximum, unit)


def _money(key, group, label, help, default, maximum=100_000.0):
    return SettingSpec(key, group, label, help, "money", default, 0.0, maximum, "KSH")


SPECS: tuple[SettingSpec, ...] = (
    # ── Commission ────────────────────────────────────────────────────────
    _rate("retail_vendor_commission_rate", "commission",
          "Retail vendor commission",
          "Taken from the product price on every retail refill order.", 0.05),
    _rate("wholesale_vendor_commission_rate", "commission",
          "Wholesale vendor commission",
          "Lower than retail because the basket is far larger.", 0.025),
    _rate("gig_rider_commission_rate", "commission",
          "Gig rider commission",
          "Taken from the delivery fee. The rider keeps the rest.", 0.10),
    _rate("gig_platinum_rider_commission_rate", "commission",
          "Platinum rider commission",
          "The reward for a high-performing rider — must be below the standard rate.", 0.07),
    _rate("keep_my_bottle_commission_premium", "commission",
          "Keep-my-bottle premium",
          "Added to the rider commission rate on keep-my-bottle orders, which "
          "involve more bottle handling.", 0.02, maximum=0.5),
    _rate("in_house_rider_commission_rate", "commission",
          "In-house rider commission",
          "Zero by default: the vendor owns the fleet and the platform did not "
          "dispatch anyone.", 0.0),
    _rate("wholesale_delivery_markup_rate", "commission",
          "Wholesale delivery markup",
          "Platform surcharge on the wholesale delivery fee.", 0.05),

    # ── Fees the customer sees ────────────────────────────────────────────
    _money("retail_service_fee", "fees", "Retail service fee",
           "Flat, per retail order.", 12.0, maximum=1_000.0),
    _money("wholesale_service_fee", "fees", "Wholesale service fee",
           "Flat, per wholesale order.", 50.0, maximum=10_000.0),
    _money("surge_fee", "fees", "Surge fee",
           "Added during peak hours. Set to 0 to switch surge off entirely.",
           10.0, maximum=1_000.0),
    SettingSpec("peak_hours", "fees", "Peak hours",
                "Windows, in 24-hour East Africa Time, when the surge fee applies. "
                "An empty list disables surge.",
                "windows", [[6, 8], [17, 19]]),
    _money("payload_surcharge_per_unit", "fees", "Payload surcharge per bottle",
           "Charged per bottle beyond the free allowance, and paid to the rider.",
           10.0, maximum=1_000.0),
    SettingSpec("payload_free_units", "fees", "Free bottles before surcharge",
                "Bottles carried at no extra charge.", "int", 2, 0, 100),
    _money("staircase_surcharge_per_floor", "fees", "Staircase surcharge per floor",
           "Charged per floor beyond the free allowance, and paid to the rider.",
           10.0, maximum=1_000.0),
    SettingSpec("staircase_free_floors", "fees", "Free floors before surcharge",
                "Floors climbed at no extra charge.", "int", 2, 0, 50),
    _money("min_chargeable_total", "fees", "Minimum chargeable total",
           "Discounts never take an order below this. Safaricom rejects an STK "
           "push for zero, so this cannot be 0.", 1.0, maximum=1_000.0),
    _money("loyalty_cashback_per_delivery", "fees", "Loyalty cashback",
           "Credited to the customer's wallet on every completed delivery, out of "
           "platform margin. Set to 0 to switch it off.", 10.0, maximum=1_000.0),
    _money("late_cancellation_penalty", "fees", "Late cancellation penalty",
           "Charged when a customer cancels an order the vendor had already "
           "accepted and is likely preparing. Added to their balance and collected "
           "on their next order. Set to 0 to switch it off.", 50.0, maximum=10_000.0),

    # ── Delivery pricing ──────────────────────────────────────────────────
    _money("retail_delivery_base_fee", "delivery", "Retail delivery base fee",
           "The flat part of every retail delivery fee.", 50.0, maximum=10_000.0),
    _money("retail_delivery_per_km", "delivery", "Retail delivery per km",
           "Added per kilometre on a standard retail delivery.", 15.0, maximum=1_000.0),
    _money("keep_my_bottle_base_premium", "delivery", "Keep-my-bottle base premium",
           "Added to the base fee on keep-my-bottle deliveries.", 20.0, maximum=1_000.0),
    _money("keep_my_bottle_per_km", "delivery", "Keep-my-bottle per km",
           "Replaces the standard per-km rate on keep-my-bottle deliveries.",
           25.0, maximum=1_000.0),
    _money("wholesale_motorbike_base", "delivery", "Wholesale motorbike base", "", 50.0),
    _money("wholesale_motorbike_per_km", "delivery", "Wholesale motorbike per km", "", 60.0),
    _money("wholesale_tuktuk_base", "delivery", "Wholesale tuk-tuk base", "", 150.0),
    _money("wholesale_tuktuk_per_km", "delivery", "Wholesale tuk-tuk per km", "", 100.0),
    _money("wholesale_truck_base", "delivery", "Wholesale truck base", "", 500.0),
    _money("wholesale_truck_per_km", "delivery", "Wholesale truck per km", "", 150.0),

    # ── Bottles and acquisition ───────────────────────────────────────────
    SettingSpec("bottle_deposit_by_capacity", "bottles", "Bottle deposit",
                "Refundable deposit per bottle, by capacity in litres. This is the "
                "platform's largest single line item on a first order.",
                "deposits", {"20": 300.0, "10": 150.0}),
    _rate("welcome_discount_rate", "bottles", "Welcome discount",
          "Taken off the bottle deposit on a customer's first order. The platform "
          "absorbs it as an acquisition cost — it is not charged to the vendor.",
          0.30),

    # ── Operating limits ──────────────────────────────────────────────────
    SettingSpec("retail_max_distance_km", "limits", "Retail delivery radius",
                "A retail order beyond this is refused at checkout.",
                "int", 2, 1, 50, "km"),
    SettingSpec("wholesale_max_distance_km", "limits", "Wholesale delivery radius",
                "Also the radius searched for wholesale riders.",
                "int", 15, 1, 200, "km"),
    SettingSpec("wholesale_moq_kg", "limits", "Wholesale minimum order",
                "Wholesale orders below this weight are refused.",
                "int", 100, 1, 10_000, "kg"),
    _money("max_customer_debt_before_block", "limits", "Debt ceiling",
           "A customer owing less than this settles it automatically on their next "
           "order, as a visible line item. Only a debt at or above this figure "
           "blocks them from ordering at all.", 500.0, maximum=100_000.0),

    # ── Withdrawals ───────────────────────────────────────────────────────
    # One schedule, read by both withdrawal paths. These were four sets of
    # hardcoded literals in two modules that disagreed with each other, so the
    # same withdrawal cost a different amount depending on which endpoint the
    # app happened to call.
    _money("payout_min_rider", "payouts", "Rider minimum withdrawal",
           "A rider cannot withdraw less than this.", 250.0, maximum=100_000.0),
    _money("payout_min_retail_vendor", "payouts", "Retail vendor minimum withdrawal",
           "", 500.0, maximum=100_000.0),
    _money("payout_min_wholesale_vendor", "payouts", "Wholesale vendor minimum withdrawal",
           "Higher than retail because the balances are larger and each "
           "disbursement costs the platform an M-Pesa B2C tariff.", 1_000.0, maximum=1_000_000.0),
    _money("payout_transaction_fee", "payouts", "Withdrawal fee",
           "Deducted from the amount withdrawn, so the platform does not lose "
           "margin on the M-Pesa B2C tariff.", 15.0, maximum=1_000.0),
    _money("payout_fee_waiver_rider", "payouts", "Rider fee waiver threshold",
           "A rider withdrawing at least this much pays no fee.", 1_000.0, maximum=1_000_000.0),
    _money("payout_fee_waiver_retail_vendor", "payouts", "Retail vendor fee waiver threshold",
           "", 2_500.0, maximum=1_000_000.0),
    _money("payout_fee_waiver_wholesale_vendor", "payouts", "Wholesale vendor fee waiver threshold",
           "", 5_000.0, maximum=1_000_000.0),
    _money("min_wallet_topup", "payouts", "Minimum top-up",
           "The smallest amount an STK push may be raised for.", 10.0, maximum=10_000.0),

    # ── Workflow switches ─────────────────────────────────────────────────
    SettingSpec("require_vendor_verification", "workflow",
                "Only verified stores are discoverable",
                "When on, a store must be verified before it appears in search, the "
                "directory or 'near you'. Verify the existing stores FIRST — turning "
                "this on with none verified empties the customer app.",
                "bool", False),
    SettingSpec("rider_kyc_sla_hours", "workflow", "Rider verification target",
                "A rider waiting longer than this is flagged as overdue. They cannot "
                "accept any delivery until reviewed, so this is a supply metric.",
                "int", 24, 1, 720, "hours"),
    SettingSpec("order_stale_after_minutes", "workflow", "Order stale after",
                "An accepted, undispatched order older than this is surfaced as stuck "
                "on the console's order board. Surfacing only — nothing is cancelled.",
                "int", 45, 5, 1440, "minutes"),
    SettingSpec("order_auto_cancel_minutes", "workflow", "Auto-cancel unclaimed after",
                "An order nobody has claimed by this age is cancelled outright, its "
                "stock returned and a paid order flagged for refund. Must be below "
                "the stale threshold, which only surfaces a warning.",
                "int", 15, 5, 1440, "minutes"),
)

SPEC_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SPECS}
DEFAULTS: dict[str, Any] = {spec.key: spec.default for spec in SPECS}

GROUP_LABELS = {
    "commission": "Commission",
    "fees": "Customer fees",
    "delivery": "Delivery pricing",
    "bottles": "Bottles and acquisition",
    "limits": "Operating limits",
    "payouts": "Withdrawals",
    "workflow": "Workflow",
}


# ── Validation ────────────────────────────────────────────────────────────


def _as_float(value: Any, label: str) -> float:
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")


def validate_one(key: str, value: Any) -> Any:
    """Coerce and bounds-check a single value, or raise with a readable reason."""
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise ValueError(f"{key} is not a platform setting.")

    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{spec.label} must be true or false.")
        return value

    if spec.kind == "windows":
        if not isinstance(value, list):
            raise ValueError(f"{spec.label} must be a list of [start, end] hours.")
        cleaned = []
        for window in value:
            if not isinstance(window, (list, tuple)) or len(window) != 2:
                raise ValueError(f"{spec.label}: each window must be [start hour, end hour].")
            start, end = int(window[0]), int(window[1])
            if not (0 <= start <= 23 and 0 <= end <= 24):
                raise ValueError(f"{spec.label}: hours must be between 0 and 24.")
            if start >= end:
                raise ValueError(
                    f"{spec.label}: {start}:00–{end}:00 never elapses. A window that "
                    "wraps midnight must be entered as two windows."
                )
            cleaned.append([start, end])
        return cleaned

    if spec.kind == "deposits":
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{spec.label} must map a bottle capacity to a deposit.")
        cleaned = {}
        for capacity, amount in value.items():
            try:
                litres = int(capacity)
            except (TypeError, ValueError):
                raise ValueError(f"{spec.label}: '{capacity}' is not a bottle capacity in litres.")
            if litres <= 0:
                raise ValueError(f"{spec.label}: capacity must be positive.")
            deposit = _as_float(amount, f"{spec.label} for {litres}L")
            if deposit < 0:
                raise ValueError(f"{spec.label}: a deposit cannot be negative.")
            if deposit > 100_000:
                raise ValueError(f"{spec.label}: {deposit} looks like a typo.")
            cleaned[str(litres)] = deposit
        return cleaned

    if spec.kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{spec.label} must be a whole number.")
    else:
        number = _as_float(value, spec.label)

    if spec.minimum is not None and number < spec.minimum:
        raise ValueError(f"{spec.label} cannot be below {spec.minimum:g}.")
    if spec.maximum is not None and number > spec.maximum:
        raise ValueError(
            f"{spec.label} cannot exceed {spec.maximum:g}"
            + (
                " — rates are a fraction of 1.0, so 5% is 0.05, not 5."
                if spec.kind == "rate" and spec.maximum == 1.0
                else "."
            )
        )
    return number


def validate_all(proposed: dict[str, Any]) -> dict[str, Any]:
    """Validate a whole proposed configuration, including the relationships.

    Single-field bounds cannot express "the reward for being a platinum rider
    must actually be a reward", and a configuration where it is not would quietly
    pay the platform's best riders *less*. So the cross-field rules live here,
    and run against the merged result rather than the submitted subset — a change
    to one field can break an invariant with a field that was not submitted.
    """
    cleaned = {key: validate_one(key, value) for key, value in proposed.items()}
    merged = {**DEFAULTS, **_cache.snapshot(), **cleaned}

    if merged["gig_platinum_rider_commission_rate"] > merged["gig_rider_commission_rate"]:
        raise ValueError(
            "Platinum riders would pay more commission than standard riders. "
            "The platinum rate must be the lower of the two."
        )

    if merged["min_chargeable_total"] <= 0:
        raise ValueError(
            "The minimum chargeable total must be at least 1 — Safaricom rejects an "
            "STK push for zero, so an order discounted to nothing cannot be paid for."
        )

    if merged["retail_max_distance_km"] > merged["wholesale_max_distance_km"]:
        raise ValueError(
            "The retail radius cannot exceed the wholesale one; the rider search "
            "radius is derived from the wholesale figure."
        )

    total_take = (
        merged["retail_vendor_commission_rate"]
        + merged["gig_rider_commission_rate"]
        + merged["keep_my_bottle_commission_premium"]
    )
    if total_take >= 1.0:
        raise ValueError(
            "Vendor and rider commission together would take the entire order value. "
            "Nothing would be left to pay either of them."
        )

    if merged["order_auto_cancel_minutes"] >= merged["order_stale_after_minutes"]:
        raise ValueError(
            "Orders would be cancelled before they were ever flagged as stuck. "
            "The auto-cancel age must be below the stale threshold, or the console "
            "never surfaces an order in time for anyone to rescue it."
        )

    # A withdrawal that cannot cover its own fee is a request the API can only
    # refuse, so a configuration that guarantees one is a configuration error.
    for minimum_key, label in (
        ("payout_min_rider", "rider"),
        ("payout_min_retail_vendor", "retail vendor"),
        ("payout_min_wholesale_vendor", "wholesale vendor"),
    ):
        if merged[minimum_key] <= merged["payout_transaction_fee"]:
            raise ValueError(
                f"The {label} minimum withdrawal is not above the withdrawal fee. "
                "Every withdrawal at the minimum would be refused for not covering "
                "its own cost."
            )

    for waiver_key, minimum_key, label in (
        ("payout_fee_waiver_rider", "payout_min_rider", "rider"),
        ("payout_fee_waiver_retail_vendor", "payout_min_retail_vendor", "retail vendor"),
        ("payout_fee_waiver_wholesale_vendor", "payout_min_wholesale_vendor", "wholesale vendor"),
    ):
        if merged[waiver_key] < merged[minimum_key]:
            raise ValueError(
                f"The {label} fee waiver threshold is below their minimum withdrawal, "
                "so the fee would never be charged at all. Raise the threshold or "
                "set the fee to zero deliberately."
            )

    return cleaned


# ── The cache ─────────────────────────────────────────────────────────────


@dataclass
class _Cache:
    values: dict[str, Any] = field(default_factory=dict)
    #: The highest `version` in the table — what an order's pricing snapshot
    #: records, so a disputed total can be traced to the exact configuration.
    version: int = 0
    #: The Redis change counter this snapshot was loaded at. A plain monotonic
    #: counter rather than the DB version, so it never has to be kept in step
    #: with anything: different means reload, and that is the whole protocol.
    stamp: Optional[int] = None
    loaded_at: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        return dict(self.values)


_cache = _Cache()


async def _load(session: AsyncSession) -> None:
    rows = (await session.execute(select(PlatformSetting))).scalars().all()
    values: dict[str, Any] = {}
    highest = 0
    for row in rows:
        # A key that has been retired from `SPECS` is ignored rather than
        # deleted: rolling back the application must not lose the value.
        if row.key in SPEC_BY_KEY:
            values[row.key] = row.value
        highest = max(highest, int(row.version or 1))

    _cache.values = values
    _cache.version = highest
    _cache.loaded_at = time.monotonic()


async def ensure_fresh(session: AsyncSession) -> None:
    """Load the configuration if this process's copy might be stale.

    Called at the top of anything about to price an order. Cheap: one Redis GET
    in the common case, and a single-table SELECT only when something changed.
    """
    redis = get_redis()
    stamp: Optional[int] = None

    if redis is not None:
        try:
            raw = await redis.get(VERSION_KEY)
            stamp = int(raw) if raw is not None else None
            if stamp is not None and _cache.loaded_at and stamp == _cache.stamp:
                return
        except Exception as exc:  # Redis down, or a non-integer stamp
            logger.warning("Platform config version check failed, using TTL: %s", exc)
            stamp = None

    # Either the counter moved, or there is no counter to consult. The TTL is
    # the floor in both cases: without it a cold Redis would mean a SELECT on
    # every quote.
    if _cache.loaded_at and time.monotonic() - _cache.loaded_at < CACHE_TTL_SECONDS:
        if stamp is None or stamp == _cache.stamp:
            return

    try:
        await _load(session)
        _cache.stamp = stamp
    except Exception:
        # Pricing must not fail because the settings table is unreachable. The
        # defaults are the values the platform shipped with, so falling back to
        # them is the conservative outcome — but it must be loud.
        logger.exception("Could not load platform settings; using defaults")
        _cache.loaded_at = time.monotonic()


def get(key: str) -> Any:
    """Synchronous read. Falls back to the shipped default for a missing key."""
    if key not in SPEC_BY_KEY:
        raise KeyError(f"{key} is not a platform setting.")
    return _cache.values.get(key, DEFAULTS[key])


def get_decimal(key: str) -> Decimal:
    """Money and rates, as `Decimal`. Never as float — see the platform's rules."""
    return Decimal(str(get(key)))


def get_int(key: str) -> int:
    return int(get(key))


def get_bool(key: str) -> bool:
    return bool(get(key))


def current_version() -> int:
    return _cache.version


def effective() -> dict[str, Any]:
    """The whole configuration as it currently applies."""
    return {**DEFAULTS, **_cache.values}


def describe() -> list[dict[str, Any]]:
    """The registry plus current values, for the settings screen."""
    values = effective()
    return [
        {
            "key": spec.key,
            "group": spec.group,
            "group_label": GROUP_LABELS.get(spec.group, spec.group),
            "label": spec.label,
            "help": spec.help,
            "kind": spec.kind,
            "unit": spec.unit,
            "value": values[spec.key],
            "default": spec.default,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "is_default": values[spec.key] == spec.default,
        }
        for spec in SPECS
    ]


# ── Writing ───────────────────────────────────────────────────────────────


async def apply_changes(
    session: AsyncSession,
    *,
    changes: dict[str, Any],
    admin_email: str,
    reason: str,
) -> dict[str, Any]:
    """Validate and persist a set of changes. Does **not** commit.

    Returns the before/after for each key that actually moved, so the caller can
    write one audit row describing the whole edit rather than one per field.

    Values identical to the current one are dropped: an administrator opening
    the screen, changing one number and saving should not produce thirty history
    rows claiming everything changed.
    """
    await ensure_fresh(session)
    cleaned = validate_all(changes)

    current = effective()
    moved = {key: value for key, value in cleaned.items() if value != current.get(key)}
    if not moved:
        return {}

    next_version = _cache.version + 1
    diff: dict[str, Any] = {}

    for key, value in moved.items():
        before = current.get(key)
        row = await session.get(PlatformSetting, key)
        if row is None:
            row = PlatformSetting(key=key, value=value, version=next_version)
            session.add(row)
        else:
            row.value = value
            row.version = next_version
        row.updated_by_email = admin_email

        session.add(
            PlatformSettingHistory(
                key=key,
                before=before,
                after=value,
                version=next_version,
                reason=reason,
                changed_by_email=admin_email,
            )
        )
        diff[key] = {"before": before, "after": value}

    return diff


async def invalidate() -> None:
    """Tell every process to reload. Call **after** the commit.

    Before the commit and the transaction could still roll back, leaving other
    workers with a version stamp for a change that never happened — and the DB
    read that follows would quietly restore the old value while the stamp says
    otherwise.
    """
    _cache.loaded_at = 0.0
    _cache.stamp = None

    redis = get_redis()
    if redis is None:
        return
    try:
        # INCR, not SET: monotonic, atomic, and it needs to know nothing about
        # what any process currently believes the version to be.
        await redis.incr(VERSION_KEY)
    except Exception as exc:
        logger.warning("Could not publish platform config version: %s", exc)


# ── Previewing a change before it is real ─────────────────────────────────


@contextmanager
def temporarily(values: dict[str, Any]):
    """Run a block against a different configuration, then put it back.

    Used only by the preview endpoint. It exists so the preview goes through the
    **same** `calculate_revenue_splits` and `DispatchPolicy.get_delivery_fee`
    that a real quote does, rather than a second implementation of the
    arithmetic that would be free to disagree with the first — which is exactly
    the class of bug `pricing_service` was created to end.

    Not for general use, and not safe to hold across an `await`: the cache is
    process-wide, so anything else priced inside the block would be priced
    against the proposal. The preview is pure and synchronous, so it cannot.
    """
    previous = _cache.values
    previous_loaded_at = _cache.loaded_at
    _cache.values = dict(values)
    try:
        yield
    finally:
        _cache.values = previous
        _cache.loaded_at = previous_loaded_at


def price_sample(
    *,
    product_total: float,
    distance_km: float,
    quantity: int,
    bottle_capacity: int,
    vendor_type: str = "retail_refill",
    delivery_type: str = "quick_swap",
    floor_level: int = 0,
    first_order: bool = False,
    surge: bool = False,
) -> dict[str, Any]:
    """Price one representative order against whatever is currently loaded.

    Deliberately not a re-implementation: the delivery fee comes from
    `DispatchPolicy`, the splits from `calculate_revenue_splits`, and the
    surcharge schedule is read from this module — the same three sources a real
    quote uses. What it does *not* model is the wallet balance and the vendor's
    negotiated wholesale rate, both of which are per-account rather than
    per-configuration and would make the comparison meaningless.
    """
    from decimal import ROUND_HALF_UP

    from services.dispatch_policy import DispatchPolicy
    from services.order_service import calculate_revenue_splits

    cents = Decimal("0.01")

    def money(value: Decimal) -> Decimal:
        return value.quantize(cents, rounding=ROUND_HALF_UP)

    vehicle_class = DispatchPolicy.get_vehicle_class(quantity)
    delivery_fee = money(
        Decimal(
            str(
                DispatchPolicy.get_delivery_fee(
                    distance_km, vendor_type, vehicle_class, 0.0, 0.0, delivery_type
                )
            )
        )
    )

    products = money(Decimal(str(product_total)))

    schedule = get("bottle_deposit_by_capacity") or {}
    per_bottle = schedule.get(str(int(bottle_capacity)))
    bottle_deposit = money(Decimal(str(per_bottle)) * quantity) if per_bottle else Decimal("0.00")

    welcome_discount = (
        money(bottle_deposit * get_decimal("welcome_discount_rate")) if first_order else Decimal("0.00")
    )

    free_units = get_int("payload_free_units")
    payload_surcharge = (
        money(Decimal(quantity - free_units) * get_decimal("payload_surcharge_per_unit"))
        if quantity > free_units
        else Decimal("0.00")
    )

    free_floors = get_int("staircase_free_floors")
    staircase_surcharge = (
        money(Decimal(floor_level - free_floors) * get_decimal("staircase_surcharge_per_floor"))
        if floor_level > free_floors
        else Decimal("0.00")
    )

    service_fee = get_decimal(
        "wholesale_service_fee" if vendor_type == "wholesale_b2b" else "retail_service_fee"
    )
    surge_fee = get_decimal("surge_fee") if surge else Decimal("0.00")
    delivery_markup = (
        money(delivery_fee * get_decimal("wholesale_delivery_markup_rate"))
        if vendor_type == "wholesale_b2b"
        else Decimal("0.00")
    )

    splits = calculate_revenue_splits(
        product_total=float(products),
        delivery_fee=float(delivery_fee),
        vendor_type=vendor_type,
        bottle_deposit=float(bottle_deposit),
        rider_surcharges=float(payload_surcharge + staircase_surcharge),
        delivery_type=delivery_type,
        welcome_discount=float(welcome_discount),
    )

    # `calculate_revenue_splits` re-derives the surge fee from the clock, which
    # is right for a live quote and wrong for a hypothetical one. The caller
    # says whether to model surge, so that figure is substituted here rather
    # than depending on what time the preview happened to be requested.
    platform_total = money(
        Decimal(str(splits["vendor_commission"]))
        + Decimal(str(splits["service_fee"]))
        + Decimal(str(splits["rider_commission"]))
        + delivery_markup
        + surge_fee
        - welcome_discount
    )

    customer_total = (
        products
        + delivery_fee
        + service_fee
        + surge_fee
        + delivery_markup
        + payload_surcharge
        + staircase_surcharge
        + bottle_deposit
        - welcome_discount
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    customer_total = max(customer_total, min_chargeable_total_value())

    return {
        "customer_total": str(customer_total),
        "product_total": str(products),
        "delivery_fee": str(delivery_fee),
        "service_fee": str(money(service_fee)),
        "surge_fee": str(money(surge_fee)),
        "delivery_markup": str(delivery_markup),
        "payload_surcharge": str(payload_surcharge),
        "staircase_surcharge": str(staircase_surcharge),
        "bottle_deposit": str(bottle_deposit),
        "welcome_discount": str(welcome_discount),
        "platform_revenue": str(platform_total),
        "vendor_receives": str(money(Decimal(str(splits["vendor_net"])))),
        "rider_receives": str(money(Decimal(str(splits["rider_net"])))),
        "vehicle_class": vehicle_class,
    }


def min_chargeable_total_value() -> Decimal:
    """The floor an order total cannot go below. Named to avoid colliding with
    `pricing_service.min_chargeable_total`, which wraps the same figure."""
    return get_decimal("min_chargeable_total")
