# Codebase-wide audit — findings and remediation

A structural review across all five surfaces (BackendAPI, drop-admin, and the
three Expo apps), and what was done about each finding. Everything below is
closed; each has a test that fails the build if it comes back.

**Method.** Cross-referencing all backend endpoints against all four clients;
route-table analysis; component and module reachability; error-handling and
money-handling sweeps; static analysis for undefined names; plus targeted deep
reads of the highest-risk paths. Not a literal line-by-line read of every file.

---

## P1 — Correctness and money

### 1. `routes/sync_routes.py` — dead, and wrong in four ways

`GET /api/sync/rider/orders` was mounted and live. No client called it, and no
test referenced it. Within 52 lines it serialised money as `float`, ran an
unbounded query with no `LIMIT`, used `get_current_user` rather than a rider
dependency (bypassing the KYC gate), and had zero coverage.

**Done:** deleted, with its mount. `PendingSync` and the offline queue already
solve sync-up; this half was never finished.

### 2. Two money serialisation conventions in one API

Newer code returned decimal strings; older code returned JSON numbers. The
places that mattered most were in the second group:

| Site | Why it mattered |
|---|---|
| `pricing_service.as_dict` | **The quote** — the most-read money payload on the platform |
| `deliverer_routes` / `vendor_management_routes` wallet summaries | The balance shown to a rider and to a vendor |
| `payment_routes` | The customer's own payment history |
| `wallet_service.get_wallet_transactions` | The wallet ledger, returned as raw ORM rows |
| `order_snapshot` | **Dispute evidence** — the frozen record an argument is settled from weeks later |
| `vendor_favorites_service` | Reorder totals |
| `delivery_fee_routes` | Per-option fee preview |

A money field annotated `float` on a Pydantic schema was the same defect with no
cast to grep for — Pydantic did the coercion. Six schemas carried them.

**Done:** `utils/money.py` is the one converter (`money_str`, `money_or_none`,
`MoneyField`, `OptionalMoneyField`, `MoneyIn`). Every money field on every schema
uses an alias. `utils/money.ts` added to each of the three apps, mirroring the
console's `lib/utils/format.ts`, and every render site converted —
`formatMoney`, `sumMoney`, `subtractMoney`, `multiplyMoney`, `compareMoney`,
`isZeroMoney`, `moneyRatio`.

**Guard:** `test_money_serialisation.py` — walks every schema and every response
dict in `routes/`, `services/` and `jobs/`. `MONEY_FIELDS` is the specification,
and a name in it that no longer exists anywhere fails too.

### 3. `calculate_revenue_splits` round-tripped money through float

It took floats and returned floats, and every caller wrapped the result straight
back into `Decimal(str(...))` — in the one path that decides what a vendor, a
rider and the platform are each owed.

**Done:** `Decimal` in, `Decimal` out; callers stop unwrapping.

### 4. Four screens re-derived the order total

`OrderCard` and `OrderDetail` in the customer app, and the vendor's order
detail, summed the component lines instead of rendering `total_amount`. Each
formula omitted the bottle deposit and any settled balance, so the card, the
detail screen, the vendor's copy and the M-Pesa message disagreed.

**Done:** all render the server's frozen `total_amount`.

### 5. `PaymentHistory` read fields the API has never sent

The screen declared its own `PaymentRecord` with `total_price`, `order_status`
and a nested `vendor`. The endpoint sends `amount`, `status` and `vendor_name`.
Every row rendered "KSH 0.00" under an unmatched status, and tapping one opened
the *payment's* id as an order id.

**Done:** typed against the endpoint's contract; routes on `order_id`; switches
on payment statuses; renders the receipt and failure reason, both dropped before.

### 6. `NameError` on the customer cancellation path

`cancel_customer_order` called `func.count(...)` with `func` never imported. The
module loaded, the suite passed, and the branch was live: the free-cancellation
allowance defaults to **1**, so a customer cancelling an order that had reached
`preparing`, `ready` or `picked_up` got a 500 instead of a cancellation.

**Done:** imported. **Guard:** `test_no_undefined_names.py` runs pyflakes over
everything that serves a request, failing on undefined names, re-imported names,
and locals computed and never read.

### 7. A rider's drop reason was never validated

`deliverer_service` declared three reason lists and consulted one. Any string
was accepted — a post-pickup drop could be recorded as `out_of_stock`, which
cannot happen to an order already on the bike and counts against the store in
every figure reading `cancellation_reason`.

**Done:** the matrix is enforced per stage. Whose fault it was still decides
whether the order is cancelled or re-offered.

### 8. Payout fees went through `float`

`payout_service` cast the withdrawal minimum and fee with `float()` — the same
defect `payment_service.whole_shillings` exists to prevent one step later, on a
fee an administrator may set to 15.50.

**Done:** `Decimal` throughout; `ProviderBalanceResponse` renders strings.

---

## P2 — Operational blind spots

### 9. The vendor app never reported a fatal crash

`ErrorBoundary.componentDidCatch` carried `// TODO: In production, report to
Sentry/Crashlytics` while `utils/sentry.ts` was initialised and working beside
it. The boundary swallows the crash, so that method is the only place the error
is observable — and this is the surface where a broken screen costs a shop its
orders.

**Done:** wired to `captureError`. **Guard:** `test_crash_reporting.py`, across
all three apps; negative-tested by reverting the fix and confirming it fires.

### 10. Two dead admin endpoints duplicating live figures

`GET /api/admin/revenue` and `GET /api/admin/map/coverage` were implemented and
permissioned, and called by nothing. `/map/bootstrap` already returns the
identical `coverage_report(db)`.

**Done:** both removed, with `/revenue`'s private `_date_filters`. The e2e money
test now asserts against `/finance/summary`, which the console actually calls.

### 11. Two sets of email templates

`email_templates.py` held seven well-built templates with a shared base that
nothing used, while `email_service.py` inlined cruder HTML — and the copies in
use never escaped the recipient's name.

**Done:** `email_service` delegates to the templates; names are escaped.

---

## P3 — Invariants that held by luck

### 12. Only the customer app's route table was enforced

`test_route_contract.py` was scoped to one app. The rider's and vendor's tables
were correct, but nothing kept them so — and the customer app's test exists
because five endpoints were once 404-ing.

**Done:** generalised over all three, with per-app parsers for the two table
shapes. Negative-tested on both new surfaces: an unresolvable path and an
uncalled entry each fail with their own message.

---

## P4 — Hygiene and reachability

### 13. Console pages rendered, then were refused

Twelve `page.tsx` files had no capability check. They painted their heading,
fired their queries, and showed "Couldn't load — 403 Forbidden" — which reads as
a broken console, so the person reports an outage instead of asking for the
capability.

**Done:** `lib/page-access.ts` reads the required capability from
**`nav-config`**, so the gate and the sidebar entry that hides the page cannot
disagree. `NoAccess` names the missing capability. Fails closed on an
unidentifiable caller. **Guard:** two tests in
`test_admin_console_frontend.py`.

Still courtesy, not access control — `require_admin(...)` remains the only check
that decides anything.

### 14. Dead code

Removed: `PercentageBar.tsx`, `use-theme-color.ts`, `constants/theme.ts`
(orphaned by the previous), `BackButton.tsx` (vendor), `types/components.ts`
(rider and vendor), `types/models.ts` (vendor); `check_orders.py`, `test_api.py`,
`test_db.py`, `test_live_api.py` — two of which patched
`dependencies/auth_dependencies.py` on disk to bypass auth; `db/init_db.py` and
`db.session.create_table`, a `Base.metadata.create_all` that would build a
database no migration had ever run against; `core/__init_.py`, a zero-byte file
whose name was a typo; `calculate_cart_payload`; `cache_delete`; ~60 unused
imports and four duplicate ones.

`settlement_service.cash_float_required` was unused while `deliverer_service`
re-derived it inline twice — once when checking whether a rider could accept,
once when debiting on delivery. It is now the single definition both call.

---

## What was not covered, and now is

The six areas listed here as out of scope were subsequently worked through in
full. Each is closed, each has a guard, and each turned up defects — several
worse than anything in the original report, because these were the areas nothing
had been asked to look at.

### 1. WebSocket lifecycle and reconnect — `test_websocket_contract.py` (22)

Four defects, every one silent from both ends: the socket either never opened or
stopped delivering while still reporting `OPEN`.

- **The vendor's live-tracking map had never worked.** Its socket omitted
  `?token=`, and `_authenticate_ws` closes a tokenless socket with 1008 before
  the first frame. The reconnect loop then ran its five attempts against a
  refusal and gave up, so a vendor watching a delivery saw the map's fallback
  position and nothing else — for every order, always. The customer app hit the
  identical bug and fixed it in `useRiderTracking`; nothing carried that across.
  Replaced by `hooks/useOrderTracking.ts`.
- **Two answers to "where is the socket".** `useWebSocket` split a REST path on
  `/api/` and called `.replace('http', 'ws')` unanchored. Both halves fail
  *open* to something plausible and wrong. One `WS_BASE_URL` per app now.
- **No half-open detection anywhere.** A cell handover leaves `readyState` at
  `OPEN` with nothing getting through. The server already sent heartbeats; no
  client measured the silence.
- **A permanent give-up**, plus a mount-guard declared *after* the connect
  effect — so a remount ran `connect()` with `mountedRef` still `false` from the
  previous teardown and opened no socket at all.

### 2. The order state machine — `test_order_state_machine.py` (54)

`VALID_TRANSITIONS` existed and was not the state machine. Fifteen writers
assigned `order.order_status` directly; two consulted the table. Worse, the
table described an idealised flow the platform does not have — a rider marking
pickup straight from `accepted` because the store handed over before tapping
"ready", a post-pickup drop, the cash-float sweep releasing to `unassigned`: all
routine, none of them legal by the table.

That is the worst of the two options. A table nobody reads is dead code; a table
that contradicts the code is documentation that lies. The table now describes
what happens, and `apply_status_transition` is the only way to change a status.

### 3. N+1 and index coverage — `test_query_shape.py` (6)

No request path issues a query per row. `Orders` gained three indexes
(`d4a8f2c61b93`): its most-filtered column, `order_status`, had no index that
could lead with it, so the re-dispatch sweep and the auto-cancel job scanned the
whole order history on a schedule, and a rider's committed cash float — seven
call sites, on every wallet summary — read every order that rider had ever
delivered to count the handful still open. The two float indexes are partial on
`payment_method = 'cash'`.

### 4. Accessibility — `test_accessibility.py` (11)

52 icon-only controls across the three apps announced as "button" and nothing
else: every password toggle, every sheet's close button, all three support
threads' send button, and five per row on the vendor's product list — including
the one that withdraws a product from the catalogue.

### 5. Auth and session edge cases — `test_session_teardown.py` (11)

- **A rider signing out cleared no push token at all.** `DELETE
  /api/auth/push-token` defaults `app_type` to `customer`; the rider app sent
  none, so the endpoint looked for a `User` row that riders do not have, cleared
  nothing, committed, and answered `200`. Riders share devices more than anyone
  on this platform: the rider who signed out kept receiving delivery offers, and
  so did the next one to sign in. The vendor app had met the same default and
  fixed its own copy.
- **The vendor's remembered store survived a 401 sign-out.** `activeStoreId` is
  persisted separately, so `queryClient.clear()` never touched it, and the
  sign-out *handler* that cleared it is the path nobody takes. The next account
  on the device signed in and then 404'd on every scoped request, which reads as
  the platform being down.
- **Three vendor paths were built outside the route table** — including
  `profile-status`, the app's first call on startup. They were invisible to
  `test_no_screen_builds_a_backend_path_inline` because its pattern required a
  quote immediately before `/api/`, and an interpolated base URL puts a `}`
  there. The pattern is widened, which is what found the other two.

### 6. `dispatch_policy` in `Decimal` end to end

The delivery-fee schedule (`base + per_km × distance`) was the one arithmetic
path still computing in float and quantizing at the boundary. Now `Decimal`
throughout. Distance stays a `float` deliberately — it is a measurement off
PostGIS, not money — and becomes `Decimal` at the moment it meets a shilling
rate.

### Found along the way

Three defects outside all six areas, turned up by the work rather than sought:

- **`DispatchPolicy` says "read through the accessors, never directly", and four
  production modules read the dataclass defaults.** Discovery used the shipped
  2 km while checkout used the configured radius, so raising
  `retail_max_distance_km` on the console widened what the platform would
  deliver and not what a customer could *find*; the cart quoted the shipped
  wholesale minimum beside an enforcement of the configured one.
- **A vendor could set their own delivery radius.** `Vendor.delivery_radius` was
  writable on the profile PATCH with a stepper in the vendor app, and nothing on
  the dispatch path has ever read it — so the control decided no deliveries. It
  was not inert, though: the vendor's map drew its circle from it, and the
  customer's product page derived the delivery ETA from it, *from the radius
  rather than the distance*, so every customer of that store saw the time to the
  edge of the catchment. A store setting 15 km quoted "45 min – 1.5 hrs" to the
  flat upstairs. The one thing the control could achieve was making its own shop
  look slower. `GET /storefront` now reports the platform's radius; the ETA comes
  from `estimated_minutes`, which the screen was already fetching and ignoring.

  Following that through, the radius was then **set to its agreed values and
  made single-sourced**: 2.5 km retail, 15 km wholesale. Retail moving from 2
  needed a retirement migration (`c7d2e94a6f18`), because a stored row outranks
  a shipped default permanently and silently — changing the source alone leaves
  every database holding a row at the old figure with nothing to say why. Both
  radii changed from `int` to a new `decimal` kind, since the `int` coercer is
  `int(value)` and would have truncated 2.5 to 2 without a word. The tripwire
  that catches the *next* default change was itself only reading the first
  retirement migration, so it would not have seen this one; it now reads every
  table in the directory. `Vendor.delivery_radius` is dropped in the same
  migration, and the rider app — which held the figure three more times, as a
  hardcoded 2 km circle, a map span "tuned to always show the full 2KM radius
  circle", and a sentence promising it — now reads `operation_radius_km` from
  its profile.
- **`MiniOrderCard` rendered a mock-up on the live tracking map** — order
  `#57v8V8V585J390-248HVQ08`, "2:00pm Feb 25, 2024", "3 items", "Ksh 300", a
  rider called John Doe — beside the customer's real order, with a `data` prop
  declared and read nowhere, and two buttons offering to call and message the
  rider that had no `onPress` at all.
