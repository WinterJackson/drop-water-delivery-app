# Database setup — local development and a deployed Postgres

Drop needs one Postgres with **PostGIS**. That is not negotiable: 44 spatial
calls across `services/` and `routes/` decide the delivery radius, and the
`Geography` columns they measure are the platform's definition of which stores a
customer may order from. Anything Postgres-*compatible* rather than Postgres —
CockroachDB and friends — has no PostGIS and will not start this application.

Also required: `pg_trgm`, and the built-in `TSVECTOR`, `JSONB`, `ARRAY` and
`UUID` types.

---

## Why there is a bootstrap script and not just `alembic upgrade head`

**The migration chain cannot build this database.** Sixty-five revisions, two
bases, and not one of them creates `Vendors`, `Users`, `Orders` or `Products`.
Those tables predate Alembic and were created out-of-band, so every revision
*alters* a schema no revision ever *creates*. `alembic upgrade head` against an
empty database fails on the first `ALTER TABLE`.

That was invisible while there was exactly one database and nobody made a
second. It stopped being invisible the moment a local one was wanted — and it
also meant the repository could not rebuild production if it ever had to.

`scripts/bootstrap_database.py` is the path for an **empty** database:

1. creates `postgis` and `pg_trgm` — no migration creates PostGIS, it was
   enabled by hand on the first database and never written down, so any fresh
   one failed at the first `Geography` column with nothing naming the cause;
2. creates the schema from `Base.metadata`, the models being the only complete
   description of it that exists;
3. stamps the Alembic head, so the next real migration applies on top.

It **refuses** if the database already has a migration history. On an existing
database the right command is `alembic upgrade head`, and `create_all` there
would build tables no migration produced — exactly what the note in
`db/session.py` warns about.

---

## Local development

`tests/test_admin_e2e.py` connects to whatever `NEONDB_URL` names. It is the one
file in the suite that touches a real database, which means that pointed at a
managed provider **every `pytest` run spends metered compute**. That is how the
original Neon project reached its quota and took the deployed API down with it.
A local database removes the meter from the loop entirely.

```bash
cd BackendAPI
docker compose -f docker-compose.dev.yml up -d      # Postgres 16 + PostGIS 3.4
python scripts/bootstrap_database.py
python -m seed.seed_data                            # 21 vendors, 30 riders
python -m seed.seed_orders                          # optional: priced orders
```

Then in `BackendAPI/.env`:

```
NEONDB_URL="postgresql+asyncpg://drop:drop_local_dev@localhost:5434/drop"
```

Port **5434**, because 5432 and 5433 are commonly already taken. It is bound to
`127.0.0.1` only: the password is in the compose file and in every developer's
`.env`, so on `0.0.0.0` it would be an open database on any network the machine
joins.

`db/session.py` decides TLS **from the host** — required for every remote
database, dropped for loopback, which serves none. It is derived rather than
configured so that it cannot be switched off for a remote database by mistake.

To rebuild from scratch:

```bash
PGPASSWORD=drop_local_dev psql -h localhost -p 5434 -U drop -d drop \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
python scripts/bootstrap_database.py && python -m seed.seed_data
```

### What the seed does not create

The seed creates vendors, riders and catalogues. It does **not** create customer
accounts, because a customer is a Clerk identity that lives in Clerk's cloud and
a `Users` row that references it. To get one locally, sign in on the app against
a locally-running API — onboarding writes the row.

---

## A deployed database

The application reads exactly one variable, `NEONDB_URL`, in seven places. The
name is historical; it holds a DSN for whichever provider you use. Changing
provider is that variable, plus a bootstrap.

`db/session.py` strips the query string before handing the URL to asyncpg, which
does not accept `sslmode` or `channel_binding` as URL parameters. Provider
console strings usually carry them; paste them as-is.

### Choosing one

The requirement that decides it is PostGIS. The requirement that decides it
*second* is **what the free tier meters**.

* **Neon** meters **compute-hours** — it charges for activity. An app under
  daily testing burns it, and when the quota goes the database refuses every
  connection with `InsufficientResourcesError` until the billing period rolls.
  There is no partial degradation and no warning in-band.
* **Supabase** meters storage (500 MB) and egress, and pauses a project after
  roughly a week of **inactivity**. For something being actively used that never
  triggers. PostGIS is enabled from the dashboard.

For a project in daily use those are opposite failure modes, and Supabase's is
the one that does not punish you for using it.

* **Aiven** — free PostgreSQL plan, PostGIS available, single node, no backups
  on the free plan.
* **Render Postgres** — same platform as the API and PostGIS is supported, but
  free instances **expire and are deleted after about 30 days**. Throwaway only.

Free-tier limits move; check the current pricing page before committing.

### Supabase, step by step

1. Create a project at <https://supabase.com/dashboard>. Choose a region near
   the API — the deployment is on Render, so match its region rather than
   yours; every query pays that round trip, not the user.
2. **Database → Extensions**, enable **`postgis`**. Nothing else is needed;
   `bootstrap_database.py` creates `pg_trgm` itself.
3. **Connect** (top of the dashboard) **→ Direct → Session pooler → URI**.
   Identify it by the string rather than the label: host contains
   `pooler.supabase.com`, port **5432**, user `postgres.<ref>`.

   Not the **transaction** pooler on 6543 — `asyncpg` uses prepared statements
   and transaction-mode pooling does not support them, which fails intermittently
   under load rather than immediately. Not the **direct** connection either,
   despite also being 5432: it is IPv6-only on the free plan, so it works from a
   laptop and fails from Render.

4. **TLS.** Supabase's pooler serves a leaf issued by `Supabase Intermediate
   2021 CA` under a private `Supabase Root 2021 CA`. No system trust store
   carries that root, so a verifying client fails with

   ```
   ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
   self-signed certificate in certificate chain
   ```

   The usual advice is to stop verifying (`ssl="require"`, or `sslmode=require`,
   which encrypts and asks no questions). **Do not.** Encryption without
   verification stops somebody *reading* the connection and does nothing about
   somebody *being* the far end of it, and what crosses this one is every
   customer record, every rider's identity document reference and every wallet
   movement.

   Verify against Supabase's CA instead. It is committed at
   `BackendAPI/certs/supabase-root-2021.crt` — a CA certificate is public by
   design — and selected with:

   ```
   DB_SSL_ROOT_CERT=certs/supabase-root-2021.crt
   ```

   Unset, the connection verifies against the system trust store, which is right
   for a provider with a publicly-rooted chain. There is deliberately no value
   that turns verification off.

5. Put the URI in `BackendAPI/.env` with the driver prefix, percent-encoding any
   special characters in the password:

   ```
   NEONDB_URL="postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
   ```

6. Build and check:

   ```bash
   python scripts/bootstrap_database.py
   python -m seed.seed_data
   ```

7. On Render, set **both** `NEONDB_URL` and `DB_SSL_ROOT_CERT` on the API
   service **and** the worker, then redeploy both. `docs/render-environment.md`
   lists the full variable set.

### Settings to refuse when creating the project

* **GitHub integration — leave it disconnected.** It is for Supabase's
  declarative schema workflow. This schema is owned by Alembic, there is no
  `supabase/` directory, and connecting it means two systems believing they own
  the schema plus a preview database per pull request drawing on the same
  allowance.
* **Data API — off.** It publishes a PostgREST API over the whole `public`
  schema for browser clients using `supabase-js`. Nothing here uses one: the
  three apps and the console all talk to FastAPI, which owns every authorisation
  decision on this platform. Leaving it on is a second door into the same 32
  tables with none of those checks in front of it.
* **Automatic RLS — off.** With no Data API there is nothing for it to protect,
  and RLS with no policies is a way for queries to start returning zero rows for
  reasons nobody can see.
* **Postgres type — Default, not OrioleDB.** It is alpha, it cannot be changed
  after creation, and it is a different storage engine — not something to gamble
  PostGIS on when 44 spatial calls decide which stores a customer can order
  from.

### After switching

* `alembic current` should report `e6b2c8d40f17`.
* Routine deploys target `f7e3b91c8d24` — the revision before the gated
  single-staff column drop. A freshly bootstrapped database is built from
  today's models, which no longer carry those columns, so the head is the honest
  stamp there; `--stamp-at f7e3b91c8d24` exists for a deployment that has not
  accepted the drop.
* The apps need no change. They talk to the API, and the API owns the database.

---

## Verifying a database is healthy

```bash
psql "$(grep -m1 '^NEONDB_URL' BackendAPI/.env | cut -d= -f2- | tr -d '"' \
  | sed 's|postgresql+asyncpg://|postgresql://|')" -c 'select postgis_version()'
```

A refusal naming a quota is the provider, not the application. Every endpoint
that touches data will be answering 500, and no code change will help.
