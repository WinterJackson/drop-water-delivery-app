import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useTabBarClearance } from '@/constants/layout';
import { EmptyState } from "@/components/ui/EmptyState";
import { PaymentRecordSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { UIThemeContext } from "@/context/ThemeContext";
import { usePaymentHistory, paymentRows, type PaymentHistoryEntry } from "@/hooks/queries/useOrders";
import { keepPaging } from "@/utils/paging";
import { formatMoney } from "@/utils/money";
import { useRouter } from "expo-router";
import { useContext } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import {
    RefreshControl,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { FlashList as OriginalFlashList } from "@shopify/flash-list";
import { BRAND } from "@/constants/brandColors";

const FlashList = OriginalFlashList as any;

/**
 * The shape here is `PaymentHistoryEntry` from the hook — the endpoint's own
 * contract. This screen used to declare its own `PaymentRecord` with
 * `total_price`, `order_status` and a nested `vendor`, none of which
 * `/api/payments/history` has ever sent. Every row rendered "KSH 0.00" under an
 * unmatched status, and tapping one opened the *payment's* id as an order.
 */

export default function PaymentHistory() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();
    const paymentsQuery = usePaymentHistory();
    const { isLoading: loading, isFetchingNextPage, hasNextPage, refetch: fetchPayments } = paymentsQuery;
    const payments = paymentRows(paymentsQuery.data);

    // These are *payment* statuses — the values `Payment.status` and the cash
    // branch of `/api/payments/history` actually take. The screen previously
    // switched on order statuses ("delivered", "rejected"), which this endpoint
    // has never sent, so every row fell through to the default.
    const getStatusColor = (status: string) => {
        switch (status) {
            case "paid": return "text-green-500";
            case "failed":
            case "refund_failed": return "text-red-500";
            case "refunded": return "text-blue-400";
            // Nothing was ever collected and nothing ever will be. It is not a
            // pending charge, and it must not wear the pending colour.
            case "not_charged": return darkTheme ? "text-gray-500" : "text-gray-400";
            default: return "text-yellow-500";
        }
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case "paid": return "✅";
            case "failed":
            case "refund_failed": return "❌";
            case "refunded": return "↩️";
            case "not_charged": return "⊘";
            case "pending": return "⏳";
            default: return "🔄";
        }
    };

    // Only money that actually left the customer is written in the colour of
    // money. A failed, reversed or never-collected charge rendered in the same
    // bold green as a successful one is the amount reading as taken.
    const getAmountColor = (status: string) =>
        status === "paid"
            ? "text-green-500"
            : status === "not_charged"
              ? (darkTheme ? "text-gray-500" : "text-gray-400")
              : (darkTheme ? "text-white" : "text-black");

    return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : ""}`} style={{ paddingTop: StatusBar.currentHeight }}>
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />

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
                <PressableScale onPress={() => router.back()} activeOpacity={0.7}>
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`font-sans-bold text-xl ${darkTheme ? "text-white" : "text-black"}`}>
                    Payment History
                </Text>
            </View>
            </View>

            <View className="flex-1 px-4">
                <FlashList
                    data={loading && payments.length === 0 ? [1, 2, 3] : payments}
                    // The list carries two kinds of row: three placeholder numbers
                    // while the first page loads, then real payments. A payment has
                    // an id; a placeholder has only its position, which is all the
                    // identity a placeholder needs.
                    keyExtractor={(item: any, index: number) =>
                        typeof item === "number" ? `placeholder-${index}` : String(item.id)
                    }
					// @ts-ignore
					estimatedItemSize={100}
                    contentContainerStyle={{ paddingTop: 16, paddingBottom: tabBarClearance }}
                    showsVerticalScrollIndicator={false}
                    refreshControl={
                        <RefreshControl
                            refreshing={loading}
                            onRefresh={fetchPayments}
                            tintColor={darkTheme ? "#fff" : "#000"}
                        />
                    }
                    onEndReached={keepPaging(paymentsQuery)}
                    onEndReachedThreshold={0.5}
                    ListFooterComponent={
                        isFetchingNextPage ? (
                            <View className="py-4">
                                <PaymentRecordSkeleton />
                            </View>
                        ) : !hasNextPage && payments.length > 0 ? (
                            // The receipt somebody is hunting for may be the oldest
                            // one; say plainly when there are no more to load.
                            <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                                That's everything.
                            </Text>
                        ) : null
                    }
                    ListEmptyComponent={() => {
                        if (loading) return null;
                        return (
                            <View className="mt-8">
                                <EmptyState 
                                    title="No Payment History" 
                                    subtitle="No payment history is available at this time." 
                                    mood="search"
                                />
                            </View>
                        );
                    }}
                    renderItem={({ item }: { item: any }) => {
                        if (loading && payments.length === 0) {
                            return <PaymentRecordSkeleton />;
                        }
                        const payment = item as PaymentHistoryEntry;
                        return (
                            <PressableScale
                                key={payment.id}
                                activeOpacity={0.8}
                                onPress={() =>
                                    router.push({
                                        pathname: "/(screens)/OrderDetail",
                                        // `order_id`, never `id`: a cash entry's id is
                                        // `cash-<order id>` and an M-Pesa entry's is the
                                        // payment row's, neither of which opens an order.
                                        params: { orderId: payment.order_id },
                                    })
                                }
                                className="mb-3"
                            >
                                <View
                                    className={`p-4 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}
                                >
                                    <View className="flex-row justify-between items-center mb-2">
                                        <View className="flex-row items-center gap-2">
                                            <Text style={{ fontSize: 18 }}>{getStatusIcon(payment.status)}</Text>
                                            <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>
                                                {payment.vendor_name || "Vendor"}
                                            </Text>
                                        </View>
                                        <Text className={`font-sans-bold text-lg ${getAmountColor(payment.status)}`}>
                                            {formatMoney(payment.amount)}
                                        </Text>
                                    </View>
                                    <View className="flex-row justify-between items-center gap-2">
                                        <Text className={`text-sm ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                            {payment.created_at
                                                ? new Date(payment.created_at).toLocaleDateString("en-US", {
                                                      day: "numeric",
                                                      month: "short",
                                                      year: "numeric",
                                                  })
                                                : "—"}
                                            {"  ·  "}
                                            {payment.payment_method === "cash" ? "Cash" : "M-PESA"}
                                        </Text>
                                        <Text className={`text-sm font-sans-semibold capitalize ${getStatusColor(payment.status)}`}>
                                            {payment.status.replace(/_/g, " ")}
                                        </Text>
                                    </View>
                                    {/* The receipt is what a customer is asked for when
                                        they query a charge, and the failure reason is
                                        the backend's own words. Both were dropped. */}
                                    {payment.mpesa_receipt ? (
                                        <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                                            Receipt {payment.mpesa_receipt}
                                        </Text>
                                    ) : null}
                                    {payment.failure_reason ? (
                                        <Text className="text-xs mt-2 text-red-400">
                                            {payment.failure_reason}
                                        </Text>
                                    ) : null}
                                </View>
                            </PressableScale>
                        );
                    }}
                />
            </View>
        </View>
    );
}
