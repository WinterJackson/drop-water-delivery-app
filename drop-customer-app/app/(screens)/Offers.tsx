import React, { useContext, useCallback, useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, Text, StatusBar, RefreshControl, Dimensions, Image } from "react-native";
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { FlashList } from "@shopify/flash-list";
import { useProductsWithOffer } from "@/hooks/queries/useProducts";
import { OfferItemSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";

const { width } = Dimensions.get("window");

export default function Offers() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: Offers = [], isLoading, refetch } = useProductsWithOffer();
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
                <Text className={`text-lg font-bold ${darkTheme ? "text-white" : "text-black"}`}>No Active Deals</Text>
                <Text className={`text-sm text-center mt-2 px-10 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Check back later for exclusive multivendor water drops and special bulk refills.</Text>
            </View>
        );
    };

    const renderItem = ({ item }: { item: any }) => {
        const percentageOffer = Math.ceil((item.discount / item.price) * 100);
        return (
            <View className={`items-center`} style={{ width: "100%", paddingHorizontal: 8, paddingVertical: 10 }}>
                <PressableScale activeOpacity={0.7} onPress={() => router.push(`/product-details/${item.id}`)} className="w-full">
                    <View className={`rounded overflow-hidden relative ${darkTheme?"bg-black":"bg-white "} w-full`}>
                        {/* Offer Badge */}
                        <View className={`absolute w-[60px] bg-red-500 z-20 right-0 items-center justify-center rotate-45 translate-x-4 translate-y-2`}>
                            <Text className={`text-white font-semibold text-xs`}>{percentageOffer}%</Text>
                        </View>
                        {/* image */}
                        <View className={`w-full`} style={{ height: width * 0.3 }}>
                            <Image source={{ uri: item.image_url }} className="w-full h-full rounded" resizeMode="cover" />
                        </View>
                        {/* Name, pricing and delivery time */}
                        <View className={`w-full h-[50px] px-1 py-2`}>
                            <Text className={`${darkTheme ? "text-white" : " text-black"}`}>
                                {item.name.length > 20 ? item.name.substring(0, 20).trim() + "..." : item.name}
                            </Text>
                            <View className={`flex-row justify-between items-center`}>
                                {/* price and discount */}
                                <View className={`flex-row gap-2`}>
                                    <Text className={`font-semibold ${darkTheme ? "text-white" : " text-black"}`}>
                                        KSH {Math.round((item.price - item.discount) * 100) / 100}
                                    </Text>
                                    <Text style={{ textDecorationLine: "line-through" }} className={`${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                        {item.price}
                                    </Text>
                                </View>
                                {/* est delivery time */}
                                <View className="flex-row gap-1 items-center">
                                    <Ionicons name="bicycle" size={20} color={BRAND.primary} />
                                    <Text className={darkTheme ? "text-gray-300 text-sm" : "text-gray-700 text-sm"}>{"40 mins"}</Text>
                                </View>
                            </View>
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
                <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-black"}`}>
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
                />
            )}
        </SafeAreaView>
    );
}
