import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export interface SubmitReviewPayload {
    order_id: string;
    target_type: 'vendor' | 'rider';
    target_id: string;
    rating: number;
    comment?: string;
}

export function useSubmitReview() {
    const api = useApiRequest();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (reviewData: SubmitReviewPayload) => api.post(ROUTES.SUBMIT_REVIEW, reviewData),
        onSuccess: (_data, variables) => {
            // `is_rated` on the order changes, as does the target's average rating,
            // so both the orders list and the review list are stale.
            queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
            // Prefix match: covers both the review list and the summary.
            queryClient.invalidateQueries({ queryKey: ['reviews', variables.target_type, variables.target_id] });
            queryClient.invalidateQueries({ queryKey: ['vendor', variables.target_id] });
        },
    });
}

export interface TargetReview {
    id: string;
    order_id: string;
    target_type: string;
    target_id: string;
    rating: number;
    comment: string | null;
    created_at: string;
}

export function useTargetReviews(targetType: string, targetId: string) {
    const api = useApiRequest();
    return useQuery<TargetReview[], Error>({
        queryKey: ['reviews', targetType, targetId],
        queryFn: () => api.get<TargetReview[]>(ROUTES.TARGET_REVIEWS(targetType, targetId)),
        enabled: !!targetType && !!targetId,
    });
}

export interface RatingSummary {
    target_type: string;
    target_id: string;
    average_rating: number;
    total_reviews: number;
    distribution: Record<string, number>;
}

/**
 * Average, count and star distribution for a vendor or rider.
 *
 * Separate from the review list on purpose: an average with no count is not
 * decidable — one five-star review and three hundred both render as "5.0" — and
 * counting the list client-side only counts the page that was fetched.
 */
export function useRatingSummary(targetType: string, targetId: string) {
    const api = useApiRequest();
    return useQuery<RatingSummary, Error>({
        queryKey: ['reviews', targetType, targetId, 'summary'],
        queryFn: () => api.get<RatingSummary>(ROUTES.RATING_SUMMARY(targetType, targetId)),
        enabled: !!targetType && !!targetId,
        staleTime: 1000 * 60 * 5,
    });
}
