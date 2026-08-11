# Drop Customer App - AI Developer Guide

## 🎯 Architecture & Business Workflow
The Drop Customer App is the B2C entry point for the water delivery platform. It interacts with the centralized `BackendAPI` to discover vendors, place orders, and track deliveries. 

Key Business Workflows:
1. **Discovery**: Uses GPS coordinates to query the backend for nearby vendors. The backend uses PostGIS + H3 indexing to filter vendors within a 2.5 km radius (retail) or 15 km radius (wholesale). Both are `Platform_Settings` rows (`retail_max_distance_km` / `wholesale_max_distance_km`), read through `DispatchPolicy`'s accessors — discovery and checkout use the one figure, so a store cannot be orderable and undiscoverable at once.
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
- API calls are strictly typed in `API/routes/ApiRoutes.ts`, which exports exactly
  one route table (`ROUTES`) and one socket origin (`WS_BASE_URL`). **Do not
  hardcode endpoints in components**, and do not add a second table beside it.

### 2. Styling (NativeWind v4)
- Use standard Tailwind utility classes via `className`.
- **Theme Awareness**: The app supports Dark Mode. Always use the `darkTheme` boolean from `UIThemeContext` (or NativeWind dark variants if configured) to style elements conditionally. 
- Example: `className={darkTheme ? "bg-black text-white" : "bg-white text-black"}`
- Brand Colors: Import colors from `constants/brandColors.ts`. Do not use hardcoded hex codes for primary UI elements.

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

### 3. Data Fetching (TanStack Query)
- All data fetching must use Custom Hooks located in `hooks/queries/`.
- Those hooks must go through `useApiRequest()` (from `API/useApiClient.ts`), never
  raw `fetch`. It injects the Clerk JWT, signs the user out on a 401, and converts
  every failure into an `ApiError` whose `message` is the backend's own `detail`.
  The only legitimate raw `fetch` calls are to third-party APIs (Google Places,
  Cloudinary).
- Every backend path lives in `API/routes/ApiRoutes.ts`, in the **one** exported
  table, `ROUTES`. Never build one inline:
  `BackendAPI/tests/test_route_contract.py` parses that file and fails CI if a path
  does not resolve, which is how five 404-ing endpoints were caught. It now also
  fails on a path built outside the table, on an entry no screen calls, and on a
  second table appearing beside `ROUTES`.
- There was a second table — `ApiRoutes`, "kept for screens not yet migrated".
  It declared 41 endpoints of which two were still reached, four screens imported
  it and used nothing from it, and every live endpoint had two declarations free
  to disagree. Resolving paths against the server cannot catch that: both copies
  of a route resolve, and a table nobody imports resolves best of all.
- The socket origin is `WS_BASE_URL` from the same file. `useWebSocket` used to
  derive it by splitting a REST path on `/api/` and calling an unanchored
  `.replace('http', 'ws')`, while `useRiderTracking` derived its own from the env
  var — two answers to one question, and the first fails open to the whole REST
  URL if that path stops containing `/api/`.
- Rely on React Query's caching and refetching mechanisms. Use `queryClient.invalidateQueries` after mutations.

### 3a. Prices come from the server
Never compute an order total on the client. `useCartQuote()` returns the
authoritative, itemised breakdown from `POST /api/cart/quote`; render those
numbers verbatim. A local copy of the pricing formula is how the displayed price,
the amount charged, and the amount recorded on the order came to disagree.

**Render every charge the quote contains.** `debt_settlement` was typed on the
quote, added into `total`, and drawn on no line — so a customer paid an
unexplained difference, the one charge on the cart that is not for anything in
the basket. `BackendAPI/tests/test_customer_money_visibility.py` walks the quote
type and fails the build if a charging field stops being rendered.

`delivery_markup` is the deliberate exception: platform margin folded into the
delivery fee, not a separate charge. Itemising it would double-count on screen.

### 3a-i. The bottle deposit is a deposit

Not a fee, and not first-order-only. `customer_bottle_service` holds it as a
liability the platform returns when the bottles come back, and it is charged on
any order where the customer keeps bottles. The cart said "New Bottle Fee /
Required for first order", which is wrong on both counts and tells the customer
the money is gone.

`BasicUser` carries `bottle_deposit_balance`, `bottles_held` and `debt_balance`.
All three columns existed, were maintained correctly, and reached nobody —
`get_user_details` is filtered by that schema, so the profile came back without
them. The consequence was a screen called **Bottle Wallet** that showed a cash
balance, "days since your first bottle" and "plastic waste saved", and never the
bottles or the deposit, which is the customer's own money.

### 3a-ii. Debt does not block checkout any more

It did, over as little as KSH 30, permanently. Since F-01 an unpaid balance
below `max_customer_debt_before_block` is charged on the next order as
`debt_settlement` and cleared when that order is created — the customer settles
it by carrying on using the platform. Only at the ceiling does `validate_quote`
refuse, with a message naming support.

Never re-implement that decision in the app. The cart renders the line and the
server decides the refusal.


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

**Never re-derive the order total.** `order.total_amount` is what the customer
was charged, frozen at creation. `OrderCard` and `OrderDetail` both used to sum
the component lines instead, and both left out the bottle deposit and any
settled balance — so the card, the detail screen and the M-Pesa message showed
three different numbers for one order.

### 3c. The delivery estimate is the server's, for this customer's distance
`/api/delivery-fee` — already called on the product page for the fee — returns
`estimated_minutes` off the same Haversine distance it prices. The screen
ignored it and derived its own from `vendor.delivery_radius`, which was wrong
twice over: that column is one the vendor typed and dispatch has never read, and
a *radius* is the distance to the edge of the catchment, so every customer saw
the estimate for the furthest possible address regardless of living next door.

`Vendor.delivery_radius` is gone from this app's types. Nothing here should read
it again.

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
