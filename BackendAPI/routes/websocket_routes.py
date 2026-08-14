import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, List, Optional
from core.security import verify_clerk_token
import asyncio
import time

logger = logging.getLogger(__name__)

router = APIRouter()


from core.redis_client import get_redis

#: Statuses an order can never move out of.
#:
#: Kept in step with `order_service.apply_status_transition`, which refuses a move
#: out of any of these with a 409. Nothing follows one, so every per-order
#: resource this module holds can be released the moment one arrives.
TERMINAL_ORDER_STATUSES = frozenset({"delivered", "cancelled", "rejected"})

#: Ceiling on each order→entity mapping cache.
#:
#: These were plain dicts that were only ever written to. Connections are removed
#: on disconnect; the *mappings* never were, so `order_rider_map[order_id]` was
#: written when an order was first broadcast and then survived that order's
#: delivery, its cancellation, and the rest of the process's life. A replica that
#: stays up for a week accumulated an entry for every order it had ever seen a
#: message about — a leak whose size is proportional to platform volume, on the
#: process that also holds every live WebSocket. The symptom is the API being
#: OOM-killed during the busiest hour it has ever had, taking every delivery's
#: socket with it.
#:
#: They are caches. Redis is the authority (`resolve_order_rider` reads it, the
#: database backs that), so evicting an entry costs one lookup and nothing else.
_MAPPING_CACHE_MAX = 5000


class _BoundedMap:
    """A dict that forgets its oldest entries instead of growing forever.

    Insertion-ordered, which Python guarantees, so the first key is the
    least-recently *inserted*. That is the right eviction order here: an order's
    mapping stops being interesting once the order is delivered, and orders are
    delivered roughly in the order they were created.
    """

    def __init__(self, maximum: int = _MAPPING_CACHE_MAX) -> None:
        self._data: Dict[str, str] = {}
        self._maximum = maximum

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __setitem__(self, key: str, value: str) -> None:
        if key not in self._data and len(self._data) >= self._maximum:
            for oldest in list(self._data.keys())[: max(1, self._maximum // 10)]:
                self._data.pop(oldest, None)
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def pop(self, key: str, default=None):
        return self._data.pop(key, default)


class ConnectionManager:
    """WebSocket connections for live delivery tracking, fanned out over Redis.

    Two properties matter more than anything else in here, and both are about
    what happens per *GPS ping* rather than per order:

    1. **A ping is matched by lookup, not by search.** `rider_tracked_orders` is
       the reverse of `order_rider_map`, so relaying a rider's location touches
       only that rider's own orders. It used to walk every tracked order on the
       worker and discard almost all of them — quadratic in live deliveries, and
       worse with every replica added rather than better.
    2. **Nothing in the send path awaits a lookup.** The mapping is resolved when
       a tracker connects and when a status broadcast arrives. A miss inside the
       fan-out loop meant a Redis round trip — or a database query — *per tracked
       order, per ping*, and a cold replica after a deploy hits that on every
       single one.
    """

    def __init__(self):
        # rider_id -> WebSocket (rider sending location)
        self.rider_connections: Dict[str, WebSocket] = {}
        # order_id -> list of WebSockets (customers watching)
        self.tracking_connections: Dict[str, List[WebSocket]] = {}
        self.order_rider_map = _BoundedMap()
        self.order_vendor_map = _BoundedMap()
        #: rider_id -> the order ids this worker is tracking for that rider. The
        #: reverse of `order_rider_map`, and the reason the fan-out is a lookup.
        self.rider_tracked_orders: Dict[str, set] = {}
        # rider_id -> latest location. Bounded by connected riders: popped in
        # `disconnect_rider`, which the socket handler calls in a `finally`.
        self.rider_locations: Dict[str, dict] = {}

        # Entity Order Connections (Real-Time State Tracking)
        self.vendor_orders: Dict[str, List[WebSocket]] = {}
        self.customer_orders: Dict[str, List[WebSocket]] = {}
        self.rider_orders: Dict[str, List[WebSocket]] = {}

        self.pubsub_task: Optional[asyncio.Task] = None

    async def start_pubsub(self):
        """Starts the Redis Pub/Sub listener for this specific worker instance."""
        r = get_redis()
        if not r:
            logger.warning("Redis not available. WebSockets will fallback to local-only mode (Not horizontally scalable).")
            return
            
        pubsub = r.pubsub()
        try:
            await pubsub.subscribe("ws_events")
        except Exception as e:
            logger.warning(f"Redis connection failed. WebSockets will fallback to local-only mode. Error: {e}")
            return
        
        self.pubsub_task = asyncio.create_task(self._listen_to_pubsub(pubsub))
        logger.info("Redis Pub/Sub WebSocket listener initialized on this worker.")

    async def _listen_to_pubsub(self, pubsub):
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    action = data.get("internal_action")
                    payload = data.get("payload", {})
                    
                    if action == "broadcast_order_update":
                        await self._local_broadcast_order_update(
                            data.get("vendor_id"),
                            data.get("customer_id"),
                            data.get("deliverer_id"),
                            payload
                        )
                    elif action == "broadcast_to_riders":
                        await self._local_broadcast_to_riders(
                            data.get("rider_ids", []),
                            payload
                        )
                    elif action == "update_rider_location":
                        await self._local_update_rider_location(
                            data.get("rider_id"),
                            payload
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis Pub/Sub WebSocket listener error: {e}", exc_info=True)

    async def connect_entity(self, entity_type: str, entity_id: str, websocket: WebSocket):
        await websocket.accept()
        target_dict = getattr(self, f"{entity_type}_orders", None)
        if target_dict is not None:
            if entity_id not in target_dict:
                target_dict[entity_id] = []
            target_dict[entity_id].append(websocket)
            logger.info(f"{entity_type.capitalize()} {entity_id} connected for order updates.")

    def disconnect_entity(self, entity_type: str, entity_id: str, websocket: WebSocket):
        target_dict = getattr(self, f"{entity_type}_orders", None)
        if target_dict is not None and entity_id in target_dict:
            try:
                target_dict[entity_id].remove(websocket)
                if not target_dict[entity_id]:
                    del target_dict[entity_id]
            except ValueError as e:
                logger.warning(f"Failed to remove websocket for {entity_type} {entity_id}: {e}")

    async def broadcast_order_update(self, vendor_id: str, customer_id: str, deliverer_id: str, payload: dict):
        """Publishes to Redis instead of only local memory."""
        r = get_redis()
        if r:
            message = {
                "internal_action": "broadcast_order_update",
                "vendor_id": vendor_id,
                "customer_id": customer_id,
                "deliverer_id": deliverer_id,
                "payload": payload
            }
            await r.publish("ws_events", json.dumps(message))
        else:
            await self._local_broadcast_order_update(vendor_id, customer_id, deliverer_id, payload)

    async def _local_broadcast_order_update(self, vendor_id: str, customer_id: str, deliverer_id: str, payload: dict):
        order_id = payload.get("order_id")
        if order_id:
            if deliverer_id:
                self.map_order_to_rider(order_id, deliverer_id)
            if vendor_id:
                self.order_vendor_map[order_id] = vendor_id

        mapping = {
            "vendor": vendor_id,
            "customer": customer_id,
            "rider": deliverer_id
        }
        for entity_type, entity_id in mapping.items():
            if not entity_id:
                continue
            target_dict = getattr(self, f"{entity_type}_orders", None)
            if target_dict and str(entity_id) in target_dict:
                for ws in target_dict[str(entity_id)]:
                    try:
                        await ws.send_json(payload)
                    except Exception as e:
                        logger.error(f"Failed broadcasting WS locally to {entity_type} {entity_id}: {e}")

        # Release *after* delivering the message, so the parties watching still
        # receive the one that says the order is finished. Terminal is terminal —
        # `apply_status_transition` guarantees nothing follows — so from here the
        # mapping is only ever a memory cost.
        #
        # Both keys are read because the twelve broadcast sites do not agree on
        # one: most send `status`, a few send `order_status`. Reading only the key
        # this module happened to be written against would make the release fire
        # for some cancellations and not others — the kind of half-working cleanup
        # that looks fine in a test and leaks in production.
        if order_id:
            status = payload.get("status") or payload.get("order_status")
            if status in TERMINAL_ORDER_STATUSES:
                self.release_order(str(order_id))

    async def broadcast_to_riders(self, rider_ids: List[str], payload: dict):
        """Publishes Trip Radar/Dispatch payloads to Redis."""
        r = get_redis()
        if r:
            message = {
                "internal_action": "broadcast_to_riders",
                "rider_ids": rider_ids,
                "payload": payload
            }
            await r.publish("ws_events", json.dumps(message))
        else:
            await self._local_broadcast_to_riders(rider_ids, payload)

    async def _local_broadcast_to_riders(self, rider_ids: List[str], payload: dict):
        for r_id in rider_ids:
            if str(r_id) in self.rider_orders:
                for ws in self.rider_orders[str(r_id)]:
                    try:
                        await ws.send_json(payload)
                    except Exception as e:
                        logger.error(f"Failed broadcasting WS to specific rider {r_id}: {e}")

    async def connect_rider(self, rider_id: str, websocket: WebSocket):
        await websocket.accept()
        self.rider_connections[rider_id] = websocket
        logger.info(f"Rider {rider_id} connected via WebSocket")

    def disconnect_rider(self, rider_id: str):
        self.rider_connections.pop(rider_id, None)
        self.rider_locations.pop(rider_id, None)
        logger.info(f"Rider {rider_id} disconnected")

    async def connect_tracker(self, order_id: str, websocket: WebSocket):
        await websocket.accept()
        if order_id not in self.tracking_connections:
            self.tracking_connections[order_id] = []
        self.tracking_connections[order_id].append(websocket)
        # Resolve the rider up front so the very first GPS packet is relayed,
        # rather than waiting for an unrelated order-status broadcast to populate
        # the mapping.
        await self.resolve_order_rider(order_id)
        logger.info(f"Tracker connected for order {order_id}")

    def disconnect_tracker(self, order_id: str, websocket: WebSocket):
        if order_id in self.tracking_connections:
            try:
                self.tracking_connections[order_id].remove(websocket)
                if not self.tracking_connections[order_id]:
                    del self.tracking_connections[order_id]
                    # Nobody on this worker is watching this order any more, so it
                    # must leave the reverse index — otherwise the rider's pings
                    # keep resolving to an order with no listeners, which is the
                    # slow leak the index would otherwise reintroduce.
                    self._unlink_order(order_id, self.order_rider_map.get(order_id))
            except ValueError:
                pass

    async def update_rider_location(self, rider_id: str, location: dict):
        r = get_redis()
        if r:
            message = {
                "internal_action": "update_rider_location",
                "rider_id": rider_id,
                "payload": location
            }
            await r.publish("ws_events", json.dumps(message))
        else:
            await self._local_update_rider_location(rider_id, location)

    async def _local_update_rider_location(self, rider_id: str, location: dict):
        self.rider_locations[rider_id] = location

        # Fan out to this rider's own orders, by lookup.
        #
        # This used to iterate `self.tracking_connections` in full — every tracked
        # order on the worker, for every ping from every rider on the platform —
        # and `await` a Redis or database resolution inside that loop whenever the
        # mapping was missing. At 1,200 concurrent deliveries that is quadratic
        # work per ping, and a replica that has just started has *no* mappings, so
        # the first ping pays a round trip per tracked order.
        #
        # The reverse index is maintained by `map_order_to_rider` and released by
        # `disconnect_tracker` / `release_order`, so this is a set lookup and the
        # send path never blocks on I/O it could have done earlier.
        for order_id in list(self.rider_tracked_orders.get(rider_id, ())):
            if order_id not in self.tracking_connections:
                # The last watcher left between the index write and here.
                self._unlink_order(order_id, rider_id)
                continue

            payload = {"rider_id": rider_id, "location": location, "order_id": order_id}
            # Include the coordinates at the top level too: older clients read
            # `data.lat` / `data.lng` directly.
            if isinstance(location, dict):
                if location.get("lat") is not None:
                    payload["lat"] = location["lat"]
                if location.get("lng") is not None:
                    payload["lng"] = location["lng"]

            for ws in list(self.tracking_connections.get(order_id, [])):
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Dropping dead tracker socket for order %s: %s", order_id, e)
                    self.disconnect_tracker(order_id, ws)

            # Broadcast to the vendor of this order
            vendor_id = self.order_vendor_map.get(order_id)
            if vendor_id and str(vendor_id) in self.vendor_orders:
                for ws in list(self.vendor_orders[str(vendor_id)]):
                    try:
                        await ws.send_json({
                            "action": "RIDER_LOCATION",
                            "rider_id": rider_id,
                            "location": location,
                            "order_id": order_id
                        })
                    except Exception as e:
                        logger.warning("Dropping dead vendor socket for %s: %s", vendor_id, e)
                        self.disconnect_entity("vendor", str(vendor_id), ws)

    async def resolve_order_rider(self, order_id: str) -> Optional[str]:
        """Which rider is serving this order? Redis first, database as fallback.

        This mapping used to live only in per-process memory and was populated as
        a side effect of order-status broadcasts. Any worker that had not seen
        such a broadcast — a fresh instance after a deploy, or one that a customer
        connected to before the next status change — silently dropped every GPS
        update instead of relaying it.
        """
        r = get_redis()
        if r:
            try:
                cached = await r.get(f"order_rider_map:{order_id}")
                if cached:
                    rider_id = cached.decode() if isinstance(cached, bytes) else str(cached)
                    # Through `map_order_to_rider`, not a bare assignment: that is
                    # the only thing that maintains the reverse index, and a
                    # mapping learned from Redis has to reach it too or the very
                    # first tracker on a fresh replica is invisible to the fan-out.
                    self.map_order_to_rider(order_id, rider_id)
                    return rider_id
            except Exception as e:
                logger.warning("Redis lookup failed for order_rider_map:%s — %s", order_id, e)

        try:
            from uuid import UUID as _UUID
            from dependencies.dependencies import get_db_session
            from models.order_model import Order

            async with get_db_session() as session:
                order = await session.get(Order, _UUID(str(order_id)))
                if order and order.deliverer_id:
                    rider_id = str(order.deliverer_id)
                    self.map_order_to_rider(order_id, rider_id)
                    if order.vendor_id:
                        self.order_vendor_map[order_id] = str(order.vendor_id)
                    return rider_id
        except Exception as e:
            logger.warning("DB lookup failed resolving rider for order %s: %s", order_id, e)

        return None

    def map_order_to_rider(self, order_id: str, rider_id: str):
        previous = self.order_rider_map.get(order_id)
        if previous and previous != rider_id:
            # Reassignment: a rider dropped the order and another took it. Without
            # this the old rider keeps relaying their position to the customer
            # watching an order they are no longer carrying.
            self._unlink_order(order_id, previous)

        self.order_rider_map[order_id] = rider_id
        self.rider_tracked_orders.setdefault(rider_id, set()).add(order_id)

        # Also persist this map to Redis so other workers know. Fire-and-forget,
        # and guarded: this is a synchronous method, so a caller outside a running
        # loop would otherwise take a `RuntimeError` from the *cache write* and
        # lose the mapping it had already resolved correctly.
        r = get_redis()
        if r:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            asyncio.create_task(r.setex(f"order_rider_map:{order_id}", 86400, rider_id))

    def _unlink_order(self, order_id: str, rider_id: Optional[str]) -> None:
        """Drop one order from the reverse index, and the rider's entry if empty."""
        if not rider_id:
            return
        orders = self.rider_tracked_orders.get(rider_id)
        if not orders:
            return
        orders.discard(order_id)
        if not orders:
            self.rider_tracked_orders.pop(rider_id, None)

    def release_order(self, order_id: str) -> None:
        """Forget an order entirely. Called when it reaches a terminal status.

        Nothing more will happen to a delivered or cancelled order, so holding its
        rider and vendor mapping is pure accumulation. The bounded maps make that
        survivable; releasing on the event that makes it certain makes it correct,
        and keeps the working set the size of the *live* platform rather than of
        everything the replica has ever seen.
        """
        rider_id = self.order_rider_map.pop(order_id, None)
        self._unlink_order(order_id, rider_id)
        self.order_vendor_map.pop(order_id, None)


manager = ConnectionManager()


# ── F-003 FIX: WebSocket JWT Authentication Helper ────────────────────────
async def _authenticate_ws(websocket: WebSocket, token: Optional[str]) -> Optional[dict]:
    """Verify JWT token for WebSocket connections. Returns payload or None."""
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return None
    try:
        payload = await verify_clerk_token(token)
        if not payload:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return None
        return payload
    except Exception as e:
        logger.warning(f"WebSocket authentication failed: {e}", exc_info=True)
        await websocket.close(code=1008, reason="Authentication failed")
        return None


def _token_expired(payload: dict) -> bool:
    """True once the token that opened this socket has passed its `exp`.

    A REST call re-presents its token on every request, so expiry is enforced
    continuously. A socket presents one exactly once, at connect, and then stays
    open for hours — a rider signed out or deactivated mid-shift kept streaming.
    """
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        # Verification already requires `exp` (python-jose rejects tokens whose
        # `exp` has passed), so its absence means an unexpected token shape.
        return True
    return time.time() >= float(exp)


async def _close_if_token_expired(websocket: WebSocket, payload: dict) -> bool:
    """Close the socket when its token has expired. True if it was closed.

    The backstop, not the primary mechanism: clients refresh in-band via
    `_handle_auth_refresh` well before this fires. It matters when a client stops
    refreshing — an old build, or a session revoked while the socket is idle.
    """
    if not _token_expired(payload):
        return False
    try:
        await websocket.close(code=1008, reason="Token expired — reconnect")
    except Exception:
        pass
    return True


async def _handle_auth_refresh(websocket: WebSocket, user: dict, message: dict) -> bool:
    """Handle `{"action": "auth_refresh", "token": "..."}`. True if consumed.

    Clerk session tokens live about a minute. Enforcing `exp` by closing the
    socket would therefore tear down and rebuild every connection on the platform
    once a minute — a reconnect storm, and a tracking map that drops to "not
    live" every time. Instead the client sends a fresh token on the open socket
    and we extend the session in place.

    The new token must belong to the *same* subject: otherwise this becomes a way
    to hand an already-authorised socket — one whose entity/order access was
    checked at connect — to a different account.
    """
    if message.get("action") != "auth_refresh":
        return False

    payload = await verify_clerk_token(message.get("token") or "")
    if not payload or payload.get("sub") != user.get("sub"):
        logger.warning("WebSocket auth refresh rejected for %s", user.get("sub"))
        await websocket.close(code=1008, reason="Re-authentication failed")
        return True

    # Mutate in place: the socket handlers hold this dict, and `_token_expired`
    # reads `exp` from it on every loop.
    user.update(payload)
    try:
        await websocket.send_json({"action": "auth_refreshed", "exp": payload.get("exp")})
    except Exception:
        pass
    return True


async def _authorise_ws_entity(websocket: WebSocket, entity_type: str, entity_id: str, clerk_id: str) -> bool:
    """Confirm the token holder owns the entity named in the URL path.

    Authentication alone only proves someone is signed in. Without this check any
    signed-in account could stream fabricated GPS for an arbitrary rider, or
    subscribe to another customer's or vendor's order events.
    """
    from dependencies.dependencies import get_db_session
    from dependencies.auth_dependencies import owns_entity

    try:
        async with get_db_session() as session:
            if await owns_entity(session, entity_type, entity_id, clerk_id):
                return True
    except Exception as e:
        logger.error("WebSocket entity authorisation failed for %s %s: %s", entity_type, entity_id, e)
        await websocket.close(code=1011, reason="Authorisation check failed")
        return False

    logger.warning(
        "WebSocket authorisation denied: %s attempted to attach to %s %s",
        clerk_id, entity_type, entity_id,
    )
    await websocket.close(code=1008, reason="Not authorised for this resource")
    return False


async def _authorise_ws_order(websocket: WebSocket, order_id: str, clerk_id: str) -> Optional[str]:
    """Confirm the token holder is a party to this order; return their role."""
    from uuid import UUID as _UUID
    from dependencies.dependencies import get_db_session
    from dependencies.auth_dependencies import resolve_order_role

    try:
        parsed = _UUID(str(order_id))
    except (ValueError, TypeError):
        await websocket.close(code=1008, reason="Invalid order id")
        return None

    try:
        async with get_db_session() as session:
            role = await resolve_order_role(session, parsed, clerk_id)
    except Exception as e:
        logger.error("WebSocket order authorisation failed for order %s: %s", order_id, e)
        await websocket.close(code=1011, reason="Authorisation check failed")
        return None

    if role is None:
        logger.warning("WebSocket tracking denied: %s is not a party to order %s", clerk_id, order_id)
        await websocket.close(code=1008, reason="Not authorised for this order")
        return None
    return role


@router.websocket("/ws/rider/{rider_id}")
async def rider_location_ws(websocket: WebSocket, rider_id: str, token: Optional[str] = Query(None)):
    """Rider sends periodic location updates as JSON: {"lat": ..., "lng": ...}"""
    user = await _authenticate_ws(websocket, token)
    if not user:
        return
    if not await _authorise_ws_entity(websocket, "rider", rider_id, user.get("sub")):
        return
    await manager.connect_rider(rider_id, websocket)
    try:
        while True:
            if await _close_if_token_expired(websocket, user):
                break
            try:
                # BUG-WS-01 FIX: Server-side heartbeat to prevent silent proxy timeouts
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
                if isinstance(data, dict) and await _handle_auth_refresh(websocket, user, data):
                    continue
                await manager.update_rider_location(rider_id, data)
                
                async def _persist_location(lat: float, lng: float, heading: float, speed: float, order_id_str: str | None):
                    try:
                        r = get_redis()
                        if r:
                            import time
                            log_entry = {
                                "rider_id": rider_id,
                                "lat": lat,
                                "lng": lng,
                                "heading": heading,
                                "speed": speed,
                                "order_id": order_id_str,
                                "timestamp": time.time()
                            }
                            await r.rpush("gps_tracking_logs", json.dumps(log_entry))
                        else:
                            # Fallback if no redis
                            from dependencies.dependencies import get_db_session
                            from services.deliverer_service import update_deliverer_location_by_id
                            from models.order_tracking_log_model import OrderTrackingLog
                            async with get_db_session() as session:
                                await update_deliverer_location_by_id(
                                    session=session,
                                    deliverer_id=rider_id,
                                    lat=lat,
                                    lng=lng,
                                )
                                if order_id_str:
                                    import uuid
                                    try:
                                        o_id = uuid.UUID(order_id_str)
                                        tracking_log = OrderTrackingLog(
                                            order_id=o_id,
                                            lat=lat,
                                            lng=lng,
                                            heading=heading,
                                            speed=speed
                                        )
                                        session.add(tracking_log)
                                        await session.commit()
                                    except ValueError:
                                        pass
                    except Exception as e:
                        logger.warning(f"WS location DB persist failed for rider {rider_id}: {e}")

                asyncio.create_task(_persist_location(
                    float(data.get("lat", 0.0)),
                    float(data.get("lng", 0.0)),
                    float(data.get("heading", 0.0)),
                    float(data.get("speed", 0.0)),
                    data.get("order_id")
                ))
            except asyncio.TimeoutError:
                await websocket.send_json({"action": "heartbeat", "timestamp": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Rider socket %s closed unexpectedly: %s", rider_id, e)
    finally:
        # `finally`, not just the disconnect handler: any other exception (a send
        # on a half-closed socket, for instance) used to escape and leave the
        # connection registered forever, so the manager's maps grew without bound
        # and dead sockets kept receiving fan-out attempts.
        manager.disconnect_rider(rider_id)


@router.websocket("/ws/track/{order_id}")
async def track_order_ws(websocket: WebSocket, order_id: str, token: Optional[str] = Query(None)):
    """Customer connects to receive live rider location updates for their order."""
    user = await _authenticate_ws(websocket, token)
    if not user:
        return
    # Only a party to this order may watch it. Order ids are UUIDs, but any id
    # that leaks (a screenshot, a log line) previously granted a live feed of
    # somebody else's home delivery to any signed-in account.
    if not await _authorise_ws_order(websocket, order_id, user.get("sub")):
        return
    await manager.connect_tracker(order_id, websocket)
    try:
        while True:
            if await _close_if_token_expired(websocket, user):
                break
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # The tracker is receive-only apart from re-authentication, which
                # keeps the map live across Clerk's ~60s token lifetime.
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    message = None
                if isinstance(message, dict):
                    await _handle_auth_refresh(websocket, user, message)
            except asyncio.TimeoutError:
                await websocket.send_json({"action": "heartbeat", "timestamp": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Tracker socket for order %s closed unexpectedly: %s", order_id, e)
    finally:
        manager.disconnect_tracker(order_id, websocket)


@router.websocket("/ws/orders/{entity_type}/{entity_id}")
async def orders_ws(websocket: WebSocket, entity_type: str, entity_id: str, token: Optional[str] = Query(None)):
    """Generic endpoint for vendors, customers, or riders to listen for real-time order status updates."""
    user = await _authenticate_ws(websocket, token)
    if not user:
        return
    if entity_type not in ["vendor", "customer", "rider"]:
        await websocket.close(code=1008, reason="Unknown entity type")
        return

    # `entity_id` comes straight from the URL and was never compared to the token
    # subject, so anyone could subscribe to another customer's or vendor's stream.
    if not await _authorise_ws_entity(websocket, entity_type, entity_id, user.get("sub")):
        return

    await manager.connect_entity(entity_type, entity_id, websocket)
    try:
        while True:
            if await _close_if_token_expired(websocket, user):
                break
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    message = json.loads(data)
                    if await _handle_auth_refresh(websocket, user, message):
                        continue
                    if message.get("action") == "join-entity-room":
                        pass
                    elif message.get("action") == "location_update" and entity_type == "rider":
                        # Safe: `entity_id` is proven to be this token's own rider.
                        await manager.update_rider_location(entity_id, message)
                except json.JSONDecodeError as e:
                    logger.warning(f"WebSocket JSON decode error from {entity_type} {entity_id}: {e}")
                    await websocket.send_json({"error": "invalid_payload", "message": "Failed to parse JSON"})
            except asyncio.TimeoutError:
                await websocket.send_json({"action": "heartbeat", "timestamp": time.time()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Order socket for %s %s closed unexpectedly: %s", entity_type, entity_id, e)
    finally:
        manager.disconnect_entity(entity_type, entity_id, websocket)
