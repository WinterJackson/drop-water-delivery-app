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

class ConnectionManager:
    """Manages WebSocket connections for live delivery tracking, backed by Redis Pub/Sub for infinite horizontal scalability."""

    def __init__(self):
        # rider_id -> WebSocket (rider sending location)
        self.rider_connections: Dict[str, WebSocket] = {}
        # order_id -> list of WebSockets (customers watching)
        self.tracking_connections: Dict[str, List[WebSocket]] = {}
        self.order_rider_map: Dict[str, str] = {}
        self.order_vendor_map: Dict[str, str] = {}
        # rider_id -> latest location
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

        # Fan out to every locally-connected tracker whose order is served by this
        # rider. The order→rider mapping is resolved per socket at connect time
        # (see `connect_tracker`) and cached in Redis, so a worker that never
        # happened to relay an order-status broadcast still knows the mapping.
        for order_id in list(self.tracking_connections.keys()):
            mapped_rider = self.order_rider_map.get(order_id)
            if mapped_rider is None:
                mapped_rider = await self.resolve_order_rider(order_id)
            if mapped_rider != rider_id:
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
                    self.order_rider_map[order_id] = rider_id
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
        self.order_rider_map[order_id] = rider_id
        # Also persist this map to Redis so other workers know
        r = get_redis()
        if r:
            asyncio.create_task(r.setex(f"order_rider_map:{order_id}", 86400, rider_id))


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
