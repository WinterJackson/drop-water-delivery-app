# Drop Customer App - AI Developer Guide

## 🎯 Architecture & Business Workflow
The Drop Customer App is the B2C entry point for the water delivery platform. It interacts with the centralized `BackendAPI` to discover vendors, place orders, and track deliveries. 

Key Business Workflows:
1. **Discovery**: Uses GPS coordinates to query the backend for nearby vendors. The backend uses PostGIS + H3 indexing to filter vendors within a 2km radius (retail) or 15km radius (wholesale).
2. **Checkout**: 
   - Before checking out, the app must ensure the user has selected an active delivery location.
   - Pushes cart items and location to the backend.
   - Triggers M-Pesa STK push.
   - Polls `GET_ORDERS` to see when the payment callback arrives and order status shifts from `pending` (unpaid) to `unassigned` (paid, awaiting rider).
3. **Tracking**:
   - Once the order is `picked_up`, a WebSocket connects to `/ws/track/{order_id}`.
   - Rider coordinates are received as `{ "lat": x, "lng": y }`.
   - The map interpolates the marker for smooth movement.

## 🏗️ Technical Stack
- **React Native / Expo**: SDK 54, React 19.
- **Styling**: NativeWind v4 (Tailwind CSS).
- **State**: TanStack Query v5 for API caching; Zustand for global UI state (like Theme, Location).
- **Auth**: Clerk (`@clerk/clerk-expo`). Use `getToken()` to attach the `Authorization: Bearer <jwt>` to API calls.

## 📜 Coding Guidelines

### 1. File Structure & Routing
- Expo Router is used. All screens are in `app/(screens)/`.
- Components go in `components/`. Sub-folders should organize by feature (`dashboard/`, `common/`, `ui/`).
- API calls are strictly typed in `API/routes/ApiRoutes.ts`. **Do not hardcode endpoints in components.**

### 2. Styling (NativeWind v4)
- Use standard Tailwind utility classes via `className`.
- **Theme Awareness**: The app supports Dark Mode. Always use the `darkTheme` boolean from `UIThemeContext` (or NativeWind dark variants if configured) to style elements conditionally. 
- Example: `className={darkTheme ? "bg-black text-white" : "bg-white text-black"}`
- Brand Colors: Import colors from `constants/brandColors.ts`. Do not use hardcoded hex codes for primary UI elements.

### 3. Data Fetching (TanStack Query)
- All data fetching must use Custom Hooks located in `hooks/queries/`.
- Those hooks must go through `useApiRequest()` (from `API/useApiClient.ts`), never
  raw `fetch`. It injects the Clerk JWT, signs the user out on a 401, and converts
  every failure into an `ApiError` whose `message` is the backend's own `detail`.
  The only legitimate raw `fetch` calls are to third-party APIs (Google Places,
  Cloudinary).
- Every backend path lives in `API/routes/ApiRoutes.ts`. Never build one inline:
  `BackendAPI/tests/test_route_contract.py` parses that file and fails CI if a path
  does not resolve, which is how five 404-ing endpoints were caught.
- Rely on React Query's caching and refetching mechanisms. Use `queryClient.invalidateQueries` after mutations.

### 3a. Prices come from the server
Never compute an order total on the client. `useCartQuote()` returns the
authoritative, itemised breakdown from `POST /api/cart/quote`; render those
numbers verbatim. A local copy of the pricing formula is how the displayed price,
the amount charged, and the amount recorded on the order came to disagree.

### 3b. Maps keys and Google web services
- The Maps key is **not** in `app.json`. `app.config.js` injects
  `GOOGLE_MAPS_ANDROID_API_KEY` / `GOOGLE_MAPS_IOS_API_KEY` from the environment at
  build time; both are restricted to this package/bundle and to the Maps SDK only.
- Never read the key back at runtime — Expo scrubs it from the public manifest, so
  `Constants.expoConfig?...googleMaps` is always `undefined`.
- Never call a Google web service (Directions, Places, Geocoding) from the client.
  Those keys cannot, and a key that could would be extractable from the binary.
  Call the backend proxy instead. See `docs/maps-architecture.md`.

### 4. Null Safety & Error Handling
- Always use optional chaining (`?.`) when rendering API data.
- Numbers/Prices should be formatted safely. e.g., `(item.price || 0).toLocaleString()`.
- Use the central `Toast` component (`lib/toast.ts`) for user feedback, and
  `Popup` (`lib/popup.ts`) for confirmations — both are theme-aware. Native
  `Alert` is reserved for the blocking forced-update prompt in `utils/appUpdate.ts`.
- Surface the backend's message: `Toast.error("…", errorMessage(err))` using
  `errorMessage` from `API/errors.ts`. Never show a bare status code.

### 4a. Errors thrown by the API client
`useApiRequest` normalises **every** failure into an `ApiError` — a plain `Error`
subclass with `status`, `detail`, `type` and a presentable `message`. It has no
`.response`, so `error.response.data.type` is always `undefined`. Reading it that
way silently disabled the vendor-conflict prompt on the product page and hid
every backend message behind a generic fallback.

- Branch on the error with the helpers, never on its shape:
  `isVendorConflict(err)` / `vendorConflictInfo(err)` from `hooks/queries/useCart`.
- Surface the message with `errorMessage(err, fallback)`.
- `retry` uses `retryTransientOnly(n)` from `API/errors`: a 4xx is a refusal, not
  a dropped packet, and retrying a 401 fires the sign-out handler once per attempt.

### 4b. Order statuses live in one place
`ORDER_STATUS_GROUPS` / `matchesOrderFilter` / `CANCELLABLE_ORDER_STATUSES` in
`hooks/queries/useOrders` are the only place statuses are grouped. Screens that
listed them inline drifted: the Orders filters covered neither `preparing` nor
`ready`, so an order being packed matched no filter and showed no action.

### 5. Authentication Flow
- Clerk handles session state.
- Protected routes are wrapped in an authenticated layout.
- The backend expects the Clerk JWT in the `Authorization` header. Use the custom `useApiClient` hook to automatically inject the token.

### 6. Component Design
- Prefer functional components with `React.memo` if they receive complex props in lists.
- Avoid large monolithic screens. Break down `app/(screens)/xxx.tsx` into smaller chunks in `components/`.
- Touchables: Prefer using `PressableScale` over standard `TouchableOpacity` to provide a premium, animated tactile feel.

### 7. Help & support

`app/(screens)/Support.tsx` writes into the admin console's queue via
`hooks/queries/useSupport.ts`.

- **Opened with `?orderId=`** from `OrderDetail`, it arrives with the order
  attached and the category pre-set. "Something went wrong with *this* order" is
  the commonest reason anyone contacts support and the worst moment to make them
  hunt through Settings.
- The server checks that order belongs to the caller and answers **404** if it
  does not, so an id typed by hand is not a way to ask about somebody else's
  delivery.
- The thread is rendered as the server gives it. Internal notes are stripped
  server-side; do not add a client-side filter as the safeguard.

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications.
