import { ROUTES, WS_BASE_URL } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useAuth } from '@clerk/clerk-expo';
import NetInfo from '@react-native-community/netinfo';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface RiderLocation {
    rider_id: string;
    rider_name: string;
    lat: number | null;
    lng: number | null;
    is_available: boolean;
}

/**
 * Live rider tracking: WebSocket first, REST polling as a fallback.
 *
 * The single source of truth for customer-side tracking. `Map/[id].tsx` used to
 * open its own socket, which could never work — it omitted the `?token=` query
 * parameter (the server closes unauthenticated sockets with 1008) and read
 * `data.lat` when the server sends `{location: {lat, lng}}`.
 *
 * @param orderId - The order to track
 * @param enabled - Only track while the order is in transit
 * @param pollingIntervalMs - REST fallback interval (default 8s)
 */
export function useRiderTracking(orderId: string | null, enabled = true, pollingIntervalMs = 8000) {
    const { getToken } = useAuth();
    const api = useApiRequest();
    const [data, setData] = useState<RiderLocation | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<Error | null>(null);
    const [isLive, setIsLive] = useState(false);

    const wsRef = useRef<WebSocket | null>(null);
    const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const wsFailCountRef = useRef(0);
    const isMountedRef = useRef(true);
    const appStateRef = useRef(AppState.currentState);
    const MAX_WS_FAILURES = 3;
    /**
     * Silence past this means the socket is half-open: `readyState` still says
     * OPEN, `onclose` never fires, and the marker has quietly stopped moving
     * while the screen still says "Live". The server sends a heartbeat after
     * 30s of client silence and acks every `auth_refresh`, so a healthy socket
     * is never quiet this long.
     */
    const LIVENESS_TIMEOUT_MS = 75_000;
    const LIVENESS_CHECK_MS = 15_000;
    /**
     * Polling is the floor, not the ceiling. Once the REST fallback is running
     * the socket is still retried on a slow interval — otherwise a single bad
     * stretch of network downgraded the map to 8-second polling for the rest of
     * the delivery, with no way back.
     */
    const IDLE_RETRY_MS = 60_000;
    const lastMessageAtRef = useRef(Date.now());
    const livenessTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    // Clerk session tokens live about a minute and the server enforces `exp` on
    // open sockets. Without an in-band refresh the tracking map would tear down
    // and rebuild its connection every minute, flicking "Live" off each time.
    const AUTH_REFRESH_INTERVAL_MS = 30_000;
    const authTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Stable refs so the connect callback never needs to be rebuilt.
    const apiRef = useRef(api);
    const getTokenRef = useRef(getToken);
    useEffect(() => { apiRef.current = api; }, [api]);
    useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

    // ── REST Polling Fallback ──────────────────────────────────────────────
    const fetchViaRest = useCallback(async () => {
        if (!orderId) return;
        try {
            const location = await apiRef.current.get<RiderLocation>(ROUTES.RIDER_LOCATION(orderId));
            if (isMountedRef.current) {
                setData(location);
                setIsLoading(false);
                setError(null);
            }
        } catch (err) {
            if (isMountedRef.current) {
                setError(err instanceof Error ? err : new Error('Tracking failed'));
                setIsLoading(false);
            }
        }
    }, [orderId]);

    const stopAuthRefresh = useCallback(() => {
        if (authTimerRef.current) {
            clearInterval(authTimerRef.current);
            authTimerRef.current = null;
        }
    }, []);

    const stopLivenessWatch = useCallback(() => {
        if (livenessTimerRef.current) {
            clearInterval(livenessTimerRef.current);
            livenessTimerRef.current = null;
        }
    }, []);

    const stopPolling = useCallback(() => {
        if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        }
    }, []);

    const startPolling = useCallback(() => {
        fetchViaRest();
        stopPolling();
        pollTimerRef.current = setInterval(fetchViaRest, pollingIntervalMs);
    }, [fetchViaRest, pollingIntervalMs, stopPolling]);

    const closeSocket = useCallback(() => {
        stopAuthRefresh();
        stopLivenessWatch();
        const ws = wsRef.current;
        wsRef.current = null;
        if (ws) {
            // Detach handlers before closing so `onclose` cannot schedule a zombie
            // reconnect for a socket we are deliberately discarding.
            ws.onopen = null;
            ws.onmessage = null;
            ws.onerror = null;
            ws.onclose = null;
            try { ws.close(); } catch { /* already closed */ }
        }
        setIsLive(false);
    }, []);

    // ── WebSocket Connection ──────────────────────────────────────────────
    const connectWs = useCallback(async () => {
        if (!orderId || !enabled || !isMountedRef.current) return;
        if (wsRef.current?.readyState === WebSocket.OPEN) return;
        if (appStateRef.current.match(/inactive|background/)) return;

        try {
            const token = await getTokenRef.current();
            if (!token || !isMountedRef.current) return;

            // The token is mandatory: the server closes unauthenticated tracking
            // sockets with code 1008.
            const ws = new WebSocket(`${WS_BASE_URL}/ws/track/${orderId}?token=${token}`);

            ws.onopen = () => {
                if (__DEV__) console.log(`[WS Tracker] Connected for order ${orderId}`);
                wsFailCountRef.current = 0;
                if (isMountedRef.current) setIsLive(true);
                stopPolling();
                stopAuthRefresh();
                authTimerRef.current = setInterval(async () => {
                    if (ws.readyState !== WebSocket.OPEN) { stopAuthRefresh(); return; }
                    try {
                        const fresh = await getTokenRef.current();
                        if (fresh) ws.send(JSON.stringify({ action: 'auth_refresh', token: fresh }));
                    } catch {
                        // Not fatal — expiry closes the socket and the existing
                        // reconnect path reopens it with a new token.
                    }
                }, AUTH_REFRESH_INTERVAL_MS);

                lastMessageAtRef.current = Date.now();
                stopLivenessWatch();
                livenessTimerRef.current = setInterval(() => {
                    if (ws.readyState !== WebSocket.OPEN) return;
                    if (Date.now() - lastMessageAtRef.current < LIVENESS_TIMEOUT_MS) return;
                    // Handlers stay attached: this is a failure, so `onclose`
                    // should run and drive the reconnect.
                    try { ws.close(); } catch { /* already gone */ }
                }, LIVENESS_CHECK_MS);
            };

            ws.onmessage = (event) => {
                // Any frame proves the socket is alive — heartbeats included.
                lastMessageAtRef.current = Date.now();
                try {
                    const payload = JSON.parse(event.data);
                    if (payload?.action === 'heartbeat') return;

                    // Accept both shapes: `{location: {lat, lng}}` from the relay and
                    // a flat `{lat, lng}` from older senders.
                    const location = payload.location ?? payload;
                    if (isMountedRef.current && location?.lat != null && location?.lng != null) {
                        setData((prev) => ({
                            rider_id: location.rider_id || payload.rider_id || prev?.rider_id || '',
                            rider_name: location.rider_name || prev?.rider_name || 'Rider',
                            lat: Number(location.lat),
                            lng: Number(location.lng),
                            is_available: true,
                        }));
                        setIsLoading(false);
                        setError(null);
                    }
                } catch (parseErr) {
                    if (__DEV__) console.warn('[WS Tracker] Parse error:', parseErr);
                }
            };

            ws.onclose = () => {
                if (__DEV__) console.log('[WS Tracker] Disconnected');
                stopAuthRefresh();
                stopLivenessWatch();
                wsRef.current = null;
                if (isMountedRef.current) setIsLive(false);
                wsFailCountRef.current++;

                if (!isMountedRef.current || !enabled) return;
                if (appStateRef.current.match(/inactive|background/)) return;

                if (wsFailCountRef.current >= MAX_WS_FAILURES) {
                    if (__DEV__) console.log('[WS Tracker] Falling back to REST polling');
                    startPolling();
                    // Polling is a floor, not a destination — keep trying for the
                    // socket so the map can return to live positions.
                    reconnectTimerRef.current = setTimeout(connectWs, IDLE_RETRY_MS);
                } else {
                    const delay = Math.min(1000 * Math.pow(2, wsFailCountRef.current), 10000);
                    reconnectTimerRef.current = setTimeout(connectWs, delay);
                }
            };

            ws.onerror = (err) => {
                if (__DEV__) console.warn('[WS Tracker] Error:', err);
            };

            wsRef.current = ws;
        } catch (e) {
            if (__DEV__) console.warn('[WS Tracker] Connection setup failed:', e);
            startPolling();
        }
    }, [orderId, enabled, stopPolling, startPolling, stopAuthRefresh, stopLivenessWatch]);

    // ── Lifecycle ──────────────────────────────────────────────────────────
    useEffect(() => {
        isMountedRef.current = true;

        if (!orderId || !enabled) {
            setData(null);
            setIsLoading(false);
            setIsLive(false);
            return;
        }

        setIsLoading(true);
        wsFailCountRef.current = 0;

        // REST first so the marker appears immediately, then upgrade to the socket.
        fetchViaRest();
        connectWs();

        // Reconnect the moment connectivity returns rather than waiting out the
        // exponential backoff — a lift or a tunnel otherwise froze the map for up
        // to ten seconds after the network was already back.
        const netInfoUnsubscribe = NetInfo.addEventListener((state) => {
            if (!isMountedRef.current || !enabled) return;
            if (state.isConnected && !wsRef.current) {
                wsFailCountRef.current = 0;
                if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
                connectWs();
            }
        });

        // Drop the socket while backgrounded to save battery, restore on return.
        const handleAppState = (nextState: AppStateStatus) => {
            const wasBackgrounded = appStateRef.current.match(/inactive|background/);
            appStateRef.current = nextState;

            if (wasBackgrounded && nextState === 'active') {
                wsFailCountRef.current = 0;
                fetchViaRest();
                connectWs();
            } else if (nextState.match(/inactive|background/)) {
                if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
                stopPolling();
                closeSocket();
            }
        };
        const appStateSubscription = AppState.addEventListener('change', handleAppState);

        return () => {
            isMountedRef.current = false;
            netInfoUnsubscribe();
            appStateSubscription.remove();
            closeSocket();
            stopPolling();
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [orderId, enabled]);

    return { data, isLoading, error, isLive };
}
