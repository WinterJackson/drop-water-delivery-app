import React, { useContext } from "react";
import {
    Dimensions,
    Image,
    ImageBackground,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import HorizontalList from "@/components/common/HorizontalList";
import Reviews from "@/components/common/Reviews";
import { SkeletonCard } from "@/components/ui/Skeleton";
import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useVendorDetails } from "@/hooks/queries/useProducts";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useAddToCart, isVendorConflict, vendorConflictInfo } from "@/hooks/queries/useCart";
import { errorMessage } from "@/API/errors";
import { useVendorFavorites, useAddVendorFavorite, useRemoveVendorFavorite } from "@/hooks/queries/useVendorFavorites";
import { useAuth } from "@clerk/clerk-expo";
import { LinearGradient } from "expo-linear-gradient";
import { usePathname, useRouter } from "expo-router";
import { PressableScale } from "@/components/ui/PressableScale";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { formatMoney, formatMoneyShort } from "@/utils/money";

type Props = {};

const { height: screenHeight } = Dimensions.get("window");

const VendorDetails = (props: Props) => {
	// <-------------------<HOOKES>------------------->
	const router = useRouter();
	const path = usePathname();
	const auth = useAuth();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const { fetchCart } = useContext(Context);
	const { data: User } = useUserDetails();

	// <--------------------STATES----------------------->
	const vendorId = path?.split("/")[2];

	const { data: VendorDetails, isLoading } = useVendorDetails(vendorId);
	const VendorDetailsLoaded = !isLoading;

	// Vendor favourite state synced globally with optimistic UI cache
	const { data: favorites = [] } = useVendorFavorites();
	const isVendorFavorite = favorites.some((f: any) => f.vendor_id === vendorId);

	const { mutateAsync: addVendorFav, isPending: addingFav } = useAddVendorFavorite();
	const { mutateAsync: removeVendorFav, isPending: removingFav } = useRemoveVendorFavorite();

	// Cart mutation
	const { mutateAsync: addToCartMutation } = useAddToCart();

	const Offers = React.useMemo(() => {
		if (VendorDetails?.products && Array.isArray(VendorDetails.products)) {
			return VendorDetails.products.filter((product: any) => product.discount > 0);
		}
		return [];
	}, [VendorDetails]);

	const Products = React.useMemo(() => {
		if (VendorDetails?.products && Array.isArray(VendorDetails.products)) {
			return VendorDetails.products.filter((product: any) => product.discount === 0);
		}
		return [];
	}, [VendorDetails]);

	const handleToggleVendorFavorite = async () => {
		try {
			if (isVendorFavorite) {
				await removeVendorFav(vendorId);
			} else {
				await addVendorFav(vendorId);
			}
		} catch (e) {
			if (__DEV__) console.error("Vendor fav toggle failed:", e);
		}
	};

	const handleQuickAddToCart = async (productId: string, productName: string, forceReplace = false) => {
		try {
			await addToCartMutation({
				id: productId,
				quantity: 1,
				force_replace: forceReplace,
			});
			fetchCart();
			Toast.success("Added to Cart", `${productName} added to your cart`);
		} catch (e: unknown) {
			// The vendor name lives on `ApiError.detail`, not on the error itself:
			// the old read produced "Your cart has items from undefined."
			if (isVendorConflict(e)) {
				const { existingVendor } = vendorConflictInfo(e);
				Popup.show({
					title: "Replace Cart?",
					message: `Your cart has items from ${existingVendor}. Adding this will replace your current cart.`,
					cancelText: "Cancel",
					confirmText: "Replace",
					isDestructive: true,
					onConfirm: () => {
						Popup.hide();
						handleQuickAddToCart(productId, productName, true);
					}
				});
			} else {
				if (__DEV__) console.error("Quick add to cart failed:", e);
				Toast.error("Failed to add", errorMessage(e, "Could not add item to cart."));
			}
		}
	};

	return (
		<>
			<StatusBar
				barStyle={darkTheme ? "light-content" : "dark-content"}
				backgroundColor="transparent"
				translucent
			/>

			<View
				className={`flex-1 ${
					darkTheme ? "bg-[#0e0e0e]" : "bg-white"
				}`}
			>
				{/* <--------------------------<STICKY TOP BAR>--------------------------> */}
				<View
					className="absolute z-20 w-full px-5 items-center justify-between flex-row"
					style={{
						top: (StatusBar.currentHeight || 0) + 10,
					}}
				>
					{/* BACK BUTTON */}
					<PressableScale
						activeOpacity={0.7}
						onPress={() => {
							router.back();
						}}
					>
						<BackButtonMinimal />
					</PressableScale>
					{/* LIKE BUTTON */}
					<PressableScale accessibilityLabel={isVendorFavorite ? "Remove this shop from your favourites" : "Add this shop to your favourites"} activeOpacity={0.7} onPress={handleToggleVendorFavorite}>
						<View 
							className="w-10 h-10 items-center justify-center rounded-full"
							style={{
								backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
								boxShadow: `2px 2px 20px ${darkTheme ? "#f1f1f140" : "#00000070"}`,
								zIndex: 20,
							}}
						>
							<Ionicons 
								name={isVendorFavorite ? "heart" : "heart-outline"} 
								size={22} 
								color={isVendorFavorite ? BRAND.primary : (darkTheme ? BRAND.white : BRAND.bgDark)} 
							/>
						</View>
					</PressableScale>
				</View>

				<ScrollView
					overScrollMode={"never"}
					showsVerticalScrollIndicator={false}
					contentContainerStyle={{ paddingBottom: 120 }}
				>
					{/* <-------------------------<HERO SECTION>------------------------> */}
					<View className="w-full relative" style={{ height: screenHeight * 0.35 }}>
						<ImageBackground
							className="w-full h-full"
							source={{ uri: VendorDetails?.profile_pic }}
							resizeMode="cover"
						>
							<LinearGradient
								className="absolute inset-0 w-full h-full"
								colors={[
									"rgba(0,0,0,0.1)",
									darkTheme ? "rgba(14,14,14,0.4)" : "rgba(255,255,255,0.4)",
									darkTheme ? "rgba(14,14,14,1)" : "rgba(249,250,251,1)",
								]}
								locations={[0, 0.6, 1]}
							/>
						</ImageBackground>
						
						{/* Floating Vendor Name inside Hero */}
						{VendorDetailsLoaded && VendorDetails && (
							<View className="absolute bottom-6 left-5 right-5 z-20">
								<Text className={`text-3xl font-heading-semibold mb-1 flex-row items-center ${darkTheme ? "text-white" : "text-black"}`}>
									{VendorDetails?.business_name || "Vendor"}
								</Text>
								<View className="flex-row items-center gap-1">
									<Text className="text-[#3498db] font-sans-bold text-lg flex-row items-center">
										⭐ {Number(VendorDetails?.rating) || "4.8"}
									</Text>
								</View>
							</View>
						)}
					</View>

					{/* <-------------------------<VENDOR INFO SECTION>------------------------> */}
					{VendorDetailsLoaded && VendorDetails ? (
						<View className="px-5 -mt-2 relative z-20">
							<View 
								className="p-6 rounded-[24px] border"
								style={{ 
									backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
									borderColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', 
									...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) 
								}}
							>
								<View className="flex-col gap-3 mb-6">
									{/* Whether this shop is actually taking orders, above everything
									    else about it — a customer who reads the address, the delivery
									    time and the rating before finding out it is shut has been
									    sold something twice. Renders nothing when open. */}
									<StoreClosedNotice store={VendorDetails as any} />
									{/* Location */}
									<View className="flex-row items-center gap-3">
										<Image
											source={require("../../../assets/icons/maps-black.png")}
											className="w-5 h-5"
											tintColor={BRAND.primary}
										/>
										<Text className={`font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
											{VendorDetails?.location_address || "Location not available"}
										</Text>
									</View>
									{/* Delivery Time */}
									<View className="flex-row items-center gap-3">
										<Ionicons name="bicycle" size={20} color={BRAND.primary} />
										<Text className={`font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
											{VendorDetails?.delivery_time ? `Est. ${VendorDetails.delivery_time} min` : "Est. Delivery available"} • {VendorDetails?.delivery_fee ? `Fee: KSH ${VendorDetails.delivery_fee}` : "Delivery fee varies"}
										</Text>
									</View>
									{/* This store's own minimum order.
									    The server refuses a short basket at checkout with the exact
									    shortfall, which is the right refusal — but a minimum a
									    customer only meets by failing is the same trip wasted twice.
									    Stated here, before anything is in the basket, the way a
									    wholesale MOQ is. Rendered only when the store set one. */}
									{Number(VendorDetails?.min_order_value ?? 0) > 0 ? (
										<View className="flex-row items-center gap-3">
											<Ionicons name="basket-outline" size={20} color={BRAND.primary} />
											<Text className={`font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
												{formatMoneyShort(VendorDetails?.min_order_value)} minimum order
											</Text>
										</View>
									) : null}
									{/* And whether they take cash, which decides whether the
									    customer needs their phone at the door. */}
									{VendorDetails?.accepts_cash === false ? (
										<View className="flex-row items-center gap-3">
											<Ionicons name="phone-portrait-outline" size={20} color={BRAND.primary} />
											<Text className={`font-sans-medium ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
												M-Pesa only — this store is not taking cash
											</Text>
										</View>
									) : null}
								</View>
								
								{/* Add to Favourites Button */}
								<PressableScale
									activeOpacity={0.9}
									onPress={handleToggleVendorFavorite}
									disabled={addingFav || removingFav}
								>
									<View 
										className="w-full rounded-full h-[56px] flex-row items-center justify-center gap-2 border-2"
										style={{ 
											borderColor: isVendorFavorite ? BRAND.primary : (darkTheme ? BRAND.gray800 : BRAND.gray200), 
											backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white 
										}}
									>
										<Ionicons 
											name={isVendorFavorite ? "heart" : "heart-outline"} 
											size={20} 
											color={isVendorFavorite ? BRAND.primary : (darkTheme ? BRAND.white : BRAND.bgDark)} 
										/>
										<Text 
											className="font-sans-bold text-sm whitespace-nowrap" 
											style={{ color: isVendorFavorite ? BRAND.primary : (darkTheme ? BRAND.white : BRAND.bgDark) }}
										>
											{isVendorFavorite ? "Remove from Favourites" : "Add to Favourites"}
										</Text>
									</View>
								</PressableScale>
							</View>
						</View>
					) : (
						<View className="px-5 -mt-2 relative z-20">
							<View 
								className="p-6 rounded-[24px] border"
								style={{ 
									backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
									borderColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', 
									...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }) 
								}}
							>
								<View className="flex-col gap-5 mb-6">
									<View className="w-3/4 h-5 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
									<View className="w-1/2 h-5 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
								</View>
								<View className="w-full h-[56px] rounded-full" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
							</View>
						</View>
					)}

					{/* <---------------------------------<PRODUCTS GRID>---------------------------------> */}
					<View className="px-5 mt-8 gap-4">
						<Text className={`text-xl font-sans-bold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>Products</Text>
						
						{VendorDetailsLoaded ? (
							<View className="flex-row flex-wrap justify-between gap-y-4">
								{Products?.map((product: any, index: number) => {
									const isFeatured = index === 0;
									const cardWidth = isFeatured ? "w-full" : "w-[48%]";
									
									return (
										<PressableScale
											key={product.id}
											className={`${cardWidth} rounded-[20px] overflow-hidden border`}
											style={{ 
												backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
												borderColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' 
											}}
											onPress={() => router.push(`/product-details/${product.id}`)}
										>
											{isFeatured ? (
												<View className="w-full flex-row relative p-4" style={{ height: 180 }}>
													<View className="w-[55%] absolute top-0 right-0 h-full overflow-hidden">
														<Image
															source={{ uri: product.image_url }}
															className="w-full h-full"
															resizeMode="cover"
														/>
														<LinearGradient
															className="absolute inset-0 w-full h-full"
															colors={[darkTheme ? "rgba(27,31,36,1)" : "rgba(255,255,255,1)", "transparent"]}
															start={{ x: 0, y: 0 }}
															end={{ x: 1, y: 0 }}
														/>
													</View>
													<View className="w-2/3 z-10 flex-col justify-between h-full py-1">
														<View>
															<Text className={`text-lg font-sans-bold mb-1 ${darkTheme ? "text-white" : "text-black"}`}>{product.name}</Text>
															<Text className="text-[#3498db] text-xl font-sans-bold">{formatMoney(product.price)}</Text>
														</View>
														<PressableScale 
															activeOpacity={0.8}
															onPress={() => handleQuickAddToCart(product.id, product.name)}
														>
															<View className="w-10 h-10 rounded-full items-center justify-center" style={{ backgroundColor: 'rgba(52, 152, 219, 0.2)' }}>
																<Text className="text-[#3498db] text-2xl font-sans-bold">+</Text>
															</View>
														</PressableScale>
													</View>
												</View>
											) : (
												<View className="w-full flex-col justify-between p-3 gap-3 h-[200px]">
													<View className="w-full h-[100px] rounded-2xl overflow-hidden bg-gray-100 dark:bg-gray-800">
														<Image
															source={{ uri: product.image_url }}
															className="w-full h-full"
															resizeMode="cover"
														/>
													</View>
													<View className="flex-1 justify-between">
														<Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-black"}`} numberOfLines={1}>{product.name}</Text>
														<View className="flex-row justify-between items-center mt-2">
															<Text className="text-[#3498db] font-sans-bold">{formatMoney(product.price)}</Text>
															<PressableScale 
																activeOpacity={0.8}
																onPress={() => handleQuickAddToCart(product.id, product.name)}
															>
																<View className="w-8 h-8 rounded-full items-center justify-center" style={{ backgroundColor: darkTheme ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.05)' }}>
																	<Text className={`text-lg ${darkTheme ? "text-white" : "text-black"}`}>+</Text>
																</View>
															</PressableScale>
														</View>
													</View>
												</View>
											)}
										</PressableScale>
									);
								})}
							</View>
						) : (
							<View className="flex-row flex-wrap justify-between gap-y-4">
								{/* Featured Card Skeleton */}
								<View 
									className="w-full h-[180px] rounded-[20px] overflow-hidden border p-4 flex-row"
									style={{ 
										backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
										borderColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
									}}
								>
									<View className="w-2/3 h-full flex-col justify-between py-1 z-10">
										<View className="gap-2 mt-2">
											<View className="w-3/4 h-6 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
											<View className="w-1/2 h-6 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
										</View>
										<View className="w-10 h-10 rounded-full" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
									</View>
									<View className="w-[55%] absolute top-0 right-0 h-full" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
								</View>

								{/* Regular Card Skeletons */}
								{[1, 2, 3, 4].map((item) => (
									<View 
										key={item}
										className="w-[48%] h-[200px] rounded-[20px] overflow-hidden border p-3 flex-col justify-between"
										style={{ 
											backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
											borderColor: darkTheme ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
										}}
									>
										<View className="w-full h-[100px] rounded-2xl" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
										<View className="flex-1 justify-between mt-3">
											<View className="w-full h-4 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
											<View className="flex-row justify-between items-center">
												<View className="w-1/2 h-4 rounded-md" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
												<View className="w-8 h-8 rounded-full" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }} />
											</View>
										</View>
									</View>
								))}
							</View>
						)}
					</View>
					
					{/* <---------------------------------<REVIEWS>---------------------------------> */}
					<View className="px-5 mt-8 mb-8">
						<Reviews targetType="vendor" targetId={vendorId as string} />
					</View>
				</ScrollView>
			</View>
		</>
	);
};

export default VendorDetails;
