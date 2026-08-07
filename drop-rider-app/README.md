# Drop Rider App 🛵

> The delivery app for the Drop platform. Riders find work, run deliveries,
> reconcile the empties they are carrying, and see exactly what they earned.
> It serves independent gig riders and stores' own in-house fleets alike.

---

## 📱 What it does

| Area | What it covers |
|---|---|
| **Onboarding** | Sign-up and KYC — identity documents, vehicle, and a wait for an administrator's decision |
| **Trip Radar** | Nearby available orders in real time, with the payout and distance up front |
| **Active delivery** | One focused screen: navigate, collect, deliver, prove |
| **Live tracking** | The rider's position, streamed to the waiting customer |
| **Bottles** | What empties they are holding, and for which store |
| **Earnings** | Every trip, base pay, surcharges, deductions and the withdrawable balance |
| **Pending sync** | Anything done offline that has not reached the server yet |
| **Support** | Raise a ticket that lands in the operations console — reachable **before** verification |

---

## 🚧 The verification gate fails closed

A rider cannot accept a delivery until an administrator has approved their KYC.

`app/(screens)/_layout.tsx` blocks unless `kyc_status === "approved"` is
**positively confirmed**. It used to skip its own check whenever the status query
errored, so turning wifi off at the right moment granted access to Trip Radar.
The backend enforces this independently through `get_verified_rider`, but the
client must not lean on that to behave.

KYC status has exactly one reader: `hooks/queries/useKycStatus`. Three screens
used to fetch it separately while `VerificationWall` kept its own copy in
`useState` — on approval the wall pushed forward while the layout's cache pushed
back, a redirect loop that only broke when the `staleTime` expired.

**Support is deliberately let through the gate.** A rider on day four of a "less
than 24 hours" review is exactly the person who needs to ask why, and the wall
itself links to it.

---

## 📡 Location tracking

`services/locationTracking.ts` owns this. **Do not add another
`watchPositionAsync` loop.**

* The **durable** path is the `expo-task-manager` task → SQLite buffer → `POST /api/rider/location-ping`. The WebSocket is a low-latency optimisation on top of it, never the only writer: a `sendMessage` with no socket used to be swallowed by a `try/catch` that only logged, so every fix produced in patchy coverage was lost.
* Reporting **starts at `picked_up` and stops at `delivered`/`cancelled`**. Tracking from acceptance spends battery on the leg to the store and shows the rider's position to a customer whose order has not been collected.
* `Accuracy.Balanced` at 25 m. `High` at 5 s / 10 m holds the GPS radio open, and a delivery dot on a city map cannot show the difference.
* Background permission is asked for at **first pickup, after an explanation** — never at launch. Android 11+ will not offer "Allow all the time" in the same prompt as the foreground one, and an unexplained prompt is the main cause of a permanent denial. A refusal does not block the delivery; it degrades to foreground-only tracking and says so.

Those pings are also the platform's record of where a delivery went. When a
customer says an order never arrived, the operations console replays the path and
measures the closest the rider came to the door — which is why a gap in the record
is reported as a gap rather than quietly averaged over, and why no tracking data
produces *no verdict* rather than an accusation.

---

## 📴 Nothing done offline is deleted silently

`services/offlineQueue.ts` retries on four triggers with exponential backoff. An
action the server refuses **on the merits** is marked `needs_attention` and shown
on the **Pending Sync** screen with the server's own reason — it is not dropped.
For a `delivered` action, dropping it destroys the rider's proof of work and
their pay. Only an explicit tap in that screen discards one.

Delivery completion is therefore retried, which is why the backend's bottle
accrual is idempotent at the database level rather than in application code.

---

## 🛠️ Tech stack

React Native · [Expo SDK 54](https://expo.dev/) · React 19 ·
[Expo Router](https://docs.expo.dev/router/introduction/) ·
[NativeWind v4](https://www.nativewind.dev/) ·
[TanStack Query v5](https://tanstack.com/query/latest) ·
[Zustand](https://zustand-demo.pmnd.rs/) · [Clerk](https://clerk.com/) ·
`socket.io-client` · `expo-location` + `expo-task-manager` · `react-native-maps` ·
`expo-image-manipulator`

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
GOOGLE_MAPS_ANDROID_API_KEY=...   # restricted to com.drop.rider + SHA-1
GOOGLE_MAPS_IOS_API_KEY=...       # restricted to bundle id com.drop.rider
```

`10.0.2.2` is the Android emulator's alias for the host machine. On a physical
device use your computer's LAN address — `localhost` reaches the handset.

> **Never commit a Google key.** `app.json` carries none; `app.config.js` reads
> the two above from the environment, with EAS secrets in CI. See
> [docs/security/google-api-key-rotation.md](../docs/security/google-api-key-rotation.md).

---

## 🔑 Signing in to test it

| | |
|---|---|
| Email | `rider+clerk_test@example.com` |
| Password | `Drop2026!!` |
| Verification code | `424242` |

Brian Otieno — motorbike, gig economy, parked in Ngong Town. Three things about
this account are deliberate, and each one is a wall you would otherwise hit:

- **`kyc_status` is `approved`.** The gate above fails closed, so any other value
  leaves every screen behind it unreachable.
- **KSH 5,000 float.** Accepting a cash order requires
  `vendor_net + platform_total` — roughly KSH 420 on a typical retail order — so
  an empty wallet is a 402 at the first thing you try.
- **Approved on both test stores.** Tier 1 dispatch only offers an order to
  riders in `VendorRiderRegistry`. Without those rows every order waits the full
  twenty seconds and arrives by Trip Radar instead, and the tiering never appears.

The full roster is in the [root README](../README.md#-test-accounts).

## 📂 Structure

```
drop-rider-app/
├── app/
│   ├── (Auth)/           # Sign-in and KYC onboarding
│   ├── (screens)/        # Radar, ActiveDelivery, Bottles, Earnings, PendingSync, Support
│   └── _layout.tsx       # Root layout, session cleanup
├── API/
│   ├── useApiClient.ts   # The only way React code talks to the backend
│   ├── apiFetch.ts       # For the store, the offline queue, the location task
│   └── routes/           # Typed endpoint definitions
├── components/
│   ├── delivery/         # Map overlays, swipe-to-complete
│   ├── radar/            # Trip cards
│   └── ui/
├── services/
│   ├── locationTracking.ts
│   └── offlineQueue.ts
├── constants/  context/  hooks/queries/  lib/
```

`ActiveDelivery.tsx` is the most complex screen; keep its logic in smaller
components under `components/delivery/`.

---

## 🔄 How the work actually flows

### Getting an order

1. A paid order the store cannot cover with its own rider hits the Trip Radar.
2. The backend finds online riders within the search radius — 2 km for retail, 15 km for wholesale — and broadcasts over WebSocket.
3. The first rider to swipe **Accept** claims it. The race is settled by `SELECT ... FOR UPDATE` on the server, not by who rendered first. A rider who loses gets a **409** and must be told gracefully — not shown a stack trace.

Registering with a store is a separate thing: the rider asks, the store approves,
and from then on that store's orders are offered to them **before** the radar
goes out at all.

### Running it

1. En route to the store — order is `accepted`, `preparing` or `ready`.
2. At the store, tap **Confirm pickup** → `picked_up`. Location reporting starts here.
3. En route to the customer.
4. At the customer: verify the empties, take the proof photo, swipe to complete → `delivered`.

### When the count is short

If the customer promised four empties and has two, the rider triggers the bottle
rejection flow: capture evidence, `POST /api/rider/bottle-rejection`, and the
order moves to `pending_review`. The store sees the reason and the photos, and a
background sweep auto-resolves it if nobody adjudicates.

> **A photo is mandatory whenever `emptiesReceived < computedEmptiesExpected`.**
> That check is never bypassed in a `catch` block — a failed upload is a failed
> completion, not a reason to complete without evidence.

### Bottles the rider is carrying

Empties collected on a quick-swap belong to the **store**, not the rider. They
accrue as a debt the moment the delivery completes and clear when the store
confirms receipt. The app shows what is outstanding and to whom — something a
rider previously had no way to see at all.

Because tier-2 radar dispatch offers orders to any nearby rider, a rider can
legitimately deliver for a store they never registered with, and the ledger
records that too. It used to be skipped, and those bottles left with no record.

### Earnings

Every trip lists base pay, surcharges and deductions. What is **withdrawable** is
the balance minus `committed_cash_float` — money already promised to open cash
orders currently being carried. That is why "Insufficient balance: KSH 4,000 is
committed as float" is a real and correct answer, and why it has to reach the
rider in those words rather than as `402`.

---

## 📸 Photos

`expo-image-picker` to capture, `expo-image-manipulator` to compress hard (width
800, quality 0.7, WebP), then upload to `POST /api/rider/upload_proof`. The
response is an S3 **key**, which is what gets attached to the completion call —
never a URL. Responses presign it for 15 minutes on the way out.

---

## 📜 Conventions

* **Every backend call goes through the API client.** `useApiRequest()` in React; `apiFetch` in the Zustand store, the offline queue and the location task. Raw `fetch` is banned and `BackendAPI/tests/test_rider_api_client.py` fails the build if one reappears — it has no timeout, no 401 handling and no error normalisation. Nineteen hooks used to throw the HTTP status at the rider.
* **Surface the backend's message** with `errorMessage(err, fallback)`. Branch on `err instanceof ApiError && err.status`, never on `err.response` — an `ApiError` has none.
* **`retry` is `retryTransientOnly`.** A 4xx is a refusal, not a dropped packet, and retrying a 401 fires the sign-out handler once per attempt.
* **Optimistic status transitions** use `onMutate` for an instant feel, and always handle `onError` to roll the cache back.
* **Never call a Google web service from the app.** The embedded keys are SDK-restricted and cannot; a key that could would be extractable from the binary. Use the backend proxy — see [docs/maps-architecture.md](../docs/maps-architecture.md).
* **Never read the Maps key back at runtime.** Expo scrubs it from the public manifest, so `Constants.expoConfig?...googleMaps` is always `undefined`.
* **`user_type=rider` on every support call.** One Clerk identity can be a rider *and* a customer; the account being acted on is stated, never guessed.
* **Dark mode everywhere**, and `SafeAreaView` from `react-native-safe-area-context` so nothing clips on a notched device.
* **Session teardown** is mounted once in the root layout and wipes local state whenever Clerk's session ends — including the ends nobody taps, like a 401 or a revoked session. `clearPushToken()` must run *before* `signOut()`, or the device keeps receiving the previous account's notifications.

More detail, stated as rules: [CLAUDE.md](./CLAUDE.md).
