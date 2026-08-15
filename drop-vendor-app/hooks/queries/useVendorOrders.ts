import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { VendorOrder, VendorOrderStatus } from "@/types/models";

/**
 * One page of orders as the backend actually describes it.
 *
 * The envelope used to be `{"pages": [orders]}` — the server imitating React
 * Query's own `InfiniteData` shape. Every caller then unwrapped `data.pages[0]`,
 * which is why `useVendorOrders` below discarded every page but the first, and
 * why "is there more?" was guessed from `page.length === limit` after the unwrap
 * rather than answered by the server.
 */
export interface VendorOrdersPage {
    items: VendorOrder[];
    limit: number;
    offset: number;
    has_more: boolean;
}

function ordersUrl(params: Record<string, string | number | undefined>) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== "") qs.append(key, String(value));
    }
    return `${VendorApiRoutes.GetOrders.path}?${qs.toString()}`;
}

export function useVendorOrdersPaginated(searchQuery: string = "", statusFilter: string = "All", limit: number = 20) {
    const { get } = useApiRequest();

    return useInfiniteQuery({
        queryKey: ["vendorOrdersPaginated", searchQuery, statusFilter, limit],
        queryFn: ({ pageParam = 0 }) =>
            get<VendorOrdersPage>(
                ordersUrl({
                    limit,
                    skip: pageParam,
                    search_query: searchQuery.trim().length > 1 ? searchQuery.trim() : undefined,
                    status_filter: statusFilter !== "All" ? statusFilter : undefined,
                })
            ),
        initialPageParam: 0,
        // `has_more` comes from the server now, so a page that happens to be
        // exactly `limit` long no longer triggers a pointless empty fetch.
        getNextPageParam: (lastPage) =>
            lastPage?.has_more ? (lastPage.offset ?? 0) + (lastPage.limit ?? limit) : undefined,
        retry: retryTransientOnly(),
    });
}

/** The dashboard's recent-orders feed: the newest page, not an infinite list. */
export function useVendorOrders() {
    const { get } = useApiRequest();

    return useQuery({
        queryKey: ["vendorOrders"],
        queryFn: async () => {
            const page = await get<VendorOrdersPage>(ordersUrl({ limit: 20, skip: 0 }));
            return page?.items ?? [];
        },
        retry: retryTransientOnly(),
    });
}

/**
 * One order, fetched by id.
 *
 * `OrderDetail` used to search the already-loaded list, which meant an order
 * past the first page did not exist as far as that screen was concerned.
 */
export function useVendorOrder(orderId: string | null) {
    const { get } = useApiRequest();

    return useQuery({
        queryKey: ["vendorOrder", orderId],
        queryFn: () => get<VendorOrder>(VendorApiRoutes.GetOrder(orderId!).path),
        enabled: !!orderId,
        retry: retryTransientOnly(),
    });
}

export interface OrderReview {
    order_status: string;
    actual_floor_level: number | null;
    bottle_rejection: {
        id: string;
        status: string;
        reason_text: string;
        /** Presigned for 15 minutes — do not cache these URLs. */
        photo_urls: string[];
        created_at: string | null;
    } | null;
}

/**
 * Why an order stopped.
 *
 * Only fetched for the two states that can stop one, so an ordinary order does
 * not pay for a request that would come back empty.
 */
export function useOrderReview(orderId: string | null, orderStatus?: string | null) {
    const { get } = useApiRequest();
    const relevant = orderStatus === "pending_review" || orderStatus === "mismatch_pending";

    return useQuery({
        queryKey: ["vendorOrderReview", orderId],
        queryFn: () => get<OrderReview>(VendorApiRoutes.GetOrderReview(orderId!).path),
        enabled: !!orderId && relevant,
        // The photo URLs expire in 15 minutes; refetch well inside that.
        staleTime: 5 * 60 * 1000,
        retry: retryTransientOnly(),
    });
}

export function useUpdateOrderStatus() {
    const { put } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ orderId, status }: { orderId: string; status: VendorOrderStatus }) => {
            const route = VendorApiRoutes.UpdateOrderStatus(orderId);
            return put(route.path, { status });
        },
        onMutate: async ({ orderId, status }) => {
            await queryClient.cancelQueries({ queryKey: ["vendorOrders"] });
            const previousOrders = queryClient.getQueryData<VendorOrder[]>(["vendorOrders"]);

            // Optimistically update
            queryClient.setQueryData<VendorOrder[]>(["vendorOrders"], (old) => {
                if (!Array.isArray(old)) return old;
                return old.map((order) =>
                    order.id === orderId ? { ...order, order_status: status } : order
                );
            });

            return { previousOrders };
        },
        // Typed rather than `any`: `context` is whatever `onMutate` returned, and
        // React Query infers exactly that. Annotating it `any` threw the
        // inference away and let a rename of `previousOrders` compile — the
        // rollback would then silently restore nothing on a failed accept.
        onError: (_err, _variables, context) => {
            if (context?.previousOrders) {
                queryClient.setQueryData(["vendorOrders"], context.previousOrders);
            }
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ["vendorOrders"] });
            queryClient.invalidateQueries({ queryKey: ["vendorOrdersPaginated"] });
            queryClient.invalidateQueries({ queryKey: ["vendorOrder"] });
            // Accepting or rejecting an order moves the day's counters too.
            queryClient.invalidateQueries({ queryKey: ["vendorDashboard"] });
        },
    });
}
