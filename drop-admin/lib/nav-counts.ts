/**
 * Queue depths for the navigation badges.
 *
 * Mirrors `GET /api/admin/nav/counts`. Every key is **optional on purpose**: the
 * backend computes each figure only when the caller holds the capability that
 * opens the screen it belongs to, and omits the rest.
 *
 * So `undefined` means "you may not see this queue" and `0` means "nothing is
 * waiting". Rendering the two the same way would either invent a badge for a
 * page that would refuse the caller, or hide the genuinely useful fact that a
 * queue is clear.
 */
export type NavCounts = {
  rider_kyc?: number;
  vendor_verification?: number;
  orders_stuck?: number;
  disputes?: number;
  /** Tickets still `open`. A ticket an admin has replied to is `pending`. */
  support?: number;
  payouts?: number;
  payouts_stuck?: number;
  /** Failed payment callbacks nobody has handled — money in, order pending. */
  reconciliation?: number;
};

export type NavBadge = keyof NavCounts;

/** Empty is a valid, safe answer — the shell renders without badges. */
export const NO_COUNTS: NavCounts = {};
