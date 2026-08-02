# Running the admin console, and checking it as every role

Everything below is local. The console is a Next.js app that talks to the same
FastAPI backend the three mobile apps use — there is no second database and no
separate API, so anything you change here is live for the apps immediately.

> Deploying it to a public URL — Vercel, the Google Maps key, the Clerk test
> accounts and the three allow-lists — is
> [admin-console-deployment.md](./admin-console-deployment.md).

---

## 1. Before it will start

| What | Where | Status on this machine |
|---|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `drop-admin/.env.local` | set |
| `CLERK_SECRET_KEY` | `drop-admin/.env.local` | **placeholder** (`sk_test_your…`) — sign-in will fail |
| `BACKEND_BASE_URL` | `drop-admin/.env.local` | `http://localhost:8000` |
| `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | `drop-admin/.env.local` | **empty** — every screen but `/operations/map` works without it (§8) |
| `CLERK_SECRET_KEY` | `BackendAPI/.env` | **absent** — needed to bind an invited admin, and for vendor staff invites |
| `NEONDB_URL`, `REDIS_URL` | `BackendAPI/.env` | set |
| `RESEND_API_KEY` | `BackendAPI/.env` | set (`re_…`) |

Two of those must be fixed before anything works:

```bash
# Clerk dashboard → API keys → Secret key (starts sk_test_ / sk_live_)
# Put the SAME value in both files. The console and the backend are one Clerk app.
#   drop-admin/.env.local   CLERK_SECRET_KEY=sk_test_…
#   BackendAPI/.env         CLERK_SECRET_KEY=sk_test_…
```

`ALLOWED_ORIGINS` in `BackendAPI/.env` already contains `http://localhost:3000`,
so CORS is done.

### How the console authenticates

Four independent things, in the order a request meets them:

1. **Clerk middleware.** Everything except `/sign-in` requires a session. The
   sign-up route is deliberately *not* public — administrators are invited, never
   self-registered, and the sign-in page hides the sign-up link.
2. **`Admin_Users`, on every request.** A session only proves who you are; the
   backend decides whether you are an administrator and what you may do, per
   request, so revoking somebody takes effect on their next click rather than at
   their next sign-in.
3. **Two-factor**, asserted from the Clerk session claim rather than trusted
   from the client.
4. **The token never reaches the browser.** Every call goes through the Next
   server (`lib/api/server.ts`, marked `server-only` — importing it from a client
   component is a build error). The browser holds Clerk's httpOnly cookie, which
   is useless against the API.

On top of that the console **signs an idle administrator out** after 15 minutes,
with a 60-second warning they can dismiss. It is not what stops a stolen token —
the per-request check is — it is what stops the unattended tab on a shared desk.

### Two-factor

`ADMIN_2FA_REQUIRED` defaults to **true**, and the check reads Clerk's session
claim — a session that never used a second factor cannot acquire it by asking,
so enabling 2FA needs a **fresh sign-in** to take effect. Either enable it on
your Clerk account, or turn it off for local work:

```bash
# BackendAPI/.env
ADMIN_2FA_REQUIRED=false
```

Leave it **on** in production. This console reads national IDs and approves
payouts.

---

## 2. Start it

Four processes. Each in its own terminal.

```bash
# 1 — Redis (rate limits, the config version counter, the job queue)
redis-server
# already have one? check with:  redis-cli ping   → PONG

# 2 — The API
cd "BackendAPI"
source venv/bin/activate
uvicorn main:app --reload --port 8000

# 3 — The background worker (broadcast sends, sweeps, receipts)
cd "BackendAPI"
source venv/bin/activate
arq worker.WorkerSettings

# 4 — The console
cd drop-admin
pnpm install          # first time only
pnpm dev              # http://localhost:3000
```

The worker is not optional if you intend to test **broadcast**: the send
endpoint queues the campaign and returns; without a worker it stays `queued` for
ever, which is the correct behaviour and looks like a bug.

### "The console can't load right now — could not reach the server"

Signing in works and then every screen says this. It means exactly what it says:
the console reached Clerk, minted a token, and found **nothing listening on
`BACKEND_BASE_URL`**. Almost always process 2 was never started, or it died.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/health   # want 200
```

Anything other than `200` — including no output at all — and the API is the
problem, not the console. Start it, then reload the page; no sign-out needed,
the Clerk session is unaffected.

Since it is a *server-side* fetch, nothing appears in the browser's network tab —
the request never leaves the Next server. The `pnpm dev` terminal now prints the
URL it failed to reach and the command that starts it, in development only.

**Redis is not required for this.** `redis-server` is not installed on this
machine, and the API starts anyway: rate limiting falls back to in-memory and
WebSockets to local-only mode, both of which it announces at startup. You need
Redis for broadcast, the job queue and the config-version counter — not to open
the console.

---

## 3. Get in

There are **no administrators** on a fresh database, and `ADMIN_CLERK_IDS` does
not grant any — `seed_first_admin` reads it and nothing calls
`seed_first_admin`. Use the script:

```bash
cd "BackendAPI" && source venv/bin/activate

# Who has access right now
python scripts/admin_access.py list

# Grant yourself the first super admin. Use the email on your Clerk account.
python scripts/admin_access.py grant --email you@example.com --role super_admin
```

The row binds to your Clerk subject the first time you open the console. (That
binding is what `_resolve_admin` → `bind_admin_for_caller` does, and it needs
`CLERK_SECRET_KEY` on the **backend**.)

Then sign in at <http://localhost:3000>.

Left-over rows from an interrupted test run can be cleared — it only ever
touches addresses containing `.invalid`, `.local` or `+clerk_test`, none of which
can be a real mailbox:

```bash
python scripts/admin_access.py prune-tests           # dry run
python scripts/admin_access.py prune-tests --apply
```

---

### Or: one Clerk account per role

Five real sign-ins, one per preset. Two halves: the **Clerk dashboard** creates
the identities, and `admin_access.py` creates the authorisation rows. They meet
on the email address.

There is deliberately no script that creates the Clerk users. It would mean a
process holding the password for five privileged identities and a
`--allow-production` flag as the only thing between it and a live instance.
Creating them in the dashboard leaves the credential where it belongs and the
audit trail with Clerk.

#### Step 1 — the five administrator rows (one command)

```bash
cd "BackendAPI" && source venv/bin/activate
python scripts/admin_access.py grant-roles --domain example.com --clerk-test
```

`--clerk-test` inserts Clerk's `+clerk_test` subaddress, and that is not
cosmetic: for an address carrying it, Clerk **sends no email at all** and accepts
the fixed verification code **`424242`**. A plain invented domain gets a real
email sent to a mailbox that cannot exist, and the account never verifies.

That creates one row per preset, each *awaiting sign-in*:

| Email | Role | Capabilities |
|---|---|---|
| `super-admin+clerk_test@example.com` | `super_admin` | 26 |
| `operations+clerk_test@example.com` | `operations` | 16 |
| `finance+clerk_test@example.com` | `finance` | 9 |
| `support+clerk_test@example.com` | `support` | 9 |
| `analyst+clerk_test@example.com` | `analyst` | 2 |

> `+clerk_test` and `424242` work on a **development** Clerk instance only. That
> suits this platform: a development instance's Frontend API is not domain-locked,
> so the same five accounts work at `localhost:3000` **and** at the deployed
> Vercel URL with no DNS records.

#### Step 2 — enable password sign-in once

Clerk dashboard → your **development** application → **Configure → Email, phone,
username**:

- **Email address** — on, used as an identifier.
- **Password** — on. If it is off, the Create-user form shows no password field.

#### Step 3 — create the five users

**Users → Create user**, five times. For each one:

| Field | Value |
|---|---|
| Email address | the address from the table above, exactly |
| Password | `Drop2026!!` |
| First name *(optional)* | `Super Admin`, `Operations`, `Finance`, `Support`, `Analyst` |

The address must match character for character — binding is an exact,
lower-cased email match, and a missing `+clerk_test` or a stray capital simply
never binds.

Where Clerk asks for a verification code, it is **`424242`**.

If Clerk rejects the password, it is one of two rules under **Configure →
Password**: a minimum length (`Drop2026!!` is 10), or the compromised-password
check against HaveIBeenPwned. Turn the latter off **on the development instance
only**, or pick a different shared password and use it for all five.

#### If the dashboard says "Something went wrong, please try again"

It is a **Clerk dashboard UI fault, not a rejection.** The same payload — same
addresses, same password, same instance — is accepted by Clerk's Backend API
without complaint, which is how it was diagnosed: the first user creates fine and
every subsequent one fails, so the data is not the problem.

Reload the dashboard tab between creations and it usually clears. If it does not,
create the remaining users through the API instead — same result, same instance,
same audit trail:

```bash
cd BackendAPI && source venv/bin/activate
python - <<'EOF'
import os
from dotenv import load_dotenv; load_dotenv()
from clerk_backend_api import Clerk

ROSTER = [
    ("super-admin+clerk_test@example.com", "Super Admin"),
    ("operations+clerk_test@example.com",  "Operations"),
    ("finance+clerk_test@example.com",     "Finance"),
    ("support+clerk_test@example.com",     "Support"),
    ("analyst+clerk_test@example.com",     "Analyst"),
]
with Clerk(bearer_auth=os.environ["CLERK_SECRET_KEY"]) as c:
    existing = {
        e.email_address
        for u in (c.users.list(request={"limit": 100}) or [])
        for e in (u.email_addresses or [])
    }
    for email, name in ROSTER:
        if email in existing:
            print(f"  exists   {email}")
            continue
        u = c.users.create(request={
            "email_address": [email],
            "password": "Drop2026!!",
            "first_name": name,
        })
        print(f"  created  {email:<36} {u.id}")
EOF
```

This is deliberately a paste-once snippet rather than a committed script. A file
that creates five privileged identities with a known password is a file that gets
run against production by accident; a snippet in a runbook is read before it is
used.

#### Step 4 — sign in as each

Open the console in a private window, sign in, look, sign out, next. Each row
binds to its Clerk subject on that first sign-in; nothing else to run.
`python scripts/admin_access.py list` should then show all five as `bound`.

Use a private window per role rather than switching in one: Clerk keeps the
session, and the console's own **Sign out** is the only reliable way back to the
sign-in form — a link to `/sign-in` with a live session returns you straight to
where you were.

#### Before this works: two settings

- **`ADMIN_2FA_REQUIRED=false`** in `BackendAPI/.env`, and on **Render** for the
  deployed console — never on Vercel, which does not read it. These accounts have
  no second factor, and with the default (`true`) every one of them gets
  `two_factor_required` instead of a dashboard. **Delete the variable** once a
  real administrator exists; absence already means required.
- **`CLERK_SECRET_KEY` on the backend.** Binding a row to a Clerk subject means
  reading the caller's email from Clerk's API. Without it every one of the five
  signs in successfully and is then refused as "not an administrator" — the
  single most confusing failure in this whole setup. Check it with
  `python scripts/check_clerk_secret.py`, which also catches the key belonging to
  a *different* Clerk instance than `CLERK_ISSUER`.
- These are shared-password accounts with no second factor. They belong on a
  **development** Clerk instance and nowhere near real customer data. For real
  people, `python scripts/admin_access.py grant --email … --role …` and let them
  bring their own credential.

#### When you are done

```bash
python scripts/admin_access.py prune-tests          # dry run
python scripts/admin_access.py prune-tests --apply
```

It only ever touches addresses containing `.invalid`, `.local` or `+clerk_test`,
none of which can be a real mailbox. Delete the five Clerk users from the
dashboard the same way they were created.

---

## 4. Check every role

You do **not** need five Clerk accounts. Switch your own row's preset, reload,
look, switch back:

```bash
python scripts/admin_access.py role --email you@example.com --role operations
# … look at the console …
python scripts/admin_access.py role --email you@example.com --role super_admin
```

Capabilities are read per request, so a reload is enough — no sign-out.

### What each role should see

The sidebar is generated from the caller's capabilities, so this is also the
checklist for whether authorisation is behaving.

**`super_admin`** — 26 capabilities, everything:

> Dashboard · Analytics · Orders · Rider verification · Live map · Vendor
> verification · Bottle disputes · Support inbox · Customers · Riders · Vendors ·
> Payouts · Transactions · Administrators · Audit log · Pricing & fees ·
> Broadcast · Settings

**`operations`** — 16. Runs the platform day to day, touches no money:

> Dashboard · Analytics · Orders · Rider verification · Live map · Vendor
> verification · Bottle disputes · Support inbox · Customers · Riders · Vendors

*Must be refused:* `/finance/payouts`, `/finance/transactions`,
`/platform/pricing`, `/platform/broadcast`, `/platform/admins`.

**`finance`** — 9. Money, and the context needed to check it:

> Dashboard · Analytics · Orders · Rider verification · Vendor verification ·
> Riders · Vendors · Payouts · Transactions

*Must be refused:* `/support`, `/operations/map`, `/platform/pricing`. And on an
account detail page there must be **no Wallet adjustment card** — `finance.adjust`
is deliberately not in this preset. Creating a balance from nothing is a super
admin decision even inside the finance team.

**`support`** — 9. No personal data, no money:

> Orders · Rider verification · Live map · Vendor verification · Bottle disputes ·
> Support inbox · Customers · Riders · Vendors

No Dashboard: this preset has no `analytics.read`, so `/` redirects to the first
screen they *can* work rather than showing them a refusal on arrival. Lists show
masked emails and phone numbers, and the **Reveal** control on a rider's KYC
documents must refuse — `pii.view` is not in this preset.

**`analyst`** — 2. Answers questions, changes nothing, identifies nobody:

> Dashboard · Analytics · Orders

*Must be refused:* everything else, including every write.

### Three things worth trying by hand

1. **A refusal is typed, not a status code.** As `support`, open a rider and
   press Reveal. You should get a sentence naming the capability, never a 403.
2. **Hiding is courtesy.** As `analyst`, type `/finance/payouts` into the address
   bar. The nav does not offer it *and* the server refuses it — the second is the
   one that matters.
3. **Badges are per-caller.** `GET /api/admin/nav/counts` returns a figure only
   for queues you may open. As `finance` you get `payouts`; as `support` you get
   `support` and `disputes`. A badge for a page that would refuse you leaks the
   size of a table you cannot see.

---

## 5. Check the things that touch the apps

### Pricing reaches all three apps with no release

```
Pricing & fees → change "Retail service fee" 12 → 25 → give a reason → save
```

Watch the preview move before you save: it prices a representative order through
the same `calculate_revenue_splits` a real quote uses. Then, without restarting
anything:

```bash
curl -s localhost:8000/api/admin/config/effective \
  -H "Authorization: Bearer <admin token>" | jq '.values.retail_service_fee'
```

…and open the customer app's cart. The next quote is the new number. Change it
back the same way; `Pricing & fees → History` shows both edits with the reason.

Orders already placed are unaffected: the splits are written onto the order at
quote time and settlement pays from those columns.

### Support, end to end

1. In any of the three apps: **Settings → Help & Support → New**, write a
   request. (Rider app: also reachable from the verification wall, before KYC.
   Customer app: also from an order, which attaches it.)
2. Console: the **Support inbox** badge increments. Open the ticket, reply.
3. Back in the app: the reply is in the thread, and a push arrives. An internal
   note (tick "internal") must **not** appear in the app.
4. Ticket status moves `open → pending` on your reply, and back to `open` if they
   write again.

### Broadcast

Needs the ARQ worker running. Send to a small segment first — the composer states
the recipient count before you can send, and requires you to type the audience
key. Email delivery additionally needs a verified Resend domain (§6).

---

## 6. Email

`RESEND_API_KEY` is set in `BackendAPI/.env` and on Render, so the wiring is
done. Two things still gate real delivery:

- **`EMAIL_FROM` is `Drop <onboarding@resend.dev>`.** Resend's shared onboarding
  sender only delivers to the address that owns the Resend account. Verify a
  domain in Resend and point `EMAIL_FROM` at it, or every broadcast email to a
  customer is refused while the in-app notification still lands.
- **The worker process needs the variable too.** Broadcast email is sent from
  ARQ, not from the request. If `RESEND_API_KEY` is set on the Render *web*
  service and not the *worker*, campaigns will report themselves sent with no
  email leaving the building — `email_service` degrades to logging by design.

`_resend_available` is decided at import, so adding the key needs a restart.

---

## 7. Quick smoke, without a browser

Any admin route needs a Clerk token. Easiest source is the console itself: sign
in, open devtools → Network → any request → copy the `Authorization` header the
Next server sends. Then:

```bash
TOKEN="…"
B=http://localhost:8000

curl -s $B/api/admin/me           -H "Authorization: Bearer $TOKEN" | jq '.role, (.permissions|length)'
curl -s $B/api/admin/nav/counts   -H "Authorization: Bearer $TOKEN" | jq
curl -s $B/api/admin/config       -H "Authorization: Bearer $TOKEN" | jq '.settings|length'
curl -s $B/api/admin/map/coverage -H "Authorization: Bearer $TOKEN" | jq '.uncovered|length'
curl -s $B/api/admin/support/counts -H "Authorization: Bearer $TOKEN" | jq
```

---

## 8. The map, layer by layer

The basemap is **Google Maps**, the same as the three apps. Every layer on top of
it is computed by the backend from PostGIS and H3 — the browser calls Google for
tiles and for nothing else.

It needs one variable:

```bash
# drop-admin/.env.local
NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY=AIza…
```

**Mint a new key for this**, do not reuse a mobile one — a key carries a single
application restriction, and an Android-package restriction rejects a browser.
In the Google Cloud console, on the new key:

- **Application restrictions → Websites**: `http://localhost:3000/*` and
  `https://drop-admin-five.vercel.app/*`.
- **API restrictions → Maps JavaScript API** only.

Without both, a key lifted from the page's JavaScript bundle is billed to the
project. Without the variable at all the screen renders a written explanation
rather than a blank rectangle, and the four data endpoints keep working — so if
you see the panel, the map is misconfigured, not the backend.

Verified against the live database:

| Layer | Source | Right now |
|---|---|---|
| Riders | `Deliverers.current_lat/lng`, viewport-scoped | **30 points** |
| Stores | `Vendors.location` (PostGIS geometry) | **21 points** |
| Orders in flight | positioned at their vendor | **6 points** |
| Coverage | `ST_DWithin` on the retail radius | **21 of 21 stores uncovered** |
| Demand | `Orders.h3_index_res8`, cells with ≥ 2 orders | **0 cells** — see below |

**Coverage reporting every store uncovered is correct, not a bug.** All 30
riders are `kyc_status = 'unsubmitted'`, so none is deployable and no store has
a rider who could serve it. That number is the point of the screen.

**Demand is empty for a different and more interesting reason.** The layer
aggregates orders into H3 cells and only draws a cell with **two or more** — a
single order in a cell is somebody's home address, and drawing it would put a
customer's front door on an operations map. There are 14 orders spread across 14
distinct cells, so nothing qualifies yet.

Those 14 orders had no cell at all until now: `create_order` writes
`h3_index_res8`, but these predate that line, and both this layer and the
analytics geographic breakdown filter `IS NOT NULL` — so missing data looked
exactly like "no orders here". Backfilled from the coordinates already on each
row:

```bash
python scripts/backfill_order_h3.py           # report
python scripts/backfill_order_h3.py --apply   # already run
```

## 9. What the data looks like right now

Worth knowing before you conclude a screen is broken:

- **30 riders, none deployable.** Every one is `kyc_status = 'unsubmitted'`, so
  the KYC queue is empty *and* nobody can accept a delivery. The Live map shows
  no available riders and the coverage report flags all 21 stores.
- **21 vendors, all `pending`.** Verify them before turning
  `require_vendor_verification` on, or the customer app's directory goes empty.
- **6 orders in flight**, which is what the order board and the map render.

Empty screens here are honest, not broken.
