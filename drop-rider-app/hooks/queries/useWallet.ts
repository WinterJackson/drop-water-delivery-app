import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApiRequest } from "@/API/useApiClient";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";

export interface WalletTransaction {
  id: string;
  /** Decimal string — the ledger's own figure. */
  amount: string;
  transaction_type: string;
  description?: string | null;
  status?: string | null;
  created_at?: string | null;
}

export const useWalletTransactions = (limit = 50, offset = 0) => {
  const { get } = useApiRequest();

  return useQuery<WalletTransaction[], Error>({
    queryKey: ["walletTransactions", limit, offset],
    queryFn: async () => {
      const response = await get<{ data: WalletTransaction[] } | WalletTransaction[]>(
        `${RiderApiRoutes.GetTransactions.path}?limit=${limit}&offset=${offset}`
      );
      // The backend wraps the array in `{ data: [...], nextCursor, ... }`.
      // Extract it so every consumer receives a plain array.
      if (response && !Array.isArray(response) && Array.isArray((response as any).data)) {
        return (response as any).data;
      }
      return Array.isArray(response) ? response : [];
    },
  });
};

export const useWalletTransactionsPaginated = (search: string, type: string, limit = 20) => {
  const { get } = useApiRequest();

  return useInfiniteQuery({
    queryKey: ["walletTransactions", search, type, limit],
    queryFn: async ({ pageParam = 0 }) => {
      let url = `${RiderApiRoutes.GetTransactions.path}?limit=${limit}&offset=${pageParam}`;
      if (search) url += `&search=${encodeURIComponent(search)}`;
      if (type && type !== "All") url += `&type=${encodeURIComponent(type)}`;
      return get<any>(url);
    },
    getNextPageParam: (lastPage: any) => lastPage?.nextCursor ?? undefined,
    initialPageParam: 0,
  });
};

export const useWalletWithdraw = () => {
  const { post } = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    // `amount` is a decimal string — money does not become a JS number to
    // cross a wire, on the way out any more than on the way in.
    mutationFn: ({ amount, phoneNumber, userType }: { amount: string, phoneNumber: string, userType: string }) =>
      post(RiderApiRoutes.WalletWithdraw.path, {
        amount,
        phone_number: phoneNumber,
        user_type: userType,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
      queryClient.invalidateQueries({ queryKey: ["rider", "profile"] });
      // The withdrawal moves the balance, so the float split the Cashout screen
      // renders is stale the moment this succeeds.
      queryClient.invalidateQueries({ queryKey: ["rider", "wallet-summary"] });
    },
  });
};

/**
 * Balance split into what is spendable and what is committed as float to cash
 * orders the rider is still carrying.
 *
 * Accepting a cash order commits `vendor_net + platform_total` from the rider's
 * wallet, settled when they deliver. That money is not withdrawable in the
 * meantime — showing only the raw balance made a refused withdrawal look
 * arbitrary, and previously the platform allowed the withdrawal anyway and ate
 * the shortfall.
 */
export interface RiderWalletSummary {
    /** Decimal strings. Render with `formatMoney`; compare with `compareMoney`. */
    wallet_balance: string;
    committed_cash_float: string;
    available_for_withdrawal: string;
    /**
     * The rules this withdrawal will be judged by, from `Platform_Settings`.
     *
     * All three were literals in `Cashout.tsx` — a minimum of 500, a fee of 15
     * and a waiver at 1,000 — so editing any of them on the console changed what
     * a rider was charged and not what they were told. Business values are rows.
     *
     * `fee_waiver_threshold` is compared against the **amount withdrawn**, never
     * the balance held; see `settlement_service.fee_for`.
     */
    /** The floor an STK push may be raised for — `min_wallet_topup`. */
    topup?: { minimum: string };
    withdrawal?: {
      minimum: string;
      fee: string;
      fee_waiver_threshold: string;
    };
    /** Negative balance: the rider owes the platform and cannot take cash orders. */
    is_in_arrears: boolean;
}

export function useWalletSummary() {
    const { get } = useApiRequest();
    return useQuery<RiderWalletSummary, Error>({
        queryKey: ['rider', 'wallet-summary'],
        queryFn: () => get<RiderWalletSummary>(RiderApiRoutes.WalletSummary.path),
        staleTime: 1000 * 30,
    });
}

// ── Cash on delivery ─────────────────────────────────────────────────────
//
// Six factors decide whether a rider may carry somebody else's money, and the
// float check never asked any of them. A rider who cannot take cash orders was
// simply shown orders they could not accept, with the refusal arriving only
// after they tapped — so the requirement and the progress toward it come back
// together, and none of these figures is ever a literal in this app.

export interface CashRequirement {
  have: number;
  need: number;
}

export interface CashEligibility {
  cash_enabled_on_platform: boolean;
  eligible: boolean;
  tier: "blocked" | "standard" | "platinum";
  reasons: string[];
  /** Decimal string — the ceiling on a single cash order at this tier. */
  max_order_value: string;
  requirements: {
    deliveries: CashRequirement;
    completion_rate: CashRequirement;
    rating: CashRequirement;
    account_age_days: CashRequirement;
  };
  limits: {
    carrying_now: number;
    max_concurrent: number;
    /** Decimal strings — money taken today against today's ceiling. */
    taken_today: string;
    daily_cap: string;
  };
}

export function useCashEligibility() {
  const { get } = useApiRequest();
  return useQuery<CashEligibility, Error>({
    queryKey: ["rider", "cash-eligibility"],
    queryFn: () => get<CashEligibility>(RiderApiRoutes.CashEligibility.path),
    // Moves when a delivery completes or a cash order is accepted, both of
    // which invalidate this key explicitly.
    staleTime: 1000 * 60,
  });
}
