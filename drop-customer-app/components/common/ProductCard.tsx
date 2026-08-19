import React from 'react';
import { View } from 'react-native';
import { Image } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { Text } from '@/components/ui/Text';
import { PressableScale } from '@/components/ui/PressableScale';
import { SkeletonAvatar } from '@/components/ui/Skeleton';
import { BRAND } from '@/constants/brandColors';
import { discountPercent, discountedPrice, formatMoney, isZeroMoney } from '@/utils/money';
import { estimateDeliveryTime, hasEstimate } from '@/utils/distance';

/**
 * The product card, once, for every shelf in the app.
 *
 * The home row and Deals & Offers drew the same object from the same fields and
 * disagreed about nearly all of it: a 24pt radius against a 4pt one, a bordered
 * surface against a bare `bg-black`, `expo-image` with a fade against a plain
 * `Image`, a 65pt discount ribbon against a 60pt one, `font-sans-bold` against
 * an unstyled `<Text>` — and the offers card had no add control at all, on the
 * one screen whose whole purpose is buying something on discount. Two hand-kept
 * copies of a card drift by definition; this is the same defect as the two
 * `Order` interfaces, one layer up.
 *
 * `width` is the only thing a caller varies. The horizontal shelf sizes to a
 * fraction of the viewport, the offers grid to a column, and the card is
 * otherwise identical because it is the same component.
 */
export type ProductCardItem = {
    id: string;
    name: string;
    price: string | number;
    discount?: string | number | null;
    image_url?: string | null;
    vendor?: { lat?: number | null; lng?: number | null } | null;
};

type Props = {
    item: ProductCardItem;
    width: number;
    darkTheme: boolean;
    onPress: () => void;
    onAddToCart: () => void;
    isAdding?: boolean;
    /** The customer's delivery origin, for the estimate. Omitted hides the row. */
    userLat?: number | null;
    userLng?: number | null;
    /**
     * Stretch to the parent's height so a row of cards ends level.
     *
     * The horizontal shelf gives its list a fixed height and wants every card
     * to fill it; the offers grid has no such height and wants each card to
     * size to its own content. Passing `h-full` unconditionally would collapse
     * the grid cards to nothing.
     */
    fillHeight?: boolean;
};

export default function ProductCard({
    item,
    width,
    darkTheme,
    onPress,
    onAddToCart,
    isAdding = false,
    userLat,
    userLng,
    fillHeight = false,
}: Props) {
    const showEstimate = hasEstimate(item.vendor?.lat, item.vendor?.lng, userLat, userLng);

    return (
        <PressableScale activeOpacity={0.9} onPress={onPress}>
            <View
                className={`overflow-hidden relative border ${fillHeight ? 'h-full' : ''} ${
                    darkTheme ? 'bg-surface-container border-outline-variant' : 'bg-white border-gray-200'
                }`}
                style={
                    darkTheme
                        ? { width, borderRadius: 24 }
                        : {
                              width,
                              borderRadius: 24,
                              shadowColor: '#000',
                              shadowOffset: { width: 0, height: 2 },
                              shadowOpacity: 0.05,
                              shadowRadius: 4,
                              elevation: 2,
                          }
                }
            >
                {!isZeroMoney(item.discount) && (
                    <View className="absolute w-[65px] bg-red-500 z-20 top-0 right-0 items-center justify-center rotate-45 translate-x-5 translate-y-2">
                        <Text className="text-white font-sans-semibold">
                            {item.price ? `${discountPercent(item.price, item.discount)}%` : 'Sale'}
                        </Text>
                    </View>
                )}

                {/* A square image, so a row of cards lines up whatever the art. */}
                <View className="w-full" style={{ height: width }}>
                    <Image
                        source={{ uri: item.image_url ?? undefined }}
                        style={{ width: '100%', height: '100%', borderRadius: 24 }}
                        contentFit="cover"
                        transition={200}
                    />
                </View>

                {/* Text column grows, button keeps its width; they cannot collide.
                    `flex-1` is safe here because the row's width is definite —
                    the card sets it — unlike `flex-1` in an auto-height column,
                    which collapses to nothing and clipped this very text. */}
                <View className="px-3 py-2 flex-row items-center gap-2">
                    {/* `overflow-hidden` is the hard guarantee, not decoration.
                        A React Native `View` does not clip by default, so a
                        child wider than this column is painted *outside* it —
                        and the add button is a later sibling in the same row, so
                        it draws on top of whatever spilled. That is how the
                        struck price ended up underneath the cart icon rather
                        than beside it. Clipping means the worst case is a
                        trimmed line, never text hidden behind a control. */}
                    <View className="flex-1 overflow-hidden">
                        <Text
                            className={`font-sans-bold text-sm ${darkTheme ? 'text-white' : 'text-gray-900'}`}
                            numberOfLines={1}
                        >
                            {item.name}
                        </Text>

                        {/* Wraps, because the two prices do not always fit on one
                            line and money must never be truncated to make them.
                            On this shelf the card is 38% of the viewport — about
                            161dp on a 720px handset — which leaves roughly 93dp
                            for text once the padding, the gap and the 36dp
                            button are taken out. "KSH 370.00" at 14dp beside
                            "KSH 430.00" at 12dp wants about 151dp. It never fit;
                            it only looked as though it did while the struck
                            price was printed raw as "430" instead of going
                            through `formatMoney`.
                            Ellipsising was the other option and is worse: a
                            trimmed "KSH 43…" reads as forty-three shillings, on
                            the figure a customer checks before deciding to buy.
                            Wrapping adapts on its own — one line where there is
                            room, two where there is not, at any card width,
                            price length or system font scale. */}
                        <View className="flex-row flex-wrap items-center gap-x-2 mt-0.5">
                            <Text
                                className={`font-sans-semibold text-sm ${darkTheme ? 'text-gray-300' : 'text-gray-700'}`}
                                numberOfLines={1}
                            >
                                {formatMoney(discountedPrice(item.price, item.discount))}
                            </Text>
                            {!isZeroMoney(item.discount) && (
                                <Text
                                    className={`text-xs ${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}
                                    style={{ textDecorationLine: 'line-through' }}
                                    numberOfLines={1}
                                >
                                    {formatMoney(item.price)}
                                </Text>
                            )}
                        </View>

                        {/* Omitted rather than filled with a placeholder when the
                            store's coordinates are absent: a line that says
                            "Est. Delivery available" takes a real answer's space
                            and carries none. */}
                        {showEstimate && (
                            <View className="flex-row gap-1 items-center mt-1">
                                <Ionicons name="bicycle" size={13} color={BRAND.primary} />
                                <Text
                                    className={`text-xs ${darkTheme ? 'text-gray-400' : 'text-gray-600'}`}
                                    numberOfLines={1}
                                >
                                    {estimateDeliveryTime(
                                        item.vendor?.lat ?? undefined,
                                        item.vendor?.lng ?? undefined,
                                        userLat ?? undefined,
                                        userLng ?? undefined,
                                    )}
                                </Text>
                            </View>
                        )}
                    </View>

                    {/* Filled brand circle, not `bg-white` on a white card, and
                        labelled: React Native names a touchable from its `<Text>`
                        children and this one has none, so a screen reader read a
                        column of identical "button"s. */}
                    <PressableScale
                        activeOpacity={0.6}
                        accessibilityLabel={`Add ${item.name} to cart`}
                        hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                        onPress={onAddToCart}
                    >
                        <View
                            className="w-9 h-9 items-center justify-center rounded-full"
                            style={{ backgroundColor: BRAND.primary }}
                        >
                            {isAdding ? (
                                <SkeletonAvatar size={16} />
                            ) : (
                                <Ionicons name="cart-outline" size={18} color="white" />
                            )}
                        </View>
                    </PressableScale>
                </View>
            </View>
        </PressableScale>
    );
}
