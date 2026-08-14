import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { retryTransientOnly } from "@/API/errors";
import { useAuth } from "@clerk/clerk-expo";
import { useInfiniteQuery } from "@tanstack/react-query";

/** One movement of bottles between this store and a rider. */
export interface BottleLedgerEntry {
  id: string;
  rider_id: string;
  rider_name: string | null;
  order_id: string | null;
  capacity_litres: number;
  /** Signed. Positive is owed to the store; negative is a return. */
  quantity: number;
  entry_type: "delivery_accrual" | "vendor_receipt" | "adjustment" | string;
  note: string | null;
  created_at: string | null;
}

/** What the endpoint sends. */
interface LedgerResponse {
  entries: BottleLedgerEntry[];
  has_more: boolean;
}

/**
 * What this hook hands on.
 *
 * `items` rather than the server's `entries`, so a page of the ledger has the
 * same shape as a page of anything else and `flattenPages` needs no special
 * case for it — this endpoint is the only one on the platform that names its
 * rows something bespoke.
 */
interface LedgerPage {
  items: BottleLedgerEntry[];
  has_more: boolean;
}

const PAGE_SIZE = 40;

/**
 * The evidence behind the debt figures on Bottle Reconciliation.
 *
 * That screen answers "who owes me what **now**"; this answers "when did that
 * happen, against which order, and did I already take those back". The endpoint
 * existed and shipped from day one with nothing in either app calling it, so
 * the platform's largest non-cash asset had a live balance and no history — and
 * a vendor disputing a rider's count had nothing to point at.
 *
 * Paged with `has_more` rather than a total: the ledger only grows.
 */
export function useBottleLedger() {
  const { isLoaded, isSignedIn } = useAuth();
  const { get } = useApiRequest();

  return useInfiniteQuery<LedgerPage, Error>({
    queryKey: ["vendorBottleLedger"],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const page = await get<LedgerResponse>(
        VendorApiRoutes.BottleLedger(PAGE_SIZE, pageParam as number).path,
      );
      return { items: page?.entries ?? [], has_more: !!page?.has_more };
    },
    // Counted from the rows actually held, not `allPages.length * PAGE_SIZE`.
    // The two agree only while every page is exactly full, and the moment one is
    // not, the multiplication walks the offset past rows nobody ever sees.
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more
        ? allPages.reduce((total, page) => total + page.items.length, 0)
        : undefined,
    enabled: isLoaded && isSignedIn,
    retry: retryTransientOnly(),
  });
}
