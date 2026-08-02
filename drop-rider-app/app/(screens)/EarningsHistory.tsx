import React, { useState, useMemo, useContext } from 'react';
import { ActivityIndicator, View, Text, StatusBar, SectionList, TouchableOpacity, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { BRAND } from '../../constants/brandColors';
import { UIThemeContext } from '../../context/ThemeContext';
import BackButtonMinimal from '../../components/ui/BackButtonMinimal';
import { useEarningsHistoryPaginated, RiderOrder } from '../../hooks/queries/useRiderData';
import { RiderEarningsHistorySkeleton } from '../../components/skeletons/ContextualSkeletons';
import { EmptyState } from '../../components/ui/EmptyState';
import { useRouter } from 'expo-router';

const formatCurrency = (amount: number) => `KSH ${Math.round(amount || 0).toLocaleString()}`;

const AccordionItem = ({ order, darkTheme }: { order: RiderOrder, darkTheme: boolean }) => {
    const [expanded, setExpanded] = useState(false);

    // Calculate totals based on backend values, fallback to 0 if undefined
    const baseFee = order.delivery_fee || 0;
    const payloadBonus = order.payload_surcharge || 0;
    const staircaseBonus = order.staircase_surcharge || 0;
    const commission = order.rider_commission || 0;
    const netPayout = order.rider_net || 0;
    const vendorName = order.vendor?.business_name || "Drop Vendor";
    
    let dateFormatted = "N/A";
    if (order.created_at) {
        const d = new Date(order.created_at);
        dateFormatted = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: 'numeric', hour12: true }).format(d);
    }
    
    const itemCount = order.order_item?.reduce((sum, item) => sum + item.quantity, 0) || 0;

    return (
        <View 
            className={`mb-3 rounded-2xl overflow-hidden border ${darkTheme ? "border-white/10 bg-white/5" : "border-gray-200 bg-white"}`}
        >
            <TouchableOpacity 
                activeOpacity={0.7} 
                onPress={() => setExpanded(!expanded)}
                className="p-4 flex-row items-center justify-between"
            >
                <View className="flex-row items-center flex-1">
                    <View className={`w-12 h-12 rounded-full items-center justify-center mr-3`} style={{ backgroundColor: `${BRAND.primary}15` }}>
                        <Ionicons name="checkmark-done" size={24} color={BRAND.primary} />
                    </View>
                    <View className="flex-1">
                        <Text className={`font-bold text-base ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
                            {vendorName}
                        </Text>
                        <View className="flex-row items-center mt-1">
                            <Ionicons name="time-outline" size={12} color={BRAND.primary} />
                            <Text className={`text-xs ml-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{dateFormatted}</Text>
                            <Text className={`text-xs mx-2 ${darkTheme ? "text-gray-600" : "text-gray-300"}`}>•</Text>
                            <Ionicons name="water-outline" size={12} color={BRAND.primary} />
                            <Text className={`text-xs ml-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{itemCount} items</Text>
                        </View>
                    </View>
                </View>

                <View className="items-end">
                    <Text className={`font-bold text-lg text-green-500`}>
                        {formatCurrency(netPayout)}
                    </Text>
                    <Ionicons 
                        name={expanded ? "chevron-up" : "chevron-down"} 
                        size={16} 
                        color={BRAND.primary} 
                        style={{ marginTop: 2 }}
                    />
                </View>
            </TouchableOpacity>

            {expanded && (
                <View className={`px-4 pb-4 pt-2 border-t ${darkTheme ? "border-white/10" : "border-gray-100"}`}>
                    <Text className={`text-xs font-bold uppercase tracking-wider mb-3 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Earnings Breakdown</Text>
                    
                    <View className="flex-row justify-between mb-2">
                        <Text className={`${darkTheme ? "text-gray-300" : "text-gray-600"}`}>Base Delivery Fare</Text>
                        <Text className={`${darkTheme ? "text-white" : "text-gray-900"}`}>{formatCurrency(baseFee)}</Text>
                    </View>

                    {payloadBonus > 0 && (
                        <View className="flex-row justify-between mb-2">
                            <View className="flex-row items-center">
                                <Text className={`${darkTheme ? "text-gray-300" : "text-gray-600"}`}>Payload Bonus</Text>
                                <View className="ml-2 bg-orange-500 px-1.5 py-0.5 rounded">
                                    <Text className="text-white text-[10px] font-bold">HEAVY</Text>
                                </View>
                            </View>
                            <Text className="text-green-500">+{formatCurrency(payloadBonus)}</Text>
                        </View>
                    )}

                    {staircaseBonus > 0 && (
                        <View className="flex-row justify-between mb-2">
                            <View className="flex-row items-center">
                                <Text className={`${darkTheme ? "text-gray-300" : "text-gray-600"}`}>Staircase Bonus</Text>
                                <View className="ml-2 bg-blue-500 px-1.5 py-0.5 rounded">
                                    <Text className="text-white text-[10px] font-bold">ELEVATION</Text>
                                </View>
                            </View>
                            <Text className="text-green-500">+{formatCurrency(staircaseBonus)}</Text>
                        </View>
                    )}

                    <View className="flex-row justify-between mb-3">
                        <Text className={`${darkTheme ? "text-gray-300" : "text-gray-600"}`}>Drop Commission Fee</Text>
                        <Text className="text-red-500">-{formatCurrency(commission)}</Text>
                    </View>

                    <View className={`flex-row justify-between pt-3 border-t ${darkTheme ? "border-white/10" : "border-gray-200"}`}>
                        <Text className={`font-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>Total Net Payout</Text>
                        <Text className={`font-bold text-lg text-green-500`}>{formatCurrency(netPayout)}</Text>
                    </View>
                </View>
            )}
        </View>
    );
};


export default function EarningsHistory() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    // Paginated: the endpoint has always defaulted to 50 rows and the old hook
    // asked for exactly one page, so a rider six months in simply could not
    // reach anything older — with no "load more" and no explanation, which reads
    // as lost history rather than a page boundary.
    const {
        data,
        isLoading,
        isRefetching,
        refetch,
        fetchNextPage,
        hasNextPage,
        isFetchingNextPage,
    } = useEarningsHistoryPaginated();

    const orders = useMemo(() => data?.pages.flat() ?? [], [data]);

    // Group orders by date (e.g., "Today", "Yesterday", "May 20, 2026")
    const groupedOrders = useMemo(() => {
        if (!orders.length) return [];

        const groups: { [key: string]: RiderOrder[] } = {};
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        orders.forEach(order => {
            if (!order.created_at) return;
            const orderDate = new Date(order.created_at);
            let dateKey = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(orderDate);

            if (orderDate.toDateString() === today.toDateString()) {
                dateKey = "Today";
            } else if (orderDate.toDateString() === yesterday.toDateString()) {
                dateKey = "Yesterday";
            }

            if (!groups[dateKey]) {
                groups[dateKey] = [];
            }
            groups[dateKey].push(order);
        });

        // Convert object to array for SectionList
        return Object.keys(groups).map(title => ({
            title,
            data: groups[title]
        }));
    }, [orders]);

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            {/* Header */}
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
                <View 
                    className="flex-row items-center px-4 py-3 pb-4 mb-2"
                    style={{ 
                        backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
                        borderBottomWidth: 1, 
                        borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                        ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                    }}
                >
                    <TouchableOpacity onPress={() => router.back()} className="mr-4">
                        <BackButtonMinimal />
                    </TouchableOpacity>
                    <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-black"}`}>
                        Earnings Breakdown
                    </Text>
                </View>
            </View>

            <SectionList<{ title: string, data: RiderOrder[] }>
                sections={groupedOrders as any}
                keyExtractor={(item: any) => item.id}
                contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
                refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={refetch} />}
                onEndReached={() => { if (hasNextPage && !isFetchingNextPage) fetchNextPage(); }}
                onEndReachedThreshold={0.4}
                ListFooterComponent={
                    isFetchingNextPage ? (
                        <View className="py-6 items-center">
                            <ActivityIndicator color={BRAND.primary} />
                        </View>
                    ) : !hasNextPage && orders.length > 0 ? (
                        <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                            That's your full delivery history.
                        </Text>
                    ) : null
                }
                renderItem={({ item }: { item: any }) => <AccordionItem order={item} darkTheme={darkTheme} />}
                renderSectionHeader={({ section: { title } }: { section: any }) => (
                    <Text className={`text-sm font-bold uppercase tracking-wider mb-3 mt-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {title}
                    </Text>
                )}
                ListEmptyComponent={
                    isLoading ? (
                        <RiderEarningsHistorySkeleton />
                    ) : (
                        <View className="mt-10">
                            <EmptyState 
                                mood="sad" 
                                title="No Deliveries Yet" 
                                subtitle="Your completed deliveries and their exact earnings breakdown will appear here." 
                            />
                        </View>
                    )
                }
            />
        </SafeAreaView>
    );
}
