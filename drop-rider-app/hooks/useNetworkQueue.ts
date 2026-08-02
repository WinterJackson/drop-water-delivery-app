/**
 * Drives the offline replay queue.
 *
 * The flush itself lives in `services/offlineQueue` so it can be called from
 * anywhere; this hook is only about *when*. It used to be the other way round —
 * the entire flush was the body of a `NetInfo` listener, which meant a replay
 * that failed waited for the next connectivity *transition* before trying again.
 * On a device that stayed online the whole time that transition never came, and
 * a delivered order sat unsynced indefinitely: the rider unpaid, the customer
 * un-notified, the order stuck at `picked_up`, and nothing on screen about it.
 *
 * Four triggers now:
 *   1. connectivity restored (the original one, still the fastest signal),
 *   2. the app returning to the foreground,
 *   3. a timer, while anything is still queued,
 *   4. the rider tapping retry on the Pending Sync screen (not here).
 */
import { useAuth } from '@clerk/clerk-expo';
import NetInfo from '@react-native-community/netinfo';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';

import { flushOfflineQueue, getQueueStatus } from '@/services/offlineQueue';

/** While the queue is non-empty. Short enough to clear a backlog promptly. */
const RETRY_INTERVAL_MS = 60_000;

export function useNetworkQueue() {
    const { getToken } = useAuth();
    const queryClient = useQueryClient();
    const timer = useRef<ReturnType<typeof setInterval> | null>(null);
    /** So a run of failures does not re-toast on every one of the four triggers. */
    const warnedAt = useRef(0);

    useEffect(() => {
        let cancelled = false;

        /** Only keep a timer alive while there is actually something waiting. */
        const rescheduleTimer = async () => {
            const { pending } = await getQueueStatus();
            if (cancelled) return;
            if (pending > 0 && !timer.current) {
                timer.current = setInterval(run, RETRY_INTERVAL_MS);
            } else if (pending === 0 && timer.current) {
                clearInterval(timer.current);
                timer.current = null;
            }
        };

        const run = async () => {
            if (cancelled) return;
            const result = await flushOfflineQueue(getToken, () => {
                queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
            });
            if (cancelled) return;

            if (result.needsAttention > 0 && Date.now() - warnedAt.current > 15 * 60_000) {
                warnedAt.current = Date.now();
                // Never a silent drop: an action that cannot replay is the
                // rider's completed work, and they have to be able to see it.
                const { Toast } = await import('@/lib/toast');
                Toast.error(
                    'Sync needs attention',
                    `${result.needsAttention} saved action${result.needsAttention === 1 ? '' : 's'} could not sync. Open Pending Sync from Settings to review.`
                );
            }
            await rescheduleTimer();
        };

        const unsubscribe = NetInfo.addEventListener((state: any) => {
            if (state.isConnected && state.isInternetReachable) run();
        });

        const appState = AppState.addEventListener('change', (status: AppStateStatus) => {
            if (status === 'active') run();
        });

        run();

        return () => {
            cancelled = true;
            unsubscribe();
            appState.remove();
            if (timer.current) {
                clearInterval(timer.current);
                timer.current = null;
            }
        };
    }, [getToken, queryClient]);
}
