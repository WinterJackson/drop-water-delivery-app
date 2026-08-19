import React, { useContext, useState } from "react";
import { View, ScrollView, RefreshControl, Alert, TouchableOpacity, Modal } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND, TOAST } from "@/constants/brandColors";
import PressableScale from "@/components/ui/PressableScale";
import { Skeleton } from "@/components/ui/Skeleton";
import { format } from "date-fns";
import { errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import * as Haptics from "expo-haptics";
import { useRiderProfile, useRiderEarnings } from "@/hooks/queries/useRiderData";
import { useWalletTransactions, useWalletWithdraw } from "@/hooks/queries/useWallet";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { useWalletSummary } from "@/hooks/queries/useWallet";
import { compareMoney, formatMoney, formatMoneyShort, isZeroMoney, moneyRatio, subtractMoney } from "@/utils/money";

export default function Cashout() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { post } = useApiRequest();
  
  const { data: rider, isLoading, refetch: refetchProfile, isRefetching } = useRiderProfile();
  const { data: earnings, isLoading: isLoadingEarnings, refetch: refetchEarnings } = useRiderEarnings();
  const { data: transactions, isLoading: isLoadingTx, refetch: refetchTx } = useWalletTransactions();
  const withdrawMutation = useWalletWithdraw();

  const [topUpAmount, setTopUpAmount] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [isProcessingTopUp, setIsProcessingTopUp] = useState(false);
  const [isTopUpModalVisible, setIsTopUpModalVisible] = useState(false);
  
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [isWithdrawModalVisible, setIsWithdrawModalVisible] = useState(false);

  const { data: walletSummary, refetch: refetchSummary } = useWalletSummary();
  const balance = walletSummary?.wallet_balance ?? rider?.wallet_balance ?? "0";
  // Float committed to cash orders still being carried settles the vendor and
  // platform cuts on delivery, so it is not withdrawable.
  const committedFloat = walletSummary?.committed_cash_float ?? "0";
  const availableToWithdraw = walletSummary?.available_for_withdrawal ?? balance;

  // The three figures the withdrawal will actually be judged by, from
  // `Platform_Settings` via `settlement_service.withdrawal_terms` — the same
  // function the withdrawal itself calls. They were literals here (500, 15,
  // 1000), so editing any of them on the console changed what a rider was
  // charged and not what they were told.
  // No numeric fallbacks: a literal here is a figure the console cannot change.
  // `"0"` for the fee and the waiver reads as "no fee, no waiver", which is the
  // safe direction; the minimum falls back to zero so a rider is never blocked
  // by a threshold this screen invented.
  const minWithdrawal = walletSummary?.withdrawal?.minimum ?? "0";
  const withdrawalFee = walletSummary?.withdrawal?.fee ?? "0";
  const freeCashoutThreshold = walletSummary?.withdrawal?.fee_waiver_threshold ?? "0";

  // The waiver is keyed on the **amount withdrawn**, not the balance held.
  // This screen said "keep KSH X more in your float balance to unlock zero-fee
  // withdrawals" and drew a progress bar of `balance / threshold`, which told
  // riders to hoard money for a discount that does not work that way: someone
  // sitting on KSH 1,200 who withdraws KSH 600 was shown "zero fee applied" and
  // charged anyway. Waiving on balance would also be the opposite of the
  // waiver's purpose — the platform pays one M-Pesa tariff per disbursement, so
  // it wants fewer, larger ones.
  // The typed amount is already a decimal string; it is never parsed.
  const amountEntered = withdrawAmount.trim() === "" ? "0" : withdrawAmount;
  const feeOnThisAmount =
    !isZeroMoney(freeCashoutThreshold) && compareMoney(amountEntered, freeCashoutThreshold) >= 0
      ? "0"
      : withdrawalFee;
  const progress = !isZeroMoney(freeCashoutThreshold)
    ? Math.min(moneyRatio(availableToWithdraw, freeCashoutThreshold) * 100, 100)
    : 100;
  const canReachFreeWithdrawal =
    !isZeroMoney(freeCashoutThreshold) &&
    compareMoney(availableToWithdraw, freeCashoutThreshold) >= 0;

  const handleRefresh = async () => {
    refetchProfile();
    refetchEarnings();
    refetchTx();
    refetchSummary();
  };

  const handleTopUp = async () => {
    // The floor is `min_wallet_topup`, a settings row. It was `< 10` here with
    // "at least KSH 10" beside it — right today, wrong the moment an
    // administrator moves the row, and refusing client-side so no server log
    // would ever show it happening.
    const minTopUp = walletSummary?.topup?.minimum ?? null;
    if (!topUpAmount || isNaN(Number(topUpAmount))) {
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
      const data = await post<{ error?: string }>(RiderApiRoutes.WalletTopUp.path, {
        amount: Number(topUpAmount),
        phone_number: phoneNumber,
        user_type: "rider",
      });

      // Daraja can answer 200 with a failure in the body, so a 2xx is not on its
      // own a success here.
      if (data?.error) {
        Alert.alert("Top Up Failed", data.error);
        return;
      }
      Alert.alert("STK Push Sent", "Please check your phone and enter your M-Pesa PIN to complete the top up.");
      setTopUpAmount("");
      setIsTopUpModalVisible(false);
    } catch (err) {
      if (__DEV__) console.error(err);
      Alert.alert("Top Up Failed", errorMessage(err, "Could not process top up at this time."));
    } finally {
      setIsProcessingTopUp(false);
      handleRefresh();
    }
  };

  const handleWithdraw = async () => {
    if (!withdrawAmount || isNaN(Number(withdrawAmount)) || compareMoney(withdrawAmount, minWithdrawal) < 0) {
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
        amount: Number(withdrawAmount),
        phoneNumber: phoneNumber,
        userType: "rider",
      });
      Alert.alert("Withdrawal requested", "You'll get an M-Pesa confirmation shortly.");
      setWithdrawAmount("");
      setIsWithdrawModalVisible(false);
    } catch (err: unknown) {
      // `errorMessage`, not `err.message`: the server's refusal is the useful
      // sentence here — "below the minimum", "that number is not registered for
      // M-Pesa" — and a raw `.message` on a rejected request is the transport's
      // words, or `undefined` when what was thrown is not an Error at all.
      Alert.alert("Withdrawal Failed", errorMessage(err, "An error occurred during withdrawal."));
    }
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
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
          <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Digital Wallet</Text>
        </View>
      </View>

      <ScrollView 
        className="flex-1 px-6 pt-4"
        contentContainerStyle={{ paddingBottom: 120 }}
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

            {!isZeroMoney(committedFloat) && (
              <View className="w-full mt-4 bg-white/10 rounded-2xl px-4 py-3">
                <View className="flex-row justify-between mb-1">
                  <Text className="text-white/80 text-sm">Held for cash orders</Text>
                  <Text className="text-white font-sans-semibold text-sm">
                    {formatMoney(committedFloat)}
                  </Text>
                </View>
                <View className="flex-row justify-between">
                  <Text className="text-white/80 text-sm">Available to withdraw</Text>
                  <Text className="text-white font-sans-bold text-sm">
                    {formatMoney(availableToWithdraw)}
                  </Text>
                </View>
                <Text className="text-white/60 text-xs mt-2">
                  Released as you deliver the cash orders you're carrying.
                </Text>
              </View>
            )}

            {walletSummary?.is_in_arrears && (
              <View className="w-full mt-4 bg-red-500/25 rounded-2xl px-4 py-3">
                <Text className="text-white font-sans-bold text-sm mb-1">Balance overdrawn</Text>
                <Text className="text-white/80 text-xs">
                  Top up to clear this before you can accept further cash orders.
                </Text>
              </View>
            )}
            
            <View className="flex-row items-center mt-6 bg-white/10 px-4 py-2 rounded-full">
              <Ionicons name="shield-checkmark" size={16} color="white" />
              <Text className="text-white font-sans-medium ml-2">Zero-Fraud Protection Active</Text>
            </View>
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
            {isLoadingEarnings ? (
              <Skeleton width={80} height={24} borderRadius={4} style={{ marginTop: 4 }} />
            ) : (
              <Text className={`text-xl font-sans-bold mt-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>{formatMoneyShort(earnings?.total_earnings)}</Text>
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
            <Text className={`text-xl font-sans-bold mt-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>{transactions?.filter((t: any) => t.transaction_type === "withdrawal").length || 0}</Text>
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
              {/* Available, not balance: what is committed as float to cash
                  orders you are still carrying cannot be withdrawn at any
                  size, so measuring the goal against the raw balance promised
                  a free withdrawal the rider could not actually make. */}
              <Text className={`text-sm font-sans-medium ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>Available: {formatMoney(availableToWithdraw)}</Text>
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
              {/* The condition is the *amount*, so say so. "You can withdraw
                  for free" was untrue for any smaller withdrawal. */}
              <Text className="text-green-600 font-sans-medium ml-2 flex-1">
                Withdraw {formatMoney(freeCashoutThreshold)} or more in one go and the {formatMoney(withdrawalFee)} fee is waived.
              </Text>
            </View>
          ) : (
            <Text className={`text-sm mt-1 leading-relaxed ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Earn {formatMoney(subtractMoney(freeCashoutThreshold, availableToWithdraw))} more and you can take it out in one free withdrawal — the fee is waived on the amount you withdraw, not the balance you keep.
            </Text>
          )}
        </View>

        {/* Action Buttons */}
        <View className="flex-row justify-between mb-8">
          <PressableScale 
            onPress={() => {
              setPhoneNumber(rider?.payment_methods?.find((pm: any) => pm.isDefault)?.phone || rider?.phone_number || "");
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
              setPhoneNumber(rider?.payment_methods?.find((pm: any) => pm.isDefault)?.phone || rider?.phone_number || "");
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
            <Text className="font-sans-bold">Wholesale Workflow:</Text> If accepting Cash On Delivery wholesale orders, your float balance must cover the commission. Funds are automatically deducted when orders are marked as delivered.
          </Text>
          <Text className={`leading-relaxed ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            <Text className="font-sans-bold">Retail Refill Workflow:</Text> For retail refills, cash is collected directly. Keep your float topped up to prevent missed dispatch opportunities!
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
        ) : !transactions || transactions.length === 0 ? (
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
          <View className={`p-6 rounded-t-3xl ${darkTheme ? "bg-surface-container" : "bg-white"}`}>
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
            <SafeAreaView edges={["bottom"]} />
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
          <View className={`p-6 rounded-t-3xl ${darkTheme ? "bg-surface-container" : "bg-white"}`}>
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Withdraw Funds</Text>
              <PressableScale accessibilityLabel="Close the withdrawal form" onPress={() => setIsWithdrawModalVisible(false)} className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-black/50" : "bg-slate-100"}`}>
                <Ionicons name="close" size={20} color={darkTheme ? "#fff" : "#0f172a"} />
              </PressableScale>
            </View>

            <Text className={`text-sm mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Withdraw to your M-Pesa. Minimum {formatMoney(minWithdrawal)}, and
              {formatMoney(availableToWithdraw)} is available right now.
            </Text>

            <View className="mb-4">
              <Text className={`text-xs font-sans-bold mb-2 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>AMOUNT (KSH)</Text>
              <TextInput
                value={withdrawAmount}
                onChangeText={setWithdrawAmount}
                keyboardType="numeric"
                placeholder={`e.g. ${minWithdrawal}`}
                placeholderTextColor={darkTheme ? "#64748b" : "#94a3b8"}
                className={`p-4 rounded-xl border font-sans-bold text-lg ${darkTheme ? "bg-black/30 border-transparent text-white" : "bg-slate-50 border-slate-200 text-slate-900"}`}
              />
              {/* What this particular withdrawal costs, at the moment the rider
                  is choosing the number. The fee turns on the amount, so this is
                  the only place it can be answered honestly. */}
              {compareMoney(amountEntered, minWithdrawal) >= 0 && !isZeroMoney(withdrawalFee) ? (
                <Text
                  className={`text-xs mt-2 ${isZeroMoney(feeOnThisAmount) ? "text-green-500" : darkTheme ? "text-slate-400" : "text-slate-500"}`}
                >
                  {isZeroMoney(feeOnThisAmount)
                    ? `No fee at this amount — you'll receive ${formatMoney(amountEntered)}.`
                    : `Fee ${formatMoney(feeOnThisAmount)} — you'll receive ${formatMoney(subtractMoney(amountEntered, feeOnThisAmount))}.` +
                      (compareMoney(freeCashoutThreshold, amountEntered) > 0
                        ? ` Withdraw ${formatMoney(freeCashoutThreshold)} or more and there's no fee.`
                        : "")}
                </Text>
              ) : null}
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
            <SafeAreaView edges={["bottom"]} />
          </View>
        </View>
      </Modal>

    </SafeAreaView>
  );
}
