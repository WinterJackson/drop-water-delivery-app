/**
 * Queue shape for the page headers.
 *
 * Mirrors `GET /api/admin/queues/stats`. Every key is **optional on purpose**,
 * exactly like `NavCounts`: the backend computes each queue only when the caller
 * holds the capability that opens it, and omits the rest.
 *
 * So `undefined` means "you may not see this queue" — render nothing. A header
 * reading "21 waiting" above a page that would refuse the caller leaks the size
 * of a table they cannot see.
 *
 * `null` inside a queue means the figure is genuinely unanswerable: no oldest
 * item because nothing is waiting, no approval rate because nothing has been
 * decided. It is never coerced to zero — "nothing decided yet" and "everything
 * rejected" are different facts.
 */

export type RiderKycStats = {
  waiting: number;
  oldest_wait_minutes: number | null;
  decided_24h: number;
  approved: number;
  rejected: number;
  approval_rate: number | null;
  never_submitted: number;
  total: number;
};

export type VendorVerificationStats = {
  waiting: number;
  oldest_wait_minutes: number | null;
  approved: number;
  rejected: number;
  approval_rate: number | null;
  suspended: number;
  total: number;
};

export type DisputeStats = {
  waiting: number;
  oldest_wait_minutes: number | null;
  decided_24h: number;
  upheld: number;
  denied: number;
  uphold_rate: number | null;
  total: number;
};

export type PayoutStats = {
  waiting: number;
  waiting_value: string;
  oldest_wait_minutes: number | null;
  largest_pending: string;
  paid_24h: number;
  paid_24h_value: string;
  failed: number;
  failed_value: string;
  processing: number;
};

export type SupportStats = {
  waiting: number;
  oldest_wait_minutes: number | null;
  awaiting_requester: number;
  resolved_24h: number;
  unassigned: number;
  total: number;
};

export type QueueStats = {
  rider_kyc?: RiderKycStats;
  vendor_verification?: VendorVerificationStats;
  disputes?: DisputeStats;
  payouts?: PayoutStats;
  support?: SupportStats;
};
