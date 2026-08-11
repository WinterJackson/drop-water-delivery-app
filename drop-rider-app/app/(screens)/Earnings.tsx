import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { UIThemeContext } from "@/context/ThemeContext";
import { Ionicons } from "@expo/vector-icons";
import { useCallback, useContext } from "react";
import {
    RefreshControl,
    ScrollView,
    StatusBar,
    View,
    TouchableOpacity,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { CashEligibilityCard } from "@/components/dashboard/CashEligibilityCard";
import { RiderEarningsSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { Skeleton } from "@/components/ui/Skeleton";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { BRAND, TOAST } from "@/constants/brandColors";
import { useRiderEarnings, useRiderProfile } from "@/hooks/queries/useRiderData";
import { useRouter } from "expo-router";
import { formatMoneyShort } from "@/utils/money";

export default function Earnings() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const { data: earnings, isLoading: earningsLoading, isError, refetch, isRefetching } = useRiderEarnings();
  const { data: profile, isLoading: profileLoading } = useRiderProfile();
  
  const isLoading = earningsLoading || profileLoading;
  const router = useRouter();

  const onRefresh = useCallback(async () => { await refetch(); }, [refetch]);

  const StatRow = ({ label, value }: { label: string; value: string | number }) => (
    <View className={`flex-row justify-between py-4 border-b ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
      <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{label}</Text>
      <Text className={`text-base font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>{value}</Text>
    </View>
  );

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
      <View style={{ overflow: "hidden", paddingBottom: 4 }}>
          <View 
              className="flex-row items-center px-4 py-3 pb-4 mb-2"
              style={{ 
                  backgroundColor: darkTheme ? "#000" : "#fff",
                  borderBottomWidth: 1, 
                  borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                  ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
              }}
          >
              <TouchableOpacity onPress={() => router.back()} className="mr-4">
                  <BackButtonMinimal />
              </TouchableOpacity>
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                  Earnings
              </Text>
          </View>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 120 }} className="px-5" refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={onRefresh} />}>

        {isLoading ? (
          <RiderEarningsSkeleton />
        ) : isError ? (
          <View className="flex-1 items-center justify-center pt-24">
            <Ionicons name="warning-outline" size={64} color={TOAST.error} />
            <Text className={`mt-4 mb-6 text-center ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
              Failed to load your earnings. Please try again.
            </Text>
            <PressableScale onPress={() => refetch()} className="px-6 py-3 rounded-xl" style={{ backgroundColor: BRAND.primary }}>
              <Text className="text-white font-sans-bold">Retry</Text>
            </PressableScale>
          </View>
        ) : (
          <>
            {/* Big Earnings Card */}
            <View className="rounded-2xl p-6 items-center mb-6 shadow-sm" style={{ backgroundColor: BRAND.primary }}>
              <Text className="text-white/70 text-sm font-sans-semibold uppercase">Total Earnings</Text>
              <Text className="text-white text-5xl font-sans-bold mt-2">
                {formatMoneyShort(earnings?.total_earnings)}
              </Text>
            </View>

            {/* Whether cash orders are open to this rider, and what stands in
                the way. On Earnings rather than Trip Radar: a rider asks "why
                can I not take those" when looking at what they made, not while
                an order is on screen for twenty seconds. */}
            <CashEligibilityCard />

            {/* Detailed Breakdown Button */}
            <PressableScale
                onPress={() => router.push("/(screens)/EarningsHistory")}
                className="rounded-2xl p-4 flex-row items-center justify-between mb-6 shadow-sm border"
                style={{
                  backgroundColor: darkTheme ? "rgba(255, 255, 255, 0.05)" : "white",
                  borderColor: darkTheme ? "rgba(255, 255, 255, 0.1)" : "#e5e7eb",
                }}
            >
                <View className="flex-row items-center gap-3">
                    <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: `${BRAND.primary}20` }}>
                        <Ionicons name="receipt-outline" size={20} color={BRAND.primary} />
                    </View>
                    <View>
                        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>See Detailed Breakdown</Text>
                        <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>View individual delivery ledgers</Text>
                    </View>
                </View>
                <Ionicons name="chevron-forward" size={20} color={BRAND.primary} />
            </PressableScale>

            <View className={`rounded-3xl p-4 shadow-sm ${darkTheme ? "bg-white/5" : "bg-white"}`}>
              <StatRow label="Rider Name" value={profile?.name || "Rider"} />
              <StatRow label="Total Deliveries" value={earnings?.total_deliveries || 0} />
              
              {/* Highlighted Bonuses */}
              <View className={`flex-row justify-between py-4 border-b ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Staircase Bonus Earned</Text>
                <Text style={{ color: TOAST.success }} className={`text-base font-sans-bold`}>+ {formatMoneyShort(earnings?.total_staircase_bonus)}</Text>
              </View>
              
              <View className={`flex-row justify-between py-4 border-b ${darkTheme ? "border-white/5" : "border-gray-100"}`}>
                <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Payload Bonus Earned</Text>
                <Text style={{ color: TOAST.success }} className={`text-base font-sans-bold`}>+ {formatMoneyShort(earnings?.total_payload_bonus)}</Text>
              </View>

              <StatRow label="Availability" value={profile?.is_available ? "Receiving Deliveries" : "Offline"} />
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
