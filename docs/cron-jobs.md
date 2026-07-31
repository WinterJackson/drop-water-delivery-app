# Scheduled jobs (cron-job.org)

## The model

```
cron-job.org  ──POST /api/cron/{slug}──▶  FastAPI  ──enqueue──▶  ARQ worker
   (the clock)          (auth + lock)                             (the work)
```

cron-job.org owns the **schedule**. The API endpoint authenticates the call,
takes a per-job lock, and hands the task to ARQ. The worker still does the work.

The endpoint returns as soon as the job is queued — it does not wait for it.
cron-job.org allows about 30 seconds per request and a sweep over thousands of
rows does not fit; holding the connection open would make a slow job look like a
failed one.

### Why not ARQ's own scheduler

ARQ crons only tick while `arq worker.WorkerSettings` is running, alone and
healthy. If the worker sleeps, restarts, or is scaled to two replicas, the
schedule either stops with nothing reporting it or fires twice. For the
auto-cancel and refund sweeps that is the difference between a delayed refund and
one nobody ever notices. An external scheduler makes a missed run visible and
alertable.

The internal schedule is still there behind `ARQ_INTERNAL_CRON=1`, for a dev
machine with no public URL. **Never set it in an environment where cron-job.org
is also configured** — every sweep would run twice.

## Setup

### 1. Generate the secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set it as `CRON_SECRET` in the API environment (Render → Environment).

Without it the endpoints return **503** outside development rather than running
open — they cancel orders, move money and delete tokens, and no user is signed
in to authorise them.

### 2. Confirm it works

```bash
curl -s -H "X-Cron-Key: $CRON_SECRET" \
  https://vepo-backend.onrender.com/api/cron/jobs
```

Should list every slug. A 403 means the secret does not match; a 503 means it is
not set on the server.

On Render's free tier the service sleeps after ~15 minutes idle and a cold start
takes 30–60 seconds — longer than the cron timeout. The one-minute jobs keep it
awake in practice, but expect a failure alert on the first tick after any deploy
or idle period. If that noise is a problem, raise the timeout rather than
silencing the alerts.

### 3. Create the jobs

On [cron-job.org](https://cron-job.org) → **Create cronjob**, once per row:

| Slug | Schedule | Why this interval |
|---|---|---|
| `flush-gps-logs` | every 1 min | Drains buffered GPS points to Postgres. Live tracking goes over the WebSocket, so this is history only — the drain takes whatever has accumulated. |
| `resolve-bottle-rejections` | every 1 min | Disputes auto-resolve after a 3-minute cutoff; a minute of granularity is enough. |
| `process-refunds` | every 2 min | A customer waiting on money back is the most latency-sensitive sweep. |
| `reassign-unassigned-orders` | every 3 min | Re-offers orders the 20-second tiered dispatch failed to place. |
| `cancel-pending-orders` | every 5 min | Expires unpaid orders and releases their stock. |
| `check-push-receipts` | every 10 min | Receipts are only queued 15 minutes after a send, so anything faster mostly finds nothing due. |
| `stale-asset-monitor` | daily, 03:00 | Housekeeping; deliberately off-peak. |
| `evaluate-platinum-riders` | daily, 00:00 | Tier evaluation is a day-boundary calculation. |

For each job:

- **URL** — `https://vepo-backend.onrender.com/api/cron/<slug>`
- **Request method** — `POST` (GET is accepted too, for the free tier)
- **Headers** — `X-Cron-Key: <your CRON_SECRET>`
- **Timeout** — 30s
- **Notify on failure** — **on**. This is the entire point of using an external
  scheduler; without alerts you have moved the schedule out but kept the silence.

If your plan does not support custom headers, put the secret in the query string
instead: `https://vepo-backend.onrender.com/api/cron/<slug>?key=<CRON_SECRET>`. It is weaker —
URLs end up in access logs — so prefer the header where you can, and rotate the
secret if you have used the query form.

### 4. Keep the worker running

cron-job.org triggers the jobs; ARQ executes them. The worker still has to be up:

```bash
arq worker.WorkerSettings
```

If Redis is unreachable the endpoint runs the job inline instead, so a broken
queue degrades rather than stops. That path is a fallback, not the design — it
runs inside the HTTP request and can hit the scheduler's timeout on a big sweep.

## Operational notes

**Overlap.** Each job takes a Redis lock for up to 10 minutes. A second call
while one is running returns `{"status": "already_running"}` with 200, so
cron-job.org does not record it as a failure.

**Failures.** A job that raises returns **500**, which cron-job.org shows in its
history and alerts on. Anything that returns 200 genuinely got queued.

**Adding a job.** Write the task in `worker.py`, add it to
`WorkerSettings.functions`, then add a slug to `_job_table()` in
`routes/cron_routes.py`. `tests/test_cron_and_receipts.py` fails if a slug points
at a task the worker does not know about — which would otherwise enqueue jobs the
worker silently drops.

**Renaming a slug** silently stops that schedule: cron-job.org keeps calling the
old URL and gets a 404. Update both sides together.

## Push receipts

`check-push-receipts` is the second half of push delivery, and is new.

Sending a push returns a **ticket**, which only means Expo accepted the message.
Whether it reached the device is reported later in a **receipt**, fetched by
ticket id — and that is where `DeviceNotRegistered` (uninstalled app, rotated
token) normally appears. Handling ticket-level errors alone left dead tokens
attached to accounts indefinitely: the platform kept pushing to devices that no
longer existed, and on a shared device a previous account could keep receiving
notifications.

Ticket ids are parked in a Redis sorted set scored by due time (send + 15 min).
The sweep claims everything due, fetches the receipts in batches of 300, and
purges the tokens Expo reports as unregistered. Entries are removed *before* the
network call so two overlapping sweeps cannot both act on the same ticket; a
failed fetch re-parks them, and anything unresolved after 24 hours is dropped
rather than retried forever.

If Redis is unavailable, tickets are simply not recorded. Delivery is unaffected —
only the cleanup is skipped.
