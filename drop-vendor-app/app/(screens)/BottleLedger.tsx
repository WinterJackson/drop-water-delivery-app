import React, { useContext, useMemo } from "react";
import { View, FlatList, RefreshControl, ActivityIndicator } from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND } from "@/constants/brandColors";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Skeleton } from "@/components/ui/Skeleton";
import { useBottleLedger, type BottleLedgerEntry } from "@/hooks/queries/useBottleLedger";
import { flattenPages } from "@/utils/paging";

/**
 * Every bottle movement between this store and its riders, newest first.
 *
 * Bottle Reconciliation answers "who owes me what now". This answers "when did
 * that happen, against which order, and did I already take those back" — the
 * question a vendor actually has when a rider disputes a count, and the one a
 * running balance can never answer.
 */

const TYPE_META: Record<
  string,
  { label: string; icon: any; tone: "out" | "in" | "neutral" }
> = {
  delivery_accrual: {
    label: "Went out on a delivery",
    icon: "arrow-up-circle",
    tone: "out",
  },
  vendor_receipt: { label: "You received them back", icon: "arrow-down-circle", tone: "in" },
  adjustment: { label: "Manual correction", icon: "build", tone: "neutral" },
};

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function BottleLedgerScreen() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const {
    data,
    isLoading,
    isError,
    refetch,
    isRefetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useBottleLedger();

  // Deduped on the entry id: the ledger grows at the top, so an accrual written
  // while the vendor is scrolling re-serves the previous page's last row —
  // which on this screen would read as a bottle counted twice.
  const entries = useMemo(() => flattenPages<BottleLedgerEntry>(data), [data]);

  const renderItem = ({ item }: { item: BottleLedgerEntry }) => {
    const meta = TYPE_META[item.entry_type] ?? {
      label: item.entry_type.replace(/_/g, " "),
      icon: "ellipse",
      tone: "neutral" as const,
    };
    // The ledger stores a signed quantity — negative is a return. Showing the
    // raw number would read as "minus six bottles owed", which is the opposite
    // of what happened.
    const count = Math.abs(item.quantity);
    const isReturn = item.quantity < 0;

    return (
      <View
        className={`flex-row items-start p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-100"}`}
        style={darkTheme ? undefined : { shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
      >
        <View
          className={`w-10 h-10 rounded-full items-center justify-center mr-3 ${
            isReturn ? "bg-green-500/15" : meta.tone === "neutral" ? "bg-slate-500/15" : "bg-orange-500/15"
          }`}
        >
          <Ionicons
            name={meta.icon}
            size={20}
            color={isReturn ? "#22c55e" : meta.tone === "neutral" ? "#64748b" : "#f97316"}
          />
        </View>

        <View className="flex-1">
          <View className="flex-row items-baseline justify-between">
            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
              {item.rider_name || "Rider"}
            </Text>
            <Text
              className={`font-sans-bold text-base ${isReturn ? "text-green-500" : darkTheme ? "text-orange-400" : "text-orange-600"}`}
            >
              {isReturn ? "−" : "+"}
              {count} × {item.capacity_litres}L
            </Text>
          </View>

          <Text className={`text-xs mt-0.5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
            {meta.label}
            {item.created_at ? ` · ${formatWhen(item.created_at)}` : ""}
          </Text>

          {item.order_id ? (
            <PressableScale
              onPress={() => router.push(`/(screens)/OrderDetail/${item.order_id}` as any)}
              className="mt-2 self-start"
            >
              <Text className="text-xs font-sans-semibold" style={{ color: BRAND.primary }}>
                Order #{item.order_id.slice(0, 8)} →
              </Text>
            </PressableScale>
          ) : null}

          {item.note ? (
            <Text className={`text-xs mt-1.5 italic ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              {item.note}
            </Text>
          ) : null}
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <View style={{ overflow: "hidden", paddingBottom: 4 }}>
        <View
          className="flex-row items-center px-4 py-3 pb-4 mb-2"
          style={{
            backgroundColor: darkTheme ? "#000" : "#fff",
            borderBottomWidth: 1,
            borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
          }}
        >
          <PressableScale onPress={() => router.back()} className="mr-4">
            <BackButtonMinimal />
          </PressableScale>
          <Text className={`text-xl font-sans-bold flex-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>
            Bottle History
          </Text>
        </View>
      </View>

      {isLoading ? (
        <View className="px-6">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} width="100%" height={84} borderRadius={16} style={{ marginBottom: 12 }} />
          ))}
        </View>
      ) : isError ? (
        <View className="flex-1 items-center justify-center px-8">
          <Ionicons name="cloud-offline-outline" size={44} color={darkTheme ? BRAND.gray400 : BRAND.gray500} />
          <Text className={`text-lg font-sans-bold mt-4 ${darkTheme ? "text-white" : "text-slate-900"}`}>
            Couldn&apos;t load the history
          </Text>
          <PressableScale onPress={() => refetch()} className="mt-6 bg-accentbg px-8 py-3 rounded-full">
            <Text className="text-white font-sans-bold">Try again</Text>
          </PressableScale>
        </View>
      ) : (
        <FlatList
          data={entries}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 40 }}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={BRAND.primary} />
          }
          ListHeaderComponent={
            <Text className={`text-sm mb-5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
              Every empty that left with a rider and every one that came back,
              newest first. This is the record behind the balances on Bottle
              Reconciliation.
            </Text>
          }
          ListEmptyComponent={
            <View className="items-center justify-center py-16">
              <View className={`w-20 h-20 rounded-full items-center justify-center mb-4 ${darkTheme ? "bg-slate-800" : "bg-white border border-slate-100"}`}>
                <Ionicons name="time-outline" size={40} color={BRAND.primary} />
              </View>
              <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                Nothing recorded yet
              </Text>
              <Text className={`text-center mt-2 px-6 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                Movements appear here as riders take Quick Swap orders out and
                bring the empties back.
              </Text>
            </View>
          }
          onEndReachedThreshold={0.4}
          onEndReached={() => {
            if (hasNextPage && !isFetchingNextPage) fetchNextPage();
          }}
          ListFooterComponent={
            isFetchingNextPage ? (
              <ActivityIndicator color={BRAND.primary} style={{ marginVertical: 16 }} />
            ) : null
          }
        />
      )}
    </SafeAreaView>
  );
}
