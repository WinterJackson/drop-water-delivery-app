# Phase 1 Implementation Plan — Backend (customer surface) + Customer App

Companion to [phase1-backend-customer-audit.md](./phase1-backend-customer-audit.md). Finding IDs (B1, H4, M12 …) refer to that document.

**Sequencing principle:** the money path is broken in a way that makes every other fix hard to verify, so 1a lands first and everything else builds on it. Phases 1a → 1e are dependency-ordered; within a phase, items are independent unless noted.

**Effort key:** S ≈ under half a day · M ≈ 1–2 days · L ≈ 3+ days.

> **Status: phases 1a–1e are implemented and verified** (145 backend tests passing,
> `tsc --noEmit` clean). See the *Phase 2 resolution status* table in the audit
> document for the per-finding ledger. The only item left open is H11's operational
> half: rotating the Google API key that remains in git history and restricting the
> Maps key in `app.json` — both require your decision.

---

## Phase 1a — Blocking: the money path and dead endpoints

**Goal:** a customer can pay, be charged the amount they were shown, have exactly one order dispatched exactly once, and cancel it.

### 1a.1 — Unify order pricing into one function *(fixes B1, B2, B3, H10; unblocks H8, M12)*

The single highest-leverage change in the whole plan. Three of the four Blocking findings and one High are the same defect seen from different angles.

- Add `services/pricing_service.py` with `compute_order_quote(cart, user, delivery_type, lat, lng) -> OrderQuote` returning every line item (`product_subtotal`, `delivery_fee`, `service_fee`, `surge_fee`, `delivery_markup`, `payload_surcharge`, `staircase_surcharge`, `bottle_deposit`, `welcome_discount`, `wallet_discount`, `total`).
- Move the fee constants out of the route bodies: `RETAIL_SERVICE_FEE_KSH`, `WHOLESALE_SERVICE_FEE_KSH`, `SURGE_FEE_KSH` become the only definitions.
- `cart_routes.mpesa_payment` uses `quote.total` for the STK amount **and** passes the quote into `create_order` so `order.total_amount` is that identical value.
- `cart_services.fetch_detailed_cart` returns the same quote (removes the hardcoded `welcome_discount_amount = 0.0`).
- Expose it as `POST /api/cart/quote` for the client to render verbatim.

**Files:** `BackendAPI/services/pricing_service.py` (new), `routes/cart_routes.py`, `services/cart_services.py`, `services/order_service.py`, `services/dispatch_policy.py`, `schemas/cart_schemas.py`
**Acceptance:**
- A unit test asserts `stk_amount == order.total_amount` for: retail/wholesale × surge/off-surge × first-order/repeat × wallet-balance/none × `quick_swap`/`keep_my_bottle`. All 32 combinations, zero drift.
- Freezing the clock inside a peak window changes the total by exactly `SURGE_FEE_KSH` on both sides.
- A retail M-Pesa callback with the exact STK amount passes the ±1 KSH validator and marks the order `paid`.

**Effort:** M

### 1a.2 — Make payment confirmation idempotent *(fixes B4)*

- In `update_orders_payment_status_by_checkout_id`: `select(...).with_for_update()`, and `return early` if `payment_status` is already `paid`. Only the transition into `paid` may broadcast, notify, or dispatch.
- Migration: unique constraint on `Orders.checkout_request_ID`, unique on `Payments.checkout_request_id`, unique on `Payments.mpesa_receipt`. *(also closes M14)*
- Client: stop polling on terminal M-Pesa result codes (`1032`, `2001`, `1`) instead of only on manual confirm. *(part of M8)*

**Files:** `services/order_service.py`, `routes/cart_routes.py`, `alembic/versions/<new>.py`, `app/(screens)/Cart.tsx`
**Acceptance:** calling `/confirm_payment` ten times in a row for one paid order produces exactly one `Payment` row, one vendor notification, and one `dispatch_order_to_riders` invocation. Replaying an identical Safaricom callback returns 200 and changes nothing.
**Depends on:** 1a.1 (the callback must be able to succeed before idempotency is observable)
**Effort:** M

### 1a.3 — Fix the five dead endpoint paths *(fixes B5, H3)*

- `useOrders.ts`: `/api/orders/{id}/cancel` → `/api/cart/orders/{id}/cancel`; `/api/orders/{id}/resolve-mismatch` → `/api/cart/orders/{id}/resolve-mismatch`. Move both into `ROUTES`.
- `ApiRoutes.ts`: `LAST_ORDER_FROM_VENDOR` → `/api/vendor-favorites/{id}/last-order`.
- `CHECK_VENDOR_FAVORITE`: add `GET /api/vendor-favorites/check/{vendor_id}` returning `{is_favorite: bool}` — cheaper than a client-side derive because `vendor/[id]` renders before the favourites list resolves.
- `GET_PAYMENT_HISTORY`: decide between implementing `GET /api/payments/history` (from the `Payment` table, which after 1a.2 is finally populated) or repointing `PaymentHistory.tsx` at `/api/wallet/transactions`. **Recommendation: implement the endpoint** — the wallet ledger is a different thing from order payments and conflating them will bite later.

**Files:** `drop-customer-app/API/routes/ApiRoutes.ts`, `hooks/queries/useOrders.ts`, `hooks/queries/useVendorFavorites.ts`, `BackendAPI/routes/vendor_favorites_routes.py`, `routes/cart_routes.py` (payment history), `services/vendor_favorites_service.py`
**Acceptance:** cancel succeeds from `OrderDetail` and `OrderCard` and the order reaches `cancelled` with stock restored; a `mismatch_pending` order can be resolved both ways; the heart icon on `vendor/[id]` reflects true state on first paint; `PaymentHistory` renders real rows.
**Effort:** S

### 1a.4 — Close the wallet top-up callback *(fixes B6)*

- Add the `MPESA_CALLBACK_SECRET` query check and `is_safaricom_ip` guard to `/api/wallet/mpesa-callback`, mirroring the order callback.
- Validate the callback `Amount` against `transaction.amount` before crediting; reject on mismatch.
- Update the Safaricom callback URL for wallet top-ups to carry the secret.

**Files:** `BackendAPI/routes/wallet_routes.py`, `services/wallet_service.py`
**Acceptance:** a forged POST from a non-Safaricom IP, or without the secret, or with an inflated amount, returns 403/400 and leaves `wallet_balance` untouched. A genuine sandbox callback still credits correctly.
**Effort:** S

### 1a.5 — Reject empty-cart checkout cleanly *(fixes H9)*

Guard `if not cart or not cart.cart_item` before any pricing; load `user_model` unconditionally so the debt intercept always runs.

**Files:** `routes/cart_routes.py`
**Acceptance:** checkout with no cart returns 400 with a readable detail, not 500. A customer with `debt_balance > 0` is blocked regardless of cart contents.
**Effort:** S

---

## Phase 1b — Blocking/High: authorisation on the tracking surface

**Goal:** a customer's live location stream is visible only to that customer.

### 1b.1 — Authorise every order-scoped realtime and tracking endpoint *(fixes B7, H5)*

- `_authenticate_ws` gains an authorisation step. Add `authorise_order_access(order_id, clerk_id) -> role` and call it in `/ws/track/{order_id}`; close 1008 on failure.
- `/ws/orders/{entity_type}/{entity_id}`: assert the token subject resolves to that entity id for that type.
- `/ws/rider/{rider_id}`: assert the subject is that `Deliverer`.
- `GET /api/cart/orders/{order_id}/tracking-logs`: filter on `order.customer_id`.

**Files:** `BackendAPI/routes/websocket_routes.py`, `routes/cart_routes.py`, `dependencies/auth_dependencies.py`
**Acceptance:** customer A's token is rejected (1008 / 403) on customer B's order for all four endpoints; the legitimate customer, the order's vendor, and its assigned rider all still connect.
**Effort:** M

### 1b.2 — Give the customer app a tracking endpoint it can actually call *(fixes H2)*

Add `GET /api/cart/orders/{order_id}/rider-location`, authorised on `order.customer_id`, returning the same shape as the rider route. Repoint `ROUTES.RIDER_LOCATION`.

**Files:** `routes/cart_routes.py`, `drop-customer-app/API/routes/ApiRoutes.ts`
**Acceptance:** `useRiderTracking`'s initial REST fetch returns 200 with coordinates for the order's owner and 403 for anyone else; the marker appears before the socket opens.
**Depends on:** 1b.1 (shares the authorisation helper)
**Effort:** S

### 1b.3 — Make the Map screen use the working tracking hook *(fixes H1)*

Delete the inline WebSocket in `Map/[id].tsx:887-922` and consume `useRiderTracking(activeSession.id, status === "picked_up")`. This removes the missing-token bug and the payload-shape bug in one move.

**Files:** `drop-customer-app/app/(screens)/Map/[id].tsx`
**Acceptance:** with an order in `picked_up`, the rider marker animates on the map from real coordinates; the socket handshake carries a token and is not closed with 1008.
**Depends on:** 1b.1, 1b.2
**Effort:** S

### 1b.4 — Fix the cross-worker tracking relay *(fixes H6)*

Read `order_rider_map:{order_id}` from Redis in `_local_update_rider_location` instead of relying on the in-process dict, and populate it when a tracker connects (resolve `order.deliverer_id` once at connect time).

**Files:** `BackendAPI/routes/websocket_routes.py`
**Acceptance:** with two API instances behind a load balancer, a customer connected to instance A receives coordinates streamed by a rider connected to instance B, including after instance A restarts.
**Depends on:** 1b.1
**Effort:** M

---

## Phase 1c — High/Medium: error handling, contracts, hardening

**Goal:** failures reach the user as sentences, and the TS types stop lying about the API.

### 1c.1 — Migrate `hooks/queries/` onto `useApiClient` and surface backend detail *(fixes M5)*

All 14 hook files. Replace raw `fetch` with the axios client so the 401 → `signOut()` interceptor covers hook traffic, and propagate `error.response.data.detail` so `Toast.error` shows the backend's message. Preserve the existing 409 `vendor_conflict` special case in `useAddToCart`.

**Files:** all of `drop-customer-app/hooks/queries/*.ts`, plus the raw-fetch call sites in `Cart.tsx`, `BottleWallet.tsx`, `Profile.tsx`, `SettingsMain.tsx`, `Map/[id].tsx`, `app/index.tsx`, `(Auth)/Onboarding.tsx`, `usePushNotifications.ts`
**Acceptance:** a 402 debt intercept, a 409 locked cart, and a 400 distance rejection each render the backend's own `detail` text in a Toast; an expired session signs the user out from any hook call; `grep -rn "fetch(" app components hooks | grep -v hooks/queries` returns only the Google Places, Cloudinary, and NetInfo calls.
**Effort:** L

### 1c.2 — Align the order contract *(fixes H4)*

- Add `is_rated` to `BaseOrder`, derived from the existence of a `Review` for that order (a `selectinload` + computed field, or a subquery-loaded column).
- Remove `is_locked` from the TS `Order` interface — it is a `Cart` concept.
- Audit the remaining TS interfaces in `hooks/queries/` against their Pydantic counterparts while in there.

**Files:** `BackendAPI/schemas/order_schema.py`, `services/order_service.py`, `drop-customer-app/hooks/queries/useOrders.ts`
**Acceptance:** `is_rated` is `true` for a reviewed delivered order and `false` otherwise; the rate action is hidden for reviewed orders; no TS field lacks a server-side source.
**Effort:** S

### 1c.3 — Fix the STK-before-validation window *(fixes H8)*

Make the preflight in `mpesa_payment` exhaustive (self-dealing, MOQ, distance, stock — everything `create_order` re-checks), so nothing can raise after the push. Where a post-push failure is still possible, write a `Payment` row with `status="orphaned"` and enqueue a refund instead of only unlocking the cart.

**Files:** `routes/cart_routes.py`, `services/order_service.py`, `services/refund_service.py`
**Acceptance:** an injected `create_order` failure after a successful push leaves an auditable record and a queued refund, never a silent loss.
**Depends on:** 1a.1
**Effort:** M

### 1c.4 — Payment UX and cart-rule feedback *(fixes M8, M1, M2, M12)*

- Polling: 3→5→8 s backoff, terminal-code stop (already partly in 1a.2), a persistent "payment pending" banner on `Orders`, and a resume affordance after the 60 s cutoff.
- Hoist the retail 4-bottle cap above the new-cart branch in `add_to_cart_service`.
- Return MOQ progress on the detailed cart and show it in `Cart.tsx` for wholesale.
- Return `surge_fee` / `surge_active` from the quote endpoint and render the line item.

**Files:** `app/(screens)/Cart.tsx`, `app/(screens)/Orders.tsx`, `BackendAPI/services/cart_services.py`, `routes/delivery_fee_routes.py`
**Acceptance:** adding a 5th bottle to an empty retail cart is rejected at add time; a wholesale cart shows "62 / 100 kg"; the checkout sheet shows a surge line during peak hours; a customer whose payment never confirms can still see and resume the order.
**Depends on:** 1a.1, 1a.2
**Effort:** M

### 1c.5 — Auth and config hardening *(fixes M11, L3, L4, H11)*

- Wallet routes: derive the entity from the token, drop `user_type` from the request body.
- Fail fast at startup if `FRONTEND_CLERK_API_KEY` or `CLERK_ISSUER` is unset, so audience validation is never silently skipped.
- Fix the `ALLOWED_ORIGINS = ["*"]` + `allow_credentials=True` combination.
- **Secrets (needs your decision, not a silent fix):** `git rm --cached drop-customer-app/google-services.json.bak`, add `*.bak` to `.gitignore`, rotate that key, and confirm the `app.json` Maps key is restricted to the `com.drop.customer` bundle ID / Android SHA-1 and to the specific Maps APIs. History rewrite is a separate call.

**Files:** `routes/wallet_routes.py`, `core/security.py`, `main.py`, `.gitignore`, `drop-customer-app/app.json`
**Acceptance:** wallet endpoints ignore a spoofed `user_type`; the app refuses to boot with an unset audience; `git ls-files | grep '\.bak'` is empty.
**Effort:** S (excluding key rotation, which is operational)

### 1c.6 — Convention cleanup *(fixes M6, M7, M13, M16, M18, L6, L9, L10)*

Batch of mechanical fixes: `Alert.alert` → `Toast` (12 sites), `TouchableOpacity` → `PressableScale` (9 files, `Cart.tsx` first), route declarations to `""` to kill the 307s, `usePushNotifications` onto `ROUTES` + correct types + sign-out de-registration, `(x || 0).toLocaleString()` on the two unguarded wallet balances, drop the dead `amount`/`user_id`/`Idempotency-Key` payload, named directory route, and correct the `RETAIL_FLAT_FEE_KSH` comment.

**Files:** as listed in the audit's M6/M7/M13/M16/M18/L6/L9/L10 rows
**Acceptance:** zero `Alert.alert` outside destructive confirmations; zero `TouchableOpacity` in `app/`; no 307 on any customer API call; `tsc --noEmit` still clean.
**Effort:** M

---

## Phase 1d — Medium: correctness of business rules, performance, scalability

**Goal:** the documented radius/dispatch rules are the rules the code actually applies.

### 1d.1 — Enforce the discovery radii *(fixes M3, M4)*

- Add explicit `ST_DWithin(Vendor.location, point, 2000)` to `get_nearby_vendors` and `get_top_rated_vendors` so the 2 km retail rule holds at discovery, not just at checkout.
- Apply a 15 km filter to the wholesale branch of `get_vendors_by_type_service` (currently an early return makes it nationwide and leaves `k_rings = 32` unreachable).
- `get_top_brands_service`: either use the coordinates it accepts or drop the parameters and rename it honestly. Fix `if not lat and not lng` → `or`.

**Files:** `BackendAPI/services/vendor_service.py`
**Acceptance:** a vendor 2.4 km away no longer appears in nearby/top-rated (it currently can, via the `k=5` H3 ring); every vendor the customer can add to a cart passes the checkout distance guard.
**Effort:** M

### 1d.2 — Move ARQ out of the API process and make the sweeps safe to run concurrently *(fixes H7)*

- Remove `create_worker` from the FastAPI lifespan; gate it behind `RUN_INLINE_WORKER=1` for local dev only.
- `run_auto_resolve_bottle_rejections`: `with_for_update(skip_locked=True)`, re-check `status` inside the loop, and per-ticket `try/except` so one failure does not abort the sweep.
- Same treatment for `auto_cancel_pending_orders`.
- Register `reassign_unassigned_orders` as a cron job or remove it, and fix its dishonest `reassigned_count`. *(fixes M22)*
- Document the required process topology in `BackendAPI/README.md`.

**Files:** `BackendAPI/main.py`, `worker.py`, `jobs/auto_resolve_bottle_rejections.py`, `jobs/auto_cancel_pending_orders.py`, `services/order_service.py`, `BackendAPI/README.md`
**Acceptance:** with 3 API instances running, a stale rejection ticket is resolved exactly once; the 3-minute dispute sweep is observable in the worker log and nowhere else; an order that fails tiered dispatch is retried on a schedule.
**Effort:** M

### 1d.3 — WebSocket lifecycle robustness *(fixes M15, M17)*

- `try/finally` around all three socket loops so cleanup always runs.
- Wire NetInfo into `useWebSocket` and `useRiderTracking`: reset the attempt counter and reconnect the moment `isConnected` flips true, instead of waiting out the backoff.

**Files:** `BackendAPI/routes/websocket_routes.py`, `drop-customer-app/hooks/useWebSocket.ts`, `hooks/queries/useRiderTracking.ts`
**Acceptance:** killing the app mid-stream leaves no entry in the manager's dicts; toggling airplane mode for 20 s reconnects within ~2 s of connectivity returning, not after the next backoff tick.
**Depends on:** 1b.3, 1b.4
**Effort:** M

### 1d.4 — Wallet and refund ledger integrity *(fixes M9, M10, M20, M21)*

- Write a `WalletTransaction` for every balance mutation (discount applied, discount restored, cashback earned), not just top-up/withdrawal.
- Normalise the two wallet hooks to a single response shape.
- Only restore `has_used_welcome_offer` when the cancelled order was actually paid.
- Enqueue a refund on cancellation of a paid order instead of relying on an admin sweep, and expose refund state on the order.

**Files:** `services/wallet_service.py`, `services/order_service.py`, `services/refund_service.py`, `drop-customer-app/hooks/queries/useWallet.ts`, `app/(screens)/Transactions.tsx`
**Acceptance:** every `wallet_balance` delta has a matching ledger row; cancel → re-order cannot re-earn the welcome discount; a cancelled paid order shows a refund status to the customer.
**Depends on:** 1a.2
**Effort:** M

### 1d.5 — Decompose the four monolith screens *(fixes M19)*

`Map/[id].tsx` (1366), `Cart.tsx` (954), `OrderDetail.tsx` (924), `Profile.tsx` (868). Extract the logic-bearing pieces first — the tracking effect, the checkout sheet, the pricing summary, the status stepper — not just JSX blocks.

**Files:** the four screens, plus new files under `components/`
**Acceptance:** no screen over ~400 lines; the extracted pricing summary reads its numbers from the server quote (1a.1) rather than recomputing them.
**Depends on:** 1a.1, 1b.3, 1c.1
**Effort:** L

### 1d.6 — Dead code and hygiene *(fixes L1, L2, L7)*

Delete `services/deliverer_service_cancel_patch.py`, untrack `BackendAPI/test.db`, and normalise the vendor-list response envelope so hooks can drop `json.data || json`.

**Files:** `BackendAPI/services/deliverer_service_cancel_patch.py` (delete), `.gitignore`, `routes/vendor_routes.py`, `hooks/queries/useVendors.ts`
**Acceptance:** `grep -rn deliverer_service_cancel_patch` is empty; `git ls-files | grep test.db` is empty; every vendor endpoint returns the same envelope.
**Effort:** S

---

## Phase 1e — Test coverage

**Goal:** the Blocking findings cannot silently return.

### 1e.1 — Regression tests for every 1a/1b fix

Non-negotiable, and cheapest to write immediately after each fix rather than at the end:

- **Pricing parity** (B1/B2/B3): the 32-combination matrix from 1a.1.
- **Callback/poll idempotency** (B4): replay, concurrent-callback, and poll-storm cases.
- **Wallet callback forgery** (B6): wrong IP, missing secret, inflated amount.
- **Tracking authorisation** (B7/H5): cross-customer rejection on all four endpoints.
- **Route existence** (B5/H3): a test that asserts every path in `ApiRoutes.ts` resolves against the FastAPI route table. This one test would have caught five of this audit's findings and will catch the next one.

**Files:** `BackendAPI/tests/test_pricing_parity.py`, `test_payment_idempotency.py`, `test_wallet_callback_security.py`, `test_ws_authorization.py`, `test_route_contract.py`
**Acceptance:** all new tests pass; each fails when its fix is reverted.
**Effort:** L

### 1e.2 — Fill the untested customer surface *(fixes H12)*

Service-level tests for refunds, wallet (top-up/withdraw/callback), favourites, vendor favourites, saved locations, reviews, notifications, and order contacts.

**Files:** `BackendAPI/tests/` (new modules per service)
**Acceptance:** every customer-facing service module has at least happy-path + authorisation-failure + one edge case.
**Effort:** L

### 1e.3 — Verify migration parity against a live database

The one Step-2 checklist item that cannot be closed statically. Run `alembic upgrade head` on a clean database, then `alembic check` (or an `--autogenerate` diff) to confirm no model drift. The revision chain itself is already verified linear: 42 revisions, one base, one head.

**Files:** none (CI step + a note in `BackendAPI/README.md`)
**Acceptance:** `alembic check` reports no pending changes; the check runs in CI so drift is caught at PR time.
**Effort:** S

---

## Suggested cut lines

If you want to ship in stages rather than all of Phase 1:

- **Minimum viable payments release:** 1a.1 → 1a.2 → 1a.3 → 1a.5 → 1e.1 (pricing + idempotency + route-contract tests). Effort ≈ 4–6 days. Without this the platform charges the wrong amount and cannot cancel an order.
- **Minimum viable security release:** add 1a.4 and 1b.1. Effort ≈ +1–2 days. B6 is remotely exploitable for free credit and should not wait behind the tracking work.
- **Everything else** can follow incrementally; 1c.1 (error handling) and 1d.5 (decomposition) are the two large ones and are safe to defer.
