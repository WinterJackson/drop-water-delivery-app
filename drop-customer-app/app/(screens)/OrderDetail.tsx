import { Ionicons } from '@expo/vector-icons';
import { useTabBarClearance } from '@/constants/layout';
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { OrderDetailSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { UIThemeContext } from "@/context/ThemeContext";
import { BRAND, TOAST } from "@/constants/brandColors";
import { useOrder, useActiveOrder, useCancelOrder, useResolveMismatch, Order, useOrderTrackingLogs } from "@/hooks/queries/useOrders";
import { useOrderContacts, ContactInfo } from "@/hooks/queries/useOrderContacts";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { errorMessage } from "@/API/errors";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useContext, useMemo, useState, useRef, useEffect } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import {
    Image,
    ScrollView,
    StatusBar,
    View,
    Platform,
    Dimensions,
    Modal,
    Linking,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { useRiderTracking } from "@/hooks/queries/useRiderTracking";
import { formatMoney, isNegativeMoney, isZeroMoney, multiplyMoney, subtractMoney, sumMoney } from "@/utils/money";

/**
 * `react-native-maps` has no web build, so it is `require`d behind a platform
 * check. Its *types* import freely — `import type` is erased and emits no
 * require — so the components below are the real ones and the web stand-ins are
 * checked against the same props.
 *
 * `AnimatedRegion` was in this list, assigned on native, set to `null` on web
 * and read by nothing at all.
 */
import type MapViewType from 'react-native-maps';
import type {
    MapMarkerProps,
    MapPolylineProps,
    MapViewProps,
    MarkerAnimated as MarkerAnimatedType,
    Provider,
} from 'react-native-maps';

/** Both driven by ref (`getCamera`, `animateMarkerToCoordinate`), so `ref` is part of the props. */
let MapView: React.ComponentType<MapViewProps & { ref?: React.Ref<MapViewType> }>;
let Marker: React.ComponentType<MapMarkerProps>;
let MarkerAnimated: React.ComponentType<
    MapMarkerProps & { ref?: React.Ref<React.ComponentRef<typeof MarkerAnimatedType>> }
>;
let Polyline: React.ComponentType<MapPolylineProps>;
let PROVIDER_GOOGLE: Provider;
if (Platform.OS !== 'web') {
    const maps = require('react-native-maps');
    MapView = maps.default;
    Marker = maps.Marker;
    MarkerAnimated = maps.MarkerAnimated;
    Polyline = maps.Polyline;
    PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
} else {
    MapView = ({ style, children }: MapViewProps) => <View style={style}>{children}</View>;
    Marker = () => null;
    MarkerAnimated = () => null;
    Polyline = () => null;
    PROVIDER_GOOGLE = 'google';
}

const { width } = Dimensions.get("window");

const STATUS_STEPS = ["pending", "accepted", "preparing", "ready", "picked_up", "delivered"];

const STATUS_LABELS: Record<string, string> = {
    unassigned: "Order Placed", // Maps loosely to pending in terms of visual feedback
    pending: "Order Placed",
    accepted: "Vendor Accepted",
    preparing: "Preparing",
    ready: "Ready for Pickup",
    picked_up: "On the Way",
    delivered: "Delivered",
    cancelled: "Cancelled",
    rejected: "Rejected",
    mismatch_pending: "Delivery Paused",
    pending_review: "Review Pending",
};

const SHORT_STATUS_LABELS: Record<string, string> = {
    pending: "Placed",
    accepted: "Accepted",
    preparing: "Preparing",
    ready: "Ready",
    picked_up: "Transit",
    delivered: "Delivered",
};

export default function OrderDetail() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const { orderId } = useLocalSearchParams<{ orderId: string }>();
    const router = useRouter();

    const [loading, setLoading] = useState(false);
    const { mutate: cancelOrderMutation, isPending: cancelLoading } = useCancelOrder();
    const { mutate: resolveMismatch, isPending: resolveLoading } = useResolveMismatch();
    const handleCancelOrder = () => {
        if (!order) return;
        const isAccepted = order.order_status === "accepted";
        const message = isAccepted 
            // No figure. The penalty is two settings rows — one before pickup, a
            // larger one after — and it is waived entirely while the customer
            // still has a free cancellation in the last 30 days. This app knows
            // none of those three things. What was actually charged comes back
            // from the server below.
            ? "Are you sure you want to cancel this order? The vendor has already accepted it, so a cancellation fee may apply."
            : "Are you sure you want to cancel this order? This action cannot be undone.";
            
        // Themed confirmation via the app's own Popup, not a native Alert:
        // native alerts ignore dark mode and the brand palette.
        Popup.show({
            title: "Cancel Order",
            message,
            cancelText: "No, Keep It",
            confirmText: "Yes, Cancel",
            isDestructive: true,
            onConfirm: () => {
                Popup.setLoading(true);
                cancelOrderMutation(order.id, {
                    onSuccess: (result) => {
                        Popup.hide();
                        Toast.success(
                            "Order cancelled",
                            isZeroMoney(result?.penalty_charged)
                                ? "Your order has been cancelled."
                                : `A ${formatMoney(result.penalty_charged)} cancellation fee has been added to your balance and will be collected on your next order.`,
                        );
                    },
                    onError: (error: Error) => {
                        Popup.hide();
                        Toast.error("Couldn't cancel order", errorMessage(error, "Please try again."));
                    }
                });
            }
        });
    };

    // Fetched by id, not searched for in the order list. The list is one page,
    // and the order somebody has just tapped a notification about is routinely
    // not on it — which rendered as a detail screen that never stopped loading.
    const { data: fetchedOrder, isLoading: ordersLoading, isFetching: ordersFetching } = useOrder(orderId);
    const { data: activeOrder } = useActiveOrder();

    const order: Order | null = useMemo(() => {
        // `activeOrder` is already in cache on the common path, so preferring the
        // fetched row but falling back to it keeps the screen painting instantly
        // for the order the customer is actually waiting on.
        return fetchedOrder ?? (activeOrder?.id === orderId ? activeOrder : null);
    }, [fetchedOrder, orderId, activeOrder]);

    // Use query loading state natively, or local state during intermediate transitions
    // If order is not found but we're fetching in the background, consider it loading to prevent UI flashes
    const isLoading = loading || ordersLoading || (!order && ordersFetching);

    const getStatusIndex = (status: string) => {
        // Handle background/legacy/cached states gracefully
        if (status === "unassigned") return 0; // Treat as pending for visual simplicity
        if (status === "completed") return 5; // Map legacy cached completed state to delivered
        return STATUS_STEPS.indexOf(status);
    };
    const currentStepIndex = order ? getStatusIndex(order.order_status) : -1;

    const shouldTrackRider = ["picked_up", "mismatch_pending", "pending_review"].includes(order?.order_status as string);
    const { data: riderLocation } = useRiderTracking(order?.id || null, shouldTrackRider);

    /**
     * The rider's position, or null when there isn't one.
     *
     * `RiderLocation.lat`/`lng` are nullable — a rider row exists before the
     * handset has reported a fix — and the map read them straight into a
     * `coordinate`, which is a `LatLng` of two non-null numbers. `null` there is
     * not a missing marker; it is a marker at a coordinate the native view
     * cannot make sense of.
     */
    const riderCoords = useMemo(
        () =>
            riderLocation && riderLocation.lat != null && riderLocation.lng != null
                ? { latitude: riderLocation.lat, longitude: riderLocation.lng }
                : null,
        [riderLocation],
    );
    const { data: trackingLogs } = useOrderTrackingLogs(order?.id || null);

    // Cross-party contact info (only fetched during active states)
    const { data: contactsData } = useOrderContacts(order?.id || null, order?.order_status || null);
    const contacts = contactsData?.contacts || [];
    const vendorContact = contacts.find((c: ContactInfo) => c.role === "vendor");
    const riderContact = contacts.find((c: ContactInfo) => c.role === "rider");

    const handleCall = (phone: string, role: string) => {
        if (!phone || phone === "N/A") {
            Toast.error("Unavailable", `${role} phone number is not available.`);
            return;
        }
        Linking.openURL(`tel:${phone}`);
    };

    const mapRef = useRef<MapViewType | null>(null);
    const markerRef = useRef<React.ComponentRef<typeof MarkerAnimatedType> | null>(null);

    const { height } = Dimensions.get('window');
    const StatusBarHeight = StatusBar.currentHeight || 0;
    const finalHeight = height + StatusBarHeight;

    const handleZoom = (zoomIn: boolean) => {
        if (mapRef.current) {
            mapRef.current.getCamera().then((camera) => {
                camera.zoom = (camera.zoom ?? 0) + (zoomIn ? 1 : -1);
                mapRef.current?.animateCamera(camera, { duration: 500 });
            });
        }
    };

    // Smoothly animate the map camera to follow the rider as WebSockets stream GPS coords natively
    useEffect(() => {
        if (riderLocation?.lat && riderLocation?.lng && mapRef.current && Platform.OS !== 'web') {
            mapRef.current.animateCamera(
                {
                    center: { latitude: riderLocation.lat, longitude: riderLocation.lng },
                    pitch: 45,
                    heading: 0,
                    altitude: 1000,
                    zoom: 16
                },
                { duration: 1500 }
            );
            
            // If MarkerAnimated resolves animateMarkerToCoordinate, fire it for total smoothness
            if (markerRef.current?.animateMarkerToCoordinate) {
                markerRef.current.animateMarkerToCoordinate(
                    { latitude: riderLocation.lat, longitude: riderLocation.lng },
                    1500
                );
            }
        } else if (!shouldTrackRider && order && mapRef.current && Platform.OS !== 'web') {
            // Pre-dispatch: Fit map to show both vendor and dropoff locations
            const coords: { latitude: number; longitude: number }[] = [];
            const vLat = order.vendor?.lat || order.lat_from;
            const vLng = order.vendor?.lng || order.lng_from;
            
            if (vLat && vLng) coords.push({ latitude: vLat, longitude: vLng });
            if (order.lat && order.lng) coords.push({ latitude: order.lat, longitude: order.lng });

            if (coords.length > 0) {
                // Wait slightly for map to render before fitting
                setTimeout(() => {
                    mapRef.current?.fitToCoordinates(coords, {
                        edgePadding: { top: 80, right: 60, bottom: 80, left: 60 },
                        animated: true,
                    });
                }, 1000);
            }
        }
    }, [riderLocation?.lat, riderLocation?.lng, shouldTrackRider, order?.id]);

    if (isLoading) {
        return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : "bg-gray-100"}`}>
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />

            {/* Map Skeleton Block (Top 55%) */}
            <View className="absolute top-0 left-0 right-0" style={{ height: '55%' }}>
                <View className={`flex-1 ${darkTheme ? "bg-gray-900" : "bg-gray-300"}`} />
                <View className="absolute top-0 left-0 right-0 z-10 px-4" style={{ paddingTop: (StatusBar.currentHeight || 40) + 10 }}>
                    <View className="flex-row items-center gap-3">
                        <View className={`w-10 h-10 rounded-full items-center justify-center`} style={{ backgroundColor: BRAND.primary }}>
                            <Ionicons name="chevron-back" size={24} color="white" />
                        </View>
                    </View>
                </View>
            </View>

            {/* Details Skeleton Block (Bottom 50%) */}
            <View className="absolute bottom-0 left-0 right-0" style={{ height: '50%', backgroundColor: darkTheme ? '#000' : '#f9fafb', borderTopLeftRadius: 24, borderTopRightRadius: 24, overflow: 'hidden', paddingBottom: tabBarClearance }}>
                <View className="w-full items-center pt-3 pb-2">
                    <View className={`w-12 h-1.5 rounded-full ${darkTheme ? "bg-gray-800" : "bg-gray-300"}`} />
                </View>
                <OrderDetailSkeleton />
            </View>
        </View>
        );
    }

    if (!order) {
        return (
            <View className={`flex-1 items-center justify-center ${darkTheme ? "bg-black" : "bg-white"}`}>
                <Text className={`text-lg ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Order not found</Text>
            </View>
        );
    }

    return (
        <View className={`flex-1 ${darkTheme ? "bg-black" : "bg-gray-100"}`}>
            <StatusBar translucent backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />

            {/* Top Half: Map Area */}
            <View className="absolute top-0 left-0 right-0" style={{ height: '55%' }}>
                {MapView && (
                    <MapView
                        ref={mapRef}
                        provider={PROVIDER_GOOGLE}
                        // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                        // the prop these three screens passed was dropped and cloud styling has
                        // never once been applied. A misspelt prop on a native view is silent.
                        googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                        style={{ flex: 1 }}
                        initialRegion={
                            shouldTrackRider && riderCoords
                                ? {
                                      ...riderCoords,
                                      latitudeDelta: 0.015,
                                      longitudeDelta: 0.015,
                                  }
                                : trackingLogs?.[0]
                                ? {
                                      latitude: trackingLogs[0].lat,
                                      longitude: trackingLogs[0].lng,
                                      latitudeDelta: 0.015,
                                      longitudeDelta: 0.015,
                                  }
                                : {
                                      // Fallback to Nairobi/General Location
                                      latitude: -1.2921,
                                      longitude: 36.8219,
                                      latitudeDelta: 0.05,
                                      longitudeDelta: 0.05,
                                  }
                        }
                    >
                        {shouldTrackRider && riderCoords && (Platform.OS !== 'web' ? (
                            <MarkerAnimated
                                ref={markerRef}
                                coordinate={riderCoords}
                                title={riderLocation?.rider_name || "Rider"}
                                description="On the way with your order"
                            >
                                <View className="w-10 h-10 rounded-full bg-white items-center justify-center border-2 border-blue-500" style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}>
                                    <Ionicons name="bicycle" size={24} color={BRAND.primary} />
                                </View>
                            </MarkerAnimated>
                        ) : (
                            <Marker
                                coordinate={riderCoords}
                                title={riderLocation?.rider_name || "Rider"}
                            >
                                <View className="w-10 h-10 rounded-full bg-white items-center justify-center border-2 border-blue-500" style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}>
                                    <Ionicons name="bicycle" size={24} color={BRAND.primary} />
                                </View>
                            </Marker>
                        ))}
                        
                        {/* Vendor Marker (Always show) */}
                        {(order?.vendor?.lat || order?.lat_from) && (order?.vendor?.lng || order?.lng_from) && (
                            <Marker
                                coordinate={{
                                    latitude: (order.vendor?.lat || order.lat_from) as number,
                                    longitude: (order.vendor?.lng || order.lng_from) as number,
                                }}
                                title={order.vendor?.business_name || "Vendor"}
                                description="Pickup Location"
                            >
                                <View className="w-10 h-10 rounded-full bg-white items-center justify-center border-2 border-green-500" style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}>
                                    <Ionicons name="storefront" size={20} color={BRAND.primary} />
                                </View>
                            </Marker>
                        )}

                        {/* Customer Dropoff Marker (Always show) */}
                        {order?.lat && order?.lng && (
                            <Marker
                                coordinate={{
                                    latitude: order.lat as number,
                                    longitude: order.lng as number,
                                }}
                                title="Delivery Destination"
                                description="Where your water is going"
                            >
                                <View className="w-10 h-10 rounded-full bg-white items-center justify-center border-2 border-black" style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}>
                                    <Ionicons name="home" size={20} color="black" />
                                </View>
                            </Marker>
                        )}
                        
                        {trackingLogs && trackingLogs.length > 0 && Polyline && (
                            <>
                                <Polyline
                                    coordinates={trackingLogs.map((log) => ({
                                        latitude: log.lat,
                                        longitude: log.lng,
                                    }))}
                                    strokeColor={BRAND.primary}
                                    strokeWidth={4}
                                />
                                <Marker
                                    coordinate={{ latitude: trackingLogs[0].lat, longitude: trackingLogs[0].lng }}
                                    title="Start"
                                    pinColor="green"
                                />
                                {order.order_status === "delivered" && (
                                    <Marker
                                        coordinate={{ latitude: trackingLogs[trackingLogs.length - 1].lat, longitude: trackingLogs[trackingLogs.length - 1].lng }}
                                        title="Delivery Location"
                                        pinColor="blue"
                                    />
                                )}
                            </>
                        )}
                    </MapView>
                )}

                {/* Overlaid Header */}
                <View className="absolute top-0 left-0 right-0 z-10 px-4 pointer-events-box-none" style={{ paddingTop: (StatusBar.currentHeight || 40) + 10 }}>
                    <View className="flex-row items-center gap-3">
                        <PressableScale accessibilityLabel="Go back" onPress={() => router.back()} activeOpacity={0.7}>
                            <View 
                                className={`w-10 h-10 rounded-full items-center justify-center`}
                                style={{ backgroundColor: BRAND.primary, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}
                            >
                                <Ionicons name="chevron-back" size={24} color="white" />
                            </View>
                        </PressableScale>
                        <View 
                            className={`px-4 py-2 rounded-full border ${darkTheme ? "bg-[#1c1c1e] border-[#2c2c2e]" : "bg-white border-gray-200"}`}
                            style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8, elevation: 5 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 4, elevation: 3 }}
                        >
                            <Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>
                                Order #{order.id?.slice(-6)}
                            </Text>
                        </View>
                    </View>
                </View>

                {/* Overlaid Rider Info (if active) */}
                {shouldTrackRider && riderLocation && (
                    <View className="absolute top-36 left-4 z-10">
                        <View className={`px-4 py-2 rounded-full flex-row items-center gap-2 border ${darkTheme ? "bg-[#1c1c1e] border-[#2c2c2e]" : "bg-white border-gray-200"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8, elevation: 5 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 4, elevation: 3 }}>
                            <View className="w-2 h-2 rounded-full bg-green-500" />
                            <Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-black"}`}>Live Tracking</Text>
                        </View>
                    </View>
                )}

                {/* Zoom Controls Overlay */}
                <View className="absolute top-36 right-4 z-10 flex-col gap-3">
                    <PressableScale
                        onPress={() => handleZoom(true)}
                        className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-[#1c1c1e] border-[#2c2c2e]" : "bg-white border-gray-200"}`}
                        style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 3.84, elevation: 5 }}
                    >
                        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>+</Text>
                    </PressableScale>
                    <PressableScale
                        onPress={() => handleZoom(false)}
                        className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-[#1c1c1e] border-[#2c2c2e]" : "bg-white border-gray-200"}`}
                        style={{ shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 3.84, elevation: 5 }}
                    >
                        <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>−</Text>
                    </PressableScale>
                </View>
            </View>

            {/* Bottom Half: Scrollable Details */}
            {/* tab-bar-clearance: the panel is shortened rather than its scroller
                padded — see the note in `constants/layout.ts`. */}
            <View className="absolute bottom-0 left-0 right-0" style={{ height: '50%', backgroundColor: darkTheme ? '#000' : '#f9fafb', borderTopLeftRadius: 24, borderTopRightRadius: 24, overflow: 'hidden', elevation: 15, shadowColor: '#000', shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.1, shadowRadius: 12, paddingBottom: tabBarClearance }}>
                <View className="w-full items-center pt-3 pb-2 bg-transparent">
                    <View className={`w-12 h-1.5 rounded-full ${darkTheme ? "bg-[#333]" : "bg-[#cbd5e1]"}`} />
                </View>
                <ScrollView
                    contentContainerStyle={{ padding: 16, paddingTop: 0, paddingBottom: tabBarClearance }}
                    showsVerticalScrollIndicator={false}
                >
                 {/* Status Timeline Tracking Bar */}
                 <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                     <Text className={`text-lg font-sans-bold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>
                         Tracking Status
                     </Text>
                     {["cancelled", "rejected", "mismatch_pending", "pending_review"].includes(order.order_status) ? (
                         <View className="flex-row items-center gap-3 pr-4">
                             <View 
                                className="w-8 h-8 rounded-full items-center justify-center shrink-0"
                                style={{ backgroundColor: ["mismatch_pending", "pending_review"].includes(order.order_status) ? BRAND.primary : TOAST.error }}
                             >
                                 <Text className="text-white font-sans-bold">{["mismatch_pending", "pending_review"].includes(order.order_status) ? "⚠️" : "✕"}</Text>
                             </View>
                             <View className="flex-1">
                                <Text 
                                    className="text-base font-sans-semibold"
                                    style={{ color: ["mismatch_pending", "pending_review"].includes(order.order_status) ? BRAND.primary : TOAST.error }}
                                >
                                    {STATUS_LABELS[order.order_status] || "Notice"}
                                </Text>
                                {order.order_status === "mismatch_pending" && (
                                    <Text className={`text-xs mt-1 leading-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                        The rider reported an address mismatch. Please come to the ground floor to pick up your bottles!
                                    </Text>
                                )}
                                {order.order_status === "pending_review" && (
                                    <Text className={`text-xs mt-1 leading-4 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                        The rider has flagged your empty bottle for review. Please wait while admin reviews the photos.
                                    </Text>
                                )}
                             </View>
                         </View>
                     ) : (
                         <View>
                             <View className="flex-row justify-between items-center mb-8 px-2 relative">
                                 {/* Background Bar */}
                                 <View className={`absolute top-4 left-6 right-6 h-1 rounded ${darkTheme ? "bg-gray-700" : "bg-gray-300"}`} />
                                 
                                 {/* Progress Fill */}
                                 <View 
                                     className="absolute top-4 left-6 h-1 rounded bg-blue-500" 
                                     style={{ width: `${(Math.max(0, currentStepIndex) / (STATUS_STEPS.length - 1)) * 100}%` }} 
                                 />
                                 
                                 {STATUS_STEPS.map((step, index) => {
                                     const isActive = index <= currentStepIndex;
                                     const isCurrent = index === currentStepIndex;
                                     const isCompleted = index < currentStepIndex;
                                     
                                     return (
                                         <View key={step} className="items-center relative">
                                             <View 
                                                 className={`w-8 h-8 rounded-full items-center justify-center z-10 border-4 ${darkTheme ? "border-[#1c1c1e]" : "border-gray-50"} ${!isCompleted && !isCurrent ? (darkTheme ? "bg-gray-700" : "bg-gray-300") : ""}`}
                                                 style={isCompleted ? { backgroundColor: TOAST.success } : (isCurrent ? { backgroundColor: TOAST.info } : {})}
                                             >
                                                 {isCompleted ? (
                                                     <Text className="text-white text-xs font-sans-bold">✓</Text>
                                                 ) : (
                                                     <Text className={`text-xs font-sans-bold ${isActive ? "text-white" : (darkTheme ? "text-gray-400" : "text-gray-500")}`}>
                                                         {index + 1}
                                                     </Text>
                                                 )}
                                             </View>
                                             
                                             <Text 
                                                 className={`absolute top-10 text-[10px] w-20 text-center font-sans-semibold ${
                                                     isCurrent
                                                         ? "text-blue-500"
                                                         : isActive
                                                         ? darkTheme ? "text-gray-300" : "text-gray-700"
                                                         : darkTheme ? "text-gray-600" : "text-gray-400"
                                                 }`}
                                             >
                                                 {SHORT_STATUS_LABELS[step] || step}
                                             </Text>
                                         </View>
                                     );
                                 })}
                             </View>
                             <View className="mt-4 flex-row items-center justify-between">
                                 <Text className={`text-base font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                    Current Stage:
                                 </Text>
                                 <Text className="text-blue-500 font-sans-bold text-lg">
                                     {STATUS_LABELS[STATUS_STEPS[currentStepIndex]] || "Processing"}
                                 </Text>
                             </View>
                         </View>
                     )}
                 </View>

                {/* ── Cross-Party Contact Cards ────────────────────────── */}
                {contacts.length > 0 && (
                    <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                        <Text className={`text-lg font-sans-bold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>
                            Contact
                        </Text>
                        <View className="gap-3">
                            {vendorContact && (
                                <PressableScale
                                    activeOpacity={0.8}
                                    onPress={() => handleCall(vendorContact.phone, "Vendor")}
                                    className="flex-row items-center gap-3 p-3 rounded-xl"
                                    style={{
                                        backgroundColor: darkTheme ? 'rgba(2, 149, 247, 0.08)' : 'rgba(2, 149, 247, 0.06)',
                                        borderWidth: 1,
                                        borderColor: darkTheme ? 'rgba(2, 149, 247, 0.15)' : 'rgba(2, 149, 247, 0.12)',
                                    }}
                                >
                                    <View className="w-11 h-11 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary + '20' }}>
                                        <Text style={{ fontSize: 18 }}>🏪</Text>
                                    </View>
                                    <View className="flex-1">
                                        <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>
                                            {vendorContact.name}
                                        </Text>
                                        <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Tap to call vendor</Text>
                                    </View>
                                    <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary }}>
                                        <Text className="text-white text-lg">📞</Text>
                                    </View>
                                </PressableScale>
                            )}
                            {riderContact && (
                                <PressableScale
                                    activeOpacity={0.8}
                                    onPress={() => handleCall(riderContact.phone, "Rider")}
                                    className="flex-row items-center gap-3 p-3 rounded-xl"
                                    style={{
                                        backgroundColor: darkTheme ? 'rgba(16, 185, 129, 0.08)' : 'rgba(16, 185, 129, 0.06)',
                                        borderWidth: 1,
                                        borderColor: darkTheme ? 'rgba(16, 185, 129, 0.15)' : 'rgba(16, 185, 129, 0.12)',
                                    }}
                                >
                                    <View className="w-11 h-11 rounded-full items-center justify-center" style={{ backgroundColor: TOAST.success + '20' }}>
                                        <Text style={{ fontSize: 18 }}>🛵</Text>
                                    </View>
                                    <View className="flex-1">
                                        <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>
                                            {riderContact.name}
                                        </Text>
                                        <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                            {riderContact.vehicle_details ? `${riderContact.vehicle_details} • ` : ""}Tap to call rider
                                        </Text>
                                    </View>
                                    <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: TOAST.success }}>
                                        <Text className="text-white text-lg">📞</Text>
                                    </View>
                                </PressableScale>
                            )}
                        </View>
                    </View>
                )}

                {/* Vendor Info */}
                {order.vendor && (
                    <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                        <Text className={`text-lg font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                            Vendor
                        </Text>
                        <View className="flex-row items-center gap-3">
                            {order.vendor.profile_pic ? (
                                <Image source={{ uri: order.vendor.profile_pic }} className="w-12 h-12 rounded-full" />
                            ) : (
                                <View className="w-12 h-12 rounded-full bg-blue-500 items-center justify-center">
                                    <Text className="text-white text-lg">🏪</Text>
                                </View>
                            )}
                            <View>
                                <Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>
                                    {order.vendor.business_name}
                                </Text>
                                <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                    {order.vendor.location_address}
                                </Text>
                            </View>
                        </View>
                    </View>
                )}

                {/* Order Items */}
                <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                    <Text className={`text-lg font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                        Items ({order.order_item?.length || 0})
                    </Text>
                    {order.order_item?.map((item) => (
                        <View key={item.id} className="flex-row items-center gap-3 mb-3">
                            {item.product?.image_url ? (
                                <Image source={{ uri: item.product.image_url }} className="w-14 h-14 rounded-xl" />
                            ) : (
                                <View className="w-14 h-14 rounded-xl bg-gray-300 items-center justify-center">
                                    <Text>📦</Text>
                                </View>
                            )}
                            <View className="flex-1">
                                <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                    {item.product?.name || "Product"}
                                </Text>
                                <Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                    Qty: {item.quantity} × {formatMoney(item.price)}
                                </Text>
                            </View>
                            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(multiplyMoney(item.price, item.quantity ?? 0))}
                            </Text>
                        </View>
                    ))}
                </View>

                {/* Price Breakdown */}
                <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                    <Text className={`text-lg font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                        Price Summary
                    </Text>
                    
                    {/* C-01 FIX: Use server-provided product_subtotal, fallback to computing it from items for legacy orders */}
                    <View className="flex-row justify-between mb-2">
                        <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Subtotal</Text>
                        <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                            {formatMoney(!isZeroMoney(order.product_subtotal) ? order.product_subtotal : sumMoney((order.order_item ?? []).map((i) => multiplyMoney(i.price, i.quantity ?? 0))))}
                        </Text>
                    </View>

                    <View className="flex-row justify-between mb-2">
                        <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Delivery Fee</Text>
                        <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                            {formatMoney(order.delivery_fee)}
                        </Text>
                    </View>

                    {!isZeroMoney(order.service_fee) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Service Fee</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(order.service_fee)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.surge_fee) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Surge Pricing</Text>
                            <Text className={`font-sans-semibold text-orange-500`}>
                                {formatMoney(order.surge_fee)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.payload_surcharge) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Large Order Surcharge</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(order.payload_surcharge)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.staircase_surcharge) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Staircase Surcharge</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(order.staircase_surcharge)}
                            </Text>
                        </View>
                    )}

                    {/* Both are columns on the order and were on neither
                        response schema, so no screen could show them. The
                        deposit is the largest line on a `new_bottle` order —
                        without it this column cannot reach the Total below. */}
                    {!isZeroMoney(order.bottle_deposit) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Bottle Deposit</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(order.bottle_deposit)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.debt_settlement) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Previous Balance</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {formatMoney(order.debt_settlement)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.welcome_discount) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Welcome Offer</Text>
                            <Text className={`font-sans-semibold text-green-500`}>
                                -{formatMoney(order.welcome_discount)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.wallet_discount) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Wallet Balance Applied</Text>
                            <Text className={`font-sans-semibold text-green-500`}>
                                -{formatMoney(order.wallet_discount)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.mpesa_discount) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>M-Pesa Payment Discount</Text>
                            <Text className={`font-sans-semibold text-green-500`}>
                                -{formatMoney(order.mpesa_discount)}
                            </Text>
                        </View>
                    )}

                    {!isZeroMoney(order.rounding_adjustment) && (
                        <View className="flex-row justify-between mb-2">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Rounding</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                                {isNegativeMoney(order.rounding_adjustment)
                                    ? `- ${formatMoney(subtractMoney("0", order.rounding_adjustment))}`
                                    : `+ ${formatMoney(order.rounding_adjustment)}`}
                            </Text>
                        </View>
                    )}

                    <View className={`border-t pt-2 mt-2 flex-row justify-between ${darkTheme ? "border-gray-700" : "border-gray-200"}`}>
                        <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>Total</Text>
                        <Text className={`text-lg font-sans-bold text-green-500`}>
                            {/* `total_amount` is what the customer was charged,
                                frozen on the order. Re-adding the lines here was
                                a second pricing formula that left out the bottle
                                deposit and any settled balance, so this screen
                                and the M-Pesa message disagreed. */}
                            {formatMoney(order.total_amount)}
                        </Text>
                    </View>
                </View>

                {/* Order Info */}
                <View className={`p-5 rounded-2xl mb-5 ${darkTheme ? "bg-white/5" : "bg-white"}`}>
                    <Text className={`text-lg font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>
                        Order Info
                    </Text>
                    <View className="gap-3">
                        <View className="flex-row justify-between">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Order ID</Text>
                            <Text className={`font-mono text-sm ${darkTheme ? "text-white" : "text-black"}`}>
                                {order.id?.slice(-12)}
                            </Text>
                        </View>
                        <View className="flex-row justify-between">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Placed On</Text>
                            <Text className={`font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>
                                {order.created_at ? new Date(order.created_at).toLocaleDateString("en-US", {
                                    day: "numeric",
                                    month: "short",
                                    year: "numeric",
                                    hour: "2-digit",
                                    minute: "2-digit",
                                }) : "Unknown Date"}
                            </Text>
                        </View>
                        {order.delivery_address && (
                            <View className="flex-row justify-between">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Address</Text>
                                <Text className={`font-sans-semibold text-right max-w-[60%] ${darkTheme ? "text-white" : "text-black"}`}>
                                    {order.delivery_address}
                                </Text>
                            </View>
                        )}
                        {order.delivery_type && (
                            <View className="flex-row justify-between">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Delivery Type</Text>
                                <Text className={`font-sans-semibold capitalize ${darkTheme ? "text-white" : "text-black"}`}>
                                    {order.delivery_type.replace('_', ' ')}
                                </Text>
                            </View>
                        )}
                        {order.bottle_source && (
                            <View className="flex-row justify-between">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Bottle Exchange</Text>
                                <Text className={`font-sans-semibold capitalize ${darkTheme ? "text-white" : "text-black"}`}>
                                    {order.bottle_source.replace('_', ' ')}
                                </Text>
                            </View>
                        )}
                        <View className={`mt-1 pt-3 border-t flex-col gap-3 ${darkTheme ? "border-gray-800" : "border-gray-200"}`}>
                            <View className="flex-row justify-between items-center">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Payment Method</Text>
                                {order.payment_method === "cash" ? (
                                    <View className="flex-row items-center gap-1">
                                        <Text className="text-amber-500 font-sans-bold">Cash on Delivery</Text>
                                        <Text className="text-amber-500">💰</Text>
                                    </View>
                                ) : order.payment_method === "card" ? (
                                    <View className="flex-row items-center gap-1">
                                        <Text className="text-blue-500 font-sans-bold">Card</Text>
                                        <Text className="text-blue-500">💳</Text>
                                    </View>
                                ) : (
                                    <View className="flex-row items-center gap-1">
                                        <Text className="text-green-500 font-sans-bold">M-PESA</Text>
                                        <Text className="text-green-500">📱</Text>
                                    </View>
                                )}
                            </View>
                            <View className="flex-row justify-between items-center">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Payment Status</Text>
                                <View className={`px-3 py-1 rounded-full ${order.payment_status === 'paid' ? 'bg-green-500/20' : 'bg-amber-500/20'}`}>
                                    <Text className={`font-sans-bold capitalize ${order.payment_status === 'paid' ? 'text-green-500' : 'text-amber-500'}`}>
                                        {order.payment_status || "Pending"}
                                    </Text>
                                </View>
                            </View>
                        </View>
                    </View>
                </View>

                {/* Actions */}
                {(order.order_status === "pending" || order.order_status === "unassigned" || order.order_status === "accepted") && (
                    <PressableScale
                        activeOpacity={0.8}
                        disabled={cancelLoading}
                        onPress={handleCancelOrder}
                        className="py-4 rounded-2xl items-center mb-4"
                        style={{ backgroundColor: TOAST.error }}
                    >
                        <Text className="text-white font-sans-bold text-lg">{cancelLoading ? "Cancelling..." : "Cancel Order"}</Text>
                    </PressableScale>
                )}

                {order.order_status === "delivered" && !order.is_rated && (
                    <PressableScale
                        activeOpacity={0.8}
                        onPress={() =>
                            router.push({
                                pathname: "/(screens)/RateOrder",
                                params: {
                                    orderId: order.id,
                                    vendorId: order.vendor?.id,
                                    riderId: order.deliverer?.id,
                                },
                            })
                        }
                        className="py-4 rounded-2xl items-center mb-4"
                        style={{ backgroundColor: BRAND.primary }}
                    >
                        <Text className="text-white font-sans-bold text-lg">⭐ Rate This Order</Text>
                    </PressableScale>
                )}

                {/* Something went wrong with *this* order is the commonest reason
                    anybody contacts support, and it is the moment they are least
                    willing to go hunting through Settings. The order travels with
                    them, so the ticket says which one without them typing it. */}
                <PressableScale
                    activeOpacity={0.8}
                    onPress={() =>
                        router.push({
                            pathname: "/(screens)/Support",
                            params: { orderId: order.id },
                        })
                    }
                    className="py-4 rounded-2xl items-center mb-4 flex-row justify-center gap-2"
                    style={{ borderWidth: 1, borderColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
                >
                    <Ionicons name="help-buoy-outline" size={18} color={BRAND.primary} />
                    <Text className="font-sans-bold text-base" style={{ color: BRAND.primary }}>
                        Get help with this order
                    </Text>
                </PressableScale>
                </ScrollView>
            </View>

            {/* Address Mismatch Dispute Modal */}
            <Modal
                visible={order.order_status === "mismatch_pending"}
                transparent={true}
                animationType="slide"
            >
                <View className="flex-1 justify-end bg-black/60">
                    <View 
                        className={`rounded-t-3xl p-6 ${darkTheme ? 'bg-[#1c1c1e]' : 'bg-white'}`}
                        style={{ borderTopWidth: 1, borderTopColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
                    >
                        <View className="items-center mb-4">
                            <View className="w-12 h-12 rounded-full items-center justify-center mb-3" style={{ backgroundColor: TOAST.errorLight }}>
                                <Text className="text-2xl">⚠️</Text>
                            </View>
                            <Text className={`text-xl font-sans-bold text-center mb-2 ${darkTheme ? 'text-white' : 'text-black'}`}>
                                Address Mismatch Detected
                            </Text>
                            <Text className={`text-base text-center ${darkTheme ? 'text-gray-300' : 'text-gray-600'}`}>
                                Your rider reported that your building requires climbing stairs, but your address specifies ground floor/elevator.
                            </Text>
                        </View>

                        <View 
                            className={`p-4 rounded-xl mb-6 ${darkTheme ? 'bg-black/50' : 'bg-white'}`}
                            style={{ borderWidth: 1, borderColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
                        >
                            <Text className={`text-sm text-center font-sans-medium ${darkTheme ? 'text-gray-300' : 'text-gray-700'}`}>
                                Please approve the {formatMoney(order.pending_staircase_charge)} adjustment to receive your water at your door, or tap 'Leave at Ground Floor'.
                            </Text>
                        </View>

                        <View className="gap-3 mb-4">
                            <PressableScale
                                activeOpacity={0.8}
                                disabled={resolveLoading}
                                onPress={() => {
                                    resolveMismatch(
                                        { orderId: order.id, action: "approve_charge" },
                                        {
                                            onSuccess: () => Toast.success("Charge Approved", "Your rider is on their way up!"),
                                            onError: (err) => Toast.error("Action Failed", err.message)
                                        }
                                    );
                                }}
                                className="w-full py-4 rounded-full items-center"
                                style={{ backgroundColor: BRAND.primary, opacity: resolveLoading ? 0.7 : 1 }}
                            >
                                <Text className="text-white font-sans-bold text-lg">{resolveLoading ? "Processing..." : `Approve Charge (+${formatMoney(order.pending_staircase_charge)})`}</Text>
                            </PressableScale>

                            <PressableScale
                                activeOpacity={0.8}
                                disabled={resolveLoading}
                                onPress={() => {
                                    resolveMismatch(
                                        { orderId: order.id, action: "leave_ground" },
                                        {
                                            onSuccess: () => Toast.info("Notified Rider", "Please meet your rider at the ground floor."),
                                            onError: (err) => Toast.error("Action Failed", err.message)
                                        }
                                    );
                                }}
                                className="w-full py-4 rounded-full items-center"
                                style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200, opacity: resolveLoading ? 0.7 : 1 }}
                            >
                                <Text className={`font-sans-bold text-lg ${darkTheme ? 'text-white' : 'text-black'}`}>
                                    {resolveLoading ? "Processing..." : "Leave at Ground Floor"}
                                </Text>
                            </PressableScale>
                        </View>
                    </View>
                </View>
            </Modal>
        </View>
    );
}
