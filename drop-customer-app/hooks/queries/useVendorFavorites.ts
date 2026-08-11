import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Toast } from '@/lib/toast';
import { errorMessage } from '@/API/errors';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface VendorFavoriteItem {
    id: string;
    vendor_id: string;
    vendor?: {
        id: string;
        business_name: string;
        profile_pic: string;
        rating: number;
        location_address: string;
        /**
         * Whether the store is taking orders, and why not.
         *
         * Favourites is the surface where this matters most — the customer
         * already knows which shop they want. `is_online` is also returned and
         * is deliberately *not* what to branch on: it answers one of the five
         * reasons a store may be shut, so a paused or suspended shop reads as
         * open through it.
         */
        is_online?: boolean;
        is_accepting_orders?: boolean;
        store_state?: string;
        store_reason?: string | null;
        reopens_at?: string | null;
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
            const previous = queryClient.getQueryData(['vendor', 'favorites']);
            queryClient.setQueryData(['vendor', 'favorites'], (old: any) => {
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
            const previous = queryClient.getQueryData(['vendor', 'favorites']);
            queryClient.setQueryData(['vendor', 'favorites'], (old: any) => {
                if (!old) return old;
                return old.filter((fav: any) => fav.vendor_id !== vendorId);
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
    return useQuery<any, Error>({
        queryKey: ['vendor', 'lastOrder', vendorId],
        queryFn: async () => {
            const json = await api.get<{ order: any }>(ROUTES.LAST_ORDER_FROM_VENDOR(vendorId));
            return json?.order ?? null;
        },
        enabled: !!vendorId,
    });
}
