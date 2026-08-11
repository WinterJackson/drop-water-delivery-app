import React, { useCallback, useContext, useState, memo } from "react";
import {
    RefreshControl,
    StatusBar,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { FlashList } from "@shopify/flash-list";
import { Ionicons } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { BRAND } from "@/constants/brandColors";

import { Skeleton } from "@/components/ui/Skeleton";
import { VendorOrderCardSkeleton } from "@/components/skeletons/ContextualSkeletons";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { UIThemeContext } from "@/context/ThemeContext";
import { useUpdateOrderStatus, useVendorOrdersPaginated } from "@/hooks/queries/useVendorOrders";
import { useDashboard } from "@/hooks/queries/useDashboard";
import { PERMISSIONS, useCan, useVendorProfile } from "@/hooks/queries/useVendorProfile";
import useWebSocket from "@/hooks/useWebSocket";
import { useDebounce } from "@/hooks/useDebounce";
import { trackEvent } from "@/utils/analytics";
import { errorMessage } from "@/API/errors";
import { ORDER_FILTERS, isUnderReview, orderStatusStyle } from "@/constants/orderStatus";
import { Toast } from "@/lib/toast";
import SearchBar from "@/components/common/Search";
import { ScrollView } from "react-native-gesture-handler";
import { EmptyState } from "@/components/ui/EmptyState";
import { compareMoney, formatMoney, subtractMoney } from "@/utils/money";

// Memoized order item to prevent unnecessary re-renders during WebSocket updates
const OrderItem = memo(({ item, darkTheme, updatingOrder, onUpdateStatus, router, vendorProfile }: any) => {
  const isWholesale = vendorProfile?.vendor_type === "wholesale_b2b";
  const isCash = item.payment_method === "cash";
  const platformCommission = item.platform_total ?? "0";
  const walletBalance = vendorProfile?.wallet_balance ?? "0";
  // Compared in cents. The server refuses regardless; this decides the warning.
  const isInsufficientFloat =
    isWholesale && isCash && compareMoney(walletBalance, platformCommission) < 0;

  return (
    <PressableScale 
      activeOpacity={0.7}
      onPress={() => router.push(`/(screens)/OrderDetail/${item.id}`)}
      className={`p-5 mb-4 rounded-[24px] border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}
      style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
    >
      <View className="flex-row justify-between items-center mb-3">
        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-slate-900"}`}>
          Order #{item.id?.substring(0, 8)}
        </Text>
        <View className={`px-4 py-1.5 rounded-full ${orderStatusStyle(item.order_status).pill}`}>
          <Text className={`text-xs font-sans-bold uppercase ${orderStatusStyle(item.order_status).text}`}>
            {orderStatusStyle(item.order_status).label}
          </Text>
        </View>
      </View>

      {/* A paused order is the one kind a vendor most needs explained: their
          stock is committed and their money is pending, and nothing on this
          card previously said why it had stopped. */}
      {isUnderReview(item.order_status) && (
        <View className={`flex-row items-start gap-2 p-3 mb-3 rounded-2xl ${darkTheme ? "bg-amber-500/10" : "bg-amber-50"}`}>
          <Ionicons name="alert-circle-outline" size={18} color="#d97706" style={{ marginTop: 1 }} />
          <Text className={`flex-1 text-xs leading-relaxed ${darkTheme ? "text-amber-200" : "text-amber-800"}`}>
            {orderStatusStyle(item.order_status).explanation}
          </Text>
        </View>
      )}
      <Text className={`text-sm font-sans-semibold mb-1 ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
        {formatMoney(item.total_amount)} <Text className={`font-sans ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>· {item.order_item?.length || 0} item(s)</Text>
      </Text>
      <Text className={`text-sm ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
        Payment: <Text className="font-sans-semibold">{item.payment_status}</Text>
      </Text>

      {item.delivery_type && (
        <View className={`mt-3 p-3 rounded-xl border ${darkTheme ? "border-slate-700 bg-slate-800" : "border-slate-200 bg-white"}`}>
          <View className="flex-row items-center gap-1.5">
            <Ionicons 
              name={item.delivery_type === 'quick_swap' ? 'flash' : 'lock-closed'} 
              size={16} 
              color={BRAND.primary} 
            />
            <Text className={`font-sans-bold ${item.delivery_type === 'quick_swap' ? 'text-blue-500' : 'text-purple-500'}`}>
              {item.delivery_type === 'quick_swap' ? 'Quick Swap' : 'Keep My Bottle'}
            </Text>
          </View>
          <Text className={`text-xs mt-1 ${darkTheme ? "text-slate-400" : "text-slate-600"}`}>
            {item.delivery_type === 'quick_swap' ? 'Prepare a filled bottle for the rider.' : 'Wait for the rider to arrive with an empty bottle to refill.'}
          </Text>
        </View>
      )}

      {item.order_status === "pending" && (
        <View className="mt-4">
          {isWholesale && isCash && (
            <View className={`p-3 rounded-xl border mb-3 ${darkTheme ? "bg-amber-900/20 border-amber-500/30" : "bg-amber-50 border-amber-200"}`}>
               <View className="flex-row items-center mb-1">
                 <Ionicons name="warning" size={16} color="#f59e0b" style={{ marginRight: 6 }} />
                 <Text className={`font-sans-bold text-xs ${darkTheme ? "text-amber-500" : "text-amber-700"}`}>Cash Order (Wholesale)</Text>
               </View>
               <Text className={`text-xs ${darkTheme ? "text-amber-200/70" : "text-amber-700/80"}`}>
                 Commission to deduct: <Text className="font-sans-bold">{formatMoney(platformCommission)}</Text>
               </Text>
               {isInsufficientFloat && (
                 <Text className="text-red-500 text-xs font-sans-bold mt-1">
                   Shortfall: {formatMoney(subtractMoney(platformCommission, walletBalance))}. Please top up.
                 </Text>
               )}
            </View>
          )}

          <View className="flex-row gap-3">
            <PressableScale
              onPress={() => onUpdateStatus(item.id, "accepted")}
              activeOpacity={0.8}
              disabled={updatingOrder === item.id || isInsufficientFloat}
              className={`flex-1 ${updatingOrder === item.id || isInsufficientFloat ? "bg-accentbg/60" : "bg-accentbg"} py-4 rounded-[16px] items-center`}
            >
              <Text className={`font-sans-bold text-base ${isInsufficientFloat ? "text-white/60" : "text-white"}`}>
                {updatingOrder === item.id ? "..." : isInsufficientFloat ? "Insufficient Float" : "Accept"}
              </Text>
            </PressableScale>
            <PressableScale
              onPress={() => onUpdateStatus(item.id, "rejected")}
              activeOpacity={0.8}
              disabled={updatingOrder === item.id}
              className={`flex-1 ${updatingOrder === item.id ? "bg-red-50" : "bg-red-500/10"} border border-red-500/20 py-4 rounded-[16px] items-center`}
            >
              <Text className="text-red-600 font-sans-bold text-base">{updatingOrder === item.id ? "..." : "Reject"}</Text>
            </PressableScale>
          </View>
        </View>
      )}
      {item.order_status === "accepted" && (
        <PressableScale
          onPress={() => onUpdateStatus(item.id, "preparing")}
          activeOpacity={0.8}
          disabled={updatingOrder === item.id}
          className={`mt-3 ${updatingOrder === item.id ? "bg-purple-500/60" : "bg-purple-500"} py-3 rounded-2xl items-center`}
        >
          <Text className="text-white font-sans-semibold text-lg">{updatingOrder === item.id ? "..." : "Start Preparing"}</Text>
        </PressableScale>
      )}
      {item.order_status === "preparing" && (
        <PressableScale
          onPress={() => onUpdateStatus(item.id, "ready")}
          activeOpacity={0.8}
          disabled={updatingOrder === item.id}
          className={`mt-3 ${updatingOrder === item.id ? "bg-green-500/60" : "bg-green-500"} py-3 rounded-2xl items-center`}
        >
          <Text className="text-white font-sans-semibold text-lg">{updatingOrder === item.id ? "..." : "Mark as Ready"}</Text>
        </PressableScale>
      )}
    </PressableScale>
  );
});

export default function Orders() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearchQuery = useDebounce(searchQuery, 500);
  const [searchState, setSearchState] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [updatingOrder, setUpdatingOrder] = useState<string | null>(null);

  const { 
    data: ordersData, 
    isFetching: productLoading, 
    fetchNextPage: fetchNextOrders, 
    hasNextPage: hasNextOrders, 
    refetch 
  } = useVendorOrdersPaginated(searchState, statusFilter, 20);
  
  const { mutateAsync: updateStatusMutation } = useUpdateOrderStatus();
  const canManageOrders = useCan(PERMISSIONS.manageOrders);
  const { data: dashboard } = useDashboard();
  const { data: vendorProfile } = useVendorProfile();
  const vendorId = dashboard?.vendor_id;

  // `page.items` — the server no longer pretends to be an `InfiniteData`.
  const filteredOrders = ordersData?.pages?.flatMap((page) => page.items ?? []) || [];

  // WebSocket hook for real-time order updates
  const { connected } = useWebSocket('vendor', vendorId || "", (updateData) => {
    if (updateData.action === 'heartbeat') return;
    refetch();
  });

  React.useEffect(() => {
    if (debouncedSearchQuery.trim().length > 1) {
      setSearchState(debouncedSearchQuery.trim());
      trackEvent('vendor_orders_search', { query: debouncedSearchQuery.trim() });
    } else {
      setSearchState("");
    }
  }, [debouncedSearchQuery]);

  const updateStatus = useCallback(async (orderId: string, status: string) => {
    if (updatingOrder === orderId) return;
    if (!canManageOrders) {
      Toast.error("Not allowed", "Ask the store owner to enable order management for you.");
      return;
    }
    setUpdatingOrder(orderId);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    try {
      await updateStatusMutation({ orderId, status });
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // The optimistic update has already rolled back. Without this the row
      // simply snapped to its old status and the vendor was told nothing —
      // typically because the customer cancelled first (409) or the order had
      // already moved on.
      Toast.error("Couldn't update", errorMessage(e, "That order didn't change. Please refresh."));
    } finally {
      setUpdatingOrder(null);
    }
  }, [updatingOrder, updateStatusMutation, canManageOrders]);

  const onRefresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const renderItem = useCallback(({ item }: any) => {
    return (
      <OrderItem 
        item={item} 
        darkTheme={darkTheme} 
        updatingOrder={updatingOrder} 
        onUpdateStatus={updateStatus}
        router={router}
        vendorProfile={vendorProfile}
      />
    );
  }, [darkTheme, updatingOrder, updateStatus, router, vendorProfile]);

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
              setFunc={setSearchQuery}
            />
          </View>
          
          {/* Status Filter Chips directly below SearchBar */}
          <View className="pt-2">
            <ScrollView 
              horizontal 
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: 20, gap: 8 }}
            >
              {ORDER_FILTERS.map(f => (
                <PressableScale
                  key={f.id}
                  onPress={() => {
                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    setStatusFilter(f.id);
                  }}
                  className={`px-4 py-2 rounded-full border ${statusFilter === f.id ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
                  style={statusFilter !== f.id ? { ...(darkTheme ? {} : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : {}}
                >
                  <Text className={`font-sans-semibold text-sm ${statusFilter === f.id ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                    {f.label}
                  </Text>
                </PressableScale>
              ))}
            </ScrollView>
          </View>
        </View>
      </View>

      <View style={{ flex: 1 }}>
        <FlashList
          data={filteredOrders}
          keyExtractor={(item: any) => item.id}
          // @ts-ignore
          refreshControl={<RefreshControl refreshing={productLoading} onRefresh={onRefresh} tintColor={darkTheme ? "white" : "black"} />}
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 120 }}
          onEndReached={() => {
            if (hasNextOrders) fetchNextOrders();
          }}
          onEndReachedThreshold={0.5}
          ListEmptyComponent={
          productLoading && filteredOrders.length === 0 ? (
            <View className="gap-4">
              {[...Array(4)].map((_, i) => (
                <VendorOrderCardSkeleton key={i} />
              ))}
            </View>
          ) : (
            <View className="mt-16">
              <EmptyState 
                mood="sad" 
                title="No orders yet" 
                subtitle="Orders will appear here once customers place them." 
              />
            </View>
          )
        }
        renderItem={renderItem}
        />
      </View>
    </SafeAreaView>
  );
}
