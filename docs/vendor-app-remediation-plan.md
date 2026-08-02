# Vendor app — audit findings and remediation plan

Audit date: 2026-07-31. Scope: `drop-vendor-app` (12,868 LOC) and the backend
paths it depends on. Every finding below was verified against the running code —
line numbers are real, and where a claim is about behaviour it was traced through
the actual call chain, not inferred from naming.

Severity:

| | Meaning |
|---|---|
| **S1** | Money, safety, compliance, or a core promise of the app is broken |
| **S2** | A feature is materially incomplete or degrades badly under normal use |
| **S3** | Correctness or maintainability debt with a clear failure mode |

---

## S1 — Critical

### S1-1. A staff member can drain the store's wallet to their own phone

**Evidence.** `POST /api/payouts/request` (`routes/payout_routes.py:31`) is
guarded by `get_current_user` and resolves the payee through
`payout_service._get_provider_details` (`:14`):

```python
async def _get_provider_details(session, clerk_id):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)   # matches staff_clerk_id too
    if vendor:
        return vendor.id, "vendor"
```

`get_vendor_by_clerk_id` (`services/vendor_management_service.py:54`) matches
`Vendor.clerk_id == clerk_id OR Vendor.staff_clerk_id == clerk_id`. So a **staff**
token resolves to the owner's vendor row. `request_payout` then debits that row's
`wallet_balance` and disburses by M-Pesa B2C to `data.account_details`
(`payout_service.py:211` — `phone=data.account_details`), a value supplied in the
request body by the caller.

The only thing preventing this today is a client-side redirect:

```tsx
// app/(screens)/business/PayoutSettings.tsx:30
if (vendorProfile?.role === "staff") {
    Toast.error("Access Denied", "Staff members cannot access payout settings.");
    router.replace("/(screens)");
}
```

**Why it matters.** A shop assistant given app access to take orders can withdraw
the store's entire available balance to their personal number with one API call.
No UI is involved, so nothing about the "Access Denied" screen matters.

The neighbouring money path already gets this right, which is what makes it a
bug rather than a design choice: `POST /api/wallet/withdraw` resolves through
`wallet_service.resolve_wallet_owner` (`:38`), which matches **only**
`model.clerk_id == clerk_id`, and correctly 403s a staff member. Two withdrawal
paths, two different answers to "is this person allowed to move this money".

**Fix.**

1. Add `get_vendor_owner` beside `get_current_vendor` — same lookup, but
   `Vendor.clerk_id == clerk_id` only, and a structured 403 the client can route
   on (`{"type": "owner_only"}`).
2. `_get_provider_details` must resolve a vendor by **ownership**, never by
   staff membership. Payouts are the owner's money.
3. Apply `get_vendor_owner` to every owner-only endpoint: payout request, payout
   history, profile update, staff assignment, account deletion.
4. Pin it with an AST scan in the style of `test_rider_kyc_enforcement.py`, so a
   new vendor route has to be classified `OWNER_ONLY` or `STAFF_ALLOWED`
   deliberately rather than defaulting to permissive.

**Effort:** ~4h including tests. **Risk:** low; additive and narrowing.

---

### S1-2. Every owner-only restriction is client-side only

**Evidence.** Six screens redirect a staff member away —
`StoreProfile.tsx:28`, `business/OperatingHours.tsx:28`, `OwnerProfile.tsx:34`,
`business/PayoutSettings.tsx:30`, `business/ManageStaff.tsx:28`,
`RiderManagement.tsx:118`. The endpoints behind them are all
`Depends(get_current_vendor)`, which accepts staff.

`role` itself is computed for display only (`vendor_management_routes.py:176`):

```python
vendor_data["role"] = "owner" if vendor.clerk_id == clerk_id else "staff"
```

So a staff member calling the API directly can change the business name, the
store's location and delivery radius, the deposit fee, the accepted payment
methods, and take the store offline — none of which the UI would ever let them
near.

One exception is enforced properly: `PUT /api/vendor/staff` re-checks
`vendor.clerk_id != clerk_id` (`:125`) and 403s. That single check is the pattern
the rest should follow.

**Why it matters.** "Staff" is a real privilege boundary in this product — the
whole point of the feature is letting an owner hand the app to someone they do
not fully trust with the business. A boundary that exists only in JSX is not one.

**Fix.** Folded into S1-1: the dependency, applied consistently, plus the
structural test. Client redirects stay as UX, not as the control.

---

### S1-3. Multi-store is broken, and breaks the whole app at two stores

**Evidence.** `get_current_vendor` (`dependencies/auth_dependencies.py:23`):

```python
result = await db.execute(select(Vendor).where(or_(Vendor.clerk_id == clerk_id, Vendor.staff_clerk_id == clerk_id)))
db_vendor = result.scalar_one_or_none()
```

`scalar_one_or_none()` raises `MultipleResultsFound` when the query matches more
than one row. `GET /api/vendor/stores` exists specifically to list a clerk id's
**multiple** stores, and `register_vendor` allows creating them. So the moment an
owner has a second store, **every authenticated vendor endpoint returns 500** —
dashboard, orders, products, profile, wallet, all of it.

Below that, `get_vendor_by_clerk_id` without an explicit `vendor_id`
(`vendor_management_service.py:54`) does:

```python
result = await session.execute(query)
return result.scalars().first()          # no ORDER BY
```

An unordered `.first()` is not stable in PostgreSQL — the row returned can change
between calls, particularly after an update rewrites a tuple. So "which store am
I acting on" is undefined, and can differ between the request that lists orders
and the request that updates one.

And the UI advertises the feature. `StoreSwitcherSheet` is fully built, wired
into the dashboard, and selecting a store does this
(`app/(screens)/index.tsx:46`):

```tsx
const handleSelectStore = useCallback((storeId: string) => {
    setActiveStoreId(storeId);
    // Future: refetch dashboard with new store context
    refetch();
}, [refetch]);
```

`activeStoreId` is never sent anywhere. The switcher changes a highlight.

**Why it matters.** This is the difference between "a feature is missing" and "a
feature is a trap". An owner who opens a second branch loses access to the first
one, with a 500 and no explanation, and no way to tell which store the numbers on
their dashboard belong to in the meantime.

**Fix.**

1. `get_current_vendor` must not use `scalar_one_or_none`. Resolve the **active
   store** explicitly: an `X-Store-Id` header (or `store_id` query parameter),
   validated against the caller's own stores; fall back to a deterministic
   default (`ORDER BY created_at ASC LIMIT 1`) when absent, so single-store
   vendors — everyone today — are unaffected.
2. Return the resolved vendor row from the dependency rather than the token, so
   every route stops re-querying and cannot drift.
3. Persist the selected store in the app and send it on every request from the
   API client, so the switcher becomes real with no per-screen changes.
4. Test: two stores for one clerk id, and assert each endpoint acts on the one
   named — and that naming a store you do not own is a 404, not a 403 (existence
   of another vendor's store id is not ours to confirm).

**Effort:** ~1.5 days. **Risk:** medium — it touches the resolution path every
vendor endpoint uses. Mitigated by the fallback keeping current behaviour for
single-store vendors.

---

### S1-4. The vendor cannot see money committed as cash float

**Evidence.** `services/settlement_service.py` has
`committed_cash_float_for_vendor` (`:76`) and `available_for_payout` handles
`provider_type == "vendor"` (`:111`). The rider app surfaces exactly this through
`GET /api/rider/wallet-summary` (`routes/deliverer_routes.py:435`).

There is no vendor equivalent. `grep -rn "wallet-summary" routes/` returns only
the rider route. `WalletScreen.tsx` renders the raw `wallet_balance`, and
`VendorApiRoutes` has no summary entry.

**Why it matters.** On a wholesale cash order the platform's cut is debited from
the **vendor's** wallet at delivery, so it is committed from acceptance. A vendor
looking at KSH 40,000 who tries to withdraw it is refused with "Insufficient
balance" for money the app just told them they had. The rider app treats this as
a first-class concept precisely because showing only the raw balance made a
refusal look arbitrary.

It compounds S3-2: the backend's explanatory message is discarded before it
reaches the screen, so the vendor sees a generic failure and a number that
disagrees with it.

**Fix.** Add `GET /api/vendor/wallet-summary` returning
`wallet_balance` / `committed_cash_float` / `available_for_withdrawal` /
`is_in_arrears`, mirroring the rider route exactly. Render the split on
`WalletScreen` and cap the withdrawal input at the available figure.

**Effort:** ~3h.

---

## S2 — Materially incomplete

### S2-1. No API client layer: 49 raw `fetch` calls, statuses shown to the user

**Evidence.** `drop-vendor-app/API/` contains only `routes/`. No `errors.ts`, no
`useApiClient.ts`. 49 hand-rolled `fetch` calls, and the hooks throw the status:

```
hooks/queries/useVendorRiders.ts:33    throw new Error(`Riders fetch failed: ${res.status}`)
hooks/queries/useBottleDebtors.ts:42   throw new Error(`Bottle debtors fetch failed: ${res.status}`)
hooks/queries/useVendorProfile.ts:45   throw new Error(`Profile fetch failed: ${res.status}`)
…9 more
```

Worse, `OrderDetail/[id].tsx:130` reads a property that does not exist on
anything this app throws:

```tsx
const errMsg = e.response?.data?.detail || (e as Error).message || "Failed to update status…";
```

`e` here is a plain `Error` from a raw `fetch` branch, so `e.response` is always
`undefined` and the message is always the generic literal. The backend's actual
answer —

> "Insufficient Wallet Balance to cover Platform Commission. Please top up KSH
> 4,000.00 to accept this Cash order."

(`vendor_management_service.py:318`) — never reaches the vendor. They tap Accept,
see "Failed to update status. Please check your connection.", and check their
connection. This is the exact `.response` mistake the customer app's `CLAUDE.md`
already documents.

Secondary: `fetch` has no default timeout, 401 handling is copy-pasted at ~20
sites, and nothing enforces HTTPS.

**Fix.** Port the layer already proven in the customer and rider apps —
`API/errors.ts`, `API/useApiClient.ts` (`useApiRequest`), `API/apiFetch.ts` for
non-React callers — and migrate every hook and screen. Add `retryTransientOnly`
to the root `QueryClient`. Guard with the same structural test the rider app now
has.

**Effort:** ~1.5 days, mechanical but broad.

### S2-2. The store switcher is decoration

Covered by S1-3. Recorded separately because the *UI* half is a real, finished
component (`components/dashboard/StoreSwitcherSheet.tsx`) that only needs the
backend contract to exist — once S1-3 lands this is a two-line change.

### S2-3. Orders in `mismatch_pending` and `pending_review` are dead ends

**Evidence.** `grep -rn "mismatch\|pending_review" drop-vendor-app/app` returns
one hit, in `useOrderContacts`'s visibility list. Neither state appears in
`STATUS_COLORS`, `STATUS_TEXT_COLORS` (`OrderDetail/[id].tsx:31,46`), the Orders
filter set, or any action.

Both states are reachable in normal operation: a rider reports a floor-level
mismatch (`POST /api/rider/orders/{id}/mismatch`) or a damaged bottle
(`.../bottle-rejection`), and the order parks there pending review.

**Why it matters.** The order shows a blank status pill and no explanation, and
the vendor — whose stock is committed and whose money is pending — has no way to
see what happened or do anything about it. `CLAUDE.md` also describes
`mismatch_pending` as "vendor flags a quantity issue", and there is no vendor
endpoint to flag one at all.

**Fix.** Render both states with an explanation of what is being reviewed and by
whom, expose the rider's reason and evidence photos where present, and add the
missing filter entries. A vendor-initiated quantity dispute is genuinely new
scope — it is specified in the guide and unbuilt — so it is listed separately in
Phase 4 rather than smuggled in here.

### S2-4. Orders list has pagination the app half-uses

**Evidence.** `GET /api/vendor/orders` returns `{"pages": [orders]}` —
a single-element array shaped to look paginated (`vendor_management_routes.py:373`).
`useVendorOrdersPaginated` exists and paginates correctly; `useVendorOrders` does
not pass `skip`/`limit` at all and is what the tab badge and dashboard use.

The hook carries a comment that reads like an unfinished debugging session:

```ts
// Because the backend now returns {"pages": [orders]} if we don't pass skip/limit properly,
// wait, we changed the backend /orders route to return {"pages": [orders]}!
```

**Fix.** Return a real paginated envelope (`items` + `total` + `has_more`), keep
one hook per purpose with honest names, and delete the commentary.

### S2-5. `(screens)` mounts before Clerk resolves

**Evidence.** `app/(screens)/_layout.tsx:45` guards `isSignedIn === false` but
not `isLoaded` — the same defect fixed in the customer app, then the rider app.
Every vendor query fires on mount and each has its own `if (401) signOut()`.

**Why it matters.** A deep link into the group before Clerk resolves sends a
burst of token-less requests, all 401, each calling `signOut()`. Opening a link
destroys a valid session.

**Fix.** Port the gate: spinner while `!isLoaded`.

### S2-6. Product images go to Cloudinary with an unsigned preset

**Evidence.** `hooks/useImageUpload.ts:8-9`:

```ts
const cloudName = 'dn5f0jksu';
const uploadPreset = 'drop_uploads';
```

posted unsigned to `https://api.cloudinary.com/v1_1/{cloud}/upload`. Both values
ship in the JS bundle. Separately, `AddProduct.tsx:173` offers a "Paste Image
URL" field, and `ProductCreateRequest.image_url` (`vendor_management_routes.py:62`)
is an unvalidated `str`.

**Why it matters.** An unsigned preset extracted from the APK lets anyone upload
arbitrary files to the account — storage and bandwidth billed to the platform,
and arbitrary content served from its Cloudinary domain. The free-text URL field
means a product image can point anywhere: a tracking pixel that logs the IP of
every customer who browses the catalogue, or content the platform would not
choose to host.

Cloudinary itself is an accepted pattern in this codebase (the customer app's
guide names it as a legitimate third-party call), so the fix is to sign the
upload, not to migrate to S3.

**Fix.** Sign uploads server-side (`GET /api/vendor/upload-signature`, short TTL,
folder-scoped), restrict the preset to signed mode, validate `image_url`
server-side against an allowlist of hosts the platform controls, and drop the
paste-a-URL field.

### S2-7. No low-stock signal anywhere

**Evidence.** `stock` is captured on create/update and rendered on the products
list, and nothing else references it — no threshold, no badge, no notification,
no dashboard card. `Product.is_available` is a separate manual flag.

**Why it matters.** A vendor's stock silently reaching zero means orders keep
being accepted against nothing, then cancelled — which restores stock
(`_restore_order_stock`) and refunds the customer, at the cost of the vendor's
rating and the platform's cut (`commission_lost`). Nothing warns anyone first.

**Fix.** A `low_stock_threshold` per product (default sensible, editable), a
badge on the products list, a dashboard card listing what needs restocking, and a
transactional notification when a product crosses the threshold. Reuse the
existing notification pipeline, `queue_push` before commit as the guide requires.

---

## S3 — Correctness and hygiene

### S3-1. Four unjustified dangerous permissions

`app.json` declares `RECORD_AUDIO`, `ACCESS_BACKGROUND_LOCATION`,
`FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_LOCATION`. The vendor app has no
audio code (`grep -rn "Audio|expo-av|Recording"` → nothing) and no background
location — its only location use is three one-shot `getCurrentPositionAsync`
calls to place the store on a map. A store does not move.

Google Play requires justification for microphone and background location and
rejects apps requesting them with no matching feature. **Fix:** drop all four;
keep `ACCESS_COARSE_LOCATION` / `ACCESS_FINE_LOCATION`.

### S3-2. Backend refusals are replaced with generic text

Beyond `OrderDetail`'s `.response` bug (S2-1), the pattern repeats: `ManageStaff`
and `PayoutSettings` catch everything into "Network Error — Unable to reach
servers", including 400s that carry a specific, actionable reason. **Fix:** part
of the S2-1 migration — `errorMessage(err, fallback)` at every boundary.

### S3-3. Order status updates take no row lock

`update_order_status` (`vendor_management_service.py:296`) reads the order with
`session.get` and writes without `with_for_update`. Two staff on two devices —
the exact scenario the staff feature creates — can both transition the same
order. `assign_order_rider` does take a Redis lock (`:497`); status updates
should be equally careful. **Fix:** `with_for_update` and re-check the status
under the lock.

### S3-4. Money handled as `float`

`update_order_status:313-314` compares `float(order.platform_total)` against
`float(vendor.wallet_balance)`. The guide is explicit that money is `Decimal`.
The comparison is a gate on accepting cash orders, so a rounding artefact decides
whether a vendor can trade. **Fix:** `Decimal` throughout, via the existing
`_money` helper.

### S3-5. Staff assignment leaks account existence

`PUT /api/vendor/staff` (`:121`) looks the email up in Clerk and returns 404
"Staff member not found. Please ask them to download the app and sign up first."
versus 200 on success. Any vendor can test whether an arbitrary email has a Drop
account. **Fix:** same response either way; deliver the invitation out of band.

### S3-6. A single `staff_clerk_id` column behind a screen called "Manage Staff"

`Vendor.staff_clerk_id` holds one id. Assigning a second staff member silently
replaces the first, with a success toast. **Fix:** either rename the screen and
say so plainly, or model staff properly. Given the product intent — and that S1-1
shows staff is a real privilege boundary — a join table is the honest answer, but
it is schema work and belongs in its own phase.

---

## What is already correct

Worth recording so it is not "fixed" later by mistake:

- `POST /api/wallet/withdraw` resolves the wallet owner by `clerk_id` only, and
  correctly refuses staff. This is the pattern S1-1 should follow.
- `assign_order_rider` verifies the rider is `approved` for **this** vendor
  before assignment, under a Redis lock.
- Order cancellation restores stock, flags paid orders `refund_pending`, records
  `commission_lost`, and commits before notifying.
- The order state machine is validated centrally through
  `validate_status_transition` rather than re-implemented here.
- `user_type=vendor` is passed on every notification call, with a comment
  explaining why — a previous bug worth keeping documented.
- `useSessionCleanup` is mounted in the root layout.
- `OfflineBanner` exists and is wired into the layout.
- Bottle reconciliation reads from the ledger, not the registry, so radar riders
  who never registered are still visible.

---

## Sequencing

| Phase | Contents | Effort | Ships |
|---|---|---|---|
| **1 — Close the privilege holes** | S1-1, S1-2, S3-5, S2-5, S3-1 | ~1 day | Backend + config; no UX risk |
| **2 — Make multi-store real** | S1-3, S2-2, S2-4 | ~1.5 days | Contract change; needs the fallback to be right |
| **3 — Pay off the client debt** | S2-1, S1-4, S3-2 | ~1.5 days | One broad PR, full manual pass |
| **4 — Complete the product** | S2-3, S2-6, S2-7, S3-3, S3-4 | ~1.5 days | Independent of 1–3 |

Phase 1 first because S1-1 is exploitable today by anyone the owner has already
trusted with the app, and the fix is small and narrowing. Phase 2 before Phase 3
so the API client is built once, already store-aware. Phase 4 is additive.

**Total: ~5.5 engineering days.**

## Verification

Each phase lands with:

- Backend tests in the existing style, plus a structural test where the defect is
  structural (the owner-only scan, the no-raw-`fetch` scan) — both classes have
  already caught real regressions in this repo.
- `npx tsc --noEmit` clean on all three apps.
- `node scripts/preflight.js --strict` clean.

---

## Outcome — 2026-07-31

All four phases are implemented. Every finding above is closed except S3-6, which
is deliberately deferred (see below).

### Delivered

**S1-1 / S1-2 / S3-5 — the privilege boundary.** `get_vendor_owner` and
`get_owned_store` in `dependencies/auth_dependencies.py`; `PUT /profile`,
`PUT /staff` and `PUT /rider-action` gated on them.
`payout_service._get_provider_details` resolves a payee by `Vendor.clerk_id`
alone and answers `403 {"type": "owner_only"}` to staff. Staff assignment now
returns the same body whether or not the address belongs to a Drop account.
Guarded by `tests/test_vendor_owner_enforcement.py`, whose AST route inventory
fails the build when a new vendor route is added without being classified.

**S1-3 / S2-2 / S2-4 — multi-store.** A store is named per request in an
`X-Store-Id` header, validated against the caller's own stores (404, not 403, for
one they do not own) with a deterministic `ORDER BY created_at ASC LIMIT 1`
fallback. Six `scalar_one_or_none()` calls that raised `MultipleResultsFound` on
a second store are gone — including `profile-status` and `push-token`, which the
app calls before anything else, so opening a branch had turned startup into a 500
and the client's `catch` sent the vendor back through onboarding. The switcher
writes to a persisted Zustand store the API client reads; `useStoreScopedCache`
empties the query cache on a switch, because requests are scoped by header and
React Query cannot otherwise tell the two stores' answers apart.
`GET /orders` and `GET /products` return `{items, limit, offset, has_more}`.

**S2-1 / S3-2 / S1-4 — the client layer.** All 48 raw `fetch` calls now go
through `API/useApiClient.ts` (React) or `API/apiFetch.ts` (outside it), both
built on `ApiError`. `errorMessage(err, fallback)` at every boundary.
`GET /api/vendor/wallet-summary` and the balance card show
`wallet_balance − committed_cash_float`, so a refusal no longer contradicts a
number the app has just displayed. Guarded by `tests/test_vendor_api_client.py`.

**S2-3 — paused orders.** One shared `constants/orderStatus.ts` (two divergent
colour maps is how both states got missed in both screens), filter entries for
each, and `GET /api/vendor/orders/{id}/review` returning the rider's reason and
signed photographs.

**S2-6 — uploads.** `POST /api/vendor/upload-image`, authenticated, store-scoped,
content-sniffed and size-capped, returning an S3 key. The unsigned Cloudinary
preset is gone from both copies. Product images and the store avatar are presigned
on the way out like every other image on the platform. `Profile.tsx` was also
writing the entire photo into the column as a base64 data URI.

**S2-7 — low stock.** `Product.low_stock_threshold` per product (0 disables),
`low_stock_notified_at` so the vendor is told once per crossing rather than once
per unit sold below the line, a dashboard card, a list badge, a form field, and a
notification that points at a screen that exists. Migration
`c7d1a4f92b08_add_low_stock_threshold`.

**S3-3 / S3-4 — the accept path.** `update_order_status` reads the order
`FOR UPDATE`, and the cash-float gate is `Decimal` and subtracts
`committed_cash_float_for_vendor` — accepting against the raw balance is how a
vendor ends the day owing the platform.

### Found during the work, not in the original audit

- `Order.status` is not a column (`order_status` is). All three branches of
  `DELETE /delete_account` filtered on it, so the endpoint answered 500 for every
  user type and its active-order guard never ran. Two of the hardcoded values
  were not platform statuses at all.
- `GET /api/wallet/transactions` was called without `user_type`, which defaults
  to `customer`. The vendor's transaction list queried the customer ledger for a
  clerk id with no customer rows, and the screen rendered its empty state over a
  live balance. `WalletScreen` also treated the `{data, nextCursor, …}` envelope
  as an array, so it threw on render.
- `DELETE /api/auth/push-token` was called without `app_type=vendor`, so signing
  out never detached the token from the store — the exact failure the call exists
  to prevent, on the shared till device it was written for.
- Push-token registration wrote to one `Vendor` row, so a multi-store owner only
  ever received notifications for one of their branches.
- Four screens (`StoreProfile`, `OwnerProfile`, `OperatingHours`,
  `PayoutSettings`) read `owners_name`, `phone_number`, `business_license`,
  `deposit_fee`, `shift_start`/`shift_end` and `preferred_payment_method` from
  the **dashboard** response, which returns none of them. The forms opened blank
  and saving them wrote empty values over the vendor's real details.
- `OrderDetail` found its order by scanning the list the dashboard had loaded, so
  any order past the first page rendered "Order not found". Now
  `GET /api/vendor/orders/{order_id}`.
- `app/index.tsx` routed to onboarding from a bare `catch`, so a timeout at
  startup sent an established vendor back through sign-up.
- Editing a product would have written the **presigned** image URL back into the
  column once uploads moved to S3, expiring the image 15 minutes later. The
  update now omits `image_url` when it has not changed.
- Several mutations checked `res.ok` and, when false, did nothing at all — a
  refused product delete refetched, the product reappeared, and the vendor was
  told nothing.

### S3-6 — staff, modelled properly (done 2026-08-01)

Originally deferred as "a feature, not a fix". Built out in full.

`Vendor_Staff` (migration `d3e5f7a91c24`) replaces `Vendor.staff_clerk_id`, which
held one id, carried a **platform-wide** UNIQUE constraint, and was the entire
access model:

- a store could have exactly one staff member, and adding a second silently
  replaced the first — behind a screen called "Manage Staff";
- one person could be staff of exactly one store on the whole platform;
- access was all-or-nothing: `get_current_vendor` admitted staff to everything
  that was not owner-only, so handing someone the till handed them the
  catalogue, the bottle ledger and the wallet balance;
- `Vendor.staff_push_token` was one column on the *store*, so it addressed
  whoever registered last;
- there was no list, so an owner could not see who they had given access to.

What replaces it:

- **Many staff per store**, one row per (store, person), soft-revoked so who
  could act on a store and when survives in the audit trail.
- **Four capabilities** — `manage_orders`, `manage_products`, `manage_bottles`,
  `view_finances` — granted per member. New staff get the first three;
  `view_finances` is withheld by default, because seeing the store's balance
  should be a decision the owner makes rather than one inherited from a schema
  that could not express the question.
- **`StoreAccess`** carries who is asking, which store, and what they may do.
  `require_permission("…")` gates every mutating route; refusals are
  `{"type": "permission_required", "permission": …}` so the client routes on the
  discriminator, never the wording.
- **Invitation by email**, recorded whether or not the address has a Drop
  account and bound on that person's first sign-in. The reply is byte-identical
  either way — the old endpoint's 404-vs-200 let any vendor test whether an
  arbitrary email is registered here.
- **`GET/POST/PATCH/DELETE /api/vendor/staff`**, and a rebuilt `ManageStaff`
  screen: the roster, pending-invitation state, per-member permission switches,
  and revoke.
- Push tokens live on the membership row, so a store with several staff reaches
  all of them, and `expo_push_service` purges a dead token from there too.

The predecessor columns are **left in place and unread** — the expand half of an
expand/contract, so an application rollback does not lose anybody's access.
`tests/test_vendor_staff.py` tokenizes every module under `routes/`, `services/`,
`dependencies/`, `jobs/` and `utils/` and fails the build if either is read
again. Dropping them is a follow-up migration, once the deployed backend is known
to be reading the table.

---

## Verification performed — 2026-08-01

- **Both migrations applied to the live Neon database** (Postgres 17), not just
  written: `c7d1a4f92b08` (low stock) and `d3e5f7a91c24` (staff). Columns,
  indexes and defaults confirmed by querying `information_schema`; all 114
  product rows took the threshold default; `alembic_version` is `d3e5f7a91c24`.
- **Multi-store proved with real rows.** `tests/test_multi_store_integration.py`
  builds two stores for one owner plus a third owned by somebody else, drives the
  real FastAPI app against the real database, and asserts each endpoint acts on
  the store named in `X-Store-Id`; that the no-header fallback is deterministic
  across repeated calls; that another owner's store is a 404; that `GET /stores`
  ignores the header; and the full staff-permission matrix. 15/15 pass. It cleans
  up after itself — the vendor and product counts were identical before and
  after, and no `Vendor_Staff` rows remained.
- 402 backend tests pass. `npx tsc --noEmit` clean on all three apps.

### The local `venv/` was corrupted — rebuilt 2026-08-01

Not caused by this work. A find/replace of `vepo` → `drop`, case-insensitive and
case-preserving, was applied across the whole tree at some point and reached
`BackendAPI/venv/lib/python3.12/site-packages/`. It hit three ordinary words
that happen to contain the substring:

| Word | Became | Packages | Effect |
|---|---|---|---|
| `savepoint` | `sadropint` | SQLAlchemy, asyncpg, psycopg2, pygments | **Functional.** Every nested transaction was a Postgres syntax error |
| `CURVEPOLYGON` | `CURDROPLYGON` | GeoAlchemy2, shapely | Docstrings and test fixtures only |
| `Shreveport` | `Shredroprt` | faker | Test data only |

Only the first mattered, and it mattered a lot — `asyncpg/transaction.py` was
emitting `SADROPINT sa_sadropint_1`, verified against the live database.

The blast radius was established by verifying every installed file against the
SHA-256 pip records in each `*.dist-info/RECORD`, rather than by grepping for
words we had guessed at: **38 mismatches across 8 packages**. (One of the 38,
`bin/fastapi`, reproduces in a clean install — pip rewrites console-script
shebangs after hashing — so the real figure is 37.)

Rebuilt from `requirements.txt`. Two things surfaced during the rebuild:

- **`pip freeze` from the old venv was not reinstallable.** `safety`, a local
  dev tool never listed in `requirements.txt`, pulls in `authlib` → `joserfc` →
  `cryptography>=45.0.1`, while `clerk-backend-api==2.2.0` requires
  `cryptography>=44.0.1,<45.0.0`. pip calls that resolution impossible; the venv
  only held it because the packages went in one at a time. Rebuilding from
  `requirements.txt` — what Render installs — resolves cleanly and `pip check`
  passes.
- **`aiosqlite` was missing from `requirements.txt`** despite
  `tests/conftest.py` running the suite on `sqlite+aiosqlite`. A clean checkout
  could not collect the tests. Now listed.

Versions moved only for unpinned transitive packages (boto3, requests, urllib3,
pytest and similar, all patch/minor). Everything load-bearing — SQLAlchemy
2.0.41, asyncpg 0.30.0, FastAPI, pydantic, clerk-backend-api — is pinned and
unchanged. 417 tests pass on the rebuilt environment, identical to before.

`test_multi_store_integration.py` still uses explicit row cleanup rather than a
transaction rollback. That was originally a workaround for this defect; it is
kept because cleanup that survives a hard failure is the better pattern anyway.

### Still outstanding for you

- **Set `CLERK_SECRET_KEY`** wherever the backend runs. Staff invitations and
  account deletion both fail closed with 503 without it. Full procedure and the
  same-instance pitfall: `docs/render-environment.md`. Verify with
  `python scripts/check_clerk_secret.py`.
- **Apply `e6b2c8d40f17`** (drops `Vendor.staff_clerk_id` /
  `Vendor.staff_push_token`) — written, deliberately **not applied**. The
  currently deployed backend still reads those columns, so dropping them now
  breaks production. The migration's docstring carries the four-step sequence;
  step 3, deleting the columns from `models/vendor_model.py` and deploying that
  *before* running the migration, is the one that is easy to miss.
