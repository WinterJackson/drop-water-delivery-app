import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { flattenPages, nextOffset } from '@/utils/paging';
import { useAuth } from '@clerk/clerk-expo';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
//
// Declared in `types/models.ts` and re-exported here so the many screens that
// import them from this hook keep working. They used to be *declared* here as
// well, a second copy of a wire shape that had already drifted eighteen fields
// away from the first — see the note on `Order` in that file.
export type { Order, OrderItem } from '@/types/models';
import type { Order, OrderTrackingLog } from '@/types/models';

// The status rules live in `constants/orderStatus.ts` — they are domain rules
// rather than a hook: they describe what a status *means*, they call nothing and
// they hold no state. Keeping them here meant that reading the order grouping
// dragged in Clerk, React Query and the whole API client. Re-exported so every
// existing import keeps working and there is still one name for each rule.
import { statusesFor, type OrderFilter } from '@/constants/orderStatus';

export {
    CANCELLABLE_ORDER_STATUSES,
    ORDER_STATUS_GROUPS,
    PENDING_PAYMENT_STATUSES,
    isAwaitingPayment,
    matchesOrderFilter,
    statusesFor,
    type OrderFilter,
} from '@/constants/orderStatus';

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

/** What the server did, reported back so the app never has to guess at it. */
export type CancelOrderResult = {
    message: string;
    order_id: string;
    /** Decimal string. `"0.00"` when nothing was charged. */
    penalty_charged: string;
    free_cancellations_remaining: number;
};

export function useCancelOrder() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation<CancelOrderResult, Error, string>({
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
    return useQuery<OrderTrackingLog[], Error>({
        queryKey: ['customer', 'orders', orderId, 'tracking', userId],
        queryFn: () => (orderId ? api.get<OrderTrackingLog[]>(ROUTES.ORDER_TRACKING_LOGS(orderId)) : Promise.resolve([])),
        enabled: !!orderId,
    });
}
