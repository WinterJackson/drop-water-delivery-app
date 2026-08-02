import VendorApiRoutes from '@/API/routes/VendorApiRoutes';
import { retryTransientOnly } from '@/API/errors';
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

// Notifications are addressed to the *account*, not to one store: every route
// here already carries `?user_type=vendor` and the backend resolves the row from
// the clerk id. They are therefore not store-scoped, and sending `X-Store-Id`
// would change nothing — it is left on for consistency and costs nothing.

// ─── Hooks ────────────────────────────────────────────────────────────────────
export function useNotifications() {
    const { get } = useApiRequest();
    return useQuery<NotificationItem[], Error>({
        queryKey: ['vendor', 'notifications'],
        queryFn: () => get<NotificationItem[]>(VendorApiRoutes.GetNotifications.path),
        staleTime: 5 * 60 * 1000, // 5 minutes
        retry: retryTransientOnly(),
    });
}

export function useMarkNotificationRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            post(VendorApiRoutes.MarkNotificationRead.path, { notification_id: notificationId }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'notifications'] });
        },
    });
}

export function useMarkAllNotificationsRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => post(VendorApiRoutes.MarkAllNotificationsRead.path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'notifications'] });
        },
    });
}

export function useUnreadNotificationCount() {
    const { get } = useApiRequest();
    return useQuery<{ unread_count: number }, Error>({
        queryKey: ['vendor', 'notifications', 'unread-count'],
        queryFn: () => get<{ unread_count: number }>(VendorApiRoutes.GetUnreadNotificationCount.path),
        staleTime: 5 * 60 * 1000,
        retry: retryTransientOnly(),
    });
}

export function useDeleteNotification() {
    const { del } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            del(VendorApiRoutes.DeleteNotification(notificationId).path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['vendor', 'notifications'] });
            queryClient.invalidateQueries({ queryKey: ['vendor', 'notifications', 'unread-count'] });
        },
    });
}
