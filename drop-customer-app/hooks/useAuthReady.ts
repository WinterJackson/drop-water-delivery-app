import { useAuth } from '@clerk/clerk-expo';

/**
 * Is a request that needs a token allowed to leave yet?
 *
 * `(screens)/_layout.tsx` carries this comment, and it is correct about the
 * hazard:
 *
 *   > Nothing in this group may mount until Clerk has resolved. Every query
 *   > below fires on mount, and while `isLoaded` is false `getToken()` yields
 *   > nothing.
 *
 * What it cannot do is enforce it. The guard there is an early `return`, and a
 * React component runs **every hook before it can return anything** — so
 * `useCart()` on the line above the guard has already issued its request by the
 * time the guard decides not to render. An early return stops rendering, never
 * fetching.
 *
 * The result reached the user as `GET /api/cart/get_cart -> 403: Not
 * authenticated` in a red overlay covering the whole screen, immediately after
 * a successful sign-in. Worse in production, where there is no overlay: the
 * cart badge is simply empty, and on a **401** `useApiRequest` signs the user
 * out — so a session could be destroyed by the act of opening the app, which is
 * the failure the layout's comment was written about.
 *
 * `isSignedIn` alone is not enough. While Clerk is still resolving it is
 * `false`, which is indistinguishable from "signed out" — so a query keyed on
 * it fires the moment the session loads, and a screen gated on it flashes the
 * signed-out state first. Both halves are required.
 *
 * Every query in `hooks/queries/` that needs a token spreads this into
 * `enabled`. `BackendAPI/tests/test_query_auth_gating.py` fails the build when
 * one does not.
 */
export function useAuthReady(): boolean {
    const { isLoaded, isSignedIn } = useAuth();
    return isLoaded && !!isSignedIn;
}
