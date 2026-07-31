import { ROUTES } from '@/API/routes/ApiRoutes';
import { ApiError, retryTransientOnly } from '@/API/errors';
import { useApiRequest } from '@/API/useApiClient';
import { useAuth } from '@clerk/clerk-expo';
import type { DetailedCart } from '@/types/models';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/**
 * Authoritative price breakdown for the current cart, computed server-side.
 *
 * The client must render these numbers verbatim. It previously recomputed the
 * total locally, which is how the displayed price, the amount charged, and the
 * amount recorded on the order all came to disagree.
 */
export interface CartQuote {
    vendor_id: string;
    vendor_type: string;
    delivery_type: string;
    total_quantity: number;
    total_weight_kg: number;
    vehicle_class: string;
    distance_km: number;
    estimated_minutes: number;
    product_subtotal: number;
    delivery_fee: number;
    service_fee: number;
    surge_fee: number;
    delivery_markup: number;
    payload_surcharge: number;
    staircase_surcharge: number;
    bottle_deposit: number;
    welcome_discount: number;
    wallet_discount: number;
    total: number;
    surge_active: boolean;
    is_welcome_offer: boolean;
    /** False when a platform rule (MOQ, unit cap, distance) blocks checkout. */
    checkout_ready: boolean;
    warnings: string[];
    moq_kg: number | null;
    max_units: number | null;
    max_distance_km: number;
}

export function useCart() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<DetailedCart | null, Error>({
        queryKey: ['cart', userId],
        queryFn: () => api.get<DetailedCart | null>(ROUTES.GET_CART),
        retry: retryTransientOnly(2)
    });
}

export function useDetailedCart() {
    const { userId } = useAuth();
    const api = useApiRequest();
    return useQuery<DetailedCart | null, Error>({
        queryKey: ['cart', 'detailed', userId],
        queryFn: () => api.get<DetailedCart | null>(ROUTES.GET_DETAILED_CART),
        retry: retryTransientOnly(2)
    });
}

/**
 * Server-priced cart total. Disabled until a delivery location is known, since
 * distance is an input to the delivery fee.
 */
export function useCartQuote(
    lat?: number | null,
    lng?: number | null,
    deliveryType: string = 'quick_swap',
    enabled: boolean = true,
) {
    const { userId } = useAuth();
    const api = useApiRequest();
    const hasLocation = typeof lat === 'number' && typeof lng === 'number' && !(lat === 0 && lng === 0);

    return useQuery<CartQuote, Error>({
        queryKey: ['cart', 'quote', userId, lat, lng, deliveryType],
        queryFn: () => api.post<CartQuote>(ROUTES.CART_QUOTE, { lat, lng, delivery_type: deliveryType }),
        enabled: enabled && hasLocation,
        // Surge windows and delivery fees change with time and location, so keep
        // this fresh but not chatty.
        staleTime: 60_000,
        retry: retryTransientOnly(1),
    });
}

export function useAddToCart() {
    const { userId } = useAuth();
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: { id: string; quantity: number; force_replace?: boolean }) =>
            api.post(ROUTES.ADD_TO_CART, payload),
        onMutate: async () => {
            await queryClient.cancelQueries({ queryKey: ['cart', userId] });
            await queryClient.cancelQueries({ queryKey: ['cart', 'detailed', userId] });
            const prevCart = queryClient.getQueryData(['cart', userId]);
            const prevDetailed = queryClient.getQueryData(['cart', 'detailed', userId]);
            return { prevCart, prevDetailed };
        },
        onError: (err, payload, context) => {
            if (context?.prevCart) queryClient.setQueryData(['cart', userId], context.prevCart);
            if (context?.prevDetailed) queryClient.setQueryData(['cart', 'detailed', userId], context.prevDetailed);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['cart'] });
        }
    });
}

/**
 * A cart can only hold one vendor's products. The backend answers with a 409 and
 * a structured `detail` so the UI can name the vendor being replaced.
 */
export function isVendorConflict(error: unknown): error is ApiError {
    return error instanceof ApiError && error.status === 409 && error.type === 'vendor_conflict';
}

export function vendorConflictInfo(error: unknown): { existingVendor: string; existingVendorId?: string } {
    if (isVendorConflict(error)) {
        const detail = error.detail as any;
        return {
            existingVendor: detail?.existing_vendor ?? 'another vendor',
            existingVendorId: detail?.existing_vendor_id,
        };
    }
    return { existingVendor: 'another vendor' };
}

export function useChangeCartQty() {
    const { userId } = useAuth();
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: { id: string; quantity: number }) =>
            api.post(ROUTES.CHANGE_CART_QTY, payload),
        onMutate: async ({ id, quantity }) => {
            await queryClient.cancelQueries({ queryKey: ['cart', 'detailed', userId] });
            const prevDetailed = queryClient.getQueryData(['cart', 'detailed', userId]);
            queryClient.setQueryData(['cart', 'detailed', userId], (old: any) => {
                if (!old || !old.items) return old;
                return {
                    ...old,
                    items: old.items.map((item: any) => (item.id === id ? { ...item, quantity } : item))
                };
            });
            return { prevDetailed };
        },
        onError: (err, payload, context) => {
            if (context?.prevDetailed) queryClient.setQueryData(['cart', 'detailed', userId], context.prevDetailed);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['cart'] });
        }
    });
}

export function useDeleteCartItem() {
    const { userId } = useAuth();
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: { id: string }) => api.post(ROUTES.DELETE_CART_ITEM, payload),
        onMutate: async ({ id }) => {
            await queryClient.cancelQueries({ queryKey: ['cart', 'detailed', userId] });
            const prevDetailed = queryClient.getQueryData(['cart', 'detailed', userId]);
            queryClient.setQueryData(['cart', 'detailed', userId], (old: any) => {
                if (!old || !old.items) return old;
                return { ...old, items: old.items.filter((item: any) => item.id !== id) };
            });
            return { prevDetailed };
        },
        onError: (err, payload, context) => {
            if (context?.prevDetailed) queryClient.setQueryData(['cart', 'detailed', userId], context.prevDetailed);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['cart'] });
        }
    });
}

export interface DeliveryFeePreview {
    delivery_fee: number;
    quick_swap_fee: number;
    keep_my_bottle_fee: number;
    distance_km: number;
    estimated_minutes: number;
    vehicle_class: string;
    service_fee: number;
    surge_fee: number;
    surge_active: boolean;
    max_distance_km: number;
    within_range: boolean;
}

export function useDeliveryFee(
    lat_from?: number,
    lng_from?: number,
    lat_to?: number,
    lng_to?: number,
    vendor_type: string = 'retail_refill',
    vehicle_class: string = 'motorbike',
    delivery_type: string = 'quick_swap',
) {
    const api = useApiRequest();
    const hasCoords = !!lat_from && !!lng_from && !!lat_to && !!lng_to;

    return useQuery<DeliveryFeePreview | null, Error>({
        queryKey: ['delivery-fee', lat_from, lng_from, lat_to, lng_to, vendor_type, vehicle_class, delivery_type],
        queryFn: () => {
            if (!hasCoords) return Promise.resolve(null);
            return api.get<DeliveryFeePreview>(ROUTES.GET_DELIVERY_FEE, {
                params: {
                    lat_from, lng_from, lat_to, lng_to,
                    vendor_type, vehicle_class, delivery_type,
                },
            });
        },
        enabled: hasCoords,
        retry: retryTransientOnly(1)
    });
}
