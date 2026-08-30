// url : /(screens)/Maps/lat=lat%lng=lng%id=id

import { useCallback, useContext, useEffect, useState, useRef as useReactRef } from "react";
import { useTabBarClearance } from '@/constants/layout';
import {
    ActivityIndicator,
    Dimensions,
    KeyboardAvoidingView,
    Platform,
    ScrollView,
    StatusBar,
    StyleSheet,
    TouchableWithoutFeedback,
    View,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { Toast } from "@/lib/toast";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import BottomSheet, { BottomSheetScrollView, BottomSheetView } from "@gorhom/bottom-sheet";

/**
 * `react-native-maps` is `require`d rather than imported: it has no web build,
 * and a static import would break the bundle there. Its *types* are safe to
 * import — `import type` is erased at compile time and emits no require — so
 * every component below is the real one, and the web fallbacks are checked
 * against the same props the native ones take.
 *
 * `Region` used to be in this list, declared `any`, assigned from
 * `maps.Region` on native and a bare `function(){}` on web. It is a **type**,
 * not a runtime export, so the native assignment was `undefined` and neither
 * was ever read. `any` is what let three lines of dead code look deliberate,
 * comment included.
 */
import type MapViewType from 'react-native-maps';
import type {
    MapMarkerProps,
    MapViewProps,
    MapUrlTileProps,
    MapStyleElement,
    MarkerAnimated as MarkerAnimatedType,
    Provider,
} from 'react-native-maps';
import type { StyleProp, ViewStyle } from 'react-native';
import type { GestureHandlerRootView as GestureHandlerRootViewType } from 'react-native-gesture-handler';

/**
 * The native components are classes and are driven through their refs
 * (`animateToRegion`, `animateMarkerToCoordinate`), so `ref` has to be part of
 * the declared props: a bare `ComponentType<P>` has no `ref` and every call site
 * would fail. The web stand-ins take the same props and simply ignore the ref.
 */
type MapViewComponent = React.ComponentType<
    MapViewProps & { ref?: React.Ref<MapViewType> }
>;
type MarkerComponent = React.ComponentType<MapMarkerProps>;
type MarkerAnimatedComponent = React.ComponentType<
    MapMarkerProps & { ref?: React.Ref<React.ComponentRef<typeof MarkerAnimatedType>> }
>;

/**
 * Declared without `| null`, and without an initialiser, because **both**
 * branches below assign every one of them. `= null` would be a lie the compiler
 * then makes everybody pay for: `ComponentType<P> | null` is not a valid JSX
 * element type, so every use site would need a guard against a state that
 * cannot occur.
 */
let MapView: MapViewComponent;
let Marker: MarkerComponent;
let MarkerAnimated: MarkerAnimatedComponent;
let GestureHandlerRootViewComponent:
    | typeof GestureHandlerRootViewType
    | React.ComponentType<{ children?: React.ReactNode; style?: StyleProp<ViewStyle> }>;
let UrlTile: React.ComponentType<MapUrlTileProps>;
/** `'google' | undefined` — the library's own union, not `string`. */
let PROVIDER_GOOGLE: Provider;

if (Platform.OS !== 'web') {
    // Import native-only modules only when not on web
    const maps = require('react-native-maps');
    MapView = maps.default;
    Marker = maps.Marker;
    MarkerAnimated = maps.MarkerAnimated;
    UrlTile = maps.UrlTile;
    PROVIDER_GOOGLE = maps.PROVIDER_GOOGLE;
    const { GestureHandlerRootView: GestureHandlerRootViewImport } = require('react-native-gesture-handler');
    GestureHandlerRootViewComponent = GestureHandlerRootViewImport;
} else {
    // Web mock implementations
    // Web stand-ins. Typed against the same props as the native components, so
    // a prop that exists on one and not the other is a build error here rather
    // than a blank rectangle in a browser nobody tests.
    MapView = ({ style, children }: MapViewProps) => <div style={{ ...(style as object), position: 'relative', width: '100%', height: '400px', backgroundColor: '#e0e0e0' }}>{children}</div>;
    Marker = (_props: MapMarkerProps) => <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'red', width: '10px', height: '10px', borderRadius: '50%' }} />;
    MarkerAnimated = (_props: MapMarkerProps) => <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'blue', width: '10px', height: '10px', borderRadius: '50%' }} />;
    UrlTile = () => null;
    PROVIDER_GOOGLE = 'google';
    GestureHandlerRootViewComponent = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
}

import MiniOrderCard from "@/components/common/MiniOrderCard";
import MiniVendorCard from "@/components/common/MiniVendorCard";
import OngoingOrderCard from "@/components/common/OngoingOrderCard";
import OrderListItem from "@/components/common/OrderListItem";
import BackButton from "@/components/ui/BackButton";
import { BRAND } from "@/constants/brandColors";
import type {
	GeoJSONFeature,
	GeoJSONVendorProperties,
	Order,
	Vendor,
} from "@/types/models";
import type { LatLng } from "react-native-maps";

import { UIThemeContext } from "@/context/ThemeContext";
import { useOrders, orderRows } from "@/hooks/queries/useOrders";
import { useRiderTracking } from "@/hooks/queries/useRiderTracking";
import { useApiRequest } from "@/API/useApiClient";
import { ROUTES } from "@/API/routes/ApiRoutes";
import { errorMessage } from "@/API/errors";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useAllVendors } from "@/hooks/queries/useVendors";
import { useSavedLocations, useCreateSavedLocation, useSelectSavedLocation } from "@/hooks/queries/useSavedLocations";
import { useAuth } from "@clerk/clerk-expo";
import { useQueryClient } from '@tanstack/react-query';
import { Skeleton } from "@/components/ui/Skeleton";
import * as Location from "expo-location";
import { usePathname, useRouter, useLocalSearchParams } from "expo-router";
import { Image } from "react-native";
import { useRef } from "react";
import { PressableScale } from "@/components/ui/PressableScale";

import { Ionicons } from "@expo/vector-icons";

const { width, height } = Dimensions.get("window");
const MAP_DIMENSIONS = {
	width: width,
	height: (height + (StatusBar.currentHeight || 0) - 55) * 0.55,
};

const retroMapStyle = [
  {
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#ebe3cd"
      }
    ]
  },
  {
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#523735"
      }
    ]
  },
  {
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#f5f1e6"
      }
    ]
  },
  {
    "featureType": "administrative",
    "elementType": "geometry.stroke",
    "stylers": [
      {
        "color": "#c9b2a6"
      }
    ]
  },
  {
    "featureType": "administrative.land_parcel",
    "elementType": "geometry.stroke",
    "stylers": [
      {
        "color": "#dcd2be"
      }
    ]
  },
  {
    "featureType": "administrative.land_parcel",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#ae9e90"
      }
    ]
  },
  {
    "featureType": "landscape.natural",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#dfd2ae"
      }
    ]
  },
  {
    "featureType": "poi",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#dfd2ae"
      }
    ]
  },
  {
    "featureType": "poi",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#93817c"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "geometry.fill",
    "stylers": [
      {
        "color": "#a5b076"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#447530"
      }
    ]
  },
  {
    "featureType": "road",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#f5f1e6"
      }
    ]
  },
  {
    "featureType": "road.arterial",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#fdfcf8"
      }
    ]
  },
  {
    "featureType": "road.highway",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#f8c967"
      }
    ]
  },
  {
    "featureType": "road.highway",
    "elementType": "geometry.stroke",
    "stylers": [
      {
        "color": "#e9bc62"
      }
    ]
  },
  {
    "featureType": "road.highway.controlled_access",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#e98d58"
      }
    ]
  },
  {
    "featureType": "road.highway.controlled_access",
    "elementType": "geometry.stroke",
    "stylers": [
      {
        "color": "#db8555"
      }
    ]
  },
  {
    "featureType": "road.local",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#806b63"
      }
    ]
  },
  {
    "featureType": "transit.line",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#dfd2ae"
      }
    ]
  },
  {
    "featureType": "transit.line",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#8f7d77"
      }
    ]
  },
  {
    "featureType": "transit.line",
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#ebe3cd"
      }
    ]
  },
  {
    "featureType": "transit.station",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#dfd2ae"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "geometry.fill",
    "stylers": [
      {
        "color": "#b9d3c2"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#92998d"
      }
    ]
  }
]

const darkMapStyle: MapStyleElement[] = [
  {
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#212121"
      }
    ]
  },
  {
    "elementType": "labels.icon",
    "stylers": [
      {
        "visibility": "off"
      }
    ]
  },
  {
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#212121"
      }
    ]
  },
  {
    "featureType": "administrative",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "administrative.country",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#9e9e9e"
      }
    ]
  },
  {
    "featureType": "administrative.land_parcel",
    "stylers": [
      {
        "visibility": "off"
      }
    ]
  },
  {
    "featureType": "administrative.locality",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#bdbdbd"
      }
    ]
  },
  {
    "featureType": "poi",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#181818"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#616161"
      }
    ]
  },
  {
    "featureType": "poi.park",
    "elementType": "labels.text.stroke",
    "stylers": [
      {
        "color": "#1b1b1b"
      }
    ]
  },
  {
    "featureType": "road",
    "elementType": "geometry.fill",
    "stylers": [
      {
        "color": "#2c2c2c"
      }
    ]
  },
  {
    "featureType": "road",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#8a8a8a"
      }
    ]
  },
  {
    "featureType": "road.arterial",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#373737"
      }
    ]
  },
  {
    "featureType": "road.highway",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#3c3c3c"
      }
    ]
  },
  {
    "featureType": "road.highway.controlled_access",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#4e4e4e"
      }
    ]
  },
  {
    "featureType": "road.local",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#616161"
      }
    ]
  },
  {
    "featureType": "transit",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#757575"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "geometry",
    "stylers": [
      {
        "color": "#000000"
      }
    ]
  },
  {
    "featureType": "water",
    "elementType": "labels.text.fill",
    "stylers": [
      {
        "color": "#3d3d3d"
      }
    ]
  }
]

/**
 * `MapView`'s `customMapStyle` — empty means "the provider's own styling", which
 * is what the light theme wants. Typed as the library's own array element so
 * the dark style above it is checked against the same shape.
 */
const standardMapStyle: MapStyleElement[] = []

export default function Maps() {
    const tabBarClearance = useTabBarClearance();
	// <------------------------HOOKS------------------------->
	const router = useRouter();
	const { getToken } = useAuth();
	const api = useApiRequest();
	const queryClient = useQueryClient();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const path = usePathname()
	
	const { id } = useLocalSearchParams();
	const rawParams = (Array.isArray(id) ? id[0] : id) || "";
	// Fallback to path if id is somehow missing
	const actualParams = rawParams || (path?.split("/").pop() ?? "");
	
	// Support both | and % for backward compatibility with existing links
	const separator = actualParams.includes("|") ? "|" : "%";
	const pathVariables = actualParams.split(separator);

	const pathLat = Number(pathVariables?.[0]?.split("=")[1]) || 1;
	const pathlng = Number(pathVariables?.[1]?.split("=")[1]) || 1;
	
	const isModeSetLocation = pathVariables?.[2]?.includes("mode=setLocation") || false;
	const pathid = isModeSetLocation ? null : (pathVariables?.[2]?.split("=")[1] || null);

	const pathAddressRaw = pathVariables?.find(v => v.startsWith("address="))?.split("=")[1];
	const pathAddress = pathAddressRaw ? decodeURIComponent(pathAddressRaw) : "";

	// if (__DEV__) console.log("pathLat", pathLat)
	// <------------------------STATES------------------------->
	const [dataShown, setDataShown] = useState(isModeSetLocation ? "setLocation" : "orders"); // either ['setLocation', 'vendorDetails', 'orders', 'all'] : View for a vendor picked on the map, View for ongoing orders/in transit or View for edit and set location
	// A marker's properties, not a `Vendor` — see `GeoJSONVendorProperties`.
	const [Vendor, setVendor] = useState<GeoJSONVendorProperties>();
	// if (__DEV__) console.log(Vendor)
	const [location, setLocation] = useState<Location.LocationObject | null>(null);
	const [ShowFloatingOrder, setShowFloatingOrder] = useState(false)
	const [ShowFloatingVendor, setShowFloatingVendor] = useState(false)
	const [errorMsg, setErrorMsg] = useState<string | null>(null);
	const [markers, setMarkers] = useState<GeoJSONFeature[]>([]);
	const [currentMapCenter, setCurrentMapCenter] = useState<LatLng>({ latitude: pathLat, longitude: pathlng });
	const [isConfirmingLocation, setIsConfirmingLocation] = useState(false);
	const [liveAddress, setLiveAddress] = useState<string>(pathAddress || "");
	
	const createSavedLocation = useCreateSavedLocation();
	const selectSavedLocation = useSelectSavedLocation();
	const [isGeocoding, setIsGeocoding] = useState(false);
	// `setTimeout` in React Native returns a number, not a Node `Timeout`.
	const geocodeTimeoutRef = useReactRef<ReturnType<typeof setTimeout> | null>(null);
	const [floorLevel, setFloorLevel] = useState<string>("0");
	const [hasElevator, setHasElevator] = useState<boolean>(false);

	// WebSocket Tracking States
	const [activeSession, setActiveSession] = useState<Order | null>(null);
	const [riderCoordinates, setRiderCoordinates] = useState<{lat: number, lng: number} | null>(null);

    const { data: allVendors = [], isLoading: vendorsLoading } = useAllVendors();
    // The newest page only — this panel is a shortcut to recent orders beside the
    // map, not the history screen. `orderRows` is how a paged query becomes a
    // list; never read `.pages` here.
    const ordersQuery = useOrders();
    const orders = orderRows(ordersQuery.data);
    const { data: savedLocations = [] } = useSavedLocations();
    const { data: User, isPending: loadingUser, refetch: refetchUser } = useUserDetails();
    const { isLoaded, isSignedIn } = useAuth();
    const Loading = vendorsLoading;

	// if(User === undefined || User === null){
	// 	fetchUserDetails()
	// 	router.push("/(screens)")
	// }

const initialRegion: import("@/types/models").MapRegion = {
        latitude: pathLat, 
        longitude: pathlng,
        latitudeDelta: 0.015,
        longitudeDelta: 0.015,
      };

	// Debounced reverse geocode — fires 500ms after user stops panning
	const debouncedReverseGeocode = useCallback((lat: number, lng: number) => {
		if (geocodeTimeoutRef.current) clearTimeout(geocodeTimeoutRef.current);
		setIsGeocoding(true);
		geocodeTimeoutRef.current = setTimeout(async () => {
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
					const parsedAddress = parts.join(", ");
					if (parsedAddress) {
						setLiveAddress(parsedAddress);
					} else {
						// Only fallback if we don't already have a valid address
						setLiveAddress(prev => prev || "Unknown Location");
					}
				} else {
					setLiveAddress(prev => prev || "Unknown Location");
				}
			} catch {
				setLiveAddress("Could not resolve address");
			} finally {
				setIsGeocoding(false);
			}
		}, 500);
	}, []);

	const [region, setRegion] = useState(initialRegion);

	// <-----------------------VARIABLES----------------------->
	const handleConfirmLocation = async () => {
		setIsConfirmingLocation(true);
		try {
			// Use the live address already resolved by debounced geocoding
			let addressStr = liveAddress;
			if (!addressStr || addressStr === "Move the map to select location" || addressStr === "Unknown Location") {
				// Fallback: reverse geocode one more time
				const geocode = await Location.reverseGeocodeAsync({
					latitude: currentMapCenter.latitude,
					longitude: currentMapCenter.longitude
				}).catch(() => []);
				if (geocode && geocode.length > 0) {
					const g = geocode[0];
					const parts: string[] = [];
					if (g.name && g.name !== g.street) parts.push(g.name);
					if (g.street) parts.push(g.street);
					if (g.district) parts.push(g.district);
					if (g.city) parts.push(g.city);
					if (parts.length === 0) {
						if (g.region) parts.push(g.region);
						if (g.country) parts.push(g.country);
					}
					addressStr = parts.join(", ") || "Unknown Location";
				} else {
					addressStr = "Unknown Location";
				}
			}

			await api.post(ROUTES.UPDATE_LOCATION, {
				lat: currentMapCenter.latitude,
				lng: currentMapCenter.longitude,
				location_address: addressStr,
				floor_level: parseInt(floorLevel) || 0,
				has_elevator: hasElevator,
			});

			// Auto-save to saved locations for quick reuse
			try {
				await createSavedLocation.mutateAsync({
					address: addressStr,
					lat: currentMapCenter.latitude,
					lng: currentMapCenter.longitude,
					floor_level: parseInt(floorLevel) || 0,
					has_elevator: hasElevator
				} as any);
			} catch {
				// Silent — max locations reached or duplicate is fine
			}

			Toast.success("Location Updated", `Delivering to ${addressStr}`);
			// Optimistically update the UI cache (flat shape matches BasicUser from API)
			await queryClient.cancelQueries({ queryKey: ['user', 'details'] });
			queryClient.setQueryData(['user', 'details'], (old: import("@/types/models").BasicUser | undefined) => {
				if (!old) return old;
				return {
					...old,
					lat: currentMapCenter.latitude,
					lng: currentMapCenter.longitude,
					location_address: addressStr,
					floor_level: parseInt(floorLevel) || 0,
					has_elevator: hasElevator,
				};
			});
			queryClient.invalidateQueries({ queryKey: ['user', 'details'] }); // Refetch to sync with server
			// The delivery fee depends on this address, so any cached quote is stale.
			queryClient.invalidateQueries({ queryKey: ['cart', 'quote'] });
			queryClient.invalidateQueries({ queryKey: ['delivery-fee'] });
			router.back();
		} catch (error) {
			if (__DEV__) console.error("Error confirming location", error);
			Toast.error("Couldn't save location", errorMessage(error, "Please try again."));
		} finally {
			setIsConfirmingLocation(false);
		}
	};

	const StatusBarHeight = StatusBar.currentHeight || 0;
	const finalHeight = height + StatusBarHeight;
	
	const vendorActive = ShowFloatingVendor;
	const orderActive = ShowFloatingOrder;
	const fullscreen = vendorActive || orderActive;

	

	

	const animatedFloatingVendorView = {
		opacity: vendorActive ? 1 : 0,
		transform: [{ scale: vendorActive ? 1 : 0 }]
	};

	const animatedFloatingOrderView = {
		opacity: orderActive ? 1 : 0,
		transform: [{ scale: orderActive ? 1 : 0 }]
	};

	const vendorMapView = () => {
		setShowFloatingVendor(true)
		setShowFloatingOrder(false)
	};
	const orderTrackingView = () => {
		setShowFloatingOrder(true)
		setShowFloatingVendor(false)
	};

	const collapseFullscreenMap = () => {
		setShowFloatingOrder(false)
		setShowFloatingVendor(false)
	};

	const bottomSheetRef = useReactRef<BottomSheet>(null);

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

	// Gesture handler — passthrough (no fling expand/collapse needed for setLocation mode)
	// Gesture handler — passthrough (no fling expand/collapse needed for setLocation mode)

	// >---->> FETCHING DATA FROM BACKEND
    useEffect(() => {
        if (!allVendors || allVendors.length === 0) return;
        
        if(pathid != null && pathid != undefined){
            for(const vendor of allVendors){
                if (vendor.id === pathid){
                    const vendorData = {
                        id: vendor.id,
                        title: vendor.business_name,
                        rating: vendor.rating,
                        image: vendor.profile_pic,
                        location_address: vendor.location_address,
                    }
                    setVendor(vendorData)
                    vendorMapView()
                }
            }
        }
        // A store whose coordinates are null is not placeable, and `lat`/`lng`
        // are nullable on `Vendor`. Coercing them would put a marker at 0°,0° —
        // in the Atlantic — so such a store is left off the map instead.
        const convertToClusterPoints = (vendors: Vendor[]): GeoJSONFeature[] =>
            vendors
                .filter((vendor) => vendor.lat != null && vendor.lng != null)
                .map((vendor) => ({
                    type: "Feature",
                    geometry: {
                        type: "Point",
                        // [lng, lat] — GeoJSON's order, the reverse of the map's.
                        coordinates: [vendor.lng as number, vendor.lat as number],
                    },
                    properties: {
                        id: vendor.id,
                        title: vendor.business_name,
                        rating: vendor.rating,
                        image: vendor.profile_pic,
                        location_address: vendor.location_address,
                    },
                }));
        setMarkers(convertToClusterPoints(allVendors));
    }, [allVendors, pathid]);

	// MAP MARKERS CALLBACK
	const renderClusterMarker = useCallback((item: GeoJSONFeature) => {
		return (
			<Marker
				key={`cluster-${item.properties.cluster_id}`}
				coordinate={{
					latitude: item.geometry.coordinates[1],
					longitude: item.geometry.coordinates[0],
				}}
				// pinColor="lightblue"
			>
				<View
					className={`w-[45px] h-[45px] items-center justify-center rounded-full border-2 border-accentbg bg-black `}
				>
					<Text className="text-accentbg font-sans-semibold">
						{item.properties.point_count}
					</Text>
				</View>
			</Marker>
		);
	}, []);

	const renderSingleMarker = useCallback((item: GeoJSONFeature) => {
		return (
			<Marker
				key={item.properties.id}
				coordinate={{
					latitude: item.geometry.coordinates[1],
					longitude: item.geometry.coordinates[0],
				}}
				
				onPress={() => {
					setShowFloatingOrder(false)
					setVendor(item.properties);
					vendorMapView();
				}}
			>
				<View className={`items-center w-[50px] h-[50px]  justify-center`}>
					<Ionicons name="water" size={24} color={BRAND.primary} />
					<View className={`p-1 ${darkTheme?"bg-black":"bg-white"} absolute top-2 min-w-[25px] min-h-[25px] rounded-full -z-10`}></View>
				</View>
			</Marker>
		);
	}, []);

	const mapRef = useRef<MapViewType | null>(null);
	const trackingMarkerRef = useRef<React.ComponentRef<typeof MarkerAnimatedType> | null>(null);

	// GET CURRENT USER LOCATION FUNCTION
	async function getCurrentLocation() {
		try {
			let { status } = await Location.requestForegroundPermissionsAsync();
			if (status !== "granted") {
				setErrorMsg("Permission to access location was denied");
				return;
			}
			let location = await Location.getCurrentPositionAsync({});
			setLocation(location);
		} catch (error) {
			if (__DEV__) console.warn("getCurrentLocation failed in Map screen:", error);
			setErrorMsg("Current location is unavailable.");
		}
	}

	// Fetch active orders for Tracking
    useEffect(() => {
        if (!orders || orders.length === 0) return;
        const active = orders.find((o) => o.order_status === "picked_up");
        if (active) {
            setActiveSession(active);
        }
    }, [orders]);

	useEffect(() => {
		getCurrentLocation();
	}, []);

	/**
	 * Live rider tracking.
	 *
	 * This screen used to open its own WebSocket, which could never have worked:
	 * the URL carried no `?token=` (the server closes unauthenticated tracking
	 * sockets with 1008) and the handler read `data.lat` while the server sends
	 * `{location: {lat, lng}}`. `useRiderTracking` is the one implementation that
	 * authenticates, handles both payload shapes, falls back to REST polling, and
	 * reconnects when connectivity returns.
	 */
	const trackedOrderId = activeSession?.id || null;
	const { data: riderLocation } = useRiderTracking(
		trackedOrderId,
		!!trackedOrderId && ShowFloatingOrder,
	);

	// Follow the rider on the map as coordinates arrive.
	useEffect(() => {
		if (!riderLocation?.lat || !riderLocation?.lng) return;

		const lat = Number(riderLocation.lat);
		const lng = Number(riderLocation.lng);
		setRiderCoordinates({ lat, lng });

		if (Platform.OS === 'web') return;
		mapRef.current?.animateCamera(
			{ center: { latitude: lat, longitude: lng }, pitch: 45, heading: 0, altitude: 1000, zoom: 16 },
			{ duration: 1500 },
		);
		trackingMarkerRef.current?.animateMarkerToCoordinate?.(
			{ latitude: lat, longitude: lng },
			1500,
		);
	}, [riderLocation?.lat, riderLocation?.lng]);

	const renderRiderMarker = useCallback(() => {
		if (!riderCoordinates) return null;
		return (
			<MarkerAnimated 
                ref={trackingMarkerRef}
                coordinate={{ latitude: Number(riderCoordinates.lat), longitude: Number(riderCoordinates.lng) }}
            >
				<View className={`items-center w-[50px] h-[50px] justify-center`}>
					<Ionicons name="bicycle" size={24} color={BRAND.primary} />
				</View>
			</MarkerAnimated>
		);
	}, [riderCoordinates]);

	// Fix for the permanent "blank page" during hot reload
	if (!isLoaded || loadingUser) {
		return (
			<View className={`flex-1 ${darkTheme ? "bg-black" : "bg-white"}`}>
				<Skeleton width="100%" height="100%" borderRadius={0} />
			</View>
		);
	}

	if (!User && !isModeSetLocation) {
		return (
			<DataFallbackUI 
				title="User data unavailable"
				message="We couldn't load your profile. This usually happens on reload before authentication finishes or due to a network timeout."
				onRetry={() => refetchUser()}
			/>
		);
	}
	return (
		<>
			<StatusBar
				backgroundColor={"transparent"}
				barStyle={darkTheme ? "light-content" : "dark-content"}
			/>
			<View
				className={`w-screen absolute ${darkTheme ? "bg-black" : ""}`}
				style={{
					height: finalHeight
				}}
			>

				<GestureHandlerRootViewComponent>
					<View style={StyleSheet.absoluteFillObject}>
						<TouchableWithoutFeedback>
										<MapView
											ref={mapRef}
											// 🟢 FREE OPEN SOURCE MVP MODE 
											// Uncomment this block for MVP:
											// provider={undefined}
											// 🔴 PRODUCTION GOOGLE MAPS MODE 
											// Uncomment this block for Production:
											provider={PROVIDER_GOOGLE}
                                            // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                                            // the prop these three screens passed was dropped and cloud styling has
                                            // never once been applied. A misspelt prop on a native view is silent.
                                            googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
											style={StyleSheet.absoluteFill}
											onRegionChangeComplete={(region: import("@/types/models").MapRegion) => {
												setRegion(region);
												if (dataShown === "setLocation") {
													setCurrentMapCenter(region);
													// Live reverse geocode as user pans (Uber-style)
													debouncedReverseGeocode(region.latitude, region.longitude);
												}
											}}
											initialRegion={initialRegion}
											userLocationUpdateInterval={3000}
											showsUserLocation={true}
											showsMyLocationButton={false}
											showsCompass={false}
										>
											{/* 🟢 FREE OPEN SOURCE MVP MODE */}
											{/* Uncomment this block for MVP: */}
											{/* {UrlTile && <UrlTile urlTemplate={darkTheme ? "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png" : "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"} maximumZ={20} />} */}
											{
												markers.map((item: GeoJSONFeature) => 
													item.properties.cluster
														? renderClusterMarker(item)
														: renderSingleMarker(item)
												)
											}
											{ShowFloatingOrder && renderRiderMarker()}
										</MapView>
						</TouchableWithoutFeedback>
						{dataShown === "setLocation" && (
							<View pointerEvents="none" className="absolute top-1/2 left-1/2 -mt-6 -ml-4 z-10">
								<Ionicons name="location" size={32} color={BRAND.primary} />
							</View>
						)}
					</View>
					{/* <-------------BACK_BUTTON-------------> */}
					<View
						className="absolute left-0 "
						style={{
							top: StatusBar.currentHeight,
						}}
					>
						<View className="w-full  flex-row items-center px-5 py-6 justify-between z-20">
							<PressableScale
								activeOpacity={0.7}
								onPress={() => router.back()}
							>
								<BackButton />
							</PressableScale>
							
							{/* ── Zoom Controls ── */}
							<View className="flex-row gap-2 pointer-events-auto">
								<PressableScale
									onPress={() => handleZoom(true)}
									className={`w-6 h-6 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}
									style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
								>
									<Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-gray-800"}`}>+</Text>
								</PressableScale>
								<PressableScale
									onPress={() => handleZoom(false)}
									className={`w-6 h-6 rounded-full items-center justify-center shadow-sm border ${darkTheme ? "bg-[#201f1f] border-[#3f4850]" : "bg-white border-gray-200"}`}
									style={darkTheme ? { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) } : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
								>
									<Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-gray-800"}`}>−</Text>
								</PressableScale>
							</View>
						</View>
					</View>

					{/* Google Places Autocomplete Search moved to LocationSearch.tsx */}
					{/* <--------KEYBOARD AVOIDING VIEW-------> */}
					{/* <------ANIMATED MINI VENDOR CARD------> */}
					{ ShowFloatingVendor && Vendor != null && Vendor != undefined && (
						<View
							className="absolute bottom-[80px] w-full px-7"
							style={[animatedFloatingVendorView]}
						>
							<View className="relative self-center max-w-[400px] w-full ">
								<View className="absolute -top-14 right-0  items-center gap-3 flex-row">
									<PressableScale
										onPress={()=>{
											setDataShown("orders")
											collapseFullscreenMap()
										}}
									>
										<View className={`px-6 py-3 ${darkTheme?"bg-black":"bg-white"} rounded-full`}>
											<Text className={`text-accentbg font-sans-bold`}>Track Orders</Text>
										</View>
									</PressableScale>
									<PressableScale accessibilityLabel="Leave the full-screen map" 
										activeOpacity={0.6}
										onPress={()=>{
											collapseFullscreenMap()
										}}
									>
										<View
											className={`w-12 h-12 ${
												darkTheme ? "bg-black" : "bg-white"
											} rounded-full items-center justify-center shadow-xl shadow-black `}
										>
											<View className={`pb-1`}>
												<Ionicons name="chevron-up" size={24} color={BRAND.primary} />
											</View>
										</View>
									</PressableScale>
								</View>
								<MiniVendorCard FullMap={false} data={Vendor} />
							</View>
						</View>
					)}

					{ShowFloatingOrder && (
						<View 
							className="absolute bottom-[80px] w-full px-7"
							style={[
								animatedFloatingOrderView,
							]}
						>
							<View className="relative self-center max-w-[400px] ">
								<View className="absolute -top-14 right-0  items-center gap-3 flex-row">
									<PressableScale accessibilityLabel="Leave the full-screen map and hide this order" 
										activeOpacity={0.6}
										onPress={()=>{ 
											collapseFullscreenMap()
											setShowFloatingOrder(false)
										}}
									>
										<View
											className={`w-12 h-12 ${
												darkTheme ? "bg-black" : "bg-white"
											} rounded-full items-center justify-center shadow-xl shadow-black `}
										>
											<View className={`pb-1`}>
												<Ionicons name="chevron-up" size={24} color={BRAND.primary} />
											</View>
										</View>
									</PressableScale>
								</View>
								<MiniOrderCard data={activeSession} />
							</View>
						</View>
					)}

					
<BottomSheet
    ref={bottomSheetRef}
    index={1}
    snapPoints={['35%', '50%', '90%']}
    backgroundStyle={{ backgroundColor: darkTheme ? '#000000' : '#f8fafc' }}
    handleIndicatorStyle={{ backgroundColor: darkTheme ? '#3f4850' : '#cbd5e1', width: 40 }}
>
    <PressableScale accessibilityLabel="Centre the map on my location"
        className="absolute -top-14 right-4"
        onPress={async () => {
            try {
                await getCurrentLocation();
                if (location && mapRef.current) {
                    mapRef.current.animateToRegion({
                        latitude: location.coords.latitude,
                        longitude: location.coords.longitude,
                        latitudeDelta: 0.008,
                        longitudeDelta: 0.008,
                    }, 800);
                }
            } catch (e) {
                if (__DEV__) console.error(e);
            }
        }}
        activeOpacity={0.7}
    >
        <View
            className={`  w-12 h-12 ${
                darkTheme ? "bg-black" : "bg-white"
            } rounded-full items-center justify-center shadow-xl shadow-black `}
        >
            <Ionicons name="navigate" size={24} color={BRAND.primary} />
        </View>
    </PressableScale>

    <BottomSheetScrollView
        contentContainerStyle={{
            gap: 20,
            paddingTop: 10,
            paddingBottom: tabBarClearance,
        }}
        showsVerticalScrollIndicator={false}
    >

									{/* <-----SETTING LOCATION MANUALLY: SEARCH INPUT WITH AUTOFILL CURRENT LOCATION BY DEFAULT, ABILITY TO SET THE SELECTED LOCATION AS YOUR DELIVERY ADDRESS----> */}
									
									{dataShown === "setLocation" && (
										<View className="gap-4 p-3 pb-8">
											{/* Header */}
											<View className="gap-1">
												<Text className={`font-sans-bold text-xl ${darkTheme?"text-on-surface":"text-gray-900"}`}>Set Delivery Location</Text>
												<Text className={`text-sm ${darkTheme?"text-on-surface-variant":"text-gray-500"}`}>Pan the map to pinpoint your exact delivery location.</Text>
											</View>

											{/* Live Address Display (Uber-style) */}
											<View className={`flex-row items-center p-3.5 rounded-xl ${darkTheme ? "bg-surface-container" : "bg-white"} border ${darkTheme ? "border-outline-variant" : "border-gray-200"}`}>
												<View className="w-3 h-3 rounded-full bg-accentbg mr-3" />
												<View className="flex-1">
													{isGeocoding ? (
														<View className="flex-row items-center gap-2">
															<ActivityIndicator size="small" color={BRAND.primary} />
															<Text className={`text-sm ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Finding address...</Text>
														</View>
													) : (
														<Text numberOfLines={2} className={`text-sm font-sans-medium ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
															{liveAddress || "Move the map to select location"}
														</Text>
													)}
												</View>
											</View>

											{/* Saved Locations (Uber-style recent addresses) */}
											{savedLocations.length > 0 && (
												<View className="gap-2">
													<Text className={`text-xs font-sans-semibold uppercase tracking-wider ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Saved Locations</Text>
													{savedLocations.slice(0, 4).map((loc: import("@/types/models").SavedLocation) => (
														<PressableScale
															key={loc.id}
															onPress={async () => {
																try {
																	await selectSavedLocation.mutateAsync(loc.id);
																	queryClient.invalidateQueries({ queryKey: ['user', 'details'] });
																	Toast.success("Location Updated", `Delivering to ${loc.address}`);
																	router.back();
																} catch (e: unknown) {
																	Toast.error("Error", (e as Error).message || "Could not select location");
																}
															}}
														>
															<View className={`flex-row items-center p-3 rounded-xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
																<View className={`w-9 h-9 rounded-full items-center justify-center mr-3 ${darkTheme ? "bg-white/10" : "bg-white"}`}>
																	<Text className="text-base">{loc.label === "Home" ? "🏠" : loc.label === "Work" ? "💼" : "📍"}</Text>
																</View>
																<View className="flex-1">
																	{loc.label && <Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{loc.label}</Text>}
																	<Text numberOfLines={1} className={`text-sm ${darkTheme ? "text-white" : "text-gray-900"}`}>{loc.address}</Text>
																</View>
															</View>
														</PressableScale>
													))}
												</View>
											)}

											{/* Floor and Elevator Info */}
											<View className="gap-3 mt-1 mb-2">
												<View className={`flex-row items-center justify-between p-3.5 rounded-xl ${darkTheme ? "bg-surface-container" : "bg-white"} border ${darkTheme ? "border-outline-variant" : "border-gray-200"}`}>
													<View className="flex-1">
														<Text className={`text-sm font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Floor Level</Text>
														<Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>0 for Ground Floor</Text>
													</View>
													<TextInput
														value={floorLevel}
														onChangeText={setFloorLevel}
														keyboardType="number-pad"
														placeholder="0"
														placeholderTextColor={darkTheme ? "#9ca3af" : "#6b7280"}
														className={`w-16 h-10 px-3 rounded-lg border text-center font-sans-bold text-base ${darkTheme ? "bg-surface text-white border-outline" : "bg-white text-black border-gray-300"}`}
													/>
												</View>

												{parseInt(floorLevel || "0") > 2 && (
													<View className={`flex-row items-center justify-between p-3.5 rounded-xl ${darkTheme ? "bg-surface-container" : "bg-white"} border ${darkTheme ? "border-outline-variant" : "border-gray-200"}`}>
														<View className="flex-1">
															<Text className={`text-sm font-sans-bold ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>Building has Elevator?</Text>
															<Text className={`text-xs ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Helps rider prepare for delivery</Text>
														</View>
														<PressableScale
															onPress={() => setHasElevator(!hasElevator)}
															className={`w-14 h-8 rounded-full justify-center px-1 ${hasElevator ? "bg-accentbg" : (darkTheme ? "bg-gray-700" : "bg-gray-300")}`}
														>
															<View className={`w-6 h-6 rounded-full bg-white transition-all ${hasElevator ? "ml-auto" : "mr-auto"}`} />
														</PressableScale>
													</View>
												)}
											</View>

											{/* Confirm Button */}
											<PressableScale
												disabled={isConfirmingLocation || isGeocoding}
												onPress={handleConfirmLocation}
											>
												<View className={`w-full rounded-2xl py-4 items-center justify-center ${isConfirmingLocation || isGeocoding ? "bg-accentbg/60" : "bg-accentbg"}`}>
													{isConfirmingLocation ? (
														<ActivityIndicator color={BRAND.white} />
													) : (
														<Text className="text-white font-sans-bold text-lg">Confirm Location</Text>
													)}
												</View>
											</PressableScale>
										</View>
									)}

									{dataShown === "orders" && (
										<View className="gap-2 p-3">
											<Text className={`font-sans-semibold text-xl ${darkTheme?"text-white":"text-black"}`}>Ongoing Orders</Text>
											{activeSession ? (
												<OngoingOrderCard 
													data={activeSession} 
													TrackOrder={() => orderTrackingView()}
												/>
											) : (
												<View className={`p-4 rounded-xl items-center ${darkTheme ? "bg-white/5" : "bg-white"}`}>
													<Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>No active deliveries right now</Text>
												</View>
											)}
											<View className={`py-3 gap-2`}>
												<View className={`flex-row w-full justify-between items-center`}>
													<Text className={`font-sans-semibold text-xl ${darkTheme?"text-white":"text-black"}`}>Order History</Text>
													<PressableScale
														activeOpacity={0.7}
														onPress={()=>{
															router.push("/(screens)/Orders")
														}}
													>
														<View className={`px-3 py-2 flex-row gap-2 items-center rounded-full ${darkTheme?"bg-gray-200/10":"bg-white"}`}> 
															<Text className={`font-sans-semibold ${darkTheme?"text-gray-400":"text-gray-600"}`}>See all</Text>
															<Ionicons name="chevron-forward" size={20} color={BRAND.primary} />
														</View>
													</PressableScale>
												</View>
											</View>
											<View className={`gap-3`}>
												{/* `activeSession?.order_id` — an `Order` has no such
												    field, so this compared every id against
												    `undefined` and the order already shown in the
												    floating card above was listed again below it. */}
												{orders && orders.filter((o) => o.id !== activeSession?.id).map((order, idx) => (
													<OrderListItem key={idx} data={order} />
												))}
												{(!orders || orders.length === 0) && (
													<Text className={`text-center py-4 ${darkTheme?"text-gray-500":"text-gray-400"}`}>No history available.</Text>
												)}
											</View>
										</View>
									)}

									{/* <----------------DATA FOR TRACKING ONGOING ORDERS LIVE-----------------> */}
									{/* <----DATA: RIDER PROFILE[ NAME, PROFILE_PIC, PHONE_NUMBER WITH OPTION TO CALL;CALL_BUTTON,EST TIME REMAINING ]----> */}
								
    </BottomSheetScrollView>
</BottomSheet>

				</GestureHandlerRootViewComponent>
			</View>
		</>
	);
}

