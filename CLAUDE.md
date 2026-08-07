# Drop Multivendor Water Delivery Platform — Developer Guide

Instructions and context for AI coding assistants working on the Drop platform.
Each sub-project carries its own `CLAUDE.md` with the rules specific to it; read
that one too before changing anything in that directory.

## Architecture & monorepo structure

Four client surfaces, **one** FastAPI backend and **one** database. There is no
second API and no separate admin datastore — a figure on the console and a figure
in a vendor's app cannot drift apart when they come from the same query.

- `BackendAPI/` — Python FastAPI backend, plus an ARQ worker in its own process.
- `drop-customer-app/` — Expo app for customers.
- `drop-rider-app/` — Expo app for delivery riders.
- `drop-vendor-app/` — Expo app for water vendors and their staff.
- `drop-admin/` — Next.js App Router operations console, deployed on Vercel.
- `docs/` — architecture, runbooks, deployment, audits. Start at `docs/README.md`.

## Coding conventions

### Backend (FastAPI / Python)
- Standard Python typing and Pydantic v2.
- Modular: `routes/`, `services/`, `models/`, `schemas/`, `jobs/`, `dependencies/`.
- `geoalchemy2` for PostGIS; H3 res-8 for bucketing before the exact pass.
- WebSockets live in `websocket_routes.py` and `order_service.py`, over Redis pub/sub.
- Background work is ARQ (`worker.py`), which runs as a **separate process**. `RUN_INLINE_WORKER=1` is for a single-process dev machine only — inside the API, every replica runs its own copy of the cron schedule.
- Contended rows (accepting an order, moving a wallet, settling bottles) are taken with `select(...).with_for_update()`. Sweeps use `FOR UPDATE ... SKIP LOCKED` and commit per item.

### Mobile apps (React Native / Expo)
- **Styling**: NativeWind. Dark mode is required on every screen.
- **State**: TanStack Query for server state, Zustand for client state.
- **Routing**: Expo Router (file-based).
- **Data fetching**: custom hooks over the app's API client (`useApiRequest()` / `apiFetch`). Never fetch inside a component, and never use raw `fetch` — three separate test suites fail the build if one reappears.
- **Errors**: surface the backend's own message through `Toast.error(..., errorMessage(err))`. Never show a raw status code, and never branch on the wording of a message — branch on `ApiError.type` or `.status`.

### Admin console (Next.js)
- `lib/api/server.ts` is `server-only`; importing it from a Client Component is a build error. Client components call a Server Action, which calls that module. The browser never holds an API token.
- Every destination is declared once in `components/shell/nav-config.ts`; a test fails the build if a `page.tsx` has no entry.
- Semantic tokens only (`bg-surface`, `text-muted`, `border-default`).

## Common tasks

### Backend
```bash
cd BackendAPI
source venv/bin/activate
uvicorn main:app --reload
arq worker.WorkerSettings          # second terminal
pytest -q --ignore=tests/test_multi_store_integration.py
```

### Expo apps
```bash
cd drop-rider-app                  # or vendor / customer
pnpm install
npx tsc --noEmit                   # before every push
pnpm start
```

### Admin console
```bash
cd drop-admin
pnpm install
pnpm dev                           # http://localhost:3000
pnpm typecheck && pnpm build
```

## Security & guardrails

Platform-wide invariants. Most are enforced by a test that parses the source and
fails the build, so breaking one is a CI failure rather than a production
incident.

- **Proof of delivery**: completing an order with `emptiesReceived < computedEmptiesExpected` requires a photo. **Do not bypass this check in a `catch` block** — a failed upload is a failed completion.
- **KYC**: riders stay blocked in `VerificationWall` until `kyc_status == "approved"` is *positively confirmed*. The gate fails closed; an errored status query is not permission.
- **Money is `Decimal`, never `float`**, from the database through the API to the string the client formats. On the frontend use `sumMoney()`, never `reduce((a,b) => a + Number(b))`.
- **One pricing path.** `services/pricing_service.py::compute_order_quote` is the only place an order total is computed. Never re-derive one on a client or in a second service.
- **Business values are rows**, not constants — 46 settings in `Platform_Settings`, edited from the console, live on the next quote. A figure that belongs to the business and sits in the source is a defect; four of the audit's fourteen findings were exactly that.
- **Two push paths only**: `queue_push` before a commit, `dispatch_background` after. A bare `asyncio.create_task(send_push_message(...))` fails the build.
- **Never read `Vendor.staff_clerk_id` or `staff_push_token`.** Staff are `Vendor_Staff` rows with four capabilities.
- **Every order-scoped endpoint, REST and WebSocket, calls `authorise_order_access`.** Authenticating proves who is calling, not that they have anything to do with that order.
- **Never call a Google web service from a client.** The embedded keys are SDK-restricted and cannot; `routes/maps_routes.py` owns Directions, Places and Geocoding on the IP-restricted server key.
- **Personal data**: lists render masked values for every role. Revealing an identity document is an audited action requiring `pii.view` and a stated reason, presigned for 5 minutes, and rendered with a plain `<img>` — `next/image` would cache somebody's national ID on a server.
- **Moderated reviews are excluded from every public read** and from the target's rating, in the same transaction.
- **Every withdrawal path calls `settlement_service.assert_withdrawable`.** A wallet balance is not what is spendable — float promised to open cash orders is settled at delivery. Two paths existed and only one checked.
- **`revert_order_side_effects` is the only way to cancel an order.** It undoes seven things; six call sites each remembering a different subset is how `commission_lost` went missing on vendor rejects.
- **Products are withdrawn (`deleted_at`), never deleted**, and every catalogue read carries `live_product()`. `Order_Items` references them and the bottle ledger reads their capacity.
- **A customer's deposit is a liability the platform can return.** `customer_bottle_service` moves `bottle_deposit_balance` and `bottles_held` together, never one alone.
- **Never coalesce a missing capability with `?? 0`** in the console. `undefined` means "not yours"; `0` means "nothing waiting". A badge that renders the first as the second leaks the size of a table the caller cannot see.

## Migrations

The repository head, `e6b2c8d40f17`, is **gated on purpose**: it drops the legacy
single-staff columns and refuses to run without `ALLOW_STAFF_COLUMN_DROP=true`.
Routine deploys should target `b8e3d1a5c704`. The expand/contract sequence is in
that migration's own docstring.

A new revision goes **before** the gated drop, never after it — anything parented
on `e6b2c8d40f17` could only ever run on a deploy that had already accepted the
column drop.
