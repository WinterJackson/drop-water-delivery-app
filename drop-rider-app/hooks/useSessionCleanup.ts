import { useAuth } from '@clerk/clerk-expo';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { clearOfflineData } from '@/config/database';

/**
 * Purge everything belonging to the previous rider when a session ends.
 *
 * Clearing the cache inside each sign-out handler only covered the deliberate
 * paths. Sessions also end without anyone tapping "Sign out":
 *
 *   - every rider query signs the user out on a 401,
 *   - Clerk ends the session when it is revoked or the refresh token expires.
 *
 * Those routes left both caches fully populated. The React Query one exposed the
 * previous rider's earnings and active delivery; the SQLite one is worse, because
 * it is on disk and held customer addresses and phone numbers indefinitely.
 *
 * Watching Clerk's own `isSignedIn` catches every route from one place. Mount it
 * once, in the root layout, inside both providers.
 */
export function useSessionCleanup() {
    const { isSignedIn, isLoaded } = useAuth();
    const queryClient = useQueryClient();

    // Only a genuine signed-in → signed-out transition should clear. On a cold
    // start `isSignedIn` is false before Clerk resolves, which is not a sign-out
    // — clearing there would wipe the offline manifest of a rider who is simply
    // reopening the app with no signal.
    const wasSignedIn = useRef(false);

    useEffect(() => {
        if (!isLoaded) return;

        if (isSignedIn) {
            wasSignedIn.current = true;
            return;
        }

        if (wasSignedIn.current) {
            wasSignedIn.current = false;
            queryClient.clear();
            clearOfflineData().catch(() => {});
        }
    }, [isSignedIn, isLoaded, queryClient]);
}

export default useSessionCleanup;
