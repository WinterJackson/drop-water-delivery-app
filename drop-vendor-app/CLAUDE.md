# Drop Vendor App - AI Developer Guide

## 🎯 Architecture & Business Workflow
The Drop Vendor App allows water providers (Retail and Wholesale) to manage their daily operations. It connects to the `BackendAPI` to manage catalog products, monitor incoming orders, and handle financial payouts.

Key Business Workflows:
1. **Catalog Management**: Vendors can create and edit products. If the vendor is a `wholesale_b2b`, the app ensures MOQ (Minimum Order Quantity) logic is displayed. 
2. **Order Fulfillment**:
   - `NEW_ORDER`: Incoming order, status `pending`. Vendor must confirm they have stock and tap "Accept".
   - `accepted`: Vendor prepares the order.
   - `ready`: Order is ready for pickup. This state is critical because it tells the Backend to finalize rider dispatch.
3. **Empty Bottle Management**: The "Receive Bottles" workflow allows the vendor to verify empty bottles returned by riders. If a rider claims to return 4 bottles but only brings 3, the vendor initiates a dispute (`bottle_rejection`).
   - `BottleReconciliation.tsx` answers *who owes me what now* — a running
     balance per rider, read from the ledger rather than the registry so a rider
     who took a radar order without ever registering is still counted.
   - `BottleLedger.tsx` answers *when did that happen, against which order, and
     did I already take those back*. It is the evidence behind the balances, and
     it is what a vendor disputing a rider's count points at. The endpoint
     (`GET /api/vendor/bottle-ledger`) shipped with nothing in either app calling
     it, so the platform's largest non-cash asset had a live balance and no
     history. Rider **names** are resolved in the route, not in
     `get_ledger_history`, which the rider app also calls.

4. **Accepting a cash order costs float.** `update_order_status` refuses with a
   402 naming the exact shortfall when `wallet_balance − committed_cash_float`
   is under the order's `platform_total`. The order detail now shows that
   comparison *before* the tap, from the same two figures the refusal uses —
   discovering it by failing in front of a waiting customer is not a workflow.
   The numbers need `view_finances`; without it the rule is stated without them.
4. **Financials (Reconciliation)**: When an order is delivered successfully, the platform automatically takes its commission (5% retail, 2.5% wholesale) + service fees and deposits the rest into the Vendor's virtual Wallet. The vendor uses the `RequestPayout` API to move funds to their M-Pesa account via B2C.

## 🏗️ Technical Stack
- **React Native / Expo**: SDK 54, React 19.
- **Styling**: NativeWind v4 (Tailwind CSS).
- **State**: TanStack Query v5 for API caching; Zustand for global UI state.
- **Auth**: Clerk (`@clerk/clerk-expo`). 

## 📜 Coding Guidelines

### 1. File Structure & Routing
- Expo Router is used. All screens are in `app/(screens)/`.
- Deeply nested settings/management pages (e.g., `ManageStaff.tsx`) should maintain consistent navigation headers using `Stack.Screen`.
- API calls are strictly typed in `API/routes/VendorApiRoutes.ts`.

### 2. Styling (NativeWind v4)
- Consistent use of BRAND colors (found in `constants/brandColors.ts`).
- Standardized padding and margins: Use `p-4`, `m-2`, etc.
- Dark mode compatibility is required for all text and background elements. 

#### Typography

`Text` and `TextInput` come from `@/components/ui/Text`, never from
`react-native`. React Native has no cascade — an element that names no family
renders in the OS font — so the wrapper attaches `font-sans` whenever the class
string names none. It decides at render time because a class string is often
built elsewhere (`<Text className={labelStyle}>`), where no static rewrite could
reach it.

- **Never `font-bold`.** A bare weight utility sets `fontWeight` and no family,
  so the OS thickens its own font: right-looking in review, different on every
  handset. Use `font-sans-bold` / `-semibold` / `-medium` / `-extrabold`, which
  name Karla's real files. Same for `fontWeight` in a `StyleSheet` — name the
  face (`fontFamily: 'Karla_700Bold'`).
- **Fredoka is for headings and stops at 600.** `font-heading`,
  `font-heading-medium`, `font-heading-semibold` — a screen, sheet or modal
  title, or an entity's name. There is no `font-heading-bold`.
- **Figures stay in Karla.** A balance, total or count is not a heading.
- `font-mono` for references and identifiers.

Every face must be registered in `app/_layout.tsx`; naming an unregistered one
falls back to the system font in silence. `BackendAPI/tests/test_typography.py`
fails the build on all of the above.

### 3. Order Data Refreshing
- Use WebSockets (`/ws/orders/vendor/{vendor_id}`) to listen for status changes.
- Upon receiving a WS event, trigger `queryClient.invalidateQueries({ queryKey: ["vendorOrders"] })` to fetch the latest state rather than manually mutating the local cache (to prevent desyncs).

### 4. Maps keys and Google web services
- The Maps key is **not** in `app.json`. `app.config.js` injects
  `GOOGLE_MAPS_ANDROID_API_KEY` / `GOOGLE_MAPS_IOS_API_KEY` from the environment at
  build time; both are restricted to `com.drop.vendor` and to the Maps SDK only.
- Never read the key back at runtime — Expo scrubs it from the public manifest, so
  `Constants.expoConfig?...googleMaps` is always `undefined`.
- Never call a Google web service (Directions, Places, Geocoding) from the client.
  Those keys cannot, and a key that could would be extractable from the binary.
  Call the backend proxy instead. See `docs/maps-architecture.md`.
- Getting device coordinates: `getLastKnownPositionAsync()` first, then
  `getCurrentPositionAsync({ accuracy: Balanced })`. A bare `getCurrentPositionAsync({})`
  defaults to the highest accuracy and can block for 30s on a cold GPS fix.

### 5. Image Handling
- Vendors upload Profile Pictures and Product Images. Both go through
  `Helpers/imageUpload.ts` → `POST /api/vendor/upload-image` → S3, and the
  **key** is stored, never a URL; the response schemas presign it for 15 minutes
  on the way out.
- Never post to Cloudinary. The app shipped an *unsigned* preset
  (`upload_preset: 'drop_uploads'`), which is a public write endpoint for anyone
  who unzips the APK, and revoking it means deleting it for every vendor at once.
- Never store an image *in* a column. `profile_pic` used to receive a
  `data:image/jpeg;base64,…` string a megabyte or two long, which was then
  returned inside every profile response.
- **Editing** a product must omit `image_url` when the image has not changed. The
  API returns a presigned URL; sending it back stores an expiring URL as the
  product's permanent image.
- `expo-image-manipulator` compresses to WebP at width 800 before upload.

### 4a. The service radius is reported, not set
`MyMap.tsx` shipped a stepper writing `Vendor.delivery_radius`, and **nothing on
the dispatch path has ever read that column** — how far an order travels is
`retail_max_distance_km` / `wholesale_max_distance_km` on the console. So the
control changed no deliveries, which is why placing a test order after moving it
looked correct.

It was not harmless. Two screens rendered the column: this map drew its circle
from it, and the *customer's* product page derived the delivery estimate from
it — from the radius rather than the distance, so every customer of the store
saw the time to the edge of the catchment. A shop setting 15 km quoted
"45 min – 1.5 hrs" to the flat upstairs. The only thing a vendor could achieve
with the control was making their own store look slower to everyone browsing it.

The real figure arrives as `useStorefront().limits.delivery_radius_km`, beside
the pause presets and the order-minimum ceiling, for the same reason they do:
a number the server owns, stated once. It is **2.5 km for retail refill and
15 km for wholesale**, the same for every store.

`Vendor.delivery_radius` no longer exists — dropped in `c7d2e94a6f18` — and
`BackendAPI/tests/test_vendor_cannot_set_the_radius.py` fails the build if the
API starts accepting it, if the model or schemas declare it again, or if any app
states a radius of its own.

### 5a. Low stock
`Product.low_stock_threshold` is per product — a shop selling 200 refills a day
and one selling a dispenser a month cannot share a number — and 0 disables the
warning. `low_stock_notified_at` latches the notification so the vendor is told
once per crossing, not once per unit sold below the line; restocking clears it.
The dashboard returns `low_stock_products`.


### Money is a decimal string

Every monetary field the backend sends is a **decimal string**, not a number —
`"1234.50"`. The columns behind them are Postgres `NUMERIC` and Python
`Decimal`, and `BackendAPI/utils/money.py` serialises them that way for one
reason: parsing them into a JS number to add or format them puts back exactly
the binary floating-point error the backend goes out of its way to avoid.

`utils/money.ts` is the only place digits are touched:

- `formatMoney(v)` → `"KSH 1,234.50"`; `formatMoneyShort(v)` → `"KSH 1,235"`.
- `sumMoney([...])`, `subtractMoney(a, b)`, `multiplyMoney(v, count)` — all in
  integer cents via `BigInt`.
- `compareMoney(a, b)`, `isZeroMoney(v)`, `isNegativeMoney(v)` — never
  `Number(a) > Number(b)`, and never `{fee > 0 && …}` on a money field.
- `moneyRatio(part, whole)` is the **only** sanctioned conversion to a number,
  and only for a progress bar's width or a "near the cap" threshold — output
  that is a pixel count, not a figure anybody reads.

`BackendAPI/tests/test_money_serialisation.py` fails the build if a money field
goes back to a float on the server side.

**Never re-derive the order total.** `order.total_amount` is the frozen figure.
The order detail summed the lines above it, omitting the deposit and any settled
balance, so the store's screen disagreed with the customer's about one order.

### 6. Access Control
- The server decides. `get_vendor_owner` / `get_owned_store` gate every route
  that changes what the business *is* or moves its money; hiding a button is a
  courtesy, not a control. Every owner-only restriction used to live in a
  `router.replace()` inside a React component — six of them — and a staff token
  calling the API directly could rename the store, change its payout account, or
  withdraw its balance to their own M-Pesa number.
- Branch on `err instanceof ApiError && err.type === "owner_only"`, never on the
  wording of the sentence. `BackendAPI/tests/test_vendor_owner_enforcement.py`
  fails the build if a new vendor route is added without being classified.
- `Staff` accounts should still have the "Wallet" and "Withdraw" UI hidden — the
  server refuses them, and offering an action that always fails is bad UX.

### 6d. Staff have capabilities, not a role
A staff member may be trusted with orders but not the catalogue. `GET /profile`
returns `permissions` for the signed-in caller — owners get all four spelled out —
and `useCan(PERMISSIONS.manageProducts)` is how a screen decides whether to
render a control. Gate on the capability, never on `role !== "staff"`: that was
the old all-or-nothing model, and it is what let anyone handed the till also
reprice the products.

- `manage_orders` · `manage_products` · `manage_bottles` · `view_finances`.
- The list of capabilities and their labels ships **with** the staff roster
  (`available_permissions`), so `ManageStaff` can never offer one the server has
  dropped or miss one it has added.
- `useWalletSummary(enabled)` is gated on `view_finances` — asking without it
  would 403 on every open of the wallet screen.
- `role === "staff"` is still correct for the four owner-only *screens*
  (OwnerProfile, StoreProfile, PayoutSettings, OperatingHours, ManageStaff):
  those are not capabilities, they are things only an owner may ever do. It is
  also correct for *navigation to* them — `Profile.tsx` and `QuickActions.tsx`
  hide the links, because hiding a link to a screen that would bounce you is the
  same decision as the screen bouncing you.

**Gate where the button is, not where the mutation is declared.**
`Orders.tsx` held `useCan(PERMISSIONS.manageOrders)` while `OrderDetail/[id].tsx`
— the screen the six order buttons actually live on — checked nothing, so a
staff member with only `manage_bottles` was offered Accept, Reject, Start Prep,
Mark as Ready, Cancel and Assign Fleet, and every one 403'd at the tap.

- A screen whose **whole purpose** is one gated action refuses at the door with
  `<CapabilityGate permission={…}>`. The product forms are the case it exists
  for: filling in a name, a price, a stock count and an image and only *then*
  being told you were never allowed to is the worst version of this.
- A screen with a **mix** of permitted and gated controls keeps rendering and
  gates the individual buttons. The order detail is readable by anyone who can
  see the order; only its writes are gated.
- `CapabilityGate` fails **open** while the profile loads. That is the opposite
  of the rider's `VerificationWall`, on purpose: the KYC gate protects the
  platform from an unverified rider, so an errored status is not permission,
  whereas this one only decides whether to show a form the server refuses
  anyway. Refusing on absent data would lock out an owner on a slow connection
  and protect nothing.
- `BackendAPI/tests/test_vendor_capability_ui.py` fails the build if a mutating
  block loses its check.

### 6e. Payouts do not exist as an endpoint
Only the M-Pesa B2C **callback** router is mounted under `/api/payouts`;
`main.py` says so. Cashouts go through `WalletWithdraw`
(`POST /api/wallet/withdraw`) and their history is the wallet ledger, which
carries `status`, `mpesa_receipt_number` and `failure_reason`. `RequestPayout`
and `GetPayouts` were declared in `VendorApiRoutes.ts`, unused, pointing at
routes that would 404 — do not add them back.

`failure_reason` is rendered on a failed row. "Insufficient balance in the
utility account" and "that number is not registered for M-Pesa" need very
different responses from the vendor, and a red "failed" with the balance
silently restored told them neither.

### 6a. Every backend call goes through the API client
- React code uses `useApiRequest()` from `API/useApiClient.ts`. Code outside
  React (push registration, the upload helper) uses `apiFetch` from
  `API/apiFetch.ts`, which is handed a token.
- Raw `fetch` is banned, and `BackendAPI/tests/test_vendor_api_client.py` fails
  the build if one reappears. `fetch` has no timeout, no 401 handling and no
  error normalisation; forty-eight of them threw the transport's own words at the
  vendor ("Failed to fetch orders"), and several checked `res.ok` and did nothing
  when it was false.
- Surface the backend's message with `errorMessage(err, fallback)` from
  `API/errors.ts`. Never `err.response?.data?.detail` — an `ApiError` has no
  `.response`, so that path always falls through to the generic string.
- `retry` is `retryTransientOnly`: a 4xx is a refusal, not a dropped packet.

### 6b. A `Vendor` row is a store, not an account
One Clerk identity may own several. The **active store** is chosen in
`stores/activeStoreStore.ts`, persisted, and sent by the API client as
`X-Store-Id` on every request; the backend validates it against the caller's own
stores and answers 404 for one they do not own.

- Never re-resolve a vendor from the clerk id in a route — take the store from
  `get_active_store` / `get_owned_store`. The old helper's fallback is
  `clerk_id = … OR staff_clerk_id = …` with no store id, which is the ambiguity
  the dependency removes.
- `allStores: true` opts a request out of scoping. Exactly one call may use it:
  `GET /api/vendor/stores`, whose purpose is to return the others.
- `useStoreScopedCache` empties the query cache on a switch. Requests are scoped
  by header, so `["vendorOrders"]` means "the active store's orders" and React
  Query cannot tell the two apart on its own.
- Never `scalar_one_or_none()` against a vendor lookup. It raises
  `MultipleResultsFound` on the second store, and `profile-status` /
  `push-token` — which the app calls before anything else — turned startup into
  a 500 the moment an owner opened a branch.

### 6c. Paused orders are not a UI edge case
`mismatch_pending` and `pending_review` are reachable in ordinary operation: a
rider flags a damaged empty or reports the customer understated their floor.
Statuses live in **one** place, `constants/orderStatus.ts` — two divergent colour
maps in two screens is how both states came to be missing from both.
`GET /api/vendor/orders/{id}/review` carries the rider's reason and photos.

### 7. Help & support

`app/(screens)/Support.tsx` writes into the admin console's queue via
`hooks/queries/useSupport.ts`, and it is **not owner-only**.

- The ticket is filed against the **active store**. The API client already sends
  `X-Store-Id`, and `support_routes._resolve_account` resolves vendors through
  the same store resolver every other vendor route uses — so an owner with two
  branches raises it against the branch they are looking at, not whichever was
  created first.
- **Staff can raise one too.** They hold no `clerk_id` on any `Vendor` row, so a
  plain lookup would answer "you don't have a vendor account" to the person
  standing in the shop when a rider turns up with the wrong bottle count. They
  see the store's support thread exactly as they see its orders.
- The thread is rendered as the server gives it; internal notes are stripped
  server-side.

### Components are declared at module scope

A component defined inside another component's render body is a new function
object — and therefore a new *type* — on every render, so React unmounts its
subtree and mounts a fresh one instead of updating it. A `TextInput` inside one
is destroyed and rebuilt on every keystroke: focus lost, keyboard dismissed, one
character per tap. `OwnerProfile.tsx`, `StoreProfile.tsx` and
`business/PayoutSettings.tsx` all shipped that way — the last being where a
vendor types the bank account their money is paid into, up to twelve digits, one
tap per digit.

Pass what it closed over — the theme, the edit mode, the form and its setter —
as props. `BackendAPI/tests/test_component_identity.py` fails the build on a
nested component containing a `TextInput` or a hook.

### A forced update reaches this app too

`utils/appUpdate.ts` is called once from the root layout. It used to exist only
in the customer app, which had it backwards: a customer on a stale build sees
wrong prices, whereas a vendor on one is open for business, accepting orders the
build may price or dispatch wrongly.

`GET /api/app-version?app=vendor` answers per app — the three ship separately and
their versions move independently, so one floor for all three would lock out a
build that is current. The floor is `MIN_APP_VERSION_VENDOR` in the API's
environment; unset means no floor.

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications. It must pass
`?app_type=vendor` — the endpoint defaults to `customer` and, without it, cleared
a `User` row that does not exist for this clerk id while the vendor's token
stayed registered. That query string is declared with the path in
`VendorApiRoutes.DeletePushToken`, not written at the call site.

**The remembered store is cleared in `useSessionCleanup`, not only in the
handler.** `activeStoreId` is persisted separately from the query cache, so
`queryClient.clear()` never touched it — and the handler that did clear it is
the path nobody takes. On the 401 route the id survived, and the next account to
sign in on that till sent an `X-Store-Id` it does not own, which the backend
answers `404` for on every scoped request. A successful sign-in followed by
universal 404s reads as the platform being down, not as stale state.

### 6f. The route table includes the paths the app starts with
`profile-status`, both push-token calls and `contacts/{id}` were built inline
off `process.env.EXPO_PUBLIC_BACKEND_BASE_URL`, so the one path the app cannot
start without was the one path never checked against the server. An
interpolated base URL is not configuration, it is a path built outside the
table; `test_no_screen_builds_a_backend_path_inline` now matches a `}` before
`/api/` as well as a quote, which is what found the other two.
