# 💧 Drop — Multivendor Water Delivery Platform

> A Kenya-focused multivendor water delivery marketplace. Three React Native apps
> — Customer, Rider, Vendor — plus a web operations console, all served by a
> single FastAPI backend.

---

## 📦 Repository structure

```
Multivendor-Water-Delivery-App/
├── BackendAPI/          # FastAPI backend — the only server, shared by all four clients
├── drop-customer-app/   # Expo app — customers order water
├── drop-rider-app/      # Expo app — riders deliver it
├── drop-vendor-app/     # Expo app — stores sell it
├── drop-admin/          # Next.js console — the owners run the business from it
├── docs/                # Architecture, runbooks, deployment, audits
└── docker-compose.yml   # Local PostgreSQL + PostGIS + Redis
```

There is **one backend and one database**. The console is not a second system: it
calls the same FastAPI service the phones call, so a figure on a dashboard and a
figure in a vendor's app cannot drift apart.

---

## 🏗️ System architecture

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐   ┌──────────────────┐
│ Customer app │ │  Rider app   │ │  Vendor app  │   │   drop-admin     │
│    (Expo)    │ │    (Expo)    │ │    (Expo)    │   │  (Next.js BFF)   │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘   └────────┬─────────┘
       │                │                │                    │
       │   HTTPS + WebSocket, Clerk JWT  │      HTTPS, token minted server-side
       └────────────────┼────────────────┴────────────────────┘
                        │
              ┌─────────▼──────────┐        ┌──────────────────────┐
              │     BackendAPI     │◀──────▶│  ARQ worker process  │
              │  FastAPI (async)   │        │  (cron + background) │
              └─────────┬──────────┘        └──────────────────────┘
          ┌─────────────┼─────────────┬──────────────┐
     ┌────▼─────┐  ┌────▼────┐  ┌─────▼────┐  ┌──────▼──────┐
     │ Postgres │  │  Redis  │  │  AWS S3  │  │  M-Pesa /   │
     │ +PostGIS │  │ pub/sub │  │ KYC+proof│  │  Clerk /    │
     │  + H3    │  │ + queue │  │ (private)│  │  Expo Push  │
     └──────────┘  └─────────┘  └──────────┘  └─────────────┘
```

**The browser never holds an API token.** `drop-admin` is a
backend-for-frontend: every call goes through its Next.js server, which mints a
Clerk token per request. The console renders national ID photographs; an XSS on
any page of it must not also hand over an admin API token.

---

## 🔄 Business workflow

### Order state machine

```
pending → unassigned → accepted → preparing → ready → picked_up → delivered
   │          (paid)                                        │
   │                                                        ├─→ pending_review    (rider flags a bottle mismatch)
   └─→ cancelled                                            └─→ mismatch_pending  (vendor flags a quantity issue)
```

### End to end

1. **Customer** browses nearby stores, builds a cart, and pays by **M-Pesa STK Push**.
2. **Backend** confirms via callback, writes an `Order` at `unassigned`.
3. **Dispatch, tier 1** — an available in-house rider registered to that store is offered it first.
4. **Dispatch, tier 2** — otherwise the Trip Radar broadcasts to nearby gig riders over WebSocket; the first to accept claims it under a row lock.
5. **Vendor** prepares, marks `ready`.
6. **Rider** collects (`picked_up`) and navigates; the customer watches the marker move in real time.
7. **Rider** completes:
   * clean delivery → `delivered`, and the revenue split credits both wallets in one transaction;
   * bottles short → **photo proof is mandatory**, order goes to `pending_review`, an ARQ sweep auto-resolves it if nobody adjudicates;
   * quantity dispute → `mismatch_pending` for the store.
8. **Customer** rates the store and the rider.
9. **Empties** the rider collected are accrued against the store in an append-only bottle ledger, and settled when the store confirms receipt.

---

## 💰 Revenue model

Commission rates, fees and delivery pricing are **rows in `Platform_Settings`,
not constants** — 34 settings across 6 groups, editable from the console at
`/platform/pricing` and live in all three apps on the next quote. The values
below are the shipped defaults, not hard-coded behaviour.

| Participant | Retail (B2C) | Wholesale (B2B) |
|---|---|---|
| **Platform** | 5% vendor commission + KSH 12 service fee | 2.5% commission + KSH 50 service fee |
| **Rider — gig** | 90% of the delivery fee | 90% |
| **Rider — platinum** | 93% | 93% |
| **Rider — in-house** | 100% | 100% |
| **Vendor** | product revenue less commission | product revenue less commission |

Surge is +KSH 10 in the peak windows (06:00–08:00 and 17:00–19:00 EAT).

> **One pricing path.** `services/pricing_service.py::compute_order_quote` is the
> only place an order total is computed. The client renders that quote verbatim,
> M-Pesa is charged `quote.stk_amount`, and the order row stores the same
> `quote.total`. `tests/test_pricing_parity.py` asserts they are equal across the
> full matrix of vendor type × surge × first order × wallet × delivery type.

---

## 🗺️ Geospatial rules

| Rule | Retail (`retail_refill`) | Wholesale (`wholesale_b2b`) |
|---|---|---|
| Max delivery distance | 2 km | 15 km |
| Max items per order | 4 × 20L | 200 bottles |
| Minimum order weight | none | 100 kg |
| Rider search radius | 2 km from the store | 15 km |
| Vehicle classes | motorbike | motorbike / tuktuk / truck |

Discovery uses **H3 hex indexing at resolution 8** with PostGIS `ST_DWithin` for
the exact-distance pass.

> **Google web services never run on a client.** The keys embedded in the apps
> are restricted to the Maps **SDK** for one bundle id each, which is what makes
> embedding them safe — and also means they cannot call Directions, Places or
> Geocoding. Those go through `BackendAPI/routes/maps_routes.py` on a single
> IP-restricted server key, which authenticates, rate-limits, caches on rounded
> coordinates, and never forwards Google's error text. See
> [docs/maps-architecture.md](./docs/maps-architecture.md).

---

## 🔑 Authentication and authorisation

All four clients authenticate through **[Clerk](https://clerk.com/)** — one
application, so somebody who is both an administrator and a vendor is one
identity. The backend verifies RS256 against the pinned JWKS with audience and
issuer checked; the `sub` claim is the `clerk_id` that links to the row.

| Surface | Who may act | How it is decided |
|---|---|---|
| Customer app | the signed-in customer | `clerk_id` on `Users` |
| Rider app | the signed-in rider | `clerk_id` on `Deliverers`, **plus** `kyc_status == "approved"` before any delivery |
| Vendor app | the store owner, or staff | `Vendor_Staff` rows with four capabilities: `manage_orders`, `manage_products`, `manage_bottles`, `view_finances` |
| Admin console | rows in `Admin_Users` | 26 capabilities (`domain.action`), 5 role presets that expand on assignment |

Roles are **presets, not authority**: assigning one expands into a permission
set, and the role name is never consulted when deciding an action. Revocation
takes effect on the next click, because every request re-reads the row.

---

## 🧰 Tech stack

### Backend
| Concern | Choice |
|---|---|
| Runtime | Python 3.12, FastAPI, Uvicorn |
| Database | PostgreSQL + PostGIS, SQLAlchemy 2.0 async, Alembic |
| Cache / queue | Redis — WebSocket pub/sub, rate limiting, ARQ job queue |
| Background | ARQ, **as its own process** (see below) |
| Payments | M-Pesa STK Push (C2B), B2C for payouts, reversals for refunds |
| Storage | AWS S3, private, presigned on read |
| Auth | Clerk backend API, RS256 with pinned JWKS |
| Geospatial | H3 res-8 + GeoAlchemy2/PostGIS |
| Push | Expo Push Notification Service |
| Observability | Sentry, Prometheus, JSON logs with correlation ids |

### Mobile apps (all three)
Expo SDK 54 · React Native 0.81 · React 19 · Expo Router 6 · NativeWind v4 ·
TanStack Query v5 · Zustand v5 · `@clerk/clerk-expo` · `react-native-maps` ·
`expo-notifications`

### Admin console
Next.js 16 App Router (Turbopack) · React 19 · Tailwind v4 · `@clerk/nextjs` ·
Recharts · Google Maps JavaScript API · deployed on Vercel

---

## 🖥️ The admin console

`drop-admin` is where the business is run rather than merely watched. 27 destinations,
none of which is a bare table with a search box — every page carries the
aggregates that tell an operator whether anything needs doing.

| Area | Screens |
|---|---|
| **Operations** | Orders board · Rider verification (KYC) · Live map · Catalogue · Bottle float · Vendor verification · Bottle disputes · Reviews · Delivery replay |
| **People** | Performance · Fleet · Customers · Riders · Vendors |
| **Finance** | Payouts · Transactions · Reconciliation · Settlement |
| **Support** | Ticket inbox and threads |
| **Platform** | Administrators · Audit log · Notifications · Broadcast · Pricing · Settings |

A few of these exist because the platform was holding evidence nobody could
look at:

* **Delivery replay** answers "the rider says they delivered it, the customer says they didn't" from the rider's own location pings — and returns *no verdict* rather than a denial when there is no data to speak from.
* **Bottle float** prices the empties riders are holding at the same deposit the customer paid, and checks the registry counters against the append-only ledger they denormalise.
* **Settlement** surfaces failed payouts that were never returned to the wallet — money debited before the M-Pesa call and never given back.
* **Reconciliation** shows payment callbacks that failed: the customer paid Safaricom and the order stayed `pending`.

Every mutating action is audited, most require a written reason, and neither
refunds nor failed webhooks offer a "retry" — a reversal that succeeded but lost
its callback is indistinguishable from one that failed.

---

## 🚀 Local development

### Prerequisites
Docker · Python 3.12 · Node 20+ · pnpm · Expo CLI · an Android emulator or device

### 1. Infrastructure
```bash
docker-compose up -d          # PostgreSQL + PostGIS, Redis
```

### 2. Backend
```bash
cd BackendAPI
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in secrets
alembic upgrade b4c7e2a91f30  # see the migration note below
uvicorn main:app --reload --port 8000
```

In a second terminal:
```bash
arq worker.WorkerSettings     # its own process — not optional
```

> **Migration head.** The repository head, `e6b2c8d40f17`, drops the legacy
> single-staff columns and **refuses to run** without `ALLOW_STAFF_COLUMN_DROP=true`.
> That guard is deliberate: applying it while any instance still maps those
> columns turns every vendor request into `UndefinedColumn`. Routine deploys
> should target `a9f4b2c71d63`. Full procedure in the migration's own docstring.

### 3. Admin console
```bash
cd drop-admin
pnpm install
cp .env.example .env.local
pnpm dev                      # http://localhost:3000, already in ALLOWED_ORIGINS
```

### 4. Mobile apps
```bash
cd drop-customer-app   # or drop-rider-app / drop-vendor-app
pnpm install
cp .env.example .env
pnpm start
```

`10.0.2.2` is the Android emulator's alias for the host. On a physical device use
your machine's LAN address — `localhost` reaches the handset, not your laptop.

---

## ✅ Checks before you push

```bash
cd BackendAPI && source venv/bin/activate
pytest -q --ignore=tests/test_multi_store_integration.py   # 617 passed, 1 skipped

cd ../drop-admin && npx tsc --noEmit && npx next build

cd ../drop-rider-app && npx tsc --noEmit                   # and the other two apps
```

The backend suite is not only unit tests. Several files walk the source with
`ast` and fail the build on a structural regression — a push fired outside the
two sanctioned paths, a vendor route added without a capability, an admin route
added without a permission gate, a review query that forgets to exclude
moderated rows, a settlement screen that grows a "retry" button.
`tests/test_multi_store_integration.py` needs a live Postgres and is excluded
above; run it separately when touching store resolution.

---

## 📋 Environment

Full annotated tables live in
[docs/render-environment.md](./docs/render-environment.md). The essentials:

### Backend (`BackendAPI/.env`, and Render)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL async connection string |
| `REDIS_URL` | Redis / Upstash (`rediss://` for TLS) |
| `CLERK_SECRET_KEY`, `CLERK_ISSUER`, `CLERK_JWKS_URL` | Token verification. All three must name the **same** Clerk instance |
| `DB_ENCRYPTION_KEY` | Encrypts payout destinations at rest |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME` | Private storage for KYC and delivery proof |
| `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_SHORTCODE`, `MPESA_PASSKEY` | STK Push |
| `MPESA_B2C_*`, `MPESA_REVERSAL_*` | Payouts and refunds |
| `MPESA_CALLBACK_URL`, `MPESA_CALLBACK_SECRET` | Payment callbacks and their shared secret |
| `SMS_WEBHOOK_SECRET`, `CRON_SECRET` | Shared secrets for the inbound webhook and scheduler |
| `GOOGLE_MAPS_SERVER_API_KEY` | IP-restricted; Directions, Places, Geocoding |
| `ALLOWED_ORIGINS` | CORS. Must include the console's origin |
| `ADMIN_2FA_REQUIRED` | Whether the console demands two-factor. **Render only** |
| `RUN_INLINE_WORKER` | `1` only on a single-process dev machine |
| `SENTRY_DSN`, `ENV` | Observability and environment name |

### Mobile apps (`.env` in each)

| Variable | Notes |
|---|---|
| `EXPO_PUBLIC_BACKEND_BASE_URL` | Inlined into the bundle — nothing secret goes in an `EXPO_PUBLIC_*` |
| `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY` | Same Clerk application as everything else |
| `GOOGLE_MAPS_ANDROID_API_KEY` / `GOOGLE_MAPS_IOS_API_KEY` | **Not** `EXPO_PUBLIC_*`. Build-time only, injected by `app.config.js` into the manifest / plist, one key per platform because a Google key carries one application restriction |

### Admin console (`.env.local`, and Vercel)

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | Same Clerk application |
| `BACKEND_BASE_URL` | Deliberately **not** `NEXT_PUBLIC_` — the browser never calls FastAPI |
| `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | The one deliberately public key. Restrict to **Websites** + **Maps JavaScript API only** |

---

## 🔐 Guardrails

Rules that hold across the whole platform. Most are enforced by a test that
fails the build.

* **Money is `Decimal`, never `float`** — from the database through the API to the string the client formats. `sumMoney()` on the frontend, never `reduce(+Number(...))`.
* **Totals are never computed on a client.** One quote, one charge, one stored total.
* **Proof of delivery is mandatory on a deficit.** If `emptiesReceived < computedEmptiesExpected`, a photo is required — and the check is never bypassed in a `catch`.
* **Riders are blocked until KYC is approved**, in the app's `VerificationWall` and again on the server.
* **Two push paths only**: `queue_push` before a commit (an `after_commit` hook sends it, a rollback discards it) and `dispatch_background` after. A bare `asyncio.create_task` fails the build.
* **`Vendor.staff_clerk_id` and `staff_push_token` are never read** — they survive only so a rollback does not lose anybody's access.
* **Every order-scoped endpoint, REST and WebSocket, calls `authorise_order_access`.** Authenticating proves who is calling, not that they have anything to do with that order.
* **Identity documents are revealed by an audited action, never rendered by default**, presigned for 5 minutes, and never through `next/image` — the optimiser would cache somebody's national ID on a server.
* **Every sweep claims rows with `FOR UPDATE ... SKIP LOCKED`** and commits per item, so a second worker degrades throughput rather than corrupting data.

---

## 📚 Documentation

| Document | What it covers |
|---|---|
| [docs/README.md](./docs/README.md) | Index of everything below |
| [docs/admin-dashboard-architecture.md](./docs/admin-dashboard-architecture.md) | Why the console is built the way it is, decision by decision |
| [docs/admin-console-deployment.md](./docs/admin-console-deployment.md) | Vercel, Google Cloud, Clerk, allow-lists — end to end |
| [docs/admin-console-runbook.md](./docs/admin-console-runbook.md) | Running it, and checking every screen as every role |
| [docs/platform-audit.md](./docs/platform-audit.md) | What was missing, what it cost, and what has since been built |
| [docs/render-environment.md](./docs/render-environment.md) | Every environment variable, annotated |
| [docs/maps-architecture.md](./docs/maps-architecture.md) | Six keys, one server key, and which calls go where |
| [docs/push-notifications.md](./docs/push-notifications.md) | The two sanctioned push paths and the preference model |
| [docs/cash-settlement.md](./docs/cash-settlement.md) | Wallet balance, committed cash float, withdrawal eligibility |
| [docs/cron-jobs.md](./docs/cron-jobs.md) | The scheduled sweeps and how they are triggered |
| [docs/security/google-api-key-rotation.md](./docs/security/google-api-key-rotation.md) | Rotating a leaked Maps key |

### Per-surface

| | |
|---|---|
| [BackendAPI/README.md](./BackendAPI/README.md) | Backend architecture, modules, process topology |
| [drop-admin/README.md](./drop-admin/README.md) | The console |
| [drop-customer-app/README.md](./drop-customer-app/README.md) | Customer app |
| [drop-rider-app/README.md](./drop-rider-app/README.md) | Rider app |
| [drop-vendor-app/README.md](./drop-vendor-app/README.md) | Vendor app |

Each directory also carries a `CLAUDE.md` — the same material aimed at an AI
coding assistant, with the invariants stated as rules rather than prose.
