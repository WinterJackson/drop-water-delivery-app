import React, { useContext, useCallback, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, StatusBar, RefreshControl, Dimensions } from "react-native";
import { Text } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { FlashList } from "@shopify/flash-list";
import { useProductsWithOffer, offerRows } from "@/hooks/queries/useProducts";
import { keepPaging } from "@/utils/paging";
import { OfferItemSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { PressableScale } from "@/components/ui/PressableScale";
import { useUserDetails } from "@/hooks/queries/useUser";
import ProductCard from "@/components/common/ProductCard";
import { useAddToCartAction } from "@/hooks/useAddToCartAction";

const { width } = Dimensions.get("window");

export default function Offers() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User } = useUserDetails();
    const { addToCart, isAdding } = useAddToCartAction();
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

    /* Two columns with an even gutter on both sides of both cards.
       `GRID_GAP` is applied as half-padding per cell, so the outer margins and
       the middle channel are the same width — a wrapper that only padded
       between cards leaves the row hugging the screen edges. The card is told
       its exact pixel width rather than `100%`, because it sizes its own square
       image from that number. */
    const GRID_GAP = 12;
    const cardWidth = Math.floor((width - GRID_GAP * 3) / 2);

    const renderItem = ({ item }: { item: any }) => (
        <View style={{ paddingHorizontal: GRID_GAP / 2, paddingBottom: GRID_GAP, alignItems: "center" }}>
            <ProductCard
                item={item}
                width={cardWidth}
                darkTheme={darkTheme}
                onPress={() => router.push(`/product-details/${item.id}`)}
                onAddToCart={() => addToCart(item.id)}
                isAdding={isAdding(item.id)}
                userLat={User?.lat}
                userLng={User?.lng}
            />
        </View>
    );

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
                    contentContainerStyle={{ paddingHorizontal: GRID_GAP / 2, paddingBottom: 120, paddingTop: GRID_GAP }}
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
