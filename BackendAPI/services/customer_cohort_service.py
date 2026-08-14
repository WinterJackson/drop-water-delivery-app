"""Recording, and repairing, when a customer was acquired.

`Customer_First_Delivery` replaces a `MIN()` over the whole `Orders` table. The
only thing that matters about it is that it says *exactly* what that query said,
so this module is written around one definition and two ways of satisfying it.

## The definition

    A customer's cohort is `date_trunc('month', created_at)` of their earliest
    **delivered** order, over all history.

Three things in that sentence are load-bearing and each was argued for before
this table existed:

* **Delivered**, not placed. An account that never received water was not
  acquired.
* **`created_at`**, not the delivery time. Acquisition is the moment the customer
  chose the platform; a delivery delayed into the next month must not move them
  into the next cohort.
* **Over all history.** Computed inside the reporting window, a `MIN()` re-acquires
  a two-year customer into this month — inventing new customers out of loyal ones
  and flattering both the growth figure and the CAC.

## The write is monotonic, not first-wins

The obvious hook — "on delivery, insert if absent" — is wrong, and wrong in a way
that would not show up for months.

The `MIN()` runs over `created_at`, but orders do not reach `delivered` in
`created_at` order. An order placed in January and disputed until March is
delivered *after* one placed in February. First-wins would record February and
never correct it, so that customer would sit in the wrong cohort permanently,
with a real delivered January order contradicting it in the same table.

So the write lowers the recorded value when it sees an earlier one, and is
otherwise a no-op:

    ON CONFLICT (customer_id) DO UPDATE … WHERE existing.first_order_at > excluded

That is idempotent, safe to replay, and safe under concurrency — two riders
completing two of the same customer's orders at the same instant converge on the
earlier one whichever lands first.

## And it is reconciled, because a hook can be missed

`reconcile` re-derives the whole table from `Orders` and repairs any row that
disagrees. It exists because the fast path depends on every delivery path calling
it, and "every path remembers" is exactly the assumption this codebase has
already been bitten by — `commission_lost` went missing on vendor rejects for
precisely that reason. The hook keeps the table current; the sweep makes it
*true*. It reports what it changed rather than fixing silently: steady drift is a
missing call site, and that is worth seeing.
"""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer_cohort_model import CustomerFirstDelivery
from models.order_model import Order

logger = logging.getLogger(__name__)

#: The single order state that counts as an acquisition. Named once here and
#: imported by the growth service, so the table and the report cannot disagree
#: about what "acquired" means.
ACQUIRED_STATUS = "delivered"


def _cohort_month(column):
    return func.date_trunc("month", column)


async def record_acquisition(session: AsyncSession, order: Order) -> None:
    """Note that this order delivered, and lower the cohort if it is earlier.

    Called on the delivery path, **before** the commit that makes the delivery
    real, so the row and the order status land in the same transaction — a
    rollback must not leave a customer acquired by an order that never completed.

    Never raises. A growth report is not worth failing a delivery over: the rider
    is at the door, the money is moving, and `reconcile` will repair anything
    lost here on the next sweep.
    """
    if order is None or order.customer_id is None or order.created_at is None:
        return

    try:
        statement = pg_insert(CustomerFirstDelivery.__table__).values(
            customer_id=order.customer_id,
            first_order_at=order.created_at,
            cohort_month=_cohort_month(order.created_at),
            order_id=order.id,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[CustomerFirstDelivery.customer_id],
            set_={
                "first_order_at": statement.excluded.first_order_at,
                "cohort_month": statement.excluded.cohort_month,
                "order_id": statement.excluded.order_id,
            },
            # Only ever move the acquisition *earlier*. Without this predicate the
            # last delivery to land would overwrite the first, and every repeat
            # customer would report as acquired this month.
            where=CustomerFirstDelivery.__table__.c.first_order_at
            > statement.excluded.first_order_at,
        )
        await session.execute(statement)
    except Exception as exc:
        logger.warning(
            "Could not record the acquisition for order %s: %s. `reconcile` will repair it.",
            getattr(order, "id", None),
            exc,
        )


def first_delivery_source():
    """The subquery the growth report joins against.

    Shaped exactly like the `MIN()` it replaced — `customer_id`, `cohort` — so the
    report reads the same either way and swapping between them is a one-line
    change rather than a rewrite.
    """
    return select(
        CustomerFirstDelivery.customer_id.label("customer_id"),
        CustomerFirstDelivery.cohort_month.label("cohort"),
    ).subquery()


def _derived_query():
    """The definition, in SQL. The one place it is written."""
    return (
        select(
            Order.customer_id.label("customer_id"),
            func.min(Order.created_at).label("first_order_at"),
        )
        .where(
            Order.order_status == ACQUIRED_STATUS,
            Order.customer_id.isnot(None),
        )
        .group_by(Order.customer_id)
    )


async def reconcile(session: AsyncSession) -> dict:
    """Re-derive the table from `Orders` and repair every row that disagrees.

    Three statements, no loop. The first version of this walked the derived rows
    and issued an upsert per customer, which `tests/test_query_shape.py` rightly
    refused: a sweep over the whole customer base doing one round trip per row is
    fifty thousand round trips, and it is *the* pattern this codebase forbids.
    Everything here is a set operation, so the cost is one pass whatever the
    platform's size.

    Returns counts rather than logging and forgetting. `repaired` should be zero
    on a healthy platform; a number that keeps climbing means a delivery path has
    been added without a `record_acquisition` call — a defect in the code, not in
    the data, and one nobody would otherwise notice.
    """
    table = CustomerFirstDelivery.__table__

    # How far out of step are we? Measured before the repair, because afterwards
    # the answer is always zero and a sweep that cannot report drift is a sweep
    # nobody can tell is doing anything.
    derived = _derived_query().subquery()
    drift = (
        await session.execute(
            select(func.count()).select_from(
                derived.outerjoin(table, table.c.customer_id == derived.c.customer_id)
            ).where(
                (table.c.customer_id.is_(None))
                | (table.c.first_order_at != derived.c.first_order_at)
            )
        )
    ).scalar_one()

    # The repair, as one statement — and it is the same SQL as the migration's
    # backfill, deliberately: the definition is written once.
    source = _derived_query().subquery()
    upsert = pg_insert(table).from_select(
        ["customer_id", "first_order_at", "cohort_month"],
        select(
            source.c.customer_id,
            source.c.first_order_at,
            _cohort_month(source.c.first_order_at),
        ),
    )
    await session.execute(
        upsert.on_conflict_do_update(
            index_elements=[table.c.customer_id],
            set_={
                "first_order_at": upsert.excluded.first_order_at,
                "cohort_month": upsert.excluded.cohort_month,
            },
            where=table.c.first_order_at != upsert.excluded.first_order_at,
        )
    )

    # A row here with no delivered order behind it — a delivery reversed after the
    # fact, or an order later corrected. The definition says a customer with no
    # delivered order was never acquired, so it goes.
    still_delivered = (
        select(Order.customer_id)
        .where(
            Order.order_status == ACQUIRED_STATUS,
            Order.customer_id == table.c.customer_id,
        )
        .exists()
    )
    removed = (
        await session.execute(table.delete().where(~still_delivered))
    ).rowcount or 0

    await session.commit()

    if drift or removed:
        _escalate(int(drift), int(removed))

    return {"corrected": int(drift), "removed": int(removed)}


def _escalate(corrected: int, removed: int) -> None:
    """Put drift somewhere a person will see it.

    A log line inside a nightly cron job is not an alert. It is written to a
    stream nobody tails, on a schedule nobody watches, about a condition whose
    entire significance is that it *keeps happening* — and by construction the
    only reader who would notice the pattern is one already looking for it.

    Most of what this used to warn about is now a build failure:
    `test_customer_cohorts.py` discovers every call that can move an order to
    `delivered` and requires `record_acquisition` beside it, so a delivery path
    added without the hook fails CI rather than showing up here a day later. What
    is left is the residue that CI cannot see — a delivery reversed after the
    fact, a row corrected by hand, a restore from an older backup — and that is
    exactly the kind of thing worth one message rather than a dashboard.

    Sentry, because it is what this platform already alerts on, and with the
    counts attached rather than in the message text so they can be grouped and
    trended rather than read one at a time. Never raises: a reporting failure
    must not fail the sweep that was doing the repair.
    """
    logger.warning(
        "Cohort reconciliation corrected %s row(s) and removed %s orphan(s).",
        corrected,
        removed,
    )
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_context(
                "cohort_reconciliation",
                {"corrected": corrected, "removed": removed},
            )
            # A tag, so this can be alerted on and trended. A single correction
            # after a manual data fix is expected; the same count returning every
            # night is the signal, and a tag is what makes that visible without
            # anybody reading individual events.
            scope.set_tag("reconciliation", "customer_cohorts")
            scope.level = "warning"
            sentry_sdk.capture_message(
                "Customer cohort table drifted from the orders it is derived from",
            )
    except Exception:  # pragma: no cover - reporting must never break the sweep
        logger.debug("Could not report cohort drift to Sentry", exc_info=True)


async def cohort_for(session: AsyncSession, customer_id: UUID):
    """This customer's cohort month, or `None` if they have never been delivered to."""
    return (
        await session.execute(
            select(CustomerFirstDelivery.cohort_month).where(
                CustomerFirstDelivery.customer_id == customer_id
            )
        )
    ).scalar_one_or_none()
