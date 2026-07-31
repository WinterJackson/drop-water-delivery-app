import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useQuery } from '@tanstack/react-query';

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
        delivery_radius?: number;
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

export function useProductsWithOffer() {
    const api = useApiRequest();
    return useQuery({
        queryKey: ['products', 'offers'],
        queryFn: async () => {
            const json: any = await api.get(ROUTES.GET_PRODUCTS_WITH_OFFER);
            // This endpoint answers with a {"data": [...], "total": …} envelope.
            return Array.isArray(json) ? json : json?.data ?? [];
        },
    });
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
