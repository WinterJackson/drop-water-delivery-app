import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

import { ApiError } from '../../API/errors';
import { useApiRequest } from '../../API/useApiClient';
import RiderApiRoutes from '../../API/routes/RiderApiRoutes';
import { flattenPages, nextOffset } from '../../utils/paging';
import { saveOrdersLocal, getOrdersLocal } from '../../config/database';

// ─── Types ────────────────────────────────────────────────────────────────────

/**
 * The customer, as `schemas/user_schemas.py::CustomerPublicProfile`.
 *
 * The field on the wire is **`user`**, not `customer` — `GET /rider/orders`
 * answers with `OrderWithDetails`, which adds exactly this. `RiderOrder`
 * declared a `customer` the server has never sent, and two screens read it: the
 * orders list rendered "3 items for Customer" for every order on the platform,
 * and the active-delivery search matched no customer name ever typed into it.
 */
export interface RiderOrderCustomer {
    id: string;
    full_name?: string | null;
    phone_number?: string | null;
    location_address?: string | null;
    floor_level?: number | null;
    has_elevator?: boolean | null;
    profile_pic?: string | null;
}

/** `schemas/order_schema.py::OrderVendorSnippet`. */
export interface RiderOrderVendor {
    id: string;
    business_name: string;
    profile_pic?: string | null;
    vendor_type?: string | null;
    location_address?: string | null;
    lat?: number | null;
    lng?: number | null;
    rating?: number | null;
    phone_number?: string | null;
}

/** `schemas/order_schema.py::OrderItemBase`. */
export interface RiderOrderItem {
    id: string;
    order_id?: string;
    product_id?: string;
    quantity: number;
    /** Decimal string. */
    price?: string;
    /** Decimal string, capitalised on the wire exactly as the schema declares it. */
    Subtotal?: string;
    product?: { id: string; name: string; image_url?: string; capacity?: number } | null;
}

export interface RiderOrder {
    id: string;
    order_status: string;
    total_amount?: string;
    delivery_address: string;
    user?: RiderOrderCustomer | null;
    vendor?: RiderOrderVendor | null;
    order_item?: RiderOrderItem[];
    /**
     * `quick_swap` | `exchange` | `refill_mine` | `new_bottle`. It decides how
     * many empties the rider is expected to collect, and it was not declared
     * here — so `activeOrder?.delivery_type === 'quick_swap'` was comparing
     * `undefined`, and the empties counter opened at **0 on every swap order**,
     * i.e. the count the rider is asked to confirm started at the wrong number
     * on exactly the orders where a count is the point.
     */
    delivery_type?: string | null;
    /** `cash` | `mpesa`. Drives the "Collect Cash" banner on the delivery sheet. */
    payment_method?: string | null;
    rider_net?: string;
    rider_commission?: string;
    payload_surcharge?: string;
    staircase_surcharge?: string;
    vendor_net?: string;
    platform_total?: string;
    distance_km?: number;
    delivery_fee?: string;
    created_at?: string;

    // Persisted to the offline SQLite cache by `saveOrdersLocal`, and therefore
    // the copy the rider reads with no signal. All six come from `BaseOrder` on
    // the server and were simply never declared here — so the writes typechecked
    // as `any[]` and nothing said whether the columns behind them were real.
    vendor_id?: string;
    customer_id?: string;
    updated_at?: string | null;
    phone?: string | null;
    lat_from?: number | null;
    lng_from?: number | null;
    lat?: number | null;
    lng?: number | null;
    payment_status?: string | null;
}

export interface RiderEarnings {
    /**
     * Lifetime earnings, as a decimal **string**.
     *
     * `total_earned`, `today_earned` and `week_earned` used to sit beside this
     * one. The server has never sent any of the three and no screen has ever
     * read them — nor has `deliveries_count`. They were an interface describing
     * a wire shape that does not exist, which typechecks perfectly and is
     * exactly how the customer app ended up with two `Order`s eighteen fields
     * apart.
     */
    total_earnings: string;
    total_deliveries: number;
    /** @deprecated Counted over `platinum_window_days`, which defaults to 7. Use `deliveries_in_window`. */
    deliveries_last_7_days?: number;
    /** Deliveries inside the trailing Platinum window. */
    deliveries_in_window?: number;
    /**
     * What Platinum takes, from `Platform_Settings` — the same two rows the
     * nightly `rider_tier_job` evaluates against. Both were literals in this
     * app (20 deliveries, 7 days), so raising the bar on the console would have
     * kept telling riders the old number while demoting them against the new.
     */
    platinum_target?: number;
    platinum_window_days?: number;
    rating?: number;
    /** How many ratings the average is made of. `0` means nobody has rated this rider — `Deliverer.rating` starts at 5.0 by policy, so the average alone cannot say. */
    rating_count?: number;
    acceptance_rate?: number;
    is_platinum?: boolean;
    /**
     * Decimal strings. Both were `float()`-cast off a `SUM()` on the server and
     * typed `number` here — the two halves agreeing with each other and both
     * disagreeing with the rule.
     */
    total_staircase_bonus?: string;
    total_payload_bonus?: string;
}

/**
 * A payout destination on `Deliverer.payment_methods` (a JSONB list).
 *
 * Not a schema on the server — the column is free-form JSON — so this is the
 * shape the app itself writes and reads, and it is the only description of it
 * that exists. `any[]` here meant the one thing the rider's money is sent to
 * had no declared shape anywhere in the platform.
 */
export interface RiderPayoutMethod {
    type: "mpesa";
    phone: string;
    isDefault?: boolean;
}

/** `Deliverer.preferences` (JSONB). Absent means both on. */
export interface RiderPreferences {
    orderUpdates?: boolean;
    analytics?: boolean;
}

export interface RiderProfile {
    id: string;
    full_name: string;
    name?: string;
    email: string;
    phone_number: string;
    profile_pic?: string;
    is_available: boolean;
    is_platinum?: boolean;
    plate_number?: string;
    vehicle_type?: string;
    rating?: number;
    /** How many ratings the average is made of. `0` means nobody has rated this rider — `Deliverer.rating` starts at 5.0 by policy, so the average alone cannot say. */
    rating_count?: number;
    acceptance_rate?: number;
    zone_changes_this_month?: number;
    last_zone_change?: string;
    operation_lat?: number;
    operation_lng?: number;
    /**
     * How far from their base this rider is offered work, in km — the figure
     * `rider_search_bounds` actually searches with. Served rather than drawn
     * from a literal, so the circle on `OperationBase` matches dispatch.
     */
    operation_radius_km?: number;
    payment_methods?: RiderPayoutMethod[];
    preferences?: RiderPreferences;
    employer_vendor_id?: string;
    kyc_status?: string;
    wallet_balance?: string;
}

/**
 * The backend page size for `GET /api/rider/orders`. It has always accepted
 * `skip`/`limit`; the client passed neither, so a rider six months in could not
 * see anything past their most recent 50 deliveries — including for an earnings
 * dispute — with no empty state to explain the cut-off, so it read as data loss.
 */
export const RIDER_ORDERS_PAGE_SIZE = 50;

/**
 * The two tabs on My Deliveries, as sets of order statuses.
 *
 * These were spelled inline in the screen and used to split one unpaged fetch
 * with two `.filter()` calls. Between them they named ten of the platform's
 * eleven statuses, so a status added on the server — or the one already
 * missing — put an order in *neither* tab and it disappeared from the rider's
 * app entirely while still being theirs to deliver. Keeping them here, adjacent
 * and exhaustive, is what makes that checkable; `test_route_contract.py`'s
 * sibling `test_rider_order_tabs_cover_every_status` asserts it.
 *
 * `unassigned` is deliberately absent: an unassigned order has no rider, so it
 * cannot appear in a list scoped to `deliverer_id`. It reaches riders through
 * the Trip Radar instead.
 */
export const RIDER_ORDER_TABS = {
    Incoming: [
        'pending', 'accepted', 'preparing', 'ready', 'picked_up',
        'mismatch_pending', 'pending_review',
    ],
    History: ['delivered', 'cancelled', 'rejected'],
} as const;

export type RiderOrderTab = keyof typeof RIDER_ORDER_TABS;

/** The statuses a tab asks the server for, as `?status=` wants them. */
export function statusesForTab(tab: RiderOrderTab): string {
    return (RIDER_ORDER_TABS[tab] as readonly string[]).join(',');
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

/**
 * The rider's current orders.
 *
 * Deliberately *not* paginated: this feeds `ActiveDelivery`, which needs the
 * live set, not a history. Use `useRiderOrdersPaginated` for the history screens.
 */
export function useRiderOrders() {
    const { get } = useApiRequest();
    return useQuery<RiderOrder[], Error>({
        queryKey: ['rider', 'orders'],
        queryFn: async () => {
            const route = RiderApiRoutes.GetOrders();
            try {
                const data = await get<RiderOrder[]>(route.path);
                saveOrdersLocal(data).catch(() => {});
                return data;
            } catch (e) {
                // A refusal is real and must surface. A *transport* failure means
                // the rider is in a coverage hole mid-shift, and the on-disk
                // manifest is the whole reason it exists.
                if (e instanceof ApiError && !e.isNetworkError) throw e;
                const localOrders = await getOrdersLocal();
                if (localOrders && localOrders.length > 0) {
                    return localOrders as RiderOrder[];
                }
                throw e;
            }
        },
        staleTime: 1000 * 60,
    });
}

/**
 * Delivery history, page by page.
 *
 * `FlashList`'s `onEndReached` drives `fetchNextPage`; a short final page means
 * the end, which is the only signal the endpoint gives.
 */
export function useRiderOrdersPaginated(status?: string, searchQuery?: string) {
    const { get } = useApiRequest();
    const search = (searchQuery ?? '').trim();

    return useInfiniteQuery<RiderOrder[], Error>({
        queryKey: ['rider', 'orders', 'paginated', status ?? 'all', search],
        initialPageParam: 0,
        queryFn: async ({ pageParam }) => {
            const route = RiderApiRoutes.GetOrdersPaged(
                status,
                pageParam as number,
                RIDER_ORDERS_PAGE_SIZE,
                search || undefined,
            );
            return get<RiderOrder[]>(route.path);
        },
        getNextPageParam: nextOffset<RiderOrder>(RIDER_ORDERS_PAGE_SIZE),
        staleTime: 1000 * 60 * 5,
    });
}

/** Every order fetched so far, newest first, each appearing once. */
export function riderOrderRows(data: InfiniteData<RiderOrder[]> | undefined): RiderOrder[] {
    return flattenPages<RiderOrder>(data);
}

export function useRiderEarningsHistory() {
    const { get } = useApiRequest();
    return useQuery<RiderOrder[], Error>({
        queryKey: ['rider', 'orders', 'delivered'],
        queryFn: () => get<RiderOrder[]>(RiderApiRoutes.GetOrders("delivered").path),
        staleTime: 1000 * 60 * 5, // Cache longer since historical data changes rarely
    });
}

/** Paginated delivered orders, for the earnings history screen. */
export function useEarningsHistoryPaginated() {
    return useRiderOrdersPaginated("delivered");
}

export function useTripRadar() {
    const { get } = useApiRequest();
    return useQuery<RiderOrder[], Error>({
        queryKey: ['rider', 'trip_radar'],
        queryFn: () => get<RiderOrder[]>(RiderApiRoutes.TripRadar.path),
        staleTime: 1000 * 5,
    });
}

export function useRiderEarnings() {
    const { get } = useApiRequest();
    return useQuery<RiderEarnings, Error>({
        queryKey: ['rider', 'earnings'],
        queryFn: () => get<RiderEarnings>(RiderApiRoutes.GetEarnings.path),
        staleTime: 1000 * 30,
    });
}

export function useRiderProfile() {
    const { get } = useApiRequest();
    return useQuery<RiderProfile, Error>({
        queryKey: ['rider', 'profile'],
        queryFn: () => get<RiderProfile>(RiderApiRoutes.GetProfile.path),
        staleTime: 1000 * 60 * 2,
    });
}

export function useAcceptOrder() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (orderId: string) => post(RiderApiRoutes.AcceptDelivery(orderId).path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
            queryClient.invalidateQueries({ queryKey: ['rider', 'trip_radar'] });
        },
        onError: () => {
            // Immediately refresh the radar so the stale/claimed card disappears
            queryClient.invalidateQueries({ queryKey: ['rider', 'trip_radar'] });
        },
    });
}

export interface RiderReview {
    id: string;
    order_id: string;
    rating: number;
    comment: string | null;
    created_at: string | null;
}

export interface RiderReviewsResponse {
    total_reviews: number;
    average_rating: number;
    distribution: {
        [key: string]: number;
    };
    reviews: RiderReview[];
}

export function useRiderReviews() {
    const { get } = useApiRequest();
    return useQuery<RiderReviewsResponse, Error>({
        queryKey: ['rider', 'reviews'],
        queryFn: () => get<RiderReviewsResponse>(RiderApiRoutes.GetReviews.path),
        staleTime: 1000 * 60 * 5, // 5 minutes
    });
}
