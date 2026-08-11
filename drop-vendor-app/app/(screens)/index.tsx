import { UIThemeContext } from "@/context/ThemeContext";
import { useDashboard } from "@/hooks/queries/useDashboard";
import { useVendorOrders } from "@/hooks/queries/useVendorOrders";
import { useRouter } from "expo-router";
import { useCallback, useContext, useRef } from "react";
import { useVendorProfile, useUpdateVendorProfile } from "@/hooks/queries/useVendorProfile";
import {
    RefreshControl,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { useUnreadNotificationCount } from "@/hooks/queries/useNotifications";
import UserAvatar from "@/components/ui/UserAvatar";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";

// Refactored components
import StatCard from "@/components/dashboard/StatCard";
import WeeklyRevenueChart from "@/components/dashboard/WeeklyRevenueChart";
import QuickActions from "@/components/dashboard/QuickActions";
import RecentOrdersFeed from "@/components/dashboard/RecentOrdersFeed";
import SwipeToGoOnline from "@/components/ui/SwipeToGoOnline";
import StoreSwitcherSheet, { type StoreSwitcherSheetRef } from "@/components/dashboard/StoreSwitcherSheet";
import LowStockCard from "@/components/dashboard/LowStockCard";
import StorePauseCard from "@/components/dashboard/StorePauseCard";
import { useActiveStore } from "@/stores/activeStoreStore";

export default function Dashboard() {
  const router = useRouter();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { data: dashboard, isLoading, isError, refetch, isRefetching } = useDashboard();
  const { data: unreadData } = useUnreadNotificationCount();
  const { data: ordersData, isLoading: isLoadingOrders } = useVendorOrders();
  const { data: vendorProfileData } = useVendorProfile();
  const updateProfile = useUpdateVendorProfile();
  
  const isOnline = vendorProfileData?.is_online ?? dashboard?.is_online ?? true;
  // The open/closed swipe is owner-only on the server. Absent while the profile
  // loads means *not* staff, so an owner on a slow connection still gets their
  // control — this decides whether to show a button, not whether to permit
  // anything, and the server refuses regardless.
  const isStaff = vendorProfileData?.role === "staff";
  const isToggling = updateProfile.isPending;

  // Store switcher. The selection lives in a persisted store rather than in
  // `useState` here, because the API client reads it to set `X-Store-Id` on
  // every request — which is what makes switching actually switch anything.
  // Previously this held the id locally beside the comment
  // `// Future: refetch dashboard with new store context`, so choosing a store
  // moved a highlight and refetched exactly the same store's data.
  const storeSwitcherRef = useRef<StoreSwitcherSheetRef>(null);
  const activeStoreId = useActiveStore((s) => s.activeStoreId);
  const setActiveStore = useActiveStore((s) => s.setActiveStore);

  const handleSelectStore = useCallback((storeId: string) => {
    if (storeId === activeStoreId) return;
    // `useStoreScopedCache` empties the query cache off the back of this, so
    // every screen refetches against the store just chosen.
    setActiveStore(storeId);
  }, [activeStoreId, setActiveStore]);

  const toggleStoreStatus = async (newValue: boolean) => {
    try {
      await updateProfile.mutateAsync({ is_online: newValue });
    } catch (error) {
      if (__DEV__) console.error("Failed to toggle store status", error);
      throw error; // Let SwipeToGoOnline catch it to revert UI
    }
  };

  const unreadCount = unreadData?.unread_count || 0;
  const recentOrders = (ordersData || []).slice(0, 3);

  const onRefresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  if (isError) {
    return (
      <SafeAreaView className={`flex-1 justify-center items-center ${darkTheme ? "bg-black" : ""}`}>
        <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
        <Text className={`text-lg font-sans-bold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>Failed to load dashboard</Text>
        <PressableScale onPress={() => refetch()} className="bg-accentbg px-6 py-2 rounded-lg">
          <Text className="text-white font-sans-bold">Retry</Text>
        </PressableScale>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
      <StatusBar
        translucent
        backgroundColor={darkTheme ? "black" : "white"}
        barStyle={darkTheme ? "light-content" : "dark-content"}
      />
      
      {/* <--------------<<HEADER>>-----------------> */}
      <View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 20 }}>
        <View 
            className="flex-row justify-between items-center px-4 py-3 pb-4 mb-2"
            style={{ 
                backgroundColor: darkTheme ? "#000" : "#fff",
                borderBottomWidth: 1, 
                borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
            }}
        >
          {/* Store Switcher Pill — opens bottom sheet */}
          <PressableScale
            activeOpacity={0.7}
            onPress={() => storeSwitcherRef.current?.open()}
          >
            <View
              className={`flex-row items-center gap-2 p-2 px-3 rounded-full border ${darkTheme ? "bg-surface-variant border-transparent" : "bg-white border-gray-200"}`}
              style={darkTheme ? undefined : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
            >
              <Ionicons name="storefront" size={24} color={BRAND.primary} />
              <View className="flex-col justify-center">
                <View className="flex-row items-center gap-1">
                  <Text className={`text-xs font-sans-medium ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Active Store</Text>
                  <Ionicons name="chevron-down" size={16} color={BRAND.primary} />
                </View>
                <Text numberOfLines={1} className={`text-sm font-sans-bold max-w-[150px] ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                  {dashboard?.business_name || "Your Store"}
                </Text>
              </View>
            </View>
          </PressableScale>

          <View className="flex-row items-center gap-3">
            <PressableScale
              activeOpacity={0.6}
              onPress={() => router.push("/(screens)/Notifications")}
            >
              <View className="relative w-10 h-10 items-center justify-center">
                {unreadCount > 0 && (
                  <View className="absolute z-10 top-0 right-0 bg-red-500 items-center justify-center min-w-[18px] h-[18px] rounded-full px-1">
                    <Text className="text-white font-sans-bold text-[10px]">
                      {unreadCount > 99 ? "99+" : unreadCount}
                    </Text>
                  </View>
                )}
                <Ionicons name="notifications-outline" size={28} color={BRAND.primary} />
              </View>
            </PressableScale>

            <PressableScale
              activeOpacity={0.6}
              onPress={() => router.push("/(screens)/Profile")}
            >
              <View style={{ borderWidth: 2, borderColor: BRAND.primary, borderRadius: 999, padding: 2 }}>
                <UserAvatar
                  profilePicUrl={vendorProfileData?.profile_pic}
                  fullName={dashboard?.business_name || "Store"}
                  size={36}
                />
              </View>
            </PressableScale>
          </View>
        </View>
      </View>

      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={onRefresh} tintColor={darkTheme ? "white" : "black"} />}
        showsVerticalScrollIndicator={false}
      >
        
        {/* Toggle Store Status — owners only.
            `PUT /profile` is `get_owned_store`, so a staff member swiping this
            got `owner_only` every time: a full-width control on the busiest
            screen in the app that could not work for the person most likely to
            reach for it. Hiding it is the same decision the profile menu
            already makes about the owner-only screens — and the pause below is
            what that person actually needs. */}
        {!isStaff && (
          <View className="pt-2 px-2">
             <SwipeToGoOnline isOnline={isOnline} onToggle={toggleStoreStatus} isLoading={isToggling} />
          </View>
        )}

        {/* Pause — the timed sibling of the swipe above, and the one a staff
            member can actually use. The swipe writes `is_online` through
            `PUT /profile`, which is owner-only, so whoever is behind the
            counter when the 20 L bottles run out could not stop orders at all.
            This card renders nothing without `manage_orders`. */}
        <StorePauseCard />

        {/* If Offline, show warning */}
        {!isOnline && (
          <View className={`mx-5 mb-4 mt-2 p-4 rounded-2xl flex-row items-center gap-3 ${darkTheme ? "bg-yellow-500/10 border border-yellow-500/20" : "bg-yellow-50 border border-yellow-200"}`}>
            <Text style={{ fontSize: 22 }}>⚠️</Text>
            <View className="flex-1">
              <Text className={`font-sans-bold text-sm ${darkTheme ? "text-yellow-400" : "text-yellow-700"}`}>
                Your store is Closed
              </Text>
              <Text className={`text-xs mt-0.5 ${darkTheme ? "text-yellow-400/70" : "text-yellow-600"}`}>
                Swipe to open and receive new delivery requests.
              </Text>
            </View>
          </View>
        )}

        {/* Stats Grid - Horizontal Scroll */}
        <View className="mt-2">
          {isLoading ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16 }}>
              {Array(4).fill(0).map((_, i) => (
                <View
                  key={i}
                  className={`w-[140px] h-[130px] p-4 rounded-[20px] shadow-sm border mr-3 animate-pulse ${
                    darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"
                  }`}
                  style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
                />
              ))}
            </ScrollView>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16 }}>
              <StatCard title="Total Orders" value={dashboard?.total_orders || 0} icon="cube-outline" color={BRAND.primary} />
              <StatCard title="Pending" value={dashboard?.pending_orders || 0} icon="time-outline" color={BRAND.primary} />
              <StatCard
                title="Revenue"
                value={`KSH ${dashboard?.total_revenue?.toLocaleString() || 0}`}
                icon="cash-outline" color={BRAND.primary}
              />
              <StatCard title="Products" value={dashboard?.product_count || 0} icon="pricetags-outline" color={BRAND.primary} />
              <StatCard title="Rating" value={dashboard?.rating?.toFixed(1) || "0.0"} icon="star-outline" color={BRAND.primary} />
            </ScrollView>
          )}
        </View>

        {/* What needs restocking. Renders nothing when nothing does — a
            permanent "all good" card is noise the vendor learns to skip. */}
        <LowStockCard products={dashboard?.low_stock_products} />

        {/* Quick Actions */}
        <QuickActions />

        {/* Revenue Chart */}
        {isLoading ? (
          <View className={`mt-6 h-64 p-5 mx-4 rounded-[24px] border shadow-sm animate-pulse ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} />
        ) : (
          <WeeklyRevenueChart data={dashboard?.weekly_revenue} />
        )}

        {/* Recent Orders Feed */}
        <RecentOrdersFeed orders={recentOrders} isLoading={isLoadingOrders} />
      </ScrollView>

      {/* Store Switcher Bottom Sheet — must be inside BottomSheetModalProvider */}
      <StoreSwitcherSheet
        ref={storeSwitcherRef}
        activeStoreId={activeStoreId}
        onSelectStore={handleSelectStore}
      />
    </SafeAreaView>
  );
}
