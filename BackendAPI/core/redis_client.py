import redis.asyncio as redis
import os
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Upstash provides rediss:// (with two s) for TLS connections
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Create a connection pool to Upstash / Local Redis
# decode_responses=True automatically decodes byte strings to Python strings
try:
    redis_pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
except Exception as e:
    logger.error(f"Failed to initialize Redis connection pool: {e}")
    redis_pool = None

from slowapi import Limiter

redis_is_available = False
storage_uri = "memory://"
try:
    import redis as sync_redis
    sync_r = sync_redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1)
    sync_r.ping()
    storage_uri = REDIS_URL
    redis_is_available = True
except Exception:
    logger.warning("Redis not accessible for rate limiting, falling back to memory://")

# Global Redis-backed Rate Limiter.
#
# Keyed on the **authenticated subject**, not the client address — see
# `core/rate_limit.py` for why. On this platform an address is a mobile carrier's
# NAT pool shared by thousands of customers, so an address-keyed limit is a
# platform-wide budget wearing a per-user label.
#
# The default is the ceiling for one *account*, which is why it is generous: a
# customer opening the app fires a burst of parallel reads (profile, cart, active
# order, catalogue, notifications) and none of that is abuse. Unauthenticated
# callers still fall back to an address key and still meet this number, so an
# anonymous flood from one connection is bounded without the whole of Safaricom
# sharing one bucket.
from core.rate_limit import rate_limit_key

redis_limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=["300/minute"],
    storage_uri=storage_uri
)

def get_redis() -> Optional[redis.Redis]:
    if not redis_is_available:
        return None
    if not redis_pool:
        return None
    return redis.Redis(connection_pool=redis_pool)

_arq_pool = None

async def get_arq_pool():
    global _arq_pool
    if not _arq_pool:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            _arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
        except Exception as e:
            logger.error(f"Failed to initialize ARQ pool: {e}")
    return _arq_pool

async def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    if not r:
        return None
    try:
        val = await r.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.warning(f"Redis GET error for key '{key}': {e}")
    return None


import uuid
from datetime import datetime, date
from contextlib import asynccontextmanager

@asynccontextmanager
async def redis_lock(lock_key: str, timeout_seconds: int = 10):
    """
    Simple distributed lock using Redis setnx.
    Usage:
        async with redis_lock("my_lock") as acquired:
            if not acquired:
                # Handle lock failure
    """
    r = get_redis()
    if not r:
        # If Redis is down, we fail open (or closed, depending on requirements. Here we fail open to allow DB to handle it)
        yield True
        return

    # Generate a random token to ensure we only delete our own lock
    token = str(uuid.uuid4())
    try:
        acquired = await r.set(lock_key, token, ex=timeout_seconds, nx=True)
    except Exception as e:
        logger.warning(f"Redis lock acquisition failed (fallback to open): {e}")
        acquired = True
    
    try:
        yield acquired
    finally:
        if acquired:
            # Only release if the token matches (Lua script for atomicity)
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                await r.eval(script, 1, lock_key, token)
            except Exception as e:
                logger.error(f"Error releasing Redis lock '{lock_key}': {e}")

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    r = get_redis()
    if not r:
        return False
    try:
        val_str = json.dumps(value, cls=CustomJSONEncoder)
        await r.setex(key, ttl_seconds, val_str)
        return True
    except Exception as e:
        logger.warning(f"Redis SET error for key '{key}': {e}")
    return False

