import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { queueOfflineAction } from '@/config/database';
import { UIThemeContext } from "@/context/ThemeContext";
import useWebSocket from "@/hooks/useWebSocket";
import { ApiError, errorMessage } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useAuth } from "@clerk/clerk-expo";
import { Ionicons } from '@expo/vector-icons';
import BottomSheet, { BottomSheetScrollView } from '@gorhom/bottom-sheet';
import * as ImagePicker from 'expo-image-picker';
import * as Location from "expo-location";
import { useContext, useEffect, useRef, useState, useMemo } from "react";
import {
    Dimensions,
    Linking,
    Platform,
    View,
    Modal,
    ScrollView,
    TouchableOpacity,
    StatusBar,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import { BRAND, TOAST } from "@/constants/brandColors";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";

/**
 * Straight-line metres between two points (haversine). Used only to decide
 * whether the drawn route is stale enough to re-request.
 */
function metresBetween(aLat: number, aLng: number, bLat: number, bLng: number) {
    const R = 6371000;
    const toRad = (d: number) => (d * Math.PI) / 180;
    const dLat = toRad(bLat - aLat);
    const dLng = toRad(bLng - aLng);
    const s =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
}

// Redraw once the rider has covered roughly a city block. Below this the
// polyline is visually identical and the request is pure quota burn.
const ROUTE_REFETCH_DISTANCE_M = 150;

// Utility to decode Google Directions polyline string
function decodePolyline(t: string, e: number = 5) {
    for (var n, o, u = 0, l = 0, r = 0, d = [], h = 0, i = 0, a = null, c = Math.pow(10, e || 5); u < t.length;) {
        a = null, h = 0, i = 0;
        do a = t.charCodeAt(u++) - 63, i |= (31 & a) << h, h += 5; while (a >= 32);
        n = 1 & i ? ~(i >> 1) : i >> 1, h = i = 0;
        do a = t.charCodeAt(u++) - 63, i |= (31 & a) << h, h += 5; while (a >= 32);
        o = 1 & i ? ~(i >> 1) : i >> 1, l += n, r += o, d.push([l / c, r / c]);
    }
    return d.map(function(t) {
        return { latitude: t[0], longitude: t[1] };
    });
}
import { Toast } from "@/lib/toast";
import PressableScale from "@/components/ui/PressableScale";
import SecureUpload from "@/Helpers/imageUpload";
import { useRejectDelivery } from "@/hooks/mutations/useRejectDelivery";
import { useRiderStore } from "@/stores/useRiderStore";
import { useRiderOrders, type RiderOrder } from "@/hooks/queries/useRiderData";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { smsCompletionUrl } from "@/utils/smsFallback";
import { Popup } from "@/lib/popup";
import { RiderActiveDeliverySkeleton } from "@/components/skeletons/ContextualSkeletons";
import { useOrderContacts, ContactInfo } from "@/hooks/queries/useOrderContacts";
import {
    hasBackgroundPermission,
    recordForegroundFix,
    requestTrackingPermissions,
    startRiderLocationTracking,
    stopRiderLocationTracking,
} from "@/services/locationTracking";

/**
 * `react-native-maps` is `require`d behind a platform check because it has no
 * web build. Its *types* import freely — `import type` is erased and emits no
 * require — so the components below are the real ones, and the web stand-in is
 * checked against the same props.
 */
import type MapViewType from 'react-native-maps';
import type {
    LatLng,
    MapMarkerProps,
    MapPolylineProps,
    MapUrlTileProps,
    MapViewProps,
    Provider,
} from 'react-native-maps';

/** Driven by ref (`animateCamera`), so `ref` is part of the declared props. */
let MapView: React.ComponentType<MapViewProps & { ref?: React.Ref<MapViewType> }>;
let Marker: React.ComponentType<MapMarkerProps>;
let Polyline: React.ComponentType<MapPolylineProps>;
let UrlTile: React.ComponentType<MapUrlTileProps>;
let PROVIDER_GOOGLE: Provider;

if (Platform.OS !== 'web') {
    const maps = require('react-native-maps');
    MapView = maps.default;
    Marker = maps.Marker;
    Polyline = maps.Polyline;
    UrlTile = maps.UrlTile;
    PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
} else {
    MapView = ({ style, children }: MapViewProps) => <View style={style}>{children}</View>;
    Marker = () => null;
    Polyline = () => null;
    UrlTile = () => null;
    PROVIDER_GOOGLE = 'google';
}

import { darkMapStyle, standardMapStyle } from "@/constants/mapStyles";
import { formatMoney } from "@/utils/money";

const { width } = Dimensions.get("window");

export default function ActiveDelivery() {
  const { currentTheme } = useContext(UIThemeContext);
  const darkTheme = currentTheme === "dark";
  // `getToken` is still needed for the multipart proof upload, which goes
  // through `apiFetch` rather than the hook client.
  const { getToken } = useAuth();
  const { get, post, put } = useApiRequest();
  const queryClient = useQueryClient();
  const router = useRouter();

  // Use React Query for single source of truth
  const { data: orders = [], isLoading } = useRiderOrders();

  const [activeOrder, setActiveOrder] = useState<RiderOrder | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentLocation, setCurrentLocation] = useState<Location.LocationObjectCoords | null>(null);
  const [routeCoords, setRouteCoords] = useState<LatLng[]>([]);
  // Origin + destination of the last route we asked for, so we can tell a
  // meaningful move from GPS jitter.
  const lastRouteFetch = useRef<{ lat: number; lng: number; destLat: number; destLng: number } | null>(null);
  const locationSubscription = useRef<Location.LocationSubscription | null>(null);
  const mapRef = useRef<MapViewType | null>(null);
  const riderId = useRiderStore((s) => s.riderId);
  const { mutateAsync: rejectDelivery, isPending: isRejecting } = useRejectDelivery();
  const [emptiesReceived, setEmptiesReceived] = useState<number>(0);
  const [sheetIndex, setSheetIndex] = useState<number>(0);

  // Cross-party contact info
  const { data: contactsData } = useOrderContacts(activeOrder?.id || null, activeOrder?.order_status || null);
  const contacts = contactsData?.contacts || [];
  const customerContact = contacts.find((c: ContactInfo) => c.role === "customer");
  const vendorContact = contacts.find((c: ContactInfo) => c.role === "vendor");

  const handleCall = (phone: string, role: string) => {
      if (!phone || phone === "N/A") {
          import("@/lib/toast").then(({ Toast }) => {
              Toast.error("Unavailable", `${role} phone number is not available.`);
          });
          return;
      }
      Linking.openURL(`tel:${phone}`);
  };

  // Derive empties expected from delivery_type and order items
  const computedEmptiesExpected = activeOrder?.delivery_type === 'quick_swap'
    ? (activeOrder?.order_item?.reduce((sum, i) => sum + (i.quantity || 0), 0) || 0)
    : 0;

  // Sync activeOrder with fetched orders array and allow search
  const activeOrdersList = useMemo(() => {
    let list = orders.filter((o) => 
        ["pending", "picked_up", "accepted", "ready", "mismatch_pending", "pending_review"].includes(o.order_status)
    );
    if (searchQuery) {
        const lowerQ = searchQuery.toLowerCase();
        list = list.filter((o) => 
            (o.id && o.id.toLowerCase().includes(lowerQ)) ||
            (o.user?.full_name && o.user.full_name.toLowerCase().includes(lowerQ)) ||
            (o.vendor?.business_name && o.vendor.business_name.toLowerCase().includes(lowerQ))
        );
    }
    return list;
  }, [orders, searchQuery]);

  useEffect(() => {
    if (activeOrdersList.length > 0) {
       const stillExists = activeOrdersList.find((o) => o.id === activeOrder?.id);
       if (stillExists) {
           if (stillExists.order_status !== activeOrder?.order_status) {
               setActiveOrder(stillExists);
           }
       } else {
           setActiveOrder(activeOrdersList[0]);
       }
    } else {
       if (activeOrder && !["delivered"].includes(activeOrder.order_status)) {
          setActiveOrder(null);
       }
    }
  }, [activeOrdersList, activeOrder?.id, activeOrder?.order_status]);

  useEffect(() => {
    if (activeOrder) {
      setEmptiesReceived(computedEmptiesExpected);
    }
  }, [activeOrder?.id]);

  // WebSocket hook for real-time order updates
  const { connected, sendMessage } = useWebSocket('rider', riderId || "", (updateData) => {
    // Handle order update from WebSocket
    if (__DEV__) console.log('Received order update via WebSocket:', updateData);
    
    // Update active order if it matches the updated order
    if (activeOrder && updateData.order_id === activeOrder.id) {
      setActiveOrder((prevOrder) =>
        prevOrder ? { ...prevOrder, order_status: updateData.status ?? prevOrder.order_status } : prevOrder,
      );
      
      // If delivered, clear the active order
      if (updateData.status === "delivered") {
        setActiveOrder(null);
        locationSubscription.current?.remove();
        Toast.success("Success", "Delivery completed!");
      }
    } else {
      // Trigger query refetch instead of raw fetch loop
      queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
    }
  });

  // BUG-LOC-01 FIX: Only request location and start aggressive polling if there is ACTUALLY an order.
  // This prevents the app from chewing battery and pinging WS constantly while idle.
  //
  // Two further corrections since:
  //
  //  - Accuracy was `High` at 5 s / 10 m, which holds the GPS radio open
  //    continuously. `Balanced` at 25 m is ample for a delivery dot on a city
  //    map and materially cheaper on battery.
  //  - Positions are only *reported* once the order is `picked_up`. Tracking
  //    from acceptance spent battery on the leg to the vendor and showed the
  //    rider's position to a customer whose order had not been collected yet.
  //    The map still needs the rider's own position before pickup, so the watch
  //    runs — it just does not report.
  useEffect(() => {
    let sub: Location.LocationSubscription | null = null;
    let cancelled = false;

    const watchLocation = async () => {
      const { status } = await Location.getForegroundPermissionsAsync();
      const granted =
        status === "granted"
          ? true
          : (await Location.requestForegroundPermissionsAsync()).status === "granted";

      if (!granted) {
        if (activeOrder) {
          Toast.error("Permission Denied", "Location access is required for delivery tracking.");
        }
        return;
      }

      if (!activeOrder) {
        try {
          const loc = await Location.getLastKnownPositionAsync();
          if (loc && !cancelled) setCurrentLocation(loc.coords);
        } catch (e) { /* the map falls back to the order's coordinates */ }
        return;
      }

      sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.Balanced, timeInterval: 15000, distanceInterval: 25 },
        (loc) => {
          setCurrentLocation(loc.coords);

          if (activeOrder.order_status !== "picked_up") return;

          // Durable first. This used to be a socket send inside a `try/catch`
          // that only logged, so every fix produced while the socket was down —
          // exactly when the customer most wants the dot to move — was silently
          // discarded. The buffer keeps it and the next flush sends it.
          recordForegroundFix(loc, activeOrder.id).catch(() => {});

          // Then the socket, as the low-latency path when one is open.
          try {
            sendMessage({
              action: 'location_update',
              lat: loc.coords.latitude,
              lng: loc.coords.longitude,
              order_id: activeOrder.id
            });
          } catch (e) { if (__DEV__) console.error("Caught Unhandled Exception:", e); }
        }
      );
      locationSubscription.current = sub;
    };

    watchLocation();

    return () => {
      cancelled = true;
      if (sub) {
        sub.remove();
      }
    };
  }, [activeOrder?.id, activeOrder?.order_status, sendMessage]);

  // Background reporting follows the order's own lifecycle, not this screen's.
  // The rider taps "Navigate" and leaves for the whole delivery; the foreground
  // watcher above dies with the screen, and everything after that point — which
  // is the entire journey to the customer — used to go unrecorded.
  useEffect(() => {
    // `activeOrder` is null until the orders query resolves. Acting on that
    // would stop a foreground service that is legitimately running — opening
    // this screen mid-delivery would end the customer's live tracking.
    if (isLoading) return;

    const status = activeOrder?.order_status;
    if (activeOrder && status === "picked_up") {
      startRiderLocationTracking(activeOrder.id).then((started) => {
        if (!started && __DEV__) {
          console.warn("[ActiveDelivery] background tracking unavailable; foreground only");
        }
      });
    } else if (!activeOrder || status === "delivered" || status === "cancelled") {
      stopRiderLocationTracking();
    }
  }, [isLoading, activeOrder?.id, activeOrder?.order_status]);

  /**
   * True when the drawn route is stale: no route yet, the destination changed
   * (pickup → dropoff on status change), or the rider has moved far enough that
   * the polyline's start no longer matches where they are.
   */
  const shouldRefetchRoute = (loc: LatLng, destLat: number, destLng: number) => {
    const last = lastRouteFetch.current;
    if (!last) return true;
    if (last.destLat !== destLat || last.destLng !== destLng) return true;
    return (
      metresBetween(last.lat, last.lng, loc.latitude, loc.longitude) >
      ROUTE_REFETCH_DISTANCE_M
    );
  };

  /**
   * Fetch the road route via the backend proxy.
   *
   * This used to call Google Directions directly with the app's Maps key. That
   * key is now restricted to the Maps SDK for `com.drop.rider`, so the direct
   * call would be rejected outright — and a key permissive enough to work from
   * JS would be extractable from the APK. The server holds an IP-restricted key
   * and caches identical legs.
   *
   * A failure here is cosmetic: the map still shows both markers, so we degrade
   * to no polyline rather than interrupting a delivery in progress.
   */
  const fetchRoute = async (startLng: number, startLat: number, endLng: number, endLat: number) => {
    lastRouteFetch.current = { lat: startLat, lng: startLng, destLat: endLat, destLng: endLng };
    try {
      const data = await get<{ polyline?: string }>(
        RiderApiRoutes.Directions(startLat, startLng, endLat, endLng).path
      );
      if (data?.polyline) {
        setRouteCoords(decodePolyline(data.polyline));
      }
    } catch (e) {
      if (__DEV__) console.warn("Route fetch failed:", errorMessage(e));
    }
  };

  useEffect(() => {
    if (currentLocation && activeOrder) {
      // Smooth animation to current location
      if (mapRef.current && Platform.OS !== 'web') {
        mapRef.current.animateCamera(
          {
            center: { latitude: currentLocation.latitude, longitude: currentLocation.longitude },
            pitch: 0,
            heading: currentLocation.heading || 0,
            altitude: 1000,
            zoom: 16
          },
          { duration: 1000 }
        );
      }

      const status = activeOrder.order_status;
      let destLat: number | null = null;
      let destLng: number | null = null;

      if (status === "pending" || status === "accepted" || status === "ready") {
        destLat = activeOrder.lat_from ?? null;
        destLng = activeOrder.lng_from ?? null;
      } else if (status === "picked_up") {
        destLat = activeOrder.lat ?? null;
        destLng = activeOrder.lng ?? null;
      }

      // The location watcher fires every 5s / 10m. Re-requesting the route on
      // every tick meant ~12 Directions calls per minute per active rider —
      // enough to burn the daily quota with a handful of riders on the road,
      // for a polyline that barely changes. Only refetch when the destination
      // changes or the rider has actually moved a block.
      if (destLat != null && destLng != null && shouldRefetchRoute(currentLocation, destLat, destLng)) {
        fetchRoute(currentLocation.longitude, currentLocation.latitude, destLng, destLat);
      }
    } else {
      setRouteCoords([]);
      lastRouteFetch.current = null;
    }
  }, [currentLocation?.latitude, currentLocation?.longitude, activeOrder?.id, activeOrder?.order_status]);

  const updateDeliveryStatus = async (status: string, proofUrl?: string) => {
    if (!activeOrder) return;
    
    const previousStatus = activeOrder.order_status;
    const previousOrder = { ...activeOrder };
    // Optimistic UI Update: Flip the UI state BEFORE network response
    // Do NOT clear activeOrder or show a success toast yet.
    setActiveOrder({ ...activeOrder, order_status: status });
    
    try {
      const payload: { status: string; proof_url?: string; empties_received?: number } = { status };
      if (proofUrl) payload.proof_url = proofUrl;
      if (status === "delivered") payload.empties_received = emptiesReceived;

      await put(RiderApiRoutes.UpdateDeliveryStatus(activeOrder.id).path, payload);

      // Only NOW, after server confirmation, treat delivery as complete.
      if (status === "delivered") {
          setActiveOrder(null);
          locationSubscription.current?.remove();
          // A quick_swap delivery just made this rider liable for the customer's
          // empties, so the debt they see must not be a stale pre-delivery number.
          queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-debt'] });
          queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-ledger'] });
          Toast.success("Success", "Delivery completed!");
      } else {
        queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
      }
    } catch (e) {
      setActiveOrder({ ...previousOrder, order_status: previousStatus });

      if (e instanceof ApiError && e.status === 401) return; // already signed out

      // A 4xx is the server refusing on the merits — a status transition that is
      // not legal, a proof photo that is mandatory. Queueing it would replay the
      // same refusal forever. Show the reason and stop.
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        Toast.error("Update Failed", errorMessage(e, "Could not update delivery status."));
        return;
      }

      // Transport failure or 5xx: ALWAYS queue for retry, delivered included —
      // money and notifications depend on this reaching the server eventually.
      await queueOfflineAction(activeOrder.id, "UPDATE_DELIVERY_STATUS", JSON.stringify({ status, proof_url: proofUrl, empties_received: status === "delivered" ? emptiesReceived : undefined }));
      Toast.info("Saved Offline", "No connection — this update will sync automatically once you're back online.");
    }
  };

  /**
   * Pickup is where background location starts mattering, so it is where we ask
   * for it — never at launch. Android 11+ will not even offer "Allow all the
   * time" in the same prompt as the foreground one, and a permission dialog that
   * arrives before the rider has seen why it is needed is the main cause of a
   * permanent denial. Explaining first, once, at the moment it becomes true.
   *
   * A refusal does not block the pickup: the delivery still works, the customer
   * just sees a dot that only moves while the rider has the app open.
   */
  const confirmPickup = async () => {
    if (await hasBackgroundPermission()) {
      updateDeliveryStatus("picked_up");
      return;
    }

    Popup.show({
      title: "Share your location during delivery",
      message:
        "Your customer watches your progress on a live map while you deliver. " +
        "For that to keep working after you switch to your navigation app, Drop " +
        "needs location access set to \"Allow all the time\".\n\n" +
        "It is used only between pickup and delivery, and stops the moment you " +
        "complete the order.",
      confirmText: "Continue",
      cancelText: "Not now",
      onConfirm: async () => {
        const result = await requestTrackingPermissions();
        if (result === "denied") {
          Toast.error("Permission Denied", "Location access is required for delivery tracking.");
          return;
        }
        if (result === "foreground-only") {
          Toast.info(
            "Limited tracking",
            "Your customer will only see you move while Drop is open. You can change this in Settings."
          );
        }
        updateDeliveryStatus("picked_up");
      },
      onCancel: () => updateDeliveryStatus("picked_up"),
    });
  };

  const captureProofAndDeliver = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      if (emptiesReceived < computedEmptiesExpected) {
        Toast.error("Permission Required", "Camera access is MANDATORY because of missing empty bottles. We need proof.");
        return;
      }
      Toast.info('Permission Denied', 'Camera access required to take proof of delivery photos. Continuing without photo.');
      updateDeliveryStatus("delivered");
      return;
    }

    try {
      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [4, 3],
        quality: 0.5,
      });

      if (result.canceled) {
        Toast.info("Canceled", "Proof of delivery photo capture was canceled.");
        return;
      }

      if (!result.canceled) {
        const photoUri = result.assets[0].uri;
        // Upload proof photo securely to S3
        try {
          const uploadResult = await SecureUpload(photoUri, `proof_${activeOrder?.id}`, getToken);
          updateDeliveryStatus("delivered", uploadResult?.secure_url || undefined);
        } catch (uploadErr) {
          if (emptiesReceived < computedEmptiesExpected) {
            Toast.error("Proof Required", "Photo upload failed, but proof is mandatory for missing bottles. Please check your connection and try again.");
            return;
          }
          // No deficit — safe to complete without photo
          updateDeliveryStatus("delivered");
        }
      }
    } catch (e) {
       if (__DEV__) console.error("Image picker error:", e);
       if (emptiesReceived < computedEmptiesExpected) {
         Toast.error("Proof Required", "Camera error occurred, but proof is mandatory for missing bottles. Please try again.");
         return;
       }
       updateDeliveryStatus("delivered");
    }
  };

  const openNavigation = (lat: number, lng: number, label: string) => {
    const url = Platform.select({
      ios: `maps://app?daddr=${lat},${lng}&dirflg=d`,
      android: `google.navigation:q=${lat},${lng}`
    });
    Linking.openURL(url!);
  };

  const [isReportingMismatch, setIsReportingMismatch] = useState(false);
  const [showMismatchSheet, setShowMismatchSheet] = useState(false);
  const [selectedMismatchFloor, setSelectedMismatchFloor] = useState<number>(1);

  const reportAddressMismatch = async (floorLevel: number) => {
    if (!activeOrder) return;
    setIsReportingMismatch(true);
    try {
      await post(RiderApiRoutes.ReportMismatch(activeOrder.id).path, {
        actual_floor_level: floorLevel,
      });
      setShowMismatchSheet(false);
      Toast.success("Dispute Raised", "The customer has been notified to correct their floor level. You will be compensated for the waiting time.");
      // Invalidate to fetch the updated state
      queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 401) return;
      Toast.error("Error", errorMessage(e, "Failed to report mismatch"));
    } finally {
      setIsReportingMismatch(false);
    }
  };

  const [showCancelSheet, setShowCancelSheet] = useState(false);
  const [isCanceling, setIsCanceling] = useState(false);
  const [cancelReason, setCancelReason] = useState<string>("other");
  const [cancelDetails, setCancelDetails] = useState<string>("");

  const cancelDelivery = async () => {
    if (!activeOrder) return;
    setIsCanceling(true);
    try {
      await put(RiderApiRoutes.CancelOrder(activeOrder.id).path, {
        reason: cancelReason,
        details: cancelDetails,
      });
      setShowCancelSheet(false);
      Toast.success("Delivery Cancelled", "Your delivery assignment has been cancelled/rejected successfully.");
      queryClient.invalidateQueries({ queryKey: ['rider', 'orders'] });
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 401) return;
      Toast.error("Error", errorMessage(e, "Failed to cancel delivery"));
    } finally {
      setIsCanceling(false);
    }
  };

  useEffect(() => {
    // Initial fetch handled directly by useRiderOrders hook via React Query
  }, []);

  // ── Zoom controls ──
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

  const STATUS_LABELS: Record<string, string> = {
    pending: "New delivery assigned",
    accepted: "Waiting for vendor to prepare",
    ready: "Ready for pickup",
    picked_up: "Picked up",
    delivered: "Delivered",
    mismatch_pending: "Dispute Paused: Waiting for Customer",
  };

  const snapPoints = ["35%", "55%", "90%"];
  const bottomSheetRef = useRef<BottomSheet>(null);

  const mapOverlays = useMemo(() => {
    if (!Marker) return null;
    const overlays = [];
    
    // OSRM Route Polyline
    if (routeCoords.length > 0 && Polyline) {
        overlays.push(
            <Polyline 
                key="route-polyline"
                coordinates={routeCoords} 
                strokeWidth={5} 
                strokeColor={BRAND.primary} 
            />
        );
    }
    
    // Rider live position
    if (currentLocation) {
        overlays.push(
            <Marker
                key="rider-position"
                coordinate={{ latitude: currentLocation.latitude, longitude: currentLocation.longitude }}
                title="You"
                pinColor={BRAND.primary}
            />
        );
    }
    // Render all active orders on the map for search and visualization
    activeOrdersList.forEach((order) => {
        const isSelected = activeOrder?.id === order.id;
        
        // Pickup marker (vendor)
        if (order.lat_from && order.lng_from) {
            overlays.push(
                <Marker
                    key={`pickup-${order.id}`}
                    coordinate={{ latitude: order.lat_from, longitude: order.lng_from }}
                    title={`Pickup #${order.id.substring(0, 8)}`}
                    description={order.vendor?.business_name || "Vendor"}
                    pinColor={isSelected ? BRAND.primary : "gray"}
                    onPress={() => setActiveOrder(order)}
                />
            );
        }
        
        // Dropoff marker (customer)
        if (order.lat && order.lng) {
            overlays.push(
                <Marker
                    key={`dropoff-${order.id}`}
                    coordinate={{ latitude: order.lat, longitude: order.lng }}
                    title={`Dropoff #${order.id.substring(0, 8)}`}
                    description="Customer"
                    pinColor={isSelected ? TOAST.success : "orange"}
                    onPress={() => setActiveOrder(order)}
                />
            );
        }
    });
    
    return overlays;
  }, [routeCoords, currentLocation?.latitude, currentLocation?.longitude, activeOrder?.id, activeOrdersList]);

  return (
    <View className={`flex-1 ${darkTheme ? "bg-surface" : "bg-white"}`}>
      <StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />

      <SafeAreaView edges={["top"]} style={{ backgroundColor: darkTheme ? "#000" : "#fff", zIndex: 50 }}>
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
                    Active Delivery
                </Text>
            </View>
        </View>
      </SafeAreaView>

      {/* ── Live Map & Zoom Controls ── */}
      <View className={`flex-1 ${darkTheme ? "bg-surface-container" : "bg-white"}`}>
        {/* Search Bar Overlay */}
        <View className="absolute top-4 left-4 right-4 z-10">
            <View className={`flex-row items-center px-4 py-3 rounded-full border ${darkTheme ? "bg-black border-gray-800" : "bg-white border-gray-100"}`} style={darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8, elevation: 5 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 4, elevation: 3 }}>
                <Ionicons name="search" size={20} color={darkTheme ? "#89929b" : "#94a3b8"} className="mr-2" />
                <TextInput
                    placeholder="Search active deliveries..."
                    placeholderTextColor={darkTheme ? "#89929b" : "#94a3b8"}
                    value={searchQuery}
                    onChangeText={setSearchQuery}
                    style={{ color: darkTheme ? "#fff" : "#0f172a", flex: 1, fontSize: 16 }}
                />
            </View>
        </View>

        {MapView ? (
          <View style={{ flex: 1 }}>
            <MapView
              ref={mapRef}
              // 🟢 FREE OPEN SOURCE MVP MODE 
              // Uncomment this block for MVP:
              // provider={undefined}
              // 🔴 PRODUCTION GOOGLE MAPS MODE 
              // Uncomment this block for Production:
              provider={PROVIDER_GOOGLE}
              // `googleMapId`, not `mapId` — react-native-maps names it the former, so
              // the prop every map screen in all three apps passed was dropped and cloud
              // styling has never once been applied. A misspelt prop is silent here.
              googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
              style={{ flex: 1 }}
              initialRegion={currentLocation ? {
                latitude: currentLocation.latitude,
                longitude: currentLocation.longitude,
                latitudeDelta: 0.015,
                longitudeDelta: 0.015,
              } : {
                latitude: -1.2921,
                longitude: 36.8219,
                latitudeDelta: 0.05,
                longitudeDelta: 0.05,
              }}
              showsUserLocation={true}
              showsMyLocationButton={true}
            >
              {mapOverlays}
            </MapView>
            
            {/* Zoom Controls Overlay - Repositioned below 'My Location' button */}
            {activeOrder && (
              <View className="absolute top-44 right-4 pointer-events-auto flex-col gap-3">
                <PressableScale
                  onPress={() => handleZoom(true)}
                  className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-surface-variant border-outline-variant" : "bg-white border-gray-200"}`}
                >
                  <Text className={`text-xl font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>+</Text>
                </PressableScale>
                <PressableScale
                  onPress={() => handleZoom(false)}
                  className={`w-10 h-10 rounded-full items-center justify-center border ${darkTheme ? "bg-surface-variant border-outline-variant" : "bg-white border-gray-200"}`}
                >
                  <Text className={`text-xl font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-800"}`}>−</Text>
                </PressableScale>
              </View>
            )}
          </View>
        ) : (
          <View className="flex-1 items-center justify-center">
            <Ionicons name="map-outline" size={64} color={BRAND.primary} />
            {currentLocation && (
              <Text className={`text-xs mt-2 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                📍 {currentLocation.latitude?.toFixed(4)}, {currentLocation.longitude?.toFixed(4)}
              </Text>
            )}
          </View>
        )}
      </View>

      <BottomSheet
        ref={bottomSheetRef}
        snapPoints={snapPoints}
        enablePanDownToClose={false}
        onChange={(index) => setSheetIndex(index)}
        backgroundStyle={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white }}
        handleIndicatorStyle={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}
        style={{ elevation: 10, zIndex: 10 }}
      >
        <BottomSheetScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 8, paddingBottom: 120 }}>
          {isLoading ? (
            <RiderActiveDeliverySkeleton />
          ) : activeOrder ? (
            <>
              <View className={`p-4 rounded-3xl border ${darkTheme ? "bg-surface-container border-outline-variant" : "bg-white border-gray-100"}`}>
                <View className="flex-row justify-between items-start">
                  <View>
                    <Text className={`font-sans-semibold text-lg ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
                      Order #{activeOrder.id?.substring(0, 8)}
                    </Text>
                    <Text className={`text-sm mt-1 font-sans-semibold ${darkTheme ? "text-accentbg" : "text-accentbg"}`}>
                      {STATUS_LABELS[activeOrder.order_status] || activeOrder.order_status}
                    </Text>
                    <Text className={`text-sm mt-1.5 ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>
                      {formatMoney(activeOrder.total_amount)} · {activeOrder.order_item?.length || 0} item(s)
                    </Text>
                    {activeOrder.payment_method === "cash" && (
                      <View className="mt-2 flex-row items-center gap-1 bg-amber-500/10 px-2 py-1 rounded-md self-start border border-amber-500/20">
                        <Ionicons name="cash" size={14} color="#f59e0b" />
                        <Text className="text-xs font-sans-bold text-amber-600">Collect Cash: {formatMoney(activeOrder.total_amount)}</Text>
                      </View>
                    )}
                  </View>
                </View>

                {/* Navigation Links */}
                <View className={`flex-row gap-2 mt-4 pt-4 border-t ${darkTheme ? "border-outline-variant" : "border-gray-200"}`}>
                  <PressableScale 
                    onPress={() => openNavigation(activeOrder.lat_from || -1.2921, activeOrder.lng_from || 36.8219, "Pickup")}
                    className={`flex-1 py-3 rounded-xl items-center border flex-row justify-center gap-1 ${(activeOrder.order_status === "accepted" || activeOrder.order_status === "ready") ? "bg-accentbg/10 border-accentbg/30" : "opacity-30 " + (darkTheme ? "border-outline-variant" : "border-gray-200")}`}
                    disabled={(activeOrder.order_status !== "accepted" && activeOrder.order_status !== "ready")}
                  >
                    <Ionicons name="compass-outline" size={18} color={(activeOrder.order_status === "accepted" || activeOrder.order_status === "ready") ? BRAND.primary : "#9ca3af"} />
                    <Text className={`font-sans-semibold ${(activeOrder.order_status === "accepted" || activeOrder.order_status === "ready") ? "text-accentbg" : darkTheme ? "text-on-surface" : "text-gray-800"}`}>Nav to Pickup</Text>
                  </PressableScale>
                  
                  <PressableScale 
                    onPress={() => openNavigation(activeOrder.lat || -1.2921, activeOrder.lng || 36.8219, "Dropoff")}
                    className={`flex-1 py-3 rounded-xl items-center border flex-row justify-center gap-1 ${(activeOrder.order_status === "picked_up") ? "bg-accentbg/10 border-accentbg/30" : "opacity-30 " + (darkTheme ? "border-outline-variant" : "border-gray-200")}`}
                    disabled={(activeOrder.order_status !== "picked_up")}
                  >
                    <Ionicons name="location-outline" size={18} color={(activeOrder.order_status === "picked_up") ? BRAND.primary : "#9ca3af"} />
                    <Text className={`font-sans-semibold ${(activeOrder.order_status === "picked_up") ? "text-accentbg" : darkTheme ? "text-on-surface" : "text-gray-800"}`}>Nav to Dropoff</Text>
                  </PressableScale>
                </View>

                {/* ── Cross-Party Contact Cards ────────────────────────── */}
                {contacts.length > 0 && (
                  <View className={`mt-4 pt-4 border-t ${darkTheme ? "border-outline-variant" : "border-gray-200"}`}>
                    <Text className={`font-sans-bold text-base mb-3 ${darkTheme ? "text-white" : "text-gray-900"}`}>Contact</Text>
                    <View className="gap-2">
                      {customerContact && (
                        <PressableScale
                          onPress={() => handleCall(customerContact.phone, "Customer")}
                          className="flex-row items-center gap-3 p-3 rounded-xl"
                          style={{
                            backgroundColor: darkTheme ? 'rgba(16, 185, 129, 0.08)' : 'rgba(16, 185, 129, 0.06)',
                            borderWidth: 1,
                            borderColor: darkTheme ? 'rgba(16, 185, 129, 0.15)' : 'rgba(16, 185, 129, 0.12)',
                          }}
                        >
                          <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: TOAST.success + '20' }}>
                            <Ionicons name="person" size={18} color={TOAST.success} />
                          </View>
                          <View className="flex-1">
                            <Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-slate-900"}`}>{customerContact.name}</Text>
                            <Text className={`text-xs ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Tap to call customer</Text>
                          </View>
                          <View className="w-9 h-9 rounded-full items-center justify-center" style={{ backgroundColor: TOAST.success }}>
                            <Ionicons name="call" size={16} color="#fff" />
                          </View>
                        </PressableScale>
                      )}
                      {vendorContact && (
                        <PressableScale
                          onPress={() => handleCall(vendorContact.phone, "Vendor")}
                          className="flex-row items-center gap-3 p-3 rounded-xl"
                          style={{
                            backgroundColor: darkTheme ? 'rgba(2, 149, 247, 0.08)' : 'rgba(2, 149, 247, 0.06)',
                            borderWidth: 1,
                            borderColor: darkTheme ? 'rgba(2, 149, 247, 0.15)' : 'rgba(2, 149, 247, 0.12)',
                          }}
                        >
                          <View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary + '20' }}>
                            <Ionicons name="storefront" size={18} color={BRAND.primary} />
                          </View>
                          <View className="flex-1">
                            <Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-slate-900"}`}>{vendorContact.name}</Text>
                            <Text className={`text-xs ${darkTheme ? "text-slate-500" : "text-slate-400"}`}>Tap to call vendor</Text>
                          </View>
                          <View className="w-9 h-9 rounded-full items-center justify-center" style={{ backgroundColor: BRAND.primary }}>
                            <Ionicons name="call" size={16} color="#fff" />
                          </View>
                        </PressableScale>
                      )}
                    </View>
                  </View>
                )}
              </View>

              {/* Action Buttons */}
              <View className="mt-4 gap-3">
                {(activeOrder.order_status === "pending" || activeOrder.order_status === "accepted") && (
                  <PressableScale
                    onPress={() => {
                      Popup.show({
                        title: "Reject Delivery",
                        message: "Are you sure you want to reject this delivery? It will be reassigned to another rider.",
                        cancelText: "Cancel",
                        confirmText: "Reject",
                        isDestructive: true,
                        onConfirm: async () => {
                            Popup.hide();
                            try {
                              await rejectDelivery(activeOrder.id);
                              setActiveOrder(null);
                              Toast.success("Rejected", "Delivery has been reassigned.");
                            } catch (e: unknown) {
                              Toast.error("Error", (e as Error).message || "Failed to reject delivery");
                            }
                          }
                      });
                    }}
                    disabled={isRejecting}
                    className="py-4 rounded-3xl items-center border"
                    style={{ borderColor: TOAST.error + '4D', backgroundColor: darkTheme ? TOAST.error + '1A' : TOAST.error + '0D' }}
                  >
                    <View className="flex-row items-center gap-1">
                      {!isRejecting && <Ionicons name="close-circle-outline" size={20} color={TOAST.error} />}
                      <Text style={{ color: TOAST.error }} className="font-sans-bold text-lg">
                        {isRejecting ? "Rejecting..." : "Reject Delivery"}
                      </Text>
                    </View>
                  </PressableScale>
                )}
                {activeOrder.order_status === "ready" && (
                  <PressableScale onPress={confirmPickup} className="py-4 rounded-3xl items-center shadow-sm" style={{ backgroundColor: BRAND.primary }}>
                    <Text className="text-white font-sans-bold text-lg">Mark as Picked Up</Text>
                  </PressableScale>
                )}
                {(activeOrder.order_status === "picked_up") && (
                  <>
                    {/* Bottle Counter UI */}
                    <View className={`my-4 p-4 rounded-2xl border ${darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}>
                      <Text className={`font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-gray-900"}`}>Empty Bottles Retrieved</Text>
                      <View className="flex-row items-center justify-between">
                        <PressableScale onPress={() => setEmptiesReceived(Math.max(0, emptiesReceived - 1))} className="w-12 h-12 rounded-full items-center justify-center border" style={{ borderColor: TOAST.error + '33', backgroundColor: TOAST.error + '1A' }}>
                          <Text style={{ color: TOAST.error }} className="font-sans-bold text-2xl">-</Text>
                        </PressableScale>
                        <Text className={`text-3xl font-sans-extrabold ${darkTheme ? "text-white" : "text-gray-900"}`}>{emptiesReceived}</Text>
                        <PressableScale onPress={() => setEmptiesReceived(emptiesReceived + 1)} className="w-12 h-12 rounded-full items-center justify-center border" style={{ borderColor: TOAST.success + '33', backgroundColor: TOAST.success + '1A' }}>
                          <Text style={{ color: TOAST.success }} className="font-sans-bold text-2xl">+</Text>
                        </PressableScale>
                      </View>
                      
                      {/* Deficit Alert */}
                      {(computedEmptiesExpected > emptiesReceived) && (
                        <View className="mt-3 p-3 rounded-xl border flex-row items-start gap-2" style={{ borderColor: TOAST.error + '33', backgroundColor: TOAST.error + '1A' }}>
                          <Ionicons name="warning-outline" size={18} color={TOAST.error} style={{ marginTop: 2 }} />
                          <View className="flex-1">
                            <Text style={{ color: TOAST.error }} className="text-sm font-sans-semibold">{computedEmptiesExpected - emptiesReceived} Bottles Missing (Deficit)</Text>
                            <Text style={{ color: TOAST.error, opacity: 0.8 }} className="text-xs mt-1">Proof Photo is mandatory when reporting missing bottles.</Text>
                          </View>
                        </View>
                      )}
                      
                      {/* Surplus Alert */}
                      {(computedEmptiesExpected < emptiesReceived) && (
                        <View className="mt-3 p-3 rounded-xl border flex-row items-center gap-2" style={{ borderColor: TOAST.success + '33', backgroundColor: TOAST.success + '1A' }}>
                          <Ionicons name="checkmark-circle-outline" size={18} color={TOAST.success} />
                          <Text style={{ color: TOAST.success }} className="text-sm font-sans-semibold">Extra empty bottles retrieved.</Text>
                        </View>
                      )}
                    </View>

                    <PressableScale onPress={captureProofAndDeliver} className="py-4 rounded-3xl items-center shadow-sm flex-row justify-center gap-2" style={{ backgroundColor: BRAND.primary }}>
                      <Ionicons name="camera-outline" size={24} color={BRAND.white} />
                      <Text className="text-white font-sans-bold text-lg">Dropoff & Take Photo</Text>
                    </PressableScale>

                    <PressableScale 
                      onPress={() => setShowMismatchSheet(true)}
                      disabled={isReportingMismatch}
                      className="py-3 mt-2 rounded-xl items-center border flex-row justify-center gap-2"
                      style={{ borderColor: TOAST.error + '4D', backgroundColor: darkTheme ? TOAST.error + '1A' : TOAST.error + '0D' }}
                    >
                      {!isReportingMismatch && <Ionicons name="warning-outline" size={18} color={TOAST.error} />}
                      <Text style={{ color: TOAST.error }} className="font-sans-bold text-base">
                        {isReportingMismatch ? "Reporting..." : "Report Floor Level Mismatch"}
                      </Text>
                    </PressableScale>

                    <PressableScale 
                      onPress={() => router.push({ pathname: "/(screens)/BottleRejection", params: { orderId: activeOrder.id } })}
                      className="py-3 mt-2 rounded-xl items-center border flex-row justify-center gap-2"
                      style={{ borderColor: TOAST.error + '4D', backgroundColor: darkTheme ? TOAST.error + '1A' : TOAST.error + '0D' }}
                    >
                      <Ionicons name="flag-outline" size={18} color={TOAST.error} />
                      <Text style={{ color: TOAST.error }} className="font-sans-bold text-base">
                        Flag Damaged Empty Bottle
                      </Text>
                    </PressableScale>

                    {/* Quick Deliver */}
                    {(emptiesReceived >= computedEmptiesExpected) && (
                      <PressableScale onPress={() => updateDeliveryStatus("delivered")} className="py-4 mt-2 rounded-3xl items-center shadow-sm flex-row justify-center gap-2" style={{ backgroundColor: BRAND.primary }}>
                        <Ionicons name="checkmark-circle-outline" size={24} color={BRAND.white} />
                        <Text className="text-white font-sans-bold text-lg">Skip Photo, Mark Delivered</Text>
                      </PressableScale>
                    )}

                    {/* GSM SMS fallback — rendered only when a gateway exists.
                        Unconfigured, this used to text a placeholder number the
                        platform does not own: the rider saw the message send and
                        believed the delivery was recorded, while the order stayed
                        open and their float stayed locked. See utils/smsFallback. */}
                    {smsCompletionUrl(activeOrder.id) && (
                      <PressableScale
                         onPress={() => {
                           const url = smsCompletionUrl(activeOrder.id);
                           if (url) Linking.openURL(url);
                         }}
                         className={`py-4 rounded-3xl items-center border ${darkTheme ? "border-gray-800 bg-white/5" : "border-gray-200 bg-white"}`}>
                        <Text className={`font-sans-bold text-sm ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>
                          No Data? SMS to Complete
                        </Text>
                      </PressableScale>
                    )}
                  </>
                )}
                {activeOrder.order_status === "mismatch_pending" && (
                  <View className="py-6 items-center">
                    <Ionicons name="hourglass-outline" size={64} color={TOAST.error} className="mb-4" />
                    <Text style={{ color: TOAST.error }} className={`text-center font-sans-bold text-lg`}>
                      Delivery Paused
                    </Text>
                    <Text className={`text-center mt-2 mb-6 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                      Waiting for the customer to come downstairs. Once you hand over the bottles on the ground floor, you can complete the delivery below.
                    </Text>
                    
                    <PressableScale onPress={captureProofAndDeliver} className="py-4 px-6 rounded-3xl items-center shadow-sm flex-row justify-center gap-2 mb-3" style={{ backgroundColor: BRAND.primary }}>
                      <Ionicons name="camera-outline" size={24} color={BRAND.white} />
                      <Text className="text-white font-sans-bold text-lg">Dropoff & Take Photo</Text>
                    </PressableScale>

                    {/* Quick Deliver */}
                    {(emptiesReceived >= computedEmptiesExpected) && (
                      <PressableScale onPress={() => updateDeliveryStatus("delivered")} className="py-4 px-6 rounded-3xl items-center shadow-sm flex-row justify-center gap-2" style={{ backgroundColor: BRAND.primary }}>
                        <Ionicons name="checkmark-circle-outline" size={24} color={BRAND.white} />
                        <Text className="text-white font-sans-bold text-lg">Skip Photo, Mark Delivered</Text>
                      </PressableScale>
                    )}
                  </View>
                )}
                {activeOrder.order_status === "pending_review" && (
                  <View className="py-6 items-center">
                    <Ionicons name="search-outline" size={64} color={TOAST.error} className="mb-4" />
                    <Text style={{ color: TOAST.error }} className={`text-center font-sans-bold text-lg`}>
                      Under Review
                    </Text>
                    <Text className={`text-center mt-2 mb-6 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                      You've flagged a damaged bottle. Please wait 2-5 minutes while admin reviews the photos.
                    </Text>
                  </View>
                )}

                {/* Cancel / Report Issue Button */}
                <View className="mt-4 pt-4 border-t" style={{ borderTopColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' }}>
                  <PressableScale 
                    onPress={() => setShowCancelSheet(true)}
                    className="py-3 rounded-xl items-center border flex-row justify-center gap-2"
                    style={{ borderColor: TOAST.error + '33', backgroundColor: darkTheme ? TOAST.error + '1A' : TOAST.error + '0D' }}
                  >
                    <Ionicons name="alert-circle-outline" size={18} color={TOAST.error} />
                    <Text style={{ color: TOAST.error }} className="font-sans-bold text-sm">
                      Report Issue / Cancel Delivery
                    </Text>
                  </PressableScale>
                </View>

              </View>
            </>
          ) : (
            <View className="flex-1 items-center justify-center py-12 mt-4">
              <Ionicons name="cafe-outline" size={64} color={BRAND.primary} />
              <Text className={`text-lg mt-4 text-center ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                No active deliveries right now. You'll be notified when a new order is assigned.
              </Text>
            </View>
          )}
        </BottomSheetScrollView>
      </BottomSheet>

      {/* Address Mismatch Bottom Sheet */}
      <Modal visible={showMismatchSheet} transparent animationType="slide">
        <View className="flex-1 justify-end bg-black/60">
          <View className={`rounded-t-3xl p-6 ${darkTheme ? 'bg-surface-container' : 'bg-white'}`}>
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? 'text-white' : 'text-gray-900'}`}>Report Address Mismatch</Text>
              <PressableScale onPress={() => setShowMismatchSheet(false)} className="w-8 h-8 rounded-full bg-gray-200/20 items-center justify-center">
                <Text className={`text-lg font-sans-bold ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>✕</Text>
              </PressableScale>
            </View>
            <Text className={`mb-4 ${darkTheme ? 'text-gray-300' : 'text-gray-600'}`}>
              Select the actual floor the customer is located on. This will pause the delivery and require them to pay the correct surcharge before you can complete the delivery.
            </Text>
            
            <View className="flex-row flex-wrap gap-2 mb-6 justify-center">
              {[1, 2, 3, 4, 5, 6, 7].map((floor) => (
                <PressableScale
                  key={floor}
                  onPress={() => setSelectedMismatchFloor(floor)}
                  className={`w-14 h-14 rounded-xl items-center justify-center border`}
                  style={{
                    backgroundColor: selectedMismatchFloor === floor ? BRAND.primary : (darkTheme ? BRAND.gray800 : BRAND.gray100),
                    borderColor: selectedMismatchFloor === floor ? BRAND.primary : (darkTheme ? BRAND.gray700 : BRAND.gray200)
                  }}
                >
                  <Text className={`font-sans-bold text-xl ${selectedMismatchFloor === floor ? 'text-white' : (darkTheme ? 'text-gray-300' : 'text-gray-700')}`}>
                    {floor === 1 ? 'GF' : floor}
                  </Text>
                </PressableScale>
              ))}
            </View>

            <PressableScale 
              onPress={() => reportAddressMismatch(selectedMismatchFloor)}
              disabled={isReportingMismatch}
              className="py-4 rounded-xl items-center"
              style={{ backgroundColor: TOAST.error }}
            >
              <Text className="text-white font-sans-bold text-lg">
                {isReportingMismatch ? "Reporting..." : `Report Floor ${selectedMismatchFloor === 1 ? 'GF' : selectedMismatchFloor} Mismatch`}
              </Text>
            </PressableScale>
          </View>
        </View>
      </Modal>

      {/* Cancel Delivery Bottom Sheet */}
      <Modal visible={showCancelSheet} transparent animationType="slide">
        <View className="flex-1 justify-end bg-black/60">
          <View className={`rounded-t-3xl p-6 ${darkTheme ? 'bg-surface-container' : 'bg-white'}`}>
            <View className="flex-row justify-between items-center mb-6">
              <Text className={`text-xl font-sans-bold ${darkTheme ? 'text-white' : 'text-gray-900'}`}>Report Issue / Cancel</Text>
              <PressableScale onPress={() => setShowCancelSheet(false)} className="w-8 h-8 rounded-full bg-gray-200/20 items-center justify-center">
                <Text className={`text-lg font-sans-bold ${darkTheme ? 'text-gray-400' : 'text-gray-500'}`}>✕</Text>
              </PressableScale>
            </View>
            <Text className={`mb-4 ${darkTheme ? 'text-gray-300' : 'text-gray-600'}`}>
              Why are you cancelling this delivery? Please note that frequent cancellations may affect your rating.
            </Text>
            
            <View className="flex-col gap-2 mb-6">
              {(activeOrder?.order_status === "picked_up") ? (
                <>
                  {["vehicle_issue", "accident", "customer_unreachable", "customer_refused", "other"].map((reason) => (
                    <PressableScale
                      key={reason}
                      onPress={() => setCancelReason(reason)}
                      className={`p-3 rounded-xl border flex-row items-center gap-2`}
                      style={{
                        backgroundColor: cancelReason === reason ? BRAND.primary + '1A' : (darkTheme ? BRAND.gray800 : BRAND.white),
                        borderColor: cancelReason === reason ? BRAND.primary : (darkTheme ? BRAND.gray700 : BRAND.gray200)
                      }}
                    >
                      <View className={`w-5 h-5 rounded-full border-2 items-center justify-center`} style={{ borderColor: cancelReason === reason ? BRAND.primary : BRAND.gray400 }}>
                        {cancelReason === reason && <View className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: BRAND.primary }} />}
                      </View>
                      <Text className={`font-sans-semibold capitalize ${cancelReason === reason ? (darkTheme ? 'text-white' : 'text-gray-900') : (darkTheme ? 'text-gray-400' : 'text-gray-600')}`}>
                        {reason.replace(/_/g, ' ')}
                      </Text>
                    </PressableScale>
                  ))}
                </>
              ) : (
                <>
                  {["vehicle_issue", "accident", "vendor_closed", "out_of_stock", "other"].map((reason) => (
                    <PressableScale
                      key={reason}
                      onPress={() => setCancelReason(reason)}
                      className={`p-3 rounded-xl border flex-row items-center gap-2`}
                      style={{
                        backgroundColor: cancelReason === reason ? BRAND.primary + '1A' : (darkTheme ? BRAND.gray800 : BRAND.white),
                        borderColor: cancelReason === reason ? BRAND.primary : (darkTheme ? BRAND.gray700 : BRAND.gray200)
                      }}
                    >
                      <View className={`w-5 h-5 rounded-full border-2 items-center justify-center`} style={{ borderColor: cancelReason === reason ? BRAND.primary : BRAND.gray400 }}>
                        {cancelReason === reason && <View className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: BRAND.primary }} />}
                      </View>
                      <Text className={`font-sans-semibold capitalize ${cancelReason === reason ? (darkTheme ? 'text-white' : 'text-gray-900') : (darkTheme ? 'text-gray-400' : 'text-gray-600')}`}>
                        {reason.replace(/_/g, ' ')}
                      </Text>
                    </PressableScale>
                  ))}
                </>
              )}
            </View>

            <PressableScale 
              onPress={cancelDelivery}
              disabled={isCanceling}
              className="py-4 rounded-xl items-center"
              style={{ backgroundColor: TOAST.error }}
            >
              <Text className="text-white font-sans-bold text-lg">
                {isCanceling ? "Processing..." : "Confirm Cancellation"}
              </Text>
            </PressableScale>
          </View>
        </View>
      </Modal>

    </View>
  );
}
