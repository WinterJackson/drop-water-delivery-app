import React, { useContext } from 'react';
import { View, ScrollView, ActivityIndicator } from 'react-native';
import { Text } from '@/components/ui/Text';
import { UIThemeContext } from '@/context/ThemeContext';
import { PressableScale } from '@/components/ui/PressableScale';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { BRAND, TOAST } from "@/constants/brandColors";
import { RiderOrder, useAcceptOrder } from '@/hooks/queries/useRiderData';
import { useToastStore } from '@/stores/toastStore';
import { HorizontalListSkeleton } from '../skeletons/ContextualSkeletons';
import { formatMoney } from "@/utils/money";

interface TripRadarListProps {
  orders: RiderOrder[];
  isLoading: boolean;
}

export default function TripRadarList({ orders, isLoading }: TripRadarListProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const { showToast } = useToastStore();
  const router = useRouter();
  
  const { mutate: acceptOrder, isPending: isAccepting } = useAcceptOrder();

  if (isLoading && orders.length === 0) {
    return (
      <View className="mt-4 mb-2">
        <View className="px-5 flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <Ionicons name="pulse-outline" size={24} color={BRAND.primary} />
            <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Trip Radar</Text>
          </View>
        </View>
        <View className="pl-5">
            <HorizontalListSkeleton />
        </View>
      </View>
    );
  }

  if (!orders || orders.length === 0) {
    return (
      <View className="mt-4 mb-2 px-5">
        <View className="flex-row items-center gap-2 mb-3">
          <Ionicons name="pulse-outline" size={24} color={BRAND.primary} />
          <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Trip Radar</Text>
        </View>
        <View 
          className={`w-full rounded-2xl p-6 items-center justify-center border border-dashed ${darkTheme ? "bg-surface-container border-gray-700" : "bg-white border-gray-300"}`}
        >
          <View className={`w-12 h-12 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-blue-900/20" : "bg-blue-50"}`}>
            <Ionicons name="planet-outline" size={24} color={BRAND.primary} />
          </View>
          <Text className={`font-sans-bold text-base mb-1 ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>Scanning for orders...</Text>
          <Text className={`text-xs text-center px-4 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
            There are currently no delivery requests in your area. Keep your app open to receive new requests.
          </Text>
        </View>
      </View>
    );
  }

  const handleAccept = (orderId: string) => {
    acceptOrder(orderId, {
      onSuccess: () => {
        showToast('success', 'Order Accepted!', 'Navigate to the vendor to pick it up.');
        router.push("/(screens)/ActiveDelivery" as any);
      },
      onError: (err: any) => {
        let title = "Failed to accept";
        if (err.status === 402) title = "Insufficient Balance";
        else if (err.status === 403) title = "Not Allowed";
        else if (err.status === 409) title = "Claimed";
        showToast('error', title, err.message || "This order was already taken by another rider.");
      }
    });
  };

  return (
    <View className="mt-4 mb-2">
      <View className="px-5 flex-row items-center justify-between mb-3">
        <View className="flex-row items-center gap-2">
          <Ionicons name="pulse-outline" size={24} color={BRAND.primary} />
          <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Trip Radar</Text>
        </View>
        <View className={`px-2 py-0.5 rounded-full ${darkTheme ? "bg-blue-900/40" : "bg-blue-100"}`}>
          <Text className="text-xs font-sans-bold text-[#0295f7]">{orders.length} Available</Text>
        </View>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}>
        {orders.map((order) => (
          <View 
            key={order.id}
            className={`w-[280px] rounded-2xl p-4 border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
            style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
          >
            <View className="flex-row justify-between items-start mb-2">
              <Text className={`font-sans-extrabold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
                {formatMoney(order?.total_amount)}
              </Text>
            </View>

            <View className="gap-2 mb-4">
              <View className="flex-row items-center">
                <Ionicons name="storefront-outline" size={16} color={BRAND.primary} />
                <Text className={`ml-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`} numberOfLines={1}>
                  Pick up: {order.vendor?.business_name}
                </Text>
              </View>
              <View className="flex-row items-center">
                <Ionicons name="location" size={16} color={BRAND.primary} />
                <Text className={`ml-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`} numberOfLines={1}>
                  Drop off: {order.delivery_address}
                </Text>
              </View>
            </View>

            <PressableScale 
              onPress={() => handleAccept(order.id)}
              disabled={isAccepting}
            >
              <View className={`w-full py-2.5 rounded-xl items-center flex-row justify-center ${darkTheme ? "bg-primary" : "bg-primary"}`} style={{ backgroundColor: BRAND.primary }}>
                {isAccepting ? (
                  <ActivityIndicator color={BRAND.white} size="small" />
                ) : (
                  <>
                    <Text className="text-white font-sans-bold mr-1">Accept Delivery</Text>
                    <Ionicons name="checkmark-circle-outline" size={18} color={BRAND.white} />
                  </>
                )}
              </View>
            </PressableScale>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
