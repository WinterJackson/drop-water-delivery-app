# Drop Vendor App 🏪

> The store management app for the Drop platform. Water station owners and their
> staff run the shop floor from here: catalogue, incoming orders, the empties
> riders owe them, and the money.

---

## 📱 What it does

| Area | What it covers |
|---|---|
| **Store** | Open/closed, operating hours, profile, payout account, multiple branches |
| **Catalogue** | Products, prices, stock, per-product low-stock thresholds, WebP-compressed photos |
| **Orders** | Live incoming orders over WebSocket; accept, prepare, mark ready for pickup |
| **Riders** | Approve riders who ask to register with the store, and see who is holding your bottles |
| **Bottles** | Confirm empties returned by a rider, or dispute the count |
| **Money** | Wallet balance, what is committed to open cash orders, and M-Pesa withdrawals |
| **Staff** | Invite people and grant them exactly the capabilities they need |
| **Support** | Raise a ticket that lands in the operations console |

---

## 🏬 A `Vendor` row is a store, not an account

One Clerk identity may own several. The **active store** is chosen in
`stores/activeStoreStore.ts`, persisted, and sent by the API client as
`X-Store-Id` on every request; the backend validates it against the caller's own
stores and answers **404** — not 403 — for one they do not own, because
confirming an id exists is itself a leak.

Switching store empties the query cache (`useStoreScopedCache`). Requests are
scoped by header, so `["vendorOrders"]` means "the active store's orders" and
React Query cannot tell the two apart on its own.

`GET /api/vendor/stores` is the single call allowed to opt out of scoping — its
whole purpose is to return the others.

---

## 👥 Staff have capabilities, not a job title

A staff member may be trusted with orders but not with the catalogue. Four
capabilities, granted individually:

| Capability | Grants |
|---|---|
| `manage_orders` | Accept, prepare, mark ready |
| `manage_products` | Add, edit, reprice, restock |
| `manage_bottles` | Confirm empty returns and raise disputes |
| `view_finances` | See the balance and the transaction history |

`view_finances` is **not** granted by default. Seeing the store's balance is a
decision the owner makes, not one inherited from a schema that could not express
the question.

`GET /profile` returns `permissions` for the signed-in caller — owners get all
four spelled out — and `useCan(PERMISSIONS.manageProducts)` is how a screen
decides whether to render a control. **Gate on the capability, never on
`role !== "staff"`**: that was the old all-or-nothing model, and it is what let
anyone handed the till also reprice the products.

Five things remain owner-only and are not capabilities at all — they are things
only an owner may ever do: the owner profile, store profile, payout settings,
operating hours, and managing staff. The server enforces every one of them; the
app hides them because offering an action that always fails is bad UX, not
because hiding is the control.

> The previous model held **one** staff id in a column that was UNIQUE across the
> entire platform: a store could have one staff member, a second silently
> replaced the first, and one person could work for exactly one store on the whole
> platform.

---

## 🛠️ Tech stack

React Native · [Expo SDK 54](https://expo.dev/) · React 19 ·
[Expo Router](https://docs.expo.dev/router/introduction/) ·
[NativeWind v4](https://www.nativewind.dev/) ·
[TanStack Query v5](https://tanstack.com/query/latest) ·
[Zustand](https://zustand-demo.pmnd.rs/) · [Clerk](https://clerk.com/) ·
`socket.io-client` · `expo-notifications` · `expo-image-manipulator`

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
GOOGLE_MAPS_ANDROID_API_KEY=...   # restricted to com.drop.vendor + SHA-1
GOOGLE_MAPS_IOS_API_KEY=...       # restricted to bundle id com.drop.vendor
```

`10.0.2.2` is the Android emulator's alias for the host machine. On a physical
device use your computer's LAN address — `localhost` reaches the handset.

> **Never commit a Google key.** `app.json` carries none; `app.config.js` reads
> the two above from the environment, with EAS secrets in CI. See
> [docs/security/google-api-key-rotation.md](../docs/security/google-api-key-rotation.md).

---

## 📂 Structure

```
drop-vendor-app/
├── app/
│   ├── (Auth)/           # Sign-in and store setup
│   ├── (screens)/        # Orders, Products, Riders, Bottles, Wallet, Staff, Support
│   └── _layout.tsx       # Providers, session cleanup
├── API/
│   ├── useApiClient.ts   # The only way React code talks to the backend
│   ├── apiFetch.ts       # For code outside React (push registration, uploads)
│   └── routes/           # Typed endpoint definitions
├── components/
│   ├── orders/ products/ ui/
├── constants/            # brandColors.ts, orderStatus.ts
├── hooks/queries/        # TanStack Query hooks
├── stores/               # Zustand — including the active store
└── Helpers/              # Image upload, formatting
```

---

## 🔄 How the work actually flows

### An order

1. Customer pays → the store gets a push **and** a `NEW_ORDER` WebSocket event.
2. It lands in **Pending**. The vendor confirms they have stock and taps **Accept** → `accepted`.
3. They prepare it, then tap **Ready for pickup** → `ready`. That state is what tells the backend to finalise rider dispatch.
4. Dispatch offers it to an in-house rider registered with the store first; otherwise the Trip Radar broadcasts to nearby gig riders.
5. Rider collects → `picked_up`. Delivers → `delivered`, and the revenue split credits the store's wallet in the same transaction.

**Paused orders are ordinary operation, not an edge case.** `mismatch_pending`
and `pending_review` happen when a rider flags a damaged empty or reports the
customer understated their floor. Statuses live in **one** place,
`constants/orderStatus.ts` — two divergent colour maps in two screens is how both
states came to be missing from both.
`GET /api/vendor/orders/{id}/review` carries the rider's reason and photos.

On a WebSocket event, invalidate the query rather than mutating the cache by
hand — the server's state is the one that counts.

### Empties

On a `quick_swap` delivery the rider takes the customer's empties, which belong
to the store. From that moment the rider is holding store property, and the
**Receive Bottles** flow is how it comes back.

Every movement is a row in an append-only ledger, and the counter the app shows
is the sum of it. Recording a return validates against the outstanding balance
rather than clamping: a client sending 999 used to zero the debt and get a
success back, with the app's own limit check the only thing between a typo and a
wiped balance.

If the rider brings three when four were expected, the vendor raises a dispute
and the operations console adjudicates.

### Stock

`low_stock_threshold` is **per product** — a shop selling 200 refills a day and
one selling a dispenser a month cannot share a number — and `0` disables the
warning. `low_stock_notified_at` latches the alert so the vendor is told once per
crossing, not once per unit sold below the line; restocking clears it.

### Money

Delivered orders credit the wallet net of commission and fees. What is
**withdrawable** is the balance minus `committed_cash_float` — money already
promised to open cash orders the store's rider is out carrying. Withdrawals go to
M-Pesa by B2C; a failure returns the amount to the wallet, because the debit
happens before the call so it cannot be spent twice in flight.

---

## 📸 Images

`Helpers/imageUpload.ts` → `POST /api/vendor/upload-image` → S3.
`expo-image-manipulator` compresses to WebP at width 800 first.

* The **key** is stored, never a URL; response schemas presign it for 15 minutes on the way out.
* **Editing a product must omit `image_url` when the image has not changed.** The API returns a presigned URL; sending it back stores an expiring URL as the product's permanent image.
* Never post to Cloudinary. The app once shipped an *unsigned* preset, which is a public write endpoint for anyone who unzips the APK, and revoking it means deleting it for every vendor at once.
* Never store an image *in* a column. `profile_pic` used to receive a megabyte of base64 that was then returned inside every profile response.

---

## 📜 Conventions

* **Every backend call goes through the API client.** `useApiRequest()` in React, `apiFetch` outside it. Raw `fetch` is banned and `BackendAPI/tests/test_vendor_api_client.py` fails the build if one reappears — `fetch` has no timeout, no 401 handling and no error normalisation.
* **Surface the backend's message** with `errorMessage(err, fallback)`. Never `err.response?.data?.detail`; an `ApiError` has no `.response`, so that path always falls through to the generic string.
* **Branch on `ApiError.type`**, never on the wording of a sentence. `retry` is `retryTransientOnly` — a 4xx is a refusal, not a dropped packet.
* **Never call a Google web service from the app.** The embedded keys are SDK-restricted and cannot; a key that could would be extractable from the binary. Use the backend proxy — see [docs/maps-architecture.md](../docs/maps-architecture.md).
* **Coordinates**: `getLastKnownPositionAsync()` first, then `getCurrentPositionAsync({ accuracy: Balanced })`. A bare `getCurrentPositionAsync({})` defaults to the highest accuracy and can block for 30 seconds on a cold fix.
* **Dark mode is required** for every text and background element.
* **Session teardown** is mounted once in the root layout and wipes local state whenever Clerk's session ends — including the ends nobody taps, like a 401 or a revoked session. `clearPushToken()` must run *before* `signOut()` and must pass `?app_type=vendor`, and the remembered store must be cleared, or the next account on the device sends an `X-Store-Id` it does not own.

More detail, stated as rules: [CLAUDE.md](./CLAUDE.md).
