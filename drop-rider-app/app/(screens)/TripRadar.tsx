import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { useTabBarClearance } from '@/constants/layout';
import { UIThemeContext } from "@/context/ThemeContext";
import useWebSocket from "@/hooks/useWebSocket";
import { useRiderStore } from "@/stores/useRiderStore";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import React, { useContext, useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useRiderProfile } from "@/hooks/queries/useRiderData";
import {
    FlatList,
    RefreshControl,
    View,
    TouchableOpacity,
    ScrollView,
    ActivityIndicator,
    StatusBar,
    Platform,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { BRAND, TOAST } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import PressableScale from "@/components/ui/PressableScale";
import { RiderTripRadarSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { EmptyState } from "@/components/ui/EmptyState";
import { Toast } from "@/lib/toast";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import BottomSheet, { BottomSheetScrollView, BottomSheetFlatList } from "@gorhom/bottom-sheet";
import { StyleSheet } from "react-native";
import MapView, { Marker, Polyline, PROVIDER_DEFAULT, PROVIDER_GOOGLE } from "react-native-maps";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import { compareMoney, formatMoney, subtractMoney, sumMoney } from "@/utils/money";

// ─── Types ────────────────────────────────────────────────────────────────────
/**
 * A money field off the socket envelope, as the decimal string everything
 * downstream expects. A number arriving here is coerced rather than passed on:
 * `utils/money.ts` works in integer cents via `BigInt` and a JS number is
 * exactly the representation it exists to keep out.
 */
const asMoney = (value: unknown): string =>
  typeof value === "string" ? value : typeof value === "number" ? String(value) : "0";

/** A numeric field off the socket envelope, defaulting to 0. */
const asNumber = (value: unknown): number =>
  typeof value === "number" ? value : typeof value === "string" ? Number(value) || 0 : 0;

interface RadarOrder {
  id: string;
  order_status: string;
  total_amount: string;
  delivery_fee: string;
  distance_km: number;
  estimated_minutes: number;
  items_count: number;
  weight_kg: number;
  vendor_net?: string;
  platform_total?: string;
  delivery_type: "quick_swap" | "keep_my_bottle";
  payment_method: "cash" | "mpesa";
  vehicle_class: string;
  vendor?: {
    id: string;
    business_name: string;
    location_address?: string;
  };
  delivery_location?: {
    street?: string;
  };
  lat?: number;
  lng?: number;
  lat_from?: number;
  lng_from?: number;
  created_at: string;
}

type FilterType = "ALL" | "< 5KM" | "HIGH PAYOUT" | "QUICK SWAP" | "KEEP MY BOTTLE";

export default function TripRadar() {
    const tabBarClearance = useTabBarClearance();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { get, post } = useApiRequest();
  const router = useRouter();
  const riderId = useRiderStore((s) => s.riderId);
  const isOnline = useRiderStore((s) => s.isOnline);
  const mutedVendors = useRiderStore((s) => s.mutedVendors);

  const [radarOrders, setRadarOrders] = useState<RadarOrder[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);

  const { data: profile } = useRiderProfile();
  const walletBalance = profile?.wallet_balance ?? "0";

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterType>("ALL");

  // Bottom Sheet State
  const bottomSheetRef = useRef<BottomSheet>(null);
  const snapPoints = useMemo(() => ["60%", "90%"], []);
  const [selectedOrder, setSelectedOrder] = useState<RadarOrder | null>(null);
  /**
   * The float a cash order commits: the vendor's cut plus the platform's, held
   * until the rider delivers. Summed in cents and compared in cents — this was
   * six copies of `(vendor_net || 0) + (platform_total || 0)` in float, deciding
   * both what the rider was told and whether the Accept button worked.
   *
   * The server refuses regardless (`cod_policy`); this only decides what the
   * screen says before they tap.
   */
  const cashFloatRequired = sumMoney([selectedOrder?.vendor_net, selectedOrder?.platform_total]);
  const cashFloatShort = compareMoney(walletBalance, cashFloatRequired) < 0;

  // ── Fetch unassigned orders from REST ────────────────────────────────
  const fetchRadarOrders = useCallback(async () => {
    try {
      const raw = await get<RadarOrder[]>(RiderApiRoutes.TripRadar.path);
      const orders: RadarOrder[] = Array.isArray(raw) ? raw : [];
      setRadarOrders(orders.filter((o) => !mutedVendors.includes(o.vendor?.id || "")));
    } catch (e) {
      // The client already signed the rider out if this was a 401. A KYC refusal
      // is the layout gate's business, not the radar's. Anything else is
      // transient and the next tick retries.
      if (__DEV__) console.warn("[TripRadar] Fetch failed:", errorMessage(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mutedVendors, get]);

  // ── WebSocket for real-time radar updates ────────────────────────────
  const { connected } = useWebSocket("rider", riderId || "", (updateData) => {
    if (updateData.action === "TRIP_RADAR_BROADCAST" || updateData.action === "NEW_DELIVERY_OFFER") {
      const newOrderId = updateData.order_id;
      if (!newOrderId) return;
      
      const vendorId = updateData.vendor?.id || "";
      if (mutedVendors.includes(vendorId)) return;

      setRadarOrders((prev) => {
        const exists = prev.some((o) => o.id === newOrderId);
        if (exists) return prev;
        // Money defaults to the string `"0"`, never the number `0`. Every
        // monetary field on this platform is a decimal string all the way to the
        // screen, and `utils/money.ts` is the only thing that touches the digits
        // — handing it a number is the one input it is built to never receive.
        // The socket envelope is open-ended by necessity, so each read is
        // narrowed to the type the card renders rather than trusted.
        const newOrder: RadarOrder = {
          id: newOrderId,
          order_status: "unassigned",
          total_amount: asMoney(updateData.total_amount),
          delivery_fee: asMoney(updateData.delivery_fee ?? updateData.fee),
          distance_km: asNumber(updateData.distance_km),
          estimated_minutes: asNumber(updateData.estimated_minutes),
          items_count: asNumber(updateData.items_count ?? updateData.quantity),
          weight_kg: asNumber(updateData.weight_kg),
          vendor_net: asMoney(updateData.vendor_net),
          platform_total: asMoney(updateData.platform_total),
          delivery_type: updateData.delivery_type === "keep_my_bottle" ? "keep_my_bottle" : "quick_swap",
          payment_method: updateData.payment_method === "cash" ? "cash" : "mpesa",
          vehicle_class: typeof updateData.vehicle_class === "string" ? updateData.vehicle_class : "motorbike",
          vendor: updateData.vendor?.id && updateData.vendor.business_name
            ? {
                id: updateData.vendor.id,
                business_name: updateData.vendor.business_name,
                location_address: updateData.vendor.location_address,
              }
            : undefined,
          lat: asNumber(updateData.lat),
          lng: asNumber(updateData.lng),
          lat_from: asNumber(updateData.lat_from),
          lng_from: asNumber(updateData.lng_from),
          created_at: new Date().toISOString(),
        };
        return [newOrder, ...prev];
      });
    } else if (updateData.action === "TRIP_RADAR_RETRACT") {
      const retractedId = updateData.order_id;
      setRadarOrders((prev) => prev.filter((o) => o.id !== retractedId));
    } else if (updateData.action === "trip_radar_claimed") {
      setRadarOrders((prev) => prev.filter((o) => o.id !== updateData.order_id));
      if (selectedOrder?.id === updateData.order_id) {
        bottomSheetRef.current?.close();
        Toast.error("Claimed", "This order was taken by another rider.");
      }
    } else if (updateData.action === "ORDER_OFFER_BROADCAST") {
      fetchRadarOrders();
    }
  });

  // ── Accept order ─────────────────────────────────────────────────────
  const acceptOrder = async (orderId: string) => {
    setAcceptingId(orderId);
    setRadarOrders((prev) => prev.filter((o) => o.id !== orderId));
    bottomSheetRef.current?.close();

    try {
      await post(RiderApiRoutes.AcceptDelivery(orderId).path);
      Toast.success("Accepted!", "Navigate to the Active Delivery tab.");
      router.push("/(screens)/ActiveDelivery" as any);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      if (status === 401) return; // the client has already signed the rider out

      // The title names the *category*; the body is the backend's own sentence
      // — "You must be online and available to accept orders", "Insufficient
      // balance: KSH 4,000 is committed as float". Those were being thrown away
      // and replaced with "This order was already taken", which was usually a
      // lie about why the accept failed.
      const title =
        status === 402 ? "Insufficient Balance"
        : status === 403 ? "Not Allowed"
        : status === 409 ? "Claimed"
        : status === 0 ? "No Connection"
        : "Couldn't Accept";
      Toast.error(title, errorMessage(e, "This order was already taken by another rider."));
      fetchRadarOrders();
    } finally {
      setAcceptingId(null);
    }
  };

  // ── Polling + Lifecycle ──────────────────────────────────────────────
  //
  // The socket above already pushes new offers, so the poll is a
  // *reconciliation* pass, not the primary path. It used to run every 30s
  // regardless: at 500 online riders that is 1,000 spatial `ST_DWithin` queries
  // a minute purely as a fallback, and it drains rider battery while idle.
  //
  // While the socket is connected, reconciling every two minutes is enough to
  // catch anything a dropped frame lost. While it is disconnected the poll *is*
  // the only path, so it speeds up.
  useEffect(() => {
    if (!isOnline) {
      setRadarOrders([]);
      return;
    }
    fetchRadarOrders();
    const interval = setInterval(fetchRadarOrders, connected ? 120_000 : 15_000);
    return () => clearInterval(interval);
  }, [isOnline, connected, fetchRadarOrders]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchRadarOrders();
    setRefreshing(false);
  }, [fetchRadarOrders]);

  // ── Filtering Logic ──────────────────────────────────────────────────
  const filteredOrders = useMemo(() => {
    let result = radarOrders;

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(o => 
        o.vendor?.business_name.toLowerCase().includes(query) ||
        o.delivery_location?.street?.toLowerCase().includes(query) ||
        o.id.toLowerCase().includes(query)
      );
    }

    if (activeFilter === "< 5KM") {
      result = result.filter(o => o.distance_km < 5);
    } else if (activeFilter === "HIGH PAYOUT") {
      // The threshold is a filter label, not a charge — compared in cents all the same.
      result = result.filter(o => compareMoney(o.delivery_fee, "200") >= 0);
    } else if (activeFilter === "QUICK SWAP") {
      result = result.filter(o => o.delivery_type === "quick_swap");
    } else if (activeFilter === "KEEP MY BOTTLE") {
      result = result.filter(o => o.delivery_type === "keep_my_bottle");
    }

    return result;
  }, [radarOrders, searchQuery, activeFilter]);

  const timeAgo = (dateStr: string) => {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  };

  // ── Components ───────────────────────────────────────────────────────
  const renderHeader = () => (
    <SafeAreaView edges={["top"]} style={{ backgroundColor: darkTheme ? "#000" : "#fff" }}>
      <View style={{ overflow: "hidden", paddingBottom: 4 }}>
        <View 
          className="flex-row items-center justify-between px-4 py-3 pb-4 mb-2"
          style={{ 
            backgroundColor: darkTheme ? "#000" : "#fff",
            borderBottomWidth: 1, 
            borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
            ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
          }}
        >
          <View className="flex-row items-center gap-3">
            <TouchableOpacity onPress={() => router.back()}>
              <BackButtonMinimal />
            </TouchableOpacity>
            <View>
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                Trip Radar
              </Text>
              <View className="flex-row items-center gap-1 mt-0.5">
                <View style={{
                  width: 6, height: 6, borderRadius: 3,
                  backgroundColor: !connected && isOnline ? BRAND.favorite : (isOnline ? TOAST.success : BRAND.favorite)
                }} />
                <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                  {!connected && isOnline ? "Reconnecting..." : (isOnline ? "Online & Scanning" : "Offline")}
                </Text>
              </View>
            </View>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );

  const renderSearchAndFilters = () => (
    <View className={`px-4 pt-2 pb-4`}>
      {/* Search Bar */}
      <View 
        className={`flex-row items-center rounded-xl px-3 py-2 mb-3 border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
      >
        <Ionicons name="search-outline" size={20} color={BRAND.primary} />
        <TextInput
          placeholder="Search vendors, locations, or order ID..."
          placeholderTextColor={darkTheme ? "rgba(255, 255, 255, 0.4)" : "rgba(0, 0, 0, 0.4)"}
          className={`flex-1 ml-2 text-base ${darkTheme ? "text-white" : "text-gray-900"}`}
          value={searchQuery}
          onChangeText={setSearchQuery}
        />
        {searchQuery.length > 0 && (
          <TouchableOpacity accessibilityRole="button" accessibilityLabel="Clear the search" onPress={() => setSearchQuery("")}>
            <Ionicons name="close-circle" size={20} color={BRAND.primary} />
          </TouchableOpacity>
        )}
      </View>

      {/* Filter Chips */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {(["ALL", "< 5KM", "HIGH PAYOUT", "QUICK SWAP", "KEEP MY BOTTLE"] as FilterType[]).map((filter) => {
          const isActive = activeFilter === filter;
          return (
            <TouchableOpacity
              key={filter}
              onPress={() => setActiveFilter(filter)}
              className={`px-4 py-2 rounded-full border ${isActive ? (darkTheme ? "bg-primary border-primary" : "bg-primary border-primary") : (darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200")}`}
            >
              <Text className={`text-xs font-sans-bold ${isActive ? "text-white" : (darkTheme ? "text-gray-300" : "text-gray-700")}`}>
                {filter}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );

  const renderDiscoverBanner = () => (
    <PressableScale
      onPress={() => router.push("/(screens)/DiscoverVendors" as any)}
      className={`mx-4 mb-4 p-4 rounded-2xl border flex-row items-center justify-between ${darkTheme ? "bg-blue-900/20 border-blue-900/40" : "bg-blue-50 border-blue-100"}`}
    >
      <View className="flex-1 mr-3">
        <Text className={`text-base font-sans-bold mb-1 ${darkTheme ? "text-blue-400" : "text-blue-700"}`}>
          Looking for consistent work?
        </Text>
        <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
          Partner with top vendors in your area for guaranteed daily orders.
        </Text>
      </View>
      <View className={`p-2.5 rounded-xl ${darkTheme ? "bg-blue-600" : "bg-blue-600"}`}>
        <Ionicons name="business-outline" size={20} color={BRAND.white} />
      </View>
    </PressableScale>
  );

  const renderEmptyState = () => (
    <View className="flex-1 mt-10">
      <EmptyState
        mood={!isOnline ? "sad" : (searchQuery ? "sad" : "proud")}
        title={!isOnline ? "You are Offline" : (searchQuery ? "No Matches Found" : "Scanning for Deliveries...")}
        subtitle={!isOnline 
          ? "Go online to start receiving Trip Radar broadcasts from nearby vendors." 
          : (searchQuery 
            ? "Try adjusting your search terms or filters to find more orders." 
            : "No unassigned orders match your criteria right now. Keep your app open to receive instant alerts.")}
      />
    </View>
  );

  const renderOrderCard = ({ item }: { item: RadarOrder }) => (
    <PressableScale
      onPress={() => {
        setSelectedOrder(item);
        bottomSheetRef.current?.expand();
      }}
      className={`mx-4 mb-3 p-4 rounded-2xl border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}
      style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
    >
      <View className="flex-row justify-between items-start">
        <View className="flex-1">
          <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>
            {item.vendor?.business_name || "Unknown Vendor"}
          </Text>
          <Text className={`text-sm mt-0.5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
            {item.delivery_location?.street || "Delivery location hidden"}
          </Text>
        </View>
        <View className="items-end">
          <Text className={`text-lg font-sans-extrabold text-primary`}>{formatMoney(item.delivery_fee)}</Text>
          <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
            {timeAgo(item.created_at)}
          </Text>
        </View>
      </View>

      <View className="flex-row flex-wrap gap-3 mt-4">
        <View className="flex-row items-center gap-1">
          <Ionicons name="navigate-outline" size={14} color={BRAND.primary} />
          <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
            {item.distance_km?.toFixed(1)} km
          </Text>
        </View>
        <View className="flex-row items-center gap-1">
          <Ionicons name="time-outline" size={14} color={BRAND.primary} />
          <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
            {item.estimated_minutes} min
          </Text>
        </View>
        <View className="flex-row items-center gap-1">
          <Ionicons name="water-outline" size={14} color={BRAND.primary} />
          <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
            {item.items_count} items ({item.weight_kg}kg)
          </Text>
        </View>
      </View>
    </PressableScale>
  );

  // ── Trip Preview Bottom Sheet ────────────────────────────────────────
  const renderTripPreview = () => {
    if (!selectedOrder) return null;

    return (
        <View style={{ padding: 20 }}>
          <View className="flex-row items-center justify-between mb-4">
            <Text className={`text-2xl font-sans-extrabold ${darkTheme ? "text-white" : "text-black"}`}>
                {formatMoney(selectedOrder.delivery_fee)}
            </Text>
            <TouchableOpacity onPress={() => setSelectedOrder(null)} className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-gray-800" : "bg-gray-200"}`}>
                <Ionicons name="close" size={20} color={darkTheme ? "#fff" : "#000"} />
            </TouchableOpacity>
          </View>
          <Text className={`text-base mb-5 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
            {selectedOrder.distance_km?.toFixed(1)} km • {selectedOrder.estimated_minutes} min total est.
          </Text>

          <View className={`p-4 rounded-2xl border mb-6 ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`}>
            <View className="flex-row items-start mb-4">
              <Ionicons name="storefront-outline" size={20} color={BRAND.primary} style={{ marginTop: 2, marginRight: 12 }} />
              <View className="flex-1">
                <Text className={`text-xs font-sans-bold uppercase mb-0.5 text-primary`}>Pickup</Text>
                <Text className={`text-base font-sans-semibold ${darkTheme ? "text-white" : "text-gray-900"}`}>{selectedOrder.vendor?.business_name}</Text>
              </View>
            </View>

            <View className={`h-px ml-8 mb-4 ${darkTheme ? "bg-gray-800" : "bg-white"}`} />

            <View className="flex-row items-start">
              <Ionicons name="location" size={20} color={TOAST.success} style={{ marginTop: 2, marginRight: 12 }} />
              <View className="flex-1">
                <Text className={`text-xs font-sans-bold uppercase mb-0.5 text-green-500`}>Dropoff</Text>
                <Text className={`text-base font-sans-semibold ${darkTheme ? "text-white" : "text-gray-900"}`}>{selectedOrder.delivery_location?.street || "Customer Location"}</Text>
              </View>
            </View>
          </View>

          <View className="flex-row justify-between mb-8">
            <View className="items-center flex-1">
              <Ionicons name="cube-outline" size={24} color={BRAND.primary} />
              <Text className={`text-sm font-sans-semibold mt-1 ${darkTheme ? "text-white" : "text-gray-900"}`}>{selectedOrder.items_count} Items</Text>
              <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{selectedOrder.weight_kg}kg</Text>
            </View>
            <View className={`w-px ${darkTheme ? "bg-gray-800" : "bg-white"}`} />
            <View className="items-center flex-1">
              <Ionicons name="swap-horizontal-outline" size={24} color={BRAND.primary} />
              <Text className={`text-sm font-sans-semibold mt-1 capitalize ${darkTheme ? "text-white" : "text-gray-900"}`}>
                {selectedOrder.delivery_type.replace('_', ' ')}
              </Text>
              <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Type</Text>
            </View>
            <View className={`w-px ${darkTheme ? "bg-gray-800" : "bg-white"}`} />
            <View className="items-center flex-1">
              <Ionicons name="bicycle-outline" size={24} color={BRAND.primary} />
              <Text className={`text-sm font-sans-semibold mt-1 capitalize ${darkTheme ? "text-white" : "text-gray-900"}`}>
                {selectedOrder.vehicle_class}
              </Text>
              <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Required</Text>
            </View>
          </View>

          {selectedOrder.payment_method === "cash" && (
            <View className={`p-4 rounded-xl border mb-6 ${darkTheme ? "bg-amber-900/20 border-amber-500/30" : "bg-amber-50 border-amber-200"}`}>
               <View className="flex-row items-center mb-2">
                 <Ionicons name="warning" size={20} color="#f59e0b" style={{ marginRight: 8 }} />
                 <Text className={`font-sans-bold text-sm ${darkTheme ? "text-amber-500" : "text-amber-700"}`}>Cash Order</Text>
               </View>
               <Text className={`text-xs mb-2 ${darkTheme ? "text-amber-200/70" : "text-amber-700/80"}`}>
                 You must have enough funds in your Wallet to cover the vendor net pay and platform's commission ({formatMoney(cashFloatRequired)}) to accept this cash order.
               </Text>
               <View className="flex-row items-center justify-between mt-2 pt-2 border-t border-amber-500/20">
                 <Text className={`text-xs font-sans-semibold ${darkTheme ? "text-amber-200" : "text-amber-800"}`}>Your Wallet Balance:</Text>
                 <Text className={`text-sm font-sans-bold ${!cashFloatShort ? (darkTheme ? "text-green-400" : "text-green-600") : "text-red-500"}`}>
                   {formatMoney(walletBalance)}
                 </Text>
               </View>
               {cashFloatShort && (
                 <Text className="text-red-500 text-xs font-sans-bold mt-2">
                   Shortfall: {formatMoney(subtractMoney(cashFloatRequired, walletBalance))}. Please top up or complete cashless orders.
                 </Text>
               )}
            </View>
          )}

          <TouchableOpacity
            onPress={() => acceptOrder(selectedOrder.id)}
            disabled={acceptingId === selectedOrder.id || (selectedOrder.payment_method === "cash" && cashFloatShort)}
            className={`py-4 rounded-2xl items-center flex-row justify-center mb-10 ${(acceptingId === selectedOrder.id || (selectedOrder.payment_method === "cash" && cashFloatShort)) ? (darkTheme ? "bg-gray-800" : "bg-gray-300") : "bg-primary"}`}
            style={{ elevation: 2, shadowColor: BRAND.primary, shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8 }}
          >
            {acceptingId === selectedOrder.id ? (
              <ActivityIndicator color={BRAND.white} />
            ) : (
              <>
                <Text className={`text-lg font-sans-bold mr-2 ${(acceptingId === selectedOrder.id || (selectedOrder.payment_method === "cash" && cashFloatShort)) ? (darkTheme ? "text-gray-500" : "text-gray-500") : "text-white"}`}>
                  {selectedOrder.payment_method === "cash" && cashFloatShort ? "Insufficient Float" : "Accept Trip"}
                </Text>
                <Ionicons name={(selectedOrder.payment_method === "cash" && cashFloatShort) ? "lock-closed" : "checkmark-circle-outline"} size={20} color={(acceptingId === selectedOrder.id || (selectedOrder.payment_method === "cash" && cashFloatShort)) ? (darkTheme ? "#6b7280" : "#6b7280") : BRAND.white} />
              </>
            )}
          </TouchableOpacity>
        </View>
    );
  };

  if (!riderId && !loading) {
    return (
      <DataFallbackUI 
        title="Rider Profile Unavailable"
        message="We couldn't load your rider profile to scan for trips. Please retry or restart."
        onRetry={() => {
          setLoading(true);
          fetchRadarOrders();
        }}
      />
    );
  }

  const mapInitialRegion = profile?.operation_lat && profile?.operation_lng ? {
    latitude: profile.operation_lat,
    longitude: profile.operation_lng,
    latitudeDelta: 0.05,
    longitudeDelta: 0.05,
  } : {
    latitude: -1.2921,
    longitude: 36.8219,
    latitudeDelta: 0.1,
    longitudeDelta: 0.1,
  };

  return (
    <View className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
      
      {/* Background Map */}
      <View style={StyleSheet.absoluteFillObject}>
        {MapView && (
            <MapView
                provider={Platform.OS !== 'web' ? PROVIDER_GOOGLE : undefined}
                googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                style={{ flex: 1 }}
                initialRegion={mapInitialRegion}
                showsUserLocation={true}
                scrollEnabled={true}
                zoomEnabled={true}
            >
                {selectedOrder && selectedOrder.lat_from !== undefined && selectedOrder.lng_from !== undefined && (
                  <Marker coordinate={{ latitude: selectedOrder.lat_from!, longitude: selectedOrder.lng_from! }}>
                    <View className="bg-primary p-1.5 rounded-full border-2 border-white">
                      <Ionicons name="storefront-outline" size={16} color={BRAND.white} />
                    </View>
                  </Marker>
                )}
                {selectedOrder && selectedOrder.lat !== undefined && selectedOrder.lng !== undefined && (
                  <Marker coordinate={{ latitude: selectedOrder.lat!, longitude: selectedOrder.lng! }}>
                    <View className="bg-green-500 p-1.5 rounded-full border-2 border-white">
                      <Ionicons name="location" size={16} color={BRAND.white} />
                    </View>
                  </Marker>
                )}
                {selectedOrder && selectedOrder.lat_from !== undefined && selectedOrder.lng_from !== undefined && selectedOrder.lat !== undefined && selectedOrder.lng !== undefined && (
                  <Polyline
                    coordinates={[
                      { latitude: selectedOrder.lat_from!, longitude: selectedOrder.lng_from! },
                      { latitude: selectedOrder.lat!, longitude: selectedOrder.lng! }
                    ]}
                    strokeColor={BRAND.primary}
                    strokeWidth={3}
                    lineDashPattern={[5, 5]}
                  />
                )}
            </MapView>
        )}
      </View>

      <View className="absolute top-0 left-0 right-0 z-10" style={{ paddingTop: StatusBar.currentHeight || 0 }}>
        {renderHeader()}
      </View>

      <BottomSheet
        ref={bottomSheetRef}
        index={1}
        snapPoints={['35%', '50%', '90%']}
        backgroundStyle={{ backgroundColor: darkTheme ? '#000000' : '#f8fafc' }}
        handleIndicatorStyle={{ backgroundColor: darkTheme ? '#3f4850' : '#cbd5e1', width: 40 }}
        style={{
          shadowColor: "#000",
          shadowOffset: { width: 0, height: -4 },
          shadowOpacity: 0.1,
          shadowRadius: 12,
          elevation: 10,
        }}
      >
        {selectedOrder ? (
            <BottomSheetScrollView contentContainerStyle={{ paddingBottom: tabBarClearance }}>
                {renderTripPreview()}
            </BottomSheetScrollView>
        ) : (
            <BottomSheetFlatList
                data={filteredOrders}
                keyExtractor={(item) => item.id}
                renderItem={renderOrderCard}
                ListHeaderComponent={<>{renderSearchAndFilters()}{renderDiscoverBanner()}</>}
                ListEmptyComponent={loading ? <RiderTripRadarSkeleton /> : renderEmptyState()}
                contentContainerStyle={{ flexGrow: 1, paddingBottom: tabBarClearance }}
                refreshControl={
                <RefreshControl
                    refreshing={refreshing}
                    onRefresh={onRefresh}
                    colors={[BRAND.primary]}
                    tintColor={BRAND.primary}
                />
                }
            />
        )}
      </BottomSheet>
    </View>
  );
}
