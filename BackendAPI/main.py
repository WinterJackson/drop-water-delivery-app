
from dotenv import load_dotenv

load_dotenv()

import os
import logging
from typing import Union
from fastapi import FastAPI
from pydantic import BaseModel
from routes import (
    vendor_routes, auth_routes, product_routes, cart_routes,
    query_routes, vendor_management_routes, deliverer_routes,
    websocket_routes, review_routes, sync_routes, sms_routes,
    favorites_routes, notification_routes, delivery_fee_routes, refund_routes,
    vendor_favorites_routes, saved_location_routes, wallet_routes
)
import models
from db.session import create_table
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
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
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
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

# Running the ARQ worker inside the API process means every uvicorn worker and
# every deployed instance runs its own copy of the cron schedule — the dispute
# sweep, the auto-cancel sweep and the GPS flush all fire N times per tick. In
# any environment with more than one instance that is both wasteful and unsafe.
# Production must run `arq worker.WorkerSettings` as its own process (see
# BackendAPI/README.md); set RUN_INLINE_WORKER=1 for a single-process dev machine.
RUN_INLINE_WORKER = os.getenv("RUN_INLINE_WORKER", "0").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from routes.websocket_routes import manager
    import asyncio

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
                logging.warning(
                    "ARQ worker started INSIDE the API process (RUN_INLINE_WORKER=1). "
                    "Never enable this with more than one API instance — cron jobs would run once per instance."
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

# --- F-011 FIX: Health Check Endpoint ---
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}

@app.get("/api/app-version", tags=["App Version"])
async def get_app_version():
    return {
        "min_version": "1.0.0",
        "ios_store_url": "https://apps.apple.com/app/drop/id123456789",
        "android_store_url": "https://play.google.com/store/apps/details?id=com.drop.app"
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

# Apply global payload compression (down to 500 bytes minimum to save processing overhead)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Trust Proxy Headers (Critical for Safaricom IP whitelisting on Render/Heroku)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Add Correlation ID Middleware
app.add_middleware(CorrelationIdMiddleware)

# Apply Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Expose Prometheus Metrics
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
from routes import admin_routes
app.include_router(admin_routes.router, prefix="/api/admin", tags=["Admin Dashboard"])

# --- Rider-facing Routes ---
from routes import deliverer_routes, rider_vendor_routes, deliverer_kyc_routes
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
app.include_router(sync_routes.router, prefix="/api/sync", tags=["Sync"])
app.include_router(sms_routes.router, prefix="/api/sms", tags=["SMS Fallback"])
app.include_router(wallet_routes.router)
from routes import contact_routes
app.include_router(contact_routes.router, prefix="/api", tags=["Contacts"])
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
