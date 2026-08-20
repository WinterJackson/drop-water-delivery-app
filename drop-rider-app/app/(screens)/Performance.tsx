import React, { useContext } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, StatusBar, TouchableOpacity } from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import { useRiderProfile, useRiderEarnings } from "@/hooks/queries/useRiderData";
import { RiderPerformanceSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { ratingScore, UNRATED_LABEL } from "@/utils/rating";

export default function Performance() {
    const tabBarClearance = useTabBarClearance();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const router = useRouter();
  const { data: profile } = useRiderProfile();
  const { data: earnings, isLoading } = useRiderEarnings();

  const isPlatinum = profile?.is_platinum || earnings?.is_platinum;
  const deliveriesInWindow = earnings?.deliveries_in_window ?? earnings?.deliveries_last_7_days ?? 0;
  // The target and the window come from the server, which reads the same two
  // `Platform_Settings` rows the nightly job evaluates against. They were a
  // literal `20` and a literal "7 days" here, so raising the bar on the console
  // would have kept telling every rider the old number while demoting them
  // against the new one.
  const platinumTarget = earnings?.platinum_target ?? 20;
  const platinumWindowDays = earnings?.platinum_window_days ?? 7;
  const progressToPlatinum =
    platinumTarget > 0 ? Math.min((deliveriesInWindow / platinumTarget) * 100, 100) : 100;
  const deliveriesRemaining = Math.max(0, platinumTarget - deliveriesInWindow);

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      {/* Header */}
      <View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 30 }}>
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
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                  Performance & Tier
              </Text>
          </View>
      </View>

      {isLoading ? (
          <RiderPerformanceSkeleton />
      ) : (
          <ScrollView contentContainerStyle={{ paddingBottom: tabBarClearance }} className="flex-1 px-4 pt-2">
            
            {/* Gamification Tier Card */}
            <View className={`w-full rounded-2xl p-5 border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}>
              <View className="flex-row items-center justify-between mb-4">
                <View>
                  <Text className={`text-base font-sans-semibold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Current Tier</Text>
                  <View className="flex-row items-center gap-2 mt-1">
                    <Ionicons name={isPlatinum ? "ribbon" : "star"} size={24} color={isPlatinum ? "#A855F7" : BRAND.primary} />
                    <Text className={`text-3xl font-heading-semibold ${isPlatinum ? 'text-purple-500' : ''}`} style={!isPlatinum ? { color: BRAND.primary } : {}}>
                      {isPlatinum ? "Platinum" : "Standard"}
                    </Text>
                  </View>
                </View>
                <View className={`w-[60px] h-[60px] rounded-full border-4 ${isPlatinum ? 'border-purple-500' : ''} items-center justify-center`} style={!isPlatinum ? { borderColor: BRAND.primary } : {}}>
                  <Ionicons name="trophy" size={24} color={isPlatinum ? "#A855F7" : BRAND.primary} />
                </View>
              </View>
              
              <View className="flex-row justify-between mb-2">
                  <Text className={`text-sm font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Weekly Deliveries</Text>
                  <Text className={`text-sm font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{deliveriesInWindow} / {platinumTarget}</Text>
              </View>
              <View className="w-full h-3 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                <View className={`h-full ${isPlatinum ? 'bg-purple-500' : ''} rounded-full`} style={[{ width: `${progressToPlatinum}%` }, !isPlatinum ? { backgroundColor: BRAND.primary } : {}]} />
              </View>
              
              <Text className={`text-xs mt-3 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                {isPlatinum
                  ? `You're on Platinum — stay above ${platinumTarget} deliveries in ${platinumWindowDays} days to keep it.`
                  : `${deliveriesRemaining} more ${deliveriesRemaining === 1 ? "delivery" : "deliveries"} in the last ${platinumWindowDays} days unlocks Platinum and a lower commission.`}
              </Text>
            </View>

            {/* Metrics Dashboard */}
            <View className="flex-row justify-between mt-6 gap-3">
              <View className={`flex-1 p-4 rounded-2xl items-center border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-100"}`}>
                <View className="w-16 h-16 rounded-full border-4 border-green-500 items-center justify-center mb-2">
                  <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{earnings?.acceptance_rate?.toFixed(0) || 100}%</Text>
                </View>
                <Text className={`text-sm text-center font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Acceptance Rate</Text>
              </View>

              <TouchableOpacity 
                  onPress={() => router.push("/(screens)/Reviews")}
                  className={`flex-1 p-4 rounded-2xl items-center border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-100"}`}
              >
                <View className="w-16 h-16 rounded-full border-4 border-blue-500 items-center justify-center mb-2">
                  <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{ratingScore(earnings?.rating, earnings?.rating_count) ?? UNRATED_LABEL}</Text>
                </View>
                <Text className={`text-sm text-center font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Customer Rating</Text>
                <Text className={`text-xs mt-1 text-blue-500 font-sans-bold`}>View Reviews →</Text>
              </TouchableOpacity>
            </View>

            {/* Benefits Section */}
            <Text className={`text-xl font-sans-bold mt-8 mb-4 ${darkTheme ? "text-white" : "text-black"}`}>
              {isPlatinum ? "Platinum Tier Benefits" : "Standard Tier Benefits"}
            </Text>
            
            <View className={`p-4 rounded-xl mb-3 flex-row items-center gap-3 border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-100"}`}>
              <Ionicons name="flash-outline" size={24} color={BRAND.primary} />
              <View className="flex-1">
                <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>Priority Pings (Level 2)</Text>
                <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>You see Trip Radar requests 5 seconds earlier than Bronze riders.</Text>
              </View>
            </View>

            <View className={`p-4 rounded-xl mb-3 flex-row items-center gap-3 border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-100"}`}>
              <Ionicons name="cash-outline" size={24} color={TOAST.success} />
              <View className="flex-1">
                <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>Flat Commission</Text>
                <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Drop Service Fee is a flat {isPlatinum ? '7%' : '10%'} on all deliveries.</Text>
              </View>
            </View>

          </ScrollView>
      )}
    </SafeAreaView>
  );
}
