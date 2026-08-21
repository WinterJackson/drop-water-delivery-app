import FullHorizontalList from "@/components/common/FullHorizontalList";
import { useTabBarClearance } from '@/constants/layout';
import HorizontalList from "@/components/common/HorizontalList";
import { Skeleton } from "@/components/ui/Skeleton";
import UserAvatar from "@/components/ui/UserAvatar";
import BentoCategories from "@/components/common/BentoCategories";
import FavouritesList from "@/components/common/FavouritesList";
import LocationRequired, { NoStoresInRange } from "@/components/common/LocationRequired";
import { Ionicons } from "@expo/vector-icons";
import images from "@/constants/images/images";
import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import { usePaginatedProducts, useProductsWithOffer, offerRows } from "@/hooks/queries/useProducts";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useNearByVendors, useTopBrandsVendors, useTopRatedVendors } from "@/hooks/queries/useVendors";
import { useLocation } from "@/hooks/useLocation";
import { useDeliveryLocation } from "@/hooks/useDeliveryLocation";
import { useUnreadNotificationCount } from "@/hooks/queries/useNotifications";
import { useActiveOrder } from "@/hooks/queries/useOrders";
import useWebSocket from "@/hooks/useWebSocket";
import { useAuth, useUser } from "@clerk/clerk-expo";
import { Image as ExpoImage } from "expo-image";
import { useRouter } from "expo-router";
import React, { useCallback, useContext, useEffect, useState } from "react";
import {
    Dimensions,
    Keyboard,
    RefreshControl,
    StatusBar,
    TouchableWithoutFeedback,
    View,
    Image,
    Modal,
    Linking,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { FlashList, ListRenderItem } from "@shopify/flash-list";
import { SafeAreaView } from "react-native-safe-area-context";
import { PressableScale } from "@/components/ui/PressableScale";
import { BRAND, TOAST } from "@/constants/brandColors";

import { useWindowDimensions } from "react-native";
import { discountPercent, discountedPrice, formatMoney, formatMoneyShort, isZeroMoney } from "@/utils/money";
import type { Product } from "@/types/models";
import type { OrderUpdate } from "@/hooks/useWebSocket";
import type { Router } from "expo-router";

const FlatlistRendorItem = React.memo(({ item, darkTheme, width, router }: { item: Product; darkTheme: boolean; width: number; router: Router }) => {
	return (
		<TouchableWithoutFeedback>
			<View
				className={`flex-1 items-center`}
				style={{
					minWidth: width * 0.5,
					maxWidth: width * 0.5,
					paddingHorizontal: width * 0.05,
					paddingVertical: width * 0.025,
				}}
			>
				<PressableScale
					activeOpacity={0.7}
					onPress={() => {
						router.push(`/product-details/${item?.id}`);
					}}
				>
					<View
						className={`overflow-hidden relative shadow-sm ${darkTheme ? "bg-surface-container border border-outline-variant" : "bg-white border border-gray-100"}`}
						style={{
							width: width * 0.39,
							borderRadius: 24,
						}}
					>
						{/* Offer Badge */}
						{!isZeroMoney(item?.discount) && (
							<View className="absolute w-[60px] bg-red-500 z-20 right-0 items-center justify-center rotate-45 translate-x-4 translate-y-2">
								<Text className="text-white font-sans-semibold">
									{discountPercent(item?.price, item?.discount)}%
								</Text>
							</View>
						)}
						{/* image */}
						<View className="w-full" style={{ height: width * 0.38 }}>
							<ExpoImage
								source={{ uri: item?.image_url }}
								style={{ width: '100%', height: '100%', borderRadius: 24 }}
								contentFit="cover"
								cachePolicy="disk"
								transition={200}
							/>
						</View>
						{/* Name and pricing.
						    Not `flex-1`. The card around this has a fixed `width`
						    and **no height**, so it is an auto-height column — and
						    `flex-1` is `flexGrow:1, flexShrink:1, flexBasis:0%`. In
						    a container with no height there is no free space to
						    grow into, so the base size of 0 is the final size: the
						    row collapsed to nothing and `overflow-hidden` on the
						    card clipped the name and the price away silently.
						    It read as intermittent because FlashList recycles
						    cells, so a view that had already been laid out at a
						    usable height kept it and a freshly recycled one did
						    not — some cards showed their name and price and some
						    did not, in the same grid, changing as you scrolled.
						    The content decides the height here. */}
						<View className="px-3 py-2 w-full">
							<Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-gray-900"}`} numberOfLines={1}>
								{item?.name}
							</Text>
							<View className="flex-row justify-between items-center mt-0.5">
								{/* price and discount */}
								<View className="flex-row gap-2 items-center">
									<Text className={`font-sans-semibold text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
										{formatMoney(discountedPrice(item?.price, item?.discount))}
									</Text>
									{!isZeroMoney(item?.discount) && (
										<Text
											style={{ textDecorationLine: "line-through" }}
											className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}
										>
											{formatMoney(item?.price)}
										</Text>
									)}
								</View>
							</View>
						</View>
					</View>
				</PressableScale>
			</View>
		</TouchableWithoutFeedback>
	);
});

export default function Home() {
    const tabBarClearance = useTabBarClearance();
	// <----------------HOOKS---------------->
	const router = useRouter();
	const { getToken } = useAuth();
	const { user } = useUser()
	const { currentTheme } = useContext(UIThemeContext);
	const { fetchCart } = useContext(Context);
	const { data: User } = useUserDetails();
	const darkTheme = currentTheme === "dark";

	const { width } = useWindowDimensions();
	// <----------------STATES--------------->
	// location
	const { location: deviceLocation, showPrompt, requestLocation } = useLocation();
	useEffect(() => {
		if (!deviceLocation) requestLocation().catch(() => {});
	}, []);

	// Whether this app knows where to deliver at all. Everything below is a list
	// of what can be delivered *to somewhere*, so this is the question that has
	// to be answered before any of it means anything.
	const { hasAddress, address, isResolved: locationResolved } = useDeliveryLocation();

	const { data: unreadData } = useUnreadNotificationCount();
	const unreadCount = unreadData?.unread_count || 0;

	// React Query standard UI States
	// React Query standard UI States
	const { data: NearByVendors = [], isLoading: _nLoad, isFetched: _nFetch, refetch: r1 } = useNearByVendors();
	const NearbyVendorsLoaded = !_nLoad;

	const { data: activeOrder, refetch: rActive } = useActiveOrder();

	const handleOrderUpdate = useCallback((payload: OrderUpdate) => {
		if (payload.action === "ORDER_STATUS_UPDATE" || payload.action === "ORDER_ASSIGNED") {
			rActive();
		}
	}, [rActive]);

	useWebSocket('customer', User?.id || "", handleOrderUpdate);

	const { data: TopRatedVendors = [], isLoading: _tLoad, refetch: r2 } = useTopRatedVendors();
	const TopRatedVendorsLoaded = !_tLoad;

	const { data: TopBrands = [], isLoading: topBrandsLoad, refetch: r6 } = useTopBrandsVendors();
	const TopBrandsloaded = !topBrandsLoad;

	// The home rail shows the first page only, which is what it always showed.
	const offersQuery = useProductsWithOffer();
	const { isLoading: offersLoad, refetch: r7 } = offersQuery;
	const Offers = offerRows(offersQuery.data);
	const OffersLoaded = !offersLoad;

	// Random products (pagination)
	const [page, setPage] = useState(1);
	const { data: currentPageProducts = [], isFetching: isFetchingMore, refetch: refetchProducts } = usePaginatedProducts(page);
	const [paginatedProducts, setPaginatedProducts] = useState<Product[]>([]);
	const [hasMore, setHasMore] = useState(true);

	useEffect(() => {
		if (currentPageProducts?.length > 0) {
			setPaginatedProducts(prev => {
				if (page === 1) return currentPageProducts;
				
				const uniqueIds = new Set(prev.map(p => p.id));
				const newProducts = currentPageProducts.filter((cp) => {
					if (uniqueIds.has(cp.id)) return false;
					uniqueIds.add(cp.id);
					return true;
				});
				return [...prev, ...newProducts];
			});
			if (currentPageProducts.length < 16) {
				setHasMore(false);
			}
		}
	}, [currentPageProducts, page]);

	const fetchRandomProducts = () => {
		if (!isFetchingMore && hasMore) setPage(p => p + 1);
	};

	const [refreshing, setRefreshing] = useState(false);
	const onRefresh = useCallback(async () => {
		setRefreshing(true);
		setPage(1);
		setPaginatedProducts([]);
		setHasMore(true);
		try {
			await Promise.all([r1(), r2(), r6(), r7(), rActive()]);
		} catch (error) {
			if (__DEV__) console.error("Refresh failed", error);
		} finally {
			setRefreshing(false);
		}
	}, [r1, r2, r6, r7, rActive, refetchProducts]);

	/**
	 * An address is set and every discovery read has come back empty.
	 *
	 * Distinct from having no address, and it has to be derived from *all* of
	 * them rather than from the nearby rail alone: that rail is retail-only and
	 * capped at three, so it answers empty for a customer whose only options are
	 * wholesale depots — which is how a screen full of stores came to sit under
	 * "No vendors currently deliver to your location".
	 */
	const everythingLoaded =
		NearbyVendorsLoaded && TopRatedVendorsLoaded && TopBrandsloaded && OffersLoaded && !isFetchingMore;
	const nothingInRange =
		hasAddress &&
		everythingLoaded &&
		NearByVendors.length === 0 &&
		TopRatedVendors.length === 0 &&
		TopBrands.length === 0 &&
		Offers.length === 0 &&
		paginatedProducts.length === 0;

	// <---------------VARIABLES---------------->
	const renderProductItem: ListRenderItem<Product> = useCallback(
		({ item }) => <FlatlistRendorItem item={item} darkTheme={darkTheme} width={width} router={router} />,
		[darkTheme, width, router]
	);

	// Native React Query manages fetching, no mount useEffect required for data

	return (
		<>
			<StatusBar
				translucent
				backgroundColor={darkTheme ? "black" : "white"}
				barStyle={darkTheme ? "light-content" : "dark-content"}
			/>
			<TouchableWithoutFeedback
				onPress={Keyboard.dismiss}
				accessible={false}
			>
				<SafeAreaView
					className={`flex-1 h-full ${darkTheme ? "bg-black" : ""}`}
					style={{
						// paddingTop: statusBarHieght,
					}}
				>
					{/* <--------------<<HEADER>-----------------> */}
					<View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 20 }}>
						<View 
							className="flex-row justify-between items-center px-5 py-3 pb-4 mb-2"
							style={{ 
								backgroundColor: darkTheme ? "#000" : "#fff",
								borderBottomWidth: 1, 
								borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
								...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
							}}
						>
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								router.push("/(screens)/LocationSearch");
							}}
						>
							<View
							className={`flex-row items-center gap-2 p-2 px-3 rounded-full border ${darkTheme ? "bg-surface-variant border-transparent" : "bg-white border-gray-200"}`}
							style={darkTheme ? undefined : { ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) }}
						>
								<Ionicons name="location" size={24} color={BRAND.primary} />
								<View className="flex-col justify-center">
									<View className="flex-row items-center gap-1">
										<Text className={`text-xs font-sans-medium ${darkTheme ? "text-on-surface-variant" : "text-gray-500"}`}>Deliver to</Text>
										<Ionicons name="chevron-down" size={16} color={BRAND.primary} />
									</View>
									<Text numberOfLines={1} className={`text-sm font-sans-bold max-w-[150px] ${darkTheme ? "text-on-surface" : "text-gray-900"}`}>
										{User?.location_address || "Set Location"}
									</Text>
								</View>
							</View>
						</PressableScale>

						<View className="flex-row items-center gap-3">
							{/* Drop Wallet pill. */}
							{!isZeroMoney(User?.wallet_balance) && (
								<PressableScale
									activeOpacity={0.6}
									accessibilityRole="button"
									accessibilityLabel={`Drop Wallet, ${formatMoneyShort(User?.wallet_balance, 'KSh')}. Open your wallet.`}
									onPress={() => router.push("/(screens)/BottleWallet")}
								>
									<View className={`flex-row items-center px-2.5 py-1.5 rounded-full border ${darkTheme ? "bg-blue-500/20 border-blue-500/30" : "bg-blue-50 border-blue-200"}`}>
										<Ionicons name="wallet-outline" size={14} color={BRAND.primary} />
										<Text className="ml-1 font-sans-bold text-xs" style={{ color: BRAND.primary }}>
											{formatMoneyShort(User?.wallet_balance, 'KSh')}
										</Text>
									</View>
								</PressableScale>
							)}

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

							{/* The avatar opens the customer's own profile, which is what an
								avatar means, and `Profile` carries a Settings row into
								`SettingsMain` one tap further on.

								It used to open `SettingsMain` directly, and the wallet pill
								beside it was the *only* thing that pushed `/(screens)/Profile`
								— so when the pill was repointed at the wallet it names, a
								fully built screen with the favourites list, the edit-profile
								sheet and the theme toggle became unreachable while still
								declared in the Stack. A route nothing navigates to is dead
								code that typechecks. */}
							<PressableScale
								activeOpacity={0.6}
								accessibilityRole="button"
								accessibilityLabel="Your profile"
								onPress={() => router.push("/(screens)/Profile")}
							>
								<View style={{ borderWidth: 2, borderColor: BRAND.primary, borderRadius: 999, padding: 2 }}>
									<UserAvatar
										profilePicUrl={User?.profile_pic || user?.imageUrl}
										fullName={User?.full_name || user?.fullName || "Customer"}
										size={36}
									/>
								</View>
							</PressableScale>
						</View>
					</View>
					</View>
					{/* Three states, and they are three different questions.
					    `unknown` is not a warning — it is the first-run state, and
					    rendering it as "Limited Coverage Area" told a customer their
					    neighbourhood was unserved when nobody had asked them where
					    they live yet. `uncovered` is the only one that is bad news.
					    Nothing below renders until the account has loaded, or the
					    prompt flashes over a home screen that is about to be fine. */}
					{locationResolved && !hasAddress ? (
						<LocationRequired />
					) : nothingInRange ? (
						<NoStoresInRange address={address} />
					) : (
					<FlashList
						data={paginatedProducts}
						// @ts-ignore
						estimatedItemSize={250}
						renderItem={renderProductItem}
						keyExtractor={(item) => item.id.toString()}
						numColumns={2}
						contentContainerStyle={{ paddingBottom: tabBarClearance }}
						onEndReached={fetchRandomProducts}
						onEndReachedThreshold={0.7}
						extraData={darkTheme}
						refreshControl={
							<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={darkTheme ? "#fff" : "#000"} />
						}
						ListHeaderComponent={
							<View className="gap-1 pb-4">
									{/* Active Order Banner */}
									{activeOrder && (
										<PressableScale
											activeOpacity={0.8}
											onPress={() => router.push({ pathname: "/(screens)/OrderDetail", params: { orderId: activeOrder.id } })}
										>
											<View className={`mx-5 mb-4 p-4 rounded-2xl flex-row items-center justify-between ${darkTheme ? "bg-blue-900/40 border border-blue-500/30" : "bg-blue-50 border border-blue-200"}`}>
												<View className="flex-row items-center gap-3">
													<View className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-blue-500/20" : "bg-blue-100"}`}>
														<Ionicons name="bicycle" size={20} color={BRAND.primary} />
													</View>
													<View>
														<Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-gray-900"}`}>
															Active Order
														</Text>
														<Text className={`text-xs ${darkTheme ? "text-blue-300" : "text-blue-600"}`}>
															Tap to track your delivery
														</Text>
													</View>
												</View>
												<Ionicons name="chevron-forward" size={20} color={BRAND.primary} />
											</View>
										</PressableScale>
									)}

									<FavouritesList />

									<BentoCategories />

									<FullHorizontalList
										title="Nearby Vendors"
										data={NearByVendors}
										loaded={NearbyVendorsLoaded}
									/>

									{/* Top Rated  */}
									<HorizontalList
										title={"Top Rated Vendors"}
										data={TopRatedVendors}
										loaded={TopRatedVendorsLoaded}
									/>

									{/* offers */}
									{/* `Offers.tsx` was fully built and registered in the
									    layout but nothing ever navigated to it — the home
									    carousel showed a slice of the deals with no way
									    through to the rest. */}
									<HorizontalList
										title="Offers and Deals"
										type="product"
										data={Offers}
										loaded={OffersLoaded}
										onSeeAll={() => router.push("/(screens)/Offers")}
									/>

									{/* top brands */}
									<HorizontalList
										title={"Popular Brands"}
										data={TopBrands}
										loaded={TopBrandsloaded}
									/>

							</View>
						}
						ListFooterComponent={
							isFetchingMore && hasMore ? (
								<View className={`gap-3`}>
									<View className={`w-full flex-row flex-wrap`}>
										{Array.from({ length: 2 }).map((_, index) => {
											return (
												<View
													key={index}
													className={`flex-1  items-center`}
													style={{
														minWidth: width * 0.5,
														maxWidth: width * 0.5,
														paddingHorizontal: width * 0.05,
														paddingVertical: width * 0.025,
													}}
												>
													<View
														className={`rounded overflow-hidden relative ${darkTheme
																? "bg-gray-800"
																: "bg-white"
															}`}
														style={{
															width: width * 0.39,
															height: width * 0.4,
															borderRadius: 24,
														}}
													>
														<Skeleton width="100%" height="100%" style={{ position: 'absolute' }} />
														<View className="w-full h-full justify-end overflow-hidden z-10">
															<View className="w-full h-[60px] p-2 justify-around" style={{ backgroundColor: darkTheme ? "rgba(0,0,0,0.8)" : "rgba(255,255,255,0.8)" }}>
																<Skeleton width="80%" height={12} borderRadius={6} />
																<View className="flex-row justify-between mt-1">
																	<Skeleton width="40%" height={12} borderRadius={6} />
																	<Skeleton width="30%" height={12} borderRadius={6} />
																</View>
															</View>
														</View>
													</View>
												</View>
											);
										})}
									</View>
								</View>
							) : null
						}
					/>
					)}

					{/* Location permission prompt. Non-blocking by design: a denied
					    permission must not lock the user out of the app — they can still
					    set a delivery address by hand and order. */}
					<Modal visible={showPrompt} transparent animationType="fade">
						<View className="flex-1 justify-center items-center bg-black/60 px-5">
							<View className={`w-full rounded-3xl p-6 ${darkTheme ? "bg-gray-900" : "bg-white"}`}>
								<View className="items-center mb-4">
									<View className="w-16 h-16 rounded-full bg-primary/20 items-center justify-center mb-4">
										<Ionicons name="location" size={24} color={BRAND.primary} />
									</View>
									<Text className={`text-xl font-sans-bold text-center mb-2 ${darkTheme ? "text-white" : "text-black"}`}>
										Location Required
									</Text>
									<Text className={`text-center text-sm ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
										Drop uses your location to find vendors that deliver to you. You can also set a delivery address by hand.
									</Text>
								</View>

								<PressableScale
									onPress={() => Linking.openSettings()}
									className="bg-primary py-3 rounded-xl items-center mb-3"
								>
									<Text className="text-white font-sans-bold">Open Settings</Text>
								</PressableScale>

								<PressableScale
									onPress={() => requestLocation()}
									className={`py-3 rounded-xl items-center mb-3 ${darkTheme ? "bg-gray-800" : "bg-gray-100"}`}
								>
									<Text className={`font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>I've enabled it, try again</Text>
								</PressableScale>

								<PressableScale
									onPress={() => router.push("/(screens)/LocationSearch")}
									className="py-3 rounded-xl items-center"
								>
									<Text className={`font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Enter address manually</Text>
								</PressableScale>
							</View>
						</View>
					</Modal>
				</SafeAreaView>
			</TouchableWithoutFeedback>
		</>
	);
}
