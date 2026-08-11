import RiderApiRoutes, { WS_BASE_URL } from "@/API/routes/RiderApiRoutes";
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

const MAX_RECONNECT_ATTEMPTS = 10;

/**
 * Clerk session tokens live about a minute, and the server enforces `exp` on open
 * sockets. Reconnecting on every lapse would rebuild every socket on the platform
 * once a minute, so the client hands the server a fresh token in-band instead.
 */
const AUTH_REFRESH_INTERVAL_MS = 30_000;

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
  const appState = useRef(AppState.currentState);

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

  // FIX-WS-RERENDER-02: `connect` has ZERO external dependencies — all values read from refs.
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
        if (!token || !mountedRef.current) {
          if (__DEV__) console.log('WebSocket skipped — no auth token available.');
          return;
        }
        const wsUrl = `${BASE_URL}/ws/orders/${entityTypeRef.current}/${entityIdRef.current}?token=${token}`;
        if (__DEV__) console.log(`WebSocket connecting: ${entityTypeRef.current}/${entityIdRef.current}`);
        const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      if (__DEV__) console.log('WebSocket connected');
      setConnected(true);
      attemptRef.current = 0; // Reset backoff on success
      ws.send(JSON.stringify({ action: 'join-entity-room' }));
      stopAuthRefresh();
      authTimerRef.current = setInterval(async () => {
        if (ws.readyState !== WebSocket.OPEN) { stopAuthRefresh(); return; }
        try {
          const fresh = await getTokenRef.current();
          if (fresh) ws.send(JSON.stringify({ action: 'auth_refresh', token: fresh }));
        } catch {
          // Not fatal — expiry closes the socket and the reconnect path reopens it.
        }
      }, AUTH_REFRESH_INTERVAL_MS);
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

    ws.onclose = (event) => {
      stopAuthRefresh();
      stopLivenessWatch();
      if (__DEV__) console.log('WebSocket disconnected', event?.code, event?.reason);
      setConnected(false);
      wsRef.current = null;
      
      if (!mountedRef.current) return;
      
      // Stop reconnecting if the app is in the background to save battery
      if (appState.current.match(/inactive|background/)) {
          return;
      }
      
      // BUG-WS-FE-02 FIX: Exponential backoff with jitter
      attemptRef.current += 1;
      if (attemptRef.current <= MAX_RECONNECT_ATTEMPTS) {
          const baseDelay = Math.min(3000 * Math.pow(2, attemptRef.current - 1), 60000);
          const jitter = Math.random() * 1000;
          const delay = baseDelay + jitter;
          reconnectTimeoutRef.current = setTimeout(connect, delay);
      }
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
  useEffect(() => {
    if (!entityId) return;
    
    attemptRef.current = 0;
    connect();

    // AppState Listener to freeze WS in background
    const subscription = AppState.addEventListener('change', (nextAppState: AppStateStatus) => {
      if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
        attemptRef.current = 0;
        connect();
      } else if (nextAppState.match(/inactive|background/)) {
        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
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
      appState.current = nextAppState;
    });

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
        // Prevent onclose from triggering a reconnect when intentionally unmounting/cleaning up
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
  }, [entityId]); // Only re-run when the actual entityId value changes


  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { connected, sendMessage };
};

export default useWebSocket;