# Platform audit — what is missing, and what it costs

Audited against the code, not the plan: every admin route, every table in the
live Neon database, and every page in the console. Findings are ordered by what
they cost the business, not by how hard they are.

---

## A. Domains with **no admin visibility at all**

These have tables, they have writers, and nobody can see them.

### A1. `failed_webhooks` — nothing reads it. **Highest severity.**

Zero mentions across every `routes/admin_*.py`. The table exists, the backend
writes to it, and no human being can look at it.

A failed M-Pesa callback means a customer has **paid Safaricom and the order is
still `pending`**. The money left their account. The reconciliation sweep may
catch it; if it does not, the row sits in `failed_webhooks` for ever and the
first anyone hears is a complaint. There is currently no screen, no count, no
badge and no alert.

*Needed:* a Finance → Reconciliation screen listing failed webhooks with the
order, the amount, the failure reason and the age, plus a **replay** action and
a nav badge. This is the single largest hole in the platform.

### A2. Catalogue — 114 products, no oversight

`Product` appears in `admin_analytics_service.py` only, to compute top sellers.
There is no way to see the catalogue, find a mispriced item, disable a product,
or audit what vendors are actually selling. Bottle sizes and prices are the
product; the platform cannot inspect its own inventory.

*Needed:* Operations → Catalogue — searchable across vendors, with price
outliers surfaced, out-of-stock and below-threshold counts, and a disable action.

### A3. Reviews — customer-visible content with no takedown path

`reviews` has no admin route. A defamatory or abusive review about a vendor or
rider is visible in three apps and cannot be removed by anyone.

*Needed:* moderation queue, rating distribution per target, and a hide action
that is audited.

### A4. Bottle ledger — disputes exist, the ledger they arbitrate does not

`/disputes` resolves `Bottle_Rejection_Tickets`, but `bottle_ledger_entries` —
the record of who holds whose bottles — is invisible. An administrator is asked
to arbitrate a deficit without being able to see the account it is drawn from.

*Needed:* per-vendor and per-rider bottle balance, movement history, and
outstanding-deficit totals. This is the platform's second currency and it is
unaudited.

### A5. `Order_Tracking_Logs` — no delivery replay

Written on every status change and read by nothing. "The rider says they
delivered it, the customer says they didn't" is unanswerable today.

### A6. In-house rider relationships

`Deliverer_Vendors` and `VendorRiderRegistry` drive dispatch priority — an
in-house rider is assigned before any gig rider. No admin screen shows these
links, so a vendor claiming "no riders are being assigned to me" cannot be
checked.

### A7. Notifications — 66 rows, no delivery visibility

No view of what was sent, to whom, or what failed. Push failures are invisible,
so "the customer was never told" cannot be confirmed or denied.

---

## B. Console pages that are a table and a filter

**8 of 13 pages** carry no aggregate at all. Every one is a list with a search
box, so the operator sees rows and never the shape of the problem.

| Page | Today | What it cannot answer |
|---|---|---|
| `operations/orders` | table + view tabs | How many are stuck, for how long, and is it getting worse |
| `operations/kyc` | queue cards | How deep is the queue, how old is the oldest, what is the approval rate |
| `operations/vendors` | queue cards | Same |
| `operations/disputes` | cards | How much money is at risk, what is about to auto-resolve |
| `finance/payouts` | table | **How much money is waiting for approval** |
| `people/[kind]` | table | Active vs suspended, KYC funnel, new this week |
| `platform/audit` | table | Who is doing what, and is anything spiking |
| `support` | table + counts | First-response time, backlog age, category mix |

Only `/analytics` (738 lines) and the dashboard root have real aggregates. The
primitives to fix this already exist and are unused on these pages: `Stat`,
`StatList`, `Sparkline`, `BarList`, `DonutChart`, `GaugeRing`, `FunnelChart`.

**Some of it is already free.** `/orders/counts` and `/finance/summary` exist on
the backend and no page calls them. `support` calls `/support/counts` and is the
only operational page that does.

---

## C. Missing operational capability

| Gap | Consequence |
|---|---|
| **No SLA anywhere** | Nothing defines "too long". `STALE_AFTER_MINUTES` is the only time rule on the platform, and it is invisible to operators |
| **No refund oversight** | `process_pending_refunds_task` runs on a schedule; no screen shows what it did or what is stuck |
| **No rider performance view** | Completion rate, acceptance rate, cancellations per rider — none of it is surfaced. Deactivating a bad rider is a guess |
| **No vendor performance view** | Same: preparation time, rejection rate, disputes per store |
| **No payout reconciliation** | Payouts approve into M-Pesa B2C with no screen reconciling what was sent against what settled |
| **No cash-float exposure** | `committed_cash_float` gates withdrawals but is shown nowhere in aggregate — the platform's cash-at-risk is unknown |
| **Export is analytics-only** | `/analytics/export` exists; no other screen can export, so finance cannot reconcile off-platform |

---

## D. Data and correctness findings

- **`Admin_Audit_Log` is empty (0 rows) — and that is correct.** Re-checked
  properly: every mutating admin route calls `record_audit`, across all eight
  modules. The table is empty because no audited action has been taken on this
  database yet, not because writes are missing. The original finding was drawn
  from too narrow a grep.
- **All 30 riders are `kyc_status='unsubmitted'` and none is bound to Clerk**, so
  coverage correctly reports 21/21 stores uncovered. Every dispatch path is
  therefore untested against real data.
- **Zero rows** in `payouts`, `WalletTransactions`, `reviews`,
  `Support_Tickets`, `bottle_ledger_entries`, `Order_Tracking_Logs`. The money
  and reputation paths have never run end to end on this database.
- **`Carts` and `Cart_Items` are empty** — abandoned-cart recovery, an obvious
  revenue lever, has no data and no screen.

---

## E. Sequence

Ordered by value per unit of work.

1. ~~**Aggregate headers on the bare pages.**~~ **Done** for orders, rider KYC,
   vendor verification, disputes, payouts and support, plus the new
   reconciliation screen. `services/admin_queue_service.py` computes depth, age,
   throughput and outcome for every queue from one uniform shape, and
   `GET /queues/stats` serves them capability-filtered like `/nav/counts` — a
   missing key means "not yours", never zero. Two tests hold the line: one fails
   the build if a queue page renders no aggregate, the other if a figure is
   coerced with `?? 0`.

   Still bare: `people/[kind]` and `platform/audit`.
2. ~~**Failed-webhook reconciliation screen.**~~ **Done.** See
   `services/admin_reconciliation_service.py` and `/finance/reconciliation`.
3. ~~**Bottle ledger views.**~~ **Done.** `services/admin_bottle_service.py`
   and `/operations/bottles`. The float is netted per (rider, vendor, capacity)
   before it is totalled — a credit at one store must never cancel a debt at
   another — and priced from `bottle_deposit_by_capacity`, the same deposit the
   customer paid. `drift()` checks the invariant `bottle_ledger_service`
   declares and nothing enforced: `SUM(quantity) == pending_{n}L_empties`. The
   repair rewrites the counter from the ledger, never the reverse, and is a
   button rather than automatic because drift means something wrote a counter
   without a ledger row.
4. ~~**Catalogue moderation.**~~ **Done.** `/operations/catalogue`.
5. ~~**Rider and vendor performance.**~~ **Done.** `/people/performance`. Every
   rate carries its denominator and nothing is ranked below five finished
   orders; below that the console writes "under 5 orders" rather than a figure
   it would have to caveat.
6. **Review moderation.**
7. **Refund and payout reconciliation.**
8. **Delivery replay from `Order_Tracking_Logs`.**
