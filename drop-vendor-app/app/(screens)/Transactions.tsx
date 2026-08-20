import React, { useCallback, useContext, useState, memo } from "react";
import {
    RefreshControl,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { FlashList } from "@shopify/flash-list";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";
import { format } from "date-fns";

import { Skeleton } from "@/components/ui/Skeleton";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { useDebounce } from "@/hooks/useDebounce";
import SearchBar from "@/components/common/Search";
import { ScrollView } from "react-native-gesture-handler";
import { EmptyState } from "@/components/ui/EmptyState";
import { useWalletTransactionsPaginated, type WalletTransaction } from "@/hooks/queries/useWallet";
import { flattenPages, keepPaging } from "@/utils/paging";
import { absMoney, formatMoney, isNegativeMoney } from "@/utils/money";

const TRANSACTION_COLORS: Record<string, string> = {
  top_up: "bg-blue-500/20 text-blue-600",
  withdrawal: "bg-orange-500/20 text-orange-600",
  order_payment: "bg-green-500/20 text-green-600",
  commission_deduction: "bg-red-500/20 text-red-600",
  refund: "bg-purple-500/20 text-purple-600",
};

const TRANSACTION_ICONS: Record<string, string> = {
  top_up: "arrow-down-circle",
  withdrawal: "arrow-up-circle",
  order_payment: "cash",
  commission_deduction: "swap-horizontal",
  refund: "refresh-circle",
};

const TransactionItem = memo(({ item, darkTheme }: any) => {
  // The sign comes from the ledger amount, never from the transaction type.
  //
  // `apply_wallet_delta` documents it: "amount is signed: negative debits. The
  // stored ledger amount keeps that sign." A customer paying from their wallet
  // is written as `amount=-quote.wallet_discount`, and on the rider side the
  // *same* `order_payment` type carries a negative (`-cash_float_required`) and
  // a positive (`vendor_net`), so the type cannot decide the sign even in
  // principle.
  //
  // Deriving it from the type put `order_payment` in the positive list and then
  // rendered the raw amount, so a wallet-paid order showed "+-KSH 450.00" and a
  // withdrawal "--KSH 200.00". The rider app already reads the amount; these two
  // did not.
  const negative = isNegativeMoney(item.amount);
  const isPositive = !negative;
  const colorClass = TRANSACTION_COLORS[item.transaction_type] || "bg-slate-500/20 text-slate-600";
  const [bgColor, textColor] = colorClass.split(" ");
  const iconName = TRANSACTION_ICONS[item.transaction_type] || "list";

  return (
    <View 
      className={`p-5 mb-3 rounded-3xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
      style={darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
    >
      <View className="flex-row justify-between items-center mb-3">
        <View className="flex-row items-center flex-1 pr-4">
          <View className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${bgColor}`}>
            <Ionicons name={iconName as any} size={20} color={textColor.replace("text-", "").replace("-600", "Color")} style={darkTheme ? { opacity: 0.8 } : {}} />
          </View>
          <View>
            <Text className={`font-sans-bold text-base capitalize ${darkTheme ? "text-white" : "text-slate-900"}`}>
              {item.transaction_type.replace(/_/g, " ")}
            </Text>
            <Text className={`text-xs ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              {format(new Date(item.created_at), "MMM d, yyyy · h:mm a")}
            </Text>
          </View>
        </View>
        <Text className={`font-sans-bold text-lg ${isPositive ? "text-green-500" : (darkTheme ? "text-white" : "text-slate-900")}`}>
          {negative ? "-" : "+"}{formatMoney(absMoney(item.amount))}
        </Text>
      </View>
      
      {/* A failure the vendor can act on. Rendered outside the details block
          below, which only appears when there is a description or a reference —
          a withdrawal that failed before M-Pesa ever issued one has neither, so
          the reason would have been hidden in exactly the case it matters. */}
      {item.status === "failed" && item.failure_reason ? (
        <View className={`p-3 rounded-xl mt-1 border ${darkTheme ? "bg-red-500/10 border-red-500/20" : "bg-red-50 border-red-200"}`}>
          <Text className={`text-xs font-sans-bold mb-0.5 ${darkTheme ? "text-red-400" : "text-red-700"}`}>
            Why this failed
          </Text>
          <Text className={`text-xs ${darkTheme ? "text-red-300/80" : "text-red-700/80"}`}>
            {item.failure_reason}
          </Text>
        </View>
      ) : null}

      {(item.description || item.reference_id || item.mpesa_receipt_number) && (
        <View className={`p-3 rounded-xl ${darkTheme ? "bg-black/20" : "bg-slate-50"} mt-1`}>
          {item.description && (
            <Text className={`text-sm mb-1 ${darkTheme ? "text-slate-300" : "text-slate-600"}`}>
              {item.description}
            </Text>
          )}
          <View className="flex-row flex-wrap gap-x-4 gap-y-1 mt-1">
            {item.reference_id && (
              <Text className={`text-xs font-mono ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                Ref: {item.reference_id}
              </Text>
            )}
            {item.mpesa_receipt_number && (
              <Text className={`text-xs font-mono ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>
                Receipt: {item.mpesa_receipt_number}
              </Text>
            )}
            <Text className={`text-xs font-sans-bold capitalize ${item.status === 'completed' ? 'text-green-500' : item.status === 'failed' ? 'text-red-500' : 'text-amber-500'}`}>
                {item.status}
            </Text>
          </View>
        </View>
      )}
    </View>
  );
});

export default function Transactions() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearchQuery = useDebounce(searchQuery, 500);
  const [searchState, setSearchState] = useState("");
  const [typeFilter, setTypeFilter] = useState("All");

  const txQuery = useWalletTransactionsPaginated(searchState, typeFilter, 20);
  const { data: txData, isFetching: txLoading, refetch } = txQuery;

  // Deduped on the ledger id: a top-up landing while somebody scrolls shifts
  // the offset window and re-serves the last row of the previous page.
  const filteredTransactions = flattenPages<WalletTransaction>(txData);

  React.useEffect(() => {
    if (debouncedSearchQuery.trim().length > 1) {
      setSearchState(debouncedSearchQuery.trim());
    } else {
      setSearchState("");
    }
  }, [debouncedSearchQuery]);

  const onRefresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const renderItem = useCallback(({ item }: any) => {
    return <TransactionItem item={item} darkTheme={darkTheme} />;
  }, [darkTheme]);

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      <View style={{ overflow: "hidden", paddingBottom: 4 }}>
        <View 
          className="pt-4 pb-4 mb-2 gap-3"
          style={{ 
            backgroundColor: darkTheme ? "#000" : "#fff",
            borderBottomWidth: 1, 
            borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
            ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
          }}
        >
          <View className="flex-row items-center px-4">
            <PressableScale accessibilityLabel="Go Back" onPress={() => router.back()} activeOpacity={0.6}>
              <BackButtonMinimal />
            </PressableScale>
            <SearchBar
              width="flex-1 ml-3"
              height="h-[50px]"
              buttonStyle=""
              value={searchQuery}
              placeholder="Search by reference, receipt or note"
              setFunc={setSearchQuery}
            />
          </View>
          
          <View className="pt-2">
            <ScrollView 
              horizontal 
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: 20, gap: 8 }}
            >
              {[
                { id: "All", label: "All Transactions" }, 
                { id: "top_up", label: "Top Ups" }, 
                { id: "withdrawal", label: "Withdrawals" },
                { id: "order_payment", label: "Payments" },
                { id: "commission_deduction", label: "Commissions" },
              ].map(f => (
                <PressableScale
                  key={f.id}
                  onPress={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setTypeFilter(f.id);
                  }}
                  className={`px-4 py-2 rounded-full border ${typeFilter === f.id ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
                  style={typeFilter !== f.id ? { ...(darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : {}}
                >
                  <Text className={`font-sans-semibold text-sm ${typeFilter === f.id ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                    {f.label}
                  </Text>
                </PressableScale>
              ))}
            </ScrollView>
          </View>
        </View>
      </View>

      <View className="flex-1 px-4 pt-2">
        {!txLoading && filteredTransactions.length === 0 ? (
          <View className="mt-16">
            <EmptyState 
              mood="sad" 
              title="No transactions found" 
              subtitle={searchQuery.length > 0 ? "Try adjusting your search query or filters." : "Your transaction history will appear here."} 
            />
          </View>
        ) : (
          <FlashList
            data={filteredTransactions}
            renderItem={renderItem}
            keyExtractor={(item: any) => item.id.toString()}
            {...{ estimatedItemSize: 120 } as any}
            showsVerticalScrollIndicator={false}
            onEndReached={keepPaging(txQuery)}
            onEndReachedThreshold={0.5}
            refreshControl={
              <RefreshControl 
                refreshing={txLoading && filteredTransactions.length > 0} 
                onRefresh={onRefresh} 
                tintColor={BRAND.primary} 
              />
            }
            ListFooterComponent={() => 
                txLoading && filteredTransactions.length > 0 ? (
                    <View className="py-4 items-center">
                        <Skeleton width={150} height={20} borderRadius={8} />
                    </View>
                ) : null
            }
          />
        )}
      </View>
    </SafeAreaView>
  );
}
