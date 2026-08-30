import { UIThemeContext } from "@/context/ThemeContext";
import * as Location from "expo-location";
import { useContext, useEffect, useRef, useState, useMemo } from "react";
import {
    Dimensions,
    Platform,
    StatusBar,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { BRAND, TOAST } from "@/constants/brandColors";
import { VendorMapBottomSkeleton } from "@/components/skeletons/ContextualSkeletons";
import * as Haptics from "expo-haptics";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useRouter } from "expo-router";
import { darkMapStyle, standardMapStyle } from "@/constants/mapStyles";
import useWebSocket from "@/hooks/useWebSocket";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { useStorefront } from "@/hooks/queries/useStorefront";
import { useVendorOrders } from "@/hooks/queries/useVendorOrders";
import { useQueryClient } from "@tanstack/react-query";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import BottomSheet, { BottomSheetScrollView, BottomSheetView } from "@gorhom/bottom-sheet";
import { ScrollView } from "react-native-gesture-handler";
import { formatMoney } from "@/utils/money";

import type MapViewType from 'react-native-maps';
import type {
    MapCircleProps,
    MapMarkerProps,
    MapPolylineProps,
    MapUrlTileProps,
    MapViewProps,
    MarkerAnimated as MarkerAnimatedType,
    Provider,
} from 'react-native-maps';

/**
 * `react-native-maps` is `require`d because it has no web build. Its *types*
 * import freely — `import type` is erased at compile time and emits no require —
 * so every component below is the real one.
 *
 * These stay `| null`, unlike the other apps' shims: this app has no web
 * stand-ins, only a `try`/`catch` that leaves them unset, so `{MapView ? …}` at
 * the use site is guarding a state that genuinely occurs.
 */
let MapView: React.ComponentType<MapViewProps & { ref?: React.Ref<MapViewType> }> | null = null;
let Marker: React.ComponentType<MapMarkerProps> | null = null;
let Circle: React.ComponentType<MapCircleProps> | null = null;
let Polyline: React.ComponentType<MapPolylineProps> | null = null;
let UrlTile: React.ComponentType<MapUrlTileProps> | null = null;
let PROVIDER_GOOGLE: Provider = undefined;

if (Platform.OS !== "web") {
    try {
        // @ts-ignore
        const maps = require("react-native-maps");
        MapView = maps.default;
        Marker = maps.Marker;
        Circle = maps.Circle;
        Polyline = maps.Polyline;
        UrlTile = maps.UrlTile;
        PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
    } catch {
    }
}

const NAIROBI = { latitude: -1.2921, longitude: 36.8219, latitudeDelta: 0.05, longitudeDelta: 0.05 };
const DEFAULT_RADIUS_KM = 5;

export default function MyMap() {
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const queryClient = useQueryClient();
    const router = useRouter();

    const { data: vendorProfile, isLoading: isProfileLoading } = useVendorProfile();
    const { data: storefront } = useStorefront();
    const { data: orders = [], isLoading: isOrdersLoading } = useVendorOrders();

    const [currentLocation, setCurrentLocation] = useState<Location.LocationObjectCoords | null>(null);
    const [deviceLocationLoading, setDeviceLocationLoading] = useState(true);
    const mapRef = useRef<MapViewType | null>(null);
    const bottomSheetRef = useRef<BottomSheet>(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");

    // Track live rider coordinates independently of the orders payload
    const [riderLocations, setRiderLocations] = useState<Record<string, {lat: number, lng: number}>>({});

    const { connected } = useWebSocket('vendor', vendorProfile?.id || '', (data) => {
        if (data.action === "RIDER_LOCATION" && data.rider_id && data.location) {
            setRiderLocations(prev => ({
                ...prev,
                [data.rider_id as string]: data.location as {lat: number, lng: number}
            }));
        } else {
            queryClient.invalidateQueries({ queryKey: ['vendorOrders'] });
        }
    });

    const loading = isProfileLoading || isOrdersLoading || deviceLocationLoading;

    const shadowStyle = darkTheme
        ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 }
        : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 };

    /**
     * The catchment this store actually has.
     *
     * This screen used to render a stepper writing `Vendor.delivery_radius`,
     * and nothing on the dispatch path has ever read that column: how far an
     * order travels is `retail_max_distance_km` / `wholesale_max_distance_km`
     * on the console. So a vendor dragging it to 15 km changed no delivery —
     * it only widened the circle on this map, and inflated the delivery
     * estimate the customer app quoted from the same column, making the store
     * look slower to everyone browsing it.
     *
     * The server now reports the real figure with the rest of the storefront
     * limits, for the same reason the pause presets and the order-minimum
     * ceiling arrive that way: a number the server owns, stated once.
     */
    const currentDisplayRadius = storefront?.limits?.delivery_radius_km ?? DEFAULT_RADIUS_KM;

    useEffect(() => {
        let cancelled = false;

        const fetchDeviceLocation = async () => {
            try {
                const { status } = await Location.requestForegroundPermissionsAsync();
                if (status !== "granted") return;

                // Last known first: it returns instantly from the OS cache.
                // A bare getCurrentPositionAsync({}) defaults to the highest
                // accuracy and can block for 10-30s waiting on a cold GPS fix,
                // holding the map skeleton on screen the whole time — matching
                // the fallback chain StoreProfile and Onboarding already use.
                let loc = await Location.getLastKnownPositionAsync();
                if (!loc) {
                    loc = await Location.getCurrentPositionAsync({
                        accuracy: Location.Accuracy.Balanced,
                    });
                }
                if (loc && !cancelled) {
                    setCurrentLocation(loc.coords);
                }
            } catch (e) {
                if (__DEV__) console.log("Location skipped:", e);
            } finally {
                if (!cancelled) setDeviceLocationLoading(false);
            }
        };
        fetchDeviceLocation();

        return () => {
            cancelled = true;
        };
    }, []);

    const safeCenter = useMemo(() => {
        if (vendorProfile?.lat && vendorProfile?.lng) {
            const lat = Number(vendorProfile.lat);
            const lng = Number(vendorProfile.lng);
            if (!isNaN(lat) && !isNaN(lng)) return { latitude: lat, longitude: lng };
        }
        if (currentLocation?.latitude && currentLocation?.longitude) {
            return { latitude: currentLocation.latitude, longitude: currentLocation.longitude };
        }
        return { latitude: NAIROBI.latitude, longitude: NAIROBI.longitude };
    }, [vendorProfile?.lat, vendorProfile?.lng, currentLocation]);

    const radiusMeters = currentDisplayRadius * 1000;

    const activeOrders = useMemo(() => {
        let filtered = orders.filter(
            (o) => ["pending", "accepted", "ready", "picked_up"].includes(o.order_status ?? "")
        );
        if (debouncedSearchQuery) {
            const lowerQuery = debouncedSearchQuery.toLowerCase();
            filtered = filtered.filter((o) => 
                (o.id && o.id.toLowerCase().includes(lowerQuery)) ||
                (o.user?.full_name && o.user.full_name.toLowerCase().includes(lowerQuery)) ||
                (o.deliverer?.full_name && o.deliverer.full_name.toLowerCase().includes(lowerQuery))
            );
        }
        return filtered;
    }, [orders, debouncedSearchQuery]);

    // Effect to handle Search debounce and Camera Snapping
    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedSearchQuery(searchQuery);
        }, 300);
        return () => clearTimeout(timer);
    }, [searchQuery]);

    useEffect(() => {
        if (debouncedSearchQuery && activeOrders.length === 1 && mapRef.current) {
            const target = activeOrders[0];
            let targetLat = target.lat;
            let targetLng = target.lng;
            const riderId = target.deliverer?.id;
            if (riderId && riderLocations[riderId]) {
                targetLat = riderLocations[riderId].lat;
                targetLng = riderLocations[riderId].lng;
            }
            if (targetLat && targetLng) {
                mapRef.current.animateCamera({
                    center: { latitude: Number(targetLat), longitude: Number(targetLng) },
                    pitch: 0,
                    heading: 0,
                    zoom: 15,
                }, { duration: 800 });
                bottomSheetRef.current?.snapToIndex(1);
            }
        }
    }, [debouncedSearchQuery, activeOrders.length]);

    const deliveredOrders = useMemo(() => orders.filter(
        (o) => o.order_status === "delivered"
    ).slice(0, 20), [orders]);

    const STATUS_COLORS: Record<string, string> = {
        pending: "#f59e0b", accepted: "#3b82f6", ready: "#8b5cf6",
        picked_up: "#06b6d4", delivered: "#22c55e",
    };

    const mapOverlays = useMemo(() => {
        if (!Marker || !Circle) return null;
        
        const overlays = [];
        
        if (vendorProfile?.lat && vendorProfile?.lng) {
            overlays.push(
                // @ts-ignore
                <Marker
                    key="vendor-store-location"
                    coordinate={{ latitude: Number(vendorProfile.lat), longitude: Number(vendorProfile.lng) }}
                    title={vendorProfile.business_name || "My Store"}
                    description={vendorProfile.location_address || "Store location"}
                    pinColor="blue"
                />
            );
            overlays.push(
                // @ts-ignore
                <Circle
                    key="vendor-delivery-radius"
                    center={{ latitude: Number(vendorProfile.lat), longitude: Number(vendorProfile.lng) }}
                    radius={radiusMeters}
                    strokeWidth={2}
                    strokeColor="rgba(14, 165, 233, 0.6)"
                    fillColor="rgba(14, 165, 233, 0.08)"
                />
            );
        }

        activeOrders.forEach((order, idx) => {
            if (order.lat && order.lng) {
                overlays.push(
                    // @ts-ignore
                    <Marker
                        key={`active-${order.id || idx}`}
                        coordinate={{ latitude: Number(order.lat), longitude: Number(order.lng) }}
                        title={`Drop-off #${order.id?.substring(0, 8)}`}
                        description={`${order.order_status} · ${formatMoney(order.total_amount)}`}
                        pinColor={STATUS_COLORS[order.order_status ?? ""] || "red"}
                    />
                );

                // If the rider is assigned and we have their location, draw a polyline and rider marker
                // The live socket is the *only* source of a rider's position
                // here. The fallback read `order.deliverer.current_lat/lng`,
                // which `OrderVendorSnippet`'s sibling `OrderDelivererSnippet`
                // does not carry — four fields the server has never sent — so
                // the "DB last known location" branch was unreachable and the
                // rider marker appeared only while a socket was delivering.
                const riderId = order.deliverer?.id;
                const live = riderId ? riderLocations[riderId] : undefined;
                const rLat = live?.lat ?? null;
                const rLng = live?.lng ?? null;

                if (rLat && rLng) {
                    // Draw Polyline: Vendor -> Rider -> Customer
                    if (Polyline && vendorProfile?.lat && vendorProfile?.lng) {
                        overlays.push(
                            // @ts-ignore
                            <Polyline
                                key={`poly-${order.id || idx}`}
                                coordinates={[
                                    { latitude: Number(vendorProfile.lat), longitude: Number(vendorProfile.lng) },
                                    { latitude: Number(rLat), longitude: Number(rLng) },
                                    { latitude: Number(order.lat), longitude: Number(order.lng) }
                                ]}
                                strokeColor={STATUS_COLORS[order.order_status ?? ""] || BRAND.primary}
                                strokeWidth={2}
                                lineDashPattern={[5, 5]}
                            />
                        );
                    }

                    // Draw Rider Marker
                    overlays.push(
                        // @ts-ignore
                        <Marker
                            key={`rider-${riderId}-${order.id}`}
                            coordinate={{ latitude: Number(rLat), longitude: Number(rLng) }}
                            title={`Rider: ${order.deliverer?.full_name || 'Dispatch'}`}
                            description={`Status: ${order.order_status}`}
                            pinColor="yellow"
                            zIndex={999}
                        >
                            <View className="bg-white p-1 rounded-full shadow-lg border border-gray-200">
                                <View className="bg-[#f59e0b] w-6 h-6 rounded-full items-center justify-center">
                                    <Ionicons name="bicycle" size={14} color="white" />
                                </View>
                            </View>
                        </Marker>
                    );
                }
            }
        });

        deliveredOrders.forEach((order, idx) => {
            if (order.lat && order.lng) {
                overlays.push(
                    // @ts-ignore
                    <Marker
                        key={`delivered-${order.id || idx}`}
                        coordinate={{ latitude: Number(order.lat), longitude: Number(order.lng) }}
                        title={`Delivered #${order.id?.substring(0, 8)}`}
                        description={formatMoney(order.total_amount)}
                        pinColor="green"
                        opacity={0.5}
                    />
                );
            }
        });

        return overlays;
    }, [vendorProfile?.lat, vendorProfile?.lng, vendorProfile?.business_name, vendorProfile?.location_address, radiusMeters, activeOrders, deliveredOrders, riderLocations]);

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

    const handleSnapToRider = (lat: number, lng: number) => {
        if (!mapRef.current) return;
        mapRef.current.animateCamera({
            center: { latitude: Number(lat), longitude: Number(lng) },
            zoom: 16
        }, { duration: 500 });
        // Optionally collapse bottom sheet
        bottomSheetRef.current?.collapse();
    };

    useEffect(() => {
        if (!loading && mapRef.current) {
            mapRef.current.animateToRegion({
                latitude: safeCenter.latitude,
                longitude: safeCenter.longitude,
                latitudeDelta: 0.04,
                longitudeDelta: 0.04,
            }, 800);
        }
    }, [loading]);

    if (!vendorProfile && !isProfileLoading) {
        return (
            <DataFallbackUI 
                title="Vendor data unavailable"
                message="We couldn't load your vendor profile. Please retry to connect to the map."
                onRetry={() => queryClient.invalidateQueries({ queryKey: ['vendorProfile'] })}
            />
        );
    }

    return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : "bg-[#f8fafc]"}`}>
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
            <View style={{ flex: 1 }}>
                {MapView ? (
                    // @ts-ignore
                    <MapView
                        ref={mapRef}
                        provider={PROVIDER_GOOGLE}
                        // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                        // the prop every map screen in all three apps passed was dropped and cloud
                        // styling has never once been applied. A misspelt prop is silent here.
                        googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                        style={{ flex: 1 }}
                        initialRegion={{
                            latitude: NAIROBI.latitude,
                            longitude: NAIROBI.longitude,
                            latitudeDelta: 0.04,
                            longitudeDelta: 0.04,
                        }}
                        showsUserLocation={true}
                        showsMyLocationButton={false}
                    >
                        {/* {UrlTile && (
                            // @ts-ignore
                            <UrlTile
                                urlTemplate={darkTheme
                                    ? "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png"
                                    : "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"}
                                maximumZ={20}
                            />
                        )} */}
                        {mapOverlays}
                    </MapView>
                ) : (
                    <View className={`flex-1 items-center justify-center ${darkTheme ? "bg-[#121212]" : "bg-slate-100"}`}>
                        <View className={`w-28 h-28 rounded-full items-center justify-center mb-6 shadow-sm border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-slate-200"}`}>
                            <Ionicons name="map" size={56} color={BRAND.primary} />
                        </View>
                        <Text className={`mt-4 text-center px-10 font-sans-bold text-lg ${darkTheme ? "text-[#bfc7d2]" : "text-slate-500"}`}>Map Engine Unavailable</Text>
                        <Text className={`mt-2 text-center px-12 font-sans-semibold text-sm ${darkTheme ? "text-[#89929b]" : "text-slate-400"}`}>Map requires a native build.</Text>
                    </View>
                )}
                <SafeAreaView edges={["top"]} className="absolute w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
                    <View className="px-4 pt-3 flex-row items-center" pointerEvents="box-none">
                        <View className="flex-row items-center flex-1" pointerEvents="box-none">
                            <PressableScale onPress={() => router.back()} className="mr-3 pointer-events-auto">
                                <BackButtonMinimal />
                            </PressableScale>
                            <View className={`flex-1 flex-row items-center px-4 py-3 rounded-full border pointer-events-auto ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                <Ionicons name="search" size={20} color={darkTheme ? "#89929b" : "#94a3b8"} className="mr-2" />
                                <TextInput
                                    placeholder="Search order ID, rider, or customer"
                                    placeholderTextColor={darkTheme ? "#89929b" : "#94a3b8"}
                                    value={searchQuery}
                                    onChangeText={setSearchQuery}
                                    style={{ color: darkTheme ? "#fff" : "#0f172a", flex: 1, fontSize: 16 }}
                                />
                            </View>
                        </View>
                    </View>
                    <View className="absolute right-4 top-24 gap-3 pointer-events-auto">
                        <PressableScale onPress={() => handleZoom(true)} className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                            <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>+</Text>
                        </PressableScale>
                        <PressableScale onPress={() => handleZoom(false)} className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                            <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>−</Text>
                        </PressableScale>
                        <PressableScale accessibilityLabel="Centre the map on your store"
                            onPress={() => {
                                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                mapRef.current?.animateToRegion({ latitude: safeCenter.latitude, longitude: safeCenter.longitude, latitudeDelta: 0.04, longitudeDelta: 0.04 }, 800);
                            }}
                            className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`}
                            style={shadowStyle}
                        >
                            <Ionicons name="navigate" size={20} color={BRAND.primary} />
                        </PressableScale>
                    </View>
                </SafeAreaView>
            </View>

            {/* Single Combined Bottom Sheet */}
            <BottomSheet
                ref={bottomSheetRef}
                index={0}
                snapPoints={['35%', '60%', '90%']}
                style={{ zIndex: 100 }}
                backgroundStyle={{ backgroundColor: darkTheme ? '#000000' : '#f8fafc' }}
                handleIndicatorStyle={{ backgroundColor: darkTheme ? '#3f4850' : '#cbd5e1', width: 40 }}
            >
                <BottomSheetScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 12, paddingBottom: 40 }}>
                    {/* Delivery Zone Details */}
                    <Text className={`text-xl font-sans-bold mb-6 ${darkTheme ? "text-white" : "text-slate-900"}`}>Delivery Zone Details</Text>
                    {loading ? (
                        <VendorMapBottomSkeleton />
                    ) : (
                        <>
                            <View className={`rounded-[24px] p-5 mb-5 border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                <View className="flex-row justify-between items-center">
                                    <View className="flex-1 mr-4">
                                        <Text className={`text-[10px] font-sans-bold mb-1 tracking-widest uppercase ${darkTheme ? "text-[#bfc7d2]" : "text-slate-500"}`}>Service Radius</Text>
                                        <Text className={`text-sm font-sans-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                                            How far Drop carries your orders. Set by Drop, the same for every store.
                                        </Text>
                                    </View>
                                    <View className="items-center bg-transparent">
                                        <Text className={`text-3xl font-sans-extrabold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                            {currentDisplayRadius}<Text className="text-sm font-sans-bold">km</Text>
                                        </Text>
                                    </View>
                                </View>
                            </View>
                            <View className="flex-row gap-4 mb-8">
                                <View className={`flex-1 rounded-[24px] p-5 border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                    <View className={`w-10 h-10 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-accentbg/20" : "bg-accentbg/10"}`}>
                                        <Ionicons name="bicycle-outline" size={20} color={BRAND.primary} />
                                    </View>
                                    <Text className={`text-3xl font-sans-extrabold ${darkTheme ? "text-white" : "text-slate-900"}`}>{activeOrders.length}</Text>
                                    <Text className={`text-xs font-sans-bold mt-1 tracking-wide uppercase ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Active Orders</Text>
                                </View>
                                <View className={`flex-1 rounded-[24px] p-5 border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                    <View className={`w-10 h-10 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-green-500/20" : "bg-green-500/10"}`}>
                                        <Ionicons name="checkmark-circle-outline" size={20} color={TOAST.success} />
                                    </View>
                                    <Text className={`text-3xl font-sans-extrabold ${darkTheme ? "text-white" : "text-slate-900"}`}>{deliveredOrders.length}</Text>
                                    <Text className={`text-xs font-sans-bold mt-1 tracking-wide uppercase ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Delivered</Text>
                                </View>
                            </View>
                        </>
                    )}

                    {/* Active Dispatches Header */}
                    <View className="flex-row items-center justify-between mb-4">
                        <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                            Active Dispatches
                        </Text>
                        <View className={`px-2 py-1 rounded-full ${activeOrders.length > 0 ? (darkTheme ? "bg-amber-900/30" : "bg-amber-100") : (darkTheme ? "bg-[#201f1f]" : "bg-gray-100")}`}>
                            <Text className={`text-xs font-sans-semibold ${activeOrders.length > 0 ? (darkTheme ? "text-amber-400" : "text-amber-700") : (darkTheme ? "text-gray-400" : "text-gray-500")}`}>
                                {activeOrders.length} Riders
                            </Text>
                        </View>
                    </View>

                    {/* Active Dispatches List */}
                    {activeOrders.length === 0 ? (
                        <View className="items-center justify-center py-10">
                            <Ionicons name="bicycle-outline" size={48} color={darkTheme ? "#475569" : "#cbd5e1"} />
                            <Text className={`mt-4 text-center ${darkTheme ? "text-[#89929b]" : "text-gray-500"}`}>
                                No active riders currently on the road.
                            </Text>
                        </View>
                    ) : (
                        activeOrders.map((order, idx) => {
                            // Live socket only — see the note on the map
                            // overlay above; `deliverer.current_lat/lng`
                            // are not on the wire.
                            const riderId = order.deliverer?.id;
                            const live = riderId ? riderLocations[riderId] : undefined;
                            const rLat = live?.lat ?? null;
                            const rLng = live?.lng ?? null;

                            const hasLocation = !!(rLat && rLng);

                            return (
                                <PressableScale 
                                    key={`dispatch-${order.id || idx}`}
                                    onPress={() => {
                                        if (hasLocation) handleSnapToRider(rLat, rLng);
                                        else Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
                                    }}
                                    disabled={!hasLocation}
                                >
                                    <View className={`flex-row items-center p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-[#121212] border-[#3f4850]" : "bg-white border-gray-100"} shadow-sm`}>
                                        <View className={`w-12 h-12 rounded-full items-center justify-center ${darkTheme ? "bg-[#201f1f]" : "bg-blue-50"}`}>
                                            <Ionicons name="person" size={20} color={BRAND.primary} />
                                            {connected && hasLocation && (
                                                <View className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white" />
                                            )}
                                        </View>
                                        <View className="flex-1 ml-4">
                                            <Text className={`font-sans-semibold text-base ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
                                                {order.deliverer?.full_name || 'Waiting for Rider'}
                                            </Text>
                                            <Text className={`text-sm mt-1 ${darkTheme ? "text-[#89929b]" : "text-gray-500"}`}>
                                                Order #{order.id?.substring(0, 8)}
                                            </Text>
                                        </View>
                                        <View className="items-end">
                                            <View className={`px-2 py-1 rounded-md bg-[${STATUS_COLORS[order.order_status ?? ''] || '#ccc'}20]`}>
                                                <Text style={{ color: STATUS_COLORS[order.order_status ?? ''] || '#ccc', fontSize: 12, fontFamily: 'Karla_600SemiBold' }}>
                                                    {(order.order_status ?? 'unknown').toUpperCase()}
                                                </Text>
                                            </View>
                                            {!hasLocation && order.deliverer && (
                                                <Text className="text-[10px] text-gray-400 mt-1">No GPS Signal</Text>
                                            )}
                                        </View>
                                    </View>
                                </PressableScale>
                            );
                        })
                    )}
                </BottomSheetScrollView>
            </BottomSheet>
        </View>
    );
}
