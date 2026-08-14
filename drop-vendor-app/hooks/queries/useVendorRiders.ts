import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { flattenPages } from "@/utils/paging";
import { useAuth } from "@clerk/clerk-expo";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";

export interface VendorRider {
  registry_id: string;
  deliverer_id: string;
  name?: string;
  phone_number?: string;
  profile_pic?: string;
  vehicle_type?: string;
  plate_number?: string;
  status: string;
  is_available?: boolean;
  applied_at?: string;
  pending_10L_empties: number;
  pending_20L_empties: number;
  /** Present on some rows; the roster endpoint does not return them today. */
  rating?: number;
  total_deliveries?: number;
}

/** Same honest envelope as `/orders` and `/products`. */
interface RiderPage {
  items: VendorRider[];
  limit: number;
  offset: number;
  has_more: boolean;
}

/** Riders per request. The endpoint caps `limit` at 100. */
export const RIDERS_PAGE_SIZE = 25;

export interface RosterQuery {
  /** Registry status. Absent means every status. */
  status?: string;
  /** `recent` (default), `rating` or `trips`. Ordered by the server. */
  sort?: 'recent' | 'rating' | 'trips';
  /** Only riders currently marked available. */
  availableOnly?: boolean;
  /** Matches a rider's name or phone number. */
  search?: string;
}

/**
 * This store's rider roster, page by page.
 *
 * Every part of the question is the server's: the endpoint returned the whole
 * roster in one unbounded, **unordered** response and the app filtered by status
 * and searched by name over it. Three consequences, all of which a vendor would
 * report as the app being broken rather than as a list being long — the roster
 * reshuffled on each of its thirty-second refetches because the query had no
 * `ORDER BY`; a long-standing store paid for every registration it had ever
 * received on each of those refetches; and any bound placed on that response
 * would immediately have turned the two client-side filters into filters over a
 * page, answering "no pending applications" to a store that has some.
 */
export function useVendorRiders({ status, availableOnly, search, sort }: RosterQuery = {}) {
  const { isLoaded, isSignedIn } = useAuth();
  const { get } = useApiRequest();
  const term = (search ?? "").trim();

  return useInfiniteQuery<RiderPage, Error>({
    queryKey: ["vendor", "riders", status ?? "all", !!availableOnly, term, sort ?? "recent"],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const qs = new URLSearchParams({
        limit: String(RIDERS_PAGE_SIZE),
        offset: String(pageParam as number),
      });
      if (status) qs.append("status", status.toLowerCase());
      if (availableOnly) qs.append("available_only", "true");
      if (term) qs.append("search_query", term);
      if (sort && sort !== "recent") qs.append("sort", sort);

      const page = await get<RiderPage>(`${VendorApiRoutes.GetMyRiders.path}?${qs.toString()}`);
      return {
        items: Array.isArray(page?.items) ? page.items : [],
        limit: page?.limit ?? RIDERS_PAGE_SIZE,
        offset: page?.offset ?? 0,
        has_more: !!page?.has_more,
      };
    },
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more
        ? allPages.reduce((total, page) => total + page.items.length, 0)
        : undefined,
    enabled: isLoaded && isSignedIn,
    refetchInterval: 30000,
    retry: retryTransientOnly(),
  });
}

/** Every rider fetched so far, newest application first, each appearing once. */
export function riderRows(data: InfiniteData<RiderPage> | undefined): VendorRider[] {
  return flattenPages<VendorRider>(data, (row) => row.registry_id);
}
