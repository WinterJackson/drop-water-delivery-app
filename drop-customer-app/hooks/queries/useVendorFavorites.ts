import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Toast } from '@/lib/toast';
import { errorMessage } from '@/API/errors';
import type { Order, Vendor } from '@/types/models';

// ─── Types ────────────────────────────────────────────────────────────────────
/**
 * The `vendor` here is the shared {@link Vendor}, narrowed to the fields this
 * endpoint actually sends — not a second declaration of the same wire shape.
 * It used to be one, and it was missing `rating_count`, which is why the
 * favourites card had nothing to go on and rendered a hardcoded "4.5".
 */
export interface VendorFavoriteItem {
    id: string;
    vendor_id: string;
    created_at?: string | null;
    vendor?: Pick<
        Vendor,
        | 'id'
        | 'business_name'
        | 'profile_pic'
        | 'location_address'
        | 'rating'
        | 'rating_count'
        | 'vendor_type'
        | 'shift_start'
        | 'shift_end'
        | 'is_accepting_orders'
        | 'store_state'
        | 'store_reason'
        | 'reopens_at'
    > & {
        /**
         * Returned, and deliberately *not* what to branch on: it answers one of
         * the five reasons a store may be shut, so a paused or suspended shop
         * reads as open through it. Use `is_accepting_orders`.
         */
        is_online?: boolean;
    };
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

/** Fetch all vendor favourites for the current user */
export function useVendorFavorites() {
    const api = useApiRequest();
    return useQuery<VendorFavoriteItem[], Error>({
        queryKey: ['vendor', 'favorites'],
        queryFn: () => api.get<VendorFavoriteItem[]>(ROUTES.GET_VENDOR_FAVORITES),
    });
}

/** Add a vendor to favourites */
export function useAddVendorFavorite() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (vendorId: string) => api.post(ROUTES.ADD_VENDOR_FAVORITE, { vendor_id: vendorId }),
        onMutate: async (vendorId) => {
            await queryClient.cancelQueries({ queryKey: ['vendor', 'favorites'] });
            const previous = queryClient.getQueryData<VendorFavoriteItem[]>(['vendor', 'favorites']);
            queryClient.setQueryData<VendorFavoriteItem[]>(['vendor', 'favorites'], (old) => {
                const arr = old ? [...old] : [];
                arr.push({ id: `temp-${vendorId}`, vendor_id: vendorId });
                return arr;
            });
            // Keep the single-vendor check in step with the optimistic list, so the
            // heart on the vendor screen fills immediately.
            queryClient.setQueryData(['vendor', 'favorites', 'check', vendorId], { is_favorite: true });
            return { previous };
        },
        onError: (err, _vendorId, context) => {
            if (context?.previous) queryClient.setQueryData(['vendor', 'favorites'], context.previous);
            Toast.error("Couldn't add favourite", errorMessage(err));
        },
        onSettled: (_data, _err, vendorId) => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'favorites'] });
            queryClient.invalidateQueries({ queryKey: ['vendor', 'favorites', 'check', vendorId] });
        },
        onSuccess: () => {
            Toast.success("Added to Favourites", "Vendor has been added to your favourites.");
        },
    });
}

/** Remove a vendor from favourites */
export function useRemoveVendorFavorite() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (vendorId: string) => api.post(ROUTES.REMOVE_VENDOR_FAVORITE, { vendor_id: vendorId }),
        onMutate: async (vendorId) => {
            await queryClient.cancelQueries({ queryKey: ['vendor', 'favorites'] });
            const previous = queryClient.getQueryData<VendorFavoriteItem[]>(['vendor', 'favorites']);
            queryClient.setQueryData<VendorFavoriteItem[]>(['vendor', 'favorites'], (old) => {
                if (!old) return old;
                return old.filter((fav) => fav.vendor_id !== vendorId);
            });
            queryClient.setQueryData(['vendor', 'favorites', 'check', vendorId], { is_favorite: false });
            return { previous };
        },
        onError: (err, _vendorId, context) => {
            if (context?.previous) queryClient.setQueryData(['vendor', 'favorites'], context.previous);
            Toast.error("Couldn't remove favourite", errorMessage(err));
        },
        onSettled: (_data, _err, vendorId) => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'favorites'] });
            queryClient.invalidateQueries({ queryKey: ['vendor', 'favorites', 'check', vendorId] });
        },
        onSuccess: () => {
            Toast.info("Removed from Favourites", "Vendor has been removed from your favourites.");
        },
    });
}

/** Check if a specific vendor is favourited */
export function useCheckVendorFavorite(vendorId: string) {
    const api = useApiRequest();
    return useQuery<{ is_favorite: boolean }, Error>({
        queryKey: ['vendor', 'favorites', 'check', vendorId],
        queryFn: () => api.get<{ is_favorite: boolean }>(ROUTES.CHECK_VENDOR_FAVORITE(vendorId)),
        enabled: !!vendorId,
    });
}

/** Fetch the last order from a specific vendor (for quick reorder) */
export function useLastOrderFromVendor(vendorId: string) {
    const api = useApiRequest();
    return useQuery<Order | null, Error>({
        queryKey: ['vendor', 'lastOrder', vendorId],
        queryFn: async () => {
            const json = await api.get<{ order: Order | null }>(ROUTES.LAST_ORDER_FROM_VENDOR(vendorId));
            return json?.order ?? null;
        },
        enabled: !!vendorId,
    });
}
