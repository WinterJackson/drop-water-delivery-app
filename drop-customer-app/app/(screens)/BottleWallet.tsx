import React, { useContext, useState, useEffect, useCallback } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, RefreshControl, Modal, StatusBar } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import { PressableScale } from "@/components/ui/PressableScale";
import { Skeleton } from "@/components/ui/Skeleton";
import { format } from "date-fns";
import { useAuth } from "@clerk/clerk-expo";
import * as Haptics from "expo-haptics";
import { useWalletTransactions, useWalletWithdraw, useWalletTopUp } from "@/hooks/queries/useWallet";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useBottleDeposit } from "@/hooks/queries/useBottleDeposit";
import { BottleCollectionCard } from "@/components/common/BottleCollection";
import { Toast } from "@/lib/toast";
import { errorMessage } from "@/API/errors";
import { compareMoney, formatMoney, formatMoneyShort, isZeroMoney, subtractMoney } from "@/utils/money";

/** What a customer may type into an amount box: shillings, optionally cents. */
const MONEY_INPUT = /^\d+(\.\d{1,2})?$/;

interface WalletData {
  bottle_purchased_at: string | null;
  bottle_refill_count: number;
  /** Decimal strings, exactly as the profile serves them. */
  wallet_balance: string;
  phone_number: string;
  /** Bottles this customer is holding, and the deposit held against them. */
  bottles_held: number;
  bottle_deposit_balance: string;
  /** Carried from an earlier order; charged on the next one, not payable here. */
  debt_balance: string;
}

export default function BottleWallet() {
    const tabBarClearance = useTabBarClearance();
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  // Wallet figures come from the shared user query rather than a bespoke fetch,
  // so a top-up or an order that spends credit updates this screen automatically.
  const { data: user, isLoading: loading, refetch: refetchUser } = useUserDetails();
  // The deposit position *and* what can be done about it. `useUserDetails`
  // carries the two figures; this carries the collection state and the part of
  // the balance that cannot be withdrawn, neither of which lives on the profile.
  const { data: deposit, refetch: refetchDeposit } = useBottleDeposit();
  // The terms, from the server, or `null` until the summary lands.
  //
  // `null` deliberately skips the client-side check rather than falling back to
  // a number: a guessed minimum is what this screen used to have. With the
  // terms unknown the request simply goes, and the server's own sentence comes
  // back through `errorMessage(err)` — which is the platform's rule for every
  // other refusal it does not have the facts to pre-empt.
  const minWithdrawal = deposit?.withdrawal?.minimum ?? null;
  const minTopUp = deposit?.topup?.minimum ?? null;

  /**
   * The two halves of the balance, both from the server.
   *
   * `wallet_balance` is everything the customer can spend on water.
   * `wallet_not_withdrawable` is the part of it that came back from a returned
   * bottle deposit, which buys water and cannot leave as cash — the server's
   * `restricted_customer_credit`, and the reason `assert_withdrawable` refuses.
   *
   * The card said "Available Balance" over the whole figure, which is the same
   * misnaming as calling this wallet "cashback": it states that all of it is
   * available when some of it provably is not, and the customer only finds out
   * at the refusal. Subtraction is `subtractMoney`, never `Number(a) - Number(b)`.
   */
  const restricted = deposit?.wallet_not_withdrawable ?? null;
  const hasRestricted = restricted !== null && !isZeroMoney(restricted);
  const withdrawable =
    restricted !== null && user?.wallet_balance
      ? subtractMoney(user.wallet_balance, restricted)
      : null;

  const wallet: WalletData | null = user
    ? {
        bottle_purchased_at: user.bottle_purchased_at ?? null,
        bottle_refill_count: user.bottle_refill_count ?? 0,
        wallet_balance: user.wallet_balance ?? "0",
        phone_number: user.phone_number ?? "",
        bottles_held: user.bottles_held ?? 0,
        bottle_deposit_balance: user.bottle_deposit_balance ?? "0",
        debt_balance: user.debt_balance ?? "0",
      }
    : null;
  const [refreshing, setRefreshing] = useState(false);

  const { data: transactions, isLoading: isLoadingTx, refetch: refetchTx } = useWalletTransactions();
  const withdrawMutation = useWalletWithdraw();
  const topUpMutation = useWalletTopUp();

  const [topUpAmount, setTopUpAmount] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [isProcessingTopUp, setIsProcessingTopUp] = useState(false);
  const [isTopUpModalVisible, setIsTopUpModalVisible] = useState(false);
  
  const [withdrawAmount, setWithdrawAmount] = useState("");
  const [isWithdrawModalVisible, setIsWithdrawModalVisible] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([refetchUser(), refetchTx(), refetchDeposit()]);
    setRefreshing(false);
  }, [refetchUser, refetchTx, refetchDeposit]);

  /**
   * Phone must reach the backend as 2547XXXXXXXX / 2541XXXXXXXX; accept the
   * common local formats and normalise rather than rejecting them.
   */
  const toMsisdn = (raw: string | null | undefined): string | null => {
    if (!raw) return null;
    let digits = raw.replace(/[^0-9]/g, "");
    if (digits.startsWith("254")) digits = digits.slice(3);
    else if (digits.startsWith("0")) digits = digits.slice(1);
    const full = `254${digits}`;
    return /^254[17]\d{8}$/.test(full) ? full : null;
  };

  const handleTopUp = async () => {
    // The typed text stays text. `Number(...)` here was the last place on this
    // screen money became a float, and it fed both the comparison and the wire.
    const amount = topUpAmount.trim();
    if (!MONEY_INPUT.test(amount)) {
      Toast.error("Invalid amount", "Enter the amount you want to top up.");
      return;
    }
    if (minTopUp !== null && compareMoney(amount, minTopUp) < 0) {
      Toast.error("Invalid amount", `Enter at least ${formatMoney(minTopUp)} to top up.`);
      return;
    }
    const msisdn = toMsisdn(phoneNumber);
    if (!msisdn) {
      Toast.error("Invalid phone", "Enter a valid Safaricom number, e.g. 0712345678.");
      return;
    }

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      setIsProcessingTopUp(true);
      await topUpMutation.mutateAsync({ amount, phoneNumber: msisdn });
      Toast.success("STK push sent", "Check your phone and enter your M-Pesa PIN to complete the top up.");
      setTopUpAmount("");
      setIsTopUpModalVisible(false);
    } catch (err) {
      Toast.error("Top up failed", errorMessage(err, "Could not process the top up right now."));
    } finally {
      setIsProcessingTopUp(false);
      handleRefresh();
    }
  };

  const handleWithdraw = async () => {
    const amount = withdrawAmount.trim();
    if (!MONEY_INPUT.test(amount)) {
      Toast.error("Invalid amount", "Enter the amount you want to withdraw.");
      return;
    }
    if (minWithdrawal !== null && compareMoney(amount, minWithdrawal) < 0) {
      Toast.error("Invalid amount", `Enter at least ${formatMoney(minWithdrawal)} to withdraw.`);
      return;
    }
    const msisdn = toMsisdn(phoneNumber);
    if (!msisdn) {
      Toast.error("Invalid phone", "Enter a valid Safaricom number, e.g. 0712345678.");
      return;
    }

    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      await withdrawMutation.mutateAsync({ amount, phoneNumber: msisdn });
      // Safaricom has only queued the disbursement at this point; the B2C result
      // callback settles it. Say "on its way", not "successful".
      Toast.success("Withdrawal started", "Your funds are on their way to your M-Pesa number.");
      setWithdrawAmount("");
      setIsWithdrawModalVisible(false);
      handleRefresh();
    } catch (err) {
      Toast.error("Withdrawal failed", errorMessage(err, "Could not process the withdrawal right now."));
    }
  };

  const daysSincePurchase = wallet?.bottle_purchased_at
    ? Math.floor((Date.now() - new Date(wallet.bottle_purchased_at).getTime()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
      
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
          <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Digital Wallet & Bottles</Text>
        </View>
      </View>

      <ScrollView 
        className="flex-1 px-6 pt-4"
        contentContainerStyle={{ paddingBottom: tabBarClearance }}
        refreshControl={<RefreshControl refreshing={refreshing || isLoadingTx} onRefresh={handleRefresh} tintColor={BRAND.primary} />}
      >
        {/* Wallet Balance Card.
            The headline is what the customer can spend, named as such. It used
            to be labelled "Available Balance", which is only true when none of
            it is returned deposit — and for a customer who has handed bottles
            back, most of it is. When part is restricted the card splits the
            figure rather than making the customer discover it at the
            withdrawal form. */}
        <View className="rounded-[24px] overflow-hidden mb-6" style={{ backgroundColor: BRAND.primary }}>
          <View className="px-6 pt-8 pb-8 items-center">
            <Text className="text-white/80 font-sans-medium text-base mb-2">Drop Wallet balance</Text>
            {loading ? (
              <Skeleton width={180} height={48} borderRadius={8} style={{ backgroundColor: "rgba(255,255,255,0.2)" }} />
            ) : (
              <Text className="text-white font-sans-bold text-5xl tracking-tight">{formatMoneyShort(wallet?.wallet_balance)}</Text>
            )}
            <Text className="text-white/70 font-sans-medium text-xs mt-2">Spend it on any order</Text>

            {hasRestricted && withdrawable !== null ? (
              <View className="flex-row w-full mt-6 bg-white/10 rounded-2xl px-4 py-3">
                <View className="flex-1 pr-3">
                  <Text className="text-white/70 text-xs">Can go to M-Pesa</Text>
                  <Text className="text-white font-sans-bold text-lg mt-0.5">
                    {formatMoneyShort(withdrawable)}
                  </Text>
                </View>
                <View className="w-px self-stretch bg-white/20" />
                <View className="flex-1 pl-3">
                  <Text className="text-white/70 text-xs">Water only</Text>
                  <Text className="text-white font-sans-bold text-lg mt-0.5">
                    {formatMoneyShort(restricted)}
                  </Text>
                </View>
              </View>
            ) : (
              <View className="flex-row items-center mt-6 bg-white/10 px-4 py-2 rounded-full">
                <Ionicons name="shield-checkmark" size={16} color="white" />
                <Text className="text-white font-sans-medium ml-2">Zero-Fraud Protection Active</Text>
              </View>
            )}
          </View>
        </View>

        {/* Action Buttons */}
        <View className="flex-row justify-between mb-8">
          <PressableScale 
            onPress={() => {
              setPhoneNumber(wallet?.phone_number || "");
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
              setPhoneNumber(wallet?.phone_number || "");
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
            <Text className="font-sans-bold">Seamless payments:</Text> top up your wallet to pay for refills without entering your M-Pesa PIN on every order.
          </Text>
          {/* This used to promise "loyalty bonuses". The setting behind that
              — `loyalty_cashback_per_delivery` — was retired to 0 by
              `b2f9c14e7a35` and is credited only `if cashback > 0`, so no order
              has earned any. The four things listed here are the four things
              that actually credit this balance. */}
          <Text className={`leading-relaxed ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            <Text className="font-sans-bold">Where the money comes from:</Text> your own top-ups, refunds on cancelled orders, and deposits returned when you hand bottles back.
          </Text>
        </View>

        {/* Bottle Tracking Section */}
        <Text className={`font-sans-bold text-lg mb-4 mt-2 ${darkTheme ? "text-white" : "text-slate-900"}`}>My Bottles & Loyalty</Text>

        {/* The actual bottle position.
            This screen is called "Bottle Wallet" and showed a cash balance,
            "days since your first bottle" and "plastic waste saved" — never the
            two facts that matter: how many bottles you are holding, and how much
            of your money the platform is holding against them. The deposit is a
            liability the platform returns (`customer_bottle_service`), so it is
            the customer's money and was invisible to the only person with a
            claim on it. */}
        <View
          className={`p-5 rounded-3xl border mb-4 ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
          style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
        >
          <View className="flex-row items-center justify-between">
            <View className="flex-1 pr-4">
              <Text className={`text-xs ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                Bottles you&apos;re holding
              </Text>
              <Text className={`text-3xl font-sans-extrabold mt-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                {wallet?.bottles_held ?? 0}
              </Text>
            </View>
            <View className={`w-px self-stretch ${darkTheme ? "bg-slate-800" : "bg-slate-100"}`} />
            <View className="flex-1 pl-4">
              <Text className={`text-xs ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                Refundable deposit
              </Text>
              <Text className="text-3xl font-sans-extrabold mt-1" style={{ color: BRAND.primary }}>
                {formatMoneyShort(wallet?.bottle_deposit_balance)}
              </Text>
            </View>
          </View>
          <Text className={`text-xs mt-3 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
            {(wallet?.bottles_held ?? 0) > 0
              ? "Book a collection below and the deposit comes back to your wallet."
              : "Deposits appear here when you keep a bottle instead of swapping it."}
          </Text>
        </View>

        {/* The promise above used to have nothing behind it: the only way a
            deposit came back was an administrator opening the console under a
            permission no preset but super admin holds. */}
        {deposit ? (
          <BottleCollectionCard
            bottlesHeld={deposit.bottles_held}
            bottleLimit={deposit.bottle_limit}
            notWithdrawable={deposit.wallet_not_withdrawable}
            openRequest={deposit.open_request}
          />
        ) : null}

        {/* Money owed, stated rather than discovered as a bigger total later. */}
        {!isZeroMoney(wallet?.debt_balance) && (
          <View className={`p-5 rounded-3xl border mb-4 ${darkTheme ? "bg-amber-500/10 border-amber-500/30" : "bg-amber-50 border-amber-200"}`}>
            <View className="flex-row items-center justify-between">
              <View className="flex-1 pr-3">
                <Text className={`font-sans-bold ${darkTheme ? "text-amber-400" : "text-amber-800"}`}>
                  Previous balance owed
                </Text>
                <Text className={`text-xs mt-1 ${darkTheme ? "text-amber-400/80" : "text-amber-700/80"}`}>
                  Added to your next order and cleared by it — nothing to pay separately.
                </Text>
              </View>
              <Text className={`text-2xl font-sans-extrabold ${darkTheme ? "text-amber-400" : "text-amber-800"}`}>
                {formatMoney(wallet?.debt_balance)}
              </Text>
            </View>
          </View>
        )}

        <View className="flex-row gap-3 mb-8">
          <View 
            className={`flex-1 p-5 rounded-3xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <Text style={{ fontSize: 28 }}>📅</Text>
            <Text className={`text-xl font-sans-extrabold mt-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>
              {daysSincePurchase !== null ? `${daysSincePurchase} Days` : "No bottle"}
            </Text>
            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
              Since your first bottle
            </Text>
          </View>
          <View 
            className={`flex-1 p-5 rounded-3xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
            style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
          >
            <Text style={{ fontSize: 28 }}>🌱</Text>
            <Text className={`text-xl font-sans-extrabold mt-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>
              {wallet?.bottle_refill_count ? (wallet.bottle_refill_count * 0.5).toFixed(1) : 0} kg
            </Text>
            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
              Plastic Waste Saved
            </Text>
          </View>
        </View>

        {/* Transaction Ledger */}
        <Text className={`font-sans-bold text-lg mb-4 ${darkTheme ? "text-white" : "text-slate-900"}`}>Recent Transactions</Text>
        
        {isLoadingTx || loading ? (
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
              // Direction comes from the signed amount. The old check compared
              // against "payment", which is not a value the backend emits — the
              // enum is `order_payment` — so wallet spends rendered as credits.
              const txAmount = tx.amount ?? "0";
              const isDeduction = txAmount < 0;
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
                    {/* The row led with the raw enum, uppercased: a returned
                        bottle deposit, a refund on a cancelled order and a
                        loyalty credit are all `refund`, so all three read
                        "REFUND" and the one question this ledger exists to
                        answer — where did this money come from — had the same
                        answer for three different events. The server already
                        writes a sentence per movement; `Transactions` shows it
                        and this preview did not. */}
                    <View className="flex-1">
                      <Text
                        numberOfLines={1}
                        className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}
                      >
                        {tx.description || tx.transaction_type.replace(/_/g, " ")}
                      </Text>
                      <Text className={`text-xs mt-1 ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                        {format(new Date(tx.created_at), 'MMM dd, yyyy • hh:mm a')}
                      </Text>
                    </View>
                  </View>
                  <View className="items-end">
                    <Text className={`font-sans-bold ${isDeduction ? "text-red-500" : "text-green-500"}`}>
                      {isDeduction ? "-" : "+"}{formatMoney(String(txAmount).replace("-", ""))}
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
                onPress={() => router.push("/(screens)/Transactions")}
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
              Top up your wallet with an M-Pesa STK push.
              {minTopUp !== null ? ` Minimum ${formatMoney(minTopUp)}.` : ""}
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
              style={{ backgroundColor: isProcessingTopUp ? BRAND.gray500 : BRAND.primary }}
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

            {/* What is actually withdrawable, stated before the customer types.
                Only ever *stated* — never enforced here. The server's
                `assert_withdrawable` reads the balance at request time and
                refuses with its own sentence; a copy of a figure fetched
                minutes ago that refused something the platform would have paid
                is precisely the `MIN_WITHDRAWAL_KSH = 500` defect this screen
                already had removed. */}
            <Text className={`text-sm mb-4 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              {hasRestricted && withdrawable !== null
                ? `You can send ${formatMoney(withdrawable)} to M-Pesa. The other ${formatMoney(restricted)} is returned bottle deposit — spendable on any order, but not withdrawable as cash.`
                : "Withdraw your wallet balance straight to M-Pesa."}
              {minWithdrawal !== null ? ` Minimum ${formatMoney(minWithdrawal)}.` : ""}
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
              style={{ backgroundColor: withdrawMutation.isPending ? BRAND.gray500 : BRAND.primary }}
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
