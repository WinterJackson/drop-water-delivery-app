# Deploying the admin console, end to end

From a renamed repository to a working `https://…vercel.app` with five test
administrators, one map and one backend. Do the five parts **in order** — each
depends on a value the previous one produces.

| # | Part | Where | Why it must come first |
|---|---|---|---|
| 0 | Rename the repository | GitHub | Vercel is connected to a repo; connecting it before the rename means reconnecting after |
| 1 | Push | local | Vercel imports from GitHub; `drop-admin/` does not exist there yet |
| 2 | Deploy | Vercel | Produces the URL that parts 3–5 all need |
| 3 | Maps key | Google Cloud | Restriction lists the URL from part 2 |
| 4 | Test accounts | Clerk | Sign-in happens at the URL from part 2 |
| 5 | `ALLOWED_ORIGINS` | Render | The value **is** the URL from part 2 |

---

## Part 0 — renaming `vepo-water-delivery-app` → `drop-water-delivery-app`

**Yes, do it, and do it now.** The cost only grows: it is one setting today and a
Vercel reconnection tomorrow. The platform is called Drop everywhere a customer
can see, and the repository is the last thing still saying otherwise.

GitHub redirects the old name permanently — web URLs, `git clone`, `git push`,
API calls. Nothing breaks the moment you rename.

**Rename it lowercase: `drop-water-delivery-app`.** GitHub preserves the case you
type. Every other identifier in this platform is lowercase-kebab (`drop-admin`,
`drop-rider-app`, `com.drop.customer`), and a capital `D` is the kind of
inconsistency that turns into a wrong `git clone` in six months.

GitHub → repository → **Settings** → **Repository name** → Rename.

### Everything that needs a change afterwards

I searched the whole tree. **No file in this repository contains the repository
name or URL** — not a README badge, not a `package.json`, not a workflow (there
are none), not `app.json`, not `eas.json`. So there is no code change at all.

What lives *outside* the repository:

| Thing | Effect | What to do |
|---|---|---|
| **Your local clone** | Keeps working via GitHub's redirect | `git remote set-url origin git@github.com:WinterJackson/drop-water-delivery-app.git` — I run this for you below |
| **Render** (`vepo-backend`) | Connected through the GitHub App, which tracks the repository by id, so auto-deploy normally survives | **Verify, do not assume.** Render → service → Settings → Repository. If it shows the old name, disconnect and reconnect. Then push a trivial commit and confirm a deploy triggers |
| **Vercel** | Not connected yet | Nothing — this is exactly why part 0 comes before part 2 |
| **EAS / Expo** | Decoupled. Builds are keyed on `projectId` UUIDs and `owner: wj-kuzzi`, never the repo name | Nothing |
| **Clerk, Neon, Redis, Resend, Sentry, cron-job.org, Google Cloud, Safaricom** | All keyed on URLs, DSNs or API keys | Nothing |
| **Any other clone** (another machine, a collaborator) | Redirect keeps it working | `git remote set-url` when convenient |
| **Deploy keys, webhooks, branch protection, secrets** | Attached to the repository object, not its name | Nothing — all survive |

### The one real risk, stated plainly

GitHub's redirect breaks **the day somebody creates a new repository under
`WinterJackson/vepo-water-delivery-app`**. That somebody can only be you, since
the redirect reserves the name on your account. So: do not recreate a repo with
the old name. That is the entire risk.

### Do not rename these

- **`vepo-backend.onrender.com`** — every shipped app has this URL compiled into
  its bundle. Renaming the Render service breaks all three until they are rebuilt
  *and re-released through the stores*, which is weeks, for a hostname no
  customer ever sees.
- **Firebase project `vepo-001`** — the same, for push notifications.

Retire both when you buy a domain, together, deliberately.

---

## Part 1 — push

```bash
cd "/home/kuzzi/Dev/C O D E/Multivendor-Water-Delivery-App"

# After the GitHub rename:
git remote set-url origin git@github.com:WinterJackson/drop-water-delivery-app.git
git remote -v          # confirm

git push origin main
```

`.env`, `.env.local` and `node_modules` are gitignored and were checked before
the commit. `drop-admin/.env.example` ships; it holds no values.

---

## Part 2 — Vercel

Free Hobby plan. No card, no domain.

**Why Vercel and not GitHub Pages:** Pages serves static files. Half of this
console is server code — Server Actions, middleware, and `lib/api/server.ts`,
which mints the Clerk token per request precisely so the browser never holds one.
Pages cannot run any of it. This is not a preference; the app would not function.

1. <https://vercel.com> → sign in **with GitHub**.
2. **Add New → Project** → import `drop-water-delivery-app`.
3. **Root Directory → Edit → `drop-admin`.** ← the one step everybody misses.
   This is a monorepo; left at the root, the build finds no Next.js app and
   fails.
4. Framework preset: **Next.js** (detected). Build command, output directory and
   install command: leave every one on the default.
5. **Project name.** This decides the URL. `drop-admin` was already taken
   globally, so Vercel appended a suffix and the live URL is:

   ```
   https://drop-admin-five.vercel.app
   ```

   That is the value used throughout the rest of this document, in
   `ALLOWED_ORIGINS`, in the Maps key restriction and in Clerk. Vercel's suffix is
   stable for the life of the project — it does not change between deployments.
6. **Environment Variables** — add all four to **Production** (tick Preview and
   Development too; harmless and saves a trip):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_test_…` — the same value as `drop-admin/.env.local` |
   | `CLERK_SECRET_KEY` | `sk_test_…` — Clerk → **API keys**, from the application whose domain matches `CLERK_ISSUER`. See "Which Clerk application" below |
   | `BACKEND_BASE_URL` | `https://vepo-backend.onrender.com` |
   | `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | from part 3 — add it now if you have done part 3, otherwise add it after and redeploy |

7. **Deploy.**

> **Only those four.** Vercel runs the console; it reads no backend variables.
> `ADMIN_2FA_REQUIRED`, `ALLOWED_ORIGINS`, `NEONDB_URL`, `CLERK_ISSUER` and the
> rest belong to Render alone. `CLERK_SECRET_KEY` is the one variable that is
> genuinely needed in **both** places, because both the console's server and the
> API talk to Clerk — and it must be the same value in both.

### The backend really is the same one

`https://vepo-backend.onrender.com` is not a guess. It is the literal value in
all three apps' production build profiles — `drop-rider-app/eas.json:23`,
`drop-vendor-app/eas.json:23`, `drop-customer-app/eas.json:31` and `:45`. One
Render service, one Neon database, one Clerk application. There is no second API.

> A commented-out `multivendor-water-delivery-app.onrender.com` line used to sit
> in the apps' `.env` files, left over from an older Render service. It has been
> deleted — a dead URL in a config file is something somebody eventually
> uncomments.

### Turn preview deployments off

Vercel → project → **Settings → Git → Ignored Build Step**, or simply deploy only
the production branch.

Every branch and pull request otherwise builds at its own hostname
(`drop-admin-five-<hash>-<scope>.vercel.app`). That hostname is in none of the three
allow-lists you are about to configure, so a preview will sign in and then fail
to draw a map — and `ALLOWED_ORIGINS` cannot help, because `main.py` compares
strings and supports no wildcard. An operations console gains nothing from
per-PR previews, and each one is a live door to production data.

### After it deploys

Open the URL. You should reach **the sign-in page**. That alone proves the Clerk
publishable key, the middleware and the build are all correct. You cannot get
past it yet — that is part 4.

---

## Part 3 — Google Cloud Console, for the map

You need **one new key**. Do not reuse a mobile key: a key carries exactly one
application restriction, and an Android-package restriction rejects a browser
outright.

### Create it

1. <https://console.cloud.google.com> → select the project that already holds
   `drop-backend-directions` (the same project keeps the billing and quota in
   one place).
2. **APIs & Services → Library** → search **Maps JavaScript API** → **Enable**.
   This is a different product from the Maps SDK for Android/iOS you enabled for
   the apps; enabling those did not enable this one.
3. **APIs & Services → Credentials → Create credentials → API key**.
4. Rename it immediately: **`drop-admin-maps-js`**. An unnamed key is one nobody
   dares delete later.

### Restrict it — before it is ever deployed

Still on the key's page:

**Application restrictions → Websites → Add:**

```
http://localhost:3000/*
https://drop-admin-five.vercel.app/*
```

(substitute the real Vercel URL from part 2.) Include `localhost` and the map
works locally too, which is what you asked for. `/*` matters — without the path
wildcard only the bare origin is allowed.

**API restrictions → Restrict key → tick *Maps JavaScript API* only.**

Nothing else. Not Directions, not Places, not Geocoding.

**Save.** Restrictions can take up to five minutes to propagate; a
`RefererNotAllowedMapError` in the browser console immediately after saving is
usually just that.

### Why the public key is not a mistake

The browser draws the map, so the key must reach the browser — there is no
arrangement of a JavaScript map in which it does not. That is why it is
`NEXT_PUBLIC_`. What makes it safe is identical to what makes the six mobile keys
safe: it is an **SDK** key with an application restriction, and an SDK key cannot
call a web service.

The platform's rule — *never call a Google web service from the client* — is
about Directions, Places and Geocoding, which are plain HTTPS calls that any
thief can replay from anywhere. Those still go through
`BackendAPI/routes/maps_routes.py` on the IP-restricted server key, and this key
is explicitly forbidden from calling them by the API restriction above.

An unrestricted browser key is the most commonly abused credential in a mapping
stack, and the abuse arrives as an invoice. Both restrictions, before deployment.

### Wire it up

```bash
# drop-admin/.env.local  — for localhost
NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY=AIza…
```

And in **Vercel → Settings → Environment Variables** for the deployment. Vercel
does **not** rebuild on an environment change: after adding it, go to
**Deployments → ⋯ → Redeploy**. `NEXT_PUBLIC_` values are inlined at build time,
so without a redeploy the variable is set and the map still says it is missing.

### Verifying

`/operations/map` draws riders, stores, live orders, coverage and demand. If the
key is wrong you get a written panel naming the likely cause, never a blank
rectangle — and the coverage figures below the map keep working, because they
come from the backend, not from Google.

---

## Part 4 — Clerk test accounts that work on the Vercel URL

### Which Clerk application — read this first

The platform used to authenticate against a Clerk application on an email
account that is no longer accessible. It has been migrated. There is exactly one
live instance now:

| | Value |
|---|---|
| Application | **Drop** |
| Frontend API | `safe-marmot-72.clerk.accounts.dev` |
| Instance id | `ins_3EVEIgEZGdiqvolZq2ZwKiYVfhS` |
| Publishable key | `pk_test_c2FmZS1tYXJtb3QtNzIuY2xlcmsuYWNjb3VudHMuZGV2JA` |

The retired one was `pet-airedale-22.clerk.accounts.dev`
(`ins_2x8bpcDIKN2T7cuquYzNfDWigYW`). If that string appears anywhere again, it is
a mistake.

> **The publishable key is not a secret and is derivable.** It is literally
> `pk_test_` + the Frontend API hostname, base64-encoded with a trailing `$`.
> That is how the two instances were told apart in the first place, and it means
> you can always check a key without looking it up:
>
> ```bash
> python3 -c "import base64,sys; print(base64.b64decode(sys.argv[1].split('_',2)[2]+'==').decode())" pk_test_c2FmZS1tYXJtb3QtNzIuY2xlcmsuYWNjb3VudHMuZGV2JA
> ```

`CLERK_SECRET_KEY` is the one value that cannot be derived. Take it from this
application's **API keys** page and set it in three places — `BackendAPI/.env`,
Render, and Vercel — then:

```bash
cd BackendAPI && source venv/bin/activate
python scripts/check_clerk_secret.py
```

A key from a different application is the worst kind of wrong, because it looks
right: token verification keeps working (that reads `CLERK_JWKS_URL`), and only
the *binding* fails. Every administrator signs in successfully and is then
refused as "not an administrator", with nothing in the logs naming the cause.
That script exists solely to catch this, and it compares instance ids rather than
trusting appearances — a secret key is an opaque string with no instance name in
it.

The `safe-marmot-72` name is an auto-generated development subdomain. It is not
customer-visible, appears in no UI, and is replaced by your own domain when you
create a **production** instance. There is nothing to fix about it.

#### What the migration touched

| Where | Variable |
|---|---|
| `BackendAPI/.env` | `CLERK_ISSUER`, `CLERK_JWKS_URL`, `FRONTEND_CLERK_API_KEY` |
| Three apps' `.env` **and** three `eas.json` | `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY` |
| `drop-admin/.env.local` | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` |
| **Render** — you | the same three as `BackendAPI/.env`, plus `CLERK_SECRET_KEY` |
| **Vercel** — you | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` |

`FRONTEND_CLERK_API_KEY` is not a stray copy of the publishable key — it is
passed as the JWT **audience** in `core/security.py:171`. Leaving it on the old
value is a check that quietly stops meaning anything.

#### Accounts the migration orphans

A Clerk subject only exists inside the instance that minted it, and Clerk cannot
translate one into another — the same person signing into the new application
gets an unrelated id. So any stored `clerk_id` from the retired instance now
points at nobody.

```bash
python scripts/clerk_rebind.py audit
```

On this database that is **two rows**, both in `Users`: one seed record
(`ngong_customer@example.com`) that was never a person, and one real account,
`winterjacksonwj@gmail.com`. Every rider, vendor, administrator and staff row is
unbound, so nothing else is affected.

`clerk_id` is `NOT NULL`, so the column cannot simply be cleared. Sign in once on
the customer app against the new instance, read the new subject from the Clerk
dashboard (Users → the account → **User ID**), then:

```bash
python scripts/clerk_rebind.py repoint --table Users \
    --email winterjacksonwj@gmail.com --clerk-id user_<new subject>          # dry run
python scripts/clerk_rebind.py repoint --table Users \
    --email winterjacksonwj@gmail.com --clerk-id user_<new subject> --apply
```

The five **administrator** rows need none of this — they bind by email on first
sign-in, so they attach themselves to the new accounts with no intervention.

#### Everyone signed in right now is signed out

Tokens minted by the retired instance no longer verify against the new JWKS. Any
app session open on a phone will start returning 401 and the user re-signs in.
With no released builds and one real account that is a non-event, but it is worth
knowing rather than discovering.

### Why `424242` needs different addresses

Clerk's fixed verification code is not a dashboard setting. It is a property of
**test identities**, and an address only becomes one by carrying the
`+clerk_test` subaddress:

```
super-admin+clerk_test@example.com
```

For any such address Clerk **sends no email at all** and accepts the code
`424242`, every time. Phone numbers behave the same way in the fictional range
`+1 (XXX) 555-0100`–`0199`.

This is why the earlier `@droptest.local` roster was wrong for your purpose: a
plain invented domain gets a *real* email sent to a mailbox that cannot exist, so
the account never verifies. Those five rows are deleted and replaced.

> **Development instance only.** `+clerk_test` and `424242` do nothing on a
> production (`pk_live_`) instance. That is fine and in fact required here: a
> development instance's Frontend API is `<slug>.clerk.accounts.dev`, which is
> not domain-locked, so it works from `drop-admin-five.vercel.app` with no DNS
> records. A production instance needs a domain you own and CNAMEs, which is
> exactly the thing you do not have yet.

### The five rows already exist

Run against your Neon database — nothing to do, shown for reference:

| Email | Role | Capabilities |
|---|---|---|
| `super-admin+clerk_test@example.com` | `super_admin` | 26 |
| `operations+clerk_test@example.com` | `operations` | 16 |
| `finance+clerk_test@example.com` | `finance` | 9 |
| `support+clerk_test@example.com` | `support` | 9 |
| `analyst+clerk_test@example.com` | `analyst` | 2 |

Regenerate at any time with:

```bash
cd BackendAPI && source venv/bin/activate
python scripts/admin_access.py grant-roles --domain example.com --clerk-test
python scripts/admin_access.py list
```

### Create the five Clerk users

Clerk dashboard → your **development** application.

1. **Configure → Email, phone, username**: **Email address** on as an identifier;
   **Password** on. Without password, the Create-user form offers no password
   field.
2. **Users → Create user**, five times:

   | Field | Value |
   |---|---|
   | Email address | the address from the table above, **character for character** |
   | Password | `Drop2026!!` |
   | First name *(optional)* | `Super Admin`, `Operations`, `Finance`, `Support`, `Analyst` |

Binding is an exact lower-cased email match, so a stray capital or a missing
`+clerk_test` simply never binds and the console reports "not an administrator".

If Clerk rejects the password it is one of two rules under **Configure →
Password**: minimum length (`Drop2026!!` is 10), or the compromised-password
check against HaveIBeenPwned. Turn the latter off **on the development instance
only**, or choose another password and use it for all five.

### Two settings, or none of this works

**`CLERK_SECRET_KEY` must be set on Render.** This is the one that will cost you
an afternoon. Sign-in will succeed and *every* administrator will be refused,
because binding a row to a Clerk subject requires the backend to read the
caller's email from Clerk's API. Render → `vepo-backend` → Environment → add
`CLERK_SECRET_KEY=sk_test_…`, the same value as Vercel. Verify with:

```bash
cd BackendAPI && source venv/bin/activate
python scripts/check_clerk_secret.py
```

It fails loudly if the key belongs to a *different* Clerk instance than
`CLERK_ISSUER` — the second-commonest cause of "authenticated but refused".

**`ADMIN_2FA_REQUIRED=false` — on Render only, never on Vercel.** It is read by
`BackendAPI/dependencies/admin_dependencies.py:81`, and the backend is the only
thing that reads it. Vercel runs the console, which does not enforce this check
at all; setting it there does nothing but mislead the next person. The five
accounts have no second factor, and the default (`true`) answers every one of
them with `two_factor_required` instead of a dashboard. It is a real weakening of a console that reads national IDs and approves
payouts — so set it while testing and **turn it back on before a real
administrator exists**, at which point that person enables 2FA on their own Clerk
account and signs in fresh (the check reads a session claim, so it needs a new
sign-in to take effect).

### Walk the roles

Open the Vercel URL in a **private window** per role: sign in, look, sign out,
next. Each row binds on first sign-in; `admin_access.py list` should then read
`bound` five times.

Use the console's own **Sign out**, not a link to `/sign-in` — Clerk sees the
live session and returns you to where you were.

What each role should and should not see is the checklist in
[admin-console-runbook.md](./admin-console-runbook.md) §4.

### When you are finished

```bash
python scripts/admin_access.py prune-tests          # dry run
python scripts/admin_access.py prune-tests --apply
```

It only ever touches addresses containing `.invalid`, `.local` or `+clerk_test` —
none of which can be a real mailbox. Delete the five Clerk users in the dashboard
the same way you made them.

---

## Part 5 — the three allow-lists

The Vercel URL now has to be named in three places. Missing one produces a
different, confusing symptom in each case.

| Where | Value | Symptom if missing |
|---|---|---|
| **Render** → `ALLOWED_ORIGINS` | `https://drop-admin-five.vercel.app` | Nothing today (the console's browser never calls FastAPI — the Next server does). It is fail-closed insurance for the first client-side call anyone adds |
| **Google Cloud** → key → Websites | `https://drop-admin-five.vercel.app/*` | `RefererNotAllowedMapError`; the map panel appears, the rest of the page is fine |
| **Clerk** → Configure → Domains / allowed origins | `https://drop-admin-five.vercel.app` | Usually nothing on a development instance; check here first if sign-in redirects in a loop |

Replace the whole `ALLOWED_ORIGINS` value; do not append to `*`, which would
leave the wildcard branch active:

```
ALLOWED_ORIGINS=https://drop-admin-five.vercel.app,http://localhost:3000
```

Comma-separated, no spaces, no trailing slash, no wildcards — `main.py` splits on
commas and compares strings exactly. Keep `http://localhost:3000` so local
development keeps working.

The three mobile apps are unaffected either way: React Native's `fetch` does not
enforce CORS, so no native client has ever needed an entry here.

Render restarts the service on an environment change. Give it a minute.

---

## When you buy a domain

Nothing about the shape of this changes. Add the domain in Vercel, then add the
new origin to the same three allow-lists and remove the `.vercel.app` one — each
is a list, so both can run side by side during the switch-over. That is also the
moment to move Clerk to a production instance (which needs the domain and its
CNAME records), and the moment to retire `vepo-backend.onrender.com` and
`vepo-001` together.
