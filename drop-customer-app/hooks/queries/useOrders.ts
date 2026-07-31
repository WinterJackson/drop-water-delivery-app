import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useAuth } from '@clerk/clerk-expo';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface Order {
    id: string;
    order_status: string;
    total_amount: number;
    delivery_fee?: number;
    vehicle_class?: string;
    created_at: string;
    payment_method: string;
    payment_status?: string;
    delivery_address?: string;
    delivery_time?: number;
    delivery_type?: string;
    bottle_source?: string;
    customer_note?: string;
    payload_surcharge?: number;
    staircase_surcharge?: number;
    /** True once the customer has reviewed this order. Served by BaseOrder. */
    is_rated?: boolean;
    lat?: number;
    lng?: number;
    lat_from?: number;
    lng_from?: number;
    product_subtotal?: number;
    wallet_discount?: number;
    welcome_discount?: number;
    service_fee?: number;
    surge_fee?: number;
    distance_km?: number;
    vendor?: { id: string; business_name: string; location_address: string; profile_pic?: string; phone_number?: string; vendor_type?: string; lat?: number; lng?: number };
    deliverer?: { id: string; full_name: string; phone_number?: string; vehicle_details?: string };
    order_item?: OrderItem[];
}

export interface OrderItem {
    id: string;
    quantity: number;
    price: number;
    product?: { name: string; image_url: string };
}

/**
 * Every order status, grouped the way the Orders screen filters them.
 *
 * The state machine is `pending → unassigned → accepted → preparing → ready →
 * picked_up → delivered`, plus the two deviations `pending_review` (rider flagged
 * a bottle mismatch) and `mismatch_pending` (address mismatch).
 *
 * The filters used to name statuses inline and between them covered only
 * `pending`, `unassigned`, `picked_up`, `mismatch_pending`, `delivered`,
 * `cancelled` and `rejected` — so an order the vendor had accepted and was
 * preparing matched *no* filter and was visible only under "All". That is the
 * window a customer is most likely to be checking.
 *
 * Keep these exhaustive: `ORDER_STATUS_GROUPS` is asserted to cover every status
 * the backend can return.
 */
export const ORDER_STATUS_GROUPS = {
    // Placed, but nobody is working on it yet.
    Pending: ['pending', 'unassigned'],
    // Somebody is working on it: accepted through to on the road, including the
    // two paused states, which resume rather than terminate.
    'In Transit': ['accepted', 'preparing', 'ready', 'picked_up', 'pending_review', 'mismatch_pending'],
    Delivered: ['delivered'],
    Cancelled: ['cancelled', 'rejected'],
} as const;

export type OrderFilter = keyof typeof ORDER_STATUS_GROUPS;

/**
 * Statuses the backend will actually let a customer cancel.
 *
 * `cancel_customer_order` allows exactly these three and 400s on anything else,
 * so offering the button elsewhere just produces a rejection. Cancelling an
 * `accepted` order carries a late-cancellation fee — the backend says so in its
 * response, which the UI surfaces verbatim.
 */
export const CANCELLABLE_ORDER_STATUSES: readonly string[] = ['pending', 'unassigned', 'accepted'];

export function matchesOrderFilter(status: string, filter: OrderFilter | 'All'): boolean {
    if (filter === 'All') return true;
    return (ORDER_STATUS_GROUPS[filter] as readonly string[]).includes(status);
}

/** Payment states where the customer still owes us an action or an outcome. */
export const PENDING_PAYMENT_STATUSES = ['pending', 'processing'];

export function isAwaitingPayment(order?: Order | null): boolean {
    if (!order) return false;
    if (order.payment_method !== 'mpesa') return false;
    if (['cancelled', 'rejected', 'delivered'].includes(order.order_status)) return false;
    return PENDING_PAYMENT_STATUSES.includes(order.payment_status ?? 'pending');
}

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useOrders() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<Order[], Error>({
        queryKey: ['customer', 'orders', userId],
        queryFn: () => api.get<Order[]>(ROUTES.GET_ORDERS),
        staleTime: 1000 * 60 * 5, // 5 min — matches global default; WebSocket handles real-time
        // Multiple screens (Orders, OrderDetail, Map) keep this query mounted at
        // once. Without this, every mount/focus refetches data already cached.
        refetchOnMount: false,
    });
}

export function useCancelOrder() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (orderId: string) => api.put(ROUTES.CANCEL_ORDER(orderId)),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
            // The cart and wallet both change on cancellation (stock returns,
            // wallet credit is refunded), so their caches are stale now too.
            queryClient.invalidateQueries({ queryKey: ['cart'] });
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            queryClient.invalidateQueries({ queryKey: ['walletTransactions'] });
        },
    });
}

export function useResolveMismatch() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ orderId, action }: { orderId: string; action: string }) =>
            api.patch(ROUTES.RESOLVE_MISMATCH(orderId), { action }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
        },
    });
}

export interface PaymentHistoryEntry {
    id: string;
    order_id: string;
    order_reference: string;
    vendor_name: string | null;
    amount: number;
    status: string;
    payment_method: string;
    mpesa_receipt: string | null;
    failure_reason: string | null;
    created_at: string | null;
}

export function usePaymentHistory() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<PaymentHistoryEntry[], Error>({
        queryKey: ['customer', 'payments', userId],
        queryFn: () => api.get<PaymentHistoryEntry[]>(ROUTES.GET_PAYMENT_HISTORY),
    });
}

export function useLastCompletedOrder() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<Order | null, Error>({
        queryKey: ['customer', 'orders', 'last-completed', userId],
        queryFn: () => api.get<Order | null>(ROUTES.GET_LAST_COMPLETED_ORDER),
        staleTime: 60000,
    });
}

export function useActiveOrder() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<Order | null, Error>({
        queryKey: ['customer', 'orders', 'active', userId],
        queryFn: () => api.get<Order | null>(ROUTES.GET_ACTIVE_ORDER),
        staleTime: 60000,
    });
}

export function useOrderTrackingLogs(orderId: string | null) {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<any[], Error>({
        queryKey: ['customer', 'orders', orderId, 'tracking', userId],
        queryFn: () => (orderId ? api.get<any[]>(ROUTES.ORDER_TRACKING_LOGS(orderId)) : Promise.resolve([])),
        enabled: !!orderId,
    });
}
