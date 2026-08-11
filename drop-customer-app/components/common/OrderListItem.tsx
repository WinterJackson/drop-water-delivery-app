import { View, Image } from 'react-native';
import { Text } from '@/components/ui/Text';import React, { useContext } from 'react'
import { UIThemeContext } from '@/context/ThemeContext';
import { Ionicons } from "@expo/vector-icons";
import { formatMoney } from "@/utils/money";

type Props = {
  data?: any;
}

const OrderListItem = ({ data }: Props) => {
  // <---------------------HOOKES----------------------->
  const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
  
  if (!data) return null;

  const isDelivered = data.order_status === "delivered" || data.order_status === "completed";
  const isCancelled = data.order_status === "cancelled" || data.order_status === "failed" || data.order_status === "rejected";
  const isPaused = data.order_status === "mismatch_pending";
  const statusColor = isDelivered ? "bg-gray-200" : (isCancelled ? "bg-red-500/20" : (isPaused ? "bg-amber-500/20" : "bg-accentbg"));
  const textColor = isDelivered ? "text-black" : (isCancelled ? "text-red-500" : (isPaused ? "text-amber-500" : "text-white"));
  const statusText = isDelivered ? "Delivered" : (isCancelled ? "Cancelled" : (isPaused ? "Paused" : "In Transit"));

  return (
    <View className={`flex-row gap-3 items-center`}>
      <View className={`w-[60px] h-[60px] items-center justify-center rounded-full ${darkTheme?"bg-gray-200/10":"bg-white"}`}>
        <Ionicons name="cube" size={24} color={darkTheme?"gray":"dimgray"} />
      </View>
      <View className={`flex-1`}>
        <Text className={`font-sans-bold text-lg ${darkTheme?"text-white":"text-black"}`}>#{data.order_id?.substring(0, 18).toUpperCase()}</Text>
        <View className={`flex-row justify-between items-center `}>
          <Text className={`${darkTheme?"text-white":"text-black"}`}>Cost: {formatMoney(data.total_amount)}</Text>
          <View className={`px-4 py-1 rounded-full ${darkTheme && isDelivered ? "bg-gray-200/20" : statusColor}`}>
            <Text className={`font-sans-semibold ${darkTheme && isDelivered ? "text-white" : textColor}`}>{statusText}</Text>
          </View>
        </View>
      </View>
    </View>
  )
}

export default OrderListItem