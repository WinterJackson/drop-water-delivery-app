import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useAuth } from "@clerk/clerk-expo";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface WalletTransaction {
  id: string;
  /** Decimal string — the ledger's own figure. */
  amount: string;
  transaction_type: string;
  status: string;
  description?: string;
  mpesa_receipt_number?: string;
  reference_id?: string;
  /**
   * Why a failed movement failed, in Safaricom's own words.
   *
   * The B2C result callback writes this on every failure and the STK callback
   * on every rejected top-up, and nothing rendered it — so a vendor whose
   * withdrawal failed saw a red "failed" and no reason, with the balance
   * silently restored. "Insufficient balance in the utility account" and "the
   * phone number is not registered for M-Pesa" need very different responses
   * from the vendor, and neither was reachable from the app.
   */
  failure_reason?: string | null;
  created_at?: string;
}

interface TransactionsPage {
  data: WalletTransaction[];
  nextCursor: number | null;
  hasNextPage: boolean;
  total: number;
}

/**
 * `user_type` is not optional and not cosmetic.
 *
 * `WalletTransaction.user_id` holds ids from three tables and carries no foreign
 * key, so the backend filters on `user_type` to tell the three ledgers apart —
 * and it defaults to `"customer"`. Every call from this app omitted it, so the
 * vendor's transaction list queried the *customer* ledger for a clerk id that
 * has no customer rows and came back empty every time. The screen rendered its
 * "No transactions yet" empty state over a wallet with a live balance.
 */
const TRANSACTIONS_USER_TYPE = "vendor";

function transactionsUrl(params: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams({ user_type: TRANSACTIONS_USER_TYPE });
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") qs.append(key, String(value));
  }
  return `${VendorApiRoutes.GetTransactions.path}?${qs.toString()}`;
}

export const useWalletTransactions = (limit = 50, offset = 0) => {
  const { get } = useApiRequest();

  return useQuery<TransactionsPage, Error>({
    queryKey: ["walletTransactions", limit, offset],
    queryFn: () => get<TransactionsPage>(transactionsUrl({ limit, offset })),
    retry: retryTransientOnly(),
  });
};

export const useWalletTransactionsPaginated = (search: string, type: string, limit = 20) => {
  const { get } = useApiRequest();

  return useInfiniteQuery({
    queryKey: ["walletTransactions", search, type, limit],
    queryFn: ({ pageParam = 0 }) =>
      get<TransactionsPage>(
        transactionsUrl({
          limit,
          offset: pageParam,
          search: search || undefined,
          type: type && type !== "All" ? type : undefined,
        })
      ),
    getNextPageParam: (lastPage) => lastPage?.nextCursor ?? undefined,
    initialPageParam: 0,
    retry: retryTransientOnly(),
  });
};

export interface WalletSummary {
  /**
   * Decimal **strings**, all of them — `vendor_wallet_summary` serialises every
   * one through `money_str`. They were declared `number` here, so `tsc` was
   * type-checking this screen's whole money path against a shape the server has
   * never sent. The rider app's copy of this interface had it right.
   */
  wallet_balance: string;
  /** Held against open cash orders — the vendor's, but not theirs to withdraw. */
  committed_cash_float: string;
  available_for_withdrawal: string;
  /** Negative balance: the store owes the platform and must settle. */
  is_in_arrears: boolean;
  /**
   * The rules the withdrawal will be judged by, from `Platform_Settings` and
   * scoped to this store's type — the wholesale minimum and waiver differ from
   * the retail ones.
   *
   * `fee_waiver_threshold` is compared against the **amount withdrawn**, never
   * the balance held; see `settlement_service.fee_for`.
   */
  withdrawal?: {
    minimum: string;
    fee: string;
    fee_waiver_threshold: string;
  };
  /** The floor an STK push may be raised for — `min_wallet_topup`. */
  topup?: { minimum: string };
}

/**
 * What the vendor can actually withdraw, and why it differs from the balance.
 *
 * On a wholesale cash order the vendor's own rider collects the cash and the
 * platform's cut is debited from the vendor's wallet at delivery, so it is
 * committed from the moment the order is accepted. `settlement_service` has
 * enforced that against withdrawals all along; the app simply had no way to
 * *show* it and displayed the raw `wallet_balance`, so a refusal read as the
 * platform withholding money it had just displayed.
 */
export const useWalletSummary = (enabled = true) => {
  const { isLoaded, isSignedIn } = useAuth();
  const { get } = useApiRequest();

  return useQuery<WalletSummary, Error>({
    queryKey: ["vendor", "wallet-summary"],
    queryFn: () => get<WalletSummary>(VendorApiRoutes.GetWalletSummary.path),
    // Gated on `view_finances`: an owner may withhold the balance from a staff
    // member, and asking anyway would 403 on every open of the wallet screen.
    enabled: enabled && isLoaded && isSignedIn,
    staleTime: 30 * 1000,
    retry: retryTransientOnly(),
  });
};

export const useWalletWithdraw = () => {
  const { post } = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      amount,
      phoneNumber,
      userType,
    }: {
      amount: number;
      phoneNumber: string;
      userType: string;
    }) =>
      post(VendorApiRoutes.WalletWithdraw.path, {
        amount,
        phone_number: phoneNumber,
        user_type: userType,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["walletTransactions"] });
      queryClient.invalidateQueries({ queryKey: ["vendor", "profile"] });
      queryClient.invalidateQueries({ queryKey: ["vendor", "wallet-summary"] });
    },
  });
};
