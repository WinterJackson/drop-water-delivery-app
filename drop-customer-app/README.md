# Drop Customer App 💧

> The consumer app for the Drop platform. Find a nearby water station, order a
> refill or a wholesale load, pay with M-Pesa, and watch the rider arrive.

---

## 📱 What it does

| Area | What it covers |
|---|---|
| **Discovery** | Nearby stores from the device's location, filtered by what can actually reach you |
| **Cart and checkout** | Saved addresses, an itemised quote from the server, M-Pesa STK Push |
| **Live tracking** | The rider's marker moving on the map, over WebSocket |
| **Empties** | Quick Swap — hand back your empties when the delivery arrives |
| **Wallet and loyalty** | Welcome discount, cashback, repeat-order incentives |
| **Ratings** | Rate the store and the rider once the order lands |
| **Support** | Raise a ticket that lands in the operations console, with the order already attached |

Full theming support: dark mode is a first-class path, not an afterthought.

---

## 💸 Prices come from the server. Always.

**Never compute an order total on the client.** `useCartQuote()` returns the
authoritative itemised breakdown from `POST /api/cart/quote`; render those
numbers verbatim.

A local copy of the pricing formula is precisely how the displayed price, the
amount charged, and the amount recorded on the order came to disagree. On the
backend there is exactly one function that prices an order, one value pushed to
M-Pesa, and one value written to the row — and a test asserts all three match
across every combination of vendor type, surge window, first-order state, wallet
credit and delivery type.

Bottle deposits, service fees, delivery pricing and the welcome discount are all
rows in `Platform_Settings`, editable from the operations console and live here
on the next quote. Nothing in this app hard-codes a shilling.

---

## 🛠️ Tech stack

React Native · [Expo SDK 54](https://expo.dev/) · React 19 ·
[Expo Router](https://docs.expo.dev/router/introduction/) ·
[NativeWind v4](https://www.nativewind.dev/) ·
[TanStack Query v5](https://tanstack.com/query/latest) ·
[Zustand](https://zustand-demo.pmnd.rs/) · [Clerk](https://clerk.com/) ·
`react-native-maps` · `socket.io-client` · `react-native-reanimated`

---

## 🚀 Getting started

```bash
pnpm install
cp .env.example .env      # fill in
pnpm start                # a = Android, i = iOS
npx tsc --noEmit          # before every push
```

### `.env`

```env
EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
EXPO_PUBLIC_BACKEND_BASE_URL="http://10.0.2.2:8000"

# Native Maps SDK keys — build-time only, injected by app.config.js into the
# manifest and plist. Deliberately NOT EXPO_PUBLIC_*: those are inlined into the
# JS bundle and readable by anyone who unzips the APK. One key per platform,
# because a Google key carries exactly one application restriction.
GOOGLE_MAPS_ANDROID_API_KEY=...   # restricted to com.drop.customer + SHA-1
GOOGLE_MAPS_IOS_API_KEY=...       # restricted to bundle id com.drop.customer
```

`10.0.2.2` is the Android emulator's alias for the host machine. On a physical
device use your computer's LAN address — `localhost` reaches the handset, not
your laptop.

> **Never commit a Google key.** `app.json` carries none; `app.config.js` reads
> the two above from the environment, with EAS secrets in CI. See
> [docs/security/google-api-key-rotation.md](../docs/security/google-api-key-rotation.md).

---

## 🔑 Signing in to test it

| | |
|---|---|
| Email | `customer+clerk_test@example.com` |
| Password | `Drop2026!!` |
| Verification code | `424242` |

Set up as Amina Wanjiru in Ngong Town, with a KSH 500 wallet balance and the
**welcome offer unused** — so the first order you place exercises the busiest
path in pricing: a bottle deposit, 30% off it, then wallet credit against the
remainder, in that order.

Both test stores sit within the 2 km retail radius of this address, so discovery
returns something. The full roster, including the wholesale store and the five
admin roles, is in the [root README](../README.md#-test-accounts).

## 📂 Structure

```
drop-customer-app/
├── app/
│   ├── (Auth)/           # Sign-in, OTP
│   ├── (screens)/        # Dashboard, Map, Cart, Orders, OrderDetail, Wallet, Support
│   └── _layout.tsx       # Providers, session cleanup
├── API/
│   ├── useApiClient.ts   # The only way React code talks to the backend
│   ├── errors.ts         # ApiError, errorMessage, retryTransientOnly
│   └── routes/ApiRoutes.ts   # Every backend path, in one place
├── components/
│   ├── common/           # Bento grids, lists
│   ├── dashboard/
│   └── ui/               # Buttons, inputs, skeletons, PressableScale
├── constants/            # brandColors.ts, images, icons
├── context/              # UIThemeContext
├── hooks/
│   ├── queries/          # TanStack Query hooks — useCart, useOrders, useCartQuote…
│   └── useWebSocket.ts
├── stores/               # Zustand
└── lib/                  # toast.ts, popup.ts, formatting
```

---

## 🔄 How it actually works

### Finding a store

The device's coordinates go to the backend, which filters with H3 res-8 bucketing
and then PostGIS `ST_DWithin` for the exact pass. Retail stores serve 2 km;
wholesale serves 15 km. A store that cannot reach you is not shown as
"unavailable" — it is not a result.

### Checkout

1. A delivery location must be selected first — the quote depends on it.
2. Cart and location go to `POST /api/cart/quote`; the app renders the breakdown as given.
3. M-Pesa STK Push is triggered for `quote.stk_amount`.
4. The app polls until the payment callback lands and the order moves from `pending` (unpaid) to `unassigned` (paid, awaiting a rider).
5. Dispatch offers it to the store's own rider first, then to nearby gig riders.

### Tracking

Once the order reaches `picked_up`, the app opens `/ws/track/{order_id}` and
receives `{ lat, lng }` as the rider moves. The marker is interpolated between
fixes so it glides rather than jumping.

Tracking deliberately starts at pickup, not at acceptance — before then the rider
is on their way to the store and their position is nothing to do with this order.

### Quick Swap

On a refill order, the empties handed back go with the rider and are credited to
the store. If the count is short, the rider records what was actually there with
a photo and the order pauses for review; the app shows that state rather than
pretending the delivery is complete.

### Ratings

Rating the store and rating the rider are two separate submissions, which is why
"has this order been rated" means *every* ratable party — the store, plus the
rider when one was assigned. A repeat submission is treated as an edit, not an
error, so a retry after a partial failure completes rather than 500-ing.

Reviews are moderated: one taken down by the platform disappears from the listing
**and** leaves the store's average in the same transaction.

---

## 📜 Conventions

* **All fetching goes through a hook in `hooks/queries/`**, and every hook goes through `useApiRequest()`. It injects the Clerk JWT, signs the user out on a 401, and converts every failure into an `ApiError` whose `message` is the backend's own `detail`.
* **Every backend path lives in `API/routes/ApiRoutes.ts`.** Never build one inline — `BackendAPI/tests/test_route_contract.py` parses that file and fails CI if a path does not resolve, which is how five 404-ing endpoints were caught.
* **`ApiError` has no `.response`.** `error.response.data.type` is always `undefined`; reading it that way silently disabled the vendor-conflict prompt and hid every backend message behind a generic fallback. Branch with `isVendorConflict(err)` / `vendorConflictInfo(err)`, and surface text with `errorMessage(err, fallback)`.
* **`retry` is `retryTransientOnly`.** A 4xx is a refusal, not a dropped packet, and retrying a 401 fires the sign-out handler once per attempt.
* **Order statuses live in one place** — `ORDER_STATUS_GROUPS` / `matchesOrderFilter` / `CANCELLABLE_ORDER_STATUSES` in `hooks/queries/useOrders`. Screens that listed them inline drifted: the Orders filters once covered neither `preparing` nor `ready`, so an order being packed matched no filter and offered no action.
* **Null-safe rendering.** Optional chaining on API data, and prices formatted defensively.
* **`Toast` for feedback, `Popup` for confirmation** — both theme-aware. Native `Alert` is reserved for the blocking forced-update prompt. Never show a bare status code.
* **Never call a Google web service from the app.** The embedded keys are SDK-restricted and cannot; a key that could would be extractable from the binary. Use the backend proxy — see [docs/maps-architecture.md](../docs/maps-architecture.md).
* **Theme from `UIThemeContext`**, colours from `constants/brandColors.ts`, never a hardcoded hex for a primary element.
* **`PressableScale` over `TouchableOpacity`**, and `React.memo` for list items with complex props.
* **Session teardown** is mounted once in the root layout and wipes local state whenever Clerk's session ends — including the ends nobody taps, like a 401 or a revoked session. `clearPushToken()` must run *before* `signOut()`, or the device keeps receiving the previous account's notifications.

More detail, stated as rules: [CLAUDE.md](./CLAUDE.md).
