import { ApiError, retryTransientOnly } from '@/API/errors';
import VendorApiRoutes from '@/API/routes/VendorApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useQuery } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface ContactInfo {
    role: "customer" | "vendor" | "rider";
    name: string;
    phone: string;
    vehicle_details?: string;
    profile_pic?: string;
}

export interface OrderContactsResponse {
    contacts: ContactInfo[];
}

// Active states where contacts are available
const CONTACT_VISIBLE_STATES = ["accepted", "preparing", "ready", "picked_up", "mismatch_pending", "pending_review"];

// ─── Hook ─────────────────────────────────────────────────────────────────────
export function useOrderContacts(orderId: string | null, orderStatus: string | null) {
    const { get } = useApiRequest();
    const isActive = orderStatus ? CONTACT_VISIBLE_STATES.includes(orderStatus) : false;

    return useQuery<OrderContactsResponse, Error>({
        queryKey: ['orderContacts', orderId],
        queryFn: async () => {
            try {
                return await get<OrderContactsResponse>(
                    VendorApiRoutes.GetOrderContacts(orderId!).path,
                );
            } catch (error) {
                // The backend withholds contacts outside the active window, and
                // outside it there is nothing to show — an empty list, not an
                // error screen over a perfectly good order.
                if (error instanceof ApiError && error.status === 403) return { contacts: [] };
                throw error;
            }
        },
        enabled: !!orderId && isActive,
        staleTime: 1000 * 60 * 2,
        retry: retryTransientOnly(1),
    });
}
