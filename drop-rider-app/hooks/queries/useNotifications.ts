import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
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

/** Defeats any intermediate cache; these are polled and must not be served stale. */
const NO_CACHE = { 'Cache-Control': 'no-cache, no-store, must-revalidate' };

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useNotifications() {
    const { get } = useApiRequest();
    return useQuery<NotificationItem[], Error>({
        queryKey: ['rider', 'notifications'],
        queryFn: () =>
            get<NotificationItem[]>(`${RiderApiRoutes.GetNotifications.path}&t=${Date.now()}`, {
                headers: NO_CACHE,
            }),
        refetchInterval: 30000, // Poll every 30 seconds for new notifications
    });
}

export function useMarkNotificationRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            post(RiderApiRoutes.MarkNotificationRead.path, { notification_id: notificationId }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications'] });
        },
    });
}

export function useMarkAllNotificationsRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => post(RiderApiRoutes.MarkAllNotificationsRead.path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications'] });
        },
    });
}

export function useUnreadNotificationCount() {
    const { get } = useApiRequest();
    return useQuery<{ unread_count: number }, Error>({
        queryKey: ['rider', 'notifications', 'unread-count'],
        queryFn: () =>
            get<{ unread_count: number }>(
                `${RiderApiRoutes.GetUnreadNotificationCount.path}&t=${Date.now()}`,
                { headers: NO_CACHE }
            ),
        refetchInterval: 30000,
    });
}

export function useDeleteNotification() {
    const { del } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            del(RiderApiRoutes.DeleteNotification(notificationId).path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications'] });
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications', 'unread-count'] });
        },
    });
}
