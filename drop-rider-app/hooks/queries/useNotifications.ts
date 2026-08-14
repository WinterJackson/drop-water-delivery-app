import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { flattenPages, nextOffset } from '@/utils/paging';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';

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

const NOTIFICATIONS_KEY = ['rider', 'notifications'];

/**
 * Rows per request. See the customer app's copy for the whole story: the
 * endpoint has always paged, no app asked it to, and each therefore showed the
 * newest 50 as though they were all of them.
 */
const PAGE_SIZE = 30;

type NotificationPages = InfiniteData<NotificationItem[]>;

// ─── Hooks ────────────────────────────────────────────────────────────────────

/**
 * The rider's notification history.
 *
 * Polling stops once the rider has paged back into it. Refetching an infinite
 * query refetches *every* page it holds, one request each — so a rider six
 * pages deep would have re-fetched all six every thirty seconds, on a handset
 * on mobile data, for a whole shift, to discover something that can only ever
 * appear on page one. While one page is held the poll costs what it always did;
 * past that the unread badge keeps its own thirty-second poll and pulling to
 * refresh returns to the top.
 */
export function useNotifications() {
    const { get } = useApiRequest();
    return useInfiniteQuery<NotificationItem[], Error>({
        queryKey: NOTIFICATIONS_KEY,
        initialPageParam: 0,
        queryFn: ({ pageParam }) =>
            get<NotificationItem[]>(
                `${RiderApiRoutes.GetNotifications.path}&skip=${pageParam as number}&limit=${PAGE_SIZE}&t=${Date.now()}`,
                { headers: NO_CACHE }
            ),
        getNextPageParam: nextOffset<NotificationItem>(PAGE_SIZE),
        refetchInterval: (query) =>
            (query.state.data?.pages.length ?? 0) > 1 ? false : 30000,
    });
}

/** Every notification fetched so far, newest first, each appearing once. */
export function notificationRows(data: NotificationPages | undefined): NotificationItem[] {
    return flattenPages<NotificationItem>(data);
}

export function useMarkNotificationRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (notificationId: string) =>
            post(RiderApiRoutes.MarkNotificationRead.path, { notification_id: notificationId }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
        },
    });
}

export function useMarkAllNotificationsRead() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: () => post(RiderApiRoutes.MarkAllNotificationsRead.path),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
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
            queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications', 'unread-count'] });
        },
    });
}
