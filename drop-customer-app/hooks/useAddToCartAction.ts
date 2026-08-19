import { useState } from 'react';
import { useAddToCart, isVendorConflict, vendorConflictInfo } from '@/hooks/queries/useCart';
import { Popup } from '@/lib/popup';
import { Toast } from '@/lib/toast';
import { errorMessage } from '@/API/errors';

/**
 * What happens when somebody taps "add" on a product card, wherever the card is.
 *
 * This is not a thin wrapper over the mutation: adding to a cart that already
 * holds another store's items has to *ask* before it discards them, and every
 * other failure has to say something. Both halves lived inside
 * `HorizontalList`, which meant the home shelf had them and Deals & Offers —
 * the screen whose entire purpose is buying something on discount — had no add
 * control at all. Copying the handler across would have made two
 * implementations of "may I replace your cart?", and the one that gets missed
 * is the one that silently throws away a basket.
 *
 * `pendingId` rather than a bare boolean: several cards are on screen at once
 * and only the tapped one should show a spinner.
 */
export function useAddToCartAction() {
    const { mutate, isPending } = useAddToCart();
    const [pendingId, setPendingId] = useState<string | null>(null);

    const addToCart = (id: string, forceReplace = false) => {
        setPendingId(id);
        mutate(
            { id, quantity: 1, force_replace: forceReplace },
            {
                onSettled: () => setPendingId(null),
                onError: (error: Error) => {
                    // The vendor name lives on `ApiError.detail`; reading it off
                    // the error itself rendered "Your cart has items from
                    // undefined."
                    if (isVendorConflict(error)) {
                        const { existingVendor } = vendorConflictInfo(error);
                        Popup.show({
                            title: 'Replace Cart?',
                            message: `Your cart has items from ${existingVendor}. Adding this will replace your current cart.`,
                            cancelText: 'Cancel',
                            confirmText: 'Replace',
                            isDestructive: true,
                            onConfirm: () => {
                                Popup.hide();
                                addToCart(id, true);
                            },
                        });
                        return;
                    }
                    // Every other failure used to be swallowed entirely: tapping
                    // "add" on a sold-out item did nothing at all, with no
                    // explanation.
                    Toast.error("Couldn't add to cart", errorMessage(error, 'Please try again.'));
                },
            },
        );
    };

    /** True only for the card that was actually tapped. */
    const isAdding = (id: string) => isPending && pendingId === id;

    return { addToCart, isAdding };
}
