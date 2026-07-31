import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

// ─── Types ────────────────────────────────────────────────────────────────────
export interface NotificationItem {
    id: string;
    title: string;
    message: string;
    message_type: string;
    related_order_id: string | null;
    is_read: boolean;
    delivered_via: string;
    action_url: string | null;
    created_at: string | null;
}

const NOTIFICATIONS_KEY = ['customer', 'notifications'];
const UNREAD_KEY = ['customer', 'notifications', 'unread-count'];

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useNotifications() {
    const api = useApiRequest();
    return useQuery<NotificationItem[], Error>({
        queryKey: NOTIFICATIONS_KEY,
        queryFn: () => api.get<NotificationItem[]>(ROUTES.GET_NOTIFICATIONS),
    });
}

export function useMarkNotificationRead() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            api.post(ROUTES.MARK_READ, { notification_id: notificationId }),
        onMutate: async (notificationId) => {
            // Optimistic: the badge should drop the instant the row is tapped.
            await queryClient.cancelQueries({ queryKey: NOTIFICATIONS_KEY });
            const previous = queryClient.getQueryData<NotificationItem[]>(NOTIFICATIONS_KEY);
            queryClient.setQueryData<NotificationItem[]>(NOTIFICATIONS_KEY, (old) =>
                old?.map((n) => (n.id === notificationId ? { ...n, is_read: true } : n))
            );
            return { previous };
        },
        onError: (_err, _id, context) => {
            if (context?.previous) queryClient.setQueryData(NOTIFICATIONS_KEY, context.previous);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
            queryClient.invalidateQueries({ queryKey: UNREAD_KEY });
        },
    });
}

export function useMarkAllNotificationsRead() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => api.post(ROUTES.MARK_ALL_READ),
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
            queryClient.invalidateQueries({ queryKey: UNREAD_KEY });
        },
    });
}

export function useDeleteNotification() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) => api.del(ROUTES.DELETE_NOTIFICATION(notificationId)),
        onMutate: async (notificationId) => {
            await queryClient.cancelQueries({ queryKey: NOTIFICATIONS_KEY });
            const previous = queryClient.getQueryData<NotificationItem[]>(NOTIFICATIONS_KEY);
            queryClient.setQueryData<NotificationItem[]>(NOTIFICATIONS_KEY, (old) =>
                old?.filter((n) => n.id !== notificationId)
            );
            return { previous };
        },
        onError: (_err, _id, context) => {
            if (context?.previous) queryClient.setQueryData(NOTIFICATIONS_KEY, context.previous);
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
            queryClient.invalidateQueries({ queryKey: UNREAD_KEY });
        },
    });
}

export function useUnreadNotificationCount() {
    const api = useApiRequest();
    return useQuery<{ unread_count: number }, Error>({
        queryKey: UNREAD_KEY,
        queryFn: () => api.get<{ unread_count: number }>(ROUTES.UNREAD_COUNT),
        staleTime: 1000 * 60,
    });
}
