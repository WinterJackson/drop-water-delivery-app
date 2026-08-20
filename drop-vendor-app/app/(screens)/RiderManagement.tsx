import React, { useContext, useEffect, useState, useCallback, memo } from "react";
import { View, StatusBar, RefreshControl } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { UIThemeContext } from "@/context/ThemeContext";
import PressableScale from "@/components/ui/PressableScale";
import { errorMessage } from "@/API/errors";
import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useApiRequest } from "@/API/useApiClient";
import { useVendorRiders, riderRows } from "@/hooks/queries/useVendorRiders";
import { useDebounce } from "@/hooks/useDebounce";
import { keepPaging } from "@/utils/paging";
import { Toast } from "@/lib/toast";
import { FlashList } from "@shopify/flash-list";
import { Ionicons } from "@expo/vector-icons";
import { Skeleton } from "@/components/ui/Skeleton";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { Popup } from "@/lib/popup";
import { BRAND } from "@/constants/brandColors";
import { Image } from "expo-image";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { EmptyState } from "@/components/ui/EmptyState";
import { ratingScore } from "@/utils/rating";

const RiderCard = memo(({ 
  item, 
  darkTheme, 
  actioningRider, 
  handleAction 
}: { 
  item: any, 
  darkTheme: boolean, 
  actioningRider: string | null, 
  handleAction: (id: string, action: string) => void 
}) => (
  <View className={`p-5 mb-4 rounded-[24px] flex-row items-center border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
    <View className="w-[60px] h-[60px] rounded-full bg-accentbg/10 mr-4 overflow-hidden border border-accentbg/20">
      {item.profile_pic ? (
        <Image source={{ uri: item.profile_pic }} style={{ width: "100%", height: "100%" }} cachePolicy="disk" transition={200} />
      ) : (
        <View className="flex-1 items-center justify-center">
          <Ionicons name="person" size={28} color={BRAND.primary} />
        </View>
      )}
    </View>
    <View className="flex-1">
      <View className="flex-row items-center">
        <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-gray-900"}`}>{item.name}</Text>
        {item.is_available ? (
           <View className="ml-2 w-2 h-2 rounded-full bg-green-500" />
        ) : (
           <View className="ml-2 w-2 h-2 rounded-full bg-amber-500" />
        )}
      </View>
      <Text className={`text-sm font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>{item.phone_number}</Text>
      <Text className={`text-[10px] mt-1 font-sans-bold uppercase tracking-widest ${darkTheme ? "text-[#0ea5e9]" : "text-accentbg"}`}>
        {item.vehicle_type} • {item.plate_number}
      </Text>
      
      {/* Performance Stats */}
      <View className={`flex-row gap-4 mt-3 pt-3 border-t ${darkTheme ? "border-slate-800" : "border-slate-100"}`}>
        {item.rating != null && (
          <View className="flex-row items-center gap-1.5">
            <Ionicons name="star" size={14} color={BRAND.primary} />
            <Text className={`text-xs font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
              {ratingScore(item.rating)}
            </Text>
          </View>
        )}
        {item.total_deliveries != null && (
          <View className="flex-row items-center gap-1.5">
            <Ionicons name="cube-outline" size={14} color={BRAND.primary} />
            <Text className={`text-xs font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
              {item.total_deliveries || 0} trips
            </Text>
          </View>
        )}
        {item.distance_km != null && (
          <View className="flex-row items-center gap-1.5">
            <Ionicons name="navigate-outline" size={14} color={BRAND.primary} />
            <Text className={`text-xs font-sans-bold ${darkTheme ? "text-slate-300" : "text-slate-700"}`}>
              {item.distance_km?.toFixed(1)} km
            </Text>
          </View>
        )}
      </View>

      <View className="flex-row mt-4 gap-3">
         {item.status === "pending" && (
           <>
             <PressableScale disabled={actioningRider === item.deliverer_id} onPress={() => handleAction(item.deliverer_id, "reject")} className={`flex-1 py-3 rounded-[12px] border ${darkTheme ? "border-slate-700 bg-slate-800" : "border-slate-200 bg-white"} items-center`}>
               <Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-slate-700"}`}>{actioningRider === item.deliverer_id ? "..." : "Reject"}</Text>
             </PressableScale>
             <PressableScale disabled={actioningRider === item.deliverer_id} onPress={() => handleAction(item.deliverer_id, "approve")} className={`flex-1 py-3 rounded-[12px] ${actioningRider === item.deliverer_id ? "bg-accentbg/60" : "bg-accentbg"} items-center shadow-sm`}>
               <Text className="text-white font-sans-bold text-sm">{actioningRider === item.deliverer_id ? "..." : "Approve"}</Text>
             </PressableScale>
           </>
         )}
         {item.status === "approved" && (
             <PressableScale disabled={actioningRider === item.deliverer_id} onPress={() => handleAction(item.deliverer_id, "suspend")} className={`flex-1 py-3 rounded-[16px] ${actioningRider === item.deliverer_id ? "bg-amber-500/5" : "bg-amber-500/10"} border border-amber-500/20 items-center`}>
               <Text className="text-amber-500 font-sans-bold text-sm uppercase tracking-wider">{actioningRider === item.deliverer_id ? "..." : "Suspend Access"}</Text>
             </PressableScale>
         )}
         {item.status === "suspended" && (
             <PressableScale disabled={actioningRider === item.deliverer_id} onPress={() => handleAction(item.deliverer_id, "approve")} className={`flex-1 py-3 rounded-[16px] ${actioningRider === item.deliverer_id ? "bg-green-500/5" : "bg-green-500/10"} border border-green-500/20 items-center`}>
               <Text className="text-green-500 font-sans-bold text-sm uppercase tracking-wider">{actioningRider === item.deliverer_id ? "..." : "Restore Access"}</Text>
             </PressableScale>
         )}
      </View>
    </View>
  </View>
));

export default function RiderManagement() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { put } = useApiRequest();
  const router = useRouter();
  const { data: vendorProfile } = useVendorProfile();

  React.useEffect(() => {
      if (vendorProfile?.role === "staff") {
          Toast.error("Access Denied", "Staff members cannot access Rider Management.");
          router.replace("/(screens)");
      }
  }, [vendorProfile]);
  
  // One reader for the roster, shared with `OrderDetail`'s assign sheet. This
  // screen used to keep its own copy in `useState` and refetch it by hand.
  const [filter, setFilter] = useState("Pending");
  const [actioningRider, setActioningRider] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<"none" | "rating" | "trips">("none");
  const debouncedSearchQuery = useDebounce(searchQuery, 400);

  // The status chip, the search box and the two sort chips are all query
  // parameters now. They used to be a `.filter().filter().sort()` over the whole
  // roster held in memory — which the endpoint returned unbounded and unordered,
  // and whose rows carried neither `rating` nor `total_deliveries`, so both sort
  // chips compared `undefined` and did nothing.
  const ridersQuery = useVendorRiders({
    status: filter,
    search: debouncedSearchQuery,
    sort: sortBy === "none" ? "recent" : sortBy,
  });
  const {
    isLoading: initialLoading,
    isRefetching: refreshing,
    isFetchingNextPage,
    hasNextPage,
    refetch: fetchRiders,
  } = ridersQuery;

  const riders = riderRows(ridersQuery.data);
  const filteredRiders = riders;

  const onRefresh = useCallback(async () => {
    await fetchRiders();
  }, [fetchRiders]);

  const handleAction = useCallback(async (delivererId: string, action: string) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (actioningRider === delivererId) return;
    const rider = riders.find(r => r.deliverer_id === delivererId);
    const riderName = rider?.name || `Rider #${delivererId.substring(0, 8)}`;
    const actionMessages: Record<string, { title: string; message: string }> = {
      approve: { title: "Approve Rider", message: `Approve ${riderName} to start delivering for your store?` },
      reject: { title: "Reject Rider", message: `Reject ${riderName}'s request? They will need to re-apply.` },
      suspend: { title: "Suspend Rider", message: `Suspend ${riderName}'s access? They won't be able to receive new orders.` },
    };
    const msg = actionMessages[action] || { title: `Confirm ${action}`, message: `Are you sure you want to ${action} this rider?` };
    Popup.show({
      title: msg.title,
      message: msg.message,
      cancelText: "Cancel",
      confirmText: action === "reject" || action === "suspend" ? `Yes, ${action}` : "Confirm",
      isDestructive: action === "reject" || action === "suspend",
      onConfirm: async () => {
          Popup.hide();
          setActioningRider(delivererId);
          try {
            await put(VendorApiRoutes.ManageRider.path, { deliverer_id: delivererId, action });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            Toast.success("Success", `${riderName} has been ${action === "approve" ? "approved" : action === "reject" ? "rejected" : "suspended"}.`);
            fetchRiders();
          } catch (e) {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
            // This route is owner-only on the server now; a staff member who
            // reaches it gets `owner_only` with a sentence saying so, which
            // "Action failed. Please try again." would have hidden behind an
            // instruction to retry something that can never succeed.
            Toast.error("Error", errorMessage(e, "That action didn\'t go through."));
          } finally {
            setActioningRider(null);
          }
        }
    });
  }, [actioningRider, put, riders, fetchRiders]);

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
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
            <View>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>Fleet Management</Text>
                <Text className={`text-xs font-sans-semibold mt-0.5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Manage your assigned riders</Text>
            </View>
        </View>
      </View>

      {/* Search Bar */}
      <View className="px-5 pt-2 pb-3">
        <View className={`flex-row items-center px-4 h-[48px] rounded-2xl border ${darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-200"}`}>
          <Ionicons name="search" size={18} color={darkTheme ? "#64748b" : "#9ca3af"} />
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="Search riders by name or phone..."
            placeholderTextColor={darkTheme ? "#64748b" : "#9ca3af"}
            className={`flex-1 ml-3 text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
          />
          {searchQuery.length > 0 && (
            <PressableScale accessibilityLabel="Clear the search" onPress={() => { setSearchQuery(""); Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); }}>
              <Ionicons name="close-circle" size={18} color={darkTheme ? "#64748b" : "#9ca3af"} />
            </PressableScale>
          )}
        </View>
      </View>

      {/* Filter Chips + Sort Toggles */}
      <View className="flex-row px-5 py-3 gap-2 flex-wrap">
        {["Pending", "Approved", "Suspended"].map(f => (
          <PressableScale
            key={f}
            onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                setFilter(f);
            }}
            className={`px-5 py-2.5 rounded-full border ${filter === f ? "bg-accentbg border-accentbg" : darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100 shadow-sm"}`}
          >
            <Text className={`font-sans-bold ${filter === f ? "text-white" : darkTheme ? "text-slate-300" : "text-slate-600"}`}>{f}</Text>
          </PressableScale>
        ))}
        <View className="flex-1" />
        <PressableScale
          onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); setSortBy(sortBy === "rating" ? "none" : "rating"); }}
          className={`px-3.5 py-2.5 rounded-full border flex-row items-center gap-1.5 ${sortBy === "rating" ? "bg-accentbg/10 border-accentbg" : darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}
        >
          <Ionicons name="star" size={12} color={sortBy === "rating" ? BRAND.primary : (darkTheme ? "#94a3b8" : "#64748b")} />
          <Text className={`text-xs font-sans-bold ${sortBy === "rating" ? "text-accentbg" : darkTheme ? "text-slate-400" : "text-slate-500"}`}>Rating</Text>
        </PressableScale>
        <PressableScale
          onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); setSortBy(sortBy === "trips" ? "none" : "trips"); }}
          className={`px-3.5 py-2.5 rounded-full border flex-row items-center gap-1.5 ${sortBy === "trips" ? "bg-accentbg/10 border-accentbg" : darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}
        >
          <Ionicons name="cube-outline" size={12} color={sortBy === "trips" ? BRAND.primary : (darkTheme ? "#94a3b8" : "#64748b")} />
          <Text className={`text-xs font-sans-bold ${sortBy === "trips" ? "text-accentbg" : darkTheme ? "text-slate-400" : "text-slate-500"}`}>Trips</Text>
        </PressableScale>
      </View>

      {/* List */}
      <View style={{ flex: 1 }}>
        <FlashList
          data={filteredRiders}
          // Never `|| Math.random()`: a fresh key on every render makes React
          // throw the row away and rebuild it, on the list this screen scrolls.
          keyExtractor={(item: any) => item.registry_id}
          // @ts-ignore
          contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 120 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={darkTheme ? "white" : "black"} />}
          onEndReached={keepPaging(ridersQuery)}
          onEndReachedThreshold={0.5}
          ListFooterComponent={
            isFetchingNextPage ? (
              <Skeleton width="100%" height={180} borderRadius={24} />
            ) : !hasNextPage && filteredRiders.length > 0 ? (
              <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                That's everyone.
              </Text>
            ) : null
          }
          ListEmptyComponent={
            initialLoading ? (
              <View className="pt-2 gap-4">
                 {[...Array(4)].map((_, i) => (
                    <Skeleton key={i} width="100%" height={180} borderRadius={24} />
                 ))}
              </View>
            ) : (
              <View className="mt-16">
                <EmptyState
                  mood="sad"
                  title={debouncedSearchQuery.trim() ? "No Matching Riders" : `No ${filter.toLowerCase()} riders`}
                  subtitle={
                    debouncedSearchQuery.trim()
                      ? `No ${filter.toLowerCase()} rider matches "${debouncedSearchQuery.trim()}". The search covers your whole roster.`
                      : "When a rider requests to join your fleet, they will appear here."
                  } 
                />
              </View>
            )
          }
          renderItem={({ item }) => (
            <RiderCard 
              item={item} 
              darkTheme={darkTheme} 
              actioningRider={actioningRider} 
              handleAction={handleAction} 
            />
          )}
        />
      </View>
    </SafeAreaView>
  );
}
