import type { Vendor } from '@/types/models';
import { retryTransientOnly } from '@/API/errors';
import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { flattenPages, nextOffset } from '@/utils/paging';
import { useInfiniteQuery, useQuery, type InfiniteData } from '@tanstack/react-query';

/**
 * Vendor discovery.
 *
 * `/api/vendors` returns a `{data, total, …}` envelope while the proximity
 * endpoints return bare arrays, so every hook normalises with `unwrap`.
 */
function unwrap<T>(payload: unknown): T[] {
    if (Array.isArray(payload)) return payload as T[];
    const data = (payload as { data?: unknown } | null)?.data;
    if (Array.isArray(data)) return data as T[];
    return [];
}

const DISCOVERY_STALE_TIME = 5 * 60 * 1000;

export function useAllVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'all'],
        queryFn: async () => unwrap<Vendor>(await api.get(ROUTES.GET_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
    });
}

export function useNearByVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'nearby'],
        queryFn: async () => unwrap<Vendor>(await api.get(ROUTES.GET_NEARBY_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
        retry: retryTransientOnly(2),
    });
}

export function useTopRatedVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'topRated'],
        queryFn: async () => unwrap<Vendor>(await api.get(ROUTES.GET_TOP_RATED_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
        retry: retryTransientOnly(2),
    });
}

export function useVendorsByType(type: string) {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'type', type],
        queryFn: async () => unwrap(await api.post(ROUTES.GET_VENDORS_BY_TYPE, { vendor_type: type })),
        enabled: !!type,
        staleTime: DISCOVERY_STALE_TIME,
    });
}

export function useTopBrandsVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'topBrands'],
        queryFn: async () => unwrap<Vendor>(await api.get(ROUTES.GET_TOP_BRAND_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
    });
}

/** Stores per request. The endpoint caps `limit` at 100. */
export const DIRECTORY_PAGE_SIZE = 20;

/**
 * The directory of stores a customer can order from, nearest first.
 *
 * The endpoint took a `limit` and no `offset` at all, and the app sent neither,
 * so the directory was permanently the nearest 50 stores with no way to ask for
 * the 51st. Both halves are fixed: `offset` exists server-side now, and the
 * search term and the type filter are still the *server's* — filtering these
 * rows in the app would search one page and report "no wholesale stores near
 * you" to somebody with one just past the cut.
 */
export function useVendorDirectory(searchQuery: string = '', filter: string = 'all') {
    const api = useApiRequest();
    return useInfiniteQuery<Vendor[], Error>({
        queryKey: ['vendors', 'directory', searchQuery, filter],
        initialPageParam: 0,
        queryFn: async ({ pageParam }) =>
            unwrap<Vendor>(
                await api.get(ROUTES.GET_VENDOR_DIRECTORY, {
                    params: {
                        limit: DIRECTORY_PAGE_SIZE,
                        offset: pageParam as number,
                        ...(searchQuery ? { search_query: searchQuery } : {}),
                        ...(filter ? { vendor_type: filter } : {}),
                    },
                })
            ),
        getNextPageParam: nextOffset<Vendor>(DIRECTORY_PAGE_SIZE),
        staleTime: DISCOVERY_STALE_TIME,
        retry: retryTransientOnly(2),
    });
}

/** Every store fetched so far, nearest first, each appearing once. */
export function directoryRows(data: InfiniteData<Vendor[]> | undefined): Vendor[] {
    return flattenPages<Vendor>(data);
}
