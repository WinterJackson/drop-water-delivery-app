/**
 * The customer's view of the order state machine.
 *
 * The state machine is `pending → unassigned → accepted → preparing → ready →
 * picked_up → delivered`, plus the two deviations `pending_review` (rider
 * flagged a bottle mismatch) and `mismatch_pending` (address mismatch).
 *
 * The filters used to name statuses inline and between them covered only
 * `pending`, `unassigned`, `picked_up`, `mismatch_pending`, `delivered`,
 * `cancelled` and `rejected` — so an order the vendor had accepted and was
 * preparing matched *no* filter and was visible only under "All". That is the
 * window a customer is most likely to be checking.
 *
 * These live here rather than in `hooks/queries/useOrders` because they are
 * domain rules, not a hook: they describe what a status *means*, they call
 * nothing and they hold no state. Keeping them in the hook meant that reading
 * the order grouping dragged in Clerk, React Query and the whole API client —
 * which made a pure assertion about status names take forty-five seconds and
 * leave a live handle behind. The vendor app has always kept its statuses in
 * `constants/orderStatus.ts`; this is the same arrangement.
 *
 * Keep these exhaustive: `ORDER_STATUS_GROUPS` is asserted to cover every
 * status the backend can return.
 */

/** The minimum an order needs for the rules below to classify it. */
export interface ClassifiableOrder {
    order_status: string;
    payment_method?: string | null;
    payment_status?: string | null;
}

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

export function isAwaitingPayment(order?: ClassifiableOrder | null): boolean {
    if (!order) return false;
    if (order.payment_method !== 'mpesa') return false;
    if (['cancelled', 'rejected', 'delivered'].includes(order.order_status)) return false;
    return PENDING_PAYMENT_STATUSES.includes(order.payment_status ?? 'pending');
}
