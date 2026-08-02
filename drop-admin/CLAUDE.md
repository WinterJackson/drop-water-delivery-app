# Drop Admin — AI Developer Guide

The operations console the Drop owners and staff run the business from. Next.js
App Router, talking to the **same FastAPI backend** as the three mobile apps.
No second database, no parallel API.

Architecture and the reasoning behind it: `docs/admin-dashboard-architecture.md`.

## 🔑 The two rules that shape everything

### 1. The browser never holds an API token

Every backend call goes through `lib/api/server.ts`, which is marked
`server-only` — importing it from a Client Component is a **build error**, and
that is deliberate. The token is minted per request by Clerk on the server; the
browser only ever holds Clerk's httpOnly session cookie.

This console renders national ID photographs and M-Pesa numbers. An XSS on any
page of it must not also hand over an admin API token.

Client components therefore never fetch. They call a **Server Action**
(`actions.ts` next to the page), which calls `lib/api/server.ts`.

> Every export of a `"use server"` module must be an `async function`
> declaration. `export const foo = () => …` compiles to a module with **no
> exports at all** and fails at build time, not typecheck.

### 1a. Four layers, and only one of them decides

1. **Middleware** — a Clerk session is required for everything but `/sign-in`.
   There is no public `/sign-up`: administrators are invited and bound on first
   sign-in, and a test fails the build if that route becomes public.
2. **`Admin_Users`, per request** — the session says who; the backend says
   whether. Revocation therefore takes effect on the next click.
3. **Two-factor** — asserted from the Clerk session claim, so it needs a fresh
   sign-in to take effect. The refusal is typed (`two_factor_required`).
4. **`IdleTimeout`** — signs out after 15 minutes idle, with a 60-second
   warning. This console is used on shared desks; an unattended tab needs no
   attacker. It is not what stops a stolen token — layer 2 is.

Dead-end screens ("you don't have access", "two-factor required") must offer a
real **sign-out**, never a link to `/sign-in`. Clerk sees the existing session
and returns the caller to the same refusal — a loop with no exit but clearing
cookies.

### 2. Hiding a control is courtesy — the server decides

`lib/permissions.ts` mirrors `BackendAPI/models/admin_model.py`. It exists so
the nav does not offer someone an action that would refuse them. Every one of
those capabilities is enforced again by `require_admin(...)` on the backend, and
that check is the only one that matters. A build of this app with the checks
deleted would gain nothing.

The **authoritative** capability list ships with the data
(`/api/admin/me`, `/api/admin/admins`), so the roster screen can never offer a
permission the server has dropped nor miss one it has added. The constants file
is only for routing decisions taken before any data has loaded.

## 🧭 Authorisation model

Admins are rows in `Admin_Users`, not entries in an environment variable.
`ADMIN_CLERK_IDS` is retired — it could not express roles, could not be revoked
without a redeploy, and left no attribution.

- Capabilities are `domain.action`. Read and write are always separate.
- `finance.adjust` (crediting a wallet by hand) and `geo.view` (live positions
  for identified people) are their own capabilities. Neither is implied by
  `finance.read` or `riders.read`, and no preset but super admin holds
  `finance.adjust`.
- **Roles are presets, not authority.** Assigning one expands it into
  `permissions`; the role name is never consulted when deciding an action. This
  is what makes a preset safe to edit later.
- `pii.view` is its own capability. `support` and `analyst` do not have it.

## 🔒 Personal data

- Lists render masked values (`••••1234`) for **everyone**, regardless of role.
- Revealing a document is an **action, not a render**: a separate endpoint,
  requiring `pii.view`, requiring a stated reason, audited *before* the URLs are
  returned, and presigned for **5 minutes** rather than the platform's 15.
- Nothing is prefetched. The KYC queue listing carries no document URLs at all —
  presigning them per row would mint live links to identity documents on every
  page load whether or not anyone opened one.
- Identity document images use a plain `<img>`, never `next/image`. The
  optimiser fetches and **caches** on the server, which turns a 5-minute
  presigned link into a stored copy of somebody's national ID.

## 🧭 Navigation and layout

**Every destination is declared once**, in `components/shell/nav-config.ts`. The
sidebar, the mobile drawer, the bottom tab bar and the header breadcrumb all
render from that list. Three hand-maintained copies is how a page gains a
capability check in one place and keeps offering itself in the other two — and
how a page ends up reachable at a desk and invisible on a phone.

A test walks the App Router tree and fails the build if a `page.tsx` exists with
no navigation entry.

- **`lg` and up**: sidebar + header.
- **Below `lg`**: header + fixed bottom tab bar. The bar holds **four**
  capability-filtered destinations plus **More**; the cap is what guarantees the
  drawer is always reachable, so no page is ever stranded.
- Tab bar items are **icons only** by request. That must not mean unlabelled —
  each carries `aria-label` plus an `sr-only` short label, so a screen reader
  announces the word the label would have shown.
- Anything with `aria-modal="true"` must use `useFocusTrap`. The attribute is a
  *promise* that focus cannot leave; without a trap it is simply untrue, and a
  test enforces it.
- The tab bar pads for `env(safe-area-inset-bottom)` (`.pb-safe`) and `<main>`
  reserves its height (`.pb-tabbar`).

### Badges

`GET /api/admin/nav/counts` returns one figure per queue **the caller may
actually open**, and omits the rest. So in `NavCounts`:

- `undefined` — you may not see this queue. Render nothing.
- `0` — nothing is waiting. Also render nothing, but it is a real answer.

`support` counts tickets still **`open`**. A ticket moves to `pending` the moment
an administrator replies, so counting that too would badge the queue with
conversations waiting on the requester — a number nobody can act on is how people
learn to ignore every badge in the console.

Never coalesce the two with `?? 0`. A badge reading "3" on a page that would
refuse the caller leaks the size of a table they cannot see.

The fetch is wrapped in a `catch` in the layout: badges are decoration, and a
slow count must not blank the console — the payout nobody has approved is still
the point of the page.

## 📊 Charts

Recharts where interactivity earns its bundle; hand-drawn SVG where it does not
(`Sparkline`, `GaugeRing` ship **zero** JavaScript). Colours are the
`--chart-1` … `--chart-6` variables, so charts inherit the theme for free.

Two rules:

- **Colour is never the only carrier of meaning.** Every slice, bar and cell
  also states its label and value as text.
- **A funnel needs genuinely nested sets.** `FunnelChart` states the drop-off
  between steps in words, so the steps must each be a subset of the one above.
  "Orders by current status" are siblings, not stages — use `BarList`.

## 💷 Money

It arrives as a decimal **string** and stays one. `formatMoney` formats the
integer and fractional parts separately without ever calling `Number`.

To add money, use `sumMoney()` — never
`values.reduce((a, b) => a + Number(b), 0).toFixed(2)`. That reintroduces the
exact float error the backend goes out of its way to avoid, in a total shown to
a human. Parsing to a number is fine for **pixel positions** in a chart, and
nowhere else.

The same applies to a **difference**: `formatMoneyDelta()` renders `+41.00` /
`-12.50` from the string, and `isZeroMoney()` tests it. `Number(delta).toFixed(2)`
was live on the pricing preview — a float round trip on the one screen whose job
is to make a pricing change safe to approve.

## ⚙️ Business values are rows, not environment variables

Two screens under **Platform** look similar and are not:

- `/platform/settings` — the **deployment's** switches. Process environment
  variables, read-only, labelled as such.
- `/platform/pricing` — the **business's** numbers. Rows in `Platform_Settings`,
  editable, live in all three apps on the next quote.

The pricing editor requires a reason and shows a debounced live preview of what
the change does to a representative order, priced by the backend through the
*same* `calculate_revenue_splits` a real quote uses. Never re-implement that
arithmetic here to avoid a round trip — a preview free to disagree with the quote
is worse than no preview.

`POST /api/admin/config/preview` returns `before`, `after` and `delta`. `delta`
carries money only; `vehicle_class` is a description and has no delta. Read it
with `?? "0.00"`, never assume a key is present.

## 🗺️ The map

**Google Maps**, like the three mobile apps. There is no OSM basemap anywhere on
this platform.

`lib/maps/google-maps.ts` injects the Maps JavaScript API once per page and
exports `useGoogleMaps()`, `DARK_MAP_STYLE` and `LIGHT_MAP_STYLE`.

- `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` is public **by necessity** — the
  browser draws the map. That does not contradict "no Google web service from
  the client": the JavaScript API is an **SDK**, the same arrangement as the
  apps' package-restricted keys. Directions, Places and Geocoding are web
  services and stay behind `routes/maps_routes.py` with the IP-restricted server
  key. Restrict this key to **Websites** + **Maps JavaScript API only** — an
  unrestricted browser key is billed to the project by whoever finds it.
- **Readiness is the `callback` parameter, never the script's `load` event.**
  `loading=async` returns a *bootstrap*; `load` fires when that arrives, while
  `google.maps.Map` is still `undefined`. Constructing one then throws
  "not a constructor" — on a cold cache only, so it survives a dev session.
- Layers refetch on **`idle`**, not `bounds_changed`: the latter fires on every
  animation frame of a drag. Do not load every rider on the platform and filter
  client-side.
- Marker colours are **resolved hex**, not CSS variables. The Maps API paints
  markers onto a canvas and never sees the stylesheet.
- Markers carry **shape and label**, not only colour — the same rule as charts.
- No key configured renders a written panel explaining that, never a blank
  rectangle that reads as a broken map.

## ✉️ Broadcast

The only control here that cannot be undone. The composer requires the audience
key to be typed to confirm, and **changing the audience clears the confirmation**
— otherwise a typed confirmation silently authorises a different, larger send.

`transactional: true` overrides every recipient's notification preferences. It is
presented as a claim the sender makes ("this is not marketing"), not as a
delivery option, and it is recorded against their account either way.

## 🎨 UI conventions

- **Semantic tokens only**: `bg-surface`, `text-muted`, `border-default`. Never
  `bg-white dark:bg-neutral-900` at a call site — that is how the two themes
  drift. Dark mode is one block in `globals.css`.
- The explicit theme toggle writes `data-theme` on `<html>`, which the
  stylesheet gives precedence over `prefers-color-scheme`, so a choice wins in
  **both** directions.
- **Wide content scrolls inside its own box** (`.scroll-x`). The page body must
  never scroll sideways on a phone — operations staff triage the KYC queue on
  one.
- **Data tables become cards below `md`.** Two sets of markup, never one set
  forced through `display: block` — that trick makes a table stop being a table
  to a screen reader. Where the row is interactive, the behaviour lives in a
  shared hook (`useIntervention`, `useDecision`) and only the presentation is
  written twice: approving a payout on a phone must be the same action, with the
  same mandatory reason, as approving one at a desk.
- Empty states are written, not blank. The platform currently has no orders and
  no riders, so every screen renders empty on day one; a blank rectangle reads
  as broken software.
- Never show a raw status code. `lib/api/server.ts` normalises refusals; branch
  on `ApiError.type` (`permission_required`, `two_factor_required`), never on
  the wording of a message.

## 🏃 Running it

```bash
cd drop-admin
pnpm install
pnpm dev          # http://localhost:3000 — already in the backend's ALLOWED_ORIGINS
pnpm typecheck
pnpm build
```

`.env.local` (see `.env.example`):

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` — the **same** Clerk
  application as the three apps.
- `BACKEND_BASE_URL` — deliberately **not** `NEXT_PUBLIC_`. The browser never
  calls FastAPI directly; prefixing it would invite someone to.
- `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` — the only variable that *is*
  deliberately public, and only because the browser draws the map. Restrict it to
  Websites + Maps JavaScript API before it ships. Everything but
  `/operations/map` runs without it.

Deployed on **Vercel** with root directory `drop-admin` (this is a monorepo).
The resulting `https://drop-admin-five.vercel.app` is the origin to list in the backend's
`ALLOWED_ORIGINS`, in the Maps key restriction and in Clerk — see
`docs/render-environment.md`.

> `pnpm-workspace.yaml` carries `fetchTimeout: 900000`. The npm registry is slow
> from here and the Next tarballs are ~35–45MB, which blows past pnpm's 60s
> default and fails the install outright.
