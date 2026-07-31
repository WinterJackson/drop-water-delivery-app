import { UIThemeContext } from "@/context/ThemeContext";
import * as Location from "expo-location";
import { useContext, useEffect, useRef, useState, useMemo, useCallback } from "react";
import {
    Dimensions,
    Platform,
    StatusBar,
    Text,
    View,
    TextInput
} from "react-native";
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
import { useVendorProfile, useUpdateVendorProfile } from "@/hooks/queries/useVendorProfile";
import { useVendorOrders } from "@/hooks/queries/useVendorOrders";
import { useQueryClient } from "@tanstack/react-query";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import BottomSheet, { BottomSheetScrollView, BottomSheetView } from "@gorhom/bottom-sheet";
import { ScrollView } from "react-native-gesture-handler";

let MapView: any = null;
let Marker: any = null;
let Circle: any = null;
let Polyline: any = null;
let UrlTile: any = null;
let PROVIDER_GOOGLE: string | null = null;

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
    const updateProfile = useUpdateVendorProfile();
    const { data: orders = [], isLoading: isOrdersLoading } = useVendorOrders();

    const [currentLocation, setCurrentLocation] = useState<any>(null);
    const [deviceLocationLoading, setDeviceLocationLoading] = useState(true);
    const mapRef = useRef<any>(null);
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

    const [optimisticRadius, setOptimisticRadius] = useState<number | null>(null);
    const radiusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const currentDisplayRadius = optimisticRadius !== null ? optimisticRadius : (vendorProfile?.delivery_radius || DEFAULT_RADIUS_KM);

    const handleUpdateRadius = useCallback((increment: number) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        const newRadius = Math.min(15, Math.max(1, currentDisplayRadius + increment));
        if (newRadius === currentDisplayRadius) return;
        setOptimisticRadius(newRadius);
        if (radiusTimeoutRef.current) clearTimeout(radiusTimeoutRef.current);
        radiusTimeoutRef.current = setTimeout(async () => {
            try {
                await updateProfile.mutateAsync({ delivery_radius: newRadius });
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            } catch (e) {
                if (__DEV__) console.error("Radius update error:", e);
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
                setOptimisticRadius(null);
            }
        }, 800);
    }, [currentDisplayRadius, updateProfile]);

    useEffect(() => {
        if (vendorProfile?.delivery_radius && !radiusTimeoutRef.current) {
            setOptimisticRadius(null);
        }
    }, [vendorProfile?.delivery_radius]);

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
                    setCurrentLocation({
                        latitude: loc.coords.latitude,
                        longitude: loc.coords.longitude,
                    });
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
            (o: any) => ["pending", "accepted", "ready", "picked_up"].includes(o.order_status)
        );
        if (debouncedSearchQuery) {
            const lowerQuery = debouncedSearchQuery.toLowerCase();
            filtered = filtered.filter((o: any) => 
                (o.id && o.id.toLowerCase().includes(lowerQuery)) ||
                (o.user?.name && o.user.name.toLowerCase().includes(lowerQuery)) ||
                (o.deliverer?.name && o.deliverer.name.toLowerCase().includes(lowerQuery))
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
        (o: any) => o.order_status === "delivered"
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

        activeOrders.forEach((order: any, idx: number) => {
            if (order.lat && order.lng) {
                overlays.push(
                    // @ts-ignore
                    <Marker
                        key={`active-${order.id || idx}`}
                        coordinate={{ latitude: Number(order.lat), longitude: Number(order.lng) }}
                        title={`Drop-off #${order.id?.substring(0, 8)}`}
                        description={`${order.order_status} · KSH ${order.total_amount}`}
                        pinColor={STATUS_COLORS[order.order_status] || "red"}
                    />
                );

                // If the rider is assigned and we have their location, draw a polyline and rider marker
                const riderId = order.deliverer?.id;
                let rLat = null;
                let rLng = null;

                // Priority: Live WebSocket location > DB last known location
                if (riderId && riderLocations[riderId]) {
                    rLat = riderLocations[riderId].lat;
                    rLng = riderLocations[riderId].lng;
                } else if (order.deliverer?.current_lat && order.deliverer?.current_lng) {
                    rLat = order.deliverer.current_lat;
                    rLng = order.deliverer.current_lng;
                }

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
                                strokeColor={STATUS_COLORS[order.order_status] || BRAND.primary}
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
                            title={`Rider: ${order.deliverer?.name || 'Dispatch'}`}
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

        deliveredOrders.forEach((order: any, idx: number) => {
            if (order.lat && order.lng) {
                overlays.push(
                    // @ts-ignore
                    <Marker
                        key={`delivered-${order.id || idx}`}
                        coordinate={{ latitude: Number(order.lat), longitude: Number(order.lng) }}
                        title={`Delivered #${order.id?.substring(0, 8)}`}
                        description={`KSH ${order.total_amount}`}
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
            <View style={{ height: Dimensions.get('window').height * 0.5 }}>
                {MapView ? (
                    // @ts-ignore
                    <MapView
                        ref={mapRef}
                        provider={PROVIDER_GOOGLE}
                        mapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
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
                        <Text className={`mt-4 text-center px-10 font-bold text-lg ${darkTheme ? "text-[#bfc7d2]" : "text-slate-500"}`}>Map Engine Unavailable</Text>
                        <Text className={`mt-2 text-center px-12 font-semibold text-sm ${darkTheme ? "text-[#89929b]" : "text-slate-400"}`}>Map requires a native build.</Text>
                    </View>
                )}
                <SafeAreaView edges={["top"]} className="absolute w-full" pointerEvents="box-none">
                    <View className="px-4 pt-3 flex-row items-center justify-between" pointerEvents="box-none">
                        <View className="flex-row items-center flex-1" pointerEvents="box-none">
                            <PressableScale onPress={() => router.back()} className="mr-3 pointer-events-auto">
                                <BackButtonMinimal />
                            </PressableScale>
                            <View className={`flex-1 mr-3 flex-row items-center px-4 py-3 rounded-full border pointer-events-auto ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
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
                        <View className="flex-row items-center gap-2 pointer-events-auto">
                            <View className="flex-row gap-2">
                                <PressableScale onPress={() => handleZoom(true)} className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                    <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>+</Text>
                                </PressableScale>
                                <PressableScale onPress={() => handleZoom(false)} className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                    <Text className={`text-xl font-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>−</Text>
                                </PressableScale>
                            </View>
                            <PressableScale
                                onPress={() => {
                                    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                                    mapRef.current?.animateToRegion({ latitude: safeCenter.latitude, longitude: safeCenter.longitude, latitudeDelta: 0.04, longitudeDelta: 0.04 }, 800);
                                }}
                                className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}
                                style={shadowStyle}
                            >
                                <Ionicons name="navigate" size={20} color={BRAND.primary} />
                            </PressableScale>
                        </View>
                    </View>
                </SafeAreaView>
            </View>
            <View className={`flex-1 rounded-t-[32px] pt-2 px-5 mt-[-24px] ${darkTheme ? "bg-black border-t border-outline-variant" : "bg-[#f8fafc] border-t border-gray-200"}`} style={shadowStyle}>
                <View className="items-center mb-4">
                    <View className={`w-12 h-1.5 rounded-full ${darkTheme ? "bg-slate-700" : "bg-slate-300"}`} />
                </View>
                <Text className={`text-xl font-bold mb-6 ${darkTheme ? "text-white" : "text-slate-900"}`}>Delivery Zone Details</Text>
                {loading ? (
                    <VendorMapBottomSkeleton />
                ) : (
                    <>
                        <View className={`rounded-[24px] p-5 mb-5 border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
                            <View className="flex-row justify-between items-center">
                                <View className="flex-1 mr-4">
                                    <Text className={`text-[10px] font-bold mb-1 tracking-widest uppercase ${darkTheme ? "text-[#bfc7d2]" : "text-slate-500"}`}>Service Radius</Text>
                                    <Text className={`text-sm font-semibold ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Determines your catchment</Text>
                                </View>
                                <View className="flex-row items-center bg-transparent">
                                    <PressableScale onPress={() => handleUpdateRadius(-1)} className="w-12 h-12 rounded-full bg-red-500/10 items-center justify-center border border-red-500/20">
                                        <Ionicons name="remove" size={24} color="#ef4444" />
                                    </PressableScale>
                                    <View className="w-16 items-center">
                                        <Text className={`text-2xl font-black ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                            {currentDisplayRadius}<Text className="text-sm font-bold">km</Text>
                                        </Text>
                                    </View>
                                    <PressableScale onPress={() => handleUpdateRadius(1)} className="w-12 h-12 rounded-full bg-green-500/10 items-center justify-center border border-green-500/20">
                                        <Ionicons name="add" size={24} color={TOAST.success} />
                                    </PressableScale>
                                </View>
                            </View>
                        </View>
                        <View className="flex-row gap-4 mb-5">
                            <View className={`flex-1 rounded-[24px] p-5 border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                <View className={`w-10 h-10 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-accentbg/20" : "bg-accentbg/10"}`}>
                                    <Ionicons name="bicycle-outline" size={20} color={BRAND.primary} />
                                </View>
                                <Text className={`text-3xl font-black ${darkTheme ? "text-white" : "text-slate-900"}`}>{activeOrders.length}</Text>
                                <Text className={`text-xs font-bold mt-1 tracking-wide uppercase ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Active Orders</Text>
                            </View>
                            <View className={`flex-1 rounded-[24px] p-5 border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`} style={shadowStyle}>
                                <View className={`w-10 h-10 rounded-full items-center justify-center mb-3 ${darkTheme ? "bg-green-500/20" : "bg-green-500/10"}`}>
                                    <Ionicons name="checkmark-circle-outline" size={20} color={TOAST.success} />
                                </View>
                                <Text className={`text-3xl font-black ${darkTheme ? "text-white" : "text-slate-900"}`}>{deliveredOrders.length}</Text>
                                <Text className={`text-xs font-bold mt-1 tracking-wide uppercase ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Delivered</Text>
                            </View>
                        </View>
                    </>
                )}
            </View>

            {/* Bottom Sheet for Active Dispatches */}
            <BottomSheet
                ref={bottomSheetRef}
                index={0}
                snapPoints={['20%', '50%', '85%']}
                backgroundStyle={{ backgroundColor: darkTheme ? '#1e293b' : '#ffffff' }}
                handleIndicatorStyle={{ backgroundColor: darkTheme ? '#cbd5e1' : '#cbd5e1', width: 40 }}
            >
                <BottomSheetView style={{ flex: 1 }}>
                    <View className="px-6 pt-2 pb-4 flex-row items-center justify-between border-b border-gray-100 dark:border-gray-800">
                        <Text className={`text-lg font-bold ${darkTheme ? "text-white" : "text-gray-900"}`}>
                            Active Dispatches
                        </Text>
                        <View className={`px-2 py-1 rounded-full ${activeOrders.length > 0 ? "bg-amber-100" : "bg-gray-100"}`}>
                            <Text className={`text-xs font-semibold ${activeOrders.length > 0 ? "text-amber-700" : "text-gray-500"}`}>
                                {activeOrders.length} Riders
                            </Text>
                        </View>
                    </View>

                    <BottomSheetScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 12, paddingBottom: 40 }}>
                        {activeOrders.length === 0 ? (
                            <View className="items-center justify-center py-10">
                                <Ionicons name="bicycle-outline" size={48} color={darkTheme ? "#475569" : "#cbd5e1"} />
                                <Text className={`mt-4 text-center ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                    No active riders currently on the road.
                                </Text>
                            </View>
                        ) : (
                            activeOrders.map((order: any, idx: number) => {
                                const riderId = order.deliverer?.id;
                                let rLat = null;
                                let rLng = null;

                                if (riderId && riderLocations[riderId]) {
                                    rLat = riderLocations[riderId].lat;
                                    rLng = riderLocations[riderId].lng;
                                } else if (order.deliverer?.current_lat && order.deliverer?.current_lng) {
                                    rLat = order.deliverer.current_lat;
                                    rLng = order.deliverer.current_lng;
                                }

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
                                        <View className={`flex-row items-center p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-gray-800 border-gray-700" : "bg-white border-gray-100"} shadow-sm`}>
                                            <View className={`w-12 h-12 rounded-full items-center justify-center ${darkTheme ? "bg-gray-700" : "bg-blue-50"}`}>
                                                <Ionicons name="person" size={20} color={BRAND.primary} />
                                                {connected && hasLocation && (
                                                    <View className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white" />
                                                )}
                                            </View>
                                            <View className="flex-1 ml-4">
                                                <Text className={`font-semibold text-base ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
                                                    {order.deliverer?.name || 'Waiting for Rider'}
                                                </Text>
                                                <Text className={`text-sm mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                                    Order #{order.id?.substring(0, 8)}
                                                </Text>
                                            </View>
                                            <View className="items-end">
                                                <View className={`px-2 py-1 rounded-md bg-[${STATUS_COLORS[order.order_status] || '#ccc'}20]`}>
                                                    <Text style={{ color: STATUS_COLORS[order.order_status] || '#ccc', fontSize: 12, fontWeight: '600' }}>
                                                        {order.order_status.toUpperCase()}
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
                </BottomSheetView>
            </BottomSheet>
        </View>
    );
}
