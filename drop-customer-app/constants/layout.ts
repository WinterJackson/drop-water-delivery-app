/**
 * The floating tab bar's geometry, declared once for the whole app.
 *
 * The bar is an absolutely-positioned pill in `app/(screens)/_layout.tsx`. It is
 * not a `Stack.Screen`, it is not in the layout flow, and it therefore reserves
 * no space: content scrolls *underneath* it unless a screen leaves room. Nothing
 * warns you when a screen forgets, because the overlap only shows once there is
 * enough data to reach the bottom of the list — which on a fresh account or a
 * seeded dev database is usually never.
 *
 * Seventy screens each carried their own guess. Seven different values were in
 * use — 120, 100, 60, 40, 24, `120 + insets.bottom + 16`, and nothing at all —
 * and the ones that were too small clipped real content: the last wallet
 * transaction in all three apps, the last support message, the last line of an
 * order's detail. A figure that has to agree with a component in another file
 * is not a per-screen decision, so it lives here and every screen reads it.
 */
import { useSafeAreaInsets } from 'react-native-safe-area-context';

/** Height of the pill itself — `h-[64px]` on the bar in `_layout.tsx`. */
export const TAB_BAR_HEIGHT = 64;

/** Gap between the safe-area bottom and the pill — `bottom: insets.bottom + 8`. */
export const TAB_BAR_OFFSET = 8;

/** How far the bar's top edge sits above the safe area. */
export const TAB_BAR_CLEARANCE = TAB_BAR_HEIGHT + TAB_BAR_OFFSET;

/** Space left between the bar and the last item, so content does not touch it. */
export const CONTENT_BREATHING_ROOM = 16;

/**
 * Bottom padding that clears the floating tab bar.
 *
 * Includes `insets.bottom` deliberately, which is the one figure a screen cannot
 * hardcode. It is correct for a scroller that reaches the physical bottom of the
 * screen, and safely generous — by exactly `insets.bottom` — for one already
 * inside a `SafeAreaView`. Over-padding costs a little extra scroll travel past
 * the last row; under-padding hides that row behind the bar, so the asymmetry is
 * the whole reason for a single value rather than a per-screen judgement.
 *
 * `extra` is for screens with something else pinned above the bar, such as a
 * sticky footer button.
 */
export function useTabBarClearance(extra = 0): number {
    const insets = useSafeAreaInsets();
    return insets.bottom + TAB_BAR_CLEARANCE + CONTENT_BREATHING_ROOM + extra;
}
