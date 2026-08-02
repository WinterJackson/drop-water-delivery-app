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

### 5a. Low stock
`Product.low_stock_threshold` is per product — a shop selling 200 refills a day
and one selling a dispenser a month cannot share a number — and 0 disables the
warning. `low_stock_notified_at` latches the notification so the vendor is told
once per crossing, not once per unit sold below the line; restocking clears it.
The dashboard returns `low_stock_products`.

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
  those are not capabilities, they are things only an owner may ever do.

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
stayed registered. Also clear the remembered store (`useActiveStore.clear()`), or
the next account on the device sends an `X-Store-Id` it does not own.
