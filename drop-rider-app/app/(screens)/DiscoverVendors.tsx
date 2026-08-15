import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import React, { useContext, useEffect, useState, useCallback, useRef } from "react";
import { View, StatusBar, FlatList, RefreshControl, Image, Switch, Platform, TouchableOpacity } from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useRouter } from "expo-router";
import PressableScale from "@/components/ui/PressableScale";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import * as Location from "expo-location";
import { Toast } from "@/lib/toast";
import { useRiderStore } from "@/stores/useRiderStore";
import { useRiderProfile } from "@/hooks/queries/useRiderData";
import { BRAND } from "@/constants/brandColors";
import { FlashList } from "@shopify/flash-list";
import { Ionicons } from "@expo/vector-icons";
import { RiderDiscoverVendorCardSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { darkMapStyle, standardMapStyle } from "@/constants/mapStyles";
import { trackEvent } from "@/utils/analytics";
import { Popup } from "@/lib/popup";
import { useDebounce } from "@/hooks/useDebounce";

/**
 * One row of `GET /api/rider/discover-vendors`.
 *
 * `registration_max_km` is the limit the *server* will enforce when this rider
 * applies, for this store's type. The screen used to compare every row against
 * a literal `2.0`, so a wholesale depot 10 km away — which the server would have
 * accepted at 15 km — was shown as "Too Far". A refusal invented on the handset
 * for a rule the platform does not have.
 */
export interface DiscoveredVendor {
    id: string;
    business_name: string;
    address: string | null;
    profile_pic: string | null;
    distance_km: number;
    /** `vendor_rider_model.status`, plus the `unregistered` the listing synthesises. */
    status: "unregistered" | "pending" | "approved" | "rejected" | "suspended";
    lat: number | null;
    lng: number | null;
    vendor_type: string | null;
    registration_max_km: number;
}

import type MapViewType from 'react-native-maps';
import type {
    LatLng,
    MapMarkerProps,
    MapUrlTileProps,
    MapViewProps,
    Provider,
} from 'react-native-maps';

/** Driven by ref (`getCamera`, `animateToRegion`), so `ref` is part of the props. */
let MapView: React.ComponentType<MapViewProps & { ref?: React.Ref<MapViewType> }>;
let Marker: React.ComponentType<MapMarkerProps>;
let UrlTile: React.ComponentType<MapUrlTileProps>;
let PROVIDER_GOOGLE: Provider;

if (Platform.OS !== 'web') {
    const maps = require('react-native-maps');
    MapView = maps.default;
    Marker = maps.Marker;
    UrlTile = maps.UrlTile;
    PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
} else {
    MapView = ({ style, children }: MapViewProps) => <View style={style}>{children}</View>;
    Marker = () => null;
    UrlTile = () => null;
    PROVIDER_GOOGLE = 'google';
}

export default function DiscoverVendors() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";

  const { get, post } = useApiRequest();
  const router = useRouter();
  const { data: profile, isLoading: isProfileLoading } = useRiderProfile();
  
  const [vendors, setVendors] = useState<DiscoveredVendor[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingLoc, setLoadingLoc] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [isMapView, setIsMapView] = useState(false);
  const [userLocation, setUserLocation] = useState<LatLng | null>(null);
  const mapRef = useRef<MapViewType | null>(null);
  
  const handleZoom = async (zoomIn: boolean) => {
    if (!mapRef.current || Platform.OS === 'web') return;
    try {
      const camera = await mapRef.current.getCamera();
      mapRef.current.animateCamera({
        ...camera,
        zoom: Math.max(1, Math.min(20, (camera.zoom || 15) + (zoomIn ? 1 : -1))),
      }, { duration: 250 });
    } catch {}
  };

  const snapToCurrentLocation = async () => {
    try {
      const location = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setUserLocation(location.coords);
      if (mapRef.current) {
        mapRef.current.animateToRegion({
          latitude: location.coords.latitude,
          longitude: location.coords.longitude,
          latitudeDelta: 0.05,
          longitudeDelta: 0.05,
        });
      }
    } catch (e) {
      Toast.error("Location Error", "Could not get your current location.");
    }
  };
  
  const { mutedVendors, toggleVendorMute } = useRiderStore();

  const debouncedSearchQuery = useDebounce(searchQuery, 500);

  const activeVendorCount = vendors.filter((v) => v.status === "pending" || v.status === "approved").length;

  /**
   * Which search this component is currently showing.
   *
   * Two searches in flight can finish in either order — a short term over a slow
   * cell and a longer one over a good one — and the staler response wins simply
   * by landing last, leaving a list that does not match the box above it. Every
   * response is checked against the term current when it arrives; a stale one is
   * dropped rather than rendered.
   */
  const inFlightFor = useRef<string>("");

  const fetchVendors = async (lat: number, lng: number, search?: string) => {
    const term = search ?? "";
    inFlightFor.current = term;
    try {
      const rows = await get<DiscoveredVendor[]>(RiderApiRoutes.DiscoverVendors(lat, lng, search).path);
      if (inFlightFor.current !== term) return;
      setVendors(rows);
    } catch (e) {
      if (inFlightFor.current !== term) return;
      if (e instanceof ApiError && e.status === 401) return;
      Toast.error("Error", errorMessage(e, "Could not load nearby vendors. Pull to refresh to try again."));
    }
  };

  const initData = async () => {
    try {
      if (profile?.operation_lat && profile?.operation_lng) {
        setUserLocation({ latitude: profile.operation_lat, longitude: profile.operation_lng });
        await fetchVendors(profile.operation_lat, profile.operation_lng, debouncedSearchQuery);
        return;
      }

      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        Toast.error("Permission Denied", "Location is required to find nearby vendors");
        setLoadingLoc(false);
        return;
      }
      const location = await Location.getCurrentPositionAsync({});
      setUserLocation(location.coords);
      await fetchVendors(location.coords.latitude, location.coords.longitude, debouncedSearchQuery);
    } catch (e) {
       // fallback generic coordinates if location fails
       await fetchVendors(-1.2921, 36.8219, debouncedSearchQuery);
    } finally {
       setLoadingLoc(false);
    }
  };

  useEffect(() => {
    if (!isProfileLoading) {
      initData();
    }
  }, [isProfileLoading]);

  useEffect(() => {
    if (userLocation) {
        fetchVendors(userLocation.latitude, userLocation.longitude, debouncedSearchQuery);
    }
  }, [debouncedSearchQuery]);

  useEffect(() => {
    if (debouncedSearchQuery.trim().length > 1) {
      trackEvent('rider_discover_search', { query: debouncedSearchQuery.trim() });
    }
  }, [debouncedSearchQuery]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await initData();
    setRefreshing(false);
  }, []);

  const handleApply = async (vendorId: string) => {
    Popup.show({
      title: "Register to Vendor",
      message: "You can register to up to 10 vendors. Are you sure you want to apply to this one?",
      cancelText: "Cancel",
      confirmText: "Apply",
      onConfirm: async () => {
          Popup.hide();
          try {
            await post(RiderApiRoutes.ApplyVendor.path, { vendor_id: vendorId });
            Toast.success("Applied", "Your registration is now pending approval.");
            // Optimistic UI Update
            setVendors(prev => prev.map(v => v.id === vendorId ? { ...v, status: "pending" } : v));
          } catch (e) {
            // The backend refuses past ten vendors, and for a vendor the rider
            // already applied to, each with its own sentence.
            Toast.error("Error", errorMessage(e, "Application failed"));
          }
        }
    });
  };

  const renderVendorCard = ({ item }: { item: DiscoveredVendor }) => (
    <View className={`p-4 mb-4 rounded-2xl flex-row items-center ${darkTheme ? "bg-white/5" : "bg-white"}`}>
      <View className="w-14 h-14 rounded-full bg-accentbg/10 mr-4 overflow-hidden border border-accentbg/20">
        {item.profile_pic ? (
          <Image source={{ uri: item.profile_pic }} className="w-full h-full" />
        ) : (
          <View className="flex-1 items-center justify-center">
            <Ionicons name="business-outline" size={24} color={BRAND.primary} />
          </View>
        )}
      </View>
      <View className="flex-1">
        <View className="flex-row items-center justify-between">
          <Text className={`font-sans-bold text-lg flex-1 ${darkTheme ? "text-white" : "text-gray-900"}`}>{item.business_name}</Text>
          <Text className={`text-xs ml-2 font-sans-bold ${darkTheme ? "text-accentbg" : "text-accentbg"}`}>{item.distance_km} KM</Text>
        </View>
        <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{item.address}</Text>
        
         <View className="flex-row mt-3">
            {item.status === "unregistered" && (
              <>
                {item.distance_km > item.registration_max_km ? (
                  <View className="flex-1 py-2.5 rounded-lg bg-gray-500/10 border border-gray-500/20 items-center">
                    <Text className="text-gray-500 font-sans-semibold text-sm">Too Far ({item.distance_km} KM)</Text>
                  </View>
                ) : activeVendorCount >= 10 ? (
                 <View className="flex-1 py-2.5 rounded-lg bg-gray-500/10 border border-gray-500/20 items-center">
                   <Text className="text-gray-500 font-sans-semibold text-sm">Max 10 Vendors Reached</Text>
                 </View>
               ) : (
                 <PressableScale onPress={() => handleApply(item.id)} className="flex-1 py-2.5 rounded-lg bg-accentbg items-center">
                   <Text className="text-white font-sans-semibold text-sm">Apply</Text>
                 </PressableScale>
               )}
             </>
           )}
           {item.status === "pending" && (
             <View className="flex-1 py-2.5 rounded-lg bg-orange-500/10 border border-orange-500/20 items-center">
               <Text className="text-orange-500 font-sans-semibold text-sm">Pending Approval</Text>
             </View>
           )}
           {item.status === "approved" && (() => {
             const isMuted = mutedVendors.includes(item.id);
             return (
               <View className="flex-1 py-1.5 px-3 rounded-lg bg-green-500/10 border border-green-500/20 flex-row justify-between items-center">
                 <Text className="text-green-600 font-sans-semibold text-xs flex-1">
                   {isMuted ? "Muted Locally" : "Receiving Orders"}
                 </Text>
                 <Switch
                    value={!isMuted} // On means receiving orders (not muted)
                    onValueChange={() => toggleVendorMute(item.id)}
                    trackColor={{ false: darkTheme ? "#333" : "#ddd", true: BRAND.gold }}
                    thumbColor="#fff"
                 />
               </View>
             );
           })()}
           {item.status === "suspended" && (
             <View className="flex-1 py-2.5 rounded-lg bg-red-500/10 border border-red-500/20 items-center">
               <Text className="text-red-500 font-sans-semibold text-sm">Suspended by Vendor</Text>
             </View>
           )}
        </View>
      </View>
    </View>
  );

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
              <TouchableOpacity onPress={() => router.back()} className="mr-4">
                  <BackButtonMinimal />
              </TouchableOpacity>
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                  Discover Vendors
              </Text>
          </View>
      </View>

      {/* Tools & Search */}
      <View className="px-5 pt-2 pb-4">
        <View className="flex-row justify-between items-start">
          <View className="flex-1">
            <Text className={`text-sm mt-1 mb-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Find and apply to up to 10 nearby water vendors.</Text>
          </View>
          <PressableScale accessibilityLabel={isMapView ? "Show these vendors as a list" : "Show these vendors on a map"}
            onPress={() => setIsMapView(!isMapView)}
            className={`w-12 h-12 rounded-full items-center justify-center border ${darkTheme ? "bg-white/10 border-white/20" : "bg-white border-gray-200"}`}
          >
            <Ionicons name={isMapView ? "list-outline" : "map-outline"} size={24} color={BRAND.primary} />
          </PressableScale>
        </View>
        
        {/* Search Bar */}
        <View className={`flex-row items-center px-4 py-3 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
            <Ionicons name="search" size={20} color={BRAND.primary} />
            <TextInput
                value={searchQuery}
                onChangeText={setSearchQuery}
                placeholder="Search by store name..."
                placeholderTextColor={darkTheme ? "#9ca3af" : "#6b7280"}
                className={`flex-1 font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}
            />
        </View>
      </View>

      {/* Content */}
      <View style={{ flex: 1 }}>
        {isMapView ? (
          <View className="flex-1">
            {MapView && (
              <>
              <MapView
                ref={mapRef}
                style={{ flex: 1 }}
                // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                // 🟢 FREE OPEN SOURCE MVP MODE (CartoDB / OSM tiles)
                //    Uses provider={undefined} + UrlTile overlay
                // provider={undefined}
                // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                // 🔴 PRODUCTION GOOGLE MAPS MODE
                //    Swap the line above for this one:
                provider={PROVIDER_GOOGLE}
                // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                // the prop every map screen in all three apps passed was dropped and cloud
                // styling has never once been applied. A misspelt prop is silent here.
                googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                zoomControlEnabled={false}
                showsUserLocation={true}
                showsMyLocationButton={false}
                pitchEnabled={true}
                showsCompass={true}
                initialRegion={userLocation ? {
                  latitude: userLocation.latitude,
                  longitude: userLocation.longitude,
                  latitudeDelta: 0.05,
                  longitudeDelta: 0.05,
                } : {
                  latitude: -1.2921,
                  longitude: 36.8219,
                  latitudeDelta: 0.05,
                  longitudeDelta: 0.05,
                }}
              >
                {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
                {/* 🟢 OSM TILE OVERLAY (Remove this block when using Google Maps) */}
                {/* {UrlTile && <UrlTile urlTemplate={darkTheme ? "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png" : "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"} maximumZ={20} />} */}
                {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
                {vendors.map((vendor) => (
                  <Marker
                    key={vendor.id}
                    coordinate={{ latitude: Number(vendor.lat), longitude: Number(vendor.lng) }}
                    title={vendor.business_name}
                    description={`${vendor.distance_km} KM away`}
                    pinColor={vendor.status === 'approved' ? '#10b981' : vendor.status === 'pending' ? '#f59e0b' : '#0295f7'}
                  />
                ))}
              </MapView>
              <View className="absolute top-4 right-4 pointer-events-auto flex-row gap-2">
                <PressableScale
                  onPress={snapToCurrentLocation}
                  className={`w-10 h-10 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-surface-variant border-outline-variant" : "bg-white border-gray-200"}`}
                  style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
                >
                  <View className={`w-4 h-4 rounded-full border-2 ${darkTheme ? "border-white" : "border-gray-800"}`} />
                </PressableScale>
                <PressableScale
                  onPress={() => handleZoom(true)}
                  className={`w-10 h-10 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-surface-variant border-outline-variant" : "bg-white border-gray-200"}`}
                  style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
                >
                  <Text className={`text-xl font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>+</Text>
                </PressableScale>
                <PressableScale
                  onPress={() => handleZoom(false)}
                  className={`w-10 h-10 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-surface-variant border-outline-variant" : "bg-white border-gray-200"}`}
                  style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
                >
                  <Text className={`text-xl font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>−</Text>
                </PressableScale>
              </View>
              </>
            )}
          </View>
        ) : (
          <FlashList
            data={vendors}
            keyExtractor={(item: DiscoveredVendor) => item.id}
            renderItem={renderVendorCard}
            contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 16, paddingBottom: 120 }}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
            ListEmptyComponent={
              <View className="items-center justify-center pt-20">
                {loadingLoc ? (
                   <View className="w-full mt-[-20px]">
                       {[1, 2, 3, 4, 5].map(i => <RiderDiscoverVendorCardSkeleton key={i} />)}
                   </View>
                ) : (
                   <>
                     <Ionicons name="sad-outline" size={48} color={BRAND.primary} />
                     <Text className={`text-lg mt-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>No vendors found nearby.</Text>
                   </>
                )}
              </View>
            }
          />
        )}
      </View>
    </SafeAreaView>
  );
}
