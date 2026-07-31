import { useAuth } from '@clerk/clerk-expo';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

/**
 * Purge everything belonging to the previous account when a session ends.
 *
 * Clearing the cache inside each sign-out handler only covered the deliberate
 * paths. Sessions also end without anyone tapping "Sign out":
 *
 *   - `useApiClient` signs the user out on any 401,
 *   - Clerk ends the session when it is revoked or the refresh token expires.
 *
 * Those routes left the React Query cache fully populated, so the next account
 * to sign in on the device rendered the previous store's orders, products and
 * profile until each query happened to refetch.
 *
 * Watching Clerk's own `isSignedIn` catches all of them from one place. Mount it
 * once, in the root layout, inside both providers.
 */
export function useSessionCleanup() {
    const { isSignedIn, isLoaded } = useAuth();
    const queryClient = useQueryClient();

    // Only a genuine signed-in → signed-out transition should clear. On a cold
    // start `isSignedIn` is false before Clerk resolves, which is not a sign-out.
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
        }
    }, [isSignedIn, isLoaded, queryClient]);
}

export default useSessionCleanup;
