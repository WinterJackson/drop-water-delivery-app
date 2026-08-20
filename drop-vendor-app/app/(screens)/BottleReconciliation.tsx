import React, { useContext, useState } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, RefreshControl, Image, Alert, Modal } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { PressableScale } from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Skeleton } from "@/components/ui/Skeleton";
import * as Haptics from "expo-haptics";
import { useBottleDebtors, type BottleDebtor } from "@/hooks/queries/useBottleDebtors";
import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { PERMISSIONS, useCan } from "@/hooks/queries/useVendorProfile";
import Toast from "react-native-toast-message";

export default function BottleReconciliation() {
    const tabBarClearance = useTabBarClearance();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { post } = useApiRequest();
  const canReceive = useCan(PERMISSIONS.manageBottles);

  const { data: debtors = [], isLoading, refetch, isRefetching } = useBottleDebtors();

  const [selectedRider, setSelectedRider] = useState<any>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [input10L, setInput10L] = useState("");
  const [input20L, setInput20L] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // The endpoint already returns only riders with a positive balance, and it
  // reads the ledger rather than the registry — so riders who took a radar order
  // without ever registering with this vendor are included. Filtering on
  // registry status here is what previously hid them and their bottles.
  const ridersWithDebt: BottleDebtor[] = debtors;

  const openReceiveModal = (rider: any) => {
    if (!canReceive) {
      Toast.show({
        type: "error",
        text1: "Not allowed",
        text2: "Ask the store owner to enable receiving empty bottles for you.",
      });
      return;
    }
    setSelectedRider(rider);
    setInput10L("");
    setInput20L("");
    setModalVisible(true);
  };

  const handleReceiveBottles = async () => {
    const recv10 = parseInt(input10L) || 0;
    const recv20 = parseInt(input20L) || 0;

    if (recv10 === 0 && recv20 === 0) {
      Alert.alert("Invalid Amount", "Please enter at least one bottle received.");
      return;
    }

    if (recv10 > (selectedRider?.pending_10L_empties || 0)) {
      Alert.alert("Excess Amount", `You cannot receive more 10L bottles than owed (${selectedRider?.pending_10L_empties}).`);
      return;
    }

    if (recv20 > (selectedRider?.pending_20L_empties || 0)) {
      Alert.alert("Excess Amount", `You cannot receive more 20L bottles than owed (${selectedRider?.pending_20L_empties}).`);
      return;
    }

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setIsSubmitting(true);
      await post(VendorApiRoutes.ReceiveBottles.path, {
        rider_id: selectedRider.rider_id,
        received_10L: recv10,
        received_20L: recv20,
      });

      Toast.show({ type: 'success', text1: 'Success', text2: 'Rider debt cleared successfully.' });
      setModalVisible(false);
      refetch();
    } catch (err) {
      // `settle_empties` refuses over-receipt with the actual outstanding count.
      // Showing its message tells the vendor what the ledger says; the previous
      // "Could not process request at this time" did not.
      Toast.show({ type: 'error', text1: 'Error', text2: errorMessage(err, "Could not clear that debt right now.") });
    } finally {
      setIsSubmitting(false);
    }
  };
  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      {/* Header */}
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
          <PressableScale onPress={() => router.back()} className="mr-4">
            <BackButtonMinimal />
          </PressableScale>
          <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>Bottle Reconciliation</Text>
          {/* The balances below are a running total. This is what produced them —
              the answer to "did I already take those six back on Tuesday?", which
              no counter can give. */}
          <PressableScale
            onPress={() => router.push("/(screens)/BottleLedger" as any)}
            accessibilityRole="button"
            accessibilityLabel="Bottle history"
            className={`flex-row items-center gap-1.5 px-3 py-2 rounded-full ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`}
          >
            <Ionicons name="time-outline" size={16} color={BRAND.primary} />
            <Text className="text-xs font-sans-bold" style={{ color: BRAND.primary }}>History</Text>
          </PressableScale>
        </View>
      </View>

      <ScrollView 
        className="flex-1 px-6 pt-2"
        refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={BRAND.primary} />}
            contentContainerStyle={{ paddingBottom: tabBarClearance }}
        >
        <Text className={`text-sm mb-6 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
          Empties owed to you by riders who delivered your Quick Swap orders. Log what they physically hand back to clear their balance — every entry is recorded against the order it came from.
        </Text>

        {isLoading && !debtors.length ? (
          <View>
             <Skeleton width="100%" height={200} borderRadius={24} style={{ marginBottom: 16 }} />
             <Skeleton width="100%" height={200} borderRadius={24} />
          </View>
        ) : ridersWithDebt.length === 0 ? (
          <View className="items-center justify-center py-12">
            <View className={`w-20 h-20 rounded-full items-center justify-center mb-4 ${darkTheme ? "bg-slate-800" : "bg-white border border-slate-100 shadow-sm"}`}>
              <Ionicons name="checkmark-circle-outline" size={40} color={BRAND.primary} />
            </View>
            <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>All Clear!</Text>
            <Text className={`text-center mt-2 px-6 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>No riders currently owe you any empty bottles.</Text>
          </View>
        ) : (
          ridersWithDebt.map((rider: BottleDebtor & { profile_pic?: string }) => (
            <View 
              key={rider.rider_id} 
              className={`p-5 rounded-3xl mb-4 border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
              style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
            >
              <View className="flex-row items-center justify-between mb-4">
                <View className="flex-row items-center">
                  <View className="w-12 h-12 rounded-full overflow-hidden mr-3 bg-slate-200">
                    {rider.profile_pic ? (
                      <Image source={{ uri: rider.profile_pic }} className="w-full h-full" />
                    ) : (
                      <View className="w-full h-full items-center justify-center bg-slate-300">
                        <Ionicons name="person" size={24} color="#64748b" />
                      </View>
                    )}
                  </View>
                  <View>
                    <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-slate-900"}`}>{rider.name || "Gig Rider"}</Text>
                    <Text className={`text-xs ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{rider.phone_number}</Text>
                  </View>
                </View>
              </View>

              <View className={`flex-row rounded-2xl p-3 mb-4 ${darkTheme ? "bg-black/30" : "bg-slate-50"}`}>
                <View className="flex-1 items-center border-r border-slate-200 dark:border-slate-700">
                  <Text className={`text-xs font-sans-medium mb-1 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>10L Empties Owed</Text>
                  <Text className={`text-xl font-sans-bold ${rider.pending_10L_empties > 0 ? "text-orange-500" : darkTheme ? "text-white" : "text-slate-900"}`}>
                    {rider.pending_10L_empties || 0}
                  </Text>
                </View>
                <View className="flex-1 items-center">
                  <Text className={`text-xs font-sans-medium mb-1 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>20L Empties Owed</Text>
                  <Text className={`text-xl font-sans-bold ${rider.pending_20L_empties > 0 ? "text-orange-500" : darkTheme ? "text-white" : "text-slate-900"}`}>
                    {rider.pending_20L_empties || 0}
                  </Text>
                </View>
              </View>

              <PressableScale 
                onPress={() => openReceiveModal(rider)}
                className="w-full h-[45px] justify-center items-center rounded-xl bg-slate-900 dark:bg-white"
              >
                <Text className="text-white dark:text-slate-900 font-sans-bold">Receive Empties</Text>
              </PressableScale>
            </View>
          ))
        )}
        <View className="h-10" />
      </ScrollView>

      {/* Receive Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={modalVisible}
        onRequestClose={() => setModalVisible(false)}
      >
        <View className="flex-1 justify-end bg-black/50">
          <View className={`p-6 rounded-t-3xl ${darkTheme ? "bg-surface-container" : "bg-white"}`}>
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Receive Empties</Text>
              <PressableScale accessibilityLabel="Close the empties form" onPress={() => setModalVisible(false)} className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-black/50" : "bg-slate-100"}`}>
                <Ionicons name="close" size={20} color={darkTheme ? "#fff" : "#0f172a"} />
              </PressableScale>
            </View>

            <Text className={`text-sm mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Enter the number of empties physically returned by <Text className="font-sans-bold text-slate-900 dark:text-white">{selectedRider?.name}</Text>.
            </Text>

            <View className="flex-row justify-between mb-6">
              <View className="flex-1 mr-2">
                <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>10L BOTTLES</Text>
                <TextInput
                  value={input10L}
                  onChangeText={setInput10L}
                  keyboardType="numeric"
                  placeholder={`Max: ${selectedRider?.pending_10L_empties || 0}`}
                  placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                  className={`p-4 rounded-xl border font-sans-bold text-lg text-center ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
                />
              </View>
              <View className="flex-1 ml-2">
                <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>20L BOTTLES</Text>
                <TextInput
                  value={input20L}
                  onChangeText={setInput20L}
                  keyboardType="numeric"
                  placeholder={`Max: ${selectedRider?.pending_20L_empties || 0}`}
                  placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                  className={`p-4 rounded-xl border font-sans-bold text-lg text-center ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
                />
              </View>
            </View>

            <PressableScale 
              onPress={handleReceiveBottles}
              disabled={isSubmitting}
              className="w-full h-[55px] justify-center items-center rounded-xl"
              style={{ backgroundColor: isSubmitting ? BRAND.gray400 : BRAND.primary }}
            >
              {isSubmitting ? (
                <Skeleton width={80} height={20} borderRadius={4} style={{ alignSelf: 'center' }} />
              ) : (
                <Text className="text-white font-sans-bold text-lg">Confirm Receipt</Text>
              )}
            </PressableScale>
            <SafeAreaView />
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
