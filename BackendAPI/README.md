# Drop Backend API ⚙️

> The single FastAPI service behind everything: the customer, rider and vendor
> apps, and the `drop-admin` operations console. One database, one pricing path,
> one set of business rules.

---

## 🏛️ Architecture

A modular monolith. Four clients, one server, and deliberately no second
database — a figure on an admin dashboard and a figure in a vendor's app cannot
drift apart when they come from the same query.

| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI, fully async | The workload is IO-bound: Postgres, Redis, M-Pesa, S3, Expo |
| Database | PostgreSQL + PostGIS | `ST_DWithin` for exact-distance discovery |
| Geospatial index | H3 resolution 8 | Cheap bucketing before the exact pass |
| ORM | SQLAlchemy 2.0 async | `with_for_update()` is what makes dispatch and wallets safe |
| Cache / bus | Redis | WebSocket pub/sub across replicas, rate limiting, the ARQ queue |
| Background | ARQ, **own process** | See *Process topology* |
| Storage | AWS S3, private | Keys in the database, presigned on read — never a public URL |

### Directory map

```
BackendAPI/
├── models/        23 SQLAlchemy models — the schema
├── schemas/       Pydantic v2 request/response types
├── routes/        Endpoints grouped by domain; everything admin is /api/admin/*
├── services/      Business logic — where the rules actually live
├── jobs/          The sweeps ARQ runs on a schedule
├── dependencies/  Auth and authorisation dependencies
├── core/          Config, session, security, Redis
├── alembic/       Migrations
├── scripts/       Operational one-offs (Clerk rebinding, admin access, backfills)
└── tests/         43 files; unit, integration, and structural (AST) tests
```

---

## ⚙️ Process topology

The API and the background worker are **two separate processes**. This is not
optional in any environment with more than one API instance.

```bash
uvicorn main:app --port 8000     # terminal 1
arq worker.WorkerSettings        # terminal 2
```

The worker owns a cron schedule. If it runs inside the API process, every uvicorn
worker and every deployed replica runs its own copy, so each tick fires N times —
N refund attempts, N auto-cancellations of the same order.

| Sweep | Cadence | What it does |
|---|---|---|
| `flush_gps_tracking_logs_task` | every 10s | Batches rider location pings into `Order_Tracking_Logs` |
| `auto_resolve_bottle_rejections_task` | every minute | Adjudicates bottle disputes nobody answered |
| `auto_cancel_pending_orders_task` | every 5 min | Cancels unpaid orders, restores stock |
| `process_pending_refunds_task` | every 2 min | Drives M-Pesa reversals for cancelled paid orders |
| `reassign_unassigned_orders_task` | every 3 min | Re-offers orders no rider took |
| `check_push_receipts_task` | every 10 min | Reads Expo delivery receipts |
| `stale_asset_monitor_task` | daily 03:00 | Flags orphaned S3 objects |
| `evaluate_platinum_riders_task` | daily 00:00 | Recomputes rider tiers |

| Env var | Default | Effect |
|---|---|---|
| `RUN_INLINE_WORKER` | `0` | `1` **only** on a single-process dev machine. Never in production |

Every sweep claims its rows with `FOR UPDATE ... SKIP LOCKED`, re-checks state
under the lock, and commits per item inside a `try/except`, so an accidental
second worker degrades throughput rather than corrupting data — but the topology
above is still the supported one.

---

## 💰 Pricing — one function, no exceptions

`services/pricing_service.py::compute_order_quote` is the **only** place an order
total is computed. It returns every line item as `Decimal` and quantizes `total`
to whole shillings.

* `POST /api/cart/quote` serves that quote; the client renders it verbatim.
* `POST /api/cart/mpesa_payment` pushes `quote.stk_amount` to Safaricom.
* `order_service.create_order(..., quote=quote)` writes that same `quote.total`.

The amount charged and the amount recorded are therefore equal by construction.
Four competing implementations of this arithmetic is what once made the M-Pesa
callback's amount cross-check reject every retail payment.

`tests/test_pricing_parity.py` asserts `stk_amount == order.total_amount` across
the full matrix of vendor type × surge × first order × wallet × delivery type.
**Do not add a second pricing path.**

### Business values are rows, not constants

34 settings across 6 groups live in `Platform_Settings` and are read through
`services/platform_config_service.py` — commission rates, service fees, delivery
pricing, bottle deposits, operating limits, workflow timings. They are edited
from the console at `/platform/pricing`, versioned, audited, and live in all
three apps on the next quote.

---

## 🔑 Authentication

**Identity comes from the token, never from the request body.** `create_user`,
`create_vendor` and `create_rider` all overwrite `clerk_id` with `user["sub"]`.
They once read it from posted JSON with no auth dependency at all, so anyone
could bind a vendor row to somebody else's Clerk subject.

`core/security.py` verifies with the JWKS pinned to RS256, plus audience and
issuer. A missing Clerk environment variable makes python-jose skip those checks
*silently*, so the module refuses to start outside development without them. An
unknown `kid` forces one cache refresh — rate-limited and single-flight — before
the token is rejected; that is how signing-key rotation is survived, and without
it a rotation locked out every user for up to an hour.

Sockets are the one place a token is presented once and then trusted for hours.
Every socket loop calls `_close_if_token_expired`, closing with 1008 so the
client reconnects with a fresh token.

Webhooks that mutate money or order state — `sms_routes`, the M-Pesa payout and
reversal callbacks — need a shared secret. IP allow-listing alone is not a guard
while `ProxyHeadersMiddleware` trusts every forwarding host.

### Order-scoped authorisation

Authenticating a token proves *who* is calling; it says nothing about whether
they have any relationship to the order named in the URL. Every order-scoped
endpoint — REST **and** WebSocket — must call
`dependencies.auth_dependencies.authorise_order_access`, or `owns_entity` for
entity-scoped sockets. Skipping it exposes one customer's live delivery location
to any other signed-in account.

---

## 🏪 A `Vendor` row is a store, not an account

One Clerk identity may own several. Every vendor endpoint resolves an **active
store** through `get_active_store` (owner or staff) or `get_owned_store` (owner
only), both of which read an `X-Store-Id` header, validate it against the
caller's own stores, and fall back to a deterministic
`ORDER BY created_at ASC LIMIT 1`. A store the caller does not own is a **404**,
not a 403 — confirming an id exists is itself a leak.

* Routes take the resolved `Vendor` row. Do not call `get_vendor_by_clerk_id` from a route; its fallback is `clerk_id = … OR staff_clerk_id = …` with no store id, which is exactly the ambiguity the dependency removes.
* **Never `scalar_one_or_none()` on a vendor lookup.** It raises `MultipleResultsFound` on the second store, and the vendor app calls `profile-status` and `push-token` before anything else — so opening a branch turned app startup into a 500.
* `get_owned_store` checks ownership against the *resolved row*. Someone can own store A and be staff of store B; composing an owner gate with a store resolver would let them act on B.

### Staff are `Vendor_Staff` rows, with capabilities

`Vendor.staff_clerk_id` held one id and was UNIQUE **platform-wide**: a store
could have one staff member, a second silently replaced the first, and one person
could work for exactly one store on the whole platform. Access was
all-or-nothing, so handing someone the till handed them the catalogue, the bottle
ledger and the wallet balance.

Four capabilities — `manage_orders`, `manage_products`, `manage_bottles`,
`view_finances`. Gate every **mutating** route with `require_permission(...)`;
reads any member may make take `get_active_store`. `view_finances` is **not**
granted by default: seeing the store's balance is a decision the owner makes, not
one inherited from a schema that could not express the question.

> **Never read `staff_clerk_id` or `staff_push_token`.** They survive only so an
> application rollback does not lose anybody's access, and
> `tests/test_vendor_staff.py` tokenizes every module and fails the build if
> either is read.

---

## 💵 Wallets, cash float and payouts

`wallet_balance` is the **single spendable balance** for riders and vendors.
`available_for_withdrawal = wallet_balance − committed_cash_float`, and
`services/settlement_service.py` owns that arithmetic — never re-derive it.
Withdrawal eligibility once came from a separate derived earnings sum while
payouts debited nothing, so the same money could be withdrawn *and* spent as
cash-order float.

Move balances only through `wallet_service.apply_wallet_delta`, which mutates the
balance and appends the signed `WalletTransaction` in one call. **Money is
`Decimal`, never `float`.**

A payout is debited *before* the M-Pesa B2C call, so the money cannot be spent
twice while it is in flight — which makes returning it on failure mandatory.
`payout_service._refund_failed_payout` writes a `refund` transaction with
`reference_id = payout.id`, and `services/admin_settlement_service.py` checks
that invariant on the console's settlement screen.

See [docs/cash-settlement.md](../docs/cash-settlement.md).

---

## 🍶 The bottle ledger

On a `quick_swap` order the rider hands over full bottles and takes the
customer's empties, which belong to the store. From that moment the rider holds
store property.

`bottle_ledger_entries` is append-only and signed; the
`VendorRiderRegistry.pending_{10,20}L_empties` counters are a denormalisation of
its sum. For every (rider, vendor, capacity):

```
SUM(bottle_ledger_entries.quantity) == VendorRiderRegistry.pending_{n}L_empties
```

`services/bottle_ledger_service.py` is the only place either is written, and
`admin_bottle_service.drift()` is what checks the invariant — an invariant nobody
checks is a comment. Two behaviours the ledger exists for: accrual is
**idempotent** (`uq_bottle_ledger_order_accrual`, because delivery completion is
retried from the rider app's offline queue), and it does **not** require a
registry row (tier-2 radar dispatch lets a rider deliver for a store they never
registered with).

---

## 🔔 Notifications

Every user-visible event writes an in-app `Notification` row **and** may send a
push. The two are not interchangeable: the row is always written so the history
survives, while the push is subject to `notification_service.push_allowed`, which
reads the recipient's `preferences`. Unmapped `message_type`s are transactional
and always delivered — muting promotions must not mute a failed payment.

There are exactly two ways to send a push, and `asyncio.create_task` is neither:

| When | Use | Why |
|---|---|---|
| Before the commit | `queue_push(session, …)` | An `after_commit` hook sends it; a rollback discards it |
| After the commit | `dispatch_background(…)` | Holds a strong reference so the task cannot be collected mid-send |

`tests/test_ratings_and_notifications.py` fails the build if a bare
`create_task(send_push_message(...))` reappears. Pushes used to fire several
statements *before* the commit that made the change real, so a rolled-back order
still told the customer it was confirmed.

`user_type` is validated against `VALID_USER_TYPES` and must be passed on **every**
notification call, reads and writes alike, because `Notification.user_id` holds
ids from three tables and carries no foreign key.

See [docs/push-notifications.md](../docs/push-notifications.md).

---

## ⭐ Ratings and moderation

Aggregation is incremental: `Vendors` and `Deliverers` carry `rating_count` and
`rating_sum`, `review_service` locks the target `FOR UPDATE`, folds the new
rating in, and derives `rating` from the two. Never recompute with `AVG()` over
the reviews table — that is unbounded work on exactly the busiest targets.

Moderation is `hidden_at`, and **every public read filters on it**. A delete would
lose that the review existed, release `uq_customer_order_target_review` so the
customer can leave another, and strand the counters on a row that is gone.
`admin_review_service.set_hidden` rebuilds the target's rating from the visible
rows in the same transaction — a one-star review taken out of the list and left
in the average is moderation theatre. That rebuild is the *one* sanctioned `SUM()`
over `reviews`. A resubmit of a hidden review is a 409, not an edit.

---

## 🗺️ Google Maps web services go through here

The six keys shipped in the mobile apps are restricted to the **Maps SDK** for
one package or bundle each — that restriction is the only thing that makes an
embedded key safe, and it also means those keys cannot call Directions, Places or
Geocoding.

`routes/maps_routes.py` owns every Google web-service call, using a single
IP-restricted `GOOGLE_MAPS_SERVER_API_KEY`. It authenticates, rate-limits, caches
in Redis on coordinates rounded to ~11 m, reduces the response to what the client
draws, and never forwards Google's `error_message` (it names the project and
sometimes the key). Add new services there, not in the apps.

See [docs/maps-architecture.md](../docs/maps-architecture.md).

---

## 🛡️ The admin surface

Everything under `/api/admin/*` is gated by `require_admin(capability)`, which
resolves an `Admin_Users` row per request — so revocation takes effect on the
next call, not the next deploy. `tests/test_admin_rbac.py` walks every route in
the module and fails the build on one that names no capability.

| Route module | Domain |
|---|---|
| `admin_routes` | Dashboard, search, navigation counts, queue stats, KYC decisions |
| `admin_analytics_routes` | Revenue, demand, retention, unit economics, export |
| `admin_orders_routes` | Order board, interventions, bottle disputes, **delivery replay** |
| `admin_people_routes` | Customers, riders, vendors, PII reveal, **performance** |
| `admin_finance_routes` | Ledger, adjustments, webhook reconciliation, **settlement** |
| `admin_catalogue_routes` | Products across every store, price outliers |
| `admin_bottle_routes` | The bottle float, drift repair, hand corrections |
| `admin_review_routes` | Review moderation |
| `admin_fleet_routes` | Rider/store registry, notification delivery |
| `admin_geo_routes` | Map layers |
| `admin_config_routes` | `Platform_Settings` and the pricing preview |
| `admin_support_routes` | Tickets and broadcast |

Every mutating admin route calls `admin_service.record_audit` in the same
transaction as the change, and most require a written reason of at least 8
characters. `Admin_Audit_Log` is what makes the console defensible.

---

## 🧪 Tests

```bash
source venv/bin/activate
pytest -q --ignore=tests/test_multi_store_integration.py    # 617 passed, 1 skipped
```

`test_multi_store_integration.py` drives the app against a live Postgres and
cleans up after itself; it is the only place a second store is real, so run it
whenever you touch store resolution.

Several suites are **structural** — they parse the source with `ast` rather than
executing it, and fail the build on a regression that would otherwise be found in
production:

| Suite | What it refuses to let back in |
|---|---|
| `test_admin_rbac.py` | An admin route with no permission gate |
| `test_vendor_owner_enforcement.py` | A vendor route unclassified, or a mutating one naming no capability |
| `test_vendor_staff.py` | Any read of `staff_clerk_id` / `staff_push_token` |
| `test_ratings_and_notifications.py` | A bare `create_task(send_push_message(...))` |
| `test_review_moderation.py` | A query over `reviews` that forgets `hidden_at` |
| `test_admin_settlement.py` | A refund "retry", or the encrypted payout destination in a payload |
| `test_delivery_replay.py` | A two-valued verdict where the third value is "we don't know" |
| `test_admin_console_frontend.py` | A page with no nav entry, a queue page with no aggregate, a count coerced with `?? 0` |
| `test_route_contract.py` | A route whose shape drifted from what the clients expect |

---

## 🛠️ Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # fill in secrets
docker-compose up -d                 # from the repository root: Postgres + PostGIS, Redis
alembic upgrade b4c7e2a91f30
uvicorn main:app --reload --port 8000
```

### ⚠️ The migration head is gated on purpose

The repository head, `e6b2c8d40f17`, drops the legacy single-staff columns and
**refuses to run** without `ALLOW_STAFF_COLUMN_DROP=true`. Applying it while any
running instance still maps those columns turns every vendor query into
`UndefinedColumn`, and that is a problem in the deployed code rather than in the
data, so no assertion can detect it. It also refuses when it finds a staff grant
that exists only in the old column — the case where a store gained a member
through an older build after the backfill ran, and dropping would silently revoke
them.

The expand/contract sequence is written out in the migration's own docstring.
**Routine deploys should target `a9f4b2c71d63`**, the last ungated revision.

### Useful scripts

| Script | Purpose |
|---|---|
| `scripts/admin_access.py` | Grant, list and revoke console roles; create Clerk test accounts |
| `scripts/clerk_rebind.py` | Audit and repoint `clerk_id`s after a Clerk instance migration |
| `scripts/check_clerk_secret.py` | Diagnose which Clerk instance a secret key belongs to |
| `scripts/check_storage.py` | Verify S3 credentials and bucket policy |
| `scripts/backfill_order_h3.py` | Populate `h3_index_res8` on historic orders |

---

## 📜 Conventions

* **Async sessions everywhere.** For anything contended — accepting an order, moving a wallet, settling bottles — take the row with `select(...).with_for_update()`.
* **`func.now()` for timestamps**, never `datetime.now()` in the application layer, so the database is the single clock.
* **Strict type separation.** `OrderCreate` / `OrderUpdate` / `OrderResponse` are different types. Never expose an internal S3 key — a `@field_validator(mode="after")` swaps it for a presigned URL on the way out.
* **`HTTPException` with an actionable `detail`.** 409 for a business-rule violation (accepting an already-accepted order), 404 rather than 403 where confirming existence would leak.
* **Long or non-critical work goes to ARQ**, never onto the request's event loop.
