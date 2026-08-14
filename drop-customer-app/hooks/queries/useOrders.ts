import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { flattenPages, nextOffset } from '@/utils/paging';
import { useAuth } from '@clerk/clerk-expo';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface Order {
    id: string;
    order_status: string;
    total_amount: string;
    delivery_fee?: string;
    vehicle_class?: string;
    created_at: string;
    payment_method: string;
    payment_status?: string;
    delivery_address?: string;
    delivery_time?: number;
    delivery_type?: string;
    bottle_source?: string;
    customer_note?: string;
    payload_surcharge?: string;
    staircase_surcharge?: string;
    /** True once the customer has reviewed this order. Served by BaseOrder. */
    is_rated?: boolean;
    lat?: number;
    lng?: number;
    lat_from?: number;
    lng_from?: number;
    product_subtotal?: string;
    wallet_discount?: string;
    welcome_discount?: string;
    service_fee?: string;
    surge_fee?: string;
    distance_km?: number;
    vendor?: { id: string; business_name: string; location_address: string; profile_pic?: string; phone_number?: string; vendor_type?: string; lat?: number; lng?: number };
    deliverer?: { id: string; full_name: string; phone_number?: string; vehicle_details?: string };
    order_item?: OrderItem[];
}

export interface OrderItem {
    id: string;
    quantity: number;
    price: string;
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
 * The statuses a filter asks the *server* for, as the query string wants them.
 *
 * `GET /api/cart/get_orders?status=` takes a comma-separated group and validates
 * every name against the enum, so a typo here is a 400 rather than an empty
 * page. "All" sends nothing at all.
 */
export function statusesFor(filter: OrderFilter | 'All'): string | undefined {
    if (filter === 'All') return undefined;
    return (ORDER_STATUS_GROUPS[filter] as readonly string[]).join(',');
}

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

/**
 * Rows per request on the order history.
 *
 * The endpoint takes `skip` and `limit` and caps `limit` at 100. The app sent
 * neither, so it received the server's default 50 and stopped — a customer who
 * had ordered water weekly for a year could reach eleven months back and no
 * further, with nothing on the screen to say the list had ended early.
 */
export const ORDERS_PAGE_SIZE = 25;

// ─── Hooks ────────────────────────────────────────────────────────────────────

/**
 * The customer's order history, one status group at a time.
 *
 * **The filter is a query parameter, not a `.filter()`.** It used to be the
 * latter, over whatever page happened to be loaded, which is the failure mode
 * that only appears once a list is paged: tapping "Delivered" searched the
 * newest 25 orders and answered "No Delivered Orders" to somebody whose last
 * delivery was 26 orders ago. The same screen then said something different
 * after scrolling, which is worse than either answer on its own.
 *
 * Returns the infinite query; `orderRows(query.data)` flattens it.
 */
export function useOrders(filter: OrderFilter | 'All' = 'All') {
    const { userId } = useAuth();
    const api = useApiRequest();
    const status = statusesFor(filter);

    return useInfiniteQuery<Order[], Error>({
        queryKey: ['customer', 'orders', userId, filter],
        initialPageParam: 0,
        queryFn: ({ pageParam }) =>
            api.get<Order[]>(ROUTES.GET_ORDERS, {
                params: {
                    skip: pageParam as number,
                    limit: ORDERS_PAGE_SIZE,
                    ...(status ? { status } : {}),
                },
            }),
        getNextPageParam: nextOffset<Order>(ORDERS_PAGE_SIZE),
        staleTime: 1000 * 60 * 5, // 5 min — matches global default; WebSocket handles real-time
        // Multiple screens (Orders, OrderDetail, Map) keep this query mounted at
        // once. Without this, every mount/focus refetches data already cached.
        refetchOnMount: false,
    });
}

/** Every order fetched so far, newest first, each appearing once. */
export function orderRows(data: InfiniteData<Order[]> | undefined): Order[] {
    return flattenPages<Order>(data);
}

/** Statuses an order can never move out of. Nothing more will happen to it. */
const TERMINAL_ORDER_STATUSES: readonly string[] = ['delivered', 'cancelled', 'rejected'];

/**
 * One order, fetched by id.
 *
 * Never find an order by searching `useOrders()` — that list is a page, and the
 * order somebody has just tapped a notification about is usually not on it.
 *
 * It refreshes itself while the order is still live. The detail screen used to
 * read out of the *list* query, so it inherited whatever the Orders screen's
 * socket had refetched; opened straight from a push notification, with the
 * Orders screen never mounted, it inherited nothing and sat on the app's
 * five-minute default. This is the screen somebody watches while their water is
 * on the way — a vendor accepting, a rider picking up, and the order arriving
 * all have to show up without them backing out and coming in again. Polling
 * stops the moment the order reaches a state it cannot leave.
 */
export function useOrder(orderId: string | null | undefined) {
    const api = useApiRequest();
    return useQuery<Order, Error>({
        queryKey: ['customer', 'order', orderId],
        queryFn: () => api.get<Order>(ROUTES.GET_ORDER(orderId!)),
        enabled: !!orderId,
        staleTime: 15 * 1000,
        refetchInterval: (query) => {
            const status = query.state.data?.order_status;
            if (status && TERMINAL_ORDER_STATUSES.includes(status)) return false;
            return 20 * 1000;
        },
    });
}

export function useCancelOrder() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (orderId: string) => api.put(ROUTES.CANCEL_ORDER(orderId)),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
            // …and the by-id copy the detail screen is looking at right now.
            queryClient.invalidateQueries({ queryKey: ['customer', 'order'] });
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
            queryClient.invalidateQueries({ queryKey: ['customer', 'order'] });
        },
    });
}

export interface PaymentHistoryEntry {
    /**
     * The *payment's* id — `cash-<order id>` for a cash order, which produces
     * no Payment row. Never route on it: use `order_id`.
     */
    id: string;
    order_id: string;
    order_reference: string;
    vendor_name: string | null;
    /** Decimal string. Render with `formatMoney`; never parse it to a number. */
    amount: string;
    status: string;
    payment_method: string;
    mpesa_receipt: string | null;
    failure_reason: string | null;
    created_at: string | null;
}

/** Rows per request on the payment history. The endpoint caps `limit` at 100. */
export const PAYMENTS_PAGE_SIZE = 25;

/**
 * The customer's payment history, page by page.
 *
 * Sent no `limit`, so it took the server's default 50 and stopped there. That
 * screen is where somebody goes to find the M-Pesa receipt for a disputed order,
 * which is exactly the order far enough back to have fallen off the end.
 */
export function usePaymentHistory() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useInfiniteQuery<PaymentHistoryEntry[], Error>({
        queryKey: ['customer', 'payments', userId],
        initialPageParam: 0,
        queryFn: ({ pageParam }) =>
            api.get<PaymentHistoryEntry[]>(ROUTES.GET_PAYMENT_HISTORY, {
                params: { offset: pageParam as number, limit: PAYMENTS_PAGE_SIZE },
            }),
        getNextPageParam: nextOffset<PaymentHistoryEntry>(PAYMENTS_PAGE_SIZE),
    });
}

/** Every payment fetched so far, newest first, each appearing once. */
export function paymentRows(data: InfiniteData<PaymentHistoryEntry[]> | undefined): PaymentHistoryEntry[] {
    return flattenPages<PaymentHistoryEntry>(data);
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
