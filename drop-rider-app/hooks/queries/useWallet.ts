import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@clerk/clerk-expo";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";

import { useInfiniteQuery } from "@tanstack/react-query";

export const useWalletTransactions = (limit = 50, offset = 0) => {
  const { getToken, signOut } = useAuth();

  return useQuery({
    queryKey: ["walletTransactions", limit, offset],
    queryFn: async () => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(`${RiderApiRoutes.GetTransactions.path}?limit=${limit}&offset=${offset}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 401) {
        signOut();
        throw new Error("Session Expired");
      }

      if (!res.ok) {
        throw new Error("Failed to fetch transactions");
      }

      return res.json();
    },
  });
};

export const useWalletTransactionsPaginated = (search: string, type: string, limit = 20) => {
  const { getToken, signOut } = useAuth();

  return useInfiniteQuery({
    queryKey: ["walletTransactions", search, type, limit],
    queryFn: async ({ pageParam = 0 }) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      let url = `${RiderApiRoutes.GetTransactions.path}?limit=${limit}&offset=${pageParam}`;
      if (search) url += `&search=${encodeURIComponent(search)}`;
      if (type && type !== "All") url += `&type=${encodeURIComponent(type)}`;

      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 401) {
        signOut();
        throw new Error("Session Expired");
      }

      if (!res.ok) {
        throw new Error("Failed to fetch transactions");
      }

      return res.json();
    },
    getNextPageParam: (lastPage) => lastPage?.nextCursor ?? undefined,
    initialPageParam: 0,
  });
};

export const useWalletWithdraw = () => {
  const { getToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ amount, phoneNumber, userType }: { amount: number, phoneNumber: string, userType: string }) => {
      const token = await getToken();
      if (!token) throw new Error("No auth token");

      const res = await fetch(RiderApiRoutes.WalletWithdraw.path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ amount, phone_number: phoneNumber, user_type: userType }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        throw new Error(data?.detail || "Withdrawal failed");
      }

      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
      queryClient.invalidateQueries({ queryKey: ["rider", "profile"] });
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
    const { getToken, signOut } = useAuth();
    return useQuery<RiderWalletSummary, Error>({
        queryKey: ['rider', 'wallet-summary'],
        queryFn: async () => {
            const token = await getToken();
            const route = RiderApiRoutes.WalletSummary;
            const res = await fetch(route.path, {
                method: route.method,
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
            });
            if (res.status === 401) { await signOut(); throw new Error('401_UNAUTHORIZED'); }
            if (!res.ok) throw new Error(`Wallet summary fetch failed: ${res.status}`);
            return res.json();
        },
        staleTime: 1000 * 30,
        retry: (failureCount, error) =>
            error.message === '401_UNAUTHORIZED' ? false : failureCount < 2,
    });
}
