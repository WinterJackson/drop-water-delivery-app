import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '../../API/errors';
import { useApiRequest } from '../../API/useApiClient';
import RiderApiRoutes from '../../API/routes/RiderApiRoutes';
import { saveOrdersLocal, getOrdersLocal } from '../../config/database';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface RiderOrder {
    id: string;
    order_status: string;
    total_amount?: number;
    delivery_address: string;
    customer?: { full_name: string; phone_number: string };
    vendor?: { business_name: string; location_address: string; lat?: number; lng?: number };
    order_item?: { id: string; quantity: number; product?: { name: string } }[];
    rider_net?: number;
    rider_commission?: number;
    payload_surcharge?: number;
    staircase_surcharge?: number;
    vendor_net?: number;
    platform_total?: number;
    distance_km?: number;
    delivery_fee?: number;
    created_at?: string;
}

export interface RiderEarnings {
    total_earned: number;
    total_earnings: number;
    today_earned: number;
    week_earned: number;
    deliveries_count: number;
    total_deliveries: number;
    deliveries_last_7_days?: number;
    rating?: number;
    acceptance_rate?: number;
    is_platinum?: boolean;
    total_staircase_bonus?: number;
    total_payload_bonus?: number;
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
    acceptance_rate?: number;
    zone_changes_this_month?: number;
    last_zone_change?: string;
    operation_lat?: number;
    operation_lng?: number;
    payment_methods?: any[];
    preferences?: any;
    employer_vendor_id?: string;
    kyc_status?: string;
    wallet_balance?: number;
}

/**
 * The backend page size for `GET /api/rider/orders`. It has always accepted
 * `skip`/`limit`; the client passed neither, so a rider six months in could not
 * see anything past their most recent 50 deliveries — including for an earnings
 * dispute — with no empty state to explain the cut-off, so it read as data loss.
 */
export const RIDER_ORDERS_PAGE_SIZE = 50;

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
export function useRiderOrdersPaginated(status?: string) {
    const { get } = useApiRequest();
    return useInfiniteQuery<RiderOrder[], Error>({
        queryKey: ['rider', 'orders', 'paginated', status ?? 'all'],
        initialPageParam: 0,
        queryFn: async ({ pageParam }) => {
            const route = RiderApiRoutes.GetOrdersPaged(
                status,
                pageParam as number,
                RIDER_ORDERS_PAGE_SIZE
            );
            return get<RiderOrder[]>(route.path);
        },
        getNextPageParam: (lastPage, allPages) =>
            lastPage.length < RIDER_ORDERS_PAGE_SIZE
                ? undefined
                : allPages.reduce((n, page) => n + page.length, 0),
        staleTime: 1000 * 60 * 5,
    });
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
