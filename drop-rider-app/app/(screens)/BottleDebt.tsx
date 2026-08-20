import React, { useCallback, useContext, useMemo, useState, memo } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { RefreshControl, ScrollView, StatusBar, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { format } from "date-fns";
import * as Haptics from "expo-haptics";

import { BRAND } from "@/constants/brandColors";
import { Skeleton } from "@/components/ui/Skeleton";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { CollectionsSection } from "@/components/bottles/CollectionsSection";
import { UIThemeContext } from "@/context/ThemeContext";
import {
    useBottleDebt,
    useBottleLedger,
    type BottleLedgerEntry,
    type VendorBottleDebt,
} from "@/hooks/queries/useBottleDebt";

/**
 * What this rider owes each vendor in empty bottles, and the movement history
 * behind it.
 *
 * Every quick_swap delivery makes the rider liable for the empties they collected
 * until a vendor confirms receipt. Before this screen existed the debt accrued
 * invisibly — only the vendor could see it, and a rider cannot return bottles they
 * do not know they are holding.
 */

const ENTRY_LABEL: Record<BottleLedgerEntry["entry_type"], string> = {
    delivery_accrual: "Collected on delivery",
    vendor_receipt: "Returned to vendor",
    adjustment: "Adjustment",
};

const ENTRY_ICON: Record<BottleLedgerEntry["entry_type"], string> = {
    delivery_accrual: "arrow-up-circle",
    vendor_receipt: "arrow-down-circle",
    adjustment: "swap-horizontal",
};

const VendorDebtCard = memo(({ item, darkTheme }: { item: VendorBottleDebt; darkTheme: boolean }) => {
    const others = Object.entries(item.other_capacities || {});
    return (
        <View
            className={`p-4 mb-3 rounded-2xl border ${
                darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"
            }`}
        >
            <View className="flex-row items-center justify-between mb-3">
                <Text
                    className={`text-base font-sans-bold flex-1 pr-3 ${darkTheme ? "text-white" : "text-slate-900"}`}
                    numberOfLines={1}
                >
                    {item.business_name || "Vendor"}
                </Text>
                <View className={`px-3 py-1 rounded-full ${item.is_stale ? "bg-red-500/20" : "bg-orange-500/20"}`}>
                    <Text className={`font-sans-bold text-xs ${item.is_stale ? "text-red-600" : "text-orange-600"}`}>
                        {item.total_bottles} owed
                    </Text>
                </View>
            </View>

            {/* The clock the platform judges this by. The screen showed the
                quantity and never the age, so the first a rider knew of the
                threshold was being flagged against it. */}
            {item.held_days !== null && item.held_days !== undefined ? (
                <Text
                    className={`text-xs mb-3 ${
                        item.is_stale
                            ? "text-red-500 font-sans-semibold"
                            : darkTheme ? "text-gray-400" : "text-slate-500"
                    }`}
                >
                    {item.held_days === 0
                        ? "Picked up today"
                        : `Held ${item.held_days} day${item.held_days === 1 ? "" : "s"}`}
                    {item.is_stale ? " — overdue, return these first" : ""}
                </Text>
            ) : null}

            <View className="flex-row gap-3">
                <View className={`flex-1 p-3 rounded-xl ${darkTheme ? "bg-black/30" : "bg-slate-50"}`}>
                    <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-slate-500"}`}>
                        10L empties
                    </Text>
                    <Text
                        className={`text-xl font-sans-bold ${
                            item.pending_10L_empties > 0
                                ? "text-orange-500"
                                : darkTheme
                                ? "text-white"
                                : "text-slate-900"
                        }`}
                    >
                        {item.pending_10L_empties || 0}
                    </Text>
                </View>
                <View className={`flex-1 p-3 rounded-xl ${darkTheme ? "bg-black/30" : "bg-slate-50"}`}>
                    <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-slate-500"}`}>
                        20L empties
                    </Text>
                    <Text
                        className={`text-xl font-sans-bold ${
                            item.pending_20L_empties > 0
                                ? "text-orange-500"
                                : darkTheme
                                ? "text-white"
                                : "text-slate-900"
                        }`}
                    >
                        {item.pending_20L_empties || 0}
                    </Text>
                </View>
            </View>

            {others.length > 0 && (
                <View className="flex-row flex-wrap gap-2 mt-3">
                    {others.map(([size, qty]) => (
                        <View
                            key={size}
                            className={`px-3 py-1 rounded-full ${darkTheme ? "bg-black/30" : "bg-slate-100"}`}
                        >
                            <Text className={`text-xs ${darkTheme ? "text-gray-300" : "text-slate-600"}`}>
                                {size}: {qty}
                            </Text>
                        </View>
                    ))}
                </View>
            )}
        </View>
    );
});
VendorDebtCard.displayName = "VendorDebtCard";

const LedgerRow = memo(({ item, darkTheme }: { item: BottleLedgerEntry; darkTheme: boolean }) => {
    const isReturn = item.quantity < 0;
    return (
        <View className="flex-row items-center py-3">
            <View
                className={`w-9 h-9 rounded-full items-center justify-center mr-3 ${
                    isReturn ? "bg-green-500/20" : "bg-orange-500/20"
                }`}
            >
                <Ionicons
                    name={(ENTRY_ICON[item.entry_type] || "list") as any}
                    size={18}
                    color={isReturn ? "#16a34a" : "#ea580c"}
                />
            </View>
            <View className="flex-1">
                <Text className={`text-sm font-sans-semibold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                    {ENTRY_LABEL[item.entry_type] || "Movement"}
                </Text>
                <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-slate-500"}`}>
                    {item.created_at ? format(new Date(item.created_at), "d MMM yyyy, HH:mm") : "—"}
                </Text>
            </View>
            <Text className={`text-sm font-sans-bold ${isReturn ? "text-green-600" : "text-orange-600"}`}>
                {isReturn ? "" : "+"}
                {item.quantity} × {item.capacity_litres}L
            </Text>
        </View>
    );
});
LedgerRow.displayName = "LedgerRow";

export default function BottleDebt() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const [refreshing, setRefreshing] = useState(false);

    const { data, isLoading, refetch, isError } = useBottleDebt();
    const { data: ledger, refetch: refetchLedger } = useBottleLedger(30);

    const vendors = useMemo(() => data?.vendors ?? [], [data]);
    const entries = useMemo(() => ledger?.entries ?? [], [ledger]);

    const onRefresh = useCallback(async () => {
        setRefreshing(true);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        await Promise.all([refetch(), refetchLedger()]);
        setRefreshing(false);
    }, [refetch, refetchLedger]);

    return (
        <>
            <StatusBar barStyle={darkTheme ? "light-content" : "dark-content"} />
            <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : "bg-slate-50"}`}>
                <View className="flex-row items-center px-4 pb-4">
                    <BackButtonMinimal />
                    <Text className={`text-xl font-sans-bold ml-4 ${darkTheme ? "text-white" : "text-slate-900"}`}>
                        Bottles I'm Holding
                    </Text>
                </View>

                <ScrollView
                    className="px-4"
                    contentContainerStyle={{ paddingBottom: tabBarClearance }}
                    refreshControl={
                        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={BRAND.primary} />
                    }
                >
                    <View
                        className={`p-5 rounded-2xl mb-4 ${darkTheme ? "bg-surface-container" : "bg-white"}`}
                    >
                        <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-slate-500"}`}>
                            Total empties owed
                        </Text>
                        {isLoading ? (
                            <Skeleton width={80} height={36} borderRadius={8} />
                        ) : (
                            <Text className={`text-4xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                {data?.total_bottles ?? 0}
                            </Text>
                        )}
                        {(data?.stale_vendors ?? 0) > 0 ? (
                            <View className={`mt-3 p-3 rounded-xl border ${darkTheme ? "bg-red-500/10 border-red-500/20" : "bg-red-50 border-red-200"}`}>
                                <Text className={`text-xs font-sans-bold ${darkTheme ? "text-red-400" : "text-red-700"}`}>
                                    {data?.stale_vendors} vendor{(data?.stale_vendors ?? 0) === 1 ? "" : "s"} overdue
                                </Text>
                                <Text className={`text-xs mt-0.5 ${darkTheme ? "text-red-300/80" : "text-red-700/80"}`}>
                                    Empties held longer than {data?.stale_after_days ?? 14} days are
                                    flagged to the platform. Return those first.
                                </Text>
                            </View>
                        ) : null}
                        <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-500" : "text-slate-400"}`}>
                            Hand these back to the vendor to clear your balance. The vendor confirms
                            the count on their side.
                        </Text>
                    </View>

                    {isError && (
                        <View className="p-4 rounded-2xl mb-4 bg-red-500/10">
                            <Text className="text-red-500 text-sm">
                                Couldn't load your bottle balance. Pull down to retry.
                            </Text>
                        </View>
                    )}

                    {isLoading ? (
                        <>
                            <Skeleton width="100%" height={120} borderRadius={16} />
                            <View className="h-3" />
                            <Skeleton width="100%" height={120} borderRadius={16} />
                        </>
                    ) : vendors.length === 0 ? (
                        <View className="items-center py-10">
                            <Ionicons
                                name="checkmark-circle-outline"
                                size={48}
                                color={darkTheme ? "#334155" : "#cbd5e1"}
                            />
                            <Text className={`mt-3 font-sans-semibold ${darkTheme ? "text-gray-300" : "text-slate-600"}`}>
                                All clear
                            </Text>
                            <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-500" : "text-slate-400"}`}>
                                You're not holding any vendor's empties.
                            </Text>
                        </View>
                    ) : (
                        vendors.map((v) => (
                            <VendorDebtCard key={v.vendor_id} item={v} darkTheme={darkTheme} />
                        ))
                    )}

                    {/* Collections add to what this rider is holding, so they
                        belong on this screen rather than one of their own. */}
                    <CollectionsSection vendors={vendors} />

                    {entries.length > 0 && (
                        <View className="mt-4">
                            <Text
                                className={`text-sm font-sans-bold mb-1 ${darkTheme ? "text-gray-300" : "text-slate-700"}`}
                            >
                                Recent activity
                            </Text>
                            <View
                                className={`px-4 rounded-2xl ${
                                    darkTheme ? "bg-surface-container" : "bg-white"
                                }`}
                            >
                                {entries.map((e) => (
                                    <LedgerRow key={e.id} item={e} darkTheme={darkTheme} />
                                ))}
                            </View>
                        </View>
                    )}
                </ScrollView>
            </SafeAreaView>
        </>
    );
}
