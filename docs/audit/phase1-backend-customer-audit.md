# Phase 1 Audit — Backend (customer surface) + Customer App

**Date:** 2026-07-30
**Scope:** `BackendAPI/` (only the surface `drop-customer-app` touches) and `drop-customer-app/`.
**Out of scope:** `drop-rider-app/`, `drop-vendor-app/`, and the vendor/rider/admin backend modules except where a customer route depends on them.
**Method:** static read-only review. No server, worker, or test suite was executed. `npx tsc --noEmit` in `drop-customer-app` was run and is **clean**.

---

## Phase 2 resolution status (2026-07-30)

All 7 Blocking and all 12 High findings are **fixed**, along with the Medium and Low
items listed below. Verification: `pytest tests/` → **145 passed** (the 4 failures in
`tests/test_vendor_remittance_service.py` are pre-existing and out of scope — see the
note at the end of this section); `npx tsc --noEmit` → **clean**.

| ID | Status | Where it was fixed |
|---|---|---|
| B1, B2, B3, H10 | Fixed | New `services/pricing_service.py` is the sole source of order pricing. `POST /api/cart/quote` serves it, `mpesa_payment` pushes `quote.stk_amount`, `create_order(quote=…)` writes `quote.total`. Total is quantized to whole shillings, so charged == recorded by construction. The client's local formula was deleted. `tests/test_pricing_parity.py` asserts parity across 32 combinations. |
| B4 | Fixed | `update_orders_payment_status_by_checkout_id` locks the order rows `FOR UPDATE`, returns early if already `paid`, and fires dispatch/broadcasts only after `session.commit()`. Backed by partial unique indexes on `orders.checkout_request_ID` and `payments.mpesa_receipt` (migration `b7c1e9f04a21`). |
| B5, H3 | Fixed | `CANCEL_ORDER`, `RESOLVE_MISMATCH`, `CART_QUOTE`, vendor-favourite paths corrected in `ApiRoutes.ts`; new `routes/payment_routes.py` serves `GET /api/payments/history`. `tests/test_route_contract.py` parses `ApiRoutes.ts` and fails if a path does not resolve. |
| B6 | Fixed | `routes/wallet_routes.py` callback now requires a shared secret **and** a Safaricom source IP; `wallet_service.handle_mpesa_topup_callback` locks the wallet, rejects replays, and validates amount + receipt. `tests/test_wallet_security.py`. |
| B7, H5 | Fixed | `dependencies/auth_dependencies.py` gained `authorise_order_access` / `owns_entity` (404, not 403, so order IDs are not enumerable). Applied to every order-scoped REST route and all three WebSocket endpoints. `tests/test_order_authorization.py`. |
| H1, H2, H6 | Fixed | `useRiderTracking` rewritten: JWT in the socket URL, both payload shapes accepted, NetInfo + AppState reconnect, REST fallback on the new customer-scoped `GET /api/cart/orders/{id}/rider-location`. Relay resolves the rider from Redis, then falls back to the DB. `Map/[id].tsx` no longer opens its own unauthenticated socket. |
| H4 | Fixed | `types/models.ts` reconciled with the actual `OrderResponse`; `is_rated` is now populated server-side by `annotate_is_rated`. |
| H7 | Fixed | ARQ only runs in-process behind `RUN_INLINE_WORKER=1`; documented in `BackendAPI/README.md`. |
| H8 | Fixed | On a post-STK failure the orphaned `Payment` row is written for audit and the customer sees an actionable error; `create_order` is transactional and returns the order. |
| H9 | Fixed | `_load_priced_cart()` returns 400 with a clear `detail` on an empty or missing cart. |
| H11 | **Partly — action required from you** | `google-services.json.bak` removed from the index and `.gitignore` extended, but the key is still in git history and must be rotated. The `app.json` Maps key needs bundle-ID / SHA-1 restrictions. |
| H12 | Fixed | Six new test modules: pricing parity, payment idempotency, wallet security, order authorisation, route contract, customer services. |
| Medium / Low | Fixed | `ST_DWithin` bounds on discovery queries; CORS credentials no longer paired with `*`; fail-fast on missing Clerk config in production; `auto_cancel_pending_orders` `User` import + status filter + cart release; `queryClient.clear()` on sign-out; all 14 hooks moved onto `useApiRequest`; `Toast.error(…, errorMessage(err))` everywhere; indexes on `orders.payment_status` and `reviews`. |

**`tests/test_vendor_remittance_service.py` — deleted, not repaired.** It imported
`services.vendor_remittance_service` and `models.vendor_remittance_model`. Neither
exists, because commit `cf959d1` ("feat: complete backend scalability overhaul…",
2026-06-16) retired the whole vendor-remittance feature in one sweep:

| Deleted in cf959d1 | Lines |
|---|---|
| `BackendAPI/models/vendor_remittance_model.py` | 36 |
| `BackendAPI/routes/vendor_remittance_routes.py` | 76 |
| `BackendAPI/services/vendor_remittance_service.py` | 95 |
| `drop-rider-app/app/(screens)/VendorRemittance.tsx` | 333 |
| `drop-vendor-app/app/(screens)/VendorRemittanceDashboard.tsx` | 577 |

Migration `ef84f79af8e4` then dropped the `vendor_remittances` table, so the schema at
head has nowhere to store a remittance. Nothing in any of the three apps or the backend
references the feature today — the only surviving traces are this test file and a stale
generated `drop-rider-app/.expo/types/router.d.ts` (build artifact, not source).

Restoring ~1,100 lines and un-dropping a table to satisfy a stale test would have been
the wrong repair; the test was the leftover, not the code. Deleting it takes the suite
to **145 passed, 0 failed**. If the removal was in fact unintentional, the whole feature
comes back with `git checkout cf959d1^ -- <paths above>` plus a migration recreating the
table (its exact columns are preserved in `ef84f79af8e4`'s `downgrade()`).

---

## 0. Endpoint mapping (Step 1 result)

Every route in `drop-customer-app/API/routes/ApiRoutes.ts` and every hook in `hooks/queries/` was cross-referenced against the registered routers in [main.py:204-243](../../BackendAPI/main.py#L204).

**Customer-relevant backend files confirmed in use:**

| Area | Backend file | Notes |
|---|---|---|
| Auth / profile / push token / saved locations | `routes/auth_routes.py`, `routes/saved_location_routes.py`, `services/user_service.py`, `services/saved_location_service.py` | all reached |
| Cart / checkout / orders / M-Pesa | `routes/cart_routes.py`, `services/cart_services.py`, `services/payment_service.py`, `services/order_service.py`, `services/dispatch_policy.py` | all reached |
| Discovery | `routes/vendor_routes.py`, `routes/product_routes.py`, `routes/query_routes.py`, `services/vendor_service.py`, `services/product_service.py`, `services/query_service.py` | all reached |
| Favourites | `routes/favorites_routes.py`, `routes/vendor_favorites_routes.py` + services | reached |
| Reviews | `routes/review_routes.py`, `services/review_service.py` | reached |
| Notifications / push | `routes/notification_routes.py`, `services/notification_service.py`, `services/expo_push_service.py` | reached |
| Wallet | `routes/wallet_routes.py`, `services/wallet_service.py` | reached |
| Delivery-fee preview | `routes/delivery_fee_routes.py` | reached (public, unauthenticated) |
| Contacts | `routes/contact_routes.py`, `services/contact_service.py` | reached — but the path is **not** in `ApiRoutes.ts` |
| Realtime | `routes/websocket_routes.py` | reached |
| Background jobs | `worker.py`, `jobs/auto_resolve_bottle_rejections.py`, `jobs/auto_cancel_pending_orders.py` | reached |

**Corrections to the assumed list:**

- `routes/refund_routes.py` is **not customer-facing**. Its three endpoints are an admin sweep (`/process-refunds`) and two Safaricom reversal webhooks. The customer app never calls it. Customer-initiated cancellation only sets `payment_status = "refund_pending"`; nothing in the customer path creates a refund.
- `routes/sync_routes.py` is **rider-only** (`GET /api/sync/rider/orders`). Not customer surface.
- One out-of-list rider file **is** on the customer critical path: `routes/deliverer_routes.py:232` (`GET /api/rider/orders/{order_id}/rider-location`) is called by the customer app's tracking fallback. See H2.
- `services/favorites_service.py`, `services/review_service.py`, `services/notification_service.py`, `services/saved_location_service.py`, `services/wallet_service.py` are all genuinely customer-facing, as assumed.

**Routes the app defines that do not exist on the backend** (see B5, H3): `/api/payments/history`, `/api/vendor-favorites/check/{id}`, `/api/vendor-favorites/last-order/{id}`, `/api/orders/{id}/cancel`, `/api/orders/{id}/resolve-mismatch`.

---

## 1. BLOCKING

### B1 — Retail service fee is 10 in the STK amount and 12 in the order record, so every retail M-Pesa callback is rejected

- [BackendAPI/routes/cart_routes.py:185](../../BackendAPI/routes/cart_routes.py#L185) — `service_fee = 50.0 if wholesale else 10.0`
- [BackendAPI/services/order_service.py:70](../../BackendAPI/services/order_service.py#L70) — `RETAIL_SERVICE_FEE_KSH = 12.0`
- [BackendAPI/services/cart_services.py:59](../../BackendAPI/services/cart_services.py#L59) — cart preview returns `12.0`
- [BackendAPI/routes/cart_routes.py:402](../../BackendAPI/routes/cart_routes.py#L402) — `abs(order.total_amount - callback_amount) > 1.0 → reject`

`server_amount` (the amount pushed to STK) is built in the route with a **10 KSH** service fee. `order.total_amount` is built inside `create_order` with a **12 KSH** service fee. The gap is a fixed 2 KSH — larger than the ±1 KSH tolerance the callback validator allows. Every retail order therefore fails `Amount mismatch`: no `Payment` audit row is written, no confirmation email is sent, and the cart is not purged by the callback. Payment only ever lands via the client's `/confirm_payment` poll, so an order whose app is backgrounded before confirmation stays unpaid while the customer has been debited.

**Fix:** make `dispatch_policy` (or `order_service`) the single source of truth for the fee constants and have `cart_routes` and `cart_services` both call it; delete the inline `10.0`/`12.0`/`50.0` literals.

### B2 — Surge fee and wholesale delivery markup are in `order.total_amount` but not in the STK amount

- [BackendAPI/routes/cart_routes.py:230](../../BackendAPI/routes/cart_routes.py#L230) — `server_amount` omits `surge_fee` and `delivery_markup`
- [BackendAPI/services/order_service.py:734-738](../../BackendAPI/services/order_service.py#L734) — `pre_discount_total` includes both
- [BackendAPI/services/order_service.py:76-88](../../BackendAPI/services/order_service.py#L76) — `SURGE_FEE_KSH = 10.0`, `PEAK_HOURS = [(6,8),(17,19)]` (matches the documented 06:00–08:00 / 17:00–19:00 EAT window)

During either surge window the divergence grows to 12 KSH (retail) and the customer is *undercharged* by 10 KSH on every order while the ledger records the higher figure. Compounds B1.

**Fix:** compute the order total once, in one function, and pass that exact figure to `initiate_stk_push`.

### B3 — Welcome-offer discount and bottle-deposit rules differ between the route and `create_order`

- [BackendAPI/routes/cart_routes.py:200-214](../../BackendAPI/routes/cart_routes.py#L200) — bottle fee only when `delivery_type == "quick_swap"`; `welcome_discount = highest_bottle_price * 0.30`
- [BackendAPI/services/order_service.py:679-698](../../BackendAPI/services/order_service.py#L679) — bottle fee when `keep_my_bottle` **or** first order; `welcome_discount = bottle_fee_total * 0.30`

For a first-time customer ordering 3×20 L the route computes a 90 KSH discount and the service computes 270 KSH — a 180 KSH divergence between what is charged and what is recorded. For a first-time `keep_my_bottle` order the route charges no deposit at all while the order records 300 KSH per bottle.

**Fix:** extract one `compute_order_pricing(cart, user, delivery_type)` helper used by both the preflight and `create_order`.

### B4 — Payment-status update is not idempotent; the 5-second poll re-dispatches the order on every tick

- [BackendAPI/services/order_service.py:861-952](../../BackendAPI/services/order_service.py#L861) — no `if order.payment_status == "paid": return` guard
- [BackendAPI/routes/cart_routes.py:301-318](../../BackendAPI/routes/cart_routes.py#L301) — `/confirm_payment` calls it
- [BackendAPI/routes/cart_routes.py:421](../../BackendAPI/routes/cart_routes.py#L421) — `/mpesa/callback` calls it too
- [drop-customer-app/app/(screens)/Cart.tsx:288-307](../../drop-customer-app/app/(screens)/Cart.tsx#L288) — polls every 5 s for 60 s

Each invocation re-broadcasts `NEW_ORDER`, creates another vendor notification + push, and spawns another `dispatch_order_to_riders` task (which itself pushes to up to 10 Tier-1 riders and then the whole Tier-2 radar). `check_payment` returns `code: "0"` on every poll after the first success, and the client only stops polling once its own success branch runs — so a slow round trip yields several duplicate dispatch cascades per order. A Safaricom callback retry does the same.

**Fix:** guard on the current status inside `update_orders_payment_status_by_checkout_id` (select `FOR UPDATE`, return early if already `paid`), and add a unique constraint on `Order.checkout_request_ID`.

### B5 — Cancel-order and resolve-mismatch call paths that do not exist (404 on every attempt)

- [drop-customer-app/hooks/queries/useOrders.ts:58](../../drop-customer-app/hooks/queries/useOrders.ts#L58) — `PUT /api/orders/{id}/cancel`; backend is `PUT /api/cart/orders/{id}/cancel` ([cart_routes.py:519](../../BackendAPI/routes/cart_routes.py#L519))
- [drop-customer-app/hooks/queries/useOrders.ts:66](../../drop-customer-app/hooks/queries/useOrders.ts#L66) — `PATCH /api/orders/{id}/resolve-mismatch`; backend is `/api/cart/orders/{id}/resolve-mismatch` ([cart_routes.py:546](../../BackendAPI/routes/cart_routes.py#L546))

Both are wired to live UI: the "Cancel Order" action in [OrderDetail.tsx:814](../../drop-customer-app/app/(screens)/OrderDetail.tsx#L814) and [OrderCard.tsx:82](../../drop-customer-app/components/common/OrderCard.tsx#L82). Customers cannot cancel anything, and an order parked in `mismatch_pending` has no exit path from the customer side (nothing else transitions it — [order_service.py:52](../../BackendAPI/services/order_service.py#L52) allows only `mismatch_pending → delivered`).

**Fix:** correct both paths and move them into `ROUTES` so they are covered by the "no hardcoded endpoints" rule.

### B6 — Wallet top-up callback is unauthenticated: free wallet credit

- [BackendAPI/routes/wallet_routes.py:59-67](../../BackendAPI/routes/wallet_routes.py#L59) — no shared secret, no `is_safaricom_ip` check
- [BackendAPI/services/wallet_service.py:61-84](../../BackendAPI/services/wallet_service.py#L61) — credits `wallet_balance` on `ResultCode == 0` without comparing the callback amount to `transaction.amount`

`POST /api/wallet/top-up` returns the `CheckoutRequestID` to the caller. The caller can then `POST /api/wallet/mpesa-callback` with `{"Body":{"stkCallback":{"CheckoutRequestID":"<theirs>","ResultCode":0}}}` and be credited for the full pending amount without paying. Wallet balance is spendable at checkout ([order_service.py:747-752](../../BackendAPI/services/order_service.py#L747)), so this converts directly into free orders.

**Fix:** apply the same guard the order callback uses — `MPESA_CALLBACK_SECRET` query check plus `is_safaricom_ip` — and validate the callback `Amount` against `transaction.amount` before crediting.

### B7 — Realtime and tracking endpoints authenticate the token but never authorise the subject

- [BackendAPI/routes/websocket_routes.py:328-342](../../BackendAPI/routes/websocket_routes.py#L328) — `/ws/track/{order_id}`: any valid Clerk token subscribes to any order's live GPS
- [BackendAPI/routes/websocket_routes.py:345-355](../../BackendAPI/routes/websocket_routes.py#L345) — `/ws/orders/{entity_type}/{entity_id}`: `entity_id` is never compared to `payload["sub"]`, so anyone can listen to another customer's or a vendor's order stream
- [BackendAPI/routes/cart_routes.py:531-540](../../BackendAPI/routes/cart_routes.py#L531) — `tracking-logs` takes `order_id` and never checks `order.customer_id`
- [BackendAPI/routes/deliverer_routes.py:232-255](../../BackendAPI/routes/deliverer_routes.py#L232) — `rider-location` checks the caller is *a* rider, not *the* rider on the order

Order IDs are UUIDs, so this is not trivially enumerable, but any ID that leaks (support screenshots, logs, a shared receipt) exposes a customer's real-time home-delivery location.

**Fix:** resolve the order in each handler and reject unless the authenticated subject is its customer, vendor, or assigned rider; close the socket with 1008 otherwise.

---

## 2. HIGH

### H1 — The Map screen's live tracking socket can never connect

- [drop-customer-app/app/(screens)/Map/[id].tsx:891](../../drop-customer-app/app/(screens)/Map/[id].tsx#L891) — WS URL is built without `?token=`; [`_authenticate_ws`](../../BackendAPI/routes/websocket_routes.py#L239) closes it immediately with code 1008
- Same file, line 896 — reads `data.lat` / `data.lng`, but the server sends `{"rider_id": ..., "location": {...}}` ([websocket_routes.py:209](../../BackendAPI/routes/websocket_routes.py#L209))

Two independent defects on the same 35-line block: it would not authenticate, and if it did it would never parse a coordinate. `useRiderTracking` already handles both correctly (`payload.location || payload`, token in the query string).

**Fix:** delete the inline socket in `Map/[id].tsx` and consume `useRiderTracking(orderId, isPickedUp)`.

### H2 — The REST tracking fallback is a rider-only route, so it 403s for every customer

- [drop-customer-app/hooks/queries/useRiderTracking.ts:49](../../drop-customer-app/hooks/queries/useRiderTracking.ts#L49) → `ROUTES.RIDER_LOCATION` → [deliverer_routes.py:236](../../BackendAPI/routes/deliverer_routes.py#L236) `Depends(get_current_rider)`

The hook fetches REST *first* on mount (line 170) to fill the map before the socket opens, and falls back to it permanently after 3 socket failures. Both paths are dead for customers: the initial marker never appears and the fallback cannot rescue a failed socket.

**Fix:** add a customer-scoped `GET /api/cart/orders/{order_id}/rider-location` that authorises on `order.customer_id`, and point the hook at it.

### H3 — Three front-end routes have no backend counterpart

- [ApiRoutes.ts:114](../../drop-customer-app/API/routes/ApiRoutes.ts#L114) `GET_PAYMENT_HISTORY = /api/payments/history` — no such route anywhere; drives the whole `PaymentHistory` screen via `usePaymentHistory`
- [ApiRoutes.ts:143](../../drop-customer-app/API/routes/ApiRoutes.ts#L143) `CHECK_VENDOR_FAVORITE = /api/vendor-favorites/check/{id}` — no `/check` route; nothing returns `is_favorite`
- [ApiRoutes.ts:144](../../drop-customer-app/API/routes/ApiRoutes.ts#L144) `LAST_ORDER_FROM_VENDOR = /api/vendor-favorites/last-order/{id}` — backend is `/{vendor_id}/last-order` ([vendor_favorites_routes.py:52](../../BackendAPI/routes/vendor_favorites_routes.py#L52)); the segments are inverted

**Fix:** implement `GET /api/payments/history` (or repoint the screen at `/api/wallet/transactions`), add a `check` endpoint or derive the flag client-side from `useVendorFavorites`, and swap the `last-order` segments.

### H4 — `Order` TS type promises two fields the API never returns

- [drop-customer-app/hooks/queries/useOrders.ts:24-25](../../drop-customer-app/hooks/queries/useOrders.ts#L24) — `is_locked: boolean` (non-optional) and `is_rated?: boolean`
- [BackendAPI/schemas/order_schema.py:50-99](../../BackendAPI/schemas/order_schema.py#L50) — `BaseOrder` has neither; `is_locked` exists only on `Cart` ([cart_model.py:17](../../BackendAPI/models/cart_model.py#L17)) and `is_rated` exists nowhere in the codebase

`is_locked` being typed as required means TypeScript will not warn about `if (order.is_locked)`, which is permanently `undefined` → falsy. Any "already rated" gating on `is_rated` silently offers the rate action forever.

**Fix:** either add `is_rated` to the order model/schema (derived from `Review.order_id`) and drop `is_locked`, or mark both optional in the TS type and stop branching on them.

### H5 — Rider-location socket accepts any authenticated token for any `rider_id`

- [BackendAPI/routes/websocket_routes.py:256-262](../../BackendAPI/routes/websocket_routes.py#L256)

`rider_id` comes from the path and is never compared to the token subject, so any signed-in account can stream fabricated coordinates for an arbitrary rider. These coordinates are relayed straight to the tracking customer and persisted to `gps_tracking_logs`. Listed here because it corrupts the customer tracking experience, not just the rider app.

**Fix:** reject unless `payload["sub"]` resolves to the `Deliverer` whose id is in the path.

### H6 — Tracking relay depends on process-local state that is often empty

- [BackendAPI/routes/websocket_routes.py:117-123](../../BackendAPI/routes/websocket_routes.py#L117) — `order_rider_map` is populated only as a side effect of an order-update broadcast
- [BackendAPI/routes/websocket_routes.py:201-211](../../BackendAPI/routes/websocket_routes.py#L201) — the relay iterates that in-memory dict to decide who receives a GPS update
- [BackendAPI/routes/websocket_routes.py:227-232](../../BackendAPI/routes/websocket_routes.py#L227) — `order_rider_map:{order_id}` is written to Redis with a 24 h TTL and **never read back**

Location fan-out is published over Redis, so every worker sees the event — but each worker then filters through its *own* dict. After a deploy/restart, or when a customer opens tracking without a fresh status broadcast having arrived, no worker holds the mapping and the coordinates are dropped silently. Also `rider_locations` / `tracking_connections` are per-process, so `README.md`'s claim of horizontal scalability holds for the pub/sub hop but not for this lookup.

**Fix:** read the Redis `order_rider_map:{order_id}` key in `_local_update_rider_location` (and seed it when the tracker connects) instead of relying on in-memory population.

### H7 — The ARQ worker runs inside every API process, multiplying every cron job

- [BackendAPI/main.py:98-109](../../BackendAPI/main.py#L98) — `create_worker(WorkerSettings)` is started as an asyncio task in the FastAPI lifespan
- [BackendAPI/worker.py:79-84](../../BackendAPI/worker.py#L79) — 4 cron jobs including the 3-minute dispute sweep (`second=0`, i.e. every minute) and the GPS flush (every 10 s)
- [BackendAPI/README.md:64-67](../../BackendAPI/README.md#L64) — also documents running `arq worker.WorkerSettings` as a separate process

With N uvicorn workers you get N (or N+1) schedulers. The 3-minute dispute auto-resolve **is** wired and will fire, but concurrently from every instance: `run_auto_resolve_bottle_rejections` ([jobs/auto_resolve_bottle_rejections.py:18-24](../../BackendAPI/jobs/auto_resolve_bottle_rejections.py#L18)) selects stale tickets with no `FOR UPDATE ... SKIP LOCKED` and no status re-check, so two instances can both cancel the same order, both restore stock, and both broadcast the cancellation. There is also no retry/DLQ around it — a raised exception inside the loop aborts the sweep for every remaining ticket, because `session.commit()` is only reached after the loop.

**Fix:** remove the in-process worker from the lifespan (gate it behind an env flag for local dev), run ARQ as its own process, and add `with_for_update(skip_locked=True)` + a per-ticket try/except in the sweep.

### H8 — STK push succeeds, `create_order` fails, money is taken with no order

- [BackendAPI/routes/cart_routes.py:276-297](../../BackendAPI/routes/cart_routes.py#L276)

The push is sent first; `create_order` then re-validates stock ([order_service.py:611-618](../../BackendAPI/services/order_service.py#L611)), self-dealing, wholesale MOQ, and the 2 km retail distance guard, any of which raises. The `except` block only unlocks the cart and re-raises. If the customer has already entered their PIN, the callback arrives, finds no order for the `CheckoutRequestID`, and returns 400 — the payment is stranded with no order and no refund record.

**Fix:** run every validation before `initiate_stk_push` (the preflight at lines 150-181 already does most of it — make it exhaustive), and on post-push failure write a `Payment` row plus a refund task rather than only unlocking the cart.

### H9 — Checkout with an empty or missing cart returns 500

- [BackendAPI/routes/cart_routes.py:133-140](../../BackendAPI/routes/cart_routes.py#L133)

`cart` is `None`-guarded on line 134 for the lock check, then dereferenced unconditionally on line 140 (`float(cart.total_amount)`) → `AttributeError` → the global handler returns a generic 500. The debt intercept at line 236 is also skipped whenever the cart has no items, because `user_model` is only assigned inside the `if cart.cart_item` branch.

**Fix:** `if not cart or not cart.cart_item: raise HTTPException(400, "Your cart is empty")` before any pricing, and load `user_model` unconditionally.

### H10 — The cart total is computed in four places with three different results

- [drop-customer-app/app/(screens)/Cart.tsx:123-156](../../drop-customer-app/app/(screens)/Cart.tsx#L123) — client copy (service fee 12, welcome discount `bottle_fee_total * 0.30`, **no** surge fee)
- [BackendAPI/routes/cart_routes.py:183-230](../../BackendAPI/routes/cart_routes.py#L183) — STK copy (service fee 10, welcome discount `highest_bottle_price * 0.30`, no surge)
- [BackendAPI/services/cart_services.py:49-68](../../BackendAPI/services/cart_services.py#L49) — preview copy (service fee 12; `welcome_discount_amount` hardcoded to 0)
- [BackendAPI/services/order_service.py:716-754](../../BackendAPI/services/order_service.py#L716) — ledger copy (service fee 12, includes surge + markup)

This is the root cause of B1–B3. The customer-visible total in the checkout sheet is not the amount debited, and neither equals the recorded `total_amount`.

**Fix:** one server-side pricing endpoint (extend `/api/delivery-fee` into a full quote, or add `POST /api/cart/quote`) that the app renders verbatim and that `mpesa_payment` reuses.

### H11 — A Google API key is committed in a tracked `.bak`, and the Maps key is inlined in `app.json`

- `drop-customer-app/google-services.json.bak` — **tracked** (`git ls-files` confirms) and contains an `AIzaSy…` key. The real `google-services.json` was removed in commit `e931eaa`, but the backup copy of it was left behind, so the key is still in `HEAD`, not merely in history.
- [drop-customer-app/app.json:25](../../drop-customer-app/app.json#L25) and line 39 — the same Maps key hardcoded for iOS and Android, while [README.md:48](../../drop-customer-app/README.md#L48) documents `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY`.
- `.gitignore` covers `**/.env` but nothing matching `*.bak`.

Maps keys shipped in a mobile binary are inherently extractable, so the `app.json` entry is a *restriction* question, not a secrecy one: it must be locked to the `com.drop.customer` bundle ID / Android SHA-1 **and** restricted to the specific Maps APIs in Cloud Console. The `.bak` file is a straightforward leak of a key that was deliberately removed.

**Fix (flagged, not applied):** `git rm --cached drop-customer-app/google-services.json.bak`, add `*.bak` to `.gitignore`, rotate that key, and verify API/app restrictions on the `app.json` key. Purging it from history requires a rewrite — your call.

### H12 — Customer-facing test coverage gaps

`BackendAPI/tests/` contains: `test_auth_services`, `test_cart_service`, `test_delivery_fee`, `test_order_service`, `test_orders_integration`, `test_payment_callback`, `test_payout_service`, `test_rider_vendor_registry`, `test_vendor_management`, `test_vendor_remittance_service`.

Untested customer surface: **wallet** (top-up, withdrawal, callback — the B6 hole), **refunds/reversals**, **favourites** and **vendor favourites**, **saved locations**, **reviews** (including the anti-self-rating rules), **notifications**, **order contacts**, **WebSocket auth/authorisation**, and the **cross-checks between `server_amount` and `order.total_amount`** (B1–B3 would all have been caught by one assertion).

---

## 3. MEDIUM

| # | Finding | Location | Why it matters | Fix sketch |
|---|---|---|---|---|
| M1 | Retail 4-bottle cap is skipped when the cart is created fresh — the cap check lives only in the existing-cart branch | [cart_services.py:91-110](../../BackendAPI/services/cart_services.py#L91) vs `141-148` | First add of qty 10 succeeds, then checkout rejects it; wasted funnel | Hoist the vendor-type/capacity check above the `if not existing_cart` split |
| M2 | Wholesale 100 kg MOQ is enforced only at checkout, twice ([dispatch_policy.py:81](../../BackendAPI/services/dispatch_policy.py#L81), [order_service.py:640](../../BackendAPI/services/order_service.py#L640)), never in the cart | `Cart.tsx` has no MOQ logic | Wholesale users hit a hard 400 with no warning | Return `moq_kg` + `current_kg` on the detailed cart and show progress in `Cart.tsx` |
| M3 | 2 km retail radius is not enforced in discovery — only an H3 `k=5` prefilter (~2.5–3 km reach), no `ST_DWithin`; `get_top_brands_service` takes `lat`/`lng` and ignores them entirely, and its guard is `if not lat and not lng` where it means `or` | [vendor_service.py:23-33](../../BackendAPI/services/vendor_service.py#L23), `35-45`, `75-84` | Users browse and cart from vendors that checkout will refuse | Add an explicit `ST_DWithin(location, point, 2000)` clause; fix the guard operator |
| M4 | Wholesale 15 km radius is bypassed: the non-retail branch returns nationwide results before the location branch is reached, making `k_rings = 32 if wholesale` dead code | [vendor_service.py:52-64](../../BackendAPI/services/vendor_service.py#L52) | Documented radius rule not enforced for wholesale discovery | Apply the H3/distance filter to both branches |
| M5 | Almost every query hook throws `new Error("Network error")` or the bare status code, discarding the backend `detail`; nothing in `hooks/queries/` uses the documented `useApiClient` axios client, so the 401 → `signOut()` interceptor never runs for hook traffic | [useCart.ts:16](../../drop-customer-app/hooks/queries/useCart.ts#L16), [useOrders.ts:53](../../drop-customer-app/hooks/queries/useOrders.ts#L53), [useVendors.ts:10](../../drop-customer-app/hooks/queries/useVendors.ts#L10), [useNotifications.ts:29](../../drop-customer-app/hooks/queries/useNotifications.ts#L29); client at [useApiClient.ts:9](../../drop-customer-app/API/useApiClient.ts#L9) | Directly violates the app's own rule ("display user-friendly backend errors, do not throw raw HTTP status codes"); expired sessions silently fail instead of signing out | Migrate hooks onto `useApiClient` and surface `error.response.data.detail` |
| M6 | 12 `Alert.alert(` calls where `Toast` is the documented convention | [BottleWallet.tsx](../../drop-customer-app/app/(screens)/BottleWallet.tsx#L78) (×9), [OrderDetail.tsx:92](../../drop-customer-app/app/(screens)/OrderDetail.tsx#L92), [OrderCard.tsx:101](../../drop-customer-app/components/common/OrderCard.tsx#L101) | Inconsistent, non-themed feedback | Replace with `Toast.*`; keep native alerts only for destructive confirmations |
| M7 | `TouchableOpacity` used where `PressableScale` is the convention, in 9 files — `Cart.tsx` alone has 37 | `Cart.tsx`, `SettingsMain.tsx`, all four `settings/*`, `Offers.tsx`, `PopupModal.tsx` | Documented tactile feel is missing on the highest-traffic screen | Swap incrementally, starting with `Cart.tsx` |
| M8 | M-Pesa polling: fixed 5 s interval, no backoff, hard 60 s cutoff, and it keeps polling after a *terminal* failure (`1032` user-cancelled, `2001` wrong PIN) because only `isManualConfirm` stops the loop | [Cart.tsx:240-307](../../drop-customer-app/app/(screens)/Cart.tsx#L240) | After the timeout toast there is no resume path; the order sits unpaid and the cart stays locked until the callback's failure branch unlocks it | Stop on terminal result codes, back off 3→5→8 s, and offer "I've paid — check again" plus a pending-payment banner on Orders |
| M9 | Wallet transaction list shape: the service returns `{data, nextCursor, hasNextPage, total}` but `useWalletTransactions` returns the envelope raw while `useWalletTransactionsPaginated` pages on it, so consumers of the two hooks see different shapes under the same `["walletTransactions"]` key prefix | [wallet_service.py:190-195](../../BackendAPI/services/wallet_service.py#L190), [useWallet.ts:10-55](../../drop-customer-app/hooks/queries/useWallet.ts#L10) | Easy source of `undefined.map` crashes and confusing invalidation | Normalise both hooks to return `data` and keep the cursor in `getNextPageParam` |
| M10 | Customer wallet cashback mutates `User.wallet_balance` directly; `WalletTransaction` rows are only ever created by top-up and withdrawal | `WalletTransaction(` appears only at [wallet_service.py:27](../../BackendAPI/services/wallet_service.py#L27) and `:132`; balance is mutated at [order_service.py:752](../../BackendAPI/services/order_service.py#L752) and `:1052` | The Transactions screen cannot explain balance changes; no audit trail for discounts or restorations | Write a `WalletTransaction` for every balance mutation (discount applied, discount restored, cashback earned) |
| M11 | `/api/wallet/*` uses bare `get_current_user` and takes `user_type` from the **request body** | [wallet_routes.py:13-49](../../BackendAPI/routes/wallet_routes.py#L13) | Role is client-asserted; a token that maps to more than one entity can pick which wallet to act on | Derive the entity from the token (reuse `get_current_customer`), drop `user_type` from the payload |
| M12 | Surge pricing is invisible pre-checkout: `/api/delivery-fee` computes `revenue["surge_fee"]` and returns only `service_fee` | [delivery_fee_routes.py:63-78](../../BackendAPI/routes/delivery_fee_routes.py#L63) | Customer cannot see why peak-hour orders cost more; also feeds B2 | Return `surge_fee` and `surge_active`, render in the checkout breakdown |
| M13 | Trailing-slash mismatch: the app calls `/api/notifications`, `/api/favorites`, `/api/vendor-favorites`, `/api/reviews` while the routers declare `"/"` | [ApiRoutes.ts:117-129](../../drop-customer-app/API/routes/ApiRoutes.ts#L117) vs the four routers | A 307 redirect on every one of those calls — an extra RTT on mobile networks | Declare the routes as `""` in the routers, or add the slash in `ROUTES` |
| M14 | `Order.checkout_request_ID` is indexed but not unique; `Payment` has no unique constraint on `checkout_request_id` or `mpesa_receipt` | [order_model.py:24](../../BackendAPI/models/order_model.py#L24) | The only thing preventing duplicate paid orders / duplicate payment rows is application code (B4) | Add unique constraints in a migration; let the DB enforce idempotency |
| M15 | WebSocket cleanup runs only in the `WebSocketDisconnect` handler; any other exception (a send on a half-closed socket) escapes without removing the entry | [websocket_routes.py:324](../../BackendAPI/routes/websocket_routes.py#L324), `341`, `371` | `tracking_connections` / `*_orders` grow unbounded, and dead sockets keep receiving fan-out attempts | Wrap the loops in `try/finally` and always call the matching `disconnect_*` |
| M16 | `usePushNotifications` hardcodes the push-token URL instead of `ROUTES.REGISTER_PUSH_TOKEN`; the response listener is annotated `import("axios").AxiosResponse` (an unrelated type); no de-registration on sign-out from this hook (only `SettingsMain` clears it) | [usePushNotifications.ts:101](../../drop-customer-app/hooks/usePushNotifications.ts#L101), `:117` | Endpoint-string rule violation; a wrong type annotation on a live callback; stale tokens keep receiving another account's pushes after sign-out on a shared device | Use `ROUTES`, fix the type, clear the token in the sign-out path |
| M17 | `@react-native-community/netinfo` is wired **only** to `OfflineBanner`; neither `useWebSocket` nor `useRiderTracking` subscribes to connectivity changes | [OfflineBanner.tsx:19](../../drop-customer-app/components/ui/OfflineBanner.tsx#L19) is the sole consumer | After a tunnel/lift network drop, reconnection waits on `onclose` + exponential backoff (up to 60 s in `useWebSocket`) instead of firing the instant the device is back online | Add a NetInfo listener that resets the attempt counter and reconnects on `isConnected` transitioning to true |
| M18 | Unguarded numeric render: `User.wallet_balance.toLocaleString()` | [(screens)/index.tsx:267](../../drop-customer-app/app/(screens)/index.tsx#L267), [Profile.tsx:209](../../drop-customer-app/app/(screens)/Profile.tsx#L209) | Crashes the home screen and profile if the field is null (it is nullable server-side) | Apply the documented `(x || 0).toLocaleString()` pattern |
| M19 | Monolith screens well past the "break into `components/`" rule | `Map/[id].tsx` 1366, `Cart.tsx` 954, `OrderDetail.tsx` 924, `Profile.tsx` 868 lines | `Map/[id].tsx` is where H1 hid for so long; `Cart.tsx` is where H10's client pricing copy lives | Extract the tracking effect, the checkout sheet, and the pricing summary first — the three that carry logic, not just JSX |
| M20 | `cancel_customer_order` resets `has_used_welcome_offer = False` on any cancellation, including free `pending`/`unassigned` ones | [order_service.py:1055-1057](../../BackendAPI/services/order_service.py#L1055) | Place → cancel → repeat farms the 30 % welcome discount indefinitely at zero cost (the 50 KSH penalty applies only to `accepted`) | Only restore the offer when the order was paid, or cap restorations |
| M21 | Customer cancellation flags `payment_status = "refund_pending"` but nothing customer-side creates a refund; the only consumer is the admin sweep `POST /api/refunds/process-refunds` | [order_service.py:1060-1063](../../BackendAPI/services/order_service.py#L1060), [refund_routes.py:22](../../BackendAPI/routes/refund_routes.py#L22) | Refunds depend on someone remembering to hit an admin endpoint; the customer sees no status | Enqueue a refund job on cancellation and expose refund state on the order |
| M22 | `reassign_unassigned_orders` increments `reassigned_count` without changing any state, notifies only the single closest rider, and is not registered as an ARQ cron job | [order_service.py:1134-1223](../../BackendAPI/services/order_service.py#L1134); absent from [worker.py:79-84](../../BackendAPI/worker.py#L79) | An order that the 20 s tiered dispatch fails to place is only retried if a rider happens to toggle availability — otherwise it sits `unassigned` forever | Register it as a cron job (or drop it in favour of re-running `dispatch_order_to_riders`) and log honestly |

---

## 4. LOW / polish

| # | Finding | Location |
|---|---|---|
| L1 | `services/deliverer_service_cancel_patch.py` (141 lines) is imported nowhere — a dead merge artifact, exactly the smell flagged in the brief. Grepping for the same pattern across the repo found **no other** `*_patch.py` / `*_fix.py` / `*_v2.py` files, so it looks like a one-off rather than a habit. | `BackendAPI/services/` |
| L2 | `BackendAPI/test.db` (SQLite test artifact) is tracked in git | repo root |
| L3 | `ALLOWED_ORIGINS = ["*"]` together with `allow_credentials=True` when `ENV=development` — an invalid CORS combination that browsers reject and that hides misconfiguration until production | [main.py:170-185](../../BackendAPI/main.py#L170) |
| L4 | `jwt.decode(..., audience=FRONTEND_CLERK_API_KEY)`: if that env var is unset, audience validation is silently skipped. No `azp` / authorised-party check either | [core/security.py:55-61](../../BackendAPI/core/security.py#L55) |
| L5 | `mpesa_payment` accepts `payment_method: "cash"` and creates the order with no payment gate; the app sends `PaymentMethod \|\| "mpesa"`, so whether cash-on-delivery is a supported customer option needs a product decision | [cart_routes.py:250-273](../../BackendAPI/routes/cart_routes.py#L250), [Cart.tsx:187](../../drop-customer-app/app/(screens)/Cart.tsx#L187) |
| L6 | `Cart.tsx` sends `amount`, `user_id`, and an `Idempotency-Key` header; the backend ignores all three (`OrderRequest` deliberately dropped `amount`) — dead payload that reads as if it were enforced | [Cart.tsx:179-196](../../drop-customer-app/app/(screens)/Cart.tsx#L179) |
| L7 | Response-envelope inconsistency: `/api/vendors` returns `{data,total,limit,offset}`, `/api/nearby_vendors` returns a bare list; every hook papers over it with `json.data \|\| json` | [vendor_routes.py:21](../../BackendAPI/routes/vendor_routes.py#L21) vs `:41`, [useVendors.ts:12](../../drop-customer-app/hooks/queries/useVendors.ts#L12) |
| L8 | `RETAIL_FLAT_FEE_KSH = 50.0` is described as a "strict flat rate" but is used as a base plus 15 KSH/km (20 + 25/km for `keep_my_bottle`) — doc/comment drift | [dispatch_policy.py:13](../../BackendAPI/services/dispatch_policy.py#L13), `:122-125` |
| L9 | `useVendorDirectory` builds its URL by concatenating `${ROUTES.GET_VENDORS}/directory` rather than a named constant | [useVendors.ts:109](../../drop-customer-app/hooks/queries/useVendors.ts#L109) |
| L10 | `/api/contacts/{order_id}` is fetched from a hardcoded template string; it has no entry in `ApiRoutes.ts` | [useOrderContacts.ts:24](../../drop-customer-app/hooks/queries/useOrderContacts.ts#L24) |
| L11 | Root `CLAUDE.md` still said "Vepo" in its title and intro — **fixed in this pass** (the only remaining Vepo reference, as briefed) | `CLAUDE.md:1-3` |

---

## 5. Checklist items that came back clean

Recording these so the next pass does not re-derive them:

- **`npx tsc --noEmit` is clean** — zero errors.
- **Alembic history is linear**: 42 revisions, one base (`7f6a28d33b0e`), one head (`fd28f730de67`). The `3f40437790a9_merge_multiple_heads` revision did its job; there is no branch drift in the chain. Model↔migration *parity* cannot be verified statically — it needs `alembic check` against a live DB, so it is carried into Phase 1e rather than cleared.
- **Dark mode is broadly consistent.** Every screen except `app/(Auth)/index.tsx` references `darkTheme`, and that file is a 5-line `<Redirect>` with no UI. Thinnest coverage is `order-confirmation.tsx`, `PaymentHistory.tsx`, and `settings/NotificationPreferences.tsx`, all of which do theme their containers. No screen is missing theming outright — this is polish, not a finding.
- **Indexes on the hot paths are present**: composite indexes on `Orders(customer_id, created_at)`, `(customer_id, order_status)`, `(vendor_id, created_at)`; GIN indexes on both search vectors; `h3_index_res8` indexed on `Vendor` and `Deliverer`; GiST spatial index migration present.
- **No N+1 in the customer read paths** — `fetch_orders_by_id`, `get_active_order`, `get_last_completed_order`, `fetch_detailed_cart`, and the vendor queries all use `joinedload`/`selectinload`.
- **Stock decrement is race-safe**: `UPDATE ... WHERE stock >= qty RETURNING` with a zero-row check ([order_service.py:814-828](../../BackendAPI/services/order_service.py#L814)).
- **Wallet withdrawal concurrency is handled correctly** — `with_for_update()` on the balance row, and the failure path re-locks rather than trusting the stale closure value.
- **The order-callback endpoint itself is well defended** (shared secret + Safaricom IP allow-list + phone/amount cross-validation + a `FailedWebhook` DLQ). Its problem is the *wrong expected amount* (B1/B2), not missing validation. Contrast with the wallet callback (B6), which has none of this.
- **Error-response shape is consistent server-side**: `HTTPException(detail=...)`, a global 500 handler that never leaks stack traces, and a 422 handler that truncates the body. The inconsistency is on the client, which throws the detail away (M5).
- **Review anti-fraud is solid**: ownership, `delivered`-only, target-must-match-order, and self-rating prevention for both vendor and rider ([review_service.py:12-41](../../BackendAPI/services/review_service.py#L12)).
- **Proof-of-delivery / KYC guardrails were not touched** — they live in `deliverer_service.py` and `vendor_management_service.py`, out of scope for this pass.
