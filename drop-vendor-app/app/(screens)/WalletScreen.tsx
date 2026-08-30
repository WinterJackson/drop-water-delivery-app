import React, { useContext, useState } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, RefreshControl, Dimensions, Alert, TouchableOpacity, Modal } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { PressableScale } from "@/components/ui/PressableScale";
import { Skeleton } from "@/components/ui/Skeleton";
import { format } from "date-fns";
import * as Haptics from "expo-haptics";
import { PERMISSIONS, useCan, useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { useDashboard } from "@/hooks/queries/useDashboard";
import { useWalletSummary, useWalletTransactions, useWalletWithdraw } from "@/hooks/queries/useWallet";
import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { compareMoney, formatMoney, formatMoneyShort, isNegativeMoney, isZeroMoney, moneyRatio, subtractMoney } from "@/utils/money";

/** What a user may type into an amount box: shillings, optionally cents. */
const MONEY_INPUT = /^\d+(\.\d{1,2})?$/;


export default function WalletScreen() {
    const tabBarClearance = useTabBarClearance();
    const insets = useSafeAreaInsets();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { post } = useApiRequest();

  const { data: vendor, isLoading, refetch: refetchProfile, isRefetching } = useVendorProfile();
  const { data: dashboardData, isLoading: isLoadingDashboard, refetch: refetchDashboard } = useDashboard();
  const { data: txPage, isLoading: isLoadingTx, refetch: refetchTx } = useWalletTransactions();
  // `GET /wallet-summary` requires `view_finances`, which an owner may withhold
  // from a staff member. Asking anyway would 403 on every open of this screen.
  const canSeeFinances = useCan(PERMISSIONS.viewFinances);
  const { data: summary, refetch: refetchSummary } = useWalletSummary(canSeeFinances);
  const withdrawMutation = useWalletWithdraw();

  // `/api/wallet/transactions` answers `{data, nextCursor, hasNextPage, total}`.
  // This screen treated the envelope itself as the array — `transactions.filter`
  // on an object throws, so the wallet crashed on render the moment the request
  // succeeded.
  const transactions = txPage?.data ?? [];

  const [topUpAmount, setTopUpAmount] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [isProcessingTopUp, setIsProcessingTopUp] = useState(false);
  const [isTopUpModalVisible, setIsTopUpModalVisible] = useState(false);
  
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [isWithdrawModalVisible, setIsWithdrawModalVisible] = useState(false);

  // The wallet summary is authoritative: it is the same arithmetic
  // `settlement_service` uses to *refuse* a withdrawal, so showing anything else
  // guarantees the two disagree. The profile balance is only a fallback for the
  // first frame before the summary lands.
  const balance = summary?.wallet_balance ?? vendor?.wallet_balance ?? "0";
  const committed = summary?.committed_cash_float ?? "0";
  const available = summary?.available_for_withdrawal ?? balance;
  const isInArrears = summary?.is_in_arrears ?? isNegativeMoney(balance);
  // From `Platform_Settings` via `settlement_service.withdrawal_terms`, scoped
  // to this store's type — the same function the withdrawal itself uses. These
  // were literals (`isWholesale ? 5000 : 2500`, a fee of 15, a minimum of 500),
  // so the console could not change what a vendor was told.
  // No numeric fallbacks: a literal here is a figure the console cannot change.
  const minWithdrawal = summary?.withdrawal?.minimum ?? "0";
  const withdrawalFee = summary?.withdrawal?.fee ?? "0";
  const freeCashoutThreshold = summary?.withdrawal?.fee_waiver_threshold ?? "0";

  // The waiver turns on the **amount withdrawn**, not the balance held. This
  // screen measured `balance / threshold` and told vendors to keep money in the
  // wallet to earn a free withdrawal, which is not the rule and is the opposite
  // of its purpose — the platform pays one M-Pesa tariff per disbursement.
  const amountEntered = withdrawAmount.trim() === "" ? "0" : withdrawAmount;
  const feeOnThisAmount =
    !isZeroMoney(freeCashoutThreshold) && compareMoney(amountEntered, freeCashoutThreshold) >= 0
      ? "0"
      : withdrawalFee;
  const progress = !isZeroMoney(freeCashoutThreshold)
    ? Math.min(moneyRatio(available, freeCashoutThreshold) * 100, 100)
    : 100;
  const canReachFreeWithdrawal =
    !isZeroMoney(freeCashoutThreshold) && compareMoney(available, freeCashoutThreshold) >= 0;
  const totalRevenue = dashboardData?.total_revenue ?? "0";

  const handleRefresh = async () => {
    refetchProfile();
    refetchDashboard();
    refetchTx();
    refetchSummary();
  };

  const handleTopUp = async () => {
    // The floor is `min_wallet_topup`, a settings row. It was `< 10` here with
    // "at least KSH 10" beside it — right today, wrong the moment an
    // administrator moves the row, and refusing client-side so no server log
    // would ever show it happening.
    const minTopUp = summary?.topup?.minimum ?? null;
    if (!MONEY_INPUT.test(topUpAmount.trim())) {
      Alert.alert("Invalid Amount", "Please enter the amount you want to top up.");
      return;
    }
    if (minTopUp !== null && compareMoney(topUpAmount, minTopUp) < 0) {
      Alert.alert("Invalid Amount", `Please enter at least ${formatMoney(minTopUp)} to top up.`);
      return;
    }
    if (!phoneNumber) {
      Alert.alert("Invalid Phone", "Please enter a valid M-Pesa phone number.");
      return;
    }

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setIsProcessingTopUp(true);
      await post(VendorApiRoutes.WalletTopUp.path, {
        amount: topUpAmount.trim(),
        phone_number: phoneNumber,
        user_type: "vendor",
      });
      Alert.alert("STK Push Sent", "Please check your phone and enter your M-Pesa PIN to complete the top up.");
      setTopUpAmount("");
      setIsTopUpModalVisible(false);
    } catch (err) {
      // The backend rejects a malformed number with the exact format it wants.
      Alert.alert("Top Up Failed", errorMessage(err, "Could not start that top up."));
    } finally {
      setIsProcessingTopUp(false);
      handleRefresh();
    }
  };

  const handleWithdraw = async () => {
    if (!MONEY_INPUT.test(withdrawAmount.trim()) || compareMoney(withdrawAmount, minWithdrawal) < 0) {
      Alert.alert(
        "Invalid Amount",
        `Please enter a valid amount of at least ${formatMoney(minWithdrawal)} to withdraw.`,
      );
      return;
    }
    if (!phoneNumber) {
      Alert.alert("Invalid Phone", "Please enter a valid M-Pesa phone number.");
      return;
    }

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      await withdrawMutation.mutateAsync({
        amount: withdrawAmount.trim(),
        phoneNumber: phoneNumber,
        userType: "vendor",
      });
      Alert.alert("Withdrawal Successful", "Funds have been disbursed to your M-Pesa number.");
      setWithdrawAmount("");
      setIsWithdrawModalVisible(false);
    } catch (err: unknown) {
      // "Insufficient wallet balance" vs. the float refusal are different
      // problems with different fixes, and the backend distinguishes them.
      Alert.alert("Withdrawal Failed", errorMessage(err, "That withdrawal didn't go through."));
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
          <TouchableOpacity onPress={() => router.back()} className="mr-4">
            <BackButtonMinimal />
          </TouchableOpacity>
          <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Digital Wallet</Text>
        </View>
      </View>

      <ScrollView 
        className="flex-1 px-6 pt-4"
        contentContainerStyle={{ paddingBottom: tabBarClearance }}
        refreshControl={<RefreshControl refreshing={isRefetching || isLoadingTx} onRefresh={handleRefresh} tintColor={BRAND.primary} />}
      >
        {/* Balance Card */}
        <View className="rounded-[24px] overflow-hidden mb-6" style={{ backgroundColor: BRAND.primary }}>
          <View className="px-6 pt-8 pb-10 items-center">
            <Text className="text-white/80 font-sans-medium text-base mb-2">Float Balance</Text>
            {isLoading ? (
              <Skeleton width={180} height={48} borderRadius={8} style={{ backgroundColor: "rgba(255,255,255,0.2)" }} />
            ) : (
              <Text className="text-white font-sans-bold text-5xl tracking-tight">{formatMoneyShort(balance)}</Text>
            )}

            {/* Balance minus what open cash orders have already claimed. The app
                used to show only the balance, so a refusal from the withdrawal
                endpoint read as the platform withholding money it had just
                displayed — the number and the rule disagreed on screen. */}
            {!isZeroMoney(committed) && (
              <View className="w-full mt-5 bg-white/10 rounded-2xl px-4 py-3">
                <View className="flex-row justify-between items-center mb-1">
                  <Text className="text-white/80 font-sans-medium">Committed to open cash orders</Text>
                  <Text className="text-white font-sans-bold">− {formatMoney(committed)}</Text>
                </View>
                <View className="h-px bg-white/20 my-2" />
                <View className="flex-row justify-between items-center">
                  <Text className="text-white font-sans-bold">Available to withdraw</Text>
                  <Text className="text-white font-sans-bold text-lg">{formatMoney(available)}</Text>
                </View>
                <Text className="text-white/70 text-xs mt-2 leading-relaxed">
                  Your rider collects the cash on these orders, and the platform&apos;s cut comes out of this balance when they&apos;re delivered.
                </Text>
              </View>
            )}

            {isInArrears ? (
              <View className="flex-row items-center mt-6 bg-red-500/25 px-4 py-2 rounded-full">
                <Ionicons name="alert-circle" size={16} color="white" />
                <Text className="text-white font-sans-medium ml-2">Top up to accept cash orders again</Text>
              </View>
            ) : (
              <View className="flex-row items-center mt-6 bg-white/10 px-4 py-2 rounded-full">
                <Ionicons name="shield-checkmark" size={16} color="white" />
                <Text className="text-white font-sans-medium ml-2">Zero-Fraud Protection Active</Text>
              </View>
            )}
          </View>
        </View>

        {/* Metrics Row */}
        <View className="flex-row justify-between mb-6">
          <View 
            className={`flex-1 p-5 rounded-3xl border mr-2 ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className={`w-10 h-10 rounded-full items-center justify-center mb-2 ${darkTheme ? "bg-slate-800" : "bg-green-50"}`}>
              <Ionicons name="stats-chart" size={20} color="#10b981" />
            </View>
            <Text className={`text-sm font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Lifetime Earned</Text>
            {isLoadingDashboard ? (
              <Skeleton width={80} height={24} borderRadius={4} style={{ marginTop: 4 }} />
            ) : (
              <Text className={`text-xl font-sans-bold mt-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>{formatMoneyShort(totalRevenue)}</Text>
            )}
          </View>

          <View 
            className={`flex-1 p-5 rounded-3xl border ml-2 ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className={`w-10 h-10 rounded-full items-center justify-center mb-2 ${darkTheme ? "bg-slate-800" : "bg-blue-50"}`}>
              <Ionicons name="card-outline" size={20} color={BRAND.primary} />
            </View>
            <Text className={`text-sm font-sans-medium ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Withdrawals</Text>
            <Text className={`text-xl font-sans-bold mt-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>{transactions.filter((t: any) => t.transaction_type === "withdrawal").length}</Text>
          </View>
        </View>

        {/* Gamified Free Cashout Section */}
        <View 
          className={`p-5 rounded-3xl border mb-6 ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
          style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
        >
          <View className="flex-row items-center justify-between mb-4">
            <View className="flex-row items-center">
              <View className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-slate-800" : "bg-orange-50"}`}>
                <Ionicons name="star" size={20} color="#f59e0b" />
              </View>
              <View className="ml-3">
                <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>Free Cashout Status</Text>
                <Text className={`text-xs ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                  {!isZeroMoney(withdrawalFee)
                    ? `Smaller withdrawals cost ${formatMoney(withdrawalFee)}`
                    : "Withdrawals are free"}
                </Text>
              </View>
            </View>
          </View>

          {/* Progress Bar */}
          <View className="mb-3">
            <View className="flex-row justify-between mb-2">
              <Text className={`text-sm font-sans-medium ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>Current: {formatMoney(balance)}</Text>
              <Text className={`text-sm font-sans-bold ${canReachFreeWithdrawal ? "text-green-500" : (darkTheme ? "text-slate-400" : "text-slate-500")}`}>
                Free at {formatMoney(freeCashoutThreshold)}
              </Text>
            </View>
            <View className={`h-3 w-full rounded-full overflow-hidden ${darkTheme ? "bg-slate-800" : "bg-gray-100"}`}>
              <View 
                className={`h-full rounded-full ${canReachFreeWithdrawal ? "bg-green-500" : "bg-amber-500"}`} 
                style={{ width: `${progress}%` }} 
              />
            </View>
          </View>

          {canReachFreeWithdrawal ? (
            <View className={`flex-row items-center p-3 rounded-xl mt-2 ${darkTheme ? "bg-green-500/10" : "bg-green-50"}`}>
              <Ionicons name="checkmark-circle" size={20} color="#10b981" />
              <Text className="text-green-600 font-sans-medium ml-2 flex-1">Zero Network Fee Applied! You can withdraw for free.</Text>
            </View>
          ) : (
            <Text className={`text-sm mt-1 leading-relaxed ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Earn {formatMoney(subtractMoney(freeCashoutThreshold, available))} more and you can take it out in one free withdrawal — the fee is waived on the amount you withdraw, not the balance you keep.
            </Text>
          )}
        </View>

        {/* Action Buttons */}
        <View className="flex-row justify-between mb-8">
          <PressableScale 
            onPress={() => {
              setPhoneNumber(vendor?.phone_number || "");
              setIsWithdrawModalVisible(true);
            }}
            className={`flex-1 mr-2 p-4 rounded-3xl items-center justify-center border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className={`w-12 h-12 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`}>
              <Ionicons name="arrow-down-outline" size={24} color={BRAND.primary} />
            </View>
            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Withdraw</Text>
          </PressableScale>

          <PressableScale 
            onPress={() => {
              setPhoneNumber(vendor?.phone_number || "");
              setIsTopUpModalVisible(true);
            }}
            className={`flex-1 ml-2 p-4 rounded-3xl items-center justify-center border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <View className={`w-12 h-12 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`}>
              <Ionicons name="wallet-outline" size={24} color={BRAND.primary} />
            </View>
            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Top Up</Text>
          </PressableScale>
        </View>

        {/* Info Section */}
        <View 
          className={`p-5 rounded-3xl border mb-8 ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
          style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
        >
          <View className="flex-row items-center mb-3">
            <Ionicons name="information-circle" size={22} color={BRAND.primary} />
            <Text className={`font-sans-bold text-base ml-2 ${darkTheme ? "text-white" : "text-slate-900"}`}>Workflow & Float Guide</Text>
          </View>
          <Text className={`leading-relaxed mb-3 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            <Text className="font-sans-bold">Wholesale Workflow:</Text> To accept Cash On Delivery wholesale orders, your float balance must cover the platform commission. Funds are automatically deducted when orders are marked as delivered.
          </Text>
          <Text className={`leading-relaxed ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            <Text className="font-sans-bold">Retail Refill Workflow:</Text> For retail refills, cash is collected directly by riders or digital payment is routed through the app. Maintain a healthy float to prevent missed dispatch opportunities!
          </Text>
        </View>

        {/* Transaction Ledger */}
        <Text className={`font-sans-bold text-lg mb-4 ${darkTheme ? "text-white" : "text-slate-900"}`}>Recent Transactions</Text>
        
        {isLoadingTx ? (
          <View className="space-y-4 mb-8">
            <Skeleton width="100%" height={70} borderRadius={16} />
            <Skeleton width="100%" height={70} borderRadius={16} />
            <Skeleton width="100%" height={70} borderRadius={16} />
          </View>
        ) : transactions.length === 0 ? (
          <View className={`items-center justify-center p-8 rounded-3xl mb-8 ${darkTheme ? "bg-surface-container" : "bg-slate-50"}`}>
            <Ionicons name="receipt-outline" size={48} color={darkTheme ? "#475569" : "#cbd5e1"} />
            <Text className={`mt-4 font-sans-bold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>No transactions yet</Text>
          </View>
        ) : (
          <View className="mb-10 space-y-3">
            {transactions.slice(0, 5).map((tx: any) => {
              const isDeduction = tx.transaction_type === "withdrawal" || tx.transaction_type === "commission_deduction";
              return (
                <View 
                  key={tx.id} 
                  className={`p-4 rounded-2xl flex-row items-center justify-between border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-slate-100"}`}
                >
                  <View className="flex-row items-center flex-1 pr-4">
                    <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${isDeduction ? "bg-red-100" : "bg-green-100"}`}>
                      <Ionicons 
                        name={isDeduction ? "arrow-up" : "arrow-down"} 
                        size={20} 
                        color={isDeduction ? "#ef4444" : "#22c55e"} 
                      />
                    </View>
                    <View>
                      <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                        {tx.transaction_type.replace(/_/g, " ").toUpperCase()}
                      </Text>
                      <Text className={`text-xs mt-1 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                        {format(new Date(tx.created_at), 'MMM dd, yyyy • hh:mm a')}
                      </Text>
                    </View>
                  </View>
                  <View className="items-end">
                    <Text className={`font-sans-bold ${isDeduction ? "text-red-500" : "text-green-500"}`}>
                      {isDeduction ? "-" : "+"}{formatMoney(tx.amount)}
                    </Text>
                    <View className={`px-2 py-0.5 mt-1 rounded text-[10px] ${tx.status === 'completed' ? 'bg-green-500/10' : tx.status === 'failed' ? 'bg-red-500/10' : 'bg-yellow-500/10'}`}>
                      <Text className={`text-[10px] uppercase font-sans-bold ${tx.status === 'completed' ? 'text-green-600' : tx.status === 'failed' ? 'text-red-600' : 'text-yellow-600'}`}>{tx.status}</Text>
                    </View>
                  </View>
                </View>
              );
            })}
            
            {transactions.length > 5 && (
              <PressableScale 
                onPress={() => router.push("/(screens)/Transactions" as any)}
                className={`w-full py-4 rounded-2xl items-center mt-2 border ${darkTheme ? "bg-slate-800 border-transparent" : "bg-white border-slate-200"}`}
              >
                <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>View All Transactions</Text>
              </PressableScale>
            )}
          </View>
        )}
      </ScrollView>

      {/* Top Up Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={isTopUpModalVisible}
        onRequestClose={() => setIsTopUpModalVisible(false)}
      >
        <View className="flex-1 justify-end bg-black/50">
          <View 
            className={`p-6 rounded-t-3xl ${darkTheme ? "bg-surface-container" : "bg-white"}`}
            style={{ paddingBottom: Math.max(insets.bottom, 24) }}
          >
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Top Up Wallet</Text>
              <PressableScale accessibilityLabel="Close the top-up form" onPress={() => setIsTopUpModalVisible(false)} className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-black/50" : "bg-slate-100"}`}>
                <Ionicons name="close" size={20} color={darkTheme ? "#fff" : "#0f172a"} />
              </PressableScale>
            </View>

            <Text className={`text-sm mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Enter amount to top up your float via M-Pesa STK Push.
            </Text>

            <View className="mb-4">
              <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>AMOUNT (KSH)</Text>
              <TextInput
                value={topUpAmount}
                onChangeText={setTopUpAmount}
                keyboardType="numeric"
                placeholder="e.g. 500"
                placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                className={`p-4 rounded-xl border font-sans-bold text-lg ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
              />
            </View>
            <View className="mb-6">
              <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>M-PESA NUMBER</Text>
              <TextInput
                value={phoneNumber}
                onChangeText={setPhoneNumber}
                keyboardType="phone-pad"
                placeholder="2547..."
                placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                className={`p-4 rounded-xl border font-sans-bold text-lg ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
              />
            </View>

            <PressableScale 
              onPress={handleTopUp}
              disabled={isProcessingTopUp}
              className="w-full h-[55px] justify-center items-center rounded-xl mb-4"
              style={{ backgroundColor: isProcessingTopUp ? BRAND.gray400 : BRAND.primary }}
            >
              {isProcessingTopUp ? (
                <Skeleton width={80} height={20} borderRadius={4} style={{ alignSelf: 'center' }} />
              ) : (
                <Text className="text-white font-sans-bold text-lg">Send STK Push</Text>
              )}
            </PressableScale>
          </View>
        </View>
      </Modal>

      {/* Withdraw Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={isWithdrawModalVisible}
        onRequestClose={() => setIsWithdrawModalVisible(false)}
      >
        <View className="flex-1 justify-end bg-black/50">
          <View 
            className={`p-6 rounded-t-3xl ${darkTheme ? "bg-surface-container" : "bg-white"}`}
            style={{ paddingBottom: Math.max(insets.bottom, 24) }}
          >
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Withdraw Funds</Text>
              <PressableScale accessibilityLabel="Close the withdrawal form" onPress={() => setIsWithdrawModalVisible(false)} className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-black/50" : "bg-slate-100"}`}>
                <Ionicons name="close" size={20} color={darkTheme ? "#fff" : "#0f172a"} />
              </PressableScale>
            </View>

            <Text className={`text-sm mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Withdraw your available balance straight to M-Pesa.
              {!isZeroMoney(minWithdrawal) ? ` Minimum ${formatMoney(minWithdrawal)}.` : ""}
            </Text>

            <View className="mb-4">
              <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>AMOUNT (KSH)</Text>
              <TextInput
                value={withdrawAmount}
                onChangeText={setWithdrawAmount}
                keyboardType="numeric"
                placeholder="e.g. 500"
                placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                className={`p-4 rounded-xl border font-sans-bold text-lg ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
              />
            </View>
            <View className="mb-6">
              <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>M-PESA NUMBER</Text>
              <TextInput
                value={phoneNumber}
                onChangeText={setPhoneNumber}
                keyboardType="phone-pad"
                placeholder="2547..."
                placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                className={`p-4 rounded-xl border font-sans-bold text-lg ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
              />
            </View>

            <PressableScale 
              onPress={handleWithdraw}
              disabled={withdrawMutation.isPending}
              className="w-full h-[55px] justify-center items-center rounded-xl mb-4"
              style={{ backgroundColor: withdrawMutation.isPending ? BRAND.gray400 : BRAND.primary }}
            >
              {withdrawMutation.isPending ? (
                <Skeleton width={80} height={20} borderRadius={4} style={{ alignSelf: 'center' }} />
              ) : (
                <Text className="text-white font-sans-bold text-lg">Withdraw to M-Pesa</Text>
              )}
            </PressableScale>
          </View>
        </View>
      </Modal>

    </SafeAreaView>
  );
}
