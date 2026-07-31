import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Toast } from '@/lib/toast';
import { errorMessage } from '@/API/errors';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface FavoriteItem {
    id: string;
    product_id: string;
    product?: {
        id: string;
        name: string;
        price: number;
        discount: number;
        image_url: string;
    };
}

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useFavorites() {
    const api = useApiRequest();
    return useQuery<FavoriteItem[], Error>({
        queryKey: ['customer', 'favorites'],
        queryFn: () => api.get<FavoriteItem[]>(ROUTES.GET_FAVORITES),
    });
}

export function useAddFavorite() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (productId: string) => api.post(ROUTES.ADD_FAVORITE, { product_id: productId }),
        onMutate: async (productId) => {
            await queryClient.cancelQueries({ queryKey: ['customer', 'favorites'] });
            const previousFavorites = queryClient.getQueryData(['customer', 'favorites']);
            queryClient.setQueryData(['customer', 'favorites'], (old: any) => {
                const newFavorites = old ? [...old] : [];
                newFavorites.push({ id: `temp-${productId}`, product_id: productId });
                return newFavorites;
            });
            return { previousFavorites };
        },
        onError: (err, _productId, context) => {
            if (context?.previousFavorites) {
                queryClient.setQueryData(['customer', 'favorites'], context.previousFavorites);
            }
            Toast.error("Couldn't add favourite", errorMessage(err));
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'favorites'] });
        },
        onSuccess: () => {
            Toast.success("Added to Favourites", "Product has been added to your favourites.");
        },
    });
}

export function useRemoveFavorite() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (productId: string) => api.post(ROUTES.REMOVE_FAVORITE, { product_id: productId }),
        onMutate: async (productId) => {
            await queryClient.cancelQueries({ queryKey: ['customer', 'favorites'] });
            const previousFavorites = queryClient.getQueryData(['customer', 'favorites']);
            queryClient.setQueryData(['customer', 'favorites'], (old: any) => {
                if (!old) return old;
                return old.filter((fav: any) => fav.product_id !== productId);
            });
            return { previousFavorites };
        },
        onError: (err, _productId, context) => {
            if (context?.previousFavorites) {
                queryClient.setQueryData(['customer', 'favorites'], context.previousFavorites);
            }
            Toast.error("Couldn't remove favourite", errorMessage(err));
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'favorites'] });
        },
        onSuccess: () => {
            Toast.info("Removed from Favourites", "Product has been removed from your favourites.");
        },
    });
}
