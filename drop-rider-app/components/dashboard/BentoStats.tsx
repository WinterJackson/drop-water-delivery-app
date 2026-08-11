import React, { useContext } from 'react';
import { View } from 'react-native';
import { Text } from '@/components/ui/Text';
import { UIThemeContext } from '@/context/ThemeContext';
import { Ionicons } from '@expo/vector-icons';
import { BRAND, TOAST } from "@/constants/brandColors";
import { RiderEarnings, RiderProfile } from '@/hooks/queries/useRiderData';
import PressableScale from '@/components/ui/PressableScale';
import { useRouter } from 'expo-router';
import { formatMoneyShort } from "@/utils/money";

interface BentoStatsProps {
  earnings: RiderEarnings | undefined;
  profile: RiderProfile | undefined;
}

export default function BentoStats({ earnings, profile }: BentoStatsProps) {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === 'dark';
  const router = useRouter();

  return (
    <View className="px-5 mt-2 mb-4">
      <View className="flex-row gap-4 h-[240px]">
        {/* Left Big Card (Earnings) */}
        <PressableScale 
          onPress={() => router.push("/(screens)/Earnings")}
          className={`flex-1 rounded-[24px] p-4 flex-col justify-between overflow-hidden border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`}
          style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
        >
          <View className="z-10">
            <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Total</Text>
            <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Earnings</Text>
            <Text className={`text-xs mt-1 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>All time revenue</Text>
          </View>
          <View className="z-10 self-start mt-2">
            <Text className={`font-sans-extrabold text-2xl ${darkTheme ? "text-white" : "text-black"}`}>
              {formatMoneyShort(earnings?.total_earnings)}
            </Text>
          </View>
          <View className="self-end z-10 flex-row items-center gap-2">
            <View className={`p-3 rounded-full ${darkTheme ? "bg-[#002d47]" : "bg-primary-container"}`}>
              <Ionicons name="wallet-outline" size={24} color={darkTheme ? BRAND.primary : "white"} />
            </View>
          </View>
          <View className="absolute -bottom-4 -right-4 opacity-10">
            <Ionicons name="cash" size={120} color={BRAND.primary} />
          </View>
        </PressableScale>

        {/* Right Column with 2 Smaller Cards */}
        <View className="flex-1 flex-col gap-4">
          {/* Top Small Card (Deliveries) */}
          <PressableScale 
            onPress={() => router.push("/(screens)/Orders")}
            className={`flex-1 rounded-[24px] p-4 flex-row items-center justify-between border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`}
            style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className="z-10 flex-1 pr-2">
              <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                {earnings?.total_deliveries || 0}
              </Text>
              <Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Deliveries</Text>
            </View>
            <Ionicons name="car-outline" size={32} color={BRAND.primary} className="z-10" />
          </PressableScale>

          {/* Bottom Small Card (Rating & Gamification) */}
          <PressableScale 
            onPress={() => router.push("/(screens)/Performance")}
            className={`flex-1 rounded-[24px] p-4 flex-row items-center justify-between border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`}
            style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className="z-10 flex-1 pr-2">
              <View className="flex-row items-center gap-1">
                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                  {profile?.rating?.toFixed(1) || "5.0"}
                </Text>
                <Ionicons name="star" size={16} color="#F59E0B" />
              </View>
              <Text className={`text-xs font-sans-bold mt-1 ${profile?.is_platinum ? 'text-purple-500' : 'text-[#0295f7]'}`}>
                {profile?.is_platinum ? "Platinum" : "Standard"}
              </Text>
            </View>
            <Ionicons name="ribbon-outline" size={32} color={profile?.is_platinum ? "#A855F7" : BRAND.primary} className="z-10" />
          </PressableScale>
        </View>
      </View>
    </View>
  );
}
