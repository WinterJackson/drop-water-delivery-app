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
- Location tracking requires explicit permissions. Ensure `expo-location` permission requests are handled gracefully, explaining to the rider *why* location is needed.
- Only broadcast WebSocket locations when an order is actively in progress to save battery and reduce server load.

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

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications.
