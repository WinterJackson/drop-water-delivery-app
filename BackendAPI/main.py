
from dotenv import load_dotenv

load_dotenv()

import os
import logging
from fastapi import FastAPI
from routes import (
    vendor_routes, auth_routes, product_routes, cart_routes,
    query_routes, vendor_management_routes, deliverer_routes,
    websocket_routes, review_routes, sms_routes,
    favorites_routes, notification_routes, delivery_fee_routes, refund_routes,
    vendor_favorites_routes, saved_location_routes, wallet_routes
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        return response

# --- Observability Initialization ---
import sentry_sdk
from prometheus_fastapi_instrumentator import Instrumentator
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id

sentry_dsn = os.getenv("SENTRY_DSN")

#: Paths whose traces are worth keeping whatever the sample rate says. Money and
#: order state: the transactions where "it was slow that one time" is a question
#: somebody will actually need answered, months later, about one order.
_ALWAYS_TRACE = (
    "/api/cart/mpesa_payment",
    "/api/wallet/withdraw",
    "/api/payouts",
    "/api/payments",
    "/api/refunds",
    "/api/rider/complete",
    "/api/sms",
)

#: Paths that are pure noise in a trace view and are hit constantly.
_NEVER_TRACE = ("/health", "/ready", "/metrics")


def _traces_sampler(context: dict) -> float:
    """Sample by what the request *is*, not uniformly.

    `traces_sample_rate=1.0` with `profiles_sample_rate=1.0` was correct for a
    platform with no traffic and ruinous with any: a sampling profiler attached to
    every request, a span tree sent for every one, latency on the request path and
    a bill that scales linearly with success. Uniform sampling at a low rate is
    the usual fix and it throws away the traces that matter — the checkout that
    took nine seconds is rare *because* it is the interesting one.
    """
    path = (context.get("asgi_scope") or {}).get("path") or ""
    if any(path.startswith(p) for p in _NEVER_TRACE):
        return 0.0
    if any(path.startswith(p) for p in _ALWAYS_TRACE):
        return 1.0
    return _DEFAULT_TRACES_RATE


def _rate_from_env(name: str, production_default: float) -> float:
    """Full sampling in development, a configured fraction anywhere else."""
    raw = os.getenv(name)
    if raw is not None:
        try:
            return min(max(float(raw), 0.0), 1.0)
        except ValueError:
            logging.warning("%s is not a number; using the default", name)
    return 1.0 if os.getenv("ENV", "development") == "development" else production_default


_DEFAULT_TRACES_RATE = _rate_from_env("SENTRY_TRACES_SAMPLE_RATE", 0.05)

if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sampler=_traces_sampler,
        # Profiling is the expensive half — it attaches a sampling profiler to the
        # running request — and it is a fraction *of traced* transactions, so the
        # two rates multiply.
        profiles_sample_rate=_rate_from_env("SENTRY_PROFILES_SAMPLE_RATE", 0.1),
    )

# --- Logging Configuration ---
# Add correlation ID to log format
log_format = "%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)

# Add a filter to inject correlation ID into all log records
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id.get() or "no-req-id"
        return True

logger = logging.getLogger(__name__)
# Add the filter to the root logger
for handler in logging.root.handlers:
    handler.addFilter(CorrelationIdFilter())

import re
class TokenRedactFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            new_args = list(record.args)
            for i, arg in enumerate(new_args):
                if isinstance(arg, str) and "token=" in arg:
                    new_args[i] = re.sub(r"token=[^&\s'\"]+", "token=***", arg)
            record.args = tuple(new_args)
        return True

# Apply the filter to the uvicorn.access logger to prevent token leaking in terminal
logging.getLogger("uvicorn.access").addFilter(TokenRedactFilter())

from contextlib import asynccontextmanager

# Running the ARQ worker inside the API process.
#
# The hazard is the **cron schedule**, not the queue: ARQ pulls each queued job
# to exactly one worker, so several consumers is safe, while an in-process cron
# fires once per instance — the dispute sweep, the auto-cancel sweep and the GPS
# flush all N times per tick.
#
# This deployment's schedule is external (cron-job.org calls `/api/cron/{slug}`)
# and `ARQ_INTERNAL_CRON` is unset, so `WorkerSettings.cron_jobs` is empty and an
# inline worker only consumes the queue. That makes `RUN_INLINE_WORKER=1` a
# legitimate single-service setup, not merely a dev shortcut — see
# `docs/render-environment.md`. Setting `ARQ_INTERNAL_CRON` **and**
# `RUN_INLINE_WORKER` together on a multi-instance service is the combination to
# avoid.
RUN_INLINE_WORKER = os.getenv("RUN_INLINE_WORKER", "0").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from routes.websocket_routes import manager
    import asyncio

    # Before anything is served: does this database have the columns the mapper
    # is about to select? A deploy can land ahead of its schema — they are not
    # carried together — and one missing column is a 500 on every request that
    # touches the table, not a degraded corner of the product. Raising here means
    # the instance never passes its health check and the previous release keeps
    # serving, so the deploy fails instead of the platform.
    from db.schema_guard import assert_models_match_database
    from db.session import engine

    await assert_models_match_database(engine)

    # Start WebSocket PubSub
    await manager.start_pubsub()

    from core.redis_client import get_redis
    import logging

    arq_task = None
    if RUN_INLINE_WORKER:
        r = get_redis()
        if r:
            try:
                await r.ping()
                from arq.worker import create_worker
                from worker import WorkerSettings

                arq_worker = create_worker(WorkerSettings)
                arq_task = asyncio.create_task(arq_worker.main())

                def _report_worker_exit(task: "asyncio.Task") -> None:
                    """A background task that dies takes the queue with it, silently.

                    Without this the exception sits in the task object until
                    shutdown awaits it — so broadcast campaigns, push sends and
                    every sweep simply stop being processed while the API keeps
                    answering requests normally, and nothing in the log says why.
                    """
                    if task.cancelled():
                        return
                    error = task.exception()
                    if error is not None:
                        logging.error(
                            "INLINE_ARQ_WORKER_DIED: background jobs are no longer being "
                            "processed in this instance. Restart the service.",
                            exc_info=error,
                        )

                arq_task.add_done_callback(_report_worker_exit)

                if os.getenv("ARQ_INTERNAL_CRON", "0").lower() in ("1", "true", "yes"):
                    logging.warning(
                        "RUN_INLINE_WORKER=1 with ARQ_INTERNAL_CRON=1: every sweep will "
                        "run once per API instance. Safe only on a single instance."
                    )
                logging.warning(
                    "ARQ worker started INSIDE the API process (RUN_INLINE_WORKER=1). "
                    "Queued jobs are consumed here; the schedule stays external."
                )
            except Exception as e:
                logging.warning(f"Redis not reachable. Skipping inline ARQ worker. Error: {e}")
        else:
            logging.warning("Redis not configured. Skipping inline ARQ worker.")
    else:
        logging.info(
            "Inline ARQ worker disabled. Run background jobs with: arq worker.WorkerSettings"
        )

    yield

    # Graceful shutdown
    if manager.pubsub_task:
        manager.pubsub_task.cancel()

    if arq_task:
        arq_task.cancel()
        try:
            await arq_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="Drop Water Delivery API", version="1.0.0", lifespan=lifespan)

# --- Health: liveness and readiness are different questions ---
@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness. Is this process running at all?

    Deliberately touches nothing. A liveness probe that consults the database
    restarts a healthy replica every time the database hiccups, which converts a
    brief dependency blip into a rolling outage of the whole fleet.
    """
    return {"status": "ok"}


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness. Can this replica actually serve a request?

    This is the one a load balancer should poll. `/health` answered `ok` from a
    replica whose connection pool was exhausted or whose Redis had gone, so it
    stayed in rotation serving 500s — the failure mode a health check exists to
    prevent.

    Redis being down is reported but is **not** disqualifying: it costs caching,
    rate limiting precision and cross-replica WebSocket fan-out, all of which
    degrade rather than break. A database that cannot answer `SELECT 1` is
    disqualifying, because nothing on this platform works without it.
    """
    from sqlalchemy import text as _text

    from db.session import AsyncSessionLocal

    checks: dict[str, str] = {}
    ready = True

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(_text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"unavailable: {type(exc).__name__}"
        ready = False

    try:
        from core.redis_client import get_redis

        r = get_redis()
        if r is None:
            checks["redis"] = "not configured"
        else:
            await r.ping()
            checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"unavailable: {type(exc).__name__}"

    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not ready", "checks": checks},
    )

#: The three apps, by the Android package each one actually ships as.
#:
#: This used to be one answer for all three, naming `com.drop.app` — a package
#: that does not exist on this platform and never has. The apps are
#: `com.drop.customer`, `com.drop.rider` and `com.drop.vendor`, so the "Update
#: Now" button on the only screen a blocked user can reach opened a Play Store
#: page for nothing. A forced update that cannot be completed is worse than no
#: forced update: it is an uninstall.
#:
#: One floor for three apps was wrong for a second reason. They are built and
#: released separately and their versions move independently, so requiring 1.4.0
#: because the customer app changed its checkout would have locked every rider
#: out of a build that was current.
_APP_PACKAGES = {
    "customer": "com.drop.customer",
    "rider": "com.drop.rider",
    "vendor": "com.drop.vendor",
}


@app.get("/api/app-version", tags=["App Version"])
async def get_app_version(app: str = "customer"):
    """The lowest version of `app` that may still be used, and where to update.

    Public and unauthenticated on purpose: a build too old to sign in still has
    to be told to update, and this is the one call it can make.

    The floor is an environment variable rather than a `Platform_Settings` row,
    which is the opposite of what a business figure would be. Two reasons, both
    deliberate. It is a release decision, not a trading one — it changes when a
    build ships, alongside the deploy that made the old one unusable. And it has
    to be answerable when the settings cache is degraded, because the situation
    in which you most need to force an upgrade is the one where something is
    already wrong. `CRON_SECRET`, `METRICS_TOKEN` and `PUBLIC_ASSET_BASE_URL`
    sit here for the same reason.

    An unknown `app` falls back to the customer's answer rather than erroring:
    this endpoint's job is to avoid blocking a client, so an unrecognised
    parameter must not be the thing that blocks one.
    """
    key = app if app in _APP_PACKAGES else "customer"
    package = _APP_PACKAGES[key]

    # Per app, so one can be forced forward without touching the other two.
    # Unset means "no floor" — 0.0.0 is below every real build, so an
    # unconfigured platform never locks anybody out by accident.
    min_version = os.getenv(f"MIN_APP_VERSION_{key.upper()}", "0.0.0")

    ios_id = os.getenv(f"IOS_APP_ID_{key.upper()}")

    return {
        "app": key,
        "min_version": min_version,
        # Only offered once there is a real App Store listing. A placeholder id
        # is a link to somebody else's app.
        "ios_store_url": f"https://apps.apple.com/app/id{ios_id}" if ios_id else None,
        "android_store_url": f"https://play.google.com/store/apps/details?id={package}",
    }

# --- F-012 FIX: Global Exception Handler (prevents stack trace leaks) ---
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: FastAPIRequest, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    if sentry_dsn:
        sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: FastAPIRequest, exc: RequestValidationError):
    logger.warning(f"422 on {request.method} {request.url.path}: {exc.errors()} | Body: {exc.body}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)[:500]},
    )

# --- Rate Limiter ---
from core.redis_client import redis_limiter
app.state.limiter = redis_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Resolves *who* the limit counts against, and must run before the check above
# consults it. Starlette runs middleware outermost-first in reverse registration
# order, so being added after `SlowAPIMiddleware` is what puts it earlier in the
# request. Swapping these two lines silently reverts every limit to the carrier
# NAT address it used to key on — `tests/test_rate_limiting.py` fails the build
# if the order changes.
from core.rate_limit import RateLimitKeyMiddleware

app.add_middleware(RateLimitKeyMiddleware)

# --- CORS Configuration ---
_env_mode = os.getenv("ENV", "development")
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if _raw_origins:
    ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
elif _env_mode == "development":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = []  # No wildcard in production — must be explicit

# `allow_origins=["*"]` together with `allow_credentials=True` is rejected by
# every browser, so the combination silently disables CORS instead of relaxing
# it. Credentials are only meaningful for an explicit origin allow-list; the
# mobile clients send a bearer token, not cookies, so dropping them in the
# wildcard case costs nothing.
_allow_credentials = "*" not in ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Conditional requests. Registered *before* GZip so it runs inside it and hashes
# the uncompressed body — a validator that depended on whether the client sent
# `Accept-Encoding` would give the same data two different tags.
from core.conditional import ETagMiddleware

app.add_middleware(ETagMiddleware)

# Apply global payload compression (down to 500 bytes minimum to save processing overhead)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Trust Proxy Headers (Critical for Safaricom IP whitelisting on Render/Heroku)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Add Correlation ID Middleware
app.add_middleware(CorrelationIdMiddleware)

# Apply Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Expose Prometheus Metrics.
#
# Behind a bearer token unless one is deliberately not configured. `/metrics`
# published route names, per-route latencies and request volumes on the public
# origin to anybody who asked — which is a map of the platform, a live read on how
# much business it is doing, and a free oracle for anyone probing it. Scrapers
# send a static token; a browser gets a 404, not a 401, because confirming the
# endpoint exists is itself part of what was being given away.
_METRICS_TOKEN = os.getenv("METRICS_TOKEN")


class MetricsGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics" and _METRICS_TOKEN:
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {_METRICS_TOKEN}"
            # Constant-time: this compares a secret, and the endpoint is public.
            import hmac

            if not hmac.compare_digest(supplied, expected):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return await call_next(request)


if not _METRICS_TOKEN:
    logging.warning(
        "METRICS_TOKEN is not set — /metrics is publicly readable. Set it in any "
        "deployment reachable from the internet."
    )

app.add_middleware(MetricsGuardMiddleware)
Instrumentator().instrument(app).expose(app)

# --- Customer-facing Routes ---
app.include_router(vendor_routes.router, prefix="/api")
app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(product_routes.router, prefix="/api")
app.include_router(cart_routes.router, prefix="/api/cart")
app.include_router(query_routes.router, prefix="/api")
app.include_router(delivery_fee_routes.router, prefix="/api", tags=["Delivery Fee"])
app.include_router(saved_location_routes.router, prefix="/api/auth", tags=["Saved Locations"])

# --- Vendor-facing Routes ---
app.include_router(vendor_management_routes.router, prefix="/api/vendor", tags=["Vendor Management"])
from routes import vendor_rider_routes
app.include_router(vendor_rider_routes.router, prefix="/api/vendor", tags=["Vendor Rider Registry"])

# --- Admin Routes ---
from routes import (
    admin_routes,
    admin_analytics_routes,
    admin_bottle_routes,
    admin_catalogue_routes,
    admin_config_routes,
    admin_finance_routes,
    admin_fleet_routes,
    admin_geo_routes,
    admin_orders_routes,
    admin_people_routes,
    admin_review_routes,
    admin_support_routes,
)
app.include_router(admin_routes.router, prefix="/api/admin", tags=["Admin Dashboard"])
# Split by concern rather than one growing module, but all under the same prefix
# so `tests/test_admin_rbac.py` can assert that everything below /api/admin is
# gated, and so the console has one base URL.
app.include_router(admin_analytics_routes.router, prefix="/api/admin", tags=["Admin Analytics"])
app.include_router(admin_people_routes.router, prefix="/api/admin", tags=["Admin People"])
app.include_router(admin_orders_routes.router, prefix="/api/admin", tags=["Admin Orders"])
app.include_router(admin_config_routes.router, prefix="/api/admin", tags=["Admin Configuration"])
app.include_router(admin_geo_routes.router, prefix="/api/admin", tags=["Admin Map"])
app.include_router(admin_support_routes.router, prefix="/api/admin", tags=["Admin Support"])
app.include_router(admin_finance_routes.router, prefix="/api/admin", tags=["Admin Finance"])
app.include_router(admin_catalogue_routes.router, prefix="/api/admin", tags=["Admin Catalogue"])
app.include_router(admin_bottle_routes.router, prefix="/api/admin", tags=["Admin Bottles"])
app.include_router(admin_review_routes.router, prefix="/api/admin", tags=["Admin Reviews"])
app.include_router(admin_fleet_routes.router, prefix="/api/admin", tags=["Admin Fleet"])

# App-facing support intake. Without this the ticket queue is an inbox
# nobody can write to.
from routes import support_routes
app.include_router(support_routes.router, prefix="/api", tags=["Support"])

# --- Rider-facing Routes ---
from routes import rider_vendor_routes, deliverer_kyc_routes
app.include_router(deliverer_routes.router, prefix="/api/rider", tags=["Rider"])
app.include_router(rider_vendor_routes.router, prefix="/api/rider", tags=["Rider Vendor Reg"])
app.include_router(deliverer_kyc_routes.router)

# --- Unification Routes ---
app.include_router(review_routes.router, prefix="/api/reviews", tags=["Reviews"])
app.include_router(favorites_routes.router, prefix="/api/favorites", tags=["Favorites"])
app.include_router(vendor_favorites_routes.router, prefix="/api/vendor-favorites", tags=["Vendor Favorites"])
app.include_router(notification_routes.router, prefix="/api/notifications", tags=["Notifications"])
# Legacy payout endpoints stay removed — cashouts go through /api/wallet/withdraw.
# Only Safaricom's B2C callbacks are mounted: they reconcile those withdrawals, and
# dropping the whole module left them unrouted while money was still going out.
from routes import payout_routes
app.include_router(payout_routes.callback_router, prefix="/api/payouts", tags=["Payout Callbacks"])
app.include_router(refund_routes.router, prefix="/api/refunds", tags=["Refunds"])
app.include_router(sms_routes.router, prefix="/api/sms", tags=["SMS Fallback"])
app.include_router(wallet_routes.router)
from routes import contact_routes
app.include_router(contact_routes.router, prefix="/api", tags=["Contacts"])
# Returning a bottle deposit. One module, two surfaces — the customer books and
# confirms, the rider claims and confirms — because the money only moves when
# the two counts agree, and splitting that across two routers is how they come
# to disagree about what the flow is.
from routes import bottle_return_routes
app.include_router(bottle_return_routes.router, prefix="/api", tags=["Bottle Returns"])
from routes import payment_routes
app.include_router(payment_routes.router, prefix="/api/payments", tags=["Payments"])
from routes import maps_routes
app.include_router(maps_routes.router, prefix="/api/maps", tags=["Maps"])

# Scheduled work is triggered by cron-job.org, not by ARQ's internal scheduler —
# see routes/cron_routes.py and docs/cron-jobs.md. Guarded by CRON_SECRET.
from routes import cron_routes
app.include_router(cron_routes.router, prefix="/api/cron", tags=["Scheduled Jobs"])


# --- WebSocket Routes ---
app.include_router(websocket_routes.router, tags=["WebSocket"])
