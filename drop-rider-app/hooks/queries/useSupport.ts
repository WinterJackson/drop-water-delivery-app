import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/**
 * Support tickets, from the rider's side.
 *
 * The admin console has the queue; this is where a ticket comes from. Without
 * it the support feature is an inbox nobody can write to.
 *
 * Identity is the token's — every route here is scoped to the rider account
 * that owns it, so a ticket id belonging to somebody else is a 404 rather than
 * a 403 (confirming the id exists is itself a leak).
 */

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SupportTicketSummary {
    id: string;
    subject: string;
    status: string;
    priority: string;
    created_at: string | null;
}

export interface SupportMessage {
    author: string;
    body: string;
    at: string | null;
}

export interface SupportTicketDetail {
    id: string;
    subject: string;
    body: string;
    status: string;
    category: string;
    created_at: string | null;
    /** Internal notes are removed by the server, not hidden by this client. */
    messages: SupportMessage[];
    resolution: string | null;
}

export interface NewTicket {
    subject: string;
    body: string;
    category: string;
    related_order_id?: string | null;
}

const KEY = ['rider', 'support'] as const;

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useSupportTickets() {
    const { get } = useApiRequest();
    return useQuery<SupportTicketSummary[], Error>({
        queryKey: [...KEY, 'tickets'],
        queryFn: async () => {
            const data = await get<{ items: SupportTicketSummary[] }>(
                RiderApiRoutes.GetSupportTickets.path
            );
            return data.items ?? [];
        },
        staleTime: 30_000,
    });
}

export function useSupportTicket(id: string | undefined) {
    const { get } = useApiRequest();
    return useQuery<SupportTicketDetail, Error>({
        queryKey: [...KEY, 'ticket', id],
        queryFn: () => get<SupportTicketDetail>(RiderApiRoutes.GetSupportTicket(id!).path),
        enabled: Boolean(id),
        // Support replies arrive as a push, but a rider sitting on the thread
        // waiting for an answer should not have to leave and come back.
        refetchInterval: 60_000,
    });
}

export function useSupportCategories() {
    const { get } = useApiRequest();
    return useQuery<string[], Error>({
        queryKey: [...KEY, 'categories'],
        queryFn: async () => {
            const data = await get<{ categories: string[] }>(RiderApiRoutes.SupportCategories.path);
            return data.categories ?? [];
        },
        // The list is a constant on the server; refetching it per visit is waste.
        staleTime: 24 * 60 * 60 * 1000,
    });
}

export function useCreateSupportTicket() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation<{ id: string; status: string; message: string }, Error, NewTicket>({
        mutationFn: (ticket) =>
            post<{ id: string; status: string; message: string }>(
                RiderApiRoutes.CreateSupportTicket.path,
                ticket
            ),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [...KEY, 'tickets'] });
        },
    });
}

export function useReplyToSupportTicket(id: string | undefined) {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation<{ ok: boolean; status: string }, Error, string>({
        mutationFn: (body) =>
            post<{ ok: boolean; status: string }>(RiderApiRoutes.ReplyToSupportTicket(id!).path, {
                body,
            }),
        onSuccess: () => {
            // Both: a reply can reopen a resolved ticket, so the list's status
            // badge is stale too.
            queryClient.invalidateQueries({ queryKey: [...KEY, 'ticket', id] });
            queryClient.invalidateQueries({ queryKey: [...KEY, 'tickets'] });
        },
    });
}
