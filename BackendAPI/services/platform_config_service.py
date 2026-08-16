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
from typing import Any, Optional

from sqlalchemy import func, select
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
    #: rate | money | int | decimal | bool | windows | deposits
    #:
    #: `int` coerces with `int(value)`, which **truncates** — so it is only for
    #: quantities that cannot be fractional (bottles, floors, days). Anything
    #: measurable in halves is `decimal`.
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


def _d(value) -> Decimal:
    """Any setting value as a Decimal, for the cross-field checks below.

    Settings arrive as floats from JSON and as Decimals from the coercer
    depending on the path, and these comparisons are about money.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


SPECS: tuple[SettingSpec, ...] = (
    # ── Commission ────────────────────────────────────────────────────────
    _rate("retail_vendor_commission_rate", "commission",
          "Retail vendor commission",
          "Taken from the product price on every retail refill order.", 0.05),
    _rate("wholesale_vendor_commission_rate", "commission",
          "Wholesale vendor commission",
          "Wholesale customers cost the platform least to serve — no rider to pay, no cash to police — and are the least price-sensitive. Charging them below retail rewarded the wrong side of the business.", 0.05),
    _rate("gig_rider_commission_rate", "commission",
          "Gig rider commission",
          "Taken from the delivery fee. The rider keeps the rest.", 0.10),
    _rate("gig_platinum_rider_commission_rate", "commission",
          "Platinum rider commission",
          "The reward for a high-performing rider — must be below the standard rate.", 0.07),
    _rate("refill_mine_commission_premium", "commission",
          "Refill-my-own-bottle premium",
          "Added to the rider commission rate on refill-my-own-bottle orders. "
          "That journey is a round trip — collect the customer's bottle, carry "
          "it to the station, bring it back — so it is more of the rider's time "
          "and more handling.", 0.02, maximum=0.5),
    _rate("in_house_rider_commission_rate", "commission",
          "In-house rider commission",
          "Zero by default: the vendor owns the fleet and the platform did not "
          "dispatch anyone.", 0.0),
    _rate("wholesale_delivery_markup_rate", "commission",
          "Wholesale delivery markup",
          "Platform surcharge on the wholesale delivery fee.", 0.05),

    # ── Fees the customer sees ────────────────────────────────────────────
    _money("retail_service_fee", "fees", "Retail service fee",
           "Flat, per retail order. At KSH 12 this did not cover the M-Pesa "
           "tariff on collecting the order, so the platform's own fee lost "
           "money on every prepaid basket. Customers accept a stated service "
           "fee far more readily than a higher price on the water itself — "
           "which is why every delivery app in this market prices it this way.",
           35.0, maximum=1_000.0),
    _money("wholesale_service_fee", "fees", "Wholesale service fee",
           "Flat, per wholesale order. Set against a basket measured in tens "
           "of thousands, not hundreds.", 120.0, maximum=10_000.0),
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
           "Credited to the customer's wallet on every completed delivery, out "
           "of platform margin. **Withdrawn — default 0.** At KSH 10 against a "
           "platform cut of KSH 37.50 it was returning a quarter of the "
           "platform's revenue on every order, unconditionally, to customers "
           "who were buying anyway. Paying on every order buys nothing; if it "
           "is ever switched back on it should be at a retention cliff, not on "
           "each delivery.", 0.0, maximum=1_000.0),
    _money("late_cancellation_penalty", "fees", "Late cancellation penalty",
           "Charged when a customer cancels an order the vendor had already "
           "accepted and is likely preparing. Added to their balance and collected "
           "on their next order. Set to 0 to switch it off.", 50.0, maximum=10_000.0),

    # ── Delivery pricing ──────────────────────────────────────────────────
    _money("retail_delivery_base_fee", "delivery", "Retail delivery base fee",
           "The flat part of a retail delivery beyond the short-hop distance. "
           "It was re-based from KSH 50: at 50 plus KSH 15/km the fee could not "
           "reach KSH 80 anywhere inside the service radius, and the rider's "
           "whole pay was capped with it — below what a boda charges for the "
           "same trip carrying nothing.",
           80.0, maximum=10_000.0),
    _money("retail_delivery_per_km", "delivery", "Retail delivery per km",
           "Added per kilometre beyond the short-hop distance.",
           20.0, maximum=1_000.0),
    _money("refill_mine_base_premium", "delivery", "Refill-my-own-bottle base premium",
           "Added to the base fee on keep-my-bottle deliveries.", 20.0, maximum=1_000.0),
    _money("refill_mine_per_km", "delivery", "Refill-my-own-bottle per km",
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
    # Both radii are `decimal`, not `int`. The retail figure is 2.5, and under
    # `int` the coercer's `int(value)` would have taken it to 2 silently — a
    # truncation, not a refusal, on the number that decides which stores a
    # customer can see at all. Wholesale is the same kind for the same reason,
    # even though it ships whole: they are one concept, edited on one screen,
    # and an asymmetry here is a trap for whoever next needs half a kilometre.
    SettingSpec("retail_max_distance_km", "limits", "Retail delivery radius",
                "A retail order beyond this is refused at checkout, and it is "
                "also how far a customer can see: discovery and checkout read "
                "the same figure.",
                "decimal", 2.5, 0.5, 50, "km"),
    SettingSpec("wholesale_max_distance_km", "limits", "Wholesale delivery radius",
                "Also the radius searched for wholesale riders.",
                "decimal", 15.0, 0.5, 200, "km"),
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
    _money("payout_transaction_fee", "payouts", "Withdrawal margin",
           "The platform's margin **on top of** what Safaricom charges to make "
           "the disbursement, not the fee itself. Zero by default: the provider "
           "pays exactly what the transfer costs, and the platform neither "
           "loses nor earns on it. Raise this only as a deliberate decision to "
           "make money on withdrawals. Safaricom's own tariff is always "
           "recovered in full and is not affected by this figure — see "
           "`settlement_service.B2C_TARIFF_BANDS`.", 0.0, maximum=1_000.0),
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
    # How long the top-up reconciliation keeps asking Safaricom about a wallet
    # top-up whose callback never arrived. Daraja stops resolving old
    # CheckoutRequestIDs, so past this the sweep escalates to a human instead of
    # querying an id that will never come back — the row is left `pending`,
    # because writing it off would assert something nobody knows.
    SettingSpec("topup_reconcile_max_age_hours", "workflow", "Top-up reconciliation window",
                "How long to keep asking M-Pesa about a wallet top-up whose "
                "confirmation never arrived. Past this the top-up is reported for "
                "somebody to check against the M-Pesa statement, because Safaricom "
                "no longer answers queries for it.",
                "int", 48, 1, 336, "hours"),
    # The *reward* for Platinum has been editable since the settings table
    # existed (`gig_platinum_rider_commission_rate`); the *requirement* was a
    # literal `>= 20` inside the nightly job, and the rider app stated it as a
    # literal `20` of its own. So the console could change what a rider earned
    # for qualifying and not what qualifying meant, and the two numbers could
    # drift apart with nothing to notice.
    SettingSpec("platinum_min_deliveries", "workflow", "Platinum: deliveries needed",
                "Completed deliveries a gig rider needs inside the window below to "
                "hold Platinum, which lowers their commission. Evaluated nightly; "
                "riders who fall short are demoted the same night.",
                "int", 20, 1, 500, "deliveries"),
    SettingSpec("platinum_window_days", "workflow", "Platinum: over how many days",
                "The trailing window the deliveries are counted over.",
                "int", 7, 1, 90, "days"),

    # ── Platform margin ───────────────────────────────────────────────────
    #
    # Retail had no equivalent of the wholesale delivery markup, so on the side
    # of the business with the rider to pay, the cash to police and the thinnest
    # basket, the platform's only margin was a KSH 12 service fee and 5% of a
    # KSH 175 bottle. The markup is *inside* the delivery fee and is never a
    # separate line — it is margin, not a charge (see `pricing_service`).
    _rate("retail_delivery_markup_rate", "commission",
          "Retail delivery markup",
          "**Default 0, deliberately.** A second platform cut from the retail "
          "delivery fee, on top of the rider commission. Two settings taking "
          "from one pot is how a KSH 50 short hop came to leave the rider "
          "KSH 37.50 when the stated rule was a single 10% commission. If the "
          "platform wants more from delivery, raise `gig_rider_commission_rate` "
          "— one number the rider can check against their own payout.",
          0.0),

    # ── Distance-tiered retail delivery ───────────────────────────────────
    #
    # A flat base plus per-km overcharges the next street and undercharges the
    # next estate. Below the short-hop threshold one flat fee applies; above it,
    # a higher base plus a higher per-km. The two must not invert — validated
    # below, because a short trip costing more than a long one is the kind of
    # thing a customer screenshots.
    SettingSpec("short_hop_threshold_m", "delivery", "Short-hop distance",
                "Deliveries at or under this distance are charged one flat fee "
                "instead of base-plus-per-km. Urban Kenya is dense: the next "
                "street should not be priced like the next suburb.",
                "int", 600, 0, 5_000, "metres"),
    _money("short_hop_delivery_fee", "delivery", "Short-hop flat fee",
           "The whole delivery fee for anything inside the short-hop distance.",
           50.0, maximum=5_000.0),

    # ── The cost of collecting money ──────────────────────────────────────
    #
    # Safaricom charges the business on both legs. Neither was modelled, so
    # every margin figure on the console overstated reality by the tariff —
    # on a KSH 442 order that is a material share of the platform's whole cut.
    _money("mpesa_collection_cost", "costs", "M-Pesa collection cost",
           "What Safaricom charges the business to receive one C2B payment. "
           "Deducted from platform revenue on every M-Pesa order so the "
           "console's margin figures are net, not gross. Set it from your "
           "current Daraja tariff sheet — it is a real cost either way; the "
           "only question is whether your dashboard admits it.",
           15.0, maximum=1_000.0),
    _money("cash_handling_cost", "costs", "Cash order handling cost",
           "The platform's own cost of a cash order — reconciliation, float "
           "risk and support. Deducted from platform revenue on cash orders so "
           "the two payment methods can be compared honestly.",
           5.0, maximum=1_000.0),

    # ── Steering customers to M-Pesa ──────────────────────────────────────
    #
    # A discount, not a cash surcharge. The two are arithmetically identical
    # and behave completely differently: a surcharge reads as a penalty for
    # paying the way most of the market pays, and costs goodwill the platform
    # cannot spare. Set to 0 to switch the steer off entirely.
    _money("mpesa_payment_discount", "fees", "Pay-by-M-Pesa discount",
           "Taken off the total when the customer pays by M-Pesa rather than "
           "cash. Cash costs the platform float risk, reconciliation and "
           "support; this pays customers a little of that back for avoiding "
           "it. Set to 0 to remove the incentive.",
           10.0, maximum=500.0),

    # ── Cancellation ──────────────────────────────────────────────────────
    #
    # One flat figure for every stage is unfair in one direction and toothless
    # in the other: cancelling before pickup costs the rider an approach,
    # cancelling after costs the vendor a prepared order and the rider a full
    # trip.
    _money("late_cancellation_penalty_after_pickup", "fees",
           "Cancellation penalty — after pickup",
           "Charged when a customer cancels once the rider is already carrying "
           "the order. The vendor has prepared it and the rider has ridden for "
           "it; the pre-pickup figure does not cover either.",
           150.0, maximum=5_000.0),
    SettingSpec("free_cancellations_per_month", "fees",
                "Free cancellations allowed",
                "Cancellations a customer may make in a rolling 30 days before "
                "any penalty applies. Genuine mistakes happen, and a support "
                "ticket costs more to handle than the penalty collects.",
                "int", 1, 0, 30, "per 30 days"),

    # ── Bottle deposits: exposure and ageing ──────────────────────────────
    SettingSpec("max_bottles_held_household", "bottles",
                "Bottle limit — household",
                "The most deposit-bearing bottles one ordinary customer may "
                "hold. Unlimited bottles is unlimited liability for the "
                "platform and an unlimited-size target for anyone farming it.",
                "int", 6, 1, 200, "bottles"),
    SettingSpec("max_bottles_held_commercial", "bottles",
                "Bottle limit — commercial account",
                "The same ceiling for an account flagged as commercial: an "
                "office or a shop legitimately holds more than a household.",
                "int", 30, 1, 1_000, "bottles"),
    SettingSpec("deposit_dormant_after_days", "bottles",
                "Deposit dormant after",
                "A deposit untouched for this long converts to store credit, "
                "after two warnings. Caps the platform's liability tail while "
                "leaving the customer's value intact — the money becomes water "
                "rather than disappearing.",
                "int", 548, 30, 3_650, "days"),
    SettingSpec("deposit_dormancy_warning_days", "bottles",
                "Warn before conversion",
                "How long before conversion the first warning goes out. A "
                "second follows at half this.",
                "int", 60, 1, 365, "days"),
    SettingSpec("deposit_return_window_hours", "bottles",
                "Pickup request expires after",
                "How long an unanswered bottle-pickup request waits for a "
                "rider before it lapses. Nothing moves when one expires — the "
                "customer keeps the bottles and the deposit — but leaving it "
                "open forever puts a task in a rider's list that nobody "
                "remembers raising.",
                "int", 72, 1, 720, "hours"),
    SettingSpec("deposit_return_auto_settle_minutes", "bottles",
                "Settle a one-sided handover after",
                "When the **rider** has confirmed a collection and the "
                "customer has not, the deposit is returned at the rider's "
                "count once this elapses. The rider has attested to taking a "
                "physical asset and is on the hook for it through the bottle "
                "ledger, so their word against their own interest settles it — "
                "and a customer should not have to chase their own money "
                "because a handset died. The reverse never auto-settles: a "
                "customer's unilateral claim goes to a human, because a timer "
                "that pays it out is a timer that pays anybody who waits.",
                "int", 120, 5, 10_080, "minutes"),
    SettingSpec("deposit_refund_is_withdrawable", "bottles",
                "Returned deposits are withdrawable as cash",
                "Off by default, and the default is the safe one. A returned "
                "deposit is credited as wallet balance that buys water but not "
                "a withdrawal. Switched on, the deposit becomes a "
                "money-transfer service — pay KSH 300 by M-Pesa, hand the "
                "bottle back, take KSH 300 out to a different phone — and with "
                "the welcome discount on top that round trip cleared a profit. "
                "Turn it on only if the platform decides to accept that.",
                "bool", False),
    _money("deposit_reconciliation_tolerance", "bottles",
           "Reconciliation tolerance",
           "How far the nightly deposit reconciliation may drift before it "
           "raises an alert. Not a licence to be wrong — a rounding residue on "
           "a partial return is real, and an alert that fires every night for "
           "one shilling is an alert everybody learns to close.",
           1.0, maximum=10_000.0),

    # ── Cash-on-delivery trust ────────────────────────────────────────────
    #
    # The float check asks "can this rider cover it". None of the below asks
    # "should this rider be trusted with it", and a rider who signed up an hour
    # ago and topped up KSH 500 could carry a stranger's cash.
    #
    # Every one is evaluated live, on each acceptance — not unlocked once. A
    # rider who was reliable in January and is abandoning orders now loses cash
    # eligibility the same day.
    SettingSpec("cod_enabled", "cash", "Cash on delivery available",
                "The master switch. Off means every order is prepaid, "
                "platform-wide, whatever an individual vendor allows.",
                "bool", True),
    SettingSpec("cod_min_rider_deliveries", "cash",
                "Cash: deliveries required",
                "Completed deliveries before a rider may carry cash. A pure "
                "count is farmable on its own, which is why it is one of six "
                "conditions rather than the gate.",
                "int", 25, 0, 1_000, "deliveries"),
    SettingSpec("cod_min_rider_account_age_days", "cash",
                "Cash: account age required",
                "Defeats burner accounts, which a delivery count alone does not.",
                "int", 14, 0, 365, "days"),
    _rate("cod_min_rider_completion_rate", "cash",
          "Cash: completion rate required",
          "Accepting a cash order and abandoning it is the main harm this "
          "guards against — it strands the customer and locks the rider's own "
          "float.", 0.92),
    SettingSpec("cod_min_rider_rating", "cash", "Cash: rating required",
                "Customer-witnessed reliability, which no internal counter is "
                "a substitute for.",
                "rate", 4.2, 0.0, 5.0, "stars"),
    _money("cod_max_order_value_standard", "cash",
           "Cash: order ceiling — standard rider",
           "The largest cash order an eligible rider may carry. Separate from "
           "the float check: that asks whether they can cover it, this asks "
           "whether they should be trusted with it.",
           2_000.0, maximum=100_000.0),
    _money("cod_max_order_value_platinum", "cash",
           "Cash: order ceiling — Platinum rider",
           "The same ceiling for a rider who has held Platinum.",
           10_000.0, maximum=200_000.0),
    SettingSpec("cod_max_concurrent_orders", "cash",
                "Cash: orders at once",
                "How many cash orders one rider may carry simultaneously. A "
                "rider with a large balance could otherwise hold six "
                "customers' water at once.",
                "int", 2, 1, 20, "orders"),
    _money("cod_max_daily_exposure", "cash", "Cash: daily ceiling per rider",
           "Total cash value one rider may carry in a day, resetting at "
           "midnight. Caps the worst single day.",
           15_000.0, maximum=500_000.0),
    SettingSpec("cod_min_customer_completed_orders", "cash",
                "Cash: customer orders required",
                "Cash on delivery is not offered on a customer's first order. "
                "A fake address plus cash costs the rider a wasted trip and "
                "the vendor a prepared order, and is the standard opening move "
                "against every COD platform in this market.",
                "int", 1, 0, 50, "orders"),
    SettingSpec("cod_unclaimed_release_minutes", "cash",
                "Cash: release float after",
                "An accepted cash order not delivered in this time releases "
                "the rider's committed float and returns to the pool. Float "
                "was otherwise committed until a terminal state, so one "
                "abandoned order locked a rider's money indefinitely.",
                "int", 120, 15, 1_440, "minutes"),
    SettingSpec("cod_max_distance_km", "cash",
                "Cash: maximum delivery distance",
                "Cash is refused beyond this. A long trip carrying somebody "
                "else's money is more exposure for the rider and more float "
                "committed for longer, and a bad address costs proportionally "
                "more the further it is. Set at or below the retail radius; "
                "above it the setting can never bite, because the order would "
                "already have been refused for distance.",
                "int", 2, 1, 50, "km"),
    SettingSpec("cod_require_delivery_photo", "cash",
                "Cash: photo proof required",
                "A photo on every cash delivery, not only on a bottle "
                "shortfall. One photo is what makes \"he never delivered it\" "
                "a decidable question.",
                "bool", True),

    # ── What a store may decide for itself ────────────────────────────────
    #
    # Vendors do not set their own delivery fee or radius. The rider is paid
    # out of the delivery fee, so a vendor undercutting to win orders would be
    # spending the rider's money; and the retail radius protects water
    # temperature and rider time, not just query cost. Both live on the console:
    # `retail_delivery_base_fee` / `retail_delivery_per_km` /
    # `short_hop_delivery_fee`, and `retail_max_distance_km`.
    #
    # What a store *does* decide is below, and each of these is the bound on
    # it. A self-service control with no ceiling is not self-service, it is an
    # unreviewed way to leave the platform: a store that sets a minimum nobody
    # can meet is delisted while still appearing open, and a pause with no
    # limit is a closure that never gets audited.
    _money("vendor_max_min_order_value", "storefront",
           "Store minimum — highest a vendor may set",
           "The largest order minimum any store may set on itself. A store "
           "setting KSH 50,000 has delisted itself while still appearing open "
           "and still ranking in search — the customer taps through, fills a "
           "basket and is refused at the last step, which reads as the "
           "platform being broken rather than the shop being shut. Set this "
           "against a realistic large basket, not against nothing.",
           500.0, maximum=100_000.0),
    SettingSpec("vendor_max_pause_hours", "storefront",
                "Longest pause a store may take",
                "A pause reopens the store by itself when it expires. This "
                "caps how long one may run for: beyond about a trading day it "
                "is not a pause, it is a closure, and a closure should be the "
                "explicit offline switch so it is visible as one on the "
                "console rather than looking like a shop that is about to "
                "reopen.",
                "int", 8, 1, 72, "hours"),
    SettingSpec("vendor_may_decline_cash", "storefront",
                "Stores may decline cash orders",
                "When on, a store can switch cash off for itself — the "
                "position a store with no float, or one that has just been "
                "robbed, is actually in. Turning it **off** takes that "
                "decision back platform-wide, which is a thing to do only if "
                "so many stores decline that cash on delivery stops working "
                "as an offer. Existing declines stop being honoured "
                "immediately when this goes off, so tell the stores first.",
                "bool", True),
    SettingSpec("vendor_hours_enforced", "storefront",
                "Refuse orders outside a store's opening hours",
                "`shift_start` and `shift_end` have been on every store since "
                "the first migration, shown on the console and in the app, and "
                "read by nothing — a store with 07:00–19:00 hours took orders "
                "at 03:00 and the owner found out from a push notification. "
                "**Off by default** because switching it on retrospectively "
                "closes every store whose hours were never real, so check them "
                "before you turn this on.",
                "bool", False),

    # ── Floors the console cannot price below ─────────────────────────────
    _money("rider_min_delivery_earning", "commission",
           "Rider minimum per delivery",
           "The least a rider may be left with on the shortest delivery. Not a "
           "charge — a floor the settings screen refuses to price below. A "
           "rider who cannot earn from a trip will not take it, and an order "
           "nobody takes is worse for the platform than one priced higher. "
           "Set against the shortest trip the platform sells: a sub-600 m drop "
           "is roughly ten minutes including loading.",
           35.0, maximum=5_000.0),
    SettingSpec("welcome_offer_requires_device", "bottles",
                "Welcome offer needs a device fingerprint",
                "When on, an account that reported no handset is refused the "
                "first-order discount. The device check existed and had never "
                "once fired: no app sent the field, so every account had a null "
                "and every null was treated as eligible — leaving the discount "
                "gated per account, and accounts are free. Turn this off only "
                "to unblock a client release that cannot report a device.",
                "bool", True),
    SettingSpec("bottle_replacement_cost_by_capacity", "bottles",
                "Bottle replacement cost",
                "What it actually costs to replace a bottle, per capacity. The "
                "deposit schedule is refused if any deposit falls below the "
                "matching figure here: a deposit worth less than the thing it "
                "secures is a discount on keeping it, and enough customers "
                "will do that arithmetic. Per capacity, because a 10 L bottle "
                "does not cost what a 20 L one does.",
                "deposits", {"20": 300.0, "10": 150.0}),
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
    "costs": "What it costs us",
    "cash": "Cash on delivery",
    "storefront": "What stores may set",
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
        + merged["refill_mine_commission_premium"]
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

    # ── The rider must still be able to earn a living ─────────────────────
    #
    # Commission rates were bounded individually and against each other, but
    # nothing checked what the rider was left holding. On retail the rider is
    # paid out of the delivery fee alone, and the platform now takes a markup
    # from that same fee — so three settings that are each individually
    # reasonable can combine to leave almost nothing.
    short_fee = _d(merged["short_hop_delivery_fee"])
    # The keep-my-bottle premium is deliberately absent: a short hop is never a
    # keep-my-bottle delivery (`DispatchPolicy.get_delivery_fee` excludes them
    # from the flat tier, because that journey is a round trip and distance is
    # exactly what it costs).
    rider_share = (
        Decimal("1")
        - _d(merged["gig_rider_commission_rate"])
        - _d(merged["retail_delivery_markup_rate"])
    )
    if rider_share <= 0:
        raise ValueError(
            "Rider commission plus the retail delivery markup would take the whole "
            "delivery fee. On a retail order the delivery fee is the rider's entire "
            "pay — this configuration pays them nothing."
        )
    if short_fee * rider_share < _d(merged["rider_min_delivery_earning"]):
        raise ValueError(
            f"A short-hop delivery would pay the rider KSH "
            f"{short_fee * rider_share:.2f}, below the KSH "
            f"{_d(merged['rider_min_delivery_earning']):.2f} floor. Raise the "
            "short-hop fee, lower the commission, or lower the floor — but a rider "
            "who cannot earn from a trip will not take it, and an order nobody "
            "takes is worse for the platform than one priced slightly higher."
        )

    # ── A short trip must not cost more than a long one ───────────────────
    threshold_km = _d(merged["short_hop_threshold_m"]) / Decimal("1000")
    long_fee_at_threshold = (
        _d(merged["retail_delivery_base_fee"])
        + _d(merged["retail_delivery_per_km"]) * threshold_km
    )
    if threshold_km > 0 and short_fee > long_fee_at_threshold:
        raise ValueError(
            f"The short-hop flat fee (KSH {short_fee:.2f}) is above what the normal "
            f"tariff would charge at the same distance (KSH {long_fee_at_threshold:.2f}). "
            "A customer one metre further away would pay less, which is the kind of "
            "thing that gets screenshotted."
        )

    # ── A deposit below the bottle's replacement cost invites theft ───────
    #
    # The deposit is the only thing standing between the platform and a bottle
    # that never comes back. Set below what a bottle costs to replace, keeping
    # it is simply the cheaper option, and enough customers will notice.
    costs = merged.get("bottle_replacement_cost_by_capacity") or {}
    schedule = merged.get("bottle_deposit_by_capacity") or {}
    for capacity, amount in schedule.items():
        # A capacity with no stated replacement cost is not checked. Better than
        # comparing it against some other bottle's cost, which is how this first
        # refused a perfectly sensible 10 L deposit for being under the 20 L
        # figure.
        if str(capacity) not in costs:
            continue
        replacement = _d(costs[str(capacity)])
        if _d(amount) < replacement:
            raise ValueError(
                f"The {capacity} L deposit (KSH {_d(amount):.0f}) is below the KSH "
                f"{replacement:.0f} cost of replacing that bottle. A deposit worth "
                "less than the thing it secures is a discount on keeping it."
            )

    # ── Debt ceiling must survive a cancellation ──────────────────────────
    #
    # If one late cancellation puts a customer at or above the ceiling, the
    # penalty is not a penalty — it is an account closure, applied by
    # arithmetic rather than by anyone's decision.
    worst_penalty = max(
        _d(merged["late_cancellation_penalty"]),
        _d(merged["late_cancellation_penalty_after_pickup"]),
    )
    if worst_penalty >= _d(merged["max_customer_debt_before_block"]):
        raise ValueError(
            f"A single cancellation (KSH {worst_penalty:.0f}) would reach the KSH "
            f"{_d(merged['max_customer_debt_before_block']):.0f} debt ceiling and "
            "lock the customer out of the platform outright. The ceiling must be "
            "above the largest penalty, or the penalty is a ban."
        )

    if merged["late_cancellation_penalty_after_pickup"] < merged["late_cancellation_penalty"]:
        raise ValueError(
            "Cancelling after pickup is set to cost less than cancelling before it. "
            "The later cancellation destroys more work, not less."
        )

    # ── Cash trust tiers must be ordered ──────────────────────────────────
    if merged["cod_max_order_value_platinum"] < merged["cod_max_order_value_standard"]:
        raise ValueError(
            "Platinum riders are allowed a smaller cash order than standard riders. "
            "The tier is meant to be a reward for reliability."
        )
    if merged["cod_max_daily_exposure"] < merged["cod_max_order_value_standard"]:
        raise ValueError(
            "The daily cash ceiling is below the single-order ceiling, so no rider "
            "could ever accept an order at the maximum value."
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

    # The history table, not just the live rows. Returning a setting to the
    # shipped default *deletes* its row, so a maximum taken over `rows` alone
    # walks backwards — and this number is what an order's pricing snapshot
    # records, so two different configurations sharing a version makes a
    # disputed total untraceable. History is append-only, so its maximum only
    # ever rises.
    try:
        recorded = (
            await session.execute(select(func.max(PlatformSettingHistory.version)))
        ).scalar()
        highest = max(highest, int(recorded or 0))
    except Exception:  # the table is unreachable; the live rows still date it
        logger.warning("Could not read the setting history high-water mark", exc_info=True)

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

    **Setting a value back to the shipped default deletes the row rather than
    storing it.** A stored row outranks the default permanently and silently, so
    writing one that merely *says* what the default says pins the key at today's
    figure forever — the next release changes the source and nothing moves, with
    nothing anywhere to explain why. That is not hypothetical: this platform ran
    at a retail service fee of 12 while its source said 35, on a row left behind
    by exactly this path (12 → 25 → 12, the last write storing the default of
    the day). Migration `b2f9c14e7a35` cleaned that up; this is what stops it
    happening again.

    An absent row is therefore the honest record of "we are following the
    platform", and it is what the console's *Use the shipped value* offers. An
    administrator who wants a figure held against future releases sets it to
    something of their own — which is the only way to express that intent
    unambiguously anyway.
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

        if value == DEFAULTS[key]:
            # Un-set, don't pin. See the docstring — a row saying what the
            # default says is indistinguishable from a decision, and outranks
            # every default the platform ships afterwards.
            if row is not None:
                await session.delete(row)
        elif row is None:
            row = PlatformSetting(key=key, value=value, version=next_version)
            row.updated_by_email = admin_email
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
        DispatchPolicy.get_delivery_fee(
            distance_km, vendor_type, vehicle_class, 0, 0, delivery_type
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
        product_total=products,
        delivery_fee=delivery_fee,
        vendor_type=vendor_type,
        bottle_deposit=bottle_deposit,
        rider_surcharges=payload_surcharge + staircase_surcharge,
        delivery_type=delivery_type,
        welcome_discount=welcome_discount,
    )

    # `calculate_revenue_splits` re-derives the surge fee from the clock, which
    # is right for a live quote and wrong for a hypothetical one. The caller
    # says whether to model surge, so that figure is substituted here rather
    # than depending on what time the preview happened to be requested.
    platform_total = money(
        splits["vendor_commission"]
        + splits["service_fee"]
        + splits["rider_commission"]
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
        "vendor_receives": str(money(splits["vendor_net"])),
        "rider_receives": str(money(splits["rider_net"])),
        "vehicle_class": vehicle_class,
    }


def min_chargeable_total_value() -> Decimal:
    """The floor an order total cannot go below. Named to avoid colliding with
    `pricing_service.min_chargeable_total`, which wraps the same figure."""
    return get_decimal("min_chargeable_total")
