import React, { useContext } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import PressableScale from '@/components/ui/PressableScale';
import { UIThemeContext } from '@/context/ThemeContext';
import { BRAND } from '@/constants/brandColors';
import { formatMoneyShort } from "@/utils/money";

export default function RecentOrdersFeed({ orders, isLoading }: { orders: any[], isLoading: boolean }) {
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";

    if (isLoading || !orders || orders.length === 0) return null;
    
    return (
        <View className="mt-8 px-4 pb-24">
            <View className="flex-row justify-between items-center mb-4">
                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>Recent Orders</Text>
                <PressableScale onPress={() => router.push("/(screens)/Orders")} className="py-1 px-2">
                    <Text className="text-accentbg font-sans-semibold text-sm">View All</Text>
                </PressableScale>
            </View>
            <View className={`rounded-[20px] overflow-hidden border shadow-sm ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
                {orders.map((order: any, idx: number) => (
                    <PressableScale 
                        key={order.id} 
                        onPress={() => router.push(`/(screens)/OrderDetail/${order.id}`)}
                        className={`flex-row justify-between items-center p-4 ${idx !== orders.length - 1 ? (darkTheme ? "border-b border-slate-800/50" : "border-b border-slate-100") : ""}`}
                    >
                        <View>
                            <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-slate-900"}`}>Order #{order.id?.substring(0, 8) || "N/A"}</Text>
                            <View className="flex-row items-center mt-1.5 gap-2">
                                <View className="flex-row items-center">
                                    <View className={`w-2 h-2 rounded-full mr-1.5 ${order.order_status === "pending" ? "bg-yellow-500" : order.order_status === "delivered" ? "bg-green-500" : "bg-blue-500"}`} />
                                    <Text className={`text-xs font-sans-medium capitalize ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{order.order_status?.replace("_", " ") || "Unknown"}</Text>
                                </View>
                                {order.delivery_type && (
                                    <View className={`px-2 py-0.5 rounded-md ${order.delivery_type === 'quick_swap' ? 'bg-blue-100 dark:bg-blue-900/40' : 'bg-purple-100 dark:bg-purple-900/40'}`}>
                                        <Text className={`text-[10px] font-sans-bold ${order.delivery_type === 'quick_swap' ? 'text-blue-600 dark:text-blue-400' : 'text-purple-600 dark:text-purple-400'}`}>
                                            {order.delivery_type === 'quick_swap' ? 'Quick Swap' : 'Keep Bottle'}
                                        </Text>
                                    </View>
                                )}
                            </View>
                        </View>
                        <View className="items-end">
                            <Text className={`font-sans-bold ${darkTheme ? "text-slate-200" : "text-slate-700"}`}>{formatMoneyShort(order.total_amount)}</Text>
                            <Ionicons name="chevron-forward" size={16} color={BRAND.primary} className="mt-1" />
                        </View>
                    </PressableScale>
                ))}
            </View>
        </View>
    );
}
