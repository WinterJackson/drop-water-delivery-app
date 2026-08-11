import { useActiveStore } from '@/stores/activeStoreStore';
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
 * The remembered **store** is the other half, and it survived even a cache
 * clear because it is persisted separately: `activeStoreId` is sent as
 * `X-Store-Id` on every vendor request, and the backend validates it against
 * the caller's own stores and answers 404 for one they do not own. Left behind
 * on a shared till device, the next account signs in successfully and then
 * 404s on every scoped request it makes — which reads as the platform being
 * down rather than as stale state. The sign-out handler in `Profile.tsx`
 * cleared it; the 401 route, which is the one nobody taps, did not.
 *
 * Watching Clerk's own `isSignedIn` catches all of them from one place. Mount it
 * once, in the root layout, inside both providers.
 */
export function useSessionCleanup() {
    const { isSignedIn, isLoaded } = useAuth();
    const queryClient = useQueryClient();
    const clearActiveStore = useActiveStore((s) => s.clear);

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
            clearActiveStore();
            queryClient.clear();
        }
    }, [isSignedIn, isLoaded, queryClient, clearActiveStore]);
}

export default useSessionCleanup;
