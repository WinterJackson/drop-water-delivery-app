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
- Vendors upload Profile Pictures and Product Images.
- Use `expo-image-manipulator` to aggressively compress images (WebP format, width 800px) before sending to the backend to save bandwidth and S3 storage costs.

### 6. Access Control
- Check the current user's role. A user might be a `Store Owner` or `Staff`.
- `Staff` accounts should have the "Wallet" and "Withdraw" UI elements hidden or disabled.

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications.
