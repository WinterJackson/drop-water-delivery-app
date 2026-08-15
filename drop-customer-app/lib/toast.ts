import { useToastStore } from '@/stores/toastStore';

/**
 * Global Toast utility.
 *
 * `unknown` rather than `any`: a caller genuinely may pass anything — the whole
 * point is that `Toast.error("…", err)` is safe with a raw thrown value — but
 * `unknown` says so while still forcing the store to narrow before it renders,
 * which `safeString` already does. `any` would have let a future call site read
 * a property straight off the argument with no complaint.
 */
export const Toast = {
    success: (text1: unknown, text2?: unknown) => {
        useToastStore.getState().showToast('success', text1, text2);
    },
    error: (text1: unknown, text2?: unknown) => {
        useToastStore.getState().showToast('error', text1, text2);
    },
    info: (text1: unknown, text2?: unknown) => {
        useToastStore.getState().showToast('info', text1, text2);
    },
};
