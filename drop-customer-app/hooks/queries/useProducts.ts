import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { flattenPages } from '@/utils/paging';
import { useInfiniteQuery, useQuery, type InfiniteData } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface Product {
    id: string;
    vendor_id: string;
    name: string;
    description: string | null;
    price: number;
    discount: number;
    image_url: string;
    capacity: number;
    weight_kg: number;
    minimum_order_qty: number;
    unit: string | null;
    stock: number;
    stock_quantity: number; // computed alias of stock from backend
    is_available: boolean;
    category?: string | null;
    vendor?: {
        id: string;
        business_name: string;
        location_address?: string;
        lat?: number;
        lng?: number;
        rating?: number;
        profile_pic?: string;
    };
}

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useProduct(productId: string) {
    const api = useApiRequest();
    return useQuery<Product, Error>({
        queryKey: ['product', productId],
        queryFn: () => api.post<Product>(ROUTES.GET_PRODUCT_DETAILS, { id: productId }),
        enabled: !!productId,
    });
}

export function useVendorDetails(vendorId: string) {
    const api = useApiRequest();
    return useQuery<any, Error>({
        queryKey: ['vendor', vendorId],
        queryFn: () => api.post(ROUTES.GET_VENDOR_DETAILS, { id: vendorId }),
        enabled: !!vendorId,
    });
}

/** Rows per request on the offers list. The endpoint caps `limit` at 100. */
const OFFERS_PAGE_SIZE = 20;

interface OffersPage {
    data: Product[];
    limit: number;
    offset: number;
}

/**
 * Discounted products, page by page.
 *
 * Sent no `limit`, so it took the server's default 20 and the screen showed
 * those twenty as the whole of the platform's offers — the one screen whose
 * entire purpose is browsing, capped at a single screenful with no way to go on.
 */
export function useProductsWithOffer() {
    const api = useApiRequest();
    return useInfiniteQuery<OffersPage, Error>({
        queryKey: ['products', 'offers'],
        initialPageParam: 0,
        queryFn: async ({ pageParam }) => {
            const json: any = await api.get(ROUTES.GET_PRODUCTS_WITH_OFFER, {
                params: { limit: OFFERS_PAGE_SIZE, offset: pageParam as number },
            });
            // This endpoint answers with a {"data": [...], "limit": …, "offset": …}
            // envelope; older builds of it answered with a bare array.
            const rows: Product[] = Array.isArray(json) ? json : json?.data ?? [];
            return { data: rows, limit: OFFERS_PAGE_SIZE, offset: (pageParam as number) ?? 0 };
        },
        // No `has_more` on this endpoint, so a short page is the only end signal.
        getNextPageParam: (lastPage, allPages) =>
            lastPage.data.length < OFFERS_PAGE_SIZE
                ? undefined
                : allPages.reduce((n, page) => n + page.data.length, 0),
    });
}

/** Every offer fetched so far, each appearing once. */
export function offerRows(data: InfiniteData<OffersPage> | undefined): Product[] {
    return flattenPages<Product>(data);
}

export function useCategories() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['categories'],
        queryFn: async () => {
            const json: any = await api.get(ROUTES.GET_CATEGORIES);
            return json?.categories ?? [];
        },
    });
}

export function usePaginatedProducts(page: number) {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['products', 'paginated', page],
        queryFn: () => api.post(ROUTES.GET_PAGINATED_PRODUCTS, { page }),
    });
}

export function useProductsByCategory(category: string) {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['products', 'category', category],
        queryFn: async () => {
            const json: any = await api.get(ROUTES.GET_PRODUCTS_BY_CATEGORY, { params: { category } });
            return Array.isArray(json) ? json : json?.data ?? [];
        },
        enabled: !!category,
    });
}
