import { ROUTES } from '@/API/routes/ApiRoutes';
import { ApiError, retryTransientOnly } from '@/API/errors';
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
/**
 * Cross-party contact information for an active order.
 * @param orderId - The order UUID
 * @param orderStatus - Current order status (used to skip the query when inactive)
 */
export function useOrderContacts(orderId: string | null, orderStatus: string | null) {
    const api = useApiRequest();
    const isActive = orderStatus ? CONTACT_VISIBLE_STATES.includes(orderStatus) : false;

    return useQuery<OrderContactsResponse, Error>({
        queryKey: ['orderContacts', orderId],
        queryFn: async () => {
            try {
                return await api.get<OrderContactsResponse>(ROUTES.ORDER_CONTACTS(orderId!));
            } catch (error) {
                // The backend withholds contacts outside active fulfilment states.
                // That is an expected answer, not a failure worth surfacing.
                if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
                    return { contacts: [] };
                }
                throw error;
            }
        },
        enabled: !!orderId && isActive,
        staleTime: 1000 * 60 * 2, // 2 min — contacts don't change often
        retry: retryTransientOnly(1),
    });
}
