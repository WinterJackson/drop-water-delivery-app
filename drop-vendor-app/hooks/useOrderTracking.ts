import { WS_BASE_URL } from "@/API/routes/VendorApiRoutes";
import { useAuth } from "@clerk/clerk-expo";
import NetInfo from "@react-native-community/netinfo";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, AppStateStatus } from "react-native";

export interface TrackedLocation {
  lat: number;
  lng: number;
}

/**
 * Where the rider carrying this order is, live.
 *
 * `Map/[id].tsx` opened its own socket inline, and that socket **could never
 * connect**: it omitted the `?token=` query parameter, and the server closes an
 * unauthenticated tracking socket with code 1008 before the first frame. The
 * screen's reconnect loop then ran its five attempts against a refusal and gave
 * up, so a vendor watching a delivery saw the map's own fallback position and
 * nothing else — for every order, always.
 *
 * The customer app hit the identical bug and fixed it in `useRiderTracking`;
 * this is the vendor-side counterpart. There is no REST fallback here because
 * there is no vendor-scoped rider-location endpoint to poll — the socket is the
 * only source, which is exactly why it has to be able to open.
 *
 * @param orderId  The order to watch.
 * @param enabled  Only while the order is actually in motion.
 */
export function useOrderTracking(orderId: string | null | undefined, enabled: boolean) {
  const { getToken } = useAuth();
  const [location, setLocation] = useState<TrackedLocation | null>(null);
  const [isLive, setIsLive] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const authTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const livenessRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastMessageAtRef = useRef(Date.now());
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);
  const appStateRef = useRef(AppState.currentState);
  const getTokenRef = useRef(getToken);

  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  /** Clerk tokens live about a minute; the server extends the session in place. */
  const AUTH_REFRESH_MS = 30_000;
  /** Silence past this means a half-open socket — see `useWebSocket`. */
  const LIVENESS_TIMEOUT_MS = 75_000;
  const LIVENESS_CHECK_MS = 15_000;
  const MAX_ATTEMPTS = 8;
  const IDLE_RETRY_MS = 60_000;

  const clearTimers = useCallback(() => {
    if (authTimerRef.current) { clearInterval(authTimerRef.current); authTimerRef.current = null; }
    if (livenessRef.current) { clearInterval(livenessRef.current); livenessRef.current = null; }
  }, []);

  const closeSocket = useCallback(() => {
    clearTimers();
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      // Detach before closing: this is a deliberate teardown, and `onclose`
      // would otherwise schedule a reconnect for a socket we are discarding.
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try { ws.close(); } catch { /* already gone */ }
    }
    setIsLive(false);
  }, [clearTimers]);

  const connect = useCallback(async () => {
    if (!orderId || !enabled || !mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (appStateRef.current.match(/inactive|background/)) return;

    try {
      const token = await getTokenRef.current();
      if (!token || !mountedRef.current) return;

      // The token is mandatory. Without it the server closes with 1008 and the
      // map never receives a single position.
      const ws = new WebSocket(`${WS_BASE_URL}/ws/track/${orderId}?token=${token}`);

      ws.onopen = () => {
        if (!mountedRef.current) { try { ws.close(); } catch {} return; }
        attemptRef.current = 0;
        setIsLive(true);
        lastMessageAtRef.current = Date.now();

        clearTimers();
        authTimerRef.current = setInterval(async () => {
          if (ws.readyState !== WebSocket.OPEN) return;
          try {
            const fresh = await getTokenRef.current();
            if (fresh) ws.send(JSON.stringify({ action: "auth_refresh", token: fresh }));
          } catch {
            // Not fatal: expiry closes the socket and the reconnect path reopens it.
          }
        }, AUTH_REFRESH_MS);

        livenessRef.current = setInterval(() => {
          if (ws.readyState !== WebSocket.OPEN) return;
          if (Date.now() - lastMessageAtRef.current < LIVENESS_TIMEOUT_MS) return;
          // Half-open: `readyState` says OPEN, nothing is getting through.
          try { ws.close(); } catch { /* already gone */ }
        }, LIVENESS_CHECK_MS);
      };

      ws.onmessage = (event) => {
        lastMessageAtRef.current = Date.now();
        try {
          const payload = JSON.parse(event.data);
          if (payload?.action === "heartbeat") return;
          // Both shapes: `{location: {lat, lng}}` from the relay, flat from older senders.
          const point = payload.location ?? payload;
          if (mountedRef.current && point?.lat != null && point?.lng != null) {
            setLocation({ lat: Number(point.lat), lng: Number(point.lng) });
          }
        } catch {
          if (__DEV__) console.warn("[Tracking] Unparseable frame");
        }
      };

      ws.onerror = () => {
        // Expected during reconnection cycles; `onclose` drives the retry.
      };

      ws.onclose = () => {
        clearTimers();
        wsRef.current = null;
        if (mountedRef.current) setIsLive(false);
        if (!mountedRef.current || !enabled) return;
        if (appStateRef.current.match(/inactive|background/)) return;

        attemptRef.current += 1;
        // Slow down rather than stop. Giving up left a vendor watching a static
        // map with nothing to say why.
        const base = attemptRef.current > MAX_ATTEMPTS
          ? IDLE_RETRY_MS
          : Math.min(1000 * Math.pow(2, attemptRef.current), 30_000);
        reconnectRef.current = setTimeout(connect, base + Math.random() * 1000);
      };

      wsRef.current = ws;
    } catch (e) {
      if (__DEV__) console.warn("[Tracking] Setup failed:", e);
    }
  }, [orderId, enabled, clearTimers]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!orderId || !enabled) {
      closeSocket();
      setLocation(null);
      return;
    }

    attemptRef.current = 0;
    connect();

    const netInfoUnsubscribe = NetInfo.addEventListener((state) => {
      if (!mountedRef.current || !enabled) return;
      if (!state.isConnected) return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      if (appStateRef.current.match(/inactive|background/)) return;
      attemptRef.current = 0;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      connect();
    });

    const handleAppState = (next: AppStateStatus) => {
      const wasBackgrounded = appStateRef.current.match(/inactive|background/);
      appStateRef.current = next;
      if (wasBackgrounded && next === "active") {
        attemptRef.current = 0;
        connect();
      } else if (next.match(/inactive|background/)) {
        if (reconnectRef.current) clearTimeout(reconnectRef.current);
        closeSocket();
      }
    };
    const appStateSubscription = AppState.addEventListener("change", handleAppState);

    return () => {
      netInfoUnsubscribe();
      appStateSubscription.remove();
      if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
      closeSocket();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId, enabled]);

  return { location, isLive };
}
