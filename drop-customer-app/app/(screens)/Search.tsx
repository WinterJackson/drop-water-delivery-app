import SearchBar from "@/components/common/Search";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonRow } from "@/components/ui/Skeleton";
import { UIThemeContext } from "@/context/ThemeContext";
import { useSearchProducts, useSearchVendors } from "@/hooks/queries/useSearch";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useContext, useEffect, useState } from "react";
import { Image, Keyboard, Linking, Modal, Platform, ScrollView, StatusBar, View } from "react-native";
import { Text } from '@/components/ui/Text';
import { PressableScale } from "@/components/ui/PressableScale";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BRAND } from "@/constants/brandColors";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { FlashList } from "@shopify/flash-list";
import { trackEvent } from "@/utils/analytics";
import { useLocation } from "@/hooks/useLocation";
import { Ionicons } from "@expo/vector-icons";
import { useDebounce } from "@/hooks/useDebounce";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { formatMoney } from "@/utils/money";

const PRODUCT_CATEGORIES = [
	{ id: 'all', label: 'All Products' },
	{ id: 'dispenser_refill', label: 'Dispenser Refills' },
	{ id: 'bottled_water', label: 'Bottled Water' },
	{ id: 'mineral_spring', label: 'Mineral & Spring' },
	{ id: 'purified_water', label: 'Purified Water' },
	{ id: 'alkaline_specialty', label: 'Alkaline Water' },
	{ id: 'dispensers_coolers', label: 'Dispensers' },
	{ id: 'bulk_wholesale', label: 'Bulk & Wholesale' },
];

const SEARCH_HISTORY_KEY = "@search_history";

export default function Search() {
	const { q, category, mode } = useLocalSearchParams();
	const initialQuery = Array.isArray(q) ? q[0] : q || "";
	const initialCategory = Array.isArray(category) ? category[0] : category || "all";
	const initialMode = Array.isArray(mode) ? mode[0] : mode || null;
	const hasCategoryParam = initialCategory !== "all" || !!initialMode;
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const insets = useSafeAreaInsets();
	
	const [searchState, setSearchState] = useState(initialQuery);
	const [search, setSearch] = useState(initialQuery);
	const debouncedSearch = useDebounce(search, 500);
	const [hasSearched, setHasSearched] = useState(!!initialQuery || hasCategoryParam);
	const [productCategoryFilter, setProductCategoryFilter] = useState(initialCategory);
	const [searchMode, setSearchMode] = useState<string | null>(initialMode);
	const [selectedResultTab, setSelectedResultTab] = useState<"products" | "vendors">("products");
	
	const [history, setHistory] = useState<string[]>([]);
	const [showHistory, setShowHistory] = useState(false);
	
	const { location, showPrompt, requestLocation } = useLocation();

	// Request location when Search page mounts if not available
	useEffect(() => {
		if (!location) {
			requestLocation();
		}
	}, []);

	const { 
		data: productsData, 
		isFetching: productLoading,
		fetchNextPage: fetchNextProducts,
		hasNextPage: hasNextProducts,
		isError: productError
	} = useSearchProducts(searchState, productCategoryFilter, 20, searchMode);

	const { 
		data: vendorsData, 
		isFetching: vendorLoading,
		fetchNextPage: fetchNextVendors,
		hasNextPage: hasNextVendors,
		isError: vendorError
	} = useSearchVendors(searchState, 20);

	useEffect(() => {
		loadHistory();
	}, []);

	// Guard: When a searchMode is active (e.g. from Bento cards), 
	// unconditionally keep the results view mounted regardless of other state changes.
	useEffect(() => {
		if (searchMode) {
			setHasSearched(true);
			setShowHistory(false);
		}
	}, [searchMode, productCategoryFilter]);

	useEffect(() => {
		if (debouncedSearch.trim().length > 1) {
			setSearchState(debouncedSearch);
			setHasSearched(true);
			setShowHistory(false);
			saveToHistory(debouncedSearch.trim());
		} else {
			setSearchState("");
			// When in a mode-based search (Bento card), never reset the view
			if (searchMode) {
				// Keep hasSearched true and showHistory false — the mode drives the query
				return;
			}
			// For standard text search: reset if no active category filter
			if (productCategoryFilter === "all") {
				setHasSearched(false);
			}
			if (debouncedSearch.trim() === "" && productCategoryFilter === "all") setShowHistory(true);
		}
	}, [debouncedSearch, productCategoryFilter, searchMode]);

	const loadHistory = async () => {
		try {
			const saved = await AsyncStorage.getItem(SEARCH_HISTORY_KEY);
			if (saved) setHistory(JSON.parse(saved));
		} catch (e) {
			console.warn("Failed to load search history");
		}
	};

	const saveToHistory = async (query: string) => {
		try {
			let newHistory = [query, ...history.filter(h => h.toLowerCase() !== query.toLowerCase())];
			if (newHistory.length > 10) newHistory = newHistory.slice(0, 10);
			setHistory(newHistory);
			await AsyncStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(newHistory));
		} catch (e) {
			console.warn("Failed to save search history");
		}
	};

	const clearHistory = async () => {
		setHistory([]);
		await AsyncStorage.removeItem(SEARCH_HISTORY_KEY);
	};

	const removeFromHistory = async (queryToRemove: string) => {
		try {
			const newHistory = history.filter(h => h !== queryToRemove);
			setHistory(newHistory);
			await AsyncStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(newHistory));
		} catch (e) {
			console.warn("Failed to remove from search history");
		}
	};

	const handleSearch = () => {
		if (!search.trim() || search.trim().length < 2) return;
		Keyboard.dismiss();
		setSearchState(search);
		setHasSearched(true);
		setShowHistory(false);
		saveToHistory(search.trim());
	};

	const productResults = productsData?.pages?.flatMap(page => page) || [];
	const vendorResults = vendorsData?.pages?.flatMap(page => page) || [];
	
	const loading = productLoading || vendorLoading;
	const totalResults = productResults.length + vendorResults.length;

	// Auto-select the tab that has results when the other doesn't
	useEffect(() => {
		if (!loading && hasSearched) {
			if (productResults.length === 0 && vendorResults.length > 0) {
				setSelectedResultTab("vendors");
			} else if (productResults.length > 0 && vendorResults.length === 0) {
				setSelectedResultTab("products");
			}
		}
	}, [loading, hasSearched, productResults.length, vendorResults.length]);

	useEffect(() => {
		if (hasSearched && !loading) {
			trackEvent('search_performed', { 
				query: searchState, 
				totalResults, 
				categoryFilter: productCategoryFilter 
			});
		}
	}, [hasSearched, loading, searchState, productCategoryFilter, totalResults]);

	const handleScrollEnd = () => {
		if (hasNextProducts) fetchNextProducts();
		if (hasNextVendors) fetchNextVendors();
	};

	return (
		<>
			<StatusBar translucent backgroundColor={darkTheme ? "black" : "white"} barStyle={darkTheme ? "light-content" : "dark-content"} />
			<View className={`${darkTheme ? "bg-black" : "bg-white"} flex-1 px-4`} style={{ paddingTop: StatusBar.currentHeight }}>
				{/* Top Search Area */}
				<View style={{ overflow: "hidden", paddingBottom: 4 }}>
					<View 
						className="flex-row items-center justify-between pt-4 pb-4 mb-2 gap-3"
						style={{ 
							backgroundColor: darkTheme ? "#000" : "#fff",
							borderBottomWidth: 1, 
							borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
							...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
						}}
					>
						<PressableScale accessibilityLabel="Go Back" onPress={() => router.back()} activeOpacity={0.6}>
							<BackButtonMinimal />
						</PressableScale>
						<SearchBar
							width="flex-1"
							height="h-[50px]"
							buttonStyle=""
							setFunc={setSearch}
						/>
						<PressableScale accessibilityLabel="Search" onPress={handleSearch} className={`w-[50px] h-[50px] items-center border justify-center rounded-2xl ${darkTheme ? "bg-white/5 border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
							<Ionicons name="search" size={24} color={BRAND.primary} />
						</PressableScale>
					</View>
				</View>

				{/* Search History */}
				{showHistory && history.length > 0 && !hasSearched && (
					<View className="py-4">
						<View className="flex-row justify-between items-center mb-4">
							<Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>Recent Searches</Text>
							<PressableScale onPress={clearHistory}>
								<Text className="text-red-400 font-sans-semibold text-sm">Clear</Text>
							</PressableScale>
						</View>
						<View className="flex-row flex-wrap gap-2">
							{history.map((h, i) => (
								<View 
									key={i} 
									className={`rounded-full flex-row items-center overflow-hidden border ${darkTheme ? "bg-white/10 border-transparent" : "bg-white border-gray-200"}`}
									style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
								>
									<PressableScale
										onPress={() => {
											setSearch(h);
											handleSearch();
										}}
										className="px-4 py-2 flex-row items-center gap-2"
									>
										<Ionicons name="search" size={24} color={BRAND.primary} />
										<Text className={`${darkTheme ? "text-gray-300" : "text-gray-700"}`}>{h}</Text>
									</PressableScale>
									<PressableScale
										accessibilityLabel={`Remove ${h} from search history`}
										onPress={() => removeFromHistory(h)}
										className="px-3 py-2 justify-center items-center"
									>
										<Ionicons name="close" size={24} color={BRAND.primary} />
									</PressableScale>
								</View>
							))}
						</View>
					</View>
				)}

				{!showHistory && hasSearched && (
					<>
		{/* Results Header */}
						<View className="py-4">
							<Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
								{searchMode === "deals" ? `Deals & Offers (${totalResults})` 
								: searchMode === "refill_wholesale" ? `Refill & Wholesale (${totalResults})` 
								: `Search Results (${totalResults})`}
							</Text>
						</View>

						{/* Product Category Filter Chips */}
						<View className="pb-3">
							<ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingRight: 20 }}>
								{(searchMode === "deals" ? [
									{ id: 'all', label: 'All Deals' },
									{ id: 'dispenser_refill', label: 'Refill' },
									{ id: 'bottled_water', label: 'Bottled Water' },
									{ id: 'bulk_wholesale', label: 'Wholesale' },
									{ id: 'dispensers_coolers', label: 'Accessories' }
								] : searchMode === "refill_wholesale" ? [
									{ id: 'all', label: 'All' },
									{ id: 'dispenser_refill', label: 'Refill (10L-20L)' },
									{ id: 'bulk_wholesale', label: 'Wholesale & Crates' }
								] : PRODUCT_CATEGORIES).map((cat) => (
									<PressableScale
										key={cat.id}
										accessibilityLabel={`Filter by ${cat.label}`}
										onPress={() => {
											setProductCategoryFilter(cat.id);
											if (cat.id !== "all" || searchMode) setHasSearched(true);
										}}
										className={`px-4 py-2 rounded-full border ${productCategoryFilter === cat.id ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
										style={darkTheme || productCategoryFilter === cat.id ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
									>
										<Text className={`font-sans-semibold text-sm ${productCategoryFilter === cat.id ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
											{cat.label}
										</Text>
									</PressableScale>
								))}
							</ScrollView>
						</View>

						{/* Result Type Tabs */}
						{hasSearched && totalResults > 0 && (
							<View className="pb-3">
								<ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingRight: 20 }}>
									<PressableScale
										accessibilityLabel="Show product results"
										onPress={() => setSelectedResultTab("products")}
										className={`px-4 py-2 rounded-full border ${selectedResultTab === "products" ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
										style={darkTheme || selectedResultTab === "products" ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
									>
										<Text className={`font-sans-semibold text-sm ${selectedResultTab === "products" ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
											Products ({productResults.length})
										</Text>
									</PressableScale>
									<PressableScale
										accessibilityLabel="Show vendor results"
										onPress={() => setSelectedResultTab("vendors")}
										className={`px-4 py-2 rounded-full border ${selectedResultTab === "vendors" ? "bg-accentbg border-accentbg" : darkTheme ? "bg-white/5 border-white/10" : "bg-white border-gray-200"}`}
										style={darkTheme || selectedResultTab === "vendors" ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
									>
										<Text className={`font-sans-semibold text-sm ${selectedResultTab === "vendors" ? "text-white" : darkTheme ? "text-gray-300" : "text-gray-600"}`}>
											Vendors ({vendorResults.length})
										</Text>
									</PressableScale>
								</ScrollView>
							</View>
						)}

						{/* Results List */}
						<View style={{ flex: 1 }}>
							{(productError || vendorError) && (
								<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
									<EmptyState mood="concerned" title="Something went wrong" subtitle="Please check your connection and try again" />
								</ScrollView>
							)}

							{loading && productResults.length === 0 && vendorResults.length === 0 && !productError && !vendorError ? (
								<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
									<View className="px-4 mt-6 w-full">
										<SkeletonRow />
										<SkeletonRow />
										<SkeletonRow />
										<SkeletonRow />
										<SkeletonRow />
									</View>
								</ScrollView>
							) : !hasSearched ? (
								<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
									<EmptyState mood="search" title="Search for products and vendors" subtitle="Type what you need in the search bar" />
								</ScrollView>
							) : totalResults === 0 && !productError && !vendorError ? (
								<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
									<EmptyState mood="search" title="No results found" subtitle={`No matching results found for "${search}"`} />
								</ScrollView>
							) : (selectedResultTab === "products" ? productResults.length : vendorResults.length) === 0 && totalResults > 0 ? (
								<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
									<EmptyState mood="search" title={`No ${selectedResultTab} found`} subtitle={`Try switching to the ${selectedResultTab === "products" ? "Vendors" : "Products"} tab`} />
								</ScrollView>
							) : (
								<FlashList
									data={
										selectedResultTab === "products"
											? productResults.map(p => ({ ...p, isProduct: true }))
											: vendorResults.map(v => ({ ...v, isVendor: true }))
									}
									// @ts-ignore - Required for FlashList to render despite missing from TS definitions in v2
									estimatedItemSize={120}
									keyboardDismissMode="on-drag"
									contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}
									onEndReached={handleScrollEnd}
									onEndReachedThreshold={0.5}
									keyExtractor={(item: any, index: number) => item.id ? item.id.toString() + index : index.toString()}
									renderItem={({ item }: { item: any }) => {

										if (item.isProduct) {
											const product = item;
											const displayPrice = Math.round((product.price - (product.discount || 0)) * 100) / 100;
											return (
												<PressableScale
													activeOpacity={0.7}
													onPress={() => router.push(`/(screens)/product-details/${product.id}`)}
												>
													<View className={`flex-row items-center gap-4 p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-white/5 border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
														{product.image_url ? (
															<Image source={{ uri: product.image_url }} className="w-14 h-14 rounded-xl" />
														) : (
															<View className="w-14 h-14 rounded-xl bg-accent items-center justify-center">
																<Text className="text-white text-xl">📦</Text>
															</View>
														)}
														<View className="flex-1">
															<Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>{product.name}</Text>
															<Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`} numberOfLines={1}>
																{product.description || "Water product"}
															</Text>
														</View>
														<View className="items-end">
															<Text className="font-sans-bold text-green-500">{formatMoney(displayPrice)}</Text>
															{product.discount > 0 && (
																<Text className="text-xs text-red-400 line-through">{formatMoney(product.price)}</Text>
															)}
														</View>
													</View>
												</PressableScale>
											);
										}

										if (item.isVendor) {
											const vendor = item;
											return (
												<PressableScale activeOpacity={0.7} onPress={() => router.push(`/(screens)/vendor/${vendor.id}`)}>
													<View className={`flex-row items-center gap-4 p-4 mb-3 rounded-2xl border ${darkTheme ? "bg-white/5 border-transparent" : "bg-white border-gray-200"}`} style={darkTheme ? undefined : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}>
														{vendor.profile_pic ? (
															<Image source={{ uri: vendor.profile_pic }} className="w-14 h-14 rounded-full" />
														) : (
															<View className="w-14 h-14 rounded-full bg-accent items-center justify-center">
																<Text className="text-white text-xl">🏪</Text>
															</View>
														)}
														<View className="flex-1">
															<Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>{vendor.business_name}</Text>
															<View className="flex-row items-center mt-1">
																<Ionicons name="location" size={16} color={BRAND.primary} />
																<Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`} numberOfLines={1}>
																	{vendor.location_address || "Water Vendor"}
																</Text>
															</View>
															{/* Searching for a shop by name is the surface where
															    "is it open" matters most — the customer already
															    knows which one they want. */}
															<View className="mt-1">
																<StoreClosedNotice store={vendor} compact />
															</View>
														</View>
														<View className="items-end">
															<Text className="font-sans-bold text-yellow-500">⭐ {vendor.rating?.toFixed(1) || "5.0"}</Text>
														</View>
													</View>
												</PressableScale>
											);
										}
										return null;
									}}
								/>
							)}
						</View>
					</>
				)}

				{!hasSearched && (
					<View style={{ flex: 1 }}>
						{(!showHistory || history.length === 0) ? (
							<ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom + 16 }}>
								<EmptyState mood="search" title="Search for products and vendors" subtitle="Type what you need in the search bar" />
							</ScrollView>
						) : null}
					</View>
				)}

				{/* Location Permission Prompt Modal */}
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
									To find the closest water vendors and products, please enable location permissions in your settings.
								</Text>
							</View>
							
							<PressableScale
								onPress={() => {
									Linking.openSettings();
								}}
								className="bg-primary py-3 rounded-xl items-center mb-3"
							>
								<Text className="text-white font-sans-bold">Open Settings</Text>
							</PressableScale>
							
							<PressableScale
								onPress={() => requestLocation()}
								className={`py-3 rounded-xl items-center ${darkTheme ? "bg-gray-800" : "bg-white"}`}
							>
								<Text className={`font-sans-bold ${darkTheme ? "text-gray-300" : "text-gray-600"}`}>I've enabled it, try again</Text>
							</PressableScale>
						</View>
					</View>
				</Modal>

			</View>
		</>
	);
}