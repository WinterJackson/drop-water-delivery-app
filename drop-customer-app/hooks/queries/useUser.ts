import { retryTransientOnly } from '@/API/errors';
import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useAuth } from '@clerk/clerk-expo';
import type { BasicUser } from '@/types/models';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export function useUserDetails() {
    const { isLoaded, isSignedIn } = useAuth();
    const api = useApiRequest();
    return useQuery<BasicUser, Error>({
        queryKey: ['user', 'details'],
        queryFn: () =>
            api.get<BasicUser>(ROUTES.GET_USER_DETAILS, {
                // Profile data drives checkout gating (location, wallet, debt), so
                // never serve it from an intermediary cache.
                headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate' },
                params: { t: Date.now() },
            }),
        enabled: isLoaded && isSignedIn,
        retry: retryTransientOnly(2)
    });
}

export function useUpdateLocation() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (coords: { lat: number; lng: number }) => api.post(ROUTES.UPDATE_LOCATION, coords),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            // Delivery fee and serviceability depend on the destination.
            queryClient.invalidateQueries({ queryKey: ['cart', 'quote'] });
            queryClient.invalidateQueries({ queryKey: ['delivery-fee'] });
            // Everything discovery serves is measured from this address, and the
            // server resolves it rather than taking it from the request — so the
            // request that produced a cached result is byte-identical to the one
            // that would produce a different result now, and nothing about the
            // key can express that. Moving the address is the invalidation.
            queryClient.invalidateQueries({ queryKey: ['vendors'] });
            queryClient.invalidateQueries({ queryKey: ['products'] });
            queryClient.invalidateQueries({ queryKey: ['search'] });
        }
    });
}

export function useUpdateProfilePic() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (profile_pic: string) => api.post(ROUTES.UPDATE_PROFILE_PIC, { profile_pic }),
        onMutate: async (newProfilePic) => {
            await queryClient.cancelQueries({ queryKey: ['user', 'details'] });
            const previousUser = queryClient.getQueryData(['user', 'details']);
            queryClient.setQueryData(['user', 'details'], (old: import("@/types/models").BasicUser | undefined) => {
                if (!old) return old;
                return { ...old, profile_pic: newProfilePic };
            });
            return { previousUser };
        },
        onError: (_err, _newProfilePic, context) => {
            if (context?.previousUser) {
                queryClient.setQueryData(['user', 'details'], context.previousUser);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
        }
    });
}

export function useCreateUser() {
    const api = useApiRequest();
    return useMutation({
        mutationFn: (userData: any) => api.post(ROUTES.CREATE_USER, userData),
    });
}

export function useUpdateUser() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (userData: { full_name?: string; phone_number?: string | null; preferences?: any; payment_methods?: any[]; floor_level?: number; has_elevator?: boolean }) =>
            api.put(ROUTES.UPDATE_USER, userData),
        onMutate: async (newUserData) => {
            await queryClient.cancelQueries({ queryKey: ['user', 'details'] });
            const previousUser = queryClient.getQueryData(['user', 'details']);
            queryClient.setQueryData(['user', 'details'], (old: import("@/types/models").BasicUser | undefined) => {
                if (!old) return old;
                return { ...old, ...newUserData };
            });
            return { previousUser };
        },
        onError: (_err, _newUserData, context) => {
            if (context?.previousUser) {
                queryClient.setQueryData(['user', 'details'], context.previousUser);
            }
        },
        onSettled: (_data, _err, variables) => {
            queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
            // Floor level and elevator feed the staircase surcharge.
            if (variables?.floor_level !== undefined || variables?.has_elevator !== undefined) {
                queryClient.invalidateQueries({ queryKey: ['cart', 'quote'] });
            }
        }
    });
}

export function useDeleteAccount() {
    const api = useApiRequest();
    return useMutation({
        mutationFn: () => api.del(ROUTES.DELETE_ACCOUNT),
    });
}
