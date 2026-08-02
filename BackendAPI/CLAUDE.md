# Drop Backend API - AI Developer Guide

## 🎯 Architecture & Business Workflow
The Backend API is the central nervous system for the Drop platform. It enforces business rules, manages state transitions, and brokers communication between Customers, Vendors, and Riders.

Key Business Workflows:
1. **Order State Machine**: Handled primarily in `order_service.py`. The strict transition is: `pending` → `unassigned` (paid) → `accepted` → `preparing` → `ready` → `picked_up` → `delivered`.
   - **Deviations**: `pending_review` (if rider flags a bottle mismatch), `mismatch_pending` (vendor flags a quantity issue).
2. **Dispatch & Trip Radar**: 
   - `unassigned` orders trigger a search for riders.
   - If an `in_house` rider belonging to the vendor is available, they are assigned first.
   - Otherwise, a spatial query (PostGIS `ST_DWithin`) finds nearby gig riders and broadcasts the order via WebSockets (`broadcast_to_riders`).
3. **Reconciliation & Payouts**: 
   - When an order reaches `delivered`, `update_delivery_status` triggers `calculate_revenue_splits`. 
   - Atomic transactions create `WalletTransaction` entries for both the Rider and the Vendor, deducting the platform's cut.
4. **S3 & KYC**: 
   - Direct image URLs are NEVER stored in the database. 
   - The database stores S3 keys. 
   - Pydantic models (e.g. `DelivererResponse`, `OrderResponse`) use `@field_validator(mode='after')` to intercept these keys and inject 15-minute expiring presigned S3 URLs before returning JSON to the client.

## 🏗️ Technical Stack
- **Framework**: FastAPI (async).
- **ORM**: SQLAlchemy 2.0 (asyncio).
- **Schema Validation**: Pydantic v2.
- **Background Tasks**: ARQ (Async Redis Queue).

## 💰 Order Pricing — one function, no exceptions

`services/pricing_service.py::compute_order_quote` is the **single** source of
truth for what an order costs. It returns every line item as `Decimal` and
quantizes `total` to whole shillings.

- `POST /api/cart/quote` serves that quote to the client, which renders it verbatim.
- `POST /api/cart/mpesa_payment` pushes `quote.stk_amount` to Safaricom.
- `order_service.create_order(..., quote=quote)` writes that same `quote.total`.

The amount charged and the amount recorded are therefore equal by construction.
**Never re-derive a total anywhere else** — four competing implementations of this
arithmetic is what made the M-Pesa callback's amount cross-check reject every
retail payment. Fee constants (`RETAIL_SERVICE_FEE_KSH`, `SURGE_FEE_KSH`, …) live
in `order_service.py` and are read through `pricing_service`; do not inline them.

## 🔑 Authentication

**Identity comes from the token, never from the request body.** `create_user`,
`create_vendor` and `create_rider` all overwrite `clerk_id` with `user["sub"]`.
They previously read it from the posted JSON with no auth dependency at all, so
anyone could bind a vendor row to somebody else's Clerk subject.

`core/security.py` verifies with the JWKS pinned to RS256, plus audience and
issuer — a missing Clerk env var makes python-jose skip those checks silently, so
the module refuses to start outside development without them. An unknown `kid`
forces one cache refresh (rate-limited, single-flight) before the token is
rejected: that is how signing-key rotation is survived, and without it a rotation
locked out every user for up to an hour.

Sockets are the one place a token is presented once and then trusted for hours.
Every socket loop calls `_close_if_token_expired`, closing with 1008 so the client
reconnects with a fresh token. Webhooks that mutate money or order state
(`sms_routes`, the M-Pesa payout and reversal callbacks) need a shared secret;
IP allow-listing alone is not a guard while `ProxyHeadersMiddleware` trusts every
forwarding host.

## 🏪 A `Vendor` row is a store, not an account

One Clerk identity may own several — `GET /api/vendor/stores` exists to list
them. Every vendor endpoint therefore resolves an **active store** through
`dependencies.auth_dependencies.get_active_store` (owner or staff) or
`get_owned_store` (owner only), both of which read an `X-Store-Id` header,
validate it against the caller's own stores, and fall back to a deterministic
`ORDER BY created_at ASC LIMIT 1`. A store the caller does not own is a **404**,
not a 403: confirming an id exists is itself a leak.

- Routes take the resolved `Vendor` row. Do not call
  `vendor_management_service.get_vendor_by_clerk_id` from a route — its fallback
  is `clerk_id = … OR staff_clerk_id = …` with no store id, which is exactly the
  ambiguity the dependency removes.
- **Never `scalar_one_or_none()` on a vendor lookup.** It raises
  `MultipleResultsFound` on the second store. `profile-status` and `push-token`
  did, and the vendor app calls both before anything else — so opening a branch
  turned app startup into a 500.
- `get_owned_store` checks ownership against the *resolved row*, not merely that
  the caller owns something. Someone can own store A and be staff of store B;
  composing an owner gate with a store resolver would let them act on B.
- `tests/test_multi_store_integration.py` is the only place a second store is
  real — every vendor in production owns one, so nothing else exercises this. It
  drives the app against a live Postgres and cleans up after itself.

## 👥 Staff are `Vendor_Staff` rows, with capabilities

`Vendor.staff_clerk_id` held one id and was UNIQUE **platform-wide**: a store
could have one staff member, adding a second silently replaced the first, and one
person could work for exactly one store on the whole platform. Access was
all-or-nothing — `get_current_vendor` admitted staff to everything that was not
owner-only, so handing someone the till handed them the catalogue, the bottle
ledger and the wallet balance.

- **Never read `staff_clerk_id` or `staff_push_token`.** They survive only so an
  application rollback does not lose anybody's access (expand/contract), and
  `tests/test_vendor_staff.py` tokenizes every module and fails the build if
  either is read. Use `services/vendor_staff_service.is_store_member` /
  `staffed_vendor_ids`, or take a `StoreAccess` from the dependency.
- Four capabilities: `manage_orders`, `manage_products`, `manage_bottles`,
  `view_finances`. Gate every **mutating** route with
  `require_permission("…")`; reads that any member may make take
  `get_active_store`. Refusals are
  `{"type": "permission_required", "permission": …}`.
- `view_finances` is **not** granted by default. Seeing the store's balance is a
  decision the owner makes, not one inherited from a schema that could not
  express the question.
- Owners are not rows in this table. `StoreAccess.may()` short-circuits for them,
  and `GET /profile` returns the full capability list so the app checks one thing
  rather than "is owner, or has permission".
- Push tokens live on the membership row, so a store with several staff reaches
  all of them. `Vendor.staff_push_token` addressed whoever registered last.
- Inviting by email must answer **identically** whether or not that address has a
  Drop account. The old endpoint's 404-vs-200 let any vendor test whether an
  arbitrary email — a competitor's, a customer's — is registered here.

Staff are a real trust boundary, not a display role. They may run the shop floor;
they may not redefine the business or move its money. `payout_service` and
`wallet_service.resolve_wallet_owner` both match on `clerk_id` alone —
`payout_service` did not, and a shop assistant could withdraw the store's balance
to their own phone. `tests/test_vendor_owner_enforcement.py` fails the build when
a new vendor route is added without being classified, or when a mutating route
names no capability.

## 🔒 Authorisation on order-scoped endpoints

Authenticating a token proves *who* is calling; it says nothing about whether they
have any relationship to the order named in the URL. Every order-scoped endpoint —
REST **and** WebSocket — must call
`dependencies.auth_dependencies.authorise_order_access` (or `owns_entity` for
entity-scoped sockets). Skipping it exposes one customer's live delivery location
to any other signed-in account.

## 🗺️ Google Maps web services go through the backend

The six keys shipped in the mobile apps are restricted to the **Maps SDK** for one
package/bundle each — that restriction is the only thing that makes an embedded key
safe, and it also means those keys cannot call Directions, Places, or Geocoding.

`routes/maps_routes.py` owns every Google web-service call, using a single
IP-restricted `GOOGLE_MAPS_SERVER_API_KEY`. It authenticates, rate-limits, caches in
Redis on coordinates rounded to ~11 m, reduces the response to what the client
draws, and never forwards Google's `error_message` (it names the project and
sometimes the key). Add new services there, not in the apps — see
`docs/maps-architecture.md`.

## 💵 Wallets, cash float and payouts

`wallet_balance` is the **single spendable balance** for riders and vendors.
`available_for_withdrawal = wallet_balance − committed_cash_float`, and
`services/settlement_service.py` owns that arithmetic — never re-derive it.
Withdrawal eligibility used to come from a separate derived earnings sum while
payouts debited nothing, so the same money could be withdrawn *and* spent as
cash-order float.

Move balances only through `wallet_service.apply_wallet_delta`, which mutates the
balance and appends the signed `WalletTransaction` in one call. Money is `Decimal`,
never `float`. See `docs/cash-settlement.md`.

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
`create_task(send_push_message(...))` reappears. Pushes used to be fired several
statements *before* the commit that made the change real, so a rolled-back order
still told the customer it was confirmed.

`expo_push_service` retries only what retrying fixes — transport failures, 5xx
and 429. A 4xx is a refusal. The retry decorator previously wrapped a body that
caught every exception, so it never ran and one 502 dropped the batch silently.

`user_type` arrives as a query parameter and is validated against
`VALID_USER_TYPES`; it must be passed on **every** notification call, reads and
writes alike, because `Notification.user_id` holds ids from three tables and
carries no foreign key.

## ⭐ Ratings

Aggregation is incremental. `Vendors`/`Deliverers` carry `rating_count` and
`rating_sum`; `review_service` locks the target `FOR UPDATE`, folds the new
rating in, and derives `rating` from the two. Never recompute with `AVG()` over
the reviews table — that is unbounded work on exactly the busiest targets.

A repeat review for the same (customer, order, target) is an **edit**, not an
error: `uq_customer_order_target_review` would otherwise turn the client's retry
into a 500. Editing moves `rating_sum` and leaves `rating_count` alone.

`is_rated` on an order means *every* ratable party has been rated — the vendor,
plus the rider when one was assigned. `ReviewOut` must never carry
`customer_clerk_id`: the target-review endpoint is unauthenticated.

## ⚙️ Background jobs

ARQ runs as its **own process** (`arq worker.WorkerSettings`), never inside the
API — see `BackendAPI/README.md`. Every sweep must claim rows with
`with_for_update(skip_locked=True)`, re-check state under the lock, and commit
per item inside a `try/except`, so it stays correct with several workers running
and one bad row cannot discard the batch.

## 📦 Stock

`Product.low_stock_threshold` is per product (0 disables the warning) and
`low_stock_notified_at` latches the notification so a vendor is told once per
crossing, not once per unit sold below the line — restocking clears it, in both
`update_product` and `_restore_order_stock`. The threshold used to be a hardcoded
`<= 5` for every product on the platform, firing on every subsequent order, and
pointing at a screen that does not exist.

## 📜 Coding Guidelines

### 1. Database Interactions
- Use asynchronous SQLAlchemy sessions (`AsyncSession`).
- **Idempotency & Concurrency**: For critical operations like Accepting an Order (`AcceptDelivery`) or Wallet updates, use `select(...).with_for_update()` to lock the row and prevent race conditions.
- Always use `func.now()` for `updated_at` columns, never `datetime.now()` in the application layer, to ensure the DB handles timestamp consistency.

### 2. API Routing
- Group endpoints logically in `routes/`.
- Use the standard `get_db_session` dependency.
- Use `get_current_user` or entity-specific authenticators (`get_current_vendor`, `get_current_deliverer`) to enforce RBAC.

### 3. Pydantic Models
- Base models and DB schemas live in `schemas/`.
- Ensure strict type separation between internal DB representation and external API responses (e.g., `OrderCreate`, `OrderUpdate`, `OrderResponse`).
- Do not expose sensitive data (like plain text passwords or internal S3 keys). Use field validators for transformation.

### 4. Background Tasks
- Long-running or non-critical tasks (like sending Push Notifications or resolving timed-out bottle disputes) must be offloaded to ARQ in `worker.py`. 
- Do not block the main FastAPI event loop.

### 5. Error Handling
- Raise `HTTPException` with clear, actionable `detail` messages.
- For business logic violations (e.g., trying to accept an already-accepted order), return 409 Conflict.
- For unauthorized access, return 401 or 403.
