import React, { useContext, useState, useMemo, useRef } from 'react';
import { useTabBarClearance } from '@/constants/layout';
import { View, ScrollView, StatusBar, Image, Platform, ActivityIndicator, StyleSheet } from 'react-native';
import { Text } from '@/components/ui/Text';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { UIThemeContext } from '@/context/ThemeContext';
import { useVendorDirectory, directoryRows } from '@/hooks/queries/useVendors';
import { PressableScale } from '@/components/ui/PressableScale';
import BackButtonMinimal from '@/components/ui/BackButtonMinimal';
import SearchBar from '@/components/common/Search';
import { BRAND, TOAST } from '@/constants/brandColors';
import { estimateDeliveryTime } from '@/utils/distance';
import { useUserDetails } from '@/hooks/queries/useUser';
import { Skeleton, SkeletonText } from '@/components/ui/Skeleton';
import { EmptyState } from '@/components/ui/EmptyState';
import { VendorCardSkeleton } from '@/components/skeletons/ContextualSkeletons';
import { useDebounce } from '@/hooks/useDebounce';
import { keepPaging } from '@/utils/paging';
import BottomSheet, { BottomSheetFlatList, BottomSheetView } from '@gorhom/bottom-sheet';
import MapView, { Marker, UrlTile, PROVIDER_GOOGLE } from 'react-native-maps';
import { Ionicons } from "@expo/vector-icons";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { ratingLabel } from "@/utils/rating";

const VENDOR_FILTERS = [
    { id: 'all', label: 'All Vendors' },
    { id: 'retail_refill', label: 'Retail Vendors' },
    { id: 'wholesale_b2b', label: 'Wholesale Vendors' },
];

export default function VendorDirectory() {
    const tabBarClearance = useTabBarClearance();
    const router = useRouter();
    const insets = useSafeAreaInsets();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === 'dark';
    const { data: User } = useUserDetails();

    const [searchQuery, setSearchQuery] = useState('');
    const [filter, setFilter] = useState('all');
    
    const debouncedSearchQuery = useDebounce(searchQuery, 500);

    const mapRef = React.useRef<MapView>(null);
    const bottomSheetRef = useRef<BottomSheet>(null);

    const directoryQuery = useVendorDirectory(debouncedSearchQuery, filter);
    const { isLoading, isFetchingNextPage, hasNextPage } = directoryQuery;

    // Named `filteredVendors` for history; the filtering happens on the server.
    // Anything narrowed here would only narrow the page in hand.
    const filteredVendors = directoryRows(directoryQuery.data);

    React.useEffect(() => {
        if (filteredVendors.length > 0 && mapRef.current) {
            const coords = filteredVendors
                .filter((v: any) => v.lat && v.lng)
                .map((v: any) => ({ latitude: Number(v.lat), longitude: Number(v.lng) }));
                
            if (User?.lat && User?.lng) {
                coords.push({ latitude: Number(User.lat), longitude: Number(User.lng) });
            }

            if (coords.length > 0) {
                mapRef.current.fitToCoordinates(coords, {
                    edgePadding: { top: 50, right: 50, bottom: 50, left: 50 },
                    animated: true,
                });
            }
        }
    }, [filteredVendors, User]);

    const renderVendor = ({ item }: { item: any }) => {
        const isWholesale = item.vendor_type === 'wholesale_b2b';
        return (
            <PressableScale
                onPress={() => router.push(`/vendor/${item.id}`)}
                className={`mb-4 rounded-3xl p-4 overflow-hidden border ${darkTheme ? 'bg-surface-container border-white/5' : 'bg-white border-gray-200'}`}
				style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
            >
                <View className="flex-row items-center gap-4">
                    <View className="w-20 h-20 rounded-2xl overflow-hidden bg-gray-200">
                        <Image source={{ uri: item.profile_pic }} style={{ width: '100%', height: '100%' }} />
                    </View>
                    <View className="flex-1 justify-center gap-1">
                        <Text className={`text-lg font-sans-bold ${darkTheme ? 'text-white' : 'text-gray-900'}`} numberOfLines={1}>
                            {item.business_name}
                        </Text>
                        {/* The rating still stands when a shop is shut; the
                            delivery estimate does not. Same component and same
                            server field as the store page, so the directory and
                            the page cannot say different things. */}
                        <View className="flex-row items-center gap-2">
                            <Text className={`${darkTheme ? 'text-gray-400' : 'text-gray-600'} font-sans-medium`}>
                                {ratingLabel(item.rating, item.rating_count)}
                            </Text>
                            <Text className={`${darkTheme ? 'text-gray-500' : 'text-gray-400'}`}>•</Text>
                            {item.is_accepting_orders === false ? (
                                <StoreClosedNotice store={item} compact />
                            ) : (
                            <View className="flex-row items-center gap-1">
                                <Ionicons name="bicycle" size={24} color={BRAND.primary} />
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-600"}`}>{estimateDeliveryTime(item.lat, item.lng, User?.lat ?? undefined, User?.lng ?? undefined)}</Text>
                            </View>
                            )}
                        </View>
                        <View className="flex-row flex-wrap gap-2 mt-1">
                            <View className={`px-2 py-1 rounded-md ${isWholesale ? 'bg-blue-100' : 'bg-green-100'}`}>
                                <Text className={`text-xs font-sans-bold ${isWholesale ? 'text-blue-800' : 'text-green-800'}`}>
                                    {isWholesale ? 'Wholesale' : 'Retail'}
                                </Text>
                            </View>
                            {item.products && (
                                <View className={`px-2 py-1 rounded-md ${darkTheme ? 'bg-white/10' : 'bg-white'}`}>
                                    <Text className={`text-xs ${darkTheme ? 'text-gray-300' : 'text-gray-600'}`}>
                                        {item.products.length} Products
                                    </Text>
                                </View>
                            )}
                        </View>
                    </View>
                </View>
            </PressableScale>
        );
    };

    return (
        <View className={`flex-1 ${darkTheme ? 'bg-black' : 'bg-background'}`}>
            <StatusBar barStyle={darkTheme ? 'light-content' : 'dark-content'} translucent backgroundColor="transparent" />
            
            {/* Map Area */}
            <View style={StyleSheet.absoluteFillObject}>
                <MapView
                    ref={mapRef}
                    // 🟢 FREE OPEN SOURCE MVP MODE 
                    // Uncomment this block for MVP:
                    // provider={undefined}
                    // 🔴 PRODUCTION GOOGLE MAPS MODE 
                    // Uncomment this block for Production:
                    provider={PROVIDER_GOOGLE}
                    // @ts-ignore
                    // `googleMapId`, not `mapId` — react-native-maps names it the former, so
                    // the prop these three screens passed was dropped and cloud styling has
                    // never once been applied. A misspelt prop on a native view is silent.
                    googleMapId={Platform.OS === 'ios' ? '3b06fa233809c6d3b07afa7e' : '3b06fa233809c6d35d39c7c1'}
                    style={{ flex: 1 }}
                    initialRegion={{
                        latitude: User?.lat || -1.2921,
                        longitude: User?.lng || 36.8219,
                        latitudeDelta: 0.05,
                        longitudeDelta: 0.05,
                    }}
                >
                    {/* 🟢 FREE OPEN SOURCE MVP MODE */}
                    {/* Uncomment this block for MVP: */}
                    {/* {UrlTile && <UrlTile urlTemplate={darkTheme ? "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png" : "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png"} maximumZ={20} />} */}

                    {useMemo(() => {
                        const overlays = [];
                        if (User?.lat && User?.lng) {
                            overlays.push(
                                <Marker
                                    key="user-marker"
                                    coordinate={{ latitude: User.lat, longitude: User.lng }}
                                    title="You are here"
                                    pinColor={BRAND.primary}
                                />
                            );
                        }
                        
                        filteredVendors.forEach((vendor: import("@/types/models").Vendor) => {
                            if (!vendor.lat || !vendor.lng) return;
                            overlays.push(
                                <Marker
                                    key={vendor.id}
                                    coordinate={{ latitude: vendor.lat, longitude: vendor.lng }}
                                    title={vendor.business_name}
                                    description={vendor.vendor_type === 'wholesale_b2b' ? 'Wholesale Vendor' : 'Retail Vendor'}
                                    pinColor={BRAND.primary}
                                    onPress={() => router.push(`/vendor/${vendor.id}`)}
                                />
                            );
                        });
                        
                        return overlays;
                    }, [User?.lat, User?.lng, filteredVendors])}
                </MapView>
            </View>

            {/* Floating Header */}
            <View className="absolute top-0 left-0 right-0 z-10 px-4" style={{ paddingTop: insets.top + 16 }}>
                <View className="flex-row items-center gap-3">
                    <PressableScale onPress={() => router.back()}>
                        <View 
                            className={`w-10 h-10 rounded-full items-center justify-center`}
                            style={{ backgroundColor: BRAND.primary, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.25, shadowRadius: 3.84, elevation: 5 }}
                        >
                            <Ionicons name="chevron-back" size={24} color="white" />
                        </View>
                    </PressableScale>
                    <SearchBar
                        width="flex-1"
                        height="h-[46px]"
                        buttonStyle=""
                        value={searchQuery}
                        placeholder="Search stores near you"
                        setFunc={setSearchQuery}
                    />
                </View>
            </View>

            <BottomSheet
                ref={bottomSheetRef}
                index={1}
                snapPoints={['35%', '60%', '90%']}
                backgroundStyle={{ backgroundColor: darkTheme ? '#000000' : '#f8fafc' }}
                handleIndicatorStyle={{ backgroundColor: darkTheme ? '#3f4850' : '#cbd5e1', width: 40 }}
            >
                <BottomSheetView>
                    {/* Filters */}
                    <View className="px-4 py-4">
                        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                            {VENDOR_FILTERS.map((f) => (
                                <PressableScale
                                    key={f.id}
                                    onPress={() => setFilter(f.id)}
                                    className={`px-4 py-2 rounded-full border ${filter === f.id ? 'bg-accentbg border-accentbg' : darkTheme ? 'bg-white/5 border-white/10' : 'bg-white border-gray-200'}`}
                                    style={darkTheme || filter === f.id ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
                                >
                                    <Text className={`font-sans-semibold ${filter === f.id ? 'text-white' : darkTheme ? 'text-gray-300' : 'text-gray-600'}`}>
                                        {f.label}
                                    </Text>
                                </PressableScale>
                            ))}
                        </ScrollView>
                    </View>
                </BottomSheetView>

                {/* List */}
                <View className="flex-1 px-4">
                    {isLoading ? (
                        <View className="gap-4">
                            {[1, 2, 3].map((i) => (
                                <VendorCardSkeleton key={i} />
                            ))}
                        </View>
                    ) : filteredVendors.length === 0 ? (
                        <View className="flex-1 mt-10">
                            <EmptyState 
                                mood="sad" 
                                title="No vendors found" 
                                subtitle="Try adjusting your filters or search query." 
                            />
                        </View>
                    ) : (
                        <BottomSheetFlatList
                            data={filteredVendors}
                            keyExtractor={(item) => item.id}
                            renderItem={renderVendor}
                            showsVerticalScrollIndicator={false}
                            contentContainerStyle={{ paddingBottom: tabBarClearance }}
                            onEndReached={keepPaging(directoryQuery)}
                            onEndReachedThreshold={0.6}
                            ListFooterComponent={
                                isFetchingNextPage ? (
                                    <View className="py-6 items-center">
                                        <ActivityIndicator color={BRAND.primary} />
                                    </View>
                                ) : !hasNextPage && filteredVendors.length > 0 ? (
                                    <Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
                                        That's every store that delivers to you.
                                    </Text>
                                ) : null
                            }
                        />
                    )}
                </View>
            </BottomSheet>
        </View>
    );
}
