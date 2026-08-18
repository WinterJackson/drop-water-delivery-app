import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useInfiniteQuery } from '@tanstack/react-query';
import { nextOffset } from '@/utils/paging';

/**
 * Search is bounded by the service radius, and the origin it is measured from is
 * the **saved delivery address**, resolved server-side.
 *
 * These two hooks used to read the handset's live GPS fix and send it as
 * `user_lat`/`user_lng`, which the server preferred over the address on the
 * account. That made search the only surface on the platform measured from where
 * the phone was rather than from where the water goes: the results listed the
 * shops that could reach the customer at work, and `validate_cart_preflight`
 * refused the basket using the shops that could reach their house.
 *
 * It also meant a denied location permission sent no coordinates at all, and the
 * radius clause — written as "bound it when coordinates are known" — silently
 * stopped applying, so the top hit for "20L" could be a shop in another town.
 *
 * The origin is no longer a parameter of these requests, so neither failure has
 * anywhere left to live.
 */

export function useSearchProducts(query: string, category: string = 'all', limit: number = 20, mode: string | null = null) {
    const api = useApiRequest();

    return useInfiniteQuery({
        queryKey: ['search', 'products', query, category, limit, mode],
        queryFn: ({ pageParam = 0 }) =>
            api.get<any[]>(ROUTES.SEARCH, {
                params: {
                    ...(query.trim().length > 1 ? { query: query.trim() } : {}),
                    ...(category !== 'all' ? { category } : {}),
                    ...(mode ? { mode } : {}),
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

    return useInfiniteQuery({
        queryKey: ['search', 'vendors', query, limit],
        queryFn: ({ pageParam = 0 }) =>
            api.get<any[]>(ROUTES.SEARCH_VENDORS, {
                params: {
                    ...(query.trim().length > 1 ? { query: query.trim() } : {}),
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
