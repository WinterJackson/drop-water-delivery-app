import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ROUTES } from "@/API/routes/ApiRoutes";
import { useApiRequest } from "@/API/useApiClient";

/**
 * The customer's bottle deposit, and getting it back.
 *
 * `bottle_deposit_balance` and `bottles_held` have been accurate since the day
 * they were added and appeared on no screen anybody could open. A balance a
 * customer cannot check is a balance they cannot trust, and a deposit they
 * cannot return is not a deposit — it is a price.
 *
 * Every figure here is the server's. Nothing on this screen re-derives what a
 * bottle is worth back: that is one function in `customer_bottle_service`,
 * shared with the console and the rider's collection, because three places
 * quoting different numbers for the same handover is a dispute the platform
 * cannot win.
 */

export type BottleCollection = {
  id: string;
  status:
    | "requested"
    | "assigned"
    | "awaiting_counterparty"
    | "settled"
    | "disputed"
    | "expired"
    | "cancelled";
  bottles_requested: number;
  bottles_stated_by_customer: number | null;
  bottles_stated_by_rider: number | null;
  bottles_settled: number | null;
  amount_refunded: string | null;
  rider_id: string | null;
  expires_at: string | null;
  settled_at: string | null;
  resolution_note: string | null;
  created_at: string | null;
};

export type BottleDepositSummary = {
  bottles_held: number;
  /** Decimal string. Never parsed to a number for display — see `sumMoney`. */
  deposit_balance: string;
  bottle_limit: number;
  wallet_balance: string;
  /**
   * The part of the wallet that buys water and cannot be withdrawn as cash: a
   * returned deposit. Stated on the screen rather than discovered at the
   * withdrawal form, because money you can spend and cannot cash out is a real
   * condition and the customer is entitled to know before relying on it.
   */
  wallet_not_withdrawable: string;
  /**
   * The terms this customer's withdrawal will actually be judged by, from the
   * same `withdrawal_terms` the withdrawal itself calls.
   *
   * The screen used to state its own — `MIN_WITHDRAWAL_KSH = 500`, under a
   * comment claiming it mirrored the server. The server's figure for a
   * customer is **1**, with no fee: it is their own unspent credit coming
   * back, not earnings. So the app was refusing, before any request was sent,
   * every withdrawal under KSH 500 that the platform would have paid — a rule
   * stated by an app that the platform does not implement, which is the exact
   * defect the rider and vendor wallets already had removed.
   */
  withdrawal: {
    minimum: string;
    fee: string;
    /** Measured against the amount withdrawn, never the balance held. */
    fee_waiver_threshold: string;
  };
  topup: { minimum: string };
  open_request: BottleCollection | null;
};

const KEY = ["bottleDeposit", "summary"] as const;

export const useBottleDeposit = () => {
  const api = useApiRequest();

  return useQuery<BottleDepositSummary, Error>({
    queryKey: KEY,
    queryFn: () => api.get<BottleDepositSummary>(ROUTES.BOTTLE_DEPOSIT_SUMMARY),
  });
};

export const useBookBottleCollection = () => {
  const api = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation<BottleCollection, Error, { bottles: number }>({
    mutationFn: (body) =>
      api.post<BottleCollection>(ROUTES.BOOK_BOTTLE_COLLECTION, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
    },
  });
};

/**
 * The customer's half of the two-sided handover.
 *
 * The deposit is returned when this count and the rider's agree. If they differ
 * it becomes a dispute a human looks at — nothing is split, and nothing moves —
 * so the number entered here matters and the screen asks for it explicitly
 * rather than assuming the booked figure.
 */
export const useConfirmBottleHandover = () => {
  const api = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation<
    { status: string; amount_refunded?: string; detail?: string },
    Error,
    { id: string; bottles: number }
  >({
    mutationFn: ({ id, bottles }) =>
      api.post(ROUTES.CONFIRM_BOTTLE_HANDOVER(id), { bottles }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
      // The refund lands as wallet balance, so the wallet and its ledger are
      // stale the moment this succeeds.
      queryClient.invalidateQueries({ queryKey: ["user"] });
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
    },
  });
};

export const useCancelBottleCollection = () => {
  const api = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation<{ status: string }, Error, { id: string }>({
    mutationFn: ({ id }) => api.del(ROUTES.CANCEL_BOTTLE_COLLECTION(id)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
    },
  });
};
