/**
 * One description of every order status the platform can produce.
 *
 * `Orders.tsx` and `OrderDetail/[id].tsx` each kept their own colour maps, and
 * neither listed `mismatch_pending` or `pending_review`. Both states are
 * reachable in ordinary operation — a rider flags a damaged empty, or reports
 * that the customer understated their floor — and the order parks there until
 * someone resolves it. The vendor saw a blank pill spelling out the raw enum
 * value, with no explanation, while their stock was committed and their money
 * pending.
 *
 * Two maps in two files is exactly how a status gets added to the backend and
 * missed in both. There is one here now, and the filter row is built from it.
 */

export interface OrderStatusStyle {
  /** Sentence case, for a human. Not the raw enum value. */
  label: string;
  pill: string;
  text: string;
  /**
   * What the vendor should understand is happening. Present only for states
   * that are not self-explanatory — nobody needs "delivered" explained.
   */
  explanation?: string;
}

export const ORDER_STATUS: Record<string, OrderStatusStyle> = {
  pending: {
    label: "Pending",
    pill: "bg-yellow-500/20",
    text: "text-yellow-600",
    explanation: "Waiting for you to accept or reject this order.",
  },
  unassigned: {
    label: "Finding a rider",
    pill: "bg-orange-500/20",
    text: "text-orange-600",
    explanation: "Paid and waiting for a rider to accept the trip.",
  },
  accepted: {
    label: "Accepted",
    pill: "bg-accentbg/20",
    text: "text-accentbg",
  },
  preparing: {
    label: "Preparing",
    pill: "bg-purple-500/20",
    text: "text-purple-600",
  },
  ready: {
    label: "Ready",
    pill: "bg-green-500/20",
    text: "text-green-600",
    explanation: "Waiting for the rider to collect it.",
  },
  picked_up: {
    label: "On the way",
    pill: "bg-blue-500/20",
    text: "text-blue-600",
  },
  delivered: {
    label: "Delivered",
    pill: "bg-green-500/20",
    text: "text-green-600",
  },
  rejected: {
    label: "Rejected",
    pill: "bg-red-500/20",
    text: "text-red-600",
  },
  cancelled: {
    label: "Cancelled",
    pill: "bg-red-500/20",
    text: "text-red-600",
  },
  refund_pending: {
    label: "Refund pending",
    pill: "bg-orange-500/20",
    text: "text-orange-600",
    explanation: "The customer paid, so their money is being returned.",
  },
  refunded: {
    label: "Refunded",
    pill: "bg-slate-500/20",
    text: "text-slate-600",
  },

  // ── Paused for review ───────────────────────────────────────────────────
  // Neither of these appeared anywhere in this app before.
  mismatch_pending: {
    label: "Floor dispute",
    pill: "bg-amber-500/20",
    text: "text-amber-600",
    explanation:
      "The rider says the delivery floor is higher than the customer stated. The customer has to accept the extra charge or come down before the delivery continues.",
  },
  pending_review: {
    label: "Under review",
    pill: "bg-amber-500/20",
    text: "text-amber-600",
    explanation:
      "The rider flagged a damaged or missing empty bottle. Support is reviewing their photos — this usually resolves within a few minutes.",
  },
};

const FALLBACK: OrderStatusStyle = {
  label: "Unknown",
  pill: "bg-slate-200",
  text: "text-slate-600",
};

/** Never returns undefined: a status we have not met yet still needs a pill. */
export function orderStatusStyle(status?: string | null): OrderStatusStyle {
  if (!status) return FALLBACK;
  return ORDER_STATUS[status] ?? { ...FALLBACK, label: status.replace(/_/g, " ") };
}

/** True while the order is parked waiting on someone else's decision. */
export function isUnderReview(status?: string | null): boolean {
  return status === "pending_review" || status === "mismatch_pending";
}

/**
 * The filter row on the Orders screen.
 *
 * `id` is sent to the backend as `status_filter`, which compares it lowercased
 * against `Order.order_status` — so it has to be the enum value, not the label.
 */
export const ORDER_FILTERS: { id: string; label: string }[] = [
  { id: "All", label: "All Orders" },
  { id: "pending", label: "Pending" },
  { id: "accepted", label: "Accepted" },
  { id: "preparing", label: "Preparing" },
  { id: "ready", label: "Ready" },
  // Added: without it there was no way to find an order that had stopped, which
  // is the one kind a vendor most needs to go looking for.
  { id: "pending_review", label: "Under review" },
  { id: "mismatch_pending", label: "Floor dispute" },
  { id: "cancelled", label: "Cancelled" },
];
