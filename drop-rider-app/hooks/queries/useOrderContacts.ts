import { useQuery } from '@tanstack/react-query';

import { ApiError } from '@/API/errors';
import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { useApiRequest } from '@/API/useApiClient';

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
const CONTACT_VISIBLE_STATES = ["pending", "accepted", "assigned", "preparing", "ready", "picked_up", "mismatch_pending", "pending_review"];

// ─── Hook ─────────────────────────────────────────────────────────────────────
export function useOrderContacts(orderId: string | null, orderStatus: string | null) {
    const { get } = useApiRequest();
    const isActive = orderStatus ? CONTACT_VISIBLE_STATES.includes(orderStatus) : false;

    return useQuery<OrderContactsResponse, Error>({
        queryKey: ['orderContacts', orderId],
        queryFn: async () => {
            try {
                return await get<OrderContactsResponse>(RiderApiRoutes.OrderContacts(orderId!).path);
            } catch (e) {
                // 403 means this order has left the window where the parties may
                // see each other's numbers. That is the expected end state, not a
                // failure — render no contacts rather than an error.
                if (e instanceof ApiError && e.status === 403) return { contacts: [] };
                throw e;
            }
        },
        enabled: !!orderId && isActive,
        staleTime: 1000 * 60 * 2,
        retry: 1,
    });
}
