import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { UIThemeContext } from "@/context/ThemeContext";
import useWebSocket from "@/hooks/useWebSocket";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useCallback, useContext, useEffect, useState } from "react";
import {
    RefreshControl,
    StatusBar,
    View,
    Image,
    TouchableOpacity,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { FlashList as OriginalFlashList } from "@shopify/flash-list";
import { BRAND, TOAST } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
const FlashList = OriginalFlashList as any;
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import PressableScale from "@/components/ui/PressableScale";
import { useRejectDelivery } from "@/hooks/mutations/useRejectDelivery";
import { Toast } from "@/lib/toast";
import { useRouter } from "expo-router";
import { useRiderStore } from "@/stores/useRiderStore";
import { trackEvent } from "@/utils/analytics";
import { useRiderProfile, useRiderOrdersPaginated, riderOrderRows, statusesForTab, type RiderOrderTab } from "@/hooks/queries/useRiderData";
import { keepPaging } from "@/utils/paging";
import { useQueryClient } from "@tanstack/react-query";
import { Popup } from "@/lib/popup";
import { useDebounce } from "@/hooks/useDebounce";
import { RiderOrderCardSkeleton, RiderTripRadarSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatMoney } from "@/utils/money";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/20", accepted: "bg-accentbg/20",
  picked_up: "bg-purple-500/20",
  delivered: "bg-green-500/20", unassigned: "bg-orange-500/20",
};
const STATUS_TEXT: Record<string, string> = {
  pending: "text-yellow-600", accepted: "text-accentbg",
  picked_up: "text-purple-600",
  delivered: "text-green-600", unassigned: "text-orange-600",
};

export default function Orders() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { post } = useApiRequest();
  const router = useRouter();
  const { data: profile } = useRiderProfile();

  const [radarOrders, setRadarOrders] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  // Read riderId from centralized Zustand store instead of redundant API call
  const riderId = useRiderStore((s) => s.riderId);
  const [tab, setTab] = useState<RiderOrderTab>("Incoming");
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearchQuery = useDebounce(searchQuery, 500);
  const [claimingOrder, setClaimingOrder] = useState<string | null>(null);

  const { mutateAsync: rejectDelivery, isPending: isRejecting } = useRejectDelivery();

  // The tab and the search box are both query parameters. This screen used to
  // fetch every order the rider had — capped at the server's default 50 with no
  // way past it — then split the tabs and match the search with three
  // `.filter()` calls over that one page. So a rider's History ended somewhere
  // in the middle of last month, and searching an order reference they had just
  // been given on the phone found nothing unless that delivery happened to be
  // among the newest fifty. The debounce existed and fed only an analytics
  // event; the filter itself ran on every keystroke.
  const ordersQuery = useRiderOrdersPaginated(statusesForTab(tab), debouncedSearchQuery);
  const { isLoading: loading, isFetchingNextPage, hasNextPage, refetch } = ordersQuery;
  const currentList = riderOrderRows(ordersQuery.data);

  // WebSocket hook for real-time order updates
  // Invalidating the `['rider','orders']` prefix, not `refetch()`. The tab and
  // the search term are both part of the query key now, so there is a cache per
  // combination and `refetch` refreshes only the one on screen — a delivery
  // completing would leave Incoming still holding it and History still without
  // it until whichever tab the rider opened next happened to go stale.
  const queryClient = useQueryClient();
  const refreshOrders = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
  }, [queryClient]);

  const { connected } = useWebSocket('rider', riderId || "", (updateData) => {
    if (__DEV__) console.log('Received order update via WebSocket:', updateData);
    if (updateData?.action === "TRIP_RADAR_BROADCAST") {
        setRadarOrders(prev => {
            const exists = prev.find(o => o.id === updateData.order_id);
            if (exists) return prev;
            return [updateData, ...prev];
        });
    } else if (updateData?.action === "ORDER_ASSIGNED") {
        setRadarOrders(prev => prev.filter(o => o.id !== updateData.order_id));
        refreshOrders(); // Pull the newly locked order if it was assigned to us
    } else if (updateData?.action === "ORDER_STATUS_UPDATE" && updateData.status === "cancelled") {
        setRadarOrders(prev => prev.filter(o => o.id !== updateData.order_id));
        refreshOrders();
    } else {
        refreshOrders();
    }
  });

  const onRefresh = useCallback(async () => { setRefreshing(true); await refetch(); setRefreshing(false); }, [refetch]);

  useEffect(() => {
    if (debouncedSearchQuery.trim().length > 1) {
      trackEvent('rider_orders_search', { query: debouncedSearchQuery.trim() });
    }
  }, [debouncedSearchQuery]);

  const handleAcceptRadar = async (orderId: string) => {
    if (claimingOrder) return;
    setClaimingOrder(orderId);
    try {
      await post(RiderApiRoutes.AcceptDelivery(orderId).path);
      Toast.success("Success", "Delivery claimed successfully!");
      setRadarOrders(prev => prev.filter(o => o.id !== orderId));
      refreshOrders();
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 401) return;
      Toast.error("Radar Update", errorMessage(e, "Failed to claim order"));
      setRadarOrders(prev => prev.filter(o => o.id !== orderId));
    } finally {
      setClaimingOrder(null);
    }
  };

  const handleReject = (orderId: string) => {
    Popup.show({
      title: "Reject Delivery",
      message: "Are you sure you want to reject this delivery? It will be reassigned.",
      cancelText: "Cancel",
      confirmText: "Reject",
      isDestructive: true,
      onConfirm: async () => {
           Popup.hide();
           try {
             await rejectDelivery(orderId);
             refreshOrders();
             Toast.success("Rejected", "Delivery reassigned.");
           } catch (e: unknown) {
             Toast.error("Error", (e as Error).message || "Failed to reject delivery");
           }
        }
    });
  };

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
      
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
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                  My Deliveries
              </Text>
          </View>
      </View>

      {!connected && (
          <View className={`px-4 py-2 flex-row justify-center items-center ${darkTheme ? "bg-red-900/50" : "bg-red-100"}`}>
             <Ionicons name="cloud-offline" size={16} color={darkTheme ? "#fca5a5" : "#ef4444"} />
             <Text className={`ml-2 text-xs font-sans-bold ${darkTheme ? "text-red-200" : "text-red-600"}`}>
                Offline Mode - Reconnecting...
             </Text>
          </View>
      )}

      <View className="flex-row px-5 py-3">
         <PressableScale onPress={() => setTab("Incoming")} className="mr-4">
             <Text className={`text-lg font-sans-bold ${tab === "Incoming" ? (darkTheme ? "text-white" : "text-gray-900") : "text-gray-400"}`}>
               Incoming
             </Text>
             {tab === "Incoming" && <View className="h-1 bg-accentbg mt-1 rounded-full w-full" />}
         </PressableScale>

         <PressableScale onPress={() => setTab("History")} className="">
             <Text className={`text-lg font-sans-bold ${tab === "History" ? (darkTheme ? "text-white" : "text-gray-900") : "text-gray-400"}`}>
               History
             </Text>
             {tab === "History" && <View className="h-1 bg-accentbg mt-1 rounded-full w-full" />}
         </PressableScale>
      </View>

      {/* Search Bar */}
      <View className="px-5 pb-2">
          <View className={`flex-row items-center px-4 py-3 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
              <Ionicons name="search" size={20} color={BRAND.primary} />
              <TextInput
                  value={searchQuery}
                  onChangeText={setSearchQuery}
                  placeholder={`Search ${tab} deliveries by order reference`}
                  accessibilityLabel={`Search ${tab} deliveries by order reference`}
                  autoCorrect={false}
                  autoCapitalize="none"
                  placeholderTextColor={darkTheme ? BRAND.gray400 : BRAND.gray500}
                  className={`flex-1 font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}
              />
          </View>
      </View>

      {/* TRIP RADAR FEEDS */}
      {tab === "Incoming" && radarOrders.length > 0 && (
          <View className="px-5 pt-2 pb-4">
              <View className="flex-row items-center justify-between mb-2">
                <View className="flex-row items-center gap-1">
                  <Ionicons name="radio-outline" size={18} color={BRAND.primary} />
                  <Text className={`font-sans-bold uppercase tracking-wider ${darkTheme ? "text-orange-400" : "text-orange-600"}`}>Live Trip Radar</Text>
                </View>
                <View className="px-2 py-1 rounded bg-accentbg/20 flex-row items-center gap-1">
                  <Ionicons name={profile?.vehicle_type === 'truck' ? 'bus-outline' : profile?.vehicle_type === 'tuktuk' ? 'car-sport-outline' : 'bicycle-outline'} size={14} color={BRAND.primary} />
                  <Text className="text-xs font-sans-bold text-accentbg">
                    {profile?.vehicle_type === 'truck' ? 'Wholesale' : profile?.vehicle_type === 'tuktuk' ? 'Medium Payload' : 'Standard Payload'}
                  </Text>
                </View>
              </View>
              {radarOrders.map((radar) => (
                  <View key={radar.order_id} className={`p-4 rounded-xl border-l-4 border-orange-500 mb-2 ${darkTheme ? "bg-white/10" : "bg-orange-50"}`}>
                      <View className="flex-row justify-between items-center mb-2">
                         <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Order #{radar.order_id.substring(0, 8)}</Text>
                         <Text className="font-sans-bold text-orange-600">New</Text>
                      </View>
                      <Text className={`mb-3 font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>Estimated Fee: {formatMoney(radar.fee)}</Text>
                      <PressableScale 
                         onPress={() => handleAcceptRadar(radar.order_id)}
                         disabled={claimingOrder === radar.order_id}
                         className={`py-3 rounded-lg items-center ${claimingOrder === radar.order_id ? "bg-gray-400" : "bg-black dark:bg-white"}`}>
                         <Text className={`font-sans-bold text-base ${darkTheme ? "text-black" : "text-white"}`}>
                             {claimingOrder === radar.order_id ? "Claiming Lock..." : "Swipe to Accept"}
                         </Text>
                      </PressableScale>
                  </View>
              ))}
          </View>
      )}

      <View style={{ flex: 1 }}>
        <FlashList
          data={currentList}
          keyExtractor={(item: any) => item.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 120, paddingTop: 10 }}
          onEndReached={keepPaging(ordersQuery)}
          onEndReachedThreshold={0.5}
          ListFooterComponent={
            isFetchingNextPage ? (
              <RiderOrderCardSkeleton />
            ) : !hasNextPage && currentList.length > 0 ? (
              <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                That's everything.
              </Text>
            ) : null
          }
        ListEmptyComponent={
          loading ? <RiderOrderCardSkeleton /> : (
            <View className="mt-10">
              <EmptyState
                  mood={debouncedSearchQuery.trim() ? "sad" : tab === "Incoming" ? "proud" : "sad"}
                  title={
                    debouncedSearchQuery.trim()
                      ? "No Matching Deliveries"
                      : tab === "Incoming" ? "No Incoming Deliveries" : "No Delivery History"
                  }
                  subtitle={
                    debouncedSearchQuery.trim()
                      ? `No ${tab.toLowerCase()} delivery matches "${debouncedSearchQuery.trim()}". The search covers your whole history, so check the reference and try again.`
                      : tab === "Incoming"
                        ? "You currently have no active deliveries. Wait for auto-assignment or check the Trip Radar."
                        : "Your past completed or cancelled deliveries will appear here."
                  }
              />
            </View>
          )
        }
        renderItem={({ item }: { item: any }) => (
          <View className={`p-4 mb-4 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white border border-gray-100"}`}>
            <View className="flex-row justify-between items-center mb-2">
              <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>
                Order #{item.id?.substring(0, 8)}
              </Text>
              <View className={`px-3 py-1 rounded-full ${STATUS_COLORS[item.order_status] || "bg-gray-200"}`}>
                <Text className={`text-xs font-sans-bold capitalize ${STATUS_TEXT[item.order_status] || "text-gray-600"}`}>
                  {item.order_status.replace("_", " ")}
                </Text>
              </View>
            </View>

             {item.delivery_type && (
                <View className="mb-2 flex-row items-center gap-1">
                  <Ionicons name={item.delivery_type === 'quick_swap' ? 'rocket-outline' : 'lock-closed-outline'} size={14} color={item.delivery_type === 'quick_swap' ? TOAST.info : '#a855f7'} />
                  <Text className={`text-xs font-sans-bold ${item.delivery_type === 'quick_swap' ? 'text-blue-500' : 'text-purple-500'}`}>
                     {item.delivery_type === 'quick_swap' ? 'Quick Swap (One-Way)' : 'Keep My Bottle (Round-Trip)'}
                  </Text>
                </View>
             )}

            <View className="flex-row justify-between">
              <View>
                <Text className={`text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                  <Text className="font-sans-semibold">Fee: </Text>{formatMoney(item.delivery_fee)}
                </Text>
                <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                  {item.order_item?.length || 0} items for {item.user?.full_name || "Customer"}
                </Text>
              </View>
            </View>

            {tab === "Incoming" && (
              <View className="flex-row mt-4 gap-2 border-t pt-4 border-gray-200 dark:border-white/10">
                 {(item.order_status === "pending" || item.order_status === "accepted") && (
                   <PressableScale 
                      onPress={() => handleReject(item.id)}
                      disabled={isRejecting}
                      className="flex-1 py-3 rounded-xl bg-red-500/10 items-center justify-center border border-red-500/20"
                   >
                     <Text className="text-red-500 font-sans-bold">{isRejecting ? "..." : "Reject"}</Text>
                   </PressableScale>
                 )}
                 <PressableScale 
                    onPress={() => router.push("/(screens)/ActiveDelivery")}
                    className="flex-1 py-3 rounded-xl bg-accentbg items-center justify-center"
                 >
                   <Text className="text-white font-sans-bold text-base">Open Map</Text>
                 </PressableScale>
              </View>
            )}
          </View>
        )}
      />
      </View>
    </SafeAreaView>
  );
}
