import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';

/**
 * Hook to reject an assigned delivery order.
 * Triggers backend reassignment engine and invalidates local order cache.
 */
export function useRejectDelivery() {
    const { put } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (orderId: string) => put(RiderApiRoutes.RejectDelivery(orderId).path),
        onSuccess: () => {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
            queryClient.invalidateQueries({ queryKey: ['rider', 'notifications'] });
        },
        onError: () => {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        },
    });
}
