import React, { useContext, useState, useEffect, useRef } from "react";
import { View, StatusBar, Platform, StyleSheet, Dimensions, Linking } from "react-native";
import { Text } from '@/components/ui/Text';
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { UIThemeContext } from "@/context/ThemeContext";
import { errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { PressableScale } from "@/components/ui/PressableScale";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import * as Location from "expo-location";
import { Toast } from "@/lib/toast";
import { BRAND } from "@/constants/brandColors";
import { darkMapStyle, standardMapStyle } from "@/constants/mapStyles";
import { useRouter } from "expo-router";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { RiderMapSkeleton } from "@/components/skeletons/ContextualSkeletons";
import PlacesAutocomplete from "@/components/map/PlacesAutocomplete";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Image } from "expo-image";
import * as SecureStore from "expo-secure-store";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";

import type { RiderProfile } from '@/hooks/queries/useRiderData';
import type { DiscoveredVendor } from '@/app/(screens)/DiscoverVendors';
import type MapViewType from 'react-native-maps';
import type {
    MapCircleProps,
    MapMarkerProps,
    MapPolygonProps,
    MapUrlTileProps,
    MapViewProps,
    Provider,
} from 'react-native-maps';

/** Driven by ref (`getCamera`, `animateCamera`), so `ref` is part of the props. */
let MapView: React.ComponentType<MapViewProps & { ref?: React.Ref<MapViewType> }>;
let Marker: React.ComponentType<MapMarkerProps>;
let Circle: React.ComponentType<MapCircleProps>;
let Polygon: React.ComponentType<MapPolygonProps>;
let UrlTile: React.ComponentType<MapUrlTileProps>;
let PROVIDER_GOOGLE: Provider;

if (Platform.OS !== 'web') {
  const maps = require('react-native-maps');
  MapView = maps.default;
  Marker = maps.Marker;
  Circle = maps.Circle;
  Polygon = maps.Polygon;
  UrlTile = maps.UrlTile;
  PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
} else {
  MapView = ({ style, children }: MapViewProps) => <View style={style}>{children}</View>;
  Marker = () => null;
  Circle = () => null;
  Polygon = () => null;
  UrlTile = () => null;
  PROVIDER_GOOGLE = 'google';
}

// Generate polygon points that approximate a circle on the map
// This is needed because the native Circle component renders BEHIND UrlTile on Android
function generateCirclePolygon(center: { latitude: number; longitude: number }, radiusKm: number, points: number = 72) {
  const coords = [];
  const earthRadius = 6371; // km
  for (let i = 0; i < points; i++) {
    const angle = (i * 360) / points;
    const radian = (angle * Math.PI) / 180;
    const lat = Math.asin(
      Math.sin((center.latitude * Math.PI) / 180) * Math.cos(radiusKm / earthRadius) +
      Math.cos((center.latitude * Math.PI) / 180) * Math.sin(radiusKm / earthRadius) * Math.cos(radian)
    );
    const lng =
      ((center.longitude * Math.PI) / 180) +
      Math.atan2(
        Math.sin(radian) * Math.sin(radiusKm / earthRadius) * Math.cos((center.latitude * Math.PI) / 180),
        Math.cos(radiusKm / earthRadius) - Math.sin((center.latitude * Math.PI) / 180) * Math.sin(lat)
      );
    coords.push({ latitude: (lat * 180) / Math.PI, longitude: (lng * 180) / Math.PI });
  }
  coords.push(coords[0]); // Close the polygon
  return coords;
}

// Haversine formula to calculate distance between two coordinates in kilometers
function getDistanceFromLatLonInKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 6371; // Radius of the earth in km
  const dLat = deg2rad(lat2 - lat1);
  const dLon = deg2rad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}
function deg2rad(deg: number) { return deg * (Math.PI / 180) }

export default function OperationBase() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  const { get, put } = useApiRequest();
  const router = useRouter();
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();
  const mapRef = useRef<MapViewType | null>(null);
  const { width, height } = Dimensions.get("window");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [physicalLocation, setPhysicalLocation] = useState<{ latitude: number, longitude: number } | null>(null);
  const [location, setLocation] = useState<{ latitude: number, longitude: number } | null>(null);
  const [liveAddress, setLiveAddress] = useState<string>("Locating...");
  const [zoneChanges, setZoneChanges] = useState<number>(0);
  const [riderId, setRiderId] = useState<string>("");
  /**
   * Null until the profile answers. The circle and the sentence below both read
   * it, so neither states a range before the server has given one — a figure
   * this screen guesses is exactly the defect being fixed here.
   */
  const [operationRadiusKm, setOperationRadiusKm] = useState<number | null>(null);

  /**
   * A map span that fits the whole circle with a margin, whatever the radius.
   *
   * This was a hardcoded `0.045` "tuned to always show the full 2KM radius
   * circle" — roughly 5 km of latitude, so at 2.5 km the circle would have
   * touched both edges, and any further widening on the console would have
   * cropped it with nothing to say why. One degree of latitude is ~111 km.
   */
  const mapDelta = ((operationRadiusKm ?? 2.5) * 2 * 1.3) / 111;

  /**
   * Load the rider's saved base and their remaining zone-change allowance.
   *
   * One definition, used by the initial load and the retry button — those were
   * two copies of the same twenty lines, and only one of them handled the
   * "never set a base" path.
   */
  const loadProfile = async () => {
    const data = await get<RiderProfile>(RiderApiRoutes.GetProfile.path);
    setZoneChanges(data.zone_changes_this_month || 0);
    setRiderId(data.id);
    // The radius dispatch actually searches, from the server. This screen used
    // to draw a hardcoded 2 km circle and promise "within a 2KM radius" in
    // words — a business figure written into an app, so moving
    // `retail_max_distance_km` on the console left the map and the promise a
    // kilometre short of the truth.
    if (data.operation_radius_km) setOperationRadiusKm(Number(data.operation_radius_km));
    if (data.operation_lat && data.operation_lng) {
      setLocation({ latitude: data.operation_lat, longitude: data.operation_lng });
      reverseGeocode(data.operation_lat, data.operation_lng);
    } else {
      await snapToCurrentLocation();
    }
  };

  // Fetch rider profile to get initial base and limit stats
  useEffect(() => {
    (async () => {
      try {
        await loadProfile();
      } catch (e) {
        setLocation({ latitude: -1.2921, longitude: 36.8219 });
        setLiveAddress("Nairobi, Kenya");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const snapToCurrentLocation = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        if (!location) {
          setLocation({ latitude: -1.2921, longitude: 36.8219 });
          setLiveAddress("Nairobi, Kenya");
        }
        Toast.error("Permission Denied", "Location permission is required to snap to your position.");
        return;
      }

      // Try last known position first (instant, no GPS required)
      let loc = await Location.getLastKnownPositionAsync();
      if (!loc) {
        // Fall back to active GPS fix
        loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      }

      setPhysicalLocation(loc.coords);
      if (!location) {
        setLocation(loc.coords);
        reverseGeocode(loc.coords.latitude, loc.coords.longitude);
      }
      if (mapRef.current) {
        mapRef.current.animateToRegion({
          latitude: loc.coords.latitude,
          longitude: loc.coords.longitude,
          latitudeDelta: mapDelta,
          longitudeDelta: mapDelta,
        });
      }
    } catch (e: unknown) {
      // Graceful fallback when location services are disabled (emulator, airplane mode, etc.)
      if (!location) {
        setLocation({ latitude: -1.2921, longitude: 36.8219 });
        setLiveAddress("Nairobi, Kenya");
      }
      Toast.error("Location Unavailable", "Could not get your current location. Drag the map manually to set your zone.");
    }
  };

  // Fetch vendors for map plotting
  const { data: vendors } = useQuery({
    queryKey: ['rider', 'discover_vendors', location?.latitude, location?.longitude],
    queryFn: async () => {
      if (!location) return [];
      // Plotting nearby vendors is decoration on this screen; failing to fetch
      // them must not blank the map the rider is choosing their base on.
      try {
        return await get<DiscoveredVendor[]>(
          RiderApiRoutes.DiscoverVendors(location.latitude, location.longitude).path
        );
      } catch {
        return [];
      }
    },
    enabled: !!location,
  });

  const reverseGeocode = async (lat: number, lng: number) => {
    try {
      const results = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
      if (results.length > 0) {
        const g = results[0];
        const parts: string[] = [];
        if (g.name && g.name !== g.street) parts.push(g.name);
        if (g.street) parts.push(g.street);
        if (g.district) parts.push(g.district);
        if (g.city) parts.push(g.city);
        if (parts.length === 0) {
          if (g.region) parts.push(g.region);
          if (g.country) parts.push(g.country);
        }
        setLiveAddress(parts.join(", ") || "Unknown Location");
      }
    } catch {
      setLiveAddress("Unknown Location");
    }
  };

  const handleSaveBase = async () => {
    if (!location) return;
    if (zoneChanges >= 2) {
      Linking.openURL(`mailto:support@drop.com?subject=Zone Change Request (Rider ${riderId})&body=I would like to request a zone change...`);
      return;
    }
    setSaving(true);
    try {
      await put(RiderApiRoutes.UpdateProfile.path, {
        operation_lat: location.latitude,
        operation_lng: location.longitude,
      });
      await SecureStore.setItemAsync("rider_operation_address", liveAddress);
      await queryClient.invalidateQueries({ queryKey: ["rider", "profile"] });
      Toast.success("Success", "Operation Base updated! You will now receive requests near this zone.");
      router.back();
    } catch (e) {
      // The backend refuses a third zone change in a month with a reason worth
      // reading — it is not a network error, which is what this used to say.
      Toast.error("Couldn't Save Base", errorMessage(e, "Failed to save your operation base."));
    } finally {
      setSaving(false);
    }
  };

  const handleZoom = (zoomIn: boolean) => {
    if (!mapRef.current || !location) return;
    mapRef.current.getCamera().then((cam) => {
      if (!cam) return;
      if (Platform.OS === 'ios') {
        cam.altitude = zoomIn ? (cam.altitude ?? 0) / 2 : (cam.altitude ?? 0) * 2;
      } else {
        cam.zoom = (cam.zoom ?? 0) + (zoomIn ? 1 : -1);
      }
      mapRef.current?.animateCamera(cam, { duration: 300 });
    });
  };

  const distanceToBase = physicalLocation && location ? getDistanceFromLatLonInKm(
    physicalLocation.latitude, physicalLocation.longitude,
    location.latitude, location.longitude
  ).toFixed(1) : null;

  if (!riderId && !loading) {
    return (
      <DataFallbackUI 
        title="Operation Data Unavailable"
        message="We couldn't load your rider profile. Please retry to set your base."
        onRetry={async () => {
          setLoading(true);
          try {
            await loadProfile();
          } catch (e) {
            if (__DEV__) console.warn("[OperationBase] retry failed:", errorMessage(e));
          } finally { setLoading(false); }
        }}
      />
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: darkTheme ? "#000" : "#fff" }}>
      <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />

      {/* FULL SCREEN MAP */}
      <View style={{ height: height * 0.55, width: width, position: 'absolute', top: 0 }}>
        {MapView && location && !loading ? (
          <MapView
            ref={mapRef}
            style={StyleSheet.absoluteFill}
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
            initialRegion={{
              latitude: location.latitude,
              longitude: location.longitude,
              latitudeDelta: mapDelta,
              longitudeDelta: mapDelta,
            }}
            onRegionChangeComplete={(region: import("@/types/models").MapRegion) => {
              setLocation({ latitude: region.latitude, longitude: region.longitude });
              reverseGeocode(region.latitude, region.longitude);
            }}
          >
            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            {/* 🟢 OSM TILE OVERLAY (Remove this block when using Google Maps) */}
            {/* {UrlTile && <UrlTile urlTemplate={darkTheme ? "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png" : "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"} maximumZ={20} />} */}
            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}

            {/* ══════════════════════════════════════════════════
                SHARED OVERLAYS — identical for both OSM & Google
                ══════════════════════════════════════════════════ */}

            {/* Operation radius — the server's figure, always visible */}
            {/* Uses Polygon instead of Circle so it renders ABOVE UrlTile on Android */}
            {Polygon && location && operationRadiusKm && (
              <Polygon
                coordinates={generateCirclePolygon(location, operationRadiusKm)}
                fillColor={BRAND.primary + "30"}
                strokeColor={BRAND.primary}
                strokeWidth={2.5}
              />
            )}
            {/* Native Circle kept as fallback for Google Maps production mode */}
            {/* When switching to Google Maps, you can use Circle instead:
            <Circle
              center={location}
              radius={(operationRadiusKm ?? 2.5) * 1000}
              fillColor={BRAND.primary + "30"}
              strokeColor={BRAND.primary}
              strokeWidth={2.5}
            />
            */}

            {/* Vendor Marker Plots */}
            {vendors?.map((v) => {
              if (typeof v.lat !== 'number' || typeof v.lng !== 'number' || isNaN(v.lat) || isNaN(v.lng)) return null;
              return Marker ? (
                <Marker
                  key={v.id}
                  coordinate={{ latitude: v.lat, longitude: v.lng }}
                  title={v.business_name || "Vendor"}
                >
                  <View style={{
                    width: 28,
                    height: 28,
                    borderRadius: 14,
                    backgroundColor: BRAND.primary,
                    borderWidth: 3,
                    borderColor: '#fff',
                    alignItems: 'center',
                    justifyContent: 'center',
                    elevation: 5,
                    shadowColor: '#000',
                    shadowOffset: { width: 0, height: 2 },
                    shadowOpacity: 0.3,
                    shadowRadius: 3,
                  }}>
                    <View style={{
                      width: 8,
                      height: 8,
                      borderRadius: 4,
                      backgroundColor: '#fff',
                    }} />
                  </View>
                </Marker>
              ) : null;
            })}
          </MapView>
        ) : (
          <RiderMapSkeleton />
        )}

        {/* Fixed target in center to help dragging visually */}
        <View className="absolute inset-0 items-center justify-center pointer-events-none pb-10">
          <View className="w-4 h-4 rounded-full bg-white items-center justify-center shadow-lg" style={{ ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
            <View className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: BRAND.primary }} />
          </View>
        </View>

        {/* MAP UI OVERLAYS */}
        {/* Back Button & Search */}
        <View style={{ top: insets.top + 10, paddingHorizontal: 16, zIndex: 50 }} className="absolute flex-row items-center w-full pointer-events-box-none">
          <PressableScale onPress={() => router.back()} className="mr-3 pointer-events-auto">
            <View className={`w-11 h-11 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}>
              <BackButtonMinimal />
            </View>
          </PressableScale>

          <View className="flex-1 pointer-events-auto">
            <PlacesAutocomplete
              placeholder="Search location..."
              darkTheme={darkTheme}
              onPress={(data, details) => {
                if (details?.geometry?.location && mapRef.current) {
                  mapRef.current.animateToRegion({
                    latitude: details.geometry.location.lat,
                    longitude: details.geometry.location.lng,
                    latitudeDelta: mapDelta,
                    longitudeDelta: mapDelta,
                  });
                }
              }}
            />
          </View>
        </View>

        {/* Zoom & Location Controls */}
        <View className="absolute right-4 top-1/2 -translate-y-1/2 gap-3 z-40">
          <PressableScale
            onPress={snapToCurrentLocation}
            className={`w-10 h-10 rounded-full items-center justify-center shadow-md border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}
            style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
          >
            {/* Minimal crosshair icon */}
            <View className={`w-4 h-4 rounded-full border-2 ${darkTheme ? "border-white" : "border-gray-800"}`} />
          </PressableScale>

          <View className="gap-2 mt-4">
            <PressableScale
              onPress={() => handleZoom(true)}
              className={`w-10 h-10 rounded-full items-center justify-center shadow-md border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}
              style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
            >
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-gray-800"}`}>+</Text>
            </PressableScale>
            <PressableScale
              onPress={() => handleZoom(false)}
              className={`w-10 h-10 rounded-full items-center justify-center shadow-md border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}
              style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
            >
              <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-gray-800"}`}>−</Text>
            </PressableScale>
          </View>
        </View>

        {/* Distance Pill */}
        {distanceToBase && Number(distanceToBase) > 0.5 && (
          <View className="absolute top-[130px] self-center z-40">
            <View className={`px-4 py-2 rounded-full shadow-md ${darkTheme ? "bg-[#201f1f]" : "bg-white"}`} style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}>
              <Text className={`text-sm font-sans-semibold ${darkTheme ? "text-white" : "text-gray-800"}`}>
                {distanceToBase} km from your physical location
              </Text>
            </View>
          </View>
        )}
      </View>

      {/* BOTTOM SHEET INFO PANEL */}
      <View
        className={`${darkTheme ? "bg-surface" : "bg-white"} absolute w-full pt-6 px-6`}
        style={{
          top: (height * 0.55), // Meets the bottom of the map exactly
          bottom: 0, // Stretches dynamically to the bottom of the screen
          shadowColor: "#000", shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.1, shadowRadius: 10, elevation: 10,
          borderTopWidth: 1, borderColor: darkTheme ? BRAND.gray800 : "transparent",
          borderTopLeftRadius: 35, borderTopRightRadius: 35 // Much larger corner radius
        }}
      >
        {/* Gesture Bar Indicator */}
        <View className="w-full items-center justify-center pb-4">
            <View className="w-16 h-2 rounded-full bg-gray-300" style={{ backgroundColor: darkTheme ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.1)" }} />
        </View>

        <Text className={`text-2xl font-heading-semibold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>
          Working Zone
        </Text>

        <Text className={`text-sm mb-6 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
          Drag the map to set your central delivery area.
          {operationRadiusKm
            ? ` You will receive requests from vendors within ${operationRadiusKm} km.`
            : ""}
        </Text>

        <View className={`p-4 rounded-2xl mb-6 border ${darkTheme ? "bg-[#111] border-gray-800" : "bg-white border-gray-200"}`}>
          <Text className={`text-xs uppercase tracking-widest font-sans-bold mb-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Selected Base Location</Text>
          <Text numberOfLines={2} className={`text-base font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>{liveAddress}</Text>
        </View>

        {/* Zone Limit Status */}
        <View className="flex-row items-center mb-6 px-1">
          <View className="w-2 h-2 rounded-full mr-3" style={{ backgroundColor: zoneChanges >= 2 ? "#EF4444" : "#10B981" }} />
          <Text className={`text-sm font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
            {zoneChanges >= 2 ? "Monthly update limit reached." : `Updates remaining this month: ${2 - zoneChanges}`}
          </Text>
        </View>

        <View className="mt-2 pb-[110px]">
          {zoneChanges >= 2 ? (
            <PressableScale
              onPress={handleSaveBase}
              className="py-4 rounded-xl items-center shadow-sm"
              style={{ backgroundColor: "#1F2937" }}
            >
              <Text className="text-white font-sans-bold text-lg">Contact Support to Change</Text>
            </PressableScale>
          ) : (
            <PressableScale
              onPress={handleSaveBase}
              disabled={saving || !location}
              className="py-4 rounded-xl items-center shadow-sm"
              style={{ backgroundColor: BRAND.primary }}
            >
              <Text className="text-white font-sans-bold text-lg">{saving ? "Saving..." : "Confirm Zone"}</Text>
            </PressableScale>
          )}
        </View>
      </View>

    </View>
  );
}
