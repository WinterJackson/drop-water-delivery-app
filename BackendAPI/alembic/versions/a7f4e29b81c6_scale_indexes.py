"""Indexes for the two query shapes that scan a whole table, and one that never earned its keep.

Three unrelated things, all about what happens when these tables stop being
empty.

## 1. `Orders.created_at` on its own

`d4a8f2c61b93` added `(order_status, created_at)`, which serves the sweeps: they
name a status first, so the index leads correctly and the live working set stays
a tiny fraction of the table.

Nothing serves the **console**. Every panel on the analytics screens filters
`Order.created_at >= start AND < end` with no other predicate — revenue, order
mix, cancellation rate, hourly demand, cohort activity. A composite that leads
with `customer_id`, `vendor_id`, `deliverer_id` or `order_status` cannot answer
that, so each of those panels is a sequential scan of the entire order history,
several of them per page load, several staff at a time, against the same database
that is taking orders.

Descending, because every one of those queries reads the recent end and several
order by it.

## 2. Trigram indexes for the console's search boxes

Twelve call sites do `column.ilike('%term%')`. A leading wildcard cannot use a
B-tree, so each is a sequential scan — on the console, where somebody searching
for an M-Pesa receipt is doing it *because* a customer is on the phone about a
disputed order.

`pg_trgm` makes exactly that pattern index-assisted, with no change to a line of
query code. Five columns, chosen because each is a search box somebody uses under
time pressure:

* a rider by name, and a store by name — the fleet and vendor screens;
* an order by the customer's phone number — the single most common support lookup;
* a payment or a wallet movement by M-Pesa receipt — the dispute path.

`gin_trgm_ops` rather than GiST: GIN is slower to build and to update and much
faster to search, which is the right trade for columns written once and searched
repeatedly.

## 3. Dropping `ix_Orders_delivery_fee`

Declared `index=True` on the column and never used by anything: no route, service
or job filters, joins or sorts on the delivery fee. It is pure write cost on the
busiest-growing table on the platform, paid on every order forever, and it made
`Orders` marginally slower to insert into for nothing at all.

Created without CONCURRENTLY, for the same reason `d4a8f2c61b93` records: Alembic
runs a migration in a transaction and `CREATE INDEX CONCURRENTLY` cannot. On a
table of this size the lock is momentary. Past the point where that stops being
true, build these by hand with CONCURRENTLY and stamp the revision instead.

Revision ID: a7f4e29b81c6
Revises: c7d2e94a6f18
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f4e29b81c6"
down_revision: Union[str, Sequence[str], None] = "c7d2e94a6f18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: (index name, table, column). Every one of these is a search box on the console.
_TRIGRAM_INDEXES = [
    ("ix_deliverers_name_trgm", "Deliverers", "name"),
    ("ix_vendors_business_name_trgm", "Vendors", "business_name"),
    ("ix_orders_phone_trgm", "Orders", "phone"),
    ("ix_payments_mpesa_receipt_trgm", "payments", "mpesa_receipt"),
    ("ix_wallet_tx_receipt_trgm", "WalletTransactions", "mpesa_receipt_number"),
]


def upgrade() -> None:
    # 1. The console's date-ranged analytics.
    op.create_index(
        "ix_orders_created_at_desc",
        "Orders",
        [sa.text("created_at DESC")],
        unique=False,
    )

    # 2. Substring search that can use an index.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in _TRIGRAM_INDEXES:
        op.execute(
            f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" '
            f'USING gin ("{column}" gin_trgm_ops)'
        )

    # 3. An index nothing has ever read.
    op.execute('DROP INDEX IF EXISTS "ix_Orders_delivery_fee"')


def downgrade() -> None:
    op.create_index("ix_Orders_delivery_fee", "Orders", ["delivery_fee"], unique=False)
    for name, _table, _column in _TRIGRAM_INDEXES:
        op.execute(f'DROP INDEX IF EXISTS "{name}"')
    # The extension is deliberately left in place: something else may have come to
    # depend on it, and dropping it would take those indexes with it.
    op.drop_index("ix_orders_created_at_desc", table_name="Orders")
