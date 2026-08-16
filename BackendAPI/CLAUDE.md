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

## 💷 How money leaves this API

`Decimal` through the service layer, a **decimal string** on the wire. Never a
JSON number: once a balance has been through a double it is no longer the figure
the ledger holds, and every one of the four clients would have to parse it back.

There is one converter, `utils/money.py`:

- `money_str(value)` — a figure as the string a client renders. `None` → `"0.00"`.
- `money_or_none(value)` — the same where absent and zero are different facts.
- `MoneyField` / `OptionalMoneyField` — the Pydantic aliases. **Every** money
  field on every schema is one of these two.
- `MoneyIn` — a money *argument*. Pricing helpers take it and return `Decimal`.

Two conventions ran side by side for a long time and the older one was in the
places that mattered most: `pricing_service.as_dict` (the quote — the single
most-read money payload on the platform), the wallet summaries shown to a rider
and a vendor, `payment_routes` (the customer's own payment history), the wallet
ledger, and `order_snapshot`, which is the frozen record a delivery dispute is
settled from weeks later.

A money field annotated `float` on a schema is the same defect with nothing to
grep for — Pydantic does the coercion, so `wallet_balance: float | None = 0.0`
survived on three schemas while the `float(...)` calls beside it were being
found and argued about.

`tests/test_money_serialisation.py` walks every schema and every response dict
in `routes/`, `services/` and `jobs/`. `MONEY_FIELDS` in that file is the
specification — adding a money field means adding it there, and a name in the
list that no longer exists anywhere fails the build too, so it cannot rot into a
list of fields nobody has.

`calculate_revenue_splits` takes and returns `Decimal`. It took floats and
returned floats, and every caller wrapped the result straight back into
`Decimal(str(...))` — a float round trip in the middle of the one path that
decides what a vendor, a rider and the platform are each owed.

`dispatch_policy` still computes the *delivery fee schedule* in float
(`base + per_km × distance`) and quantizes at the boundary. That is safe — the
result is rounded to two places before anything is charged or persisted — but it
is the one arithmetic path not yet `Decimal` end to end.

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

**Every withdrawal path calls `settlement_service.assert_withdrawable`**, and
takes its minimum and fee from `settlement_service.withdrawal_terms`. There are
two paths — `payout_service.request_payout` and
`wallet_service.initiate_wallet_withdrawal` — and they disagreed on all three:
the second compared against the raw balance, so a rider could withdraw the float
backing their open cash orders and then deliver into arrears the platform cannot
collect. It also carried its own minimum and waived the fee on the *balance held*
rather than the amount withdrawn. `tests/test_withdrawal_unification.py` walks
each withdrawal function and fails the build on a missing `assert_withdrawable`
or a re-introduced literal.

Move balances only through `wallet_service.apply_wallet_delta`, which mutates the
balance and appends the signed `WalletTransaction` in one call. Money is `Decimal`,
never `float`. A bare `wallet_balance +=` fails the build, and so does an assigned
arithmetic expression — `tests/test_money_movement_integrity.py` walks every
function in `services/` and `routes/`. See `docs/cash-settlement.md`.

### Which balance, and how much actually leaves

Two things a Clerk id cannot tell you, both discovered on the outbound path:

- **Which row.** `WalletTransactions.user_id` is a Clerk id; one identity may own
  several stores, each with its own `wallet_balance`. Every callback arrives
  minutes after the request that raised it and re-resolved the owner by clerk id
  with an unordered `.first()` — so a top-up paid into the second branch credited
  the first, and a failed withdrawal from the second was refunded to the first.
  Two real balances wrong by the same amount in opposite directions, with nothing
  in either ledger to explain it. `wallet_owner_id` records the row the money
  came off; resolve with `_locked_wallet_owner`, never by clerk id.
- **How much.** Every Daraja amount field is whole shillings, and the code sent
  `int(amount)`. `payout_transaction_fee` is a `Platform_Settings` row: set it to
  15.50 and a KSH 1,000 withdrawal debited 1,000, recorded a fee of 15.50 and put
  **984** on the phone — the missing 50 cents in no ledger and reported to
  nobody. `payment_service.whole_shillings` refuses a fraction rather than
  rounding one, and `initiate_wallet_withdrawal` re-derives the fee from the
  rounded disbursement so `debited == disbursed + retained` exactly.

### The B2C request body

Two fields, both wrong in ways Daraja never reports:

- **`Occassion`, with two s's.** That is Safaricom's spelling in their v3
  request body and parameter table. Daraja drops an unrecognised key silently,
  so the correct English spelling meant `payout_id` had never reached a single
  disbursement — the field that reconciles an M-Pesa statement line against a
  payout row. `B2C_OCCASION_KEY` names it so it is not "fixed" back. The
  Reversal API documents the single-s form; they are inconsistent, and each
  call site follows its own documentation.
- **`OriginatorConversationID`** is required and is the double-disbursement
  guard. It was absent, so the gateway could not deduplicate a retry — on the
  outbound path, where a duplicate pays a rider twice. It is `payout_id`, and
  it must be stable across retries of the same disbursement or it does nothing.

`tests/test_daraja_contract.py` asserts the serialised request, not the source.

### Which Daraja, not which ENV

`is_safaricom_ip` reads `MPESA_BASE_URL`. `SAFARICOM_IP_RANGES` holds
*production* addresses, so applying it to sandbox callbacks rejects all of them
— after the shared secret has already matched, invisibly from both ends. Gating
on the base URL is what lets a pre-launch deployment run `ENV=production`, with
every fail-closed gate active, while still integrated against sandbox.

It stays defence in depth: `ProxyHeadersMiddleware(trusted_hosts=["*"])` means
the apparent client IP comes from a header anyone can set, so the secret is the
guard and this is a second opinion.

### Where a push comes back to

An STK push names its own `CallBackURL` **in the request body**. There is no
registration step and nothing in the Daraja portal decides it, which makes the
URL a per-caller choice — and it was a module-level
`os.getenv("MPESA_CALLBACK_URL")` that both callers inherited.

The two are settled by different handlers, because a `CheckoutRequestID`
resolves against `Orders` for a checkout and against `WalletTransactions` for a
top-up. So every wallet top-up's confirmation went to `/api/cart/mpesa/callback`,
which found no order and returned **400** — a retry instruction to Safaricom,
not an acknowledgement. The customer paid, the row stayed `pending` for ever,
and `handle_mpesa_topup_callback` had never been called by anybody.

- `initiate_stk_push(..., *, callback_url)` is **keyword-only and required**. A
  default is precisely what re-adopts one caller's endpoint for the next.
- Resolve with `order_callback_url()` / `topup_callback_url()`. They return
  `""` when unconfigured and the push is refused: collecting money with nowhere
  for the confirmation to land is the defect, and declining is better.
- `topup_callback_url()` derives from the order URL by swapping the path and
  **keeping the query**, which is what carries `?secret=`. A second required
  variable would have meant the fix did nothing until somebody set it.
- `query_stk_status` is the one implementation of "how did this push end?",
  shared by the client's poll and the reconciliation. A query answers with a
  result code and **no receipt and no amount**.
- `jobs/reconcile_pending_topups.py` recovers the residue. It settles only what
  Safaricom positively resolves — a query that cannot answer is not a reason to
  credit a wallet *or* to write a payment off — and escalates to Sentry past
  `topup_reconcile_max_age_hours` rather than writing off a payment nobody can
  confirm.

`tests/test_stk_callback_routing.py` is the specification.

`get_access_token` caches the Daraja token until shortly before it expires and
raises `MpesaError` rather than returning `None`. It minted a fresh token per
call — two round trips per payment — and a throttled mint returned `None`, which
went on the wire as the literal header `Authorization: Bearer None`. Every
initiator catches `MpesaError` and returns the same shape as an in-flight
failure, because the checkout route reads a missing `CheckoutRequestID` as
"nothing was charged" and the withdrawal path refunds on a falsy `success`.

STK timestamps are **EAT**, not naive local time. Safaricom validates the
timestamp against its own clock and the password is the base64 of
`shortcode + passkey + timestamp`, so both must come from one instant in EAT;
`datetime.now()` in a container is UTC, three hours behind.

## 🍶 Deposits, debt, and the three bottle relationships

Three separate obligations, three owners, and none of them may be re-derived:

| Relationship | Owner |
|---|---|
| Rider holds a vendor's empties | `bottle_ledger_service` |
| Rider's aggregate debt to a vendor | `admin_bottle_service` |
| **Customer paid a deposit and holds a bottle** | `customer_bottle_service` |

`Users.bottle_deposit_balance` and `Users.bottles_held` are two views of one
fact and move only through `customer_bottle_service._apply` — the same discipline
`_apply_movement` enforces on the rider side, and for the same reason. The
deposit was previously folded into `vendor_net` and forgotten, so the platform
could not say what it owed and had no way to give one back.

**`Users.debt_balance` is settleable, not a block.** A cancellation penalty or an
approved staircase charge is collected on the customer's next order as
`quote.debt_settlement`, cleared by `create_order`, and restored by every
cancellation path. Only a balance at or above `max_customer_debt_before_block`
refuses checkout. It was previously incremented in two places and decremented
nowhere while any positive value returned 402, so one late cancellation locked an
account out of the platform permanently over KSH 50.

## 🔀 An order's status moves through one function

`order_service.apply_status_transition` is the only thing that assigns
`order.order_status`. It refuses a move out of a terminal state with a 409 and a
sentence about the order, refuses anything backwards, and treats a repeat of the
current status as success — two staff on two devices is not a conflict.

`VALID_TRANSITIONS` used to exist beside fifteen writers, two of which consulted
it. Worse, it described an *idealised* flow this platform does not have: a rider
marking pickup straight from `accepted` because the store handed the order over
before tapping "ready", a post-pickup drop, the cash-float sweep releasing back
to `unassigned`. All routine; none of them legal by the table.

That is the worse of the two failure modes. A table nobody consults is dead
code, and can be deleted. A table that contradicts the code is documentation
that lies — the next person either trusts it about their own feature, or
"corrects" the thirteen non-conforming paths to match it and breaks the rider
flow. `tests/test_order_state_machine.py` walks `routes/`, `services/` and
`jobs/` and fails the build on a direct assignment.

## 📏 `DispatchPolicy`: accessors, never the dataclass defaults

`RETAIL_MAX_DISTANCE_KM` is the shipped default. `retail_max_distance_km()`
reads the `Platform_Settings` row. Reading the attribute is invisible — right
value, right type, passing tests — right up until an administrator moves the
setting, at which point two halves of the platform enforce different numbers for
the same rule.

Both halves existed. `vendor_service._search_bounds` used the shipped 2 km while
checkout used the configured radius, so raising `retail_max_distance_km` widened
what the platform would *deliver* and not what a customer could *find* — the
store that had just come into range stayed invisible. `cart_routes` quoted the
shipped wholesale minimum on the cart beside an enforcement of the configured
one. `tests/test_delivery_fee.py` fails the build on a direct read from
`routes/`, `services/` or `jobs/`.

The registration radii are exempt and documented as such on the dataclass: where
a rider registers to serve is a different question from how far one order may
travel, and they have no settings row on purpose.

### The radii themselves: 2.5 km retail, 15 km wholesale

One figure per vendor type, and it is every use at once — what discovery
searches, what checkout enforces, what the rider search covers, and what each
app draws on a map. `retail_max_distance_km` moved from 2 to 2.5 in
`c7d2e94a6f18`, which had to be a **retirement migration**: a stored row
outranks a shipped default permanently and silently, so changing the source
alone would have left every database holding a row at 2 with nothing to say why.
The migration deletes rows still holding the superseded 2 and leaves any other
value alone, exactly as `b2f9c14e7a35` established.

Both are `decimal`, not `int`. `int` coerces with `int(value)` — a truncation,
not a refusal — so 2.5 entered against an `int` spec would have been stored as
2 without a word.

`Vendor.delivery_radius` is gone in the same migration. It was vendor-writable,
read by no dispatch path, and rendered on two screens as though it were the
catchment.

## ↩️ Cancelling an order is seven things, not one

`order_service.revert_order_side_effects` is the only implementation: stock, the
customer's wallet credit, the settled debt, the bottle deposit, the welcome
offer, the refund flag and `commission_lost`. **Every reversal path calls it** —
customer cancel, vendor cancel, vendor reject, rider cancel, and both sweeps.

Six call sites each remembering a different subset is how `commission_lost` came
to be null on precisely the most common kind of cancellation, the vendor's own
reject. `tests/test_remediation_structural.py` is parametrised over all six.

## 📦 Products are withdrawn, never deleted

`Order_Items.product_id` is a foreign key with no `ondelete`, so deleting a
product that has ever sold is a foreign-key violation the vendor sees as a bare
500 — and relaxing the constraint would be worse, because
`bottle_ledger_service` reads `item.product.capacity` and an order item with no
product silently contributes no bottle debt.

`delete_product` sets `Products.deleted_at`. Every catalogue read carries
`product_service.live_product()`; an AST test counts filters against
`select(Product)` calls per function and fails the build on a shortfall.

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

**Moderation is `hidden_at`, and every read filters on it.** A delete would lose
that the review existed, release `uq_customer_order_target_review` so the
customer can simply leave another, and strand the target's counters on a row
that is gone. `admin_review_service.set_hidden` rebuilds the target's
`rating_count`/`rating_sum` from the visible rows in the same transaction — a
one-star review taken out of the list and left in the average is moderation
theatre. That rebuild is the *one* sanctioned `SUM()` over `reviews`: it is a
single indexed aggregate for one target on a rare admin action, not the per-write
recomputation the incremental path exists to avoid. A resubmit of a hidden review
is a 409, not an edit; folding its rating back in would be a way round moderation.

## ⚙️ Background jobs

ARQ runs as its **own process** (`arq worker.WorkerSettings`), never inside the
API — see `BackendAPI/README.md`. Every sweep must claim rows with
`with_for_update(skip_locked=True)`, re-check state under the lock, and commit
per item inside a `try/except`, so it stays correct with several workers running
and one bad row cannot discard the batch.

## 🏬 Is this store trading? — `vendor_availability`

Five separate reasons a shop may not be taking orders, and `is_online` is one of
them. It was the only one anything read, and **nothing on the ordering path read
even that**: the vendor app shipped a swipe control wired to `is_online`, so a
vendor could swipe their store closed, watch the toggle turn grey, and keep
receiving orders. `shift_start`/`shift_end` were in the same position — on every
store since the first migration, rendered on the console, enforced nowhere. A
control that reaches the user but not the platform is worse than no control,
because the person operating it believes it worked.

`services/vendor_availability.py` is the single decision, in the same sense
`pricing_service` owns the total and `cod_policy` owns the cash question.

| Column | Who sets it | What it means |
|---|---|---|
| `is_active` | administrator | Suspended. Outranks everything below. |
| `paused_until` / `pause_reason` | store (`manage_orders`) | A pause that ends by itself. |
| `is_online` | store (owner) | The indefinite "we are shut" switch. |
| `shift_start` / `shift_end` | store (owner) | Opening hours; enforced only when `vendor_hours_enforced` is on. |
| `accepts_cash` | store (owner) | Read through `cod_policy`, never off the column. |
| `min_order_value` | store (owner) | Checked on `product_subtotal`, inside `validate_quote`. |

- **`evaluate` is synchronous** against the cached configuration snapshot;
  `store_state` is the async wrapper that refreshes first. A discovery query
  returning twenty stores evaluates twenty states and makes no extra round trips.
- **`annotate` stamps, it never filters.** A closed store must appear and be
  marked closed. All seven reads in `vendor_service` go through `_annotated`,
  and a test walks them.
- **The minimum lives in `validate_quote`**, so it reaches the quote, the
  pre-push validation and `create_order`'s locked re-check from one call site.
  Measured on the goods: a minimum counting delivery would move with the
  customer's address.
- **These controls fail open.** An unreadable `paused_until` or
  `min_order_value` is no pause and no minimum. The platform's own gates fail
  closed; a shop's optional courtesy must not be able to 500 a checkout.
- **Every bound is a settings row** (`storefront` group), and
  `vendor_may_decline_cash` / `vendor_hours_enforced` are live overrides — a
  stored decline stops being honoured the moment the platform withdraws the
  right to make it, rather than persisting with nothing on any screen to explain
  it.
- `Vendor.preferred_payment_method` is the **payout destination**, despite the
  name. Not a payment method the store accepts.

## 📈 Acquisition cost — `admin_growth_service`

Two halves, and they never merge silently.

`Order.welcome_discount` is real acquisition spend, recorded on every order,
and it was summed nowhere. Posters, a branded boda, ads, referrals and an
agent's weekend are equally real and are not in this database at all —
`Acquisition_Spend` holds those, entered per (month, channel), upserted so a
corrected invoice replaces rather than doubles, `settings.manage` to write, and
audited both ways.

`measured` / `entered` / `blended` come back separately with
`has_entered_spend`. A CAC assembled from the measured half alone is precise,
confident, and typically wrong by an order of magnitude **in the direction that
makes acquisition look cheap** — every figure in it real, on a screen that
looks authoritative, and somebody spends against it.

- **`unattributed_spend`** is spend in months that acquired nobody. Summing per
  cohort drops it entirely, because such a month has no cohort — and that is
  the single most important month on the screen.
- **A cohort is a first *delivered* order**, and the `MIN()` runs over all
  history. Computed inside the window it would re-acquire a long-standing
  customer into this month, inventing new customers out of loyal ones.
- **Contribution is `platform_net`**, frozen on the order. Never re-derive it
  from today's commission settings.
- **Nothing is projected**, and `median_payback_month` counts only cohorts that
  have actually paid back. Averaging in the young ones reports a payback faster
  than any cohort has achieved.

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
