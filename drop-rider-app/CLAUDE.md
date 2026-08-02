# Drop Rider App - AI Developer Guide

## 🎯 Architecture & Business Workflow
The Drop Rider App is the operational engine for delivery logistics. It allows riders to find available orders, navigate to vendors and customers, and resolve delivery disputes (like missing bottles).

Key Business Workflows:
1. **Trip Radar**: The default state for a free rider. The app connects to the WebSocket room `broadcast_to_riders` to listen for new orders. It renders them as cards. 
2. **Accepting an Order**: A race condition can occur if two riders tap "Accept" simultaneously. The `BackendAPI` handles this using `select ... for update` (row-level locking). If a rider loses the race, the API returns a 409 Conflict, and the app must gracefully inform the rider.
3. **Active Delivery**: 
   - State 1: En route to Vendor (Order is `accepted` or `preparing` or `ready`).
   - State 2: At Vendor. Rider taps "Confirm Pickup". Status becomes `picked_up`.
   - State 3: En route to Customer.
   - State 4: At Customer. Rider verifies bottles, takes a photo, and completes delivery. Status becomes `delivered`.
4. **GPS Broadcasting**: While on an active delivery (`picked_up` state), the app must broadcast location to the WebSocket `/ws/rider/{rider_id}` so the customer can watch the dot move.
5. **Bottle Rejections**: If a customer fails to provide the required empty bottles, the rider triggers the `BottleRejection` flow. This involves capturing evidence (a photo) and calling `POST /api/rider/bottle-rejection`. The order is marked `pending_review`.

## 🏗️ Technical Stack
- **React Native / Expo**: SDK 54, React 19.
- **Styling**: NativeWind v4 (Tailwind CSS).
- **State**: TanStack Query v5 for API caching; Zustand for global UI state (like `useActiveOrderStore`).
- **Auth**: Clerk (`@clerk/clerk-expo`). 
- **Location**: `expo-location`.

## 📜 Coding Guidelines

### 1. File Structure & Routing
- Expo Router is used. All screens are in `app/(screens)/`.
- `ActiveDelivery.tsx` is the most complex screen. Logic should be separated into smaller UI components in `components/delivery/`.
- API calls are strictly typed in `API/routes/RiderApiRoutes.ts`.

### 2. Styling (NativeWind v4)
- Maintain dark mode compatibility across all screens.
- Use `SafeAreaView` from `react-native-safe-area-context` to prevent UI clipping on notched devices.

### 3. Location Tracking
`services/locationTracking.ts` owns this. Do not add another `watchPositionAsync`
loop.

- The **durable** path is the `expo-task-manager` task -> SQLite buffer ->
  `POST /api/rider/location-ping`. The WebSocket is a low-latency optimisation on
  top of it, never the only writer: a `sendMessage` with no socket used to be
  swallowed by a `try/catch` that only logged, so every fix produced in patchy
  coverage was lost.
- Reporting starts at `picked_up` and stops at `delivered`/`cancelled`. Tracking
  from acceptance spends battery on the leg to the vendor and shows the rider's
  position to a customer whose order has not been collected.
- `Accuracy.Balanced` at 25 m. `High` at 5 s / 10 m holds the GPS radio open and
  a delivery dot on a city map cannot show the difference.
- Background permission is requested at **first pickup**, after an explanation —
  never at launch. Android 11+ will not offer "Allow all the time" in the same
  prompt as the foreground one, and an unexplained prompt is the main cause of a
  permanent denial. A refusal does not block the delivery; it degrades to
  foreground-only tracking and says so.

### 3a. Every backend call goes through the API client
- React code uses `useApiRequest()` from `API/useApiClient.ts`.
- Code outside React (the Zustand store, the offline replay queue, the location
  task) uses `apiFetch` from `API/apiFetch.ts`, which is handed a token.
- Raw `fetch` is banned everywhere else, and
  `BackendAPI/tests/test_rider_api_client.py` fails the build if one reappears.
  `fetch` has no timeout, no 401 handling and no error normalisation; nineteen
  hooks used to throw the HTTP status at the rider, so "Insufficient balance: KSH
  4,000 is committed as float" arrived as `Earnings fetch failed: 402`.
- Surface the backend's message with `errorMessage(err, fallback)` from
  `API/errors.ts`. Branch on `err instanceof ApiError && err.status`, never on
  `err.response` — an `ApiError` has no `.response`.
- `retry` is `retryTransientOnly`: a 4xx is a refusal, not a dropped packet, and
  retrying a 401 fires the sign-out handler once per attempt.

### 3b. The verification gate fails closed
`app/(screens)/_layout.tsx` blocks unless `kyc_status === "approved"` is
*positively* confirmed. It used to skip its own check whenever the status query
errored, so turning wifi off at the right moment granted access to Trip Radar.
The backend enforces this independently via `get_verified_rider`, but the client
must not rely on that to behave.

KYC status has exactly one reader: `hooks/queries/useKycStatus`. Three screens
used to fetch it separately, and `VerificationWall` kept it in `useState` — on
approval the wall pushed forward while the layout's cache pushed back, a redirect
loop that only broke when the `staleTime` expired.

### 3c. Nothing the rider did offline is deleted silently
`services/offlineQueue.ts` retries on four triggers with exponential backoff. An
action the server refuses on the merits is marked `needs_attention` and shown on
the **Pending Sync** screen with the server's reason — it is not dropped. For a
`delivered` action, dropping it destroys the rider's proof of work and their pay.
Only an explicit tap in that screen discards one.

### 4. Maps keys and Google web services
- The Maps key is **not** in `app.json`. `app.config.js` injects
  `GOOGLE_MAPS_ANDROID_API_KEY` / `GOOGLE_MAPS_IOS_API_KEY` from the environment at
  build time; both are restricted to this package/bundle and to the Maps SDK only.
- Never read the key back at runtime — Expo scrubs it from the public manifest, so
  `Constants.expoConfig?...googleMaps` is always `undefined`.
- Never call a Google web service (Directions, Places, Geocoding) from the client.
  Those keys cannot, and a key that could would be extractable from the binary.
  Call the backend proxy instead. See `docs/maps-architecture.md`.

### 5. Image Uploads
- Proof of Delivery (POD) and Bottle Rejection evidence require photos.
- Use `expo-image-picker` to take the photo, and `expo-image-manipulator` to aggressively compress the image (e.g., width 800, quality 0.7, WebP format).
- Upload the compressed image using `SecureUpload` utility to `POST /api/rider/upload_proof`. This will return an S3 key which is then attached to the `CompleteDelivery` API call.

### 6. Optimistic UI Updates
- When transitioning order statuses (e.g., Accept, Pick Up, Complete), use React Query's `onMutate` to optimistically update the local cache, providing an instant, snappy feel to the rider. Always handle `onError` to rollback the cache if the network request fails.

### 7. Help & support

`app/(screens)/Support.tsx` writes into the admin console's queue via
`hooks/queries/useSupport.ts`. Three things about it are deliberate:

- **It is reachable before verification.** `(screens)/_layout.tsx` lets
  `VerificationWall` *and* `Support` through the KYC gate. A rider on day four of
  a "less than 24 hours" review is exactly the person who needs to ask why, and
  the wall itself links to it.
- **The thread is rendered as given.** Support staff write internal notes in the
  same thread; the server strips them. Never re-add a client-side filter as the
  safeguard — the boundary is the safeguard.
- **`user_type=rider` is on every call.** One Clerk identity can be a rider and a
  customer; the account being acted on is stated, never guessed.

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications.
