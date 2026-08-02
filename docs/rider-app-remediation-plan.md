# Rider app — audit findings and remediation plan

Audit date: 2026-07-31. Scope: `drop-rider-app` (14,031 LOC) and the backend paths
it depends on. Verified against the running code, not inferred.

> **Status: phases 1–4 implemented on 2026-07-31.** Every finding below is
> addressed in code; see "Implementation record" at the end for what landed where
> and what still needs a physical device. The findings are kept in their original
> wording so the reasoning behind each fix stays readable.

Findings are ordered by consequence, not by effort. Severity means:

| | Meaning |
|---|---|
| **S1** | Money, safety, compliance, or a core promise of the app is broken |
| **S2** | A feature is materially incomplete or degrades badly under normal use |
| **S3** | Correctness or maintainability debt with a clear failure mode |

---

## S1 — Critical

### S1-1. KYC approval is not enforced anywhere on the server

**Evidence.** `grep -c kyc routes/deliverer_routes.py services/deliverer_service.py`
→ `0` and `0`. `get_current_rider` (`dependencies/auth_dependencies.py:32`) checks
only that a `Deliverer` row exists. `accept_delivery_radar` checks
`is_available`, cash float and the order lock — never `kyc_status`.

The only gate is a client-side redirect in `app/(screens)/_layout.tsx:63`:

```tsx
if (!statusLoading && statusData) {
  if (statusData.kyc_status !== "approved" && !path.includes("VerificationWall")) {
```

**Why it matters.** `CLAUDE.md` states riders "remain blocked in `VerificationWall`
until `kyc_status == 'approved'`". They are not. A rider whose KYC is
`unsubmitted` or explicitly **`rejected`** can accept orders, collect customers'
cash, take their empty bottles, and be paid — by calling the API directly, or
simply by using the app while the KYC query is failing (see S1-2). For a platform
handling cash and identity verification this is a compliance failure, not just a
bug.

**Fix.**

1. Add a `get_verified_rider` dependency beside `get_current_rider`:

   ```python
   async def get_verified_rider(user=Depends(get_current_user), db=Depends(get_db)):
       rider = (await db.execute(select(Deliverer).where(Deliverer.clerk_id == user["sub"]))).scalar_one_or_none()
       if not rider:
           raise HTTPException(403, "Access denied. Must be a registered rider.")
       if rider.kyc_status != KYCStatus.approved:
           raise HTTPException(403, detail={"type": "kyc_required", "message": "…", "kyc_status": rider.kyc_status.value})
       return user
   ```

2. Apply it to every endpoint that moves goods, money or order state: accept,
   accept-radar, reject, cancel, status update, bottle-rejection, mismatch,
   payout request, cashout. Leave read-only profile/KYC/notification endpoints on
   `get_current_rider` so a pending rider can still see their status.

3. Structured `detail` so the client can route to `VerificationWall` on the
   `kyc_required` type rather than string-matching.

4. Pin it: a test asserting every state-changing rider route depends on
   `get_verified_rider`, in the style of `test_auth_security.py`'s AST scan — so
   a new endpoint cannot be added without the gate.

**Effort:** ~3h including tests. **Risk:** low; additive.

---

### S1-2. The verification wall fails *open*

**Evidence.** `app/(screens)/_layout.tsx:63` — `if (!statusLoading && statusData)`.
When the KYC query errors (network blip, 500, timeout) `statusData` is
`undefined`, the branch is skipped, and the rider is dropped into the **full app**
including Trip Radar.

**Why it matters.** The security control is bypassed by turning off wifi at the
right moment. It compounds S1-1: today there is no server-side backstop.

**Fix.** Invert the default — render a blocking state unless approval is
*positively* confirmed:

```tsx
if (statusLoading) return <SplashOrSkeleton />;
if (isError) return <RetryScreen onRetry={refetch} />;   // never silently continue
if (statusData?.kyc_status !== "approved" && !path.includes("VerificationWall"))
  return <Redirect href="/(screens)/VerificationWall" />;
```

**Effort:** ~1h. **Risk:** low, but needs a real retry affordance so a genuine
outage does not lock a working rider out with no way forward.

---

### S1-3. Location tracking stops the moment the app backgrounds

**Evidence.** `ActiveDelivery.tsx:206-235` uses
`requestForegroundPermissionsAsync` + `watchPositionAsync` inside a component
effect. There is no `TaskManager` task and no `startLocationUpdatesAsync`
anywhere in the app:

```
grep -rn "TaskManager|startLocationUpdatesAsync|requestBackgroundPermissionsAsync" → (no matches)
```

Meanwhile `app.json` **already declares** `ACCESS_BACKGROUND_LOCATION`,
`FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_LOCATION`, and iOS declares no
`UIBackgroundModes` at all.

**Why it matters.** The rider backgrounds the app the instant they tap "Navigate"
— that is the *entire* delivery. The customer's live map, which
`drop-customer-app` builds a whole WebSocket + REST fallback for, freezes at the
last foreground position. The app's own guide says location must broadcast while
the delivery is in progress; it does so only while the rider is staring at the
screen.

Declaring background-location permission without using it is also a Google Play
review risk in its own right.

**Fix.**

1. Add `expo-task-manager`; define `RIDER_LOCATION_TASK` in a module imported at
   app root (task definitions must register before the task fires).
2. Start with `Location.startLocationUpdatesAsync(RIDER_LOCATION_TASK, {…})` when
   an order reaches `picked_up`; stop on `delivered`/`cancelled`.
3. Android: `foregroundService: { notificationTitle: "Drop delivery in progress", … }`
   — required for `FOREGROUND_SERVICE_LOCATION`, and it is also the honest UX.
4. iOS: `UIBackgroundModes: ["location"]` plus
   `NSLocationAlwaysAndWhenInUseUsageDescription` explaining the delivery use.
5. Request background permission **only** at first `picked_up`, with an
   explanation screen first. Asking on launch is the main cause of denial.
6. Have the task POST to a REST endpoint, not the WebSocket — a background task
   has no live socket. Add `POST /api/rider/location-ping` (batched, ≤1 write per
   10s per rider) and let the existing WS relay fan out to the customer.

**Effort:** ~2 days including device testing on both platforms. **Risk:** medium
— background location is the most fragile surface in mobile; budget real device
time, not simulator.

---

### S1-4. Location broadcast has no fallback when the socket is down

**Evidence.** `ActiveDelivery.tsx:226` sends positions exclusively via
`sendMessage` (WebSocket). If the socket is closed the coordinate is dropped —
the `try/catch` only logs.

**Why it matters.** Riders work in patchy coverage; that is precisely when the
customer most wants the dot to move. The customer app already degrades gracefully
for *reading* (`useRiderTracking` falls back to REST polling) — the writing side
has no equivalent, so there is nothing for it to read.

**Fix.** Fold into S1-3: the batched `location-ping` endpoint becomes the durable
path, and the socket becomes the low-latency optimisation. Buffer the last N
positions in memory and flush on reconnect.

**Effort:** included in S1-3.

---

## S2 — Materially incomplete

### S2-1. No API client layer: 19 raw status codes reach the user

**Evidence.** `drop-rider-app/API/` contains only `routes/`. There is no
`useApiClient`, no `ApiError`, no `errors.ts`. Every call is a hand-rolled
`fetch`, and 19 of them throw the HTTP status at the user:

```
hooks/queries/useNotifications.ts:31  throw new Error(`Notifications fetch failed: ${res.status}`)
hooks/queries/useRiderData.ts:81      throw new Error(`Rider orders fetch failed: ${res.status}`)
…17 more
```

**Why it matters.** The platform guide is explicit — "Use the global `Toast.error`
component to display user-friendly backend errors. DO NOT silently fail or throw
raw HTTP status codes to users." The customer app was migrated to `useApiRequest`
for exactly this reason; the rider app never was. Concretely, the backend's
carefully written `detail` — *"You must be online and available to accept
orders"*, *"Insufficient balance: KSH 4,000 is committed as float"* — is discarded
and the rider sees `Earnings fetch failed: 402`.

Secondary consequences of having no client: `fetch` has **no default timeout**, so
a hung request hangs forever; 401 handling is copy-pasted at ~15 sites; there is
no HTTPS enforcement.

**Fix.** Port the customer app's layer verbatim — it is proven and the two apps
should not diverge:

1. Copy `API/errors.ts` (`ApiError`, `toApiError`, `errorMessage`,
   `retryTransientOnly`) and `API/useApiClient.ts` (`useApiRequest`).
2. Migrate hooks in dependency order: `useRiderData` → `useWallet` →
   `useNotifications` → `useBottleDebt` → `useOrderContacts` → mutations.
3. Then screens: `ActiveDelivery`, `TripRadar`, `Cashout`, `Profile`,
   `OperationBase`, `VerificationWall`, `MyVendors`, `DiscoverVendors`,
   `Earnings`, `SettingsMain`, `rider/BankDetails`, `Onboarding`.
4. Delete the per-hook `signOut()` on 401 — the interceptor owns it.
5. Add the `retryTransientOnly` predicate to the QueryClient so a 4xx is not
   retried three times, each firing `signOut()`.
6. Guard with a test: no `fetch(` outside `API/`, `useNetworkQueue` (background
   replay) and `PlacesAutocomplete` (third-party).

**Effort:** ~1.5 days, mechanical but broad. **Risk:** medium — touches every
screen; do it as one PR with a full manual pass, not piecemeal.

### S2-2. Offline queue only retries on a connectivity *transition*

**Evidence.** `hooks/useNetworkQueue.ts:14` — the entire flush lives inside
`NetInfo.addEventListener`. A 5xx or 401 during replay leaves the action queued
(correct) but schedules **no retry**; nothing runs again until the next
connectivity change event.

**Why it matters.** A completed delivery that fails to sync — because the token
had just expired, or the API was restarting — sits in SQLite indefinitely while
the device stays online. The rider is not paid, the customer is not notified, and
the order is stuck in `picked_up`. Nothing surfaces this.

The same handler drops the action outright on 400/404/409 (`:42`, `:64`) with a
toast. For a *delivered* action that is the rider's proof of work being deleted
with a transient message.

**Fix.**

1. Extract the flush into `flushOfflineQueue()`; call it from (a) the NetInfo
   listener, (b) app foreground (`AppState`), (c) a 60s timer while the queue is
   non-empty, (d) manually from a new "Pending sync" UI.
2. Add `attempts` and `last_error` columns; exponential backoff; stop at ~10
   attempts and mark `needs_attention` rather than deleting.
3. Never delete a `delivered` action automatically. Surface it in a
   **Pending Sync** screen with the server's reason and a retry button.
4. Add a mutex so two overlapping NetInfo events cannot double-replay.

**Effort:** ~1 day incl. a small migration on the SQLite table. **Risk:** low.

### S2-3. Order history is silently truncated at 50

**Evidence.** Backend `GET /api/rider/orders` supports `skip`/`limit`
(`routes/deliverer_routes.py:151`). The client route
(`API/routes/RiderApiRoutes.ts:36`) passes neither, and no screen implements
"load more".

**Why it matters.** A rider six months in cannot see anything past their most
recent 50 deliveries — including for an earnings dispute. There is no empty state
explaining the cut-off, so it reads as data loss.

**Fix.** `useInfiniteQuery` on `useRiderOrders` and `useEarningsHistory`, mirroring
`useWalletTransactionsPaginated`, which already does this correctly in the same
app. Add `FlashList` `onEndReached`.

**Effort:** ~4h.

### S2-4. Trip Radar polls every 30s in addition to the WebSocket

**Evidence.** `TripRadar.tsx:221` — `setInterval(fetchRadarOrders, 30000)`,
running alongside the `useWebSocket` subscription that already pushes new orders.

**Why it matters.** Every online rider issues a spatial PostGIS query twice a
minute whether or not anything changed. At 500 online riders that is 1,000
`ST_DWithin` queries per minute purely as a fallback, and it drains rider battery
while idle.

**Fix.** Treat the poll as a *reconciliation* pass, not the primary path: 30s →
120s while the socket is connected, 15s only while it is disconnected. Use the
`connected` flag `useWebSocket` already returns. Add `If-Modified-Since`-style
short-circuiting server-side if load is still a concern.

**Effort:** ~2h. **Risk:** low, immediate load win.

### S2-5. `(screens)` mounts before Clerk resolves

**Evidence.** `app/(screens)/_layout.tsx:53` guards `isSignedIn === false` but not
`isLoaded`. This is the same defect fixed in the customer app this week; the rider
app still has it. Only the KYC query is `enabled`-guarded — every other rider
query fires on mount, and each has its own `if (res.status === 401) signOut()`.

**Why it matters.** A deep link into the group before Clerk resolves sends a burst
of token-less requests, all 401, each calling `signOut()`. Opening a link destroys
a valid session.

**Fix.** Port the customer app's gate exactly: render a spinner while `!isLoaded`.

**Effort:** ~30min.

---

## S3 — Correctness and hygiene

### S3-1. Unused dangerous permissions declared

`android.permissions` includes `RECORD_AUDIO` — no audio code exists anywhere in
the app (`grep -rn "Audio|Recording|expo-av"` → nothing). It also declares the
three background-location permissions that S1-3 shows are unused today.

Google Play requires justification for both microphone and background location,
and rejects apps that request them without a matching feature. **Fix:** drop
`RECORD_AUDIO` now; keep the location ones only once S1-3 lands.

### S3-2. GPS tracked from `accepted`, not `picked_up`

`ActiveDelivery.tsx:220` starts watching on any `activeOrder`. The guide says to
broadcast only while the delivery is actually in progress. Tracking from
acceptance wastes battery on the leg to the vendor and exposes the rider's
position to the customer before pickup. **Fix:** gate on
`order_status === "picked_up"`.

### S3-3. Over-aggressive location accuracy

`accuracy: High, timeInterval: 5000, distanceInterval: 10` keeps GPS hot
continuously. `Balanced` with `distanceInterval: 25` is ample for a delivery dot
and materially cheaper — the vendor app's guide already records this lesson.
**Fix:** downgrade, and raise the interval when the rider is stationary.

### S3-4. Console noise outside `__DEV__`

Six sites log unconditionally (`Cashout.tsx:91`, `sign-up/screen.tsx:151`,
`SettingsMain.tsx:84`, `Onboarding.tsx:62`, `index.tsx:105`, `PlacesAutocomplete`).
`sign-up` logs the full response object. **Fix:** wrap in `__DEV__`; these are the
paths most likely to carry identity data.

### S3-5. Duplicated `useAuth()` calls

`(screens)/_layout.tsx:22,24` destructures `useAuth()` twice. Harmless, but it is
the kind of drift that hides a real inconsistency later.

---

## What is already correct

Worth recording so it is not "fixed" later by mistake:

- **The proof-of-delivery guardrail is right, on both sides.** Every failure
  branch in `captureProofAndDeliver` (permission denied, upload failed, camera
  error) re-checks `emptiesReceived < computedEmptiesExpected` and refuses. The
  backend independently enforces it at `deliverer_service.py:362`, so a modified
  client cannot bypass it. This is the pattern S1-1 should follow.
- Accept-race handling is correct: Redis lock + `FOR UPDATE NOWAIT` + a 409 the
  client renders as "Claimed".
- Optimistic status updates roll back properly on 4xx.
- Cash-order float is checked under a row lock before acceptance.
- Mock location injection is `__DEV__`-gated.
- Wallet transactions already paginate correctly.
- Session teardown (query cache + offline DB purge + push-token detach) landed
  this week and is sound.

---

## Sequencing

Ordered so that each phase is independently shippable and nothing depends on a
later phase.

| Phase | Contents | Effort | Ships |
|---|---|---|---|
| **1 — Close the security holes** | S1-1, S1-2, S2-5, S3-1 | ~1 day | Backend + a config change; no UX risk |
| **2 — Make delivery tracking real** | S1-3, S1-4, S3-2, S3-3 | ~2.5 days | Needs device testing; own release |
| **3 — Pay off the client debt** | S2-1, S3-4, S3-5 | ~1.5 days | One broad PR, full manual pass |
| **4 — Reliability and scale** | S2-2, S2-3, S2-4 | ~1.5 days | Independent of 1–3 |

Phase 1 first because S1-1 is exploitable today with nothing but a token, and the
fix is small and additive. Phase 2 is the largest functional gap but carries real
platform risk, so it wants its own release and rollback plan. Phase 3 is broad but
mechanical and blocks nothing. Phase 4 improves numbers rather than correctness.

**Total: ~6.5 engineering days.**

## Verification

Each phase lands with:

- Backend: tests in the existing style, plus a structural test where the defect is
  structural (the `get_verified_rider` scan, the `no raw fetch` scan) — both
  classes have already caught real regressions in this repo.
- `npx tsc --noEmit` clean on all three apps.
- Phase 2 additionally: a physical Android device and a physical iPhone, screen
  locked, app backgrounded, full order lifecycle, battery measured over a 30-minute
  delivery.


---

## Implementation record — 2026-07-31

All four phases landed together. `npx tsc --noEmit` is clean on all three apps
and the backend suite is 347 passing / 1 skipped.

### Phase 1 — security

| Finding | Where |
|---|---|
| S1-1 | `dependencies/auth_dependencies.py::get_verified_rider`, applied to the ten state-changing routes in `routes/deliverer_routes.py`. Pinned by `tests/test_rider_kyc_enforcement.py` (9 tests), whose `test_the_route_inventory_is_complete` fails if a new rider route is added without being classified. |
| S1-2 | `app/(screens)/_layout.tsx`. The gate now blocks unless approval is *positively* confirmed, with a retry screen and a sign-out escape hatch so an outage cannot strand a working rider. |
| S2-5 | Same file: one `useAuth()` destructure including `isLoaded`, and a spinner until Clerk resolves. |
| S3-1, S3-5 | `RECORD_AUDIO` removed from `app.json`; the duplicate `useAuth()` merged. |

Two things surfaced while implementing this that the audit had not recorded:

- **The KYC status endpoint was fetched by hand in three places** with three
  different failure behaviours, and `VerificationWall` kept its answer in
  `useState`. On approval the wall pushed to `/(screens)` while the layout's
  cache still said `pending` and pushed straight back — a redirect loop that only
  broke when the 60s `staleTime` expired. Now one hook, `hooks/queries/useKycStatus`.
- **`GET /api/rider/orders/{id}/rider-location` had no order-scoped check.** Any
  registered rider could read any other rider's live position, name and
  availability by guessing an order id. It now calls `authorise_order_access`.

### Phase 2 — delivery tracking

`services/locationTracking.ts` defines `RIDER_LOCATION_TASK` (registered from
`app/_layout.tsx`, so it survives a headless relaunch), buffers every fix to
SQLite before sending, and flushes batches to the new
`POST /api/rider/location-ping`. `hooks/useRiderLocationTracking` bridges Clerk's
token into the task and drains the buffer on foreground.

- **S1-3** — background updates start at `picked_up` and stop at
  `delivered`/`cancelled`, behind an Android foreground service and the iOS
  `location` background mode. Background permission is requested at first pickup
  after an explanation, never at launch.
- **S1-4** — the buffer is the durable path; the socket is now the low-latency
  optimisation on top of it. A fix produced with the socket down is kept, not
  logged and discarded.
- **S3-2** — positions are only *reported* from `picked_up`. The foreground
  watch still runs earlier, because the map needs the rider's own position.
- **S3-3** — `Accuracy.Balanced` at 25 m, with deferred updates while stationary.

Server side, `record_location_pings` throttles the row write to one per rider per
10 s while still recording every sample, and strips an `order_id` the rider does
not own so nobody can forge another rider's trail.
`tests/test_rider_location_pings.py` covers all of it (13 tests).

**Not yet verified:** everything in this phase needs a physical Android device
and a physical iPhone — screen locked, app backgrounded, full order lifecycle,
battery measured over a 30-minute delivery. Simulators do not exercise the
foreground service or iOS background suspension.

### Phase 3 — client debt

`API/errors.ts` and `API/useApiClient.ts` are ported from `drop-customer-app`;
`API/apiFetch.ts` is the non-hook equivalent for the Zustand store, the replay
queue and the background task. All 52 hand-rolled `fetch` call sites are gone —
`tests/test_rider_api_client.py` fails the build if one reappears, or if any
screen formats a raw HTTP status into a message. The root `QueryClient` uses
`retryTransientOnly`, so a 4xx no longer costs three round-trips and three
sign-out calls.

Also found in passing: **rider sign-up was broken.** `POST /api/auth/create_rider`
takes the caller's identity from the verified token, and
`app/(Auth)/sign-up/screen.tsx` sent no `Authorization` header at all, so every
sign-up ended on "Failed to save rider details". It now attaches the token
`setActive` has just established.

### Phase 4 — reliability

- **S2-2** — `services/offlineQueue.ts` replaces the flush that lived inside the
  NetInfo callback. Four triggers (connectivity, foreground, a timer while the
  queue is non-empty, manual), exponential backoff, `attempts`/`last_error`/
  `needs_attention` columns added by ALTER rather than a table rebuild, and a
  mutex so overlapping events cannot double-replay a delivery. A `delivered`
  action is never deleted automatically; it surfaces on the new **Pending Sync**
  screen (`app/(screens)/PendingSync.tsx`, linked from Settings) with the
  server's reason, a retry, and an explicit discard.
- **S2-3** — `useRiderOrdersPaginated` / `useEarningsHistoryPaginated` on
  `useInfiniteQuery`, wired to `SectionList`'s `onEndReached`, with an explicit
  "that's your full delivery history" footer instead of a silent cut-off.
- **S2-4** — the radar poll is now a reconciliation pass: 120 s while the socket
  is connected, 15 s only while it is not.
- **S3-4** — the remaining unconditional `console` calls are `__DEV__`-gated.
  `ErrorBoundary`'s fatal log stays, deliberately: it feeds crash reporting.

### Configuration

`.env.example` already documented every variable the app reads, and still does —
no new ones were introduced. `scripts/preflight.js` gained checks for the
WebSocket scheme matching the backend scheme, the three Android background
location permissions, the iOS `UIBackgroundModes`, the
`locationAlwaysAndWhenInUsePermission` string, and a hard failure if
`RECORD_AUDIO` ever comes back.
