import { retryTransientOnly } from '@/API/errors';
import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useQuery } from '@tanstack/react-query';

/**
 * Vendor discovery.
 *
 * `/api/vendors` returns a `{data, total, …}` envelope while the proximity
 * endpoints return bare arrays, so every hook normalises with `unwrap`.
 */
function unwrap<T = any>(payload: any): T[] {
    if (Array.isArray(payload)) return payload as T[];
    if (payload && Array.isArray(payload.data)) return payload.data as T[];
    return [];
}

const DISCOVERY_STALE_TIME = 5 * 60 * 1000;

export function useAllVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'all'],
        queryFn: async () => unwrap(await api.get(ROUTES.GET_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
    });
}

export function useNearByVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'nearby'],
        queryFn: async () => unwrap(await api.get(ROUTES.GET_NEARBY_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
        retry: retryTransientOnly(2),
    });
}

export function useTopRatedVendors() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'topRated'],
        queryFn: async () => unwrap(await api.get(ROUTES.GET_TOP_RATED_VENDORS)),
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
        queryFn: async () => unwrap(await api.get(ROUTES.GET_TOP_BRAND_VENDORS)),
        staleTime: DISCOVERY_STALE_TIME,
    });
}

export function useVendorDirectory(searchQuery: string = '', filter: string = 'all') {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['vendors', 'directory', searchQuery, filter],
        queryFn: async () =>
            unwrap(
                await api.get(ROUTES.GET_VENDOR_DIRECTORY, {
                    params: {
                        ...(searchQuery ? { search_query: searchQuery } : {}),
                        ...(filter ? { vendor_type: filter } : {}),
                    },
                })
            ),
        staleTime: DISCOVERY_STALE_TIME,
        retry: retryTransientOnly(2),
    });
}
