import { UIThemeContext } from "@/context/ThemeContext";
import { useCallback, useContext, useEffect, useRef as useReactRef, useState } from "react";
import {
    Dimensions,
    Platform,
    StatusBar,
    StyleSheet,
    View,
    ActivityIndicator,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";
import { Skeleton } from "@/components/ui/Skeleton";
import * as Haptics from "expo-haptics";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { useLocalSearchParams, useRouter } from "expo-router";
import { darkMapStyle, standardMapStyle } from "@/constants/mapStyles";
import { useVendorOrders } from "@/hooks/queries/useVendorOrders";
import { useVendorProfile } from "@/hooks/queries/useVendorProfile";
import { useOrderTracking } from "@/hooks/useOrderTracking";

// Safe Map Imports
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
let MarkerAnimated: React.ComponentType<
    MapMarkerProps & { ref?: React.Ref<React.ComponentRef<typeof MarkerAnimatedType>> }
> | null = null;
let UrlTile: React.ComponentType<MapUrlTileProps> | null = null;
let PROVIDER_GOOGLE: Provider = undefined;

if (Platform.OS !== "web") {
    try {
        const maps = require("react-native-maps");
        MapView = maps.default;
        Marker = maps.Marker;
        MarkerAnimated = maps.MarkerAnimated;
        UrlTile = maps.UrlTile;
        PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
    } catch {}
}

const { width, height } = Dimensions.get("window");

export default function LiveMap() {
    const { id } = useLocalSearchParams();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: vendorProfile } = useVendorProfile();
    const { data: orders = [] } = useVendorOrders();
    
    const activeOrder = orders.find((o) => o.id === id);

    const [riderCoordinates, setRiderCoordinates] = useState<{lat: number, lng: number} | null>(null);
    const mapRef = useReactRef<MapViewType | null>(null);
    const trackingMarkerRef = useReactRef<React.ComponentRef<typeof MarkerAnimatedType> | null>(null);

    /**
     * Live rider position, from the one hook that knows how to open this socket.
     *
     * This screen used to build the connection inline and omit the `?token=`
     * query parameter, so the server closed it with 1008 before the first
     * frame — the map has never shown a moving rider to a vendor. It also
     * derived the socket origin with an unanchored `.replace("http", "ws")` on
     * a REST base URL.
     */
    const { location: riderLocation, isLive } = useOrderTracking(
        activeOrder?.id,
        !!activeOrder?.order_status && ["accepted", "picked_up"].includes(activeOrder.order_status),
    );

    useEffect(() => {
        if (!riderLocation) return;
        setRiderCoordinates(riderLocation);
        if (Platform.OS === 'web') return;
        mapRef.current?.animateCamera({
            center: { latitude: riderLocation.lat, longitude: riderLocation.lng },
            pitch: 45,
        }, { duration: 1000 });
        trackingMarkerRef.current?.animateMarkerToCoordinate?.(
            { latitude: riderLocation.lat, longitude: riderLocation.lng },
            1500,
        );
    }, [riderLocation]);

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

    const StatusBarHeight = StatusBar.currentHeight || 0;
    const finalHeight = height + StatusBarHeight;

    const initialRegion = {
        latitude: Number(vendorProfile?.lat || -1.2921),
        longitude: Number(vendorProfile?.lng || 36.8219),
        latitudeDelta: 0.04,
        longitudeDelta: 0.04,
    };

    if (!activeOrder) {
        return (
            <SafeAreaView className={`flex-1 items-center justify-center ${darkTheme ? "bg-black" : "bg-white"}`}>
                <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Order not found</Text>
                <PressableScale onPress={() => router.back()} className="mt-4 bg-accentbg px-6 py-2 rounded-lg">
                    <Text className="text-white font-sans-bold">Go Back</Text>
                </PressableScale>
            </SafeAreaView>
        );
    }

    return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            <View style={{ height: finalHeight * 0.75 }}>
                {MapView ? (
                    <MapView
                        ref={mapRef}
                        provider={PROVIDER_GOOGLE}
                        // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                        // the prop every map screen in all three apps passed was dropped and cloud
                        // styling has never once been applied. A misspelt prop is silent here.
                        googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                        style={StyleSheet.absoluteFill}
                        initialRegion={initialRegion}
                        showsUserLocation={true}
                        showsMyLocationButton={false}
                        showsCompass={false}
                    >

                        {/* Customer Location */}
                        {Marker && activeOrder.lat && activeOrder.lng && (
                            <Marker
                                coordinate={{ latitude: Number(activeOrder.lat), longitude: Number(activeOrder.lng) }}
                                title="Delivery Location"
                            >
                                <View className="items-center w-[50px] h-[50px] justify-center">
                                    <Ionicons name="home" size={24} color={BRAND.primary} />
                                    <View className={`p-1 ${darkTheme ? "bg-black" : "bg-white"} absolute top-2 min-w-[25px] min-h-[25px] rounded-full -z-10`} />
                                </View>
                            </Marker>
                        )}

                        {/* Vendor Location */}
                        {Marker && vendorProfile?.lat && vendorProfile?.lng && (
                            <Marker
                                coordinate={{ latitude: Number(vendorProfile.lat), longitude: Number(vendorProfile.lng) }}
                                title="My Store"
                            >
                                <View className="items-center w-[50px] h-[50px] justify-center">
                                    <Ionicons name="storefront" size={24} color="#10b981" />
                                    <View className={`p-1 ${darkTheme ? "bg-black" : "bg-white"} absolute top-2 min-w-[25px] min-h-[25px] rounded-full -z-10`} />
                                </View>
                            </Marker>
                        )}

                        {/* Live Rider Location */}
                        {MarkerAnimated && riderCoordinates && (
                            <MarkerAnimated 
                                ref={trackingMarkerRef}
                                coordinate={{ latitude: Number(riderCoordinates.lat), longitude: Number(riderCoordinates.lng) }}
                            >
                                <View className="items-center w-[50px] h-[50px] justify-center">
                                    <Ionicons name="bicycle" size={28} color="#f59e0b" />
                                    <View className={`p-1 ${darkTheme ? "bg-black" : "bg-white"} absolute top-2 min-w-[25px] min-h-[25px] rounded-full -z-10`} />
                                </View>
                            </MarkerAnimated>
                        )}
                    </MapView>
                ) : (
                    <View className="flex-1">
                        <Skeleton width="100%" height="100%" borderRadius={0} />
                    </View>
                )}

                <SafeAreaView edges={["top"]} className="absolute w-full" pointerEvents="box-none">
                    <View className="px-4 pt-3 flex-row items-center justify-between" pointerEvents="box-none">
                        <View className="flex-row items-center" pointerEvents="box-none">
                            <PressableScale onPress={() => router.back()} className="mr-4">
                                <BackButtonMinimal />
                            </PressableScale>
                        </View>
                        <View className="flex-row gap-2 pointer-events-auto">
                            <PressableScale onPress={() => handleZoom(true)} className={`w-10 h-10 rounded-full items-center justify-center border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-200"}`}>
                                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>+</Text>
                            </PressableScale>
                            <PressableScale onPress={() => handleZoom(false)} className={`w-10 h-10 rounded-full items-center justify-center border shadow-sm ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-200"}`}>
                                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-slate-800"}`}>−</Text>
                            </PressableScale>
                        </View>
                    </View>
                </SafeAreaView>
            </View>

            {/* Bottom Card matching the UI style exactly */}
            <View className={`absolute bottom-0 w-full rounded-t-[32px] pt-4 pb-8 px-6 border-t shadow-2xl ${darkTheme ? "bg-surface border-outline-variant" : "bg-white border-gray-200"}`}>
                <View className="items-center mb-5">
                    <View className={`w-12 h-1.5 rounded-full ${darkTheme ? "bg-slate-700" : "bg-slate-300"}`} />
                </View>
                
                <Text className={`text-xl font-sans-extrabold mb-1 ${darkTheme ? "text-white" : "text-slate-900"}`}>Live Tracking</Text>
                <Text className={`text-sm font-sans-semibold mb-6 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>Order #{activeOrder.id.substring(0,8)}</Text>
                
                <View className={`flex-row items-center justify-between p-4 rounded-2xl border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-slate-50 border-gray-100"}`}>
                    <View className="flex-row items-center">
                        <View className={`w-12 h-12 rounded-full items-center justify-center mr-4 ${darkTheme ? "bg-accentbg/20" : "bg-accentbg/10"}`}>
                            {isLive ? (
                                <Ionicons name="pulse" size={24} color={BRAND.primary} />
                            ) : (
                                <ActivityIndicator size="small" color={BRAND.primary} />
                            )}
                        </View>
                        <View>
                            {/* Three states, not two. A position with a dead
                                socket is the last one we were told, not a rider
                                who is moving — and saying "moving" over a frozen
                                marker is the version of this a vendor calls
                                support about. */}
                            <Text className={`text-sm font-sans-bold ${darkTheme ? "text-white" : "text-slate-900"}`}>
                                {isLive
                                    ? "Rider is moving"
                                    : riderCoordinates
                                        ? "Reconnecting — showing last position"
                                        : "Waiting for rider location..."}
                            </Text>
                            <Text className={`text-xs mt-0.5 ${darkTheme ? "text-slate-400" : "text-slate-500"}`}>
                                {activeOrder.order_status?.replace("_", " ") ?? "unknown"}
                            </Text>
                        </View>
                    </View>
                </View>
            </View>
        </View>
    );
}
