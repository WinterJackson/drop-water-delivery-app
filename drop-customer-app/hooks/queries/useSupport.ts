import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/**
 * Support tickets, from the customer's side.
 *
 * The admin console has the queue; this is where a ticket comes from. Without
 * it the support feature is an inbox nobody can write to.
 *
 * Identity is the token's. A ticket id belonging to somebody else is a 404
 * rather than a 403 — confirming the id exists is itself a leak. An order
 * referenced on a new ticket is checked against the caller for the same reason.
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

const KEY = ['customer', 'support'] as const;

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useSupportTickets() {
    const api = useApiRequest();
    return useQuery<SupportTicketSummary[], Error>({
        queryKey: [...KEY, 'tickets'],
        queryFn: async () => {
            const data = await api.get<{ items: SupportTicketSummary[] }>(ROUTES.GET_SUPPORT_TICKETS);
            return data.items ?? [];
        },
        staleTime: 30_000,
    });
}

export function useSupportTicket(id: string | undefined) {
    const api = useApiRequest();
    return useQuery<SupportTicketDetail, Error>({
        queryKey: [...KEY, 'ticket', id],
        queryFn: () => api.get<SupportTicketDetail>(ROUTES.GET_SUPPORT_TICKET(id!)),
        enabled: Boolean(id),
        // A reply arrives as a push, but somebody sitting on the thread waiting
        // for an answer should not have to leave and come back.
        refetchInterval: 60_000,
    });
}

export function useSupportCategories() {
    const api = useApiRequest();
    return useQuery<string[], Error>({
        queryKey: [...KEY, 'categories'],
        queryFn: async () => {
            const data = await api.get<{ categories: string[] }>(ROUTES.SUPPORT_CATEGORIES);
            return data.categories ?? [];
        },
        // A constant on the server; refetching it per visit is waste.
        staleTime: 24 * 60 * 60 * 1000,
    });
}

export function useCreateSupportTicket() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation<{ id: string; status: string; message: string }, Error, NewTicket>({
        mutationFn: (ticket) =>
            api.post<{ id: string; status: string; message: string }>(
                ROUTES.CREATE_SUPPORT_TICKET,
                ticket
            ),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [...KEY, 'tickets'] });
        },
    });
}

export function useReplyToSupportTicket(id: string | undefined) {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation<{ ok: boolean; status: string }, Error, string>({
        mutationFn: (body) =>
            api.post<{ ok: boolean; status: string }>(ROUTES.REPLY_TO_SUPPORT_TICKET(id!), { body }),
        onSuccess: () => {
            // Both: a reply can reopen a resolved ticket, so the list's status
            // badge is stale too.
            queryClient.invalidateQueries({ queryKey: [...KEY, 'ticket', id] });
            queryClient.invalidateQueries({ queryKey: [...KEY, 'tickets'] });
        },
    });
}
