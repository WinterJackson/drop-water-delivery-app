# Drop Admin — architecture

The console the Drop owners and staff run the business from. It manages every
user of all three apps — customers, riders, vendors and vendor staff — plus the
money, the disputes and the platform's own configuration.

It is a **Next.js app in `drop-admin/`**, talking to the **same FastAPI backend**
as the three mobile apps. No second database, no parallel API, no data that
exists only here.

---

## 1. Why this exists

`admin_routes.py` is four endpoints and there is no interface at all. Rider KYC
approval — the gate every rider is blocked behind — is a `PUT` you must
hand-craft with an admin bearer token. **Rider onboarding is therefore blocked
today**, which is why the delivery order below leads with it.

The existing four endpoints also carry defects that this work fixes rather than
builds on. They are catalogued in §9.

---

## 2. Decisions, and what they cost

### 2.1 Identity: the existing Clerk instance, authorisation in the database

Admins sign in through the **same Clerk application** as everyone else. A second,
admin-only Clerk app was considered and rejected: the real security boundary is
the permission record, not the token issuer, and you will have staff who are also
vendors. One identity keeps the platform in sync, which is the point of a single
backend.

The consequence to be honest about: **a customer's token is a structurally valid
token.** It is simply unauthorised. So the gate has to be airtight and it has to
be one gate — `require_admin(permission)` — never an ad-hoc check in a handler.

Compensating controls:

- **2FA is mandatory** for any Clerk user holding an admin record. Enforced in
  Clerk, asserted by the backend reading the session claim; an admin without it
  is refused with a message telling them to enrol.
- `ADMIN_CLERK_IDS` **is retired.** An env allowlist cannot express roles, cannot
  be audited, and needs a redeploy to revoke someone on their last day.

### 2.2 Transport: the Next server is a BFF, not a static client

Server Components and Route Handlers call FastAPI with a token obtained from
Clerk **server-side** (`auth().getToken()`). The browser holds an httpOnly
session cookie and never sees a bearer token.

This is a bigger deal here than on the mobile apps. This dashboard renders
national ID photographs, M-Pesa account details and the full customer table. An
XSS anywhere in it must not also hand over an admin API token. It additionally
removes the production CORS surface and lets one dashboard screen be assembled
from several backend calls in a single round trip.

Cost: one extra hop. Same region, single-digit milliseconds, and it buys
server-side caching that more than pays it back.

### 2.3 Capabilities, not job titles

The backend already models vendor staff as a **capability set**
(`VendorStaff.permissions`, `normalise_permissions`). Admins use the same shape,
for the same reason: "role" is too coarse the first time you need someone who
can review KYC but must not touch payouts.

Roles exist, but only as **named presets over the capability set** — chosen in
the UI, stored expanded, so removing a capability from a preset later cannot
silently re-grant it to existing staff.

---

## 3. Authorisation model

### 3.1 `Admin_Users`

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `clerk_id` | nullable until first sign-in — an invitation, exactly like `Vendor_Staff` |
| `email` | not null, the invitation key |
| `name` | |
| `role` | the preset the permissions came from, for display and filtering |
| `permissions` | JSONB, the authoritative grant |
| `is_active`, `revoked_at` | soft revoke; who could act, and when, is audit evidence |
| `invited_by`, `created_at`, `accepted_at`, `last_seen_at` | |

Mirrors `Vendor_Staff` deliberately — same invitation semantics, same soft
revoke, same "identical response whether or not the email has an account" so the
endpoint is not an account-existence oracle.

### 3.2 Capabilities

Namespaced `domain.action`. Read and write are always separate, and every
capability that exposes PII or moves money is separate again.

```
riders.read          riders.kyc_review     riders.suspend
vendors.read         vendors.approve       vendors.suspend
customers.read       customers.suspend     customers.erase
orders.read          orders.intervene
finance.read         finance.payout_approve  finance.refund_approve
disputes.read        disputes.resolve
analytics.read
pii.view                                    ← see §5
admins.manage
settings.manage
```

### 3.3 Role presets

| Role | Capabilities |
|---|---|
| `super_admin` | all, including `admins.manage` |
| `operations` | riders/vendors/orders/disputes read + act, `pii.view` |
| `finance` | `finance.*`, `analytics.read`, read-only elsewhere |
| `support` | `*.read`, `orders.intervene`, no `pii.view`, no finance |
| `analyst` | `analytics.read` + reads only. No PII, no actions |

`analyst` exists so business questions can be answered without handing anyone the
ability to change anything.

### 3.4 The gate

```python
async def require_admin(permission: str) -> AdminAccess   # dependency factory
```

Single implementation, mirroring `require_permission` in the vendor routes.
Returns `403 {"type": "permission_required", "permission": …}` — the same refusal
shape the apps already branch on. A structural test fails the build if any route
under `/api/admin` is registered without one.

---

## 4. Audit — the part that makes this defensible

Every mutation and every PII read writes an `Admin_Audit_Log` row **in the same
transaction as the change**. If the audit write fails, the action fails. An audit
trail that can be silently skipped is worse than none, because it is trusted.

| Column | Notes |
|---|---|
| `admin_id`, `admin_email` | email denormalised — the record must survive the admin being deleted |
| `action` | `rider.kyc.approve`, `payout.approve`, `customer.pii.view`, … |
| `target_type`, `target_id` | |
| `before`, `after` | JSONB, changed fields only |
| `reason` | required for destructive and PII actions |
| `ip`, `user_agent`, `created_at` | |

Append-only: no update or delete route exists, and the DB grant does not include
them. Viewable in-app by `admins.manage`, filterable by admin, action, target and
date.

---

## 5. Handling PII, which is the real risk here

This console displays national ID photographs, encrypted ID numbers and M-Pesa
account details. It is the highest-value target on the platform.

- **`pii.view` is its own capability.** `support` and `analyst` do not have it.
  Lists render `••••1234`; the full value requires an explicit reveal.
- **Revealing is an action, not a render.** A separate endpoint, audited with a
  mandatory reason, returning a value that was never in the list payload. You can
  answer "who looked at this rider's ID, and why" — which is the question that
  gets asked after an incident.
- **KYC documents are presigned for 5 minutes** in the admin context, not the
  default 15, and the URL is fetched on reveal rather than embedded in the list.
- **No PII in analytics.** Aggregates only, so `analyst` is structurally unable
  to reach it.
- **Export is a capability and is audited**, with the row count recorded.

---

## 6. What the dashboard contains

### Operations
- **KYC review queue** — documents side by side, approve/reject with a reason
  that reaches the rider's notification. Ages visibly; a rider waiting three days
  is an SLA breach, not a row in a list.
- **Live order board** — orders by state, stuck orders surfaced (accepted but
  undispatched, `mismatch_pending`, `pending_review`), with intervene actions:
  reassign rider, cancel with refund, force-resolve.
- **Disputes** — `BottleRejectionTicket` queue with the rider's photos and reason,
  resolving to a bottle-ledger adjustment. Outcomes are the ledger's vocabulary,
  `approved`/`denied`: a ticket is the rider's *rejection* of what they were
  given, so "approved" means that rejection stands. The console labels the two
  buttons "Uphold the rider" and "Reject the report".
- **Vendor verification** — confirming a store's paperwork, with the decision
  and reason reaching the vendor. Deliberately separate from suspension:
  rejecting records that documents are not in order, it does not stop the store
  trading. Whether verification *gates discovery* is the
  `require_vendor_verification` platform setting, off by default (§14).
- **Live map** — riders, stores, demand and orders in flight on one basemap,
  plus the coverage report: which stores have no rider who could serve them.
  Its own capability, `geo.view` — reading the KYC queue is not a reason to hold
  live positions for identified people.

### People — every user of all three apps
- **Customers** — profile, orders, wallet, bottle debt, notes, suspend, KDPA erase.
- **Riders** — KYC state, earnings, cash float, bottle debt, performance, vendor
  affiliations, suspend.
- **Vendors** — verification, store details, products, staff roster (read-only
  view of `Vendor_Staff`), wallet, payouts, commission tier, suspend.
- Each is a **detail page with a timeline**, not just a row: an admin answering a
  support call needs the history in one place.

### Finance
- Revenue and GMV over time, split by the existing ledger columns
  (`vendor_commission`, `service_fee`, `rider_commission`, `delivery_markup`,
  `surge_fee`) — the schema already carries this and nothing reads it.
- **Payout approval** with dual control above a configurable threshold.
- Reconciliation: withdrawals stuck in `processing`, wallets in arrears.
- Refund approval.
- **Transactions** — the wallet ledger and the M-Pesa collections, keyset
  paginated. The row that matters is *unresolved collections*: a `pending`
  payment older than an hour is an STK push the customer either ignored or paid
  without the callback arriving, and the second case is somebody charged for an
  order the platform does not think exists.
- **Adjusting a balance by hand** — its own capability (`finance.adjust`), held
  by no preset but super admin. See §14.

### Support
- **The queue** — tickets raised from the three apps, oldest first, because a
  support queue sorted newest-first is how somebody waits a week. Internal notes
  live in the same thread and are stripped at the API boundary, never left to
  the client not to render.

### Analytics
Orders, GMV, take rate, unit economics per order, vendor and rider leaderboards,
retention cohorts, delivery-time distribution, dispute rate, geographic demand
from the existing `h3_index_res8`.

### Platform
- **Administrators** — the roster, role presets, capability grants, revocation.
- **Audit log** — every administrative action with the reason given, append-only.
- **Pricing & fees** — every number the platform earns from, editable, with a
  live preview of what the change does to a typical order.
- **Broadcast** — messaging a segment of the platform.
- **Settings** — the *deployment's* switches: process environment variables,
  read-only and labelled as such, because a toggle that appeared to work and
  silently did nothing until the next deploy would be worse than no toggle. It
  also reports whether each integration credential is *present* — never its
  value — because a missing credential fails quietly (uploads that never arrive,
  pushes never delivered) and this is the fastest way to find out which one.
  Business values are **not** here; they are rows, on the pricing screen.

Section 14 covers support, broadcast, the map, the ledger and dynamic pricing in
full — they were built after the shell.

---

## 7. Frontend architecture

| Concern | Choice | Why |
|---|---|---|
| Framework | Next.js App Router, TypeScript strict | Server Components make the BFF natural |
| Auth | `@clerk/nextjs` middleware | Same instance as the apps |
| Styling | Tailwind CSS v4 | Matches NativeWind vocabulary already in the repo |
| Components | `components/ui/primitives.tsx` | Eight primitives, one file, all read |
| Server state | Server Components + Server Actions | No client cache to keep coherent |
| Charts | Recharts, plus hand-drawn SVG | See below |
| Forms | Plain `<form method="GET">` and Server Actions | Works before hydration |

Three of these differ from what was originally planned, and the reasons are
worth recording.

**No shadcn/ui.** It generates a large surface of Radix-backed components, of
which this console needs about eight. The ones it does need are in
`components/ui/primitives.tsx` — deliberately small, because a component library
nobody has read gets bypassed the first time it does not quite fit, and then the
console has two button styles.

**No TanStack Query, and no client data fetching at all.** Every screen is a
Server Component that awaits `lib/api/server.ts`; mutations are Server Actions
that `revalidatePath`. A client cache would have to be invalidated correctly
after every approval, and an admin acting on a stale payout queue is worse than
an admin waiting 200ms. It was declared in `package.json` and never imported —
removed, along with `zod`, which the same decision made unnecessary.

**No TanStack Table.** The lists here are 20–100 rows of server-paginated data
with no client sorting; a table library would ship a client bundle to render a
`<table>` that already renders on the server.

### Responsive, and what that actually means here

Not a media query at the end. Below `lg` the console has a genuinely different
navigation, and below `md` the data tables have genuinely different markup.

- **Sidebar** (`lg` and up) — grouped, capability-filtered, with live queue
  depths beside the entries that need working.
- **Bottom tab bar** (below `lg`) — fixed, icons only, four capability-filtered
  destinations plus **More**. The cap is what guarantees the fifth slot can
  always open the drawer, so no page is ever unreachable on a phone. Icons carry
  no visible text by design — five labels on a 360px screen truncate to "Ver…",
  "Dis…", "Pay…" — but each has a real accessible name, so a screen reader
  announces the word the label would have shown.
- **Drawer** — a bottom sheet behind More, with the full grouped nav. Focus is
  trapped and restored by the same `useFocusTrap` hook the command palette uses.
- **Header** — breadcrumb on the left, search / theme / account on the right.
- **Tables → cards below `md`.** Two sets of markup, not one set forced through
  `display: block` — that trick is what makes a table stop being a table to a
  screen reader. The behaviour behind an interactive row (cancelling an order,
  approving a payout) lives in a shared hook, so only the presentation is
  written twice and a decision made on a phone is the same decision.
- **Safe areas.** The tab bar pads for `env(safe-area-inset-bottom)` and the main
  column reserves the bar's height, or the last row of every list sits
  permanently underneath it.

Everything is declared once in `components/shell/nav-config.ts` — the sidebar,
the drawer, the tab bar and the breadcrumb all render from that list.
`test_admin_console_frontend.py` walks the App Router tree and fails the build if
a page exists with no navigation entry.

### Charts

Recharts where interactivity earns its bundle, hand-drawn SVG where it does not:

| | |
|---|---|
| `RevenueChart` | Recharts `ComposedChart` — revenue and GMV as areas, order volume as bars on a second axis. The three answer one question together: revenue falling while orders hold means the *mix* changed; revenue falling with orders means demand did. |
| `DonutChart` | Recharts. Only where the parts sum to a meaningful whole. |
| `GrowthChart` | Recharts. Paired bars, current against previous — "+300%" reads as a triumph when the numbers are 1 and 4, and on this platform they frequently are. |
| `Sparkline` | Hand-drawn SVG, **zero JavaScript**. Eight of these in KPI cards would otherwise mean shipping a charting library to draw eight polylines that never change after paint. |
| `GaugeRing` | Hand-drawn SVG. For bounded rates, where the ceiling is the point. |
| `FunnelChart` | Server-rendered. Steps must be genuinely **nested** sets or the drop-off figures are fiction — which rules out charting "orders by current status" this way, since those are siblings, not stages. |
| `CohortGrid` | Server-rendered `<table>` with row and column headers. |
| `DemandHeatmap` | Server-rendered `<table>`. ~170 cells that never change. |

Colours are CSS variables (`--chart-1` … `--chart-6`), so a chart inherits the
theme with no JavaScript and no re-render. Colour is never the only carrier of
meaning: every slice, bar and cell also states its label and value as text.

Structure:

```
drop-admin/
  app/
    (auth)/sign-in/
    (dashboard)/
      layout.tsx              shell: nav, command palette, admin context
      page.tsx                overview
      operations/{kyc,vendors,orders,disputes}/
      people/[kind]/[id]/
      finance/payouts/
      analytics/
      platform/{admins,audit,settings}/
    api/export/               the one BFF route handler (CSV streaming)
  lib/
    api/server.ts             typed FastAPI client, `server-only`
    permissions.ts            capability constants, mirrored from the backend
    nav-counts.ts             badge payload shape
    hooks/useFocusTrap.ts     shared by the palette and the drawer
  components/
    shell/                    nav-config, Sidebar, MobileNav, Header, NavList
    charts/                   see below
    ui/primitives.tsx
```

### Search
One command palette (`⌘K`) over a single backend endpoint that resolves an order
id, phone number, email, plate or store name to the right detail page. Backed by
the existing Postgres full-text `search_vector` plus trigram indexes, so it stays
a database query rather than a scan.

---

## 8. Scalability

- **Every list is server-paginated** with keyset pagination, never `OFFSET` —
  offset degrades exactly when the table gets big.
- **Analytics never aggregates in the request path** at scale. Phase 2 ships
  direct queries against indexed columns; when volume justifies it, a nightly
  rollup table behind the same endpoint, so no frontend change is needed.
- **`Decimal` end to end.** The existing `/admin/revenue` casts money to `float`;
  the replacement does not, per the platform rule.
- Read-heavy queries are hinted with covering indexes added in the same migration.
- Rate limits on admin endpoints via the existing `slowapi` setup.

---

## 9. Defects in today's admin endpoints, fixed as part of this

1. **`/admin/payouts` returns ciphertext.** It reads `account_details` via raw
   `text()` SQL. That column is a `StringEncryptedType`, decrypted by the ORM
   type — raw SQL bypasses it. Verified against the live database on the
   equivalent `Deliverers.ID_number` column: raw SQL returns
   `'S/xQ6YBb9arO/y2vUpduxQ=='`, the typed ORM returns the real value. The payout
   screen would show base64 where the phone number should be.
2. **Money as `float`** throughout `/admin/revenue`.
3. **No pagination** on `/admin/payouts` or `/admin/riders/pending-kyc`.
4. **KYC review writes no audit record** and discards `rejection_reason` after
   putting it in the notification — so there is no record of why anyone was
   rejected.
5. **`require_admin` is an env allowlist** — see §2.1.
6. **KYC documents presigned into a list response**, so every document in the
   queue gets a live 15-minute URL whether or not anyone opened it.

## 10. Schema gaps this needs

- **Vendors cannot be suspended.** `Vendor` has no `is_active`;
  `verification_status` is an unconstrained `String`. Adding suspension state.
- **No entity records why it was suspended, by whom, or when** — needed for
  appeals and for the audit trail to mean anything.
- `User.verification_status` is an enum, `Vendor.verification_status` is a free
  string. Converging them.

---

## 11. Delivery order

**Phase 1 — foundation and operations. ✅ Built 2026-08-01.** `Admin_Users`,
capabilities, the gate, audit log, migrations; the fixes in §9; Next.js shell
with Clerk and RBAC-aware navigation; KYC review queue; payout approval;
administrator roster; audit viewer. *Unblocks rider onboarding.*

Delivered:

| | |
|---|---|
| `models/admin_model.py` | 21 capabilities, 5 role presets, `AdminUser`, `AdminAuditLog` |
| `dependencies/admin_dependencies.py` | `require_admin(...)`, 2FA assertion, `AdminAccess` |
| `services/admin_service.py` | roster, invitations, audit, `seed_first_admin` |
| `routes/admin_routes.py` | 14 endpoints, every one gated |
| `f1a7c3e59d82` | admin tables + suspension columns — **applied** |
| `a2d8f4b61e93` | `kyc_rejection_reason`, `kyc_reviewed_at` — **applied** |
| `tests/test_admin_rbac.py` | 22 tests, structural + behavioural |
| `drop-admin/` | Next 16, 6 routes, typechecks and builds clean |

Two things were found while building and fixed in passing:

- **A rejected rider was never told why.** The reviewer's reason went into a
  push notification and nowhere else, while `VerificationWall` prefills their
  previous answers — so the form looked correct and the usual response was
  resubmitting the same document. Now stored, returned by `/kyc/status`, and
  rendered on the wall; cleared on resubmission so it cannot outlive the
  problem it described.
- **Migration ordering.** The admin migration was initially chained behind
  `e6b2c8d40f17`, the deliberately-unapplied contract migration, which would
  have made the console un-shippable without breaking production. Re-sequenced
  so the gated migration stays last.

**Phase 2 — finance and analytics. ✅ Built 2026-08-02.** `admin_analytics_service`
(timeseries with gap-filling, unit economics, operations health, leaderboards,
retention cohorts, growth), `/analytics/summary`, `/analytics/cohorts`,
`/analytics/export`, the analytics screen with charts, and a CSV export that
goes through a BFF route handler so the token stays server-side.

Every figure is `Decimal` serialised as a string, and aggregation happens in
Postgres. The chart parses to `Number` only for pixel positions — every value
rendered as text uses the original string, so the chart cannot disagree with the
ledger even by a rounding step.

**Phase 3 — people management. ✅ Built 2026-08-02.** `admin_people_service`,
`admin_people_routes`, list and detail screens for all three account types,
suspension with a mandatory reason, audited PII reveal, and the ⌘K command
palette over one capability-scoped search endpoint.

**Phase 4 — hardening. ✅ Built 2026-08-02.** Rate limits on the PII, search and
export endpoints; `tests/test_admin_e2e.py` (13 tests driving the real app
against the real database); `tests/test_admin_console_frontend.py` (13
structural and accessibility checks over `drop-admin/`).

**Orders and disputes. ✅ Built 2026-08-02.** `admin_orders_routes` with an order
board that opens on *stuck* rather than *all*, cancel and reassign, and the
bottle-dispute queue with evidence photos presigned on demand.

**Vendor verification. ✅ Built 2026-08-02.** `vendors.approve` was a capability
with nothing behind it. There is now a real verify/reject workflow, and
`require_vendor_verification` (default **off**) decides whether verification
gates discovery — read per call, so it can be turned off as fast as it was
turned on. It began as an environment variable and became a platform setting in
§14.1, so reverting it no longer needs a Render edit and a restart.

### Analytics, in full

Gated on `analytics.read` — demand, fulfilment, supply, products, customers,
quality, bottles, funnel, cohorts, growth, leaderboards, revenue timeseries,
unit economics.

Gated on `finance.read` — payment mix and float exposure. These are **omitted
from the payload** rather than 403ing the endpoint, and `finance_visible` says
so explicitly. Refusing the whole screen for one section is how somebody ends up
being handed `finance.read` just to look at demand charts.

### Three more defects found while building these

**The KYC queue would have 500'd in production.** `admin_routes` read
`Deliverer.full_name`; only `User` has that column, a rider has `name`. The
endpoint that unblocks rider onboarding was broken end to end and no unit test
saw it, because they all mocked the model. Caught by the first E2E run.

**`available_now` counted riders who could not work.** `is_available` defaults
to true at signup, so the supply metric reported 30 riders ready to go on a
platform where none had passed KYC. Now `deployable_now` — available, approved
and not suspended — with `marked_available` kept beside it, because a large gap
between the two means onboarding is the bottleneck rather than recruitment.

**The command palette's `aria-modal` was a lie.** No focus trap, so Tab walked
straight out into the page behind the overlay. Trap, focus restoration and full
combobox semantics added.

### Still outstanding

- **Decide whether unverified vendors may trade.** The workflow and the switch
  now exist. All 21 vendors are still `pending`, so verify them *before* setting
  `REQUIRE_VENDOR_VERIFICATION=true` or the customer app goes empty.
- A browser-driven E2E run (Playwright) against the console itself. The
  backend is covered end to end; the React screens are covered structurally.

### Two defects found while building these

**Customer-facing discovery never filtered on account state.** Nine queries
selected vendors and not one looked at whether the store still existed — account
deletion sets `verification_status = "deleted"` and anonymises the row, and that
row kept appearing in search, "near you", the directory, product search and its
own detail page. Suspension would have fallen into the same hole, which is why
`vendor_service.discoverable_vendor()` and the suspend action shipped in the
same change. `tests/test_vendor_discoverability.py` fails the build if a tenth
query is added without it.

Deliberately **not** gated on `verification_status == "verified"`: all 21
vendors are `pending`, so that predicate would empty the customer app. Whether
unverified stores may trade is a business decision, not a side effect of a bug
fix — see "Still outstanding".

**Masking masked nothing.** `mask(email, keep=0)` was meant to hide the whole
value. `value[-0:]` in Python is the *entire string*, so every list response
carried full email addresses behind a decorative `••••`. It read correctly and
reviewed correctly. Caught by a smoke test against real data, fixed with a
clamp, and `mask_email` now keeps the domain and hides the person.

---

## 13. The shell, the charts, and a broken workflow

### The dispute endpoints returned 500 for every decision

Found while adding E2E coverage for the navigation badges, and the most serious
thing in this document.

`RejectionStatus` defines three values: `pending_review`, `approved`, `denied`.
Both dispute endpoints spoke a different vocabulary:

```python
# list_disputes
status: Literal["pending_review", "resolved", "rejected", "all"]
# ResolveDisputeRequest
outcome: Literal["resolved", "rejected"]
```

`RejectionStatus("resolved")` raises `ValueError`, and FastAPI does not catch
that — so it is a **500, not a 422**. Two of the three tabs on the disputes
screen returned 500, and *every dispute decision on the platform* returned 500.
The resolve endpoint had never worked.

It reviewed cleanly because "resolved"/"rejected" is a perfectly reasonable
vocabulary — it simply is not the one the enum defines. The API now speaks the
ledger's words, and `test_admin_rbac.py` pins both literals to
`RejectionStatus`, checking the two sites **by name**: a heuristic looking for
literals that overlap the enum would have skipped the resolve endpoint precisely
because *none* of its values were valid, which is the worse of the two bugs.

### Money summed as a float

The payment-mix donut's centre total was
`methods.reduce((sum, m) => sum + Number(m.value), 0).toFixed(2)` — which puts
binary floating point back into a figure shown to a human, defeating the reason
money crosses the wire as a decimal string in the first place. Replaced with
`sumMoney()`, which scales to integer cents and sums with `BigInt`.

### Two dependencies that were never imported

`@tanstack/react-query` and `zod` were declared and used in zero files. The BFF
design made both unnecessary — every screen is a Server Component and every
mutation a Server Action — but the entry stayed in `package.json`. Removed.

### Still outstanding

- **Decide whether unverified vendors may trade.** The workflow, the queue and
  the switch now all exist. All 21 vendors are still `pending`, so verify them
  *before* turning `require_vendor_verification` on, or the customer app goes
  empty.
- A browser-driven E2E run (Playwright) against the console itself. The backend
  is covered end to end and the React screens are covered structurally — but no
  test has yet opened this in a real browser at 360px, and the responsive work
  above is exactly the kind that structural tests cannot confirm.
- Rider proof-of-delivery uploads still have no magic-byte validation (KYC and
  vendor uploads do).

---

## 12. Environment

New for `drop-admin/`:

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY   same instance as the apps
CLERK_SECRET_KEY                    server-side, for auth() and getToken()
BACKEND_BASE_URL                    server-only, NOT NEXT_PUBLIC_
```

`BACKEND_BASE_URL` is deliberately not `NEXT_PUBLIC_`: the browser never calls
FastAPI directly, and prefixing it would invite someone to.

Backend gains `ADMIN_2FA_REQUIRED` (default true) and
`PAYOUT_DUAL_CONTROL_THRESHOLD`. `ADMIN_CLERK_IDS` is removed once `Admin_Users`
is seeded — with the first super admin seeded from it, so you are never locked
out.

`RESEND_API_KEY` is what makes broadcast and support-reply **email** real; without
it `email_service` logs and returns, which is the correct degradation (the in-app
notification is the record either way) but means half of a `both` campaign
quietly does nothing.

---

## 14. Managing the business, not just watching it

Sections 1–13 built a console that could *see* the platform and act on one row at
a time. This section is the rest of the job: the geography, the conversations,
the money, and the numbers the business runs on.

### 14.1 Pricing is data now, not code

Every figure the platform earns from — seven commission rates, nine delivery
prices, six customer-facing fees, the bottle deposits, the operating radii — was
a Python constant in `order_service.py`. Changing the retail service fee meant a
pull request and a deploy, so in practice nobody changed anything and the pricing
was whatever a developer typed once.

They are rows in `Platform_Settings` now, read through
`services/platform_config_service.py`.

**Why it is safe to hand to an administrator:**

| Guard | What it prevents |
|---|---|
| A typed registry with bounds (`SettingSpec`) | `5` where `0.05` was meant — a 5000% commission, discovered when a vendor is paid a negative amount |
| Cross-field invariants, checked against the **merged** configuration | A platinum rider paying more commission than a standard one; commissions that together exceed the order |
| A live preview through the **real** `calculate_revenue_splits` | Approving a rate without seeing that the vendor now receives KSH 41 less |
| A mandatory reason, `Platform_Setting_History`, and an audit row | "Who changed the wholesale rate in March, and why" |

**How a change reaches the three apps.** It already does, and this is the part
worth understanding: the customer app renders `POST /api/cart/quote` verbatim,
and `pricing_service.compute_order_quote` is the single source of truth for what
an order costs. Change a fee here and the next quote in every app is different —
no client release, no App Store review. The vendor and rider apps follow through
the same route, since their earnings come from the order's stored splits.

**Why it cannot rewrite history.** `calculate_revenue_splits` runs at quote time
and writes its output to the order's columns; `settlement_service` pays from
those columns and never recomputes. Raising a commission today cannot change what
is owed on an order placed yesterday. If settlement ever starts recomputing from
live config, every in-flight order silently reprices mid-delivery — that property
is what makes the whole feature defensible.

**Reads are synchronous, refreshes are not.** The pricing functions are pure and
synchronous and are called from routes, the seeder and the tests; threading an
`await` through all of them to fetch a rate would be a large change for no gain.
So `ensure_fresh(session)` is awaited once per request in `get_db`, and `get(...)`
is a dictionary read afterwards. Between those two points the configuration
cannot change, which is also what makes a single quote internally consistent.
Propagation between the API and the ARQ worker rides on a Redis `INCR` counter
bumped **after** the commit; with Redis down it degrades to a 30-second TTL.

The legacy constant names still resolve — `order_service.RETAIL_SERVICE_FEE_KSH`
returns the live value through a module-level `__getattr__` — because four
modules and several tests import them. `test_platform_config.py` fails the build
if any module re-declares one as a literal.

### 14.2 The map, and what it is for

**Google Maps JavaScript API**, the same provider as the three mobile apps —
there is no OpenStreetMap basemap anywhere on this platform. The key is public
(`NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY`), because the browser is what draws
the map, and is made safe by an HTTP-referrer restriction plus **Maps JavaScript
API only** — the web-browser equivalent of the apps' package-restricted SDK keys.
The rule the platform actually enforces is about **web services**: Directions,
Places and Geocoding stay behind `routes/maps_routes.py` with the IP-restricted
server key, and no browser ever calls them. See `docs/maps-architecture.md`.

Layers refetch on the map's `idle` event rather than `bounds_changed`, which
fires on every animation frame of a drag; marker colours are resolved hex rather
than CSS variables, because the Maps API paints them onto a canvas that never
sees the stylesheet. With no key configured the screen renders a written
explanation, not a blank rectangle.

Four layers, all viewport-scoped so panning fetches only what is on screen:
riders (coloured by availability), stores, demand (H3 `res8` cells, the same
index the orders table already carries), and orders in flight.

The fifth is the one that earns the screen: **coverage** — stores with no
available rider within the wholesale radius, by `ST_DWithin`. "How many riders do
we have" is the wrong question; forty riders all parked in one suburb is not
coverage. On today's data it reports all 21 stores uncovered, because every rider
is `kyc_status='unsubmitted'`.

`geo.view` is its own capability. Live positions for identified people are not a
free extra on `riders.read`.

### 14.3 Support: the first place two people talk

`Support_Tickets` carries the thread as JSONB. Three properties matter:

- **A ticket is filed against an account the token owns.** The requester comes
  from the Clerk subject, never from the body; a referenced order is checked
  against the caller, and an unowned one is a 404 rather than a 403, because
  confirming the id exists is itself the leak.
- **Internal notes are stripped at the boundary.** Support staff write "checking
  the rider's GPS, customer sounds confused" in the same thread as the reply.
  Filtering in the client would be one careless render away from showing it.
- **`open` means somebody has to answer.** An admin reply moves the ticket to
  `pending` — waiting on *them* — and a follow-up reopens it. The nav badge counts
  `open` alone, so it is a number somebody can act on rather than a queue depth
  people learn to ignore.

Requester email addresses are captured on the ticket at creation, not joined at
read time: an account can be renamed, anonymised on erasure or suspended, and a
ticket nobody can reply to six weeks later is not a ticket.

**The three apps write into it.** Each has a `Support` screen and a thread view
(`hooks/queries/useSupport.ts` → `/api/support/tickets?user_type=…`), reached
from Settings — plus two placements that matter more than the menu entry:

- The **rider** app lets Support through the KYC gate and links to it from the
  verification wall. A rider on day four of a "less than 24 hours" review had no
  way to ask anybody.
- The **customer** app opens it from an order with the order attached, so the
  ticket says which delivery without them typing it. The server checks that
  order belongs to the caller.
- The **vendor** app resolves the ticket through the store resolver rather than
  by `clerk_id`. A `Vendor` row is a store: an owner with two branches would
  otherwise always file against the first, and **staff**, who hold no `clerk_id`
  on any `Vendor` row, would be told they have no vendor account — which is most
  of the people actually using that app.

### 14.4 Broadcast: the one action that cannot be recalled

Every other control in this console affects one account. This one reaches
everybody, so:

- **Preferences are honoured by default.** A campaign is `transactional=False`,
  which routes the push through `notification_service.push_allowed` exactly as
  any other promotion would. Marking one transactional overrides that, and the
  console words it as a claim the sender is making — "this is not marketing" —
  with the choice recorded in the audit row.
- **The in-app row is always written.** Same rule as the rest of the platform:
  the `Notification` row is the history, the push and the email are best-effort
  on top of it.
- **It runs in ARQ, in batches, and records progress.** Sending inline would time
  out around the thirtieth recipient with nobody able to say how far it got. The
  campaign row is written *before* the first message, so a run that dies leaves
  evidence, and `sent_count`/`failed_count` update per batch.
- **Batching is keyset, not OFFSET.** The loop commits between batches, and an
  OFFSET with no total ordering may return rows in a different order next time —
  on a campaign that means one person is messaged twice and another never hears
  from us at all.
- **There is no "everyone" audience.** Nine concrete segments, each excluding
  suspended accounts, because "everyone" invites sending a rider shift notice to
  customers.

The console requires the audience key to be typed to confirm. A dialog with an OK
button is something people click without reading.

### 14.5 Adjusting a balance by hand

The only endpoint on the platform that creates money from nothing, and it carries
every guard that fits: its own capability held by no preset but super admin, a
ten-character minimum reason, a ceiling per adjustment that refuses rather than
warns, an optimistic check against the balance the operator was looking at, a
refusal to push an account into arrears, and a notification to the account holder
— because a silent balance change is indistinguishable from a bug to the person
it happens to, and generates the support ticket it was meant to close.

It moves through `wallet_service.apply_wallet_delta`, which writes the balance and
the ledger row as one operation, never one without the other.

### 14.6 Three defects found while building this

**Every pricing preview was a 500.** `/config/preview` built its delta by
subtracting each string field of the sample quote from the same field of the
proposed one — and `vehicle_class` is a string. `Decimal("motorbike")` raises
`InvalidOperation`, so the one screen whose entire purpose is to make a pricing
change safe to approve failed on every call. Now only fields that parse as
decimals produce a delta, and a test pins it.

**The account ledger filtered by the wrong id.** `WalletTransaction.user_id`
holds the **Clerk id** — `record_wallet_movement` writes `user_id=clerk_id` — and
the new per-account ledger filtered by the row UUID from the path. It would have
matched nothing and shown every account an empty ledger, which reads as "no
activity" rather than as a bug. The list endpoint's query parameter is named
`clerk_id` for the same reason.

**A float crept back into money.** The pricing preview rendered its deltas with
`Number(delta).toFixed(2)` — binary floating point in a figure shown to a human,
on the screen where the figure is the whole point. `formatMoneyDelta` keeps it a
string.

### 14.7 The invite flow could not complete

Found while wiring support into the apps, and it made the console a one-person
tool.

`admin_service.invite_admin` creates a row with `clerk_id = NULL` and documents
that "the grant is live the moment the invited person signs in — `bind_admin`
matches the pending row by email". `bind_admin` was written, tested by nobody,
and **called by nothing**. `_resolve_admin` looks an administrator up by
`clerk_id`, so the invited person matched no row, was refused with
"Administrator access required", and the row stayed unbound for ever.

`_resolve_admin` now calls `admin_service.bind_admin_for_caller` on the no-match
path, which mirrors `vendor_staff_service.bind_invitations_for_caller`: a cheap
pre-check for any pending invitation at all, then one Clerk round trip to read
the caller's own email, then `bind_admin`. The round trip therefore happens only
on a first sign-in that has an invitation waiting, and a Clerk failure leaves the
invitation pending rather than 500ing the request.

`ADMIN_CLERK_IDS` is a related trap: `seed_first_admin` reads it, and nothing
calls `seed_first_admin` either. The variable grants nobody anything.
`scripts/admin_access.py` is the way in on a fresh deployment — and the way to
walk the console through every role without maintaining five Clerk accounts.

Its `grant-roles --domain` subcommand creates one `Admin_Users` row per preset at
predictable addresses, to pair with five users created **by hand in the Clerk
dashboard**. A script that creates Clerk accounts was written and deleted: it
meant a process holding the password for five privileged identities, and an
`--allow-production` flag standing between that and a live instance. Creating
them in the dashboard leaves the credential where it belongs and the audit trail
with Clerk. See `docs/admin-console-runbook.md` §6.

### 14.8 A merge revision that merged nothing

`c8d1f5b30e72` was written to collapse three migration heads —
`b4c7e2a91f30`, `f9a3b7c2d1e0` and `412f43743aad` — and a script existed to stamp
the latter two as "applied but unrecorded".

Both were wrong. `3f40437790a9` had already merged those two branches years
earlier, and `b4c7e2a91f30` descends from it, so they were **ancestors of the
applied head**, not stranded siblings. Stamping them produced three rows in
`alembic_version` and alembic refused the next upgrade outright: *"Requested
revision b4c7e2a91f30 overlaps with other requested revisions"*. The stamp was
reverted, the merge revision and its repair script deleted, and
`e6b2c8d40f17` repointed at `b4c7e2a91f30` — where it always belonged.

The graph is now linear: one head, `alembic current` at `b4c7e2a91f30`, with the
guarded staff-column drop as the only outstanding revision. Routine deploys
should run `alembic upgrade b4c7e2a91f30` until step 3 of that migration's
sequence is done.

### 14.9 The demand layer had nothing to draw

`Orders.h3_index_res8` is written by `create_order` and read by the map's demand
layer and the analytics geographic breakdown. Every order predating that line
had `NULL`, and both readers filter `IS NOT NULL` — so missing data rendered as
"no orders here" on the two screens whose entire job is showing where the orders
are. `scripts/backfill_order_h3.py` derives the cell from the coordinates
already on each row.

It still draws nothing, and that part is correct: a cell needs **two** orders
before it appears, because one order in a cell is a customer's front door.

---

## 15. Closing the audit: seven screens over data nobody could see

[platform-audit.md](./platform-audit.md) found seven domains the platform wrote
to and never read back, and eight console pages that were a table with a search
box. This section covers the work that closed both.

The common shape: the data already existed. `bottle_ledger_entries` recorded
every empty; `Order_Tracking_Logs` recorded every rider ping; `payouts` recorded
every disbursement including the failed ones. What was missing was any query that
would tell a human whether something had gone wrong.

### 15.1 The bottle float — `/operations/bottles`

A 20L bottle carries a refundable deposit the platform has already collected from
the customer. Bottles a rider never returns are money the platform owes and
cannot recover, and nobody could see the total.

Three decisions worth recording.

**Value comes from `bottle_deposit_by_capacity`, not a constant.** A float priced
at a number this module invented is a number nobody can reconcile against a
receipt. It reads the same setting the customer was charged.

**Every total nets per (rider, vendor, capacity) before summing.** A rider can
hold store A's bottles while store B carries a credit against them from an
over-recorded return. Summing the raw signed column platform-wide lets B's
negative cancel A's positive and reports *less* float than exists. The `HAVING`
clause keeps only the positive side of each pair.

**`drift()` checks an invariant that was declared and never verified.**
`bottle_ledger_service` states it in its own module docstring:

```
SUM(bottle_ledger_entries.quantity) == VendorRiderRegistry.pending_{n}L_empties
```

An invariant nobody checks is a comment. The check is on a screen rather than in
a test because the ways it breaks — a hand-edited row, a half-applied migration,
a crash between the ledger write and the counter — all happen in production and
never in CI. Repair rewrites the counter *from* the ledger and never the reverse,
because the ledger is append-only and attributed while the counter is a
denormalisation with neither property.

The repair is a button, not something the read path does quietly. Drift means
something wrote a counter without a ledger row, and that is a bug worth finding
rather than a nuisance worth papering over.

Hand corrections go through the ledger too — signed, attributed, with a mandatory
note that travels into both apps' history. Gated on `finance.adjust`, the same
capability as crediting a wallet, because a written-off deposit is money moved by
assertion rather than by an event.

### 15.2 Review moderation — `/operations/reviews`

`reviews` had no moderation state and no admin reader at all. A review naming a
rider's home address could only be removed with a `DELETE`, which loses that the
review existed, releases `uq_customer_order_target_review` so the customer can
leave another, and strands the target's counters on a row that is gone.

Migration `a9f4b2c71d63` adds `hidden_at` / `hidden_by` / `hidden_reason`, and
**five read paths across four modules** now filter on it. That number only goes
up, so the guard is structural: a test walks every `select` over `reviews` with
`ast` and fails the build on one that does not filter — verified by removing a
filter and watching it catch.

**Hiding is not enough on its own.** Taking a one-star review out of the list and
leaving it in the average is theatre: the store still sits at 2.1 for a review
nobody can read. `set_hidden` rebuilds the target's counters from the visible
rows in the same transaction. That rebuild is the one sanctioned `SUM()` over
`reviews` — a single indexed aggregate for one target on a rare admin action, not
the per-write recomputation the incremental path exists to avoid.

A resubmit of a hidden review is a **409**, not an edit. Folding its rating back
in would be a working way round moderation.

**Nothing here is user-reported** — no app has a report button — so the default
view is a heuristic and the page says so in those words: comments that look like
they carry a phone number or an email, and low ratings that came with something
written. A heuristic presented as a queue of confirmed problems is how a
moderator learns to clear a screen without reading it.

### 15.3 Settlement — `/finance/settlement`

Three things that move money without a person pressing anything.

**Refunds.** `refund_service` sweeps cancelled paid orders into an M-Pesa
reversal and leaves them `refunded` or `refund_failed`, and nothing surfaced
either. A failed refund is somebody who paid for water they never got and never
got their money back; the only trace was a column on a row nobody queried. Those
customers do not write in — they leave. `refund_processing` is the quieter one:
the reversal was accepted and the callback never arrived, which is
indistinguishable from success except by age.

**Payouts.** Two invariants `payout_service` declares in prose and nothing
checked. A payout is debited from the wallet *before* the B2C call so the money
cannot be spent twice in flight, which makes returning it on failure mandatory —
a failed payout with no matching refund transaction is money the platform took
and did not give back. The check is a correlated `EXISTS` on
`reference_id = payout.id`. The second is a `completed` disbursement carrying no
M-Pesa receipt: recorded as paid with nothing to evidence it.

**Cash float.** `committed_cash_float` gates every withdrawal and is computed one
provider at a time, so the platform's total cash-at-risk had never been visible.
Same arithmetic, aggregated, with negative rider balances called what they are:
cash collected and not remitted.

**There is no retry, and two tests enforce it** — one on the routes, one on the
page's own labels. A reversal that succeeded but lost its callback looks exactly
like one that failed, and sending a second pays the customer twice out of the
platform's own float with no way to claw it back. The administrator settles it in
the M-Pesa portal and records that here, which is the same reasoning as the
webhook reconciliation screen.

The payout destination is encrypted at rest and never enters the payload. The
screen carries *whether* a receipt exists, not where the money went.

### 15.4 Delivery replay — `/operations/replay`

`Order_Tracking_Logs` was written on every location ping and read by nothing, so
"the rider says they delivered it, the customer says they didn't" was
unanswerable while the platform held the evidence.

`closest_approach_m` is the answer: the minimum distance between any recorded
ping and the order's delivery coordinates. A rider whose nearest approach was
four kilometres did not deliver that order.

**`reached_destination` is three-valued, and the `None` is the point of the whole
module.** Tracking depends on the rider app having permission, signal and
battery, so no path at all is routine and says nothing about where anyone went.
Collapsing that into `false` would turn an absence of evidence into evidence of
absence on the one screen used to decide whether somebody is stealing. The
console prints *why* there is no verdict and declines to draw one.
`largest_gap_minutes` exists for the same reason: a path with a thirty-minute
hole is two paths.

Gated on **`geo.view`, not `orders.read`**. A breadcrumb trail is a person's
precise movements, and the coordinates being historical rather than live makes
them no less identifying. The photo proof is reported as present or absent, never
as a URL — presigning an image of somebody's doorstep on every page load is the
same mistake as prefetching KYC documents.

The map draws the proximity radius the backend actually used, read from the
payload rather than duplicated, so the circle and the verdict cannot disagree.

### 15.5 Performance — `/people/performance`

Deactivating somebody's income is the most consequential thing this console does
to an individual, and it was being done from a roster showing a name and a phone
number.

**Every rate ships its denominator and nothing is ranked below five finished
orders.** A rider with one delivery and one cancellation has a 100% cancellation
rate and means nothing; a league table that puts them at the top is worse than no
league table, because somebody acts on it. Below the threshold the console writes
"under 5 orders" rather than a number it would have to caveat.

For stores, "never sold anything" is surfaced deliberately: on a young platform
that is the most actionable vendor figure there is — supply acquired and not
activated.

### 15.6 Fleet — `/people/fleet`

`VendorRiderRegistry` decides dispatch priority and had no admin reader, so a
store saying "no riders are being assigned to me" could not be checked. On this
deployment the answer is one number: **every store has no approved rider**, so
every order falls straight through to the gig radar.

Building it turned up a latent crash. `Deliverer_Vendors` is a second table for
the same relationship that nothing reads or writes, and its model declared
`back_populates="vendors"` / `"deliverers"` against properties that exist on
neither mapper. Importing that module *from the application* raised
`InvalidRequestError` on the first ORM query in the process and took every
unrelated query with it. It survived because the only importer is
`alembic/env.py`, which wants the metadata for autogenerate and never compiles an
ORM query. The relationships are gone, the table declaration stays so Alembic
still describes it, and a test fails the build if a relationship returns.

### 15.7 Notification delivery — `/platform/notifications`

The figure that matters is not how many were sent but **how many recipients could
ever have been interrupted**. A `Notification` row is always written; the push
needs a device token and the recipient's own preference.

On this deployment not one account has a `push_token`, while every notification
is recorded as `delivered_via: "push"` — each one written as an interruption that
could not arrive. On a platform where a rider learns about an order from a push,
that is the difference between "they ignored it" and "they were never told".

The feed **names no recipient**. It is readable with `analytics.read`, and who
was told what belongs on their support ticket; the body is truncated because it
can carry a delivery address or a phone number.

### 15.8 Catalogue — and a false positive worth recording

`Product` was read in exactly one place before this, the top-sellers query, so
the platform could report what sold and not what was on the shelf. Price outliers
are found within a band, against the **median** rather than the mean: one item
priced at 40,000 by a misplaced decimal drags a mean far enough to hide itself,
which is precisely the case the check exists to catch.

The first implementation banded by capacity alone, and it was wrong. `accessories`
(675–1,406) and `dispensers_coolers` (14,655–23,462) both carry `capacity = 0`,
so they pooled into one group with a median of 1,250 and **every dispenser on the
platform** was reported as an 18× outlier — 21 false positives out of 114
products, which is a screen nobody opens twice. The band is the pair
`(category, capacity)`. With that fix the detector reports zero outliers on real
data, and it was proved to still work by temporarily mispricing a real product
12× and watching it flag at 24×.

### 15.9 What these have in common

Every one of them is a query over data that was already being written. None
needed a new integration, and only one needed a migration. The work was almost
entirely deciding **what question a screen exists to answer**, and then refusing
to answer a different, easier one:

* a rate is not quoted below its minimum sample,
* a verdict has three values when the data has three states,
* an aggregate is `None` rather than `0%` when the denominator is zero,
* a heuristic is labelled as a heuristic,
* and where a table is empty on this deployment, the module docstring says so
  rather than implying the arithmetic has been observed against real volume.

---

## 16. The join between the console and the apps

A later pass walked the console page by page against the endpoints behind it.
The screens themselves held up — every one carries a summary band, real filters
and written empty states, and none is a bare table. What did not hold up was the
**join**: capability the backend already had and the console never asked for,
and one path where the console recorded something and never delivered it.

### 16.1 A support reply never pushed

The worst of them, and invisible from either end.

`support_service.reply` wrote a `Notification` row; the route sent an email.
Nothing pushed. An exhaustive walk of every `queue_push` and
`dispatch_background` call site on the platform found orders, refunds, riders,
stores and broadcast — and no support anywhere. The compose box in this console
said "Sent to their app, and emailed if we have an address", and the first half
of that sentence was false.

So the single message on this platform a person is *actively waiting for* was
the only one that never interrupted them. They found it by opening the
notifications screen and pulling to refresh.

### 16.2 …and the link in it pointed here

`action_url` was `/support/{ticket_id}` — a route in **this** application. Every
other `action_url` in the backend is an Expo Router path. Three apps, three
different silent failures: the customer app's deep-link whitelist blocked it and
logged in dev only; the rider and vendor apps pushed an unmatched route.

Both are now covered by structural tests, the second across the whole backend
rather than the one line that was wrong.

### 16.3 `pending` meant "waiting on them" even after they replied

An administrator's reply moves a ticket to `pending`. A requester's follow-up
reopened it only from `resolved` or `closed` — so answering an answer left the
ticket labelled as somebody else's turn. The nav badge counts only `open`, so
the console was never told at all. Someone who replied within a minute became
invisible in a queue sorted oldest-first.

Two changes: a follow-up now reopens from any state, and `list_tickets` returns
`awaiting_us` — who spoke last, ignoring internal notes, so a colleague writing
"checking the GPS trail" does not count as having answered the customer.

### 16.4 Priority could be filtered but never set

`Support_Tickets.priority` had a default of `normal`, four documented values, a
filter on the queue endpoint, a `/support/meta` endpoint serving the list, and a
coloured badge on two screens. Nothing on the platform could write it. Every
ticket ever raised was `normal` for life, and the filter could only return
everything or nothing.

It is an administrator's judgement rather than a field on the intake form —
a form that lets you tick "urgent" is a form where everything is urgent — and
setting it is audited, because moving one ticket up an oldest-first queue moves
every other one down.

### 16.5 Three screens asked for less than they could have

| Screen | Already supported by the endpoint | Sent |
|---|---|---|
| `/platform/audit` | `action`, `target_id`, keyset `cursor` | nothing |
| `/platform/notifications` | `days`, `audience` | nothing |
| `/support` | `category`, `requester_type` | nothing |

The audit one mattered most. It is the compliance screen — "every time someone
opened a person's identity documents" — and it was capped at the newest fifty
rows of *everything*, with `next_cursor` fetched and dropped on the floor. There
was no way to ask the question the page exists to answer.

### 16.6 A link that discarded the id it was holding

The ticket sidebar's "Related order" linked to `/operations/orders` — the bare
board — while holding the order id and rendering the first eight characters of
it. An agent answering "where is my order" landed on an unfiltered queue with
the answer on the screen behind them. It now carries `?view=all&q=<id>`;
`view=all` because the default board is "needs attention" and a delivered order
is not on it.

### 16.7 Access control over the new surface

Everything above was checked against the capability model rather than assumed
into it.

**The one new endpoint.** `POST /support/tickets/{id}/priority` holds
`support.respond`, alongside reply, status and assign — never `support.read`.
Escalation reorders an oldest-first queue, which is a change to somebody else's
workload, so it is a write and it is audited (`support.priority`) with the
administrator's email on it.

**Read and write stay separate.** A test now walks the support router's AST and
fails on any `POST`/`PATCH`/`DELETE` handler gated on a read capability — the
platform's existing `test_every_admin_route_declares_a_permission` proves a gate
*exists*, and this proves it is the right *kind*.

**The console mirrors, it does not decide.** `PriorityControl` renders nothing
without `support.respond`, and a Server Action is a public endpoint regardless —
so the refusal is proven at the backend, not at the button. A `support.read`
caller invoking the action directly gets a typed `permission_required` 403.

**A link that would refuse you is not offered.** The ticket sidebar's
related-order link is gated on `orders.read`, matching the requester-name link
beside it. Both stock presets that reach this screen happen to carry it, but
*roles are presets, not authority* — permissions are edited per administrator,
and the id still renders, just not as a link into a refusal.

**No new filter widened anybody's reach.** The audit, notification and support
filters all narrow queries behind gates that were already there
(`admins.manage`, `analytics.read`, `support.read`). The administrators summary
band counts rows the caller had already been served — someone with
`admins.manage` can edit those very capabilities, so counting who holds
`pii.view` reveals nothing to them.

**Pushing to store staff is not an expansion.** `support_routes._resolve_account`
resolves a vendor through `_resolve_access(..., owner_only=False)`, so every live
staff member could already read the store's whole support thread in the app. The
push reaches people who already had the read; it does not create one. That is
also why it carries no staff-capability filter — support is not one of the four,
and gating on one would silence whoever holds none.

### 16.8 What these have in common

Different from §15.9. Those were screens that did not exist. These all existed,
looked complete, and were complete on both sides of a boundary that nothing
carried across — a capability the server offered and no caller used, a column
every layer read and no layer wrote, a URL that was valid in the wrong
application. None would appear in a typecheck, a build, or a walk of the UI,
because at every single point the code is doing something reasonable.
