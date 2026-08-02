import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { retryTransientOnly } from "@/API/errors";
import { useActiveStore } from "@/stores/activeStoreStore";
import { useAuth } from "@clerk/clerk-expo";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface VendorProfile {
    id: string;
    business_name: string;
    location_address?: string;
    lat?: number;
    lng?: number;
    delivery_radius?: number;
    is_online?: boolean;
    profile_pic?: string;
    phone_number?: string;
    vendor_type?: string;
    rating?: number;
    verification_status?: string;
    role?: "owner" | "staff";
    /**
     * What *this caller* may do in this store.
     *
     * Owners get every capability spelled out, so a screen checks one thing
     * rather than "is owner, or has permission". `role` used to be computed for
     * display only while the server enforced nothing at all.
     */
    permissions?: string[];
    wallet_balance?: number;
    owners_name?: string;
    email?: string;
    business_license?: string;
    deposit_fee?: number;
    shift_start?: string;
    shift_end?: string;
    preferred_payment_method?: string[];
    created_at?: string;
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

/**
 * Single source of truth for the *active store's* profile.
 *
 * The cache-busting `?t=` parameter this used to carry is gone: it defeated the
 * backend's own caching as well as the native one, and every response already
 * arrives through a client that does not cache.
 */
export function useVendorProfile() {
    const { isLoaded, isSignedIn } = useAuth();
    const { get } = useApiRequest();

    return useQuery<VendorProfile, Error>({
        queryKey: ['vendor', 'profile'],
        queryFn: () => get<VendorProfile>(VendorApiRoutes.GetProfile.path),
        enabled: isLoaded && isSignedIn,
        retry: retryTransientOnly(),
    });
}

/**
 * Update any field of the active store (delivery_radius, is_online, …).
 * Optimistically updates the local cache and reverts on error.
 *
 * Owner-only on the server (`get_owned_store`). A staff member gets a 403 whose
 * `detail.type` is `owner_only`; `errorMessage(err)` renders the sentence the
 * backend chose, so the screens do not have to invent one.
 */
export function useUpdateVendorProfile() {
    const { put } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (updates: Partial<VendorProfile>) =>
            put(VendorApiRoutes.UpdateProfile.path, updates),
        onMutate: async (updates) => {
            await queryClient.cancelQueries({ queryKey: ['vendor', 'profile'] });
            const previousProfile = queryClient.getQueryData(['vendor', 'profile']);

            // Optimistic update
            queryClient.setQueryData(['vendor', 'profile'], (old: any) => {
                if (!old) return old;
                return { ...old, ...updates };
            });

            return { previousProfile };
        },
        onError: (_err, _updates, context) => {
            if (context?.previousProfile) {
                queryClient.setQueryData(['vendor', 'profile'], context.previousProfile);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'profile'] });
            queryClient.invalidateQueries({ queryKey: ['vendorDashboard'] });
        },
    });
}

/**
 * Every store this account can reach.
 *
 * Deliberately *not* store-scoped (`allStores: true`) — it is the one endpoint
 * whose whole purpose is to return the others, and sending `X-Store-Id` would
 * narrow it to the store the switcher is trying to move away from.
 *
 * Also drops a selection that no longer resolves: a store deleted, or a device
 * now signed in as a different vendor. Without this the app would keep sending a
 * stale id and every request would 404 with no way back.
 */
/** The capability keys the backend defines. Mirrors `vendor_staff_model.py`. */
export const PERMISSIONS = {
    manageOrders: "manage_orders",
    manageProducts: "manage_products",
    manageBottles: "manage_bottles",
    viewFinances: "view_finances",
} as const;

export type PermissionKey = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

/**
 * Whether the signed-in caller may do something in the active store.
 *
 * Hiding a control is a courtesy, not a control — the server refuses regardless
 * — but offering an action that always fails is worse than not offering it.
 * Returns `false` while the profile is still loading, so nothing flashes into
 * view and then disappears.
 */
export function useCan(permission: PermissionKey): boolean {
    const { data } = useVendorProfile();
    return !!data?.permissions?.includes(permission);
}

export function useVendorStores() {
    const { isLoaded, isSignedIn } = useAuth();
    const { get } = useApiRequest();
    const reconcile = useActiveStore((s) => s.reconcile);

    const query = useQuery<VendorProfile[], Error>({
        queryKey: ['vendor', 'stores'],
        queryFn: () => get<VendorProfile[]>(VendorApiRoutes.GetStores.path, { allStores: true }),
        enabled: isLoaded && isSignedIn,
        retry: retryTransientOnly(),
    });

    const stores = query.data;
    useEffect(() => {
        if (stores) reconcile(stores.map((s) => s.id));
    }, [stores, reconcile]);

    return query;
}
