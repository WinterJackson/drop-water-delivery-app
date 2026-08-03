# Drop Admin 🖥️

> The operations console the Drop owners and staff run the business from.
> Next.js App Router, talking to the **same FastAPI backend** as the three mobile
> apps. No second database, no parallel API.

---

## 🔑 The two rules that shape everything

### 1. The browser never holds an API token

Every backend call goes through `lib/api/server.ts`, which is marked
`server-only` — importing it from a Client Component is a **build error**, and
that is deliberate. The token is minted per request by Clerk on the server; the
browser only ever holds Clerk's httpOnly session cookie.

This console renders national ID photographs and M-Pesa numbers. An XSS on any
page of it must not also hand over an admin API token.

Client components therefore never fetch. They call a **Server Action**
(`actions.ts` beside the page), which calls `lib/api/server.ts`.

### 2. Hiding a control is courtesy — the server decides

`lib/permissions.ts` mirrors `BackendAPI/models/admin_model.py` so the navigation
does not offer somebody an action that would refuse them. Every one of those
capabilities is enforced again by `require_admin(...)` on the backend, and that
check is the only one that matters. A build of this app with the client-side
checks deleted would gain nothing.

---

## 🧭 Authorisation

Administrators are rows in `Admin_Users`, not entries in an environment
variable. `ADMIN_CLERK_IDS` is retired: it could not express roles, could not be
revoked without a redeploy, and left no attribution.

* **26 capabilities**, all shaped `domain.action`. Read and write are always separate.
* **5 role presets** — `super_admin`, `operations`, `finance`, `support`, `analyst`. A role is a preset, not authority: assigning one expands into a permission set, and the role name is never consulted when deciding an action. That is what makes a preset safe to edit later.
* `finance.adjust` (crediting a wallet, or writing off a bottle debt) and `geo.view` (positions for identified people) are their own capabilities. Neither is implied by `finance.read` or `riders.read`, and no preset but super admin holds `finance.adjust`.
* `pii.view` is its own capability. Support and analyst do not have it.

Four layers stand between a request and the data, and only one of them decides:

1. **Middleware** — a Clerk session is required for everything but `/sign-in`. There is no public sign-up; administrators are invited and bound on first sign-in, and a test fails the build if that route becomes public.
2. **`Admin_Users`, re-read per request** — the session says who, the backend says whether. Revocation takes effect on the next click.
3. **Two-factor**, asserted from the session claim, so it needs a fresh sign-in to take hold. The refusal is typed (`two_factor_required`), never a bare 403.
4. **Idle timeout** — signs out after 15 minutes with a 60-second warning. This console is used at shared desks; an unattended tab needs no attacker. It is not what stops a stolen token — layer 2 is.

---

## 🗂️ What is in it

27 destinations. None is a bare table with a search box: every page carries the
aggregates that tell an operator whether anything needs doing, and a test fails
the build if a queue page renders none.

### Operations
| Screen | What it is for |
|---|---|
| **Orders** | The live board, opening on the ones that are stuck. Carries unassigned count, oldest stale age, and the value sitting in flight |
| **Rider verification** | The KYC queue. Documents are revealed by an audited action with a stated reason, never rendered by default |
| **Live map** | Riders, stores, demand and live orders, on Google Maps. Layers refetch on `idle`, not on every frame of a drag |
| **Catalogue** | Every product on the platform, with prices checked against the median for the same **category and capacity** — a misplaced decimal shows up here rather than on a customer's bill |
| **Bottle float** | Empties riders are holding, priced at the same refundable deposit the customer paid, plus a check that the registry counters still agree with the append-only ledger they denormalise |
| **Vendor verification** | Paperwork before a store trades |
| **Bottle disputes** | Deliveries where the count did not agree |
| **Reviews** | Moderation. Hiding is never a delete, and the target's rating is rebuilt from the visible rows in the same transaction |
| **Delivery replay** | The rider's recorded path for one order, and the closest they came to the door |

### People
| Screen | What it is for |
|---|---|
| **Performance** | Completion and fulfilment rates, each with its denominator, and nothing ranked below five finished orders |
| **Fleet** | Which riders are registered with which stores — the thing that decides dispatch priority — and which stores have none |
| **Customers / Riders / Vendors** | The rosters, with masked personal data by default for every role |

### Finance
| Screen | What it is for |
|---|---|
| **Payouts** | What is waiting for approval, and how much |
| **Transactions** | Every movement of money and what the platform kept |
| **Reconciliation** | Payment callbacks that failed — the customer paid Safaricom and the order stayed `pending` |
| **Settlement** | Refunds owed, payouts in flight, and the cash customers are holding in notes right now |

### Support and Platform
Ticket inbox and threads · Administrators · Audit log · Notification delivery ·
Broadcast · Pricing · Deployment settings.

---

## ⚖️ Decisions worth knowing before you change something

**A rate is never quoted below its minimum sample.** A rider with one delivery
and one cancellation has a 100% cancellation rate and means nothing. Below the
threshold the console writes "under 5 orders", not a number it would have to
caveat.

**A verdict can be three-valued.** Delivery replay returns `true`, `false`, or
**`null`** — the last when the order has no coordinates or nothing was ever
recorded. Tracking depends on the rider app having permission, signal and
battery, so no path at all is routine. Collapsing that into `false` would turn an
absence of evidence into evidence of absence on the one screen used to decide
whether somebody is stealing.

**There is no retry on a refund, and a test enforces it.** A reversal that
succeeded but lost its callback is indistinguishable from one that failed, and
sending a second pays the customer twice out of the platform's own float. The
administrator settles it in the M-Pesa portal and records that here.

**`undefined` and `0` are different answers.** `GET /nav/counts` returns a figure
only for the queues the caller may actually open. `undefined` means "not yours" —
render nothing. `0` means "nothing waiting" — also render nothing, but it is a
real answer. Never coalesce with `?? 0`: a badge reading "3" on a page that would
refuse the caller leaks the size of a table they cannot see. A test fails the
build on that pattern.

**Business values are rows, not environment variables.** Two screens under
Platform look alike and are not. `/platform/settings` shows the *deployment's*
switches — process environment, read-only, labelled as such.
`/platform/pricing` shows the *business's* numbers — rows in `Platform_Settings`,
editable, live in all three apps on the next quote. The pricing editor requires
a reason and previews the change through the *same* `calculate_revenue_splits` a
real quote uses; never re-implement that arithmetic here to save a round trip, as
a preview free to disagree with the quote is worse than no preview.

**Broadcast is the one action that cannot be undone.** The composer requires the
audience key to be typed to confirm, and **changing the audience clears the
confirmation** — otherwise a typed confirmation silently authorises a different,
larger send.

---

## 🎨 UI conventions

* **Semantic tokens only** — `bg-surface`, `text-muted`, `border-default`. Never `bg-white dark:bg-neutral-900` at a call site; that is how two themes drift. Dark mode is one block in `globals.css`, and the explicit toggle writes `data-theme` on `<html>`, which the stylesheet gives precedence over `prefers-color-scheme` in **both** directions.
* **Every destination is declared once**, in `components/shell/nav-config.ts`. The sidebar, the mobile drawer, the bottom tab bar and the breadcrumb all render from that list, and a test walks the App Router tree and fails the build if a `page.tsx` exists with no entry.
* **Below `lg`** the bar holds four capability-filtered destinations plus **More**; the cap is what guarantees the drawer stays reachable, so no page is ever stranded. Tab items are icons only by request — which does not mean unlabelled: each carries an `aria-label` plus an `sr-only` short label.
* **Wide content scrolls inside its own box** (`.scroll-x`). The page body must never scroll sideways on a phone — operations staff triage the KYC queue on one.
* **Data tables become cards below `md`** — two sets of markup, never one forced through `display: block`, which stops a table being a table to a screen reader. The behaviour lives in a shared hook so approving a payout on a phone is the same action, with the same mandatory reason, as approving one at a desk.
* **Colour is never the only carrier of meaning.** Every slice, bar, cell and map marker also states its label and value as text, and markers carry shape as well as colour.
* **Empty states are written, not blank.** A blank rectangle reads as broken software.
* **Never show a raw status code.** `lib/api/server.ts` normalises refusals; branch on `ApiError.type`, never on the wording of a message.
* Anything with `aria-modal="true"` must use `useFocusTrap`. The attribute is a *promise* that focus cannot leave; without a trap it is simply untrue, and a test enforces it.

---

## 💷 Money

It arrives as a decimal **string** and stays one. `formatMoney` formats the
integer and fractional parts separately without ever calling `Number`.

To add money use `sumMoney()` — never
`values.reduce((a, b) => a + Number(b), 0).toFixed(2)`, which reintroduces the
exact float error the backend goes out of its way to avoid, in a total shown to
a human. The same applies to a difference: `formatMoneyDelta()` renders
`+41.00` / `-12.50` from the string, and `isZeroMoney()` tests it. Parsing to a
number is fine for **pixel positions** in a chart, and nowhere else.

---

## 🗺️ The map

**Google Maps**, like the three mobile apps. There is no OSM basemap anywhere on
this platform. `lib/maps/google-maps.ts` injects the JavaScript API once per page
and exports `useGoogleMaps()` plus the two theme styles.

* `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` is public **by necessity** — the browser draws the map. That does not contradict "no Google web service from a client": the JavaScript API is an **SDK**, the same arrangement as the apps' package-restricted keys. Directions, Places and Geocoding stay behind `routes/maps_routes.py` on the IP-restricted server key. Restrict this one to **Websites** + **Maps JavaScript API only**; an unrestricted browser key is billed to the project by whoever finds it.
* **Readiness is the `callback` parameter, never the script's `load` event.** `loading=async` returns a *bootstrap*; `load` fires when that arrives, while `google.maps.Map` is still `undefined`. Constructing one then throws "not a constructor" — on a cold cache only, so it survives a whole dev session.
* Marker colours are **resolved hex**, not CSS variables: the Maps API paints onto a canvas and never sees the stylesheet.
* No key configured renders a written panel explaining that, never a blank rectangle that reads as a broken map.

---

## 🏃 Running it

```bash
cd drop-admin
pnpm install
cp .env.example .env.local
pnpm dev          # http://localhost:3000 — already in the backend's ALLOWED_ORIGINS
pnpm typecheck
pnpm build
```

The backend must be running on `BACKEND_BASE_URL`, or every page renders
"Could not reach the server" — the fetch is server-side, so it produces no
entry in the browser's network tab.

### `.env.local`

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` | The **same** Clerk application as the three apps |
| `BACKEND_BASE_URL` | Deliberately **not** `NEXT_PUBLIC_`. Prefixing it would invite someone to call FastAPI from the browser |
| `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | The only deliberately public one. Everything but `/operations/map` runs without it |

> `pnpm-workspace.yaml` carries `fetchTimeout: 900000`. The npm registry is slow
> from here and the Next tarballs are 35–45 MB, which blows past pnpm's 60-second
> default and fails the install outright.

### Tests

The console's structural tests live with the backend suite, because they assert
agreement between the two:

```bash
cd ../BackendAPI && source venv/bin/activate
pytest tests/test_admin_console_frontend.py tests/test_admin_rbac.py -q
```

They walk the App Router tree and the TSX sources and fail the build on a page
with no navigation entry, a queue page with no aggregate, a figure coerced with
`?? 0`, an `aria-modal` without a focus trap, or an admin route added without a
permission gate.

---

## 🚢 Deployment

Vercel, with **Root Directory = `drop-admin`** (this is a monorepo). The
resulting origin has to be listed in three places, and missing any one of them
produces a different confusing failure:

1. the backend's `ALLOWED_ORIGINS`,
2. the Google Maps key's website restrictions,
3. Clerk's allowed origins.

Step-by-step, including the Clerk test accounts for all five roles:
[docs/admin-console-deployment.md](../docs/admin-console-deployment.md).
Operating it once deployed: [docs/admin-console-runbook.md](../docs/admin-console-runbook.md).
The reasoning behind the architecture: [docs/admin-dashboard-architecture.md](../docs/admin-dashboard-architecture.md).
