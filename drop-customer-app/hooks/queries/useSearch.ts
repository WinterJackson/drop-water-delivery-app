import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useInfiniteQuery } from '@tanstack/react-query';
import { nextOffset } from '@/utils/paging';
import { useLocation } from '@/hooks/useLocation';

export function useSearchProducts(query: string, category: string = 'all', limit: number = 20, mode: string | null = null) {
    const api = useApiRequest();
    const { location } = useLocation();

    return useInfiniteQuery({
        queryKey: ['search', 'products', query, category, limit, mode, location?.coords.latitude, location?.coords.longitude],
        queryFn: ({ pageParam = 0 }) =>
            api.get<any[]>(ROUTES.SEARCH, {
                params: {
                    ...(query.trim().length > 1 ? { query: query.trim() } : {}),
                    ...(category !== 'all' ? { category } : {}),
                    ...(mode ? { mode } : {}),
                    ...(location?.coords
                        ? { user_lat: location.coords.latitude, user_lng: location.coords.longitude }
                        : {}),
                    limit,
                    offset: pageParam,
                },
            }),
        initialPageParam: 0,
        // Counted from the rows actually held. `allPages.length * limit` assumes
        // every page came back full, and the first that does not sends the next
        // offset past rows nobody ever sees — silently, in the middle of a
        // search result.
        getNextPageParam: nextOffset<any>(limit),
        enabled: query.trim().length > 1 || category !== 'all' || !!mode,
        staleTime: 30000,
    });
}

export function useSearchVendors(query: string, limit: number = 20) {
    const api = useApiRequest();
    const { location } = useLocation();

    return useInfiniteQuery({
        queryKey: ['search', 'vendors', query, limit, location?.coords.latitude, location?.coords.longitude],
        queryFn: ({ pageParam = 0 }) =>
            api.get<any[]>(ROUTES.SEARCH_VENDORS, {
                params: {
                    ...(query.trim().length > 1 ? { query: query.trim() } : {}),
                    ...(location?.coords
                        ? { user_lat: location.coords.latitude, user_lng: location.coords.longitude }
                        : {}),
                    limit,
                    offset: pageParam,
                },
            }),
        initialPageParam: 0,
        // Counted from the rows actually held. `allPages.length * limit` assumes
        // every page came back full, and the first that does not sends the next
        // offset past rows nobody ever sees — silently, in the middle of a
        // search result.
        getNextPageParam: nextOffset<any>(limit),
        enabled: true,
        staleTime: 30000,
    });
}
