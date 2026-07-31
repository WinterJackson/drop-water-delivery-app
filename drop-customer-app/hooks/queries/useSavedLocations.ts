import { ApiRoutes, ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface SavedLocation {
    id: string;
    label: string | null;
    address: string;
    lat: number;
    lng: number;
    is_default: boolean;
    use_count: number;
    last_used_at: string;
}

export interface CreateSavedLocationPayload {
    label?: string;
    address: string;
    lat: number;
    lng: number;
    is_default?: boolean;
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

/** Fetch all saved locations for the current user */
export function useSavedLocations() {
    const api = useApiRequest();
    return useQuery<SavedLocation[], Error>({
        queryKey: ['customer', 'savedLocations'],
        queryFn: () => api.get<SavedLocation[]>(ROUTES.GET_SAVED_LOCATIONS),
    });
}

/** Create a new saved location */
export function useCreateSavedLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data: CreateSavedLocationPayload) => api.post(ROUTES.CREATE_SAVED_LOCATION, data),
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'savedLocations'] });
        },
    });
}

/** Update an existing saved location */
export function useUpdateSavedLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }: CreateSavedLocationPayload & { id: string }) =>
            api.put(ROUTES.UPDATE_SAVED_LOCATION(id), data),
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'savedLocations'] });
        },
    });
}

/** Delete a saved location */
export function useDeleteSavedLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (locationId: string) => api.del(ROUTES.DELETE_SAVED_LOCATION(locationId)),
        onMutate: async (locationId) => {
            await queryClient.cancelQueries({ queryKey: ['customer', 'savedLocations'] });
            const prev = queryClient.getQueryData(['customer', 'savedLocations']);
            queryClient.setQueryData(['customer', 'savedLocations'], (old: any) =>
                old ? old.filter((loc: any) => loc.id !== locationId) : old
            );
            return { prev };
        },
        onError: (_err, _id, context) => {
            if (context?.prev) queryClient.setQueryData(['customer', 'savedLocations'], context.prev);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'savedLocations'] });
        },
    });
}

export function useRevokeLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => api.post(ApiRoutes.RevokeUserLocation.path),
        onMutate: async () => {
            // Cancel any outgoing user detail refetches
            await queryClient.cancelQueries({ queryKey: ['user', 'details'] });

            // Snapshot for rollback
            const previousUser = queryClient.getQueryData(['user', 'details']);

            // Optimistically clear the user's location
            queryClient.setQueryData(['user', 'details'], (old: import("@/types/models").BasicUser | undefined) => {
                if (!old) return old;
                return {
                    ...old,
                    lat: null,
                    lng: null,
                    location_address: null,
                };
            });

            return { previousUser };
        },
        onError: (_err, _variables, context) => {
            if (context?.previousUser) {
                queryClient.setQueryData(['user', 'details'], context.previousUser);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            queryClient.invalidateQueries({ queryKey: ['customer', 'savedLocations'] });
            // The delivery quote depends on the destination, so it is stale now.
            queryClient.invalidateQueries({ queryKey: ['cart', 'quote'] });
        },
    });
}

/** Select a saved location as the active delivery address.
 *  This syncs lat/lng/address to the User profile on the backend. */
export function useSelectSavedLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (locationId: string) => api.post(ROUTES.USE_SAVED_LOCATION(locationId)),
        onMutate: async (locationId: string) => {
            // Cancel any outgoing refetches so they don't overwrite our optimistic update
            await queryClient.cancelQueries({ queryKey: ['user', 'details'] });

            // Snapshot previous user data for rollback
            const previousUser = queryClient.getQueryData(['user', 'details']);

            // Get the saved location we're trying to use
            const savedLocations = queryClient.getQueryData<any[]>(['customer', 'savedLocations']);
            const targetLoc = savedLocations?.find((l) => l.id === locationId);

            // Optimistically update the user details cache with the new location
            if (targetLoc) {
                queryClient.setQueryData(['user', 'details'], (old: import("@/types/models").BasicUser | undefined) => {
                    if (!old) return old;
                    return {
                        ...old,
                        lat: targetLoc.lat,
                        lng: targetLoc.lng,
                        location_address: targetLoc.address,
                    };
                });
            }

            return { previousUser };
        },
        onError: (_err, _locationId, context) => {
            // Roll back to previous user data on error
            if (context?.previousUser) {
                queryClient.setQueryData(['user', 'details'], context.previousUser);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['customer', 'savedLocations'] });
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            // Changing the delivery address changes the delivery fee.
            queryClient.invalidateQueries({ queryKey: ['cart', 'quote'] });
        },
    });
}
