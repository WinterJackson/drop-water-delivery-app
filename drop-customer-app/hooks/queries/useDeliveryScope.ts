import { useUserDetails } from '@/hooks/queries/useUser';

/**
 * The cache scope for anything the server bounds by the delivery address.
 *
 * Ten endpoints resolve `services/delivery_point.resolve` and filter their
 * results to what can actually be delivered to *that* origin — the two
 * searches, five vendor reads and three product listings. Their responses are
 * therefore a function of the customer's saved address, and a cache key that
 * omits it is a key that cannot tell two different answers apart.
 *
 * It was omitted from all ten, and the cache is persisted to AsyncStorage with
 * a 24-hour `maxAge`. So a customer who changed their delivery address — moved
 * house, or switched from home to the office — kept being served the previous
 * address's shops from disk, across restarts, until the entry aged out. React
 * Query had no reason to think otherwise: same key, same query, still fresh.
 *
 * That is the "two halves of the app disagreeing" defect again, and this time
 * it reaches checkout: the customer fills a basket from a store the cache said
 * was nearby, and `validate_cart_preflight` refuses it against the radius
 * measured from the address they actually have.
 *
 * Observed as a stale "Vendors (19)" on a screen the server answers with 11.
 *
 * The scope is the coordinates rather than `location_address`, because the
 * coordinates are what the radius is measured from — two different addresses
 * that geocode to the same point genuinely have the same answer, and a renamed
 * address that geocodes identically should not throw the cache away. They are
 * fixed to five decimals (about a metre) so a re-geocode of the same place
 * cannot churn every list.
 *
 * `no-origin` is a real scope, not a fallback: with no address the server
 * returns `[]` by design, and that emptiness belongs to its own key rather than
 * overwriting the results the customer had before.
 */
export function deliveryScope(lat: number | null | undefined, lng: number | null | undefined): string {
    // `!= null`, not truthiness: Kenya straddles the equator and `!0` is true.
    if (lat == null || lng == null) return 'no-origin';
    return `${lat.toFixed(5)},${lng.toFixed(5)}`;
}

/**
 * Deliberately reads only the saved account, never `useLocation`.
 *
 * This runs inside ten query hooks, and `useLocation` asks for foreground
 * permission and takes a GPS fix — mounting that ten times over would prompt
 * the customer and spin the radio for a value the radius does not use anyway.
 * The origin is the saved address; see `services/delivery_point`.
 */
export function useDeliveryScope(): string {
    const { data: user } = useUserDetails();
    return deliveryScope(user?.lat, user?.lng);
}
