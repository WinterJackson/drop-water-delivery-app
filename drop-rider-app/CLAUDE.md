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

### 3d. Money rules come from the server, and they are about the *amount*

`GET /api/rider/wallet-summary` returns a `withdrawal` block —
`minimum`, `fee`, `fee_waiver_threshold` — read from `Platform_Settings` by
`settlement_service.withdrawal_terms`, which is the same function the withdrawal
itself calls. Never restate any of them as a literal.

`Cashout.tsx` had all three hardcoded (500, 15, 1000), so the console could
change what a rider was charged and not what they were told. The *rule* was also
wrong: `fee_for` waives the fee on the **amount withdrawn**, and the screen
measured the **balance held** — a progress bar of `balance / threshold` under
"Keep KSH X more in your float balance to unlock zero-fee withdrawals". A rider
holding KSH 1,200 who withdrew KSH 600 saw "Zero Network Fee Applied!" and was
charged. It also inverts the waiver's purpose: the platform pays one M-Pesa B2C
tariff per disbursement, so it wants fewer, larger withdrawals — not larger idle
balances.

Measure progress against `available_for_withdrawal`, never `wallet_balance`.
Float committed to open cash orders cannot be withdrawn at any size.

### 3e. Platinum is two settings, not two literals

`platinum_min_deliveries` over `platinum_window_days`, both rows in
`Platform_Settings` and both read by `jobs/rider_tier_job.py`. The *reward*
(`gig_platinum_rider_commission_rate`) had always been configurable while the
*requirement* was `>= 20` over `days=7` in the job, with `Performance.tsx`
stating `20` and "7 days" of its own — so raising the bar would have kept
quoting riders the old number while demoting them against the new one.

`GET /earnings` returns `platinum_target`, `platinum_window_days` and
`deliveries_in_window`, and counts that window with the same setting the job
evaluates on. Counting progress over a different period from the one that
decides the tier is how a rider hits the target on screen and is demoted anyway.

### 3f. Bottle debt has an age, and the rider can see it

`GET /api/rider/bottle-debt` carries `held_days` and `is_stale` per vendor, plus
`stale_after_days` for the platform's own threshold
(`admin_bottle_service.STALE_AFTER_DAYS`). The debt list is sorted **oldest
first**, not largest first — a debt about to be escalated should not sit under a
bigger one that is fine.

The rider was shown the quantity and never the clock, while
`stale_asset_monitor` swept nightly and the console flagged them at 14 days. The
first they knew of the threshold was being flagged against it.

`BackendAPI/tests/test_withdrawal_terms_surface.py` fails the build if any of
these figures becomes a literal again.

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

### The operation radius comes from the server
`GET /rider/profile` returns `operation_radius_km` — the radius dispatch
actually searches from a rider's base, 2.5 km for retail work and 15 km for a
wholesale fleet rider. `OperationBase.tsx` draws its circle from it, sizes the
map span from it, and states it in words from it.

All three were hardcoded: a `2` km polygon, a `0.045` map delta "tuned to always
show the full 2KM radius circle", and the sentence "you will receive requests
from vendors within a 2KM radius". A business figure written into an app is one
an administrator cannot move — and here moving it would have left a rider
looking at a map, and reading a promise, that were both a kilometre short of
what the platform was doing. Same rule, same reason, as the withdrawal fee.

### Components are declared at module scope

A component defined inside another component's render body is a new function
object — and therefore a new *type* — on every render, so React unmounts its
subtree and mounts a fresh one instead of updating it. A `TextInput` inside one
is destroyed and rebuilt on every keystroke: focus lost, keyboard dismissed, one
character per tap. `Profile.tsx` and `rider/VehicleDetails.tsx` both shipped
that way — the two screens where a rider types their phone number and their
number plate.

Pass what it closed over — the theme, the edit mode, the form and its setter —
as props. `BackendAPI/tests/test_component_identity.py` fails the build on a
nested component containing a `TextInput` or a hook.

### A forced update reaches this app too

`utils/appUpdate.ts` is called once from the root layout. It used to exist only
in the customer app, which had it backwards: a customer on a stale build sees
wrong prices, whereas a rider on one is mid-delivery, holding somebody's water
and somebody's cash — and is the person least likely to go looking for an app
store.

`GET /api/app-version?app=rider` answers per app — the three ship separately and
their versions move independently, so one floor for all three would lock out a
build that is current. The floor is `MIN_APP_VERSION_RIDER` in the API's
environment; unset means no floor.

### Session teardown
`hooks/useSessionCleanup.ts` is mounted once in the root layout and wipes local
state whenever Clerk's session ends. Do not rely on the sign-out handlers alone:
sessions also end without anyone tapping "Sign out" — every query signs the user
out on a 401, and Clerk ends a revoked session on its own. Those routes left the
cache fully populated for the next account on the device.

`clearPushToken()` is the exception that must stay in the handlers: the endpoint
is authenticated, so it has to run *before* `signOut()`. Skipping it leaves the
device receiving the previous account's notifications.

It must send **`?app_type=rider`**, and it is declared with the path in
`RiderApiRoutes.DeletePushToken` for that reason. The endpoint defaults to
`customer`: without the parameter it looked up a `User` row by this clerk id,
found none — a rider has no `User` row — cleared nothing, committed, and
answered `200`. So every rider sign-out *looked* like it worked while
`Deliverer.push_token` stayed registered. Riders share devices more than anyone
else on this platform, which is the whole reason the call exists: the rider who
signed out kept receiving delivery offers, and so did the next rider to sign in
on the same handset. `BackendAPI/tests/test_session_teardown.py` fails the build
if any app clears the wrong kind of account, or signs out before clearing.


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

**The float a cash order commits** is `vendor_net + platform_total` — summed
with `sumMoney` and compared with `compareMoney`. `TripRadar` had six copies of
that expression in float, deciding both what the rider was told and whether the
Accept button worked. The server refuses regardless (`cod_policy`); the screen
only decides what it says before they tap.

