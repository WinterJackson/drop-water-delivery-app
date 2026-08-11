import React, { useContext } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { UIThemeContext } from '@/context/ThemeContext';
import { PressableScale } from '@/components/ui/PressableScale';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { BRAND, TOAST } from "@/constants/brandColors";
import { RiderOrder } from '@/hooks/queries/useRiderData';
import { formatMoney } from "@/utils/money";

interface ActiveTripCardProps {
  order: RiderOrder;
}

export default function ActiveTripCard({ order }: ActiveTripCardProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const router = useRouter();

  if (!order) return null;

  return (
    <View className="px-5 mb-4 mt-2">
      <Text className={`font-sans-bold mb-2 ml-1 ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Current Delivery</Text>
      <PressableScale 
        onPress={() => router.push(`/(screens)/ActiveDelivery` as any)}
      >
        <View 
          className={`w-full rounded-2xl p-4 border ${darkTheme ? "bg-[#0f291e] border-transparent" : "bg-green-50 border-green-200"}`}
          style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
        >
          <View className="flex-row justify-between items-center mb-3">
            <View className={`px-2 py-1 rounded-full ${darkTheme ? "bg-green-800" : "bg-green-200"}`}>
              <Text className={`text-xs font-sans-bold ${darkTheme ? "text-green-100" : "text-green-800"}`}>
                {order.order_status.replace(/_/g, ' ').toUpperCase()}
              </Text>
            </View>
            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
              {formatMoney(order?.total_amount)}
            </Text>
          </View>
          
          <View className="flex-row items-center mb-3">
            <Ionicons name="storefront-outline" size={20} color={BRAND.primary} />
            <Text className={`ml-2 font-sans-medium ${darkTheme ? "text-gray-200" : "text-gray-800"}`} numberOfLines={1}>
              {order.vendor?.business_name || "Vendor"}
            </Text>
          </View>

          <View className="flex-row items-center mb-4">
            <Ionicons name="location" size={20} color={BRAND.primary} />
            <Text className={`ml-2 text-sm ${darkTheme ? "text-gray-300" : "text-gray-600"}`} numberOfLines={2}>
              {order.delivery_address}
            </Text>
          </View>

          <View className={`w-full py-3 rounded-xl items-center flex-row justify-center ${darkTheme ? "bg-green-600" : "bg-green-500"}`}>
            <Text className="text-white font-sans-bold mr-2">View Delivery Details</Text>
            <Ionicons name="arrow-forward" size={18} color={BRAND.white} />
          </View>
        </View>
      </PressableScale>
    </View>
  );
}
