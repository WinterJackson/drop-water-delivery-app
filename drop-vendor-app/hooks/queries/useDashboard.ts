import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useAuth } from "@clerk/clerk-expo";
import { useQuery } from "@tanstack/react-query";

import type { LowStockProduct } from "@/components/dashboard/LowStockCard";

/**
 * Exactly what `GET /api/vendor/dashboard` returns, for the active store.
 *
 * Note what is *not* here: `owners_name`, `phone_number`, `business_license`,
 * `deposit_fee`, `shift_start`/`shift_end`, `preferred_payment_method`,
 * `location_address`. Four screens read those off this response and rendered
 * empty strings for every one of them — they belong to `useVendorProfile`.
 */
export interface VendorDashboard {
    vendor_id: string;
    business_name: string;
    vendor_type: string | null;
    is_online: boolean;
    total_orders: number;
    total_revenue: string;
    pending_orders: number;
    product_count: number;
    rating: number;
    /** Seven totals, Monday first — what `WeeklyRevenueChart` plots. */
    weekly_revenue: number[];
    /** At or below their own threshold. Empty when nothing needs restocking. */
    low_stock_products: LowStockProduct[];
}

export function useDashboard() {
    const { isLoaded, isSignedIn } = useAuth();
    const { get } = useApiRequest();

    return useQuery({
        queryKey: ["vendorDashboard"],
        queryFn: () => get<VendorDashboard>(VendorApiRoutes.GetDashboard.path),
        enabled: isLoaded && isSignedIn,
        retry: retryTransientOnly(),
    });
}
