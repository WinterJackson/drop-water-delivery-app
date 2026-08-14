import { ROUTES } from '@/API/routes/ApiRoutes';
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

const NOTIFICATIONS_KEY = ['customer', 'notifications'];
const UNREAD_KEY = ['customer', 'notifications', 'unread-count'];

/**
 * Rows per request.
 *
 * `GET /api/notifications` has always taken `skip` and `limit` and caps `limit`
 * at 100; the app sent neither, so it received the server's default page of 50
 * and had no way to ask for the 51st. The screen rendered that page under a
 * heading with no end marker and no "load more", which reads as *all* of them —
 * so an order confirmation from two months ago had not been deleted, it had
 * simply become unreachable, and the same was true in all three apps.
 */
const PAGE_SIZE = 30;

type NotificationPages = InfiniteData<NotificationItem[]>;

/** Rewrite every cached page in place — the shape optimistic updates need. */
function mapCached(
    pages: NotificationPages | undefined,
    change: (rows: NotificationItem[]) => NotificationItem[],
): NotificationPages | undefined {
    if (!pages) return pages;
    return { ...pages, pages: pages.pages.map((page) => change(page ?? [])) };
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

/**
 * The notification history, oldest reachable by scrolling.
 *
 * Returns the infinite query itself; use `notificationRows(query.data)` for the
 * flat list. Screens must not flatten by hand — offset paging over a feed that
 * grows at the top re-serves a row at each page boundary, and `flattenPages`
 * is where that is dealt with once.
 */
export function useNotifications() {
    const api = useApiRequest();
    return useInfiniteQuery<NotificationItem[], Error>({
        queryKey: NOTIFICATIONS_KEY,
        initialPageParam: 0,
        queryFn: ({ pageParam }) =>
            api.get<NotificationItem[]>(ROUTES.GET_NOTIFICATIONS, {
                params: { skip: pageParam as number, limit: PAGE_SIZE },
            }),
        getNextPageParam: nextOffset<NotificationItem>(PAGE_SIZE),
    });
}

/** Every notification fetched so far, newest first, each appearing once. */
export function notificationRows(data: NotificationPages | undefined): NotificationItem[] {
    return flattenPages<NotificationItem>(data);
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
            const previous = queryClient.getQueryData<NotificationPages>(NOTIFICATIONS_KEY);
            queryClient.setQueryData<NotificationPages>(NOTIFICATIONS_KEY, (old) =>
                mapCached(old, (rows) =>
                    rows.map((n) => (n.id === notificationId ? { ...n, is_read: true } : n))
                )
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
            const previous = queryClient.getQueryData<NotificationPages>(NOTIFICATIONS_KEY);
            queryClient.setQueryData<NotificationPages>(NOTIFICATIONS_KEY, (old) =>
                mapCached(old, (rows) => rows.filter((n) => n.id !== notificationId))
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
