import { useMemo } from 'react';
import { useUserDetails } from '@/hooks/queries/useUser';
import { useLocation } from '@/hooks/useLocation';

/**
 * Whether this app knows where to deliver, and therefore what it may show.
 *
 * Discovery on Drop is bounded by what can actually be delivered — 2.5 km for a
 * refill shop, 15 km for a depot — so every list on the home screen is measured
 * from one origin. `services/delivery_point.py` decides that origin server-side
 * and answers **nothing** when there isn't one. This is the client half of the
 * same rule, and the two shipped together on purpose: serving nothing is only an
 * honest answer if the app then asks for the missing thing instead of rendering
 * an empty shelf.
 *
 * Before this existed the app had no name for the state at all, and the two
 * halves of one screen disagreed about it. A customer with no saved address saw
 *
 *     ⚠️  Limited Coverage Area
 *         No vendors currently deliver to your location.
 *
 * — the four vendor endpoints having answered `[]` — directly above a grid of
 * products from stores 400 km away, because the product listings applied their
 * radius only "when coordinates are known" and unknown coordinates therefore
 * meant no radius at all. Each product was tappable, addable to a basket, and
 * refused at checkout once the basket was full.
 *
 * Three states, and they are genuinely different questions with genuinely
 * different answers:
 *
 * * `unknown` — we have not been told. This is a *question*, not a result, and
 *   it is the first-run state for every new customer. It is not a warning, and
 *   rendering it as one ("Limited Coverage Area") tells somebody their
 *   neighbourhood is unserved when the truth is that nobody has asked them where
 *   they live yet.
 * * `covered` — an address, and stores in range.
 * * `uncovered` — an address, and genuinely nothing in range. The only one of
 *   the three that is bad news, and the only one that should read like it.
 *
 * The saved address is what counts, not the device fix. It is what the server
 * measures from, what checkout enforces against and what the customer set
 * deliberately; a GPS reading is where the handset happens to be, which is a
 * different fact and frequently a different place. The live fix is still
 * reported, because a customer who has granted permission and has no saved
 * address can be offered a one-tap way to use it.
 */
export interface DeliveryLocation {
    /** True once the account carries a delivery address the server can measure from. */
    hasAddress: boolean;
    /** The address as the customer set it, for display. */
    address: string | null;
    /** A live device fix, when permission was granted and a fix has landed. */
    deviceFix: { lat: number; lng: number } | null;
    /**
     * True only once the account has actually been **read**.
     *
     * Every caller must wait on this, and it is deliberately not `!isPending`.
     * A request that failed is also not pending, and its `data` is also
     * `undefined` — so keying off pending alone reads a backend outage as
     * "this customer has no delivery address" and shows a brand-new-user prompt
     * to somebody who set their address months ago. That is the same mistake as
     * the banner this whole hook replaced: an unanswered question rendered as a
     * confident answer.
     *
     * Proven in the worst way. The database hit its compute quota mid-session,
     * every endpoint began answering 500, and the first build of this hook put
     * "Where should we deliver?" over an account whose address was on screen in
     * the header at the time.
     */
    isResolved: boolean;
    /** The account could not be read at all — neither state below is known. */
    isUnavailable: boolean;
}

export function useDeliveryLocation(): DeliveryLocation {
    const { data: user, isSuccess, isError } = useUserDetails();
    const { location } = useLocation();

    return useMemo(() => {
        const lat = user?.lat;
        const lng = user?.lng;
        // Both halves, and `!= null` rather than truthiness: latitude 0 is the
        // equator, which Kenya straddles, and `!0` is true. The server-side
        // guard had exactly this bug in four endpoints.
        const hasAddress = lat != null && lng != null;

        return {
            hasAddress,
            address: user?.location_address ?? null,
            deviceFix: location?.coords
                ? { lat: location.coords.latitude, lng: location.coords.longitude }
                : null,
            // `isSuccess`, not `!isPending`: only a read that came back tells us
            // anything about whether an address exists.
            isResolved: isSuccess,
            isUnavailable: isError,
        };
    }, [user?.lat, user?.lng, user?.location_address, location?.coords, isSuccess, isError]);
}
