import VendorApiRoutes, { WS_BASE_URL } from "@/API/routes/VendorApiRoutes";
import NetInfo from '@react-native-community/netinfo';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';

import { useAuth } from '@clerk/clerk-expo';

export interface OrderUpdate {
  action?: string;
  order_id?: string;
  status?: string;
  [key: string]: any;
}

/**
 * Silence past this is a dead socket. Comfortably above the server's 30s
 * heartbeat cadence, so a slow network cannot trip it.
 */
const LIVENESS_TIMEOUT_MS = 75_000;
const LIVENESS_CHECK_MS = 15_000;

/**
 * After the backoff ladder is exhausted the socket is not abandoned — it is
 * retried on a slow, fixed interval. Giving up permanently left a foregrounded
 * app on a working network with a screen that had quietly stopped updating and
 * no way back short of navigating away; the only things that reset the counter
 * were a background→foreground trip and a connectivity change.
 */
const IDLE_RETRY_MS = 60_000;

const useWebSocket = (
  entityType: string,
  entityId: string,
  onOrderUpdate: (data: OrderUpdate) => void
) => {
  const { getToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<any | null>(null);
  
  // FIX-WS-RERENDER-01: Stabilize references to prevent dependency-loop re-renders
  const getTokenRef = useRef(getToken);
  const entityTypeRef = useRef(entityType);
  const entityIdRef = useRef(entityId);

  // Keep refs current without triggering useCallback/useEffect dependency changes
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);
  useEffect(() => { entityTypeRef.current = entityType; }, [entityType]);
  useEffect(() => { entityIdRef.current = entityId; }, [entityId]);

  // BUG-WS-FE-01 FIX: Store latest callback to prevent stale closures and dependency loops
  const onOrderUpdateRef = useRef(onOrderUpdate);
  useEffect(() => {
    onOrderUpdateRef.current = onOrderUpdate;
  }, [onOrderUpdate]);
  
  // Backoff state
  const attemptRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 10;

/**
 * Clerk session tokens live about a minute, and the server now enforces `exp` on
 * open sockets. Reconnecting every time one lapses would rebuild every socket on
 * the platform once a minute, so instead we hand the server a fresh token on the
 * live connection and it extends the session in place.
 */
const AUTH_REFRESH_INTERVAL_MS = 30_000;


  // Guard to prevent connecting after unmount
  const mountedRef = useRef(true);

  // BUG-WS-FE-03 FIX: Use secure URL construction from env vars with flexible fallback
  const BASE_URL = WS_BASE_URL;


  // Push a fresh token onto the live socket so the server can extend the session
  // without a reconnect. Cleared whenever the socket goes away.
  const authTimerRef = useRef<any | null>(null);
  const stopAuthRefresh = useCallback(() => {
    if (authTimerRef.current) {
      clearInterval(authTimerRef.current);
      authTimerRef.current = null;
    }
  }, []);
  const startAuthRefresh = useCallback((ws: WebSocket) => {
    stopAuthRefresh();
    authTimerRef.current = setInterval(async () => {
      if (ws.readyState !== WebSocket.OPEN) { stopAuthRefresh(); return; }
      try {
        const fresh = await getTokenRef.current();
        if (fresh) ws.send(JSON.stringify({ action: 'auth_refresh', token: fresh }));
      } catch {
        // A failed mint is not fatal: the server closes on expiry and the
        // existing reconnect path takes over with a new token.
      }
    }, AUTH_REFRESH_INTERVAL_MS);
  }, [stopAuthRefresh]);

  // FIX-WS-RERENDER-02: `connect` has ZERO external dependencies — all values read from refs.
  // This means useCallback never produces a new reference, so the useEffect never re-fires.
  /**
   * Declared **before** the connect effect, not after it.
   *
   * Effects run in declaration order, so with this one last a remount — Fast
   * Refresh, StrictMode's double-invoke, or any unmount/mount of the screen —
   * ran `connect()` while `mountedRef` was still `false` from the previous
   * teardown, and every early return in the connect path fired. The socket
   * silently never opened, and only a background→foreground trip brought it
   * back.
   */
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  /**
   * Liveness, not just connectedness.
   *
   * A mobile socket can go **half-open**: the TCP connection survives a cell
   * handover or a NAT timeout on paper, so `onclose` never fires and
   * `readyState` stays `OPEN`, while nothing can actually get through. The
   * client sits believing it is live and the screen silently stops updating —
   * which on the rider's radar means missed offers and on the customer's map
   * means a marker that stopped moving.
   *
   * The traffic to watch for already exists: the server sends
   * `{"action":"heartbeat"}` after 30s of client silence, and acks every
   * `auth_refresh` with `auth_refreshed`. One or the other arrives at least
   * every ~30s on a healthy socket, so silence past `LIVENESS_TIMEOUT_MS` means
   * the socket is dead however it looks. Closing it ourselves lets the normal
   * reconnect path take over.
   */
  const lastMessageAtRef = useRef(Date.now());
  const livenessTimerRef = useRef<any | null>(null);

  const stopLivenessWatch = useCallback(() => {
    if (livenessTimerRef.current) {
      clearInterval(livenessTimerRef.current);
      livenessTimerRef.current = null;
    }
  }, []);

  const startLivenessWatch = useCallback((ws: WebSocket) => {
    stopLivenessWatch();
    lastMessageAtRef.current = Date.now();
    livenessTimerRef.current = setInterval(() => {
      if (ws.readyState !== WebSocket.OPEN) return;
      if (Date.now() - lastMessageAtRef.current < LIVENESS_TIMEOUT_MS) return;
      if (__DEV__) console.warn('WebSocket went quiet — treating as dead and reconnecting');
      // `close()` fires `onclose`, which schedules the reconnect. Handlers are
      // left in place on purpose: this is a failure, not an intentional teardown.
      try { ws.close(); } catch { /* already gone */ }
    }, LIVENESS_CHECK_MS);
  }, [stopLivenessWatch]);

  const connect = useCallback(async () => {
    if (!mountedRef.current) return;
    if (!entityIdRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
        const token = await getTokenRef.current();
        if (!token || !mountedRef.current) return;

        const ws = new WebSocket(
          `${BASE_URL}/ws/orders/${entityTypeRef.current}/${entityIdRef.current}?token=${token}`
        );

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      if (__DEV__) console.log('WebSocket connected');
      setConnected(true);
      attemptRef.current = 0; // Reset backoff on success
      ws.send(JSON.stringify({ action: 'join-entity-room' }));
      startAuthRefresh(ws);
      startLivenessWatch(ws);
    };

    ws.onmessage = (event) => {
      // Any frame at all proves the socket is alive — heartbeats included,
      // which is the whole point of watching for their absence.
      lastMessageAtRef.current = Date.now();
      try {
        const data = JSON.parse(event.data) as OrderUpdate;
        // FIX-WS-RERENDER-03: Silently ignore heartbeat messages — they are keep-alive pings,
        // NOT order updates. Previously, every heartbeat triggered refetch() → re-render.
        if (data.action === 'heartbeat') return;
        if (__DEV__) console.log('Received order update:', data);
        onOrderUpdateRef.current(data);
      } catch (err) {
        if (__DEV__) console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onclose = () => {
      stopAuthRefresh();
      stopLivenessWatch();
      if (__DEV__) console.log('WebSocket disconnected');
      setConnected(false);
      wsRef.current = null;
      
      if (!mountedRef.current) return;
      
      // Stop reconnecting if the app is in the background to save battery
      if (appState.current.match(/inactive|background/)) {
          return;
      }

      // BUG-WS-FE-02 FIX: Exponential backoff with jitter, capped at MAX_RECONNECT_ATTEMPTS
      attemptRef.current += 1;
      // Past the ladder, keep trying on a slow interval instead of giving
      // up. Stopping outright left a foregrounded app on a working network
      // with a screen that had silently stopped updating.
      const exhausted = attemptRef.current > MAX_RECONNECT_ATTEMPTS;
      const baseDelay = exhausted
        ? IDLE_RETRY_MS
        : Math.min(3000 * Math.pow(2, attemptRef.current - 1), 60000);
      const jitter = Math.random() * 1000;
      const delay = baseDelay + jitter;
      
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // Errors are expected during reconnection cycles — handled silently in production.
      // The onclose handler will trigger the reconnect logic.
    };

    wsRef.current = ws;
    } catch (e) {
      if (__DEV__) console.error('WebSocket connection failed:', e);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [BASE_URL]); // BASE_URL is a stable ref — this callback never changes.

  // FIX-WS-RERENDER-04: Only connect when entityId actually becomes available.
  // Previously this depended on `connect` which changed on every render.
  const appState = useRef(AppState.currentState);

  useEffect(() => {
    if (!entityId) return; // Don't connect until we have a real ID
    
    attemptRef.current = 0;
    connect();

    // DOMAIN-3: AppState listener to freeze/restore WS on background/foreground
    const handleAppState = (nextState: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && nextState === 'active') {
        // Only reconnect on genuine background→active transition
        attemptRef.current = 0;
        connect();
      } else if (nextState.match(/inactive|background/)) {
        // Freeze connection when backgrounded to save battery
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        if (wsRef.current) {
          // Nullify handlers BEFORE close to prevent onclose from spawning zombie reconnects
          stopLivenessWatch();
        wsRef.current.onclose = null;
          wsRef.current.onerror = null;
          wsRef.current.onmessage = null;
          wsRef.current.onopen = null;
          wsRef.current.close();
          wsRef.current = null;
        }
        setConnected(false);
      }
      appState.current = nextState;
    };
    const subscription = AppState.addEventListener('change', handleAppState);

    // Reconnect as soon as the device is back online. Relying on `onclose` plus
    // exponential backoff alone meant a brief network drop could leave the
    // socket down for up to a minute after connectivity had already returned —
    // long enough to miss the order the screen exists to show.
    const netInfoUnsubscribe = NetInfo.addEventListener((state) => {
      if (!mountedRef.current) return;
      if (!state.isConnected) return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      if (appState.current.match(/inactive|background/)) return;

      attemptRef.current = 0;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      connect();
    });
    return () => {
      subscription.remove();
      netInfoUnsubscribe();
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        stopLivenessWatch();
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.onopen = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId]); // Only re-run when the actual entityId value changes (null → "abc-123")


  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { connected, sendMessage };
};

export default useWebSocket;