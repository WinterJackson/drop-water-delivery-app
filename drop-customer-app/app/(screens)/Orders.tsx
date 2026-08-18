import OrderCard from "@/components/common/OrderCard";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import { OrderCardSkeleton } from "@/components/skeletons/ContextualSkeletons";
import { UIThemeContext } from "@/context/ThemeContext";
import { useOrders, orderRows, isAwaitingPayment, ORDER_STATUS_GROUPS, type Order, type OrderFilter } from "@/hooks/queries/useOrders";
import { keepPaging } from "@/utils/paging";
import { useQueryClient } from "@tanstack/react-query";
import useWebSocket from "@/hooks/useWebSocket";
import { FlashList as OriginalFlashList } from "@shopify/flash-list";
import { useRouter } from "expo-router";
import { useContext, useCallback, useState, useMemo, useRef } from "react";
import { RefreshControl, StatusBar, TouchableWithoutFeedback, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useUserDetails } from "@/hooks/queries/useUser";
import { BRAND } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
const FlashList = OriginalFlashList as any;

const filterOptions = ["All", ...(Object.keys(ORDER_STATUS_GROUPS) as OrderFilter[])] as const;

const Orders = () => {
	const router = useRouter();
	const [showFilter, setShowFilter] = useState(false);
	const [selectedFilter, setSelectedFilter] = useState<OrderFilter | "All">("All");
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const insets = useSafeAreaInsets();
	// The filter is the query, not a pass over the rows. Filtering client-side
	// searched the page in hand, so "Delivered" answered "no orders" to anybody
	// whose last delivery was further back than one page — and answered
	// differently once they had scrolled. Changing the filter starts a new query
	// at page 1, which is also what somebody expects when they tap one.
	const ordersQuery = useOrders(selectedFilter);
	const { isLoading, isFetchingNextPage, hasNextPage, refetch } = ordersQuery;
	const Orders = orderRows(ordersQuery.data);
	const OrdersLoaded = !isLoading;
	const [refreshing, setRefreshing] = useState(false);

	// MED-04: Use existing hook instead of redundant raw fetch
	const { data: UserData } = useUserDetails();
	const userId = UserData?.id || null;

	// Already the filtered set: the server was asked for this status group. See
	// ORDER_STATUS_GROUPS, which is asserted to cover every status the backend
	// can return, so no order can fall between two filters and vanish.
	const filteredOrders = Orders;

	// FIX-RERENDER-01: Stabilize the WebSocket callback with useCallback so it
	// doesn't create a new function reference on every render cycle.
	//
	// It invalidates the whole `['customer','orders']` prefix rather than calling
	// `refetch()`. Now that the filter is part of the query key there is a cache
	// per filter, and `refetch` only refreshes the one on screen — so an order
	// moving from In Transit to Delivered would leave the *other* tab holding it
	// in its old state, for the five minutes of `staleTime`, with `refetchOnMount`
	// off. The customer would watch it arrive, tap Delivered, and not find it.
	const queryClient = useQueryClient();
	const handleOrderUpdate = useCallback((updateData: any) => {
		if (__DEV__) console.log('[WS] order_update:', updateData?.order_id);
		queryClient.invalidateQueries({ queryKey: ['customer', 'orders'] });
		queryClient.invalidateQueries({ queryKey: ['customer', 'order', updateData?.order_id] });
	}, [queryClient]);

	// HIGH-05: Only connect WebSocket when userId is available.
	// The hook internally ignores heartbeats so refetch() is only called
	// on actual order status changes.
	const { connected } = useWebSocket('customer', userId || "", handleOrderUpdate);

	// Orders whose M-Pesa payment was started but never confirmed. The customer
	// may have backgrounded the app mid-payment, so give them a way back in.
	// Unpaid orders are always among the newest, so the first page holds them
	// whichever filter is on — and this banner is a prompt, not a list.
	const awaitingPayment = useMemo(
		() => (Orders as Order[]).filter(isAwaitingPayment),
		[Orders]
	);

	const awaitingPaymentBanner = useCallback(() => {
		if (awaitingPayment.length === 0) return null;
		const order = awaitingPayment[0];
		return (
			<PressableScale
				onPress={() => router.push(`/(screens)/OrderDetail?orderId=${order.id}`)}
				className="mb-3"
			>
				<View className={`w-full p-4 rounded-2xl border flex-row items-center gap-3 ${darkTheme ? 'bg-amber-500/10 border-amber-500/30' : 'bg-amber-50 border-amber-200'}`}>
					<Ionicons name="time-outline" size={20} color="#d97706" />
					<View className="flex-1">
						<Text className={`text-sm font-sans-bold ${darkTheme ? 'text-amber-300' : 'text-amber-800'}`}>
							Payment not confirmed
						</Text>
						<Text className={`text-xs mt-0.5 ${darkTheme ? 'text-amber-400/80' : 'text-amber-700'}`}>
							Order #{String(order.id).slice(0, 8).toUpperCase()} is waiting for M-PESA. Tap to review.
						</Text>
					</View>
					<Ionicons name="chevron-forward" size={18} color={darkTheme ? "#fbbf24" : "#b45309"} />
				</View>
			</PressableScale>
		);
	}, [awaitingPayment, darkTheme, router]);

	// <-------------FUNCTIONS------------->
	const onRefreshOrders = useCallback(async () => {
		setRefreshing(true);
		await refetch();
		setRefreshing(false);
	}, [refetch]);

	// FIX-RERENDER-02: Memoize renderItem to prevent FlashList from re-rendering
	// every cell when the parent re-renders. FlashList uses reference equality checks.
	const renderItem = useCallback(({ item, index }: { item: any; index: number }) => {
		if (!OrdersLoaded && Orders.length === 0) {
			return (
				<View className="mt-2">
					<OrderCardSkeleton />
				</View>
			);
		}
		return <OrderCard order={item} />;
	}, [OrdersLoaded, Orders.length]);

	// FIX-RERENDER-03: Stabilize ListEmptyComponent to avoid recreating on every render
	const listEmptyComponent = useCallback(() => {
		if (!OrdersLoaded && Orders.length === 0) return null;
		return (
			<View className="h-[200px] items-center justify-center">
				<Text className={`text-lg ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
					No orders found.
				</Text>
			</View>
		);
	}, [OrdersLoaded, Orders.length, darkTheme]);

	// FIX-RERENDER-04: Memoize keyExtractor
	const keyExtractor = useCallback((item: any, index: number) => {
		return item?.id?.toString() || index.toString();
	}, []);

	// FIX-RERENDER-05: Stable refreshControl reference
	const refreshControl = useMemo(() => (
		<RefreshControl
			refreshing={refreshing}
			onRefresh={onRefreshOrders}
			tintColor={darkTheme ? "#fff" : "#000"}
		/>
	), [refreshing, onRefreshOrders, darkTheme]);

	// FIX-RERENDER-06: Stable contentContainerStyle to avoid FlashList re-layout
	const contentContainerStyle = useMemo(() => ({
		paddingVertical: 10,
		paddingBottom: 120 + insets.bottom + 16,
	}), [insets.bottom]);

	// FIX-RERENDER-07: Stable data reference for skeleton loading state
	const listData = useMemo(() => {
		if (!OrdersLoaded && Orders.length === 0) return [1, 2, 3, 4];
		return filteredOrders;
	}, [OrdersLoaded, Orders.length, filteredOrders]);

	return (
		<>
			<StatusBar
				backgroundColor={darkTheme ? "black" : "white"}
				barStyle={darkTheme ? "light-content" : "dark-content"}
			/>
			<TouchableWithoutFeedback onPress={() => setShowFilter(false)}>
				<View
					className={`flex-1 pb-3 ${darkTheme?"bg-black":""}`}
					style={{
						marginTop: StatusBar.currentHeight,
					}}
				>
					{/* HEADER */}
					<View style={{ overflow: "hidden", paddingBottom: 4 }}>
					<View
						className={`flex-row items-center px-4 py-3 pb-4 mb-2 ${darkTheme ? "bg-black" : "bg-white"}`}
						style={{ 
    backgroundColor: darkTheme ? "#000" : "#fff",
    borderBottomWidth: 1, 
    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
}}
					>
						<PressableScale
							activeOpacity={0.7}
							onPress={() => router.back()}
							className="mr-4"
						>
							<BackButtonMinimal />
						</PressableScale>
						<Text
							className={`${
								darkTheme ? "text-white" : "text-black"
							} text-xl font-sans-bold`}
						>
							Orders
						</Text>
					</View>
					</View>

					{/* FILTER HEADER */}
					<View className="relative z-10">
						<View className={`flex-row justify-between items-center m-4 px-3 py-2 rounded-xl ${darkTheme?"bg-gray-200/15":"bg-white"} `}>
							<Text className={`font-sans-semibold text-lg capitalize ${darkTheme?"text-white":"text-black"}`}>
								{selectedFilter}
							</Text>

							<PressableScale
								activeOpacity={0.7}
								onPress={() => setShowFilter(!showFilter)}
							>
								<View className="flex-row items-center gap-2 p-2 px-4 rounded-xl">
									<Text className={`font-sans-semibold text-lg ${darkTheme?"text-white":"text-black"}`}>
										Filter
									</Text>
									<Ionicons name="filter" size={24} color={BRAND.primary} />
								</View>
							</PressableScale>
						</View>

						{/* DROPDOWN */}
						{/*
						  * `left-4 right-4` rather than a fixed `w-[140px]` pinned to
						  * `right-5`: the bar above is `m-4`, so those two insets make the
						  * menu exactly as wide as the control it belongs to and aligned
						  * to the same edges. A 140px box floating under a full-width bar
						  * read as an unrelated popover rather than that bar's options,
						  * and it clipped the longer status names.
						  */}
						{showFilter && (
							<View className={`${darkTheme?"bg-slate-950":"bg-white"} absolute left-4 right-4 top-[70px] rounded-xl shadow p-2 z-50 border ${darkTheme?"border-slate-800":"border-slate-200"}`}>
								{filterOptions.map((label, index) => (
									<PressableScale
										key={index}
										onPress={() => {
											setSelectedFilter(label);
											setShowFilter(false);
										}}
										activeOpacity={0.7}
									>
										<View className="p-2 rounded-lg">
											<Text className={`text-base ${darkTheme?"text-white":"text-black"}`} >
												{label}
											</Text>
										</View>
									</PressableScale>
								))}
							</View>
						)}
					</View>
					{
						filteredOrders.length === 0 && OrdersLoaded ? (
							<View style={{ flex: 1, marginTop: -140 }}>
								<EmptyState 
									mood="sad" 
									title={selectedFilter === "All" ? "No Orders Found" : `No ${selectedFilter} Orders`}
									subtitle={selectedFilter === "All" ? "You have no previous orders." : `No orders found matching the filter.`}
									ctaLabel="Browse Products"
									onCtaPress={() => router.push("/(screens)")}
								/>
							</View>
						):(
								<View style={{ flex: 1, marginHorizontal: 16 }}>
									<FlashList
										data={listData}
										// @ts-ignore
										estimatedItemSize={200}
										contentContainerStyle={contentContainerStyle}
										showsVerticalScrollIndicator={false}
										refreshControl={refreshControl}
										ListEmptyComponent={listEmptyComponent}
										ListHeaderComponent={awaitingPaymentBanner}
										keyExtractor={keyExtractor}
										renderItem={renderItem}
										onEndReached={keepPaging(ordersQuery)}
										onEndReachedThreshold={0.5}
										ListFooterComponent={
											isFetchingNextPage ? (
												<View className="mt-2">
													<OrderCardSkeleton />
												</View>
											) : !hasNextPage && filteredOrders.length > 0 ? (
												// A list that simply stops reads as one that failed to
												// load; say where the history ends.
												<Text className={`text-center text-xs py-6 ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>
													That's everything.
												</Text>
											) : null
										}
									/>
								</View>
						)
					}

					{/* ORDERS LIST */}
				</View>
			</TouchableWithoutFeedback>
		</>
	);
};

export default Orders;
