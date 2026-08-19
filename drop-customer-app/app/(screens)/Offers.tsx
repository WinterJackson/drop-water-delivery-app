import React, { useContext, useCallback, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, StatusBar, RefreshControl, Dimensions, Image } from "react-native";
import { Text } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { FlashList } from "@shopify/flash-list";
import { useProductsWithOffer, offerRows } from "@/hooks/queries/useProducts";
import { keepPaging } from "@/utils/paging";
import { OfferItemSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { discountPercent, discountedPrice, formatMoney } from "@/utils/money";
import { estimateDeliveryTime, hasEstimate } from "@/utils/distance";
import { useUserDetails } from "@/hooks/queries/useUser";

const { width } = Dimensions.get("window");

export default function Offers() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User } = useUserDetails();
    const offersQuery = useProductsWithOffer();
    const { isLoading, isFetchingNextPage, hasNextPage, refetch } = offersQuery;
    const Offers = offerRows(offersQuery.data);
    const [refreshing, setRefreshing] = useState(false);

    const onRefresh = useCallback(async () => {
        setRefreshing(true);
        await refetch();
        setRefreshing(false);
    }, [refetch]);

    const renderEmpty = () => {
        if (isLoading) return null;
        return (
            <View className="flex-1 items-center justify-center pt-20">
                <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>No Active Deals</Text>
                <Text className={`text-sm text-center mt-2 px-10 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Check back later for exclusive multivendor water drops and special bulk refills.</Text>
            </View>
        );
    };

    const renderItem = ({ item }: { item: any }) => {
        const percentageOffer = discountPercent(item.price, item.discount);
        return (
            <View className={`items-center`} style={{ width: "100%", paddingHorizontal: 8, paddingVertical: 10 }}>
                <PressableScale activeOpacity={0.7} onPress={() => router.push(`/product-details/${item.id}`)} className="w-full">
                    <View className={`rounded overflow-hidden relative ${darkTheme?"bg-black":"bg-white "} w-full`}>
                        {/* Offer Badge */}
                        <View className={`absolute w-[60px] bg-red-500 z-20 right-0 items-center justify-center rotate-45 translate-x-4 translate-y-2`}>
                            <Text className={`text-white font-sans-semibold text-xs`}>{percentageOffer}%</Text>
                        </View>
                        {/* image */}
                        <View className={`w-full`} style={{ height: width * 0.3 }}>
                            <Image source={{ uri: item.image_url }} className="w-full h-full rounded" resizeMode="cover" />
                        </View>
                        {/* Name, pricing and delivery time.
                            Height is left to the content. It was `h-[50px]`
                            with the price and the estimate side by side on one
                            `justify-between` row, which does not fit a card
                            this wide: the estimate was clipped mid-word by the
                            card's edge, so "40 mins" reached the customer as
                            "40 m". A fixed height cannot adapt to a longer
                            price, a longer name or a larger system font. */}
                        <View className={`w-full px-1 py-2`}>
                            {/* `numberOfLines`, not `substring(0, 20)`. Cutting
                                at a character count ignores how wide the glyphs
                                actually are, so it truncated names that fit and
                                left ones that did not still overflowing — and it
                                appended "..." to text the renderer would have
                                ellipsised itself. */}
                            <Text
                                className={`${darkTheme ? "text-white" : " text-black"}`}
                                numberOfLines={1}
                            >
                                {item.name}
                            </Text>
                            {/* price and discount */}
                            <View className={`flex-row gap-2 items-center mt-0.5`}>
                                <Text className={`font-sans-semibold ${darkTheme ? "text-white" : " text-black"}`}>
                                    {formatMoney(discountedPrice(item.price, item.discount))}
                                </Text>
                                {!!item.discount && (
                                    <Text style={{ textDecorationLine: "line-through" }} className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                        {formatMoney(item.price)}
                                    </Text>
                                )}
                            </View>
                            {/* Est. delivery, measured from this store to this
                                customer. It was the string "40 mins", hard-coded
                                — the same figure on every card whatever the
                                distance, on the one screen built for comparing
                                offers across stores. `estimateDeliveryTime` is
                                what the rest of the app quotes from. */}
                            {hasEstimate(item.vendor?.lat, item.vendor?.lng, User?.lat, User?.lng) && (
                                <View className="flex-row gap-1 items-center mt-1">
                                    <Ionicons name="bicycle" size={14} color={BRAND.primary} />
                                    <Text
                                        className={darkTheme ? "text-gray-300 text-xs" : "text-gray-700 text-xs"}
                                        numberOfLines={1}
                                    >
                                        {estimateDeliveryTime(
                                            item.vendor?.lat ?? undefined,
                                            item.vendor?.lng ?? undefined,
                                            User?.lat ?? undefined,
                                            User?.lng ?? undefined,
                                        )}
                                    </Text>
                                </View>
                            )}
                        </View>
                    </View>
                </PressableScale>
            </View>
        );
    };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className={`flex-row items-center px-4 py-3 pb-4 mb-2 ${darkTheme ? "bg-black" : "bg-white"} shadow-sm z-10`}
                style={{ 
    backgroundColor: darkTheme ? "#000" : "#f9fafb",
    borderBottomWidth: 1, 
    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
}}
            >
                <PressableScale onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Offers & Deals
                </Text>
            </View>
            </View>

            {isLoading && Offers.length === 0 ? (
                <View className="flex-row flex-wrap px-2">
                    {[...Array(6)].map((_, i) => (
                        <View key={i} style={{ width: '50%' }}>
                            <OfferItemSkeleton />
                        </View>
                    ))}
                </View>
            ) : (
                <FlashList
                    data={Offers}
                    renderItem={renderItem}
                    keyExtractor={(item) => item.id.toString()}
                    numColumns={2}
                    contentContainerStyle={{ paddingHorizontal: 8, paddingBottom: 120, paddingTop: 10 }}
                    ListEmptyComponent={renderEmpty}
                    refreshControl={
                        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={darkTheme ? "#fff" : "#000"} />
                    }
                    onEndReached={keepPaging(offersQuery)}
                    onEndReachedThreshold={0.6}
                    ListFooterComponent={
                        isFetchingNextPage ? (
                            <View className="py-6 flex-row">
                                <View style={{ width: '50%' }}><OfferItemSkeleton /></View>
                                <View style={{ width: '50%' }}><OfferItemSkeleton /></View>
                            </View>
                        ) : !hasNextPage && Offers.length > 0 ? (
                            <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                                That's every offer on right now.
                            </Text>
                        ) : null
                    }
                />
            )}
        </SafeAreaView>
    );
}
