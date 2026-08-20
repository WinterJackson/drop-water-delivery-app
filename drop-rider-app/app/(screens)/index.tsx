import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { useTabBarClearance } from '@/constants/layout';
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth, useUser } from "@clerk/clerk-expo";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import * as Location from "expo-location";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import React, { useCallback, useContext, useEffect, useRef, useState } from "react";
import { Toast } from "@/lib/toast";
import { useRiderProfile, useRiderEarnings, useRiderOrders, useTripRadar } from "@/hooks/queries/useRiderData";
import { useRiderStore } from "@/stores/useRiderStore";
import {
    RefreshControl,
    ScrollView,
    StatusBar,
    View,
    TouchableWithoutFeedback,
    Keyboard,
    Linking,
    Platform,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { PressableScale } from "@/components/ui/PressableScale";
import { useUnreadNotificationCount } from "@/hooks/queries/useNotifications";
import UserAvatar from "@/components/ui/UserAvatar";
import { Ionicons } from "@expo/vector-icons";
import { BRAND, TOAST } from "@/constants/brandColors";
import SwipeToGoOnline from "@/components/ui/SwipeToGoOnline";
import BentoStats from "@/components/dashboard/BentoStats";
import ActiveTripCard from "@/components/dashboard/ActiveTripCard";
import TripRadarList from "@/components/dashboard/TripRadarList";
import { Popup } from "@/lib/popup";
import { Skeleton } from "@/components/ui/Skeleton";

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const QuickActionCard = ({ title, subtitle, icon, route, darkTheme, router }: { title: string, subtitle: string, icon: keyof typeof Ionicons.glyphMap, route: string } & { darkTheme: boolean; router: ReturnType<typeof useRouter> }) => (
  <PressableScale
    activeOpacity={0.8}
    onPress={() => router.push(route as any)}
  >
    <View className={`p-4 rounded-2xl flex-row items-center border ${darkTheme ? "bg-surface-container border-gray-800" : "bg-white border-gray-200"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
      <View className={`p-3 rounded-full mr-3 ${darkTheme ? "bg-blue-900/40" : "bg-blue-50"}`}>
        <Ionicons name={icon} size={24} color={BRAND.primary} />
      </View>
      <View className="flex-1">
        <Text className={`font-sans-bold text-base ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>{title}</Text>
        <Text className={`text-xs mt-0.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>{subtitle}</Text>
      </View>
      <Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
    </View>
  </PressableScale>
);

export default function Dashboard() {
    const tabBarClearance = useTabBarClearance();
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { put } = useApiRequest();
  const router = useRouter();

  const { data: unreadData } = useUnreadNotificationCount();
  const unreadCount = unreadData?.unread_count || 0;

  const { data: profile, isLoading: isProfileLoading, refetch: refetchProfile } = useRiderProfile();
  const { user } = useUser();
  const { data: earnings, isLoading: isEarningsLoading, refetch: refetchEarnings } = useRiderEarnings();
  const { data: orders = [], refetch: refetchOrders } = useRiderOrders();
  const { data: radarOrders = [], isLoading: isRadarLoading, refetch: refetchRadar } = useTripRadar();

  const [isOnline, setIsOnline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [isToggling, setIsToggling] = useState(false);
  const [operationAddress, setOperationAddress] = useState<string>("Current Location");

  // Sync operation address from SecureStore or reverse-geocode
  useEffect(() => {
    (async () => {
      try {
        const saved = await SecureStore.getItemAsync("rider_operation_address");
        if (saved) {
          setOperationAddress(saved);
        } else if (profile?.operation_lat && profile?.operation_lng) {
          const geocoded = await Location.reverseGeocodeAsync({
            latitude: profile.operation_lat,
            longitude: profile.operation_lng
          });
          if (geocoded.length > 0) {
            const g = geocoded[0];
            const parts = [];
            if (g.street || g.name) parts.push(g.street || g.name);
            if (g.city || g.subregion) parts.push(g.city || g.subregion);
            const addr = parts.join(", ") || "Current Location";
            setOperationAddress(addr);
            await SecureStore.setItemAsync("rider_operation_address", addr);
          }
        }
      } catch (e) {
        // Fallback or ignore
      }
    })();
  }, [profile?.operation_lat, profile?.operation_lng]);

  // Sync online status and profile data to store
  useEffect(() => {
    if (profile) {
      if (profile.is_available !== isOnline) {
        setIsOnline(profile.is_available);
      }
      useRiderStore.setState({ 
        isOnline: profile.is_available,
        riderId: profile.id,
        riderProfile: profile
      });
    }
  }, [profile]);

  // Request location permission once on mount — riders need this immediately
  const locationPrompted = useRef(false);
  useEffect(() => {
    if (locationPrompted.current) return;
    locationPrompted.current = true;
    (async () => {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted" && __DEV__) {
        console.log("Location permission denied by rider.");
      }
    })();
  }, []);

  const toggleOnline = async (value: boolean) => {
    if (isToggling) return;
    setIsToggling(true);
    const previousState = isOnline;
    setIsOnline(value); // Optimistic immediate update
    useRiderStore.setState({ isOnline: value });
    await SecureStore.setItemAsync("rider_availability", String(value));

    try {
      if (value) {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === "granted") {
          
          // 1. Check if GPS is physically enabled
          const servicesEnabled = await Location.hasServicesEnabledAsync();
          if (!servicesEnabled) {
            if (Platform.OS === "android") {
              try {
                // Natively prompts the user to turn on GPS
                await Location.enableNetworkProviderAsync();
              } catch (e) {
                // Ignore prompt failure
              }
            }

            // Re-check if they actually turned it on
            const isNowEnabled = await Location.hasServicesEnabledAsync();
            if (!isNowEnabled) {
              Popup.show({
                title: "Location Required",
                message: "Your device's GPS is currently turned off. Please enable it to go online and receive delivery requests.",
                cancelText: "Cancel",
                confirmText: "Open Settings",
                onConfirm: () => { Popup.hide(); Linking.openSettings(); }
              });
              throw new Error("SERVICES_DISABLED");
            }
          }

          // 2. Fetch Coordinates
          let loc = null;
          try {
            // Use Balanced accuracy to avoid emulator timeouts
            loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
          } catch (locErr) {
            if (__DEV__) console.warn("getCurrentPositionAsync failed, trying getLastKnownPositionAsync...");
            try {
              loc = await Location.getLastKnownPositionAsync({});
            } catch (fallbackErr) {
              if (__DEV__) console.warn("getLastKnownPositionAsync also failed.");
            }
          }

          // 3. Handle Emulator / Dev Fallback
          if (!loc && __DEV__) {
            console.log("Injecting mock location for emulator testing.");
            loc = {
              coords: { latitude: -1.2921, longitude: 36.8219 }, // Nairobi
            } as any;
          }

          if (loc) {
            await put(RiderApiRoutes.UpdateLocation.path, {
              lat: loc.coords.latitude,
              lng: loc.coords.longitude,
            });
          } else {
            // Warn but don't crash if we couldn't get a coordinate despite GPS being on
            Toast.error("Location Warning", "Could not fetch your exact coordinates. Please ensure you have a clear view of the sky.");
          }
        } else {
          throw new Error("PERMISSION_DENIED");
        }
      }

      await put(RiderApiRoutes.ToggleAvailability.path, { is_available: value });

      // If going online, refetch radar immediately
      if (value) {
        refetchRadar();
      }
    } catch (e: unknown) {
      if (__DEV__) console.error(e);
      if ((e as Error).message === "PERMISSION_DENIED") {
        Toast.error("Permission Denied", "Please grant location permissions to go online.");
      } else if ((e as Error).message === "SERVICES_DISABLED") {
        // Do nothing, Alert is already shown
      } else if (e instanceof ApiError && e.status === 401) {
        // The client has already signed the rider out.
      } else {
        // The backend refuses with a reason — an unapproved KYC, a wallet in
        // arrears. "We couldn't toggle your availability" told the rider nothing
        // they could act on.
        Toast.error("Status Update Failed", errorMessage(e, "We couldn't toggle your availability."));
      }
      
      // Revert optimism
      setIsOnline(previousState);
      useRiderStore.setState({ isOnline: previousState });
      await SecureStore.setItemAsync("rider_availability", String(previousState));
    } finally {
      setIsToggling(false);
    }
  };

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([refetchProfile(), refetchEarnings(), refetchOrders(), refetchRadar()]);
    setRefreshing(false);
  }, [refetchProfile, refetchEarnings, refetchOrders, refetchRadar]);

  // Find the active order (if any)
  const activeOrder = orders.find(o => 
    !['delivered', 'cancelled', 'rejected'].includes(o.order_status)
  );

  const quickActionCardProps = { darkTheme, router };

  return (
    <>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
      <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
        <SafeAreaView className={`flex-1 h-full ${darkTheme ? "bg-black" : ""}`}>
          
          {/* <--------------<<HEADER>-----------------> */}
          <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className="flex-row justify-between items-center px-4 py-3 pb-4 mb-2"
                style={{ 
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1, 
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                }}
            >
              <PressableScale
              activeOpacity={0.7}
              onPress={() => router.push("/(screens)/OperationBase" as any)}
            >
              <View 
                className={`flex-row items-center gap-2 p-2 px-3 rounded-full border ${darkTheme ? "bg-surface-variant border-transparent" : "bg-white border-gray-200"}`}
                style={darkTheme ? undefined : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
              >
                <Ionicons name="location" size={24} color={BRAND.primary} />
                <View className="flex-col justify-center">
                  <View className="flex-row items-center gap-1">
                    <Text className={`text-xs font-sans-medium ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Working Zone</Text>
                  </View>
                  <Text numberOfLines={1} className={`text-sm font-sans-bold max-w-[150px] ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                    {operationAddress}
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
                onPress={() => router.push("/(screens)/SettingsMain")}
              >
                <View style={{ borderWidth: 2, borderColor: BRAND.primary, borderRadius: 999, padding: 2 }}>
                  <UserAvatar
                    profilePicUrl={profile?.profile_pic || user?.imageUrl}
                    fullName={profile?.name || user?.fullName || "Rider"}
                    size={36}
                  />
                </View>
              </PressableScale>
            </View>
          </View>
        </View>

          <ScrollView 
            contentContainerStyle={{ paddingBottom: tabBarClearance }} 
            className="flex-1" 
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={darkTheme ? "#fff" : "#000"} />}
          >
            {/* Status Toggle - Only for Operational Riders */}
            {isProfileLoading ? (
              <View className={`mx-5 mb-4 mt-2 border rounded-2xl ${darkTheme ? "border-gray-800" : "border-gray-200"}`} style={{ height: 100, overflow: 'hidden' }}>
                <Skeleton width="100%" height={100} borderRadius={16} />
              </View>
            ) : profile?.employer_vendor_id ? (
              <SwipeToGoOnline isOnline={isOnline} onToggle={toggleOnline} isLoading={isToggling} />
            ) : (
              <View className={`mx-5 mb-4 mt-2 p-5 rounded-2xl border ${darkTheme ? "bg-[#1A1A1A] border-gray-800" : "bg-white border-gray-200"}`}>
                <Text className={`font-sans-bold text-lg mb-1 ${darkTheme ? "text-white" : "text-black"}`}>Vendor Required</Text>
                <Text className={`text-sm mb-4 ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
                  To receive deliveries, you must apply and be accepted by a water vendor in your zone.
                </Text>
                <PressableScale onPress={() => router.push("/(screens)/DiscoverVendors")} className="bg-primary py-3 rounded-xl items-center">
                  <Text className="text-white font-sans-bold text-base">Find a Vendor</Text>
                </PressableScale>
              </View>
            )}

            {/* If Offline, show warning */}
            {profile?.employer_vendor_id && !isOnline && (
              <View className={`mx-5 mb-2 mt-2 p-4 rounded-2xl flex-row items-center gap-3 ${darkTheme ? "bg-yellow-500/10 border border-yellow-500/20" : "bg-yellow-50 border border-yellow-200"}`}>
                <Text style={{ fontSize: 22 }}>⚠️</Text>
                <View className="flex-1">
                  <Text className={`font-sans-bold text-sm ${darkTheme ? "text-yellow-400" : "text-yellow-700"}`}>
                    You are Offline
                  </Text>
                  <Text className={`text-xs mt-0.5 ${darkTheme ? "text-yellow-400/70" : "text-yellow-600"}`}>
                    Swipe to go online to receive new delivery requests.
                  </Text>
                </View>
              </View>
            )}

            {/* Active Delivery Card */}
            {activeOrder && <ActiveTripCard order={activeOrder} />}

            {/* Trip Radar (only show if online, operational, and no active trip) */}
            {profile?.employer_vendor_id && isOnline && !activeOrder && <TripRadarList orders={radarOrders} isLoading={isRadarLoading} />}

            {/* Analytics Grid */}
            <BentoStats earnings={earnings} profile={profile} />

            {/* Quick Actions */}
            <View className="px-5 mt-4">
              <Text className={`font-sans-bold text-lg mb-3 ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Quick Actions</Text>
              <View className="gap-3">
                <QuickActionCard {...quickActionCardProps} title="Discover Vendors" subtitle="Find water distribution points" icon="business-outline" route="/(screens)/DiscoverVendors" />
                <QuickActionCard {...quickActionCardProps} title="Withdraw Earnings" subtitle="Transfer funds directly to M-Pesa" icon="cash-outline" route="/(screens)/Cashout" />

                <QuickActionCard {...quickActionCardProps} title="My Deliveries" subtitle="View your past delivery history" icon="bicycle-outline" route="/(screens)/EarningsHistory" />
                <QuickActionCard {...quickActionCardProps} title="My Performance" subtitle="View stats and gamification progress" icon="stats-chart-outline" route="/(screens)/Performance" />
              </View>
            </View>

          </ScrollView>
        </SafeAreaView>
      </TouchableWithoutFeedback>
    </>
  );
}
