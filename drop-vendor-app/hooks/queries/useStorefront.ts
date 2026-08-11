import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { retryTransientOnly } from "@/API/errors";
import { useAuth } from "@clerk/clerk-expo";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/**
 * The three decisions a store makes for itself.
 *
 * `limits` arrives with the state on purpose. Every bound here is a
 * `Platform_Settings` row an administrator can move, so a pause duration or a
 * maximum order minimum written as a literal in this app is a number that goes
 * stale silently — which is exactly what both apps did with the withdrawal fee,
 * telling riders to keep money in the wallet to earn a rule the platform does
 * not implement.
 */
export interface Storefront {
    /** Whether the store is taking orders right now. */
    accepting: boolean;
    /** open | paused | offline | closed_hours | suspended */
    state: string;
    /** The server's own sentence. Render it; never compose one here. */
    reason: string | null;
    reopens_at: string | null;
    accepts_cash: boolean;
    cash_reason: string | null;
    min_order_value: string;
    is_online: boolean;
    pause_reason: string | null;
    limits: {
        max_min_order_value: string;
        max_pause_minutes: number;
        pause_presets_minutes: number[];
        may_decline_cash: boolean;
        hours_enforced: boolean;
        /**
         * How far this store's orders travel, in km — set by Drop, not by the
         * store. It sits in `limits` because that is where the app reads the
         * figures the server owns, but it is not a ceiling on a vendor
         * control: there is no vendor control. `Vendor.delivery_radius` was
         * one, and dispatch never read it.
         */
        delivery_radius_km: number;
    };
}

const KEY = ["vendor", "storefront"] as const;

export function useStorefront() {
    const { isLoaded, isSignedIn } = useAuth();
    const { get } = useApiRequest();

    return useQuery<Storefront, Error>({
        queryKey: KEY,
        queryFn: () => get<Storefront>(VendorApiRoutes.GetStorefront.path),
        enabled: isLoaded && isSignedIn,
        retry: retryTransientOnly(),
        // A pause ends on its own, so a screen left open would keep showing
        // "paused until 14:32" past 14:32. Cheap, and only while the screen is
        // in front of somebody.
        refetchInterval: 60_000,
    });
}

/** Owner only on the server — the terms this store trades on. */
export function useSetStorefrontTerms() {
    const { put } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (body: { accepts_cash?: boolean; min_order_value?: number }) =>
            put<Storefront>(VendorApiRoutes.SetStorefrontTerms.path, body),
        // The server answers with the whole state, so seed the cache from the
        // response rather than refetching — and never guess it locally: a
        // refused change would otherwise leave the switch showing the value the
        // server rejected.
        onSuccess: (data) => queryClient.setQueryData(KEY, data),
    });
}

/** Shop floor — `manage_orders`. Whoever just ran out of stock is standing there. */
export function usePauseStore() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (body: { minutes: number; reason?: string }) =>
            post<Storefront>(VendorApiRoutes.PauseStore.path, body),
        onSuccess: (data) => {
            queryClient.setQueryData(KEY, data);
            queryClient.invalidateQueries({ queryKey: ["vendor", "profile"] });
        },
    });
}

export function useResumeStore() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: () => post<Storefront>(VendorApiRoutes.ResumeStore.path, {}),
        onSuccess: (data) => {
            queryClient.setQueryData(KEY, data);
            queryClient.invalidateQueries({ queryKey: ["vendor", "profile"] });
        },
    });
}

/** "Paused until 14:32" → "32 min left". Presentation only. */
export function minutesRemaining(reopensAt: string | null): number | null {
    if (!reopensAt) return null;
    const ms = new Date(reopensAt).getTime() - Date.now();
    if (!Number.isFinite(ms) || ms <= 0) return null;
    return Math.ceil(ms / 60_000);
}
