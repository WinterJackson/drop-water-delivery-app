import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from "@tanstack/react-query";
import { ROUTES } from "@/API/routes/ApiRoutes";
import { useApiRequest } from "@/API/useApiClient";

export interface WalletTransaction {
  id: string;
  user_type: string;
  transaction_type: string;
  amount: number;
  status: string;
  reference_id: string | null;
  mpesa_receipt_number: string | null;
  description: string | null;
  failure_reason: string | null;
  created_at: string | null;
}

/**
 * The backend wraps the ledger in `{data, nextCursor, hasNextPage, total}`.
 * Both hooks below return the *rows*, so screens never have to know which of the
 * two they are using — previously one returned the envelope and the other the
 * pages, under the same cache-key prefix.
 */
interface WalletPage {
  data: WalletTransaction[];
  nextCursor: number | null;
  hasNextPage: boolean;
  total: number;
}

export const useWalletTransactions = (limit = 50, offset = 0) => {
  const api = useApiRequest();

  return useQuery<WalletTransaction[], Error>({
    queryKey: ["walletTransactions", "page", limit, offset],
    queryFn: async () => {
      const page = await api.get<WalletPage>(ROUTES.GET_TRANSACTIONS, {
        params: { limit, offset, user_type: "customer" },
      });
      return page?.data ?? [];
    },
  });
};

export const useWalletTransactionsPaginated = (search: string, type: string, limit = 20) => {
  const api = useApiRequest();

  return useInfiniteQuery<WalletPage, Error>({
    queryKey: ["walletTransactions", "infinite", search, type, limit],
    queryFn: ({ pageParam }) =>
      api.get<WalletPage>(ROUTES.GET_TRANSACTIONS, {
        params: {
          limit,
          offset: pageParam ?? 0,
          user_type: "customer",
          ...(search ? { search } : {}),
          ...(type && type !== "All" ? { type } : {}),
        },
      }),
    getNextPageParam: (lastPage) => lastPage?.nextCursor ?? undefined,
    initialPageParam: 0,
  });
};

/** Flatten an infinite wallet query into a single row list. */
export const flattenWalletPages = (pages?: { pages: WalletPage[] }): WalletTransaction[] =>
  pages?.pages.flatMap((page) => page?.data ?? []) ?? [];

export const useWalletTopUp = () => {
  const api = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ amount, phoneNumber }: { amount: number; phoneNumber: string }) =>
      api.post(ROUTES.WALLET_TOP_UP, {
        amount,
        phone_number: phoneNumber,
        user_type: "customer",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
      queryClient.invalidateQueries({ queryKey: ["user", "details"] });
    },
  });
};

export const useWalletWithdraw = () => {
  const api = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ amount, phoneNumber }: { amount: number; phoneNumber: string }) =>
      api.post(ROUTES.WALLET_WITHDRAW, {
        amount,
        phone_number: phoneNumber,
        // Derived server-side from the token as well; sent for explicitness.
        user_type: "customer",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
      queryClient.invalidateQueries({ queryKey: ["user", "details"] });
    },
  });
};
