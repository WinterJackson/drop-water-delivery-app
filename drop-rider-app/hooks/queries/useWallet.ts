import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApiRequest } from "@/API/useApiClient";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";

export interface WalletTransaction {
  id: string;
  amount: number;
  transaction_type: string;
  description?: string | null;
  status?: string | null;
  created_at?: string | null;
}

export const useWalletTransactions = (limit = 50, offset = 0) => {
  const { get } = useApiRequest();

  return useQuery<WalletTransaction[], Error>({
    queryKey: ["walletTransactions", limit, offset],
    queryFn: () =>
      get<WalletTransaction[]>(
        `${RiderApiRoutes.GetTransactions.path}?limit=${limit}&offset=${offset}`
      ),
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
    mutationFn: ({ amount, phoneNumber, userType }: { amount: number, phoneNumber: string, userType: string }) =>
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
    wallet_balance: number;
    committed_cash_float: number;
    available_for_withdrawal: number;
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
