import { usePathname, useRouter } from "expo-router";
import React, { useContext, useEffect, useState } from "react";
import * as Haptics from 'expo-haptics';
import {
    Dimensions,
    Image,
    Modal,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { SkeletonCard, SkeletonRow, Skeleton } from "@/components/ui/Skeleton";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";

import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAddToCart, isVendorConflict, vendorConflictInfo } from "@/hooks/queries/useCart";
import { errorMessage } from "@/API/errors";
import { useAddFavorite, useFavorites, useRemoveFavorite } from "@/hooks/queries/useFavorites";
import { useProduct } from "@/hooks/queries/useProducts";
import { useUserDetails } from "@/hooks/queries/useUser";
import { useAuth } from "@clerk/clerk-expo";
import { PressableScale } from "@/components/ui/PressableScale";
import { useLocation } from "@/hooks/useLocation";
import { useDeliveryFee } from "@/hooks/queries/useCart";
import { BRAND, TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { discountedPrice, formatMoney, isZeroMoney } from "@/utils/money";

const ProductDetails = () => {
	// <---------------HOOKES--------------->
	const router = useRouter();
	const { fetchCart } = useContext(Context);
	const { getToken } = useAuth();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const { data: User } = useUserDetails();

	// <---------------STATES--------------->
	const [Product, setProduct] = useState<any>();
	const [ProductLoaded, setProductLoaded] = useState<boolean>(false);
	const [Quantity, setQuantity] = useState(1);
	const [loading, setLoading] = useState<boolean>(false);
    const [location, setLocation] = useState<string>("");
    
    const { mutateAsync: addToCartMutation } = useAddToCart();
    const { data: favorites = [] } = useFavorites();
    const { mutateAsync: addFavorite } = useAddFavorite();
    const { mutateAsync: removeFavorite } = useRemoveFavorite();

	// <---------------VARIABLES--------------->

	const path = usePathname();
	const id = path.split("/")[2];
	// <---------------FUNCTIONS--------------->
    const { data: ProductData, isSuccess: queryLoaded } = useProduct(id as string);
    const { location: userDeviceLocation } = useLocation();

    // Prefer saved location coordinates if available, otherwise device GPS
    const userLat = User?.lat || userDeviceLocation?.coords?.latitude;
    const userLng = User?.lng || userDeviceLocation?.coords?.longitude;
    const vendorLat = Product?.vendor?.lat;
    const vendorLng = Product?.vendor?.lng;
    const vendorType = Product?.vendor?.vendor_type || 'retail_refill';

	const { data: deliveryFeeData, isLoading: deliveryFeeLoading } = useDeliveryFee(
		vendorLat,
		vendorLng,
		userLat,
		userLng,
		vendorType,
		'motorbike'
	);

	useEffect(() => {
		if (queryLoaded && ProductData) {
			setProduct(ProductData);
			setProductLoaded(true);
			
			// Extract vendor location from product data if available
			if (ProductData?.vendor?.location_address) {
				setLocation(ProductData.vendor.location_address);
			} else if (ProductData?.vendor) {
				// Fallback to constructing location from vendor data
				const vendor = ProductData.vendor as any;
				const locationParts = [
					vendor.name,
					vendor.address_line_1,
					vendor.address_line_2,
					vendor.city,
					vendor.state,
					vendor.zip_code
				].filter(part => part && typeof part === "string" && part.trim() !== '');
				
				if (locationParts.length > 0) {
					setLocation(locationParts.join(', '));
				} else {
					setLocation("Location not available");
				}
			} else {
				setLocation("Location not available");
			}
		}
	}, [queryLoaded, ProductData]);

	// Initialize quantity to vendor-defined minimum order quantity once product loads
	useEffect(() => {
		if (Product?.minimum_order_qty && Product.minimum_order_qty > 1) {
			setQuantity(Product.minimum_order_qty);
		}
	}, [Product?.minimum_order_qty]);

	const add_to_cart = async (forceReplace = false) => {
		setLoading(true);
		const payload = {
			id: id,
			quantity: Quantity,
			force_replace: forceReplace,
		};
		if (__DEV__) console.log(payload)
		try {
            await addToCartMutation(payload);
			fetchCart()
			setLoading(false);
		} catch (error: unknown) {
			setLoading(false);
			// `useApiRequest` normalises every failure into an `ApiError`, which has
			// no `.response` — reading `error.response.data.type` was always
			// `undefined`, so the replace-cart prompt never appeared and a customer
			// with another vendor's items simply could not add this one.
			if (isVendorConflict(error)) {
				const { existingVendor } = vendorConflictInfo(error);
				Popup.show({
					title: "Replace Cart?",
					message: `Your cart has items from ${existingVendor}. Adding this will replace your current cart.`,
					cancelText: "Cancel",
					confirmText: "Replace",
					isDestructive: true,
					onConfirm: () => {
						Popup.hide();
						add_to_cart(true);
					}
				});
			} else {
                Toast.error("Failed to add", errorMessage(error, "Could not add item to cart."));
            }
		}
	};

	const isFavorite = favorites.some((f: any) => f.product_id === id);

	const handleToggleFavorite = async () => {
		try {
			if (isFavorite) {
				await removeFavorite(id as string);
			} else {
				await addFavorite(id as string);
			}
		} catch (e) {
			if (__DEV__) console.error("Favorite toggle failed:", e);
		}
	};

	// Direct checkout hook that bypasses cart
	const directCheckout = async (forceReplace = false) => {
		setLoading(true);
		const payload = {
			id: id,
			quantity: Quantity,
			force_replace: forceReplace,
		};
		if (__DEV__) console.log("Direct checkout via Add To Cart bypass:", payload);
		try {
			// Direct Checkout flow: Route first to AddToCart, then jump to Cart page
            await addToCartMutation(payload);
			fetchCart(); // Ensure global context updates
			setLoading(false);
			
			// Navigate to Cart screen to complete the flow with Payment methods and Address integration
			router.push("/(screens)/Cart");
		} catch (error: unknown) {
			setLoading(false);
			if (isVendorConflict(error)) {
				const { existingVendor } = vendorConflictInfo(error);
				Popup.show({
					title: "Replace Cart?",
					message: `Your cart has items from ${existingVendor}. Adding this will replace your current cart.`,
					cancelText: "Cancel",
					confirmText: "Replace & Checkout",
					isDestructive: true,
					onConfirm: () => {
						Popup.hide();
						directCheckout(true);
					}
				});
			} else {
				if (__DEV__) console.error("Direct checkout error:", error);
                Toast.error("Failed to checkout", errorMessage(error, "Could not proceed to checkout."));
			}
		}
	};

	// stockAvailable derived entirely from live API response — synced with DB schema
	const stockAvailable: boolean = Product?.is_available === true && Product?.stock != null && Product.stock > 0;
	const minQty = Product?.minimum_order_qty || 1;
	const maxStock = Product?.stock || 0;

	/**
	 * The server's estimate, for the distance to *this* customer.
	 *
	 * `/api/delivery-fee` — already called above for the fee — returns
	 * `estimated_minutes` off the same Haversine distance it prices. This
	 * screen ignored it and derived its own from `vendor.delivery_radius`,
	 * which was wrong twice: that column is one the vendor typed and dispatch
	 * has never read, and a radius is the distance to the *edge of the
	 * catchment*, so every customer saw the estimate for the furthest possible
	 * address regardless of living next door. A store that set 15 km quoted
	 * "45 min–1.5 hrs" to the flat above it.
	 */
	const getEstimatedDelivery = (): string => {
		const minutes = deliveryFeeData?.estimated_minutes;
		if (!minutes || minutes <= 0) return "30-60 min";
		// A range, because a single figure reads as a promise. The server's
		// number is the midpoint.
		const low = Math.max(10, Math.round(minutes * 0.75));
		const high = Math.round(minutes * 1.5);
		if (high <= 60) return `${low}-${high} min`;
		return `${(low / 60).toFixed(1)}-${(high / 60).toFixed(1)} hrs`;
	};

	return (
		<>
			<StatusBar
				backgroundColor="transparent"
				barStyle={darkTheme ? "light-content" : "dark-content"}
                translucent
			/>
			<View className={`flex-1 ${darkTheme ? "bg-[#0e0e0e]" : "bg-white"}`}>
				{/* Top Actions overlay */}
				<View className="absolute z-20 w-full px-5 flex-row justify-between" style={{ top: (StatusBar.currentHeight || 0) + 10 }}>
					<PressableScale activeOpacity={0.7} onPress={() => router.back()}>
						<BackButtonMinimal />
					</PressableScale>
					<PressableScale accessibilityLabel={isFavorite ? "Remove from your favourites" : "Add to your favourites"} activeOpacity={0.7} onPress={handleToggleFavorite}>
						<View 
							className="w-10 h-10 items-center justify-center rounded-full"
							style={{
								backgroundColor: darkTheme ? BRAND.bgDark : BRAND.white,
								boxShadow: `2px 2px 20px ${darkTheme ? "#f1f1f140" : "#00000070"}`,
								zIndex: 20,
							}}
						>
							<Ionicons 
								name={isFavorite ? "heart" : "heart-outline"} 
								size={22} 
								color={isFavorite ? BRAND.primary : (darkTheme ? BRAND.white : BRAND.bgDark)} 
							/>
						</View>
					</PressableScale>
				</View>

				{!ProductLoaded ? (
					// Professional 1:1 Skeleton Layout
					<View className="flex-1">
						{/* Professional Image Placeholder (No Skeleton) */}
						<View className="w-full relative items-center justify-center" style={{ height: Dimensions.get('window').height * 0.45, backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white }}>
							<Ionicons name="water-outline" size={60} color={darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)"} />
						</View>

						{/* Bottom Sheet Skeleton */}
						<View className="flex-1 -mt-6 px-5 pt-6 pb-5 rounded-t-[32px]" style={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}>
							{/* Title & Price */}
							<View className="flex-row justify-between mb-6">
								<Skeleton width="60%" height={32} borderRadius={8} />
								<Skeleton width="25%" height={32} borderRadius={8} />
							</View>
							
							{/* Description */}
							<View className="mb-6 gap-2">
								<Skeleton width="100%" height={16} borderRadius={4} />
								<Skeleton width="80%" height={16} borderRadius={4} />
							</View>

							{/* Specifications Row */}
							<View className="flex-row gap-3 mb-6">
								<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={40} height={12} borderRadius={4} style={{ marginBottom: 8 }} />
									<Skeleton width={30} height={16} borderRadius={4} />
								</View>
								<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={40} height={12} borderRadius={4} style={{ marginBottom: 8 }} />
									<Skeleton width={40} height={16} borderRadius={4} />
								</View>
								<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={50} height={12} borderRadius={4} style={{ marginBottom: 8 }} />
									<Skeleton width={50} height={16} borderRadius={4} />
								</View>
							</View>

							{/* Availability & Delivery Row */}
							<View className="flex-row gap-3 mb-6">
								<View className="flex-1 p-4 rounded-[20px] border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={60} height={14} borderRadius={4} style={{ marginBottom: 8 }} />
									<Skeleton width={80} height={18} borderRadius={4} />
								</View>
								<View className="flex-1 p-4 rounded-[20px] border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={50} height={14} borderRadius={4} style={{ marginBottom: 8 }} />
									<Skeleton width={70} height={18} borderRadius={4} />
								</View>
							</View>

							{/* Vendor Snippet */}
							<View className="mb-6">
								<Skeleton width={70} height={20} borderRadius={6} style={{ marginBottom: 12 }} />
								<View className="p-4 rounded-[20px] flex-row items-center gap-3 border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Skeleton width={48} height={48} borderRadius={24} />
									<View className="flex-1 gap-2">
										<Skeleton width="60%" height={16} borderRadius={4} />
										<Skeleton width="40%" height={12} borderRadius={4} />
									</View>
								</View>
							</View>
						</View>
					</View>
				) : (
					<ScrollView
						className="flex-1"
						contentContainerStyle={{ paddingBottom: 120 }}
						showsVerticalScrollIndicator={false}
						bounces={false}
						overScrollMode="never"
					>
						{/* Product Image Hero */}
						<View className="w-full relative" style={{ height: Dimensions.get('window').height * 0.45, backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white }}>
							<Image
								source={{ uri: Product?.image_url }}
								className="w-full h-full"
								resizeMode="cover"
							/>
						</View>

						{/* Details Sheet */}
						<View className="flex-1 -mt-6 px-5 pt-6 pb-5 rounded-t-[32px]" style={{ backgroundColor: darkTheme ? BRAND.bgDark : BRAND.bgLight }}>
							
							{/* Title & Price row */}
							<View className="flex-row justify-between items-start mb-2">
								<View className="flex-1 pr-4">
									<Text className={`text-2xl font-heading-semibold ${darkTheme ? "text-white" : "text-black"}`}>
										{Product?.name}
									</Text>
								</View>
								<View className="items-end">
									<Text className="text-2xl font-sans-bold" style={{ color: BRAND.blue }}>
										{formatMoney(discountedPrice(Product?.price, Product?.discount))}
									</Text>
                                    <View className="flex-row items-center mt-0.5 gap-1">
                                        {Product?.capacity > 0 && Product?.unit !== "pack" && Product?.unit !== "unit" && (
                                            <Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                                {/* A unit rate, not money: the exact net price divided
                                                    by the bottle's litres, for comparison between sizes.
                                                    The subtraction stays in cents; only the division —
                                                    whose output is a label, never a charge — becomes a
                                                    number. */}
                                                KSH {(Number(discountedPrice(Product?.price, Product?.discount)) / Product.capacity).toFixed(1)} /L
                                            </Text>
                                        )}
                                        {Product?.unit && Product?.capacity > 0 && Product?.unit !== "pack" && Product?.unit !== "unit" && (
                                            <Text className={`text-[10px] ${darkTheme ? "text-gray-600" : "text-gray-400"}`}>•</Text>
                                        )}
                                        {Product?.unit && (
                                            <Text className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                                                1 {Product.unit}
                                            </Text>
                                        )}
                                    </View>
								</View>
							</View>
							
							{/* Description */}
							<Text className={`text-base leading-relaxed mb-4 ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
								{Product?.description || "High-quality purified water."}
							</Text>

							{/* Product Specifications */}
							<View className="flex-row gap-3 mb-6">
								{Product?.capacity != null && (
									<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
										<Text className={`text-xs mb-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Capacity</Text>
										<Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-black"}`}>{Product.capacity}L</Text>
									</View>
								)}
								{Product?.weight_kg != null && (
									<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
										<Text className={`text-xs mb-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Weight</Text>
										<Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-black"}`}>{Product.weight_kg} kg</Text>
									</View>
								)}
								{minQty > 1 && (
									<View className="flex-1 p-3 rounded-2xl items-center border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
										<Text className={`text-xs mb-1 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>Min. Order</Text>
										<Text className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-black"}`}>{minQty} {Product?.unit || 'units'}</Text>
									</View>
								)}
							</View>

							{/* Info Cards Row (Availability & Delivery Time) */}
							<View className="flex-row gap-3 mb-6">
								<View className="flex-1 p-4 rounded-[20px] border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Text className={`text-sm mb-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Availability</Text>
									<Text className="font-sans-bold" style={{ color: stockAvailable ? TOAST.success : TOAST.error }}>
										{stockAvailable ? "In Stock" : "Out Of Stock"}
									</Text>
								</View>
								<View className="flex-1 p-4 rounded-[20px] border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
									<Text className={`text-sm mb-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Delivery</Text>
                                    {deliveryFeeLoading ? (
                                        <View className="mt-1"><Skeleton width={60} height={16} /></View>
                                    ) : (
                                        <>
                                            <Text className={`font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{getEstimatedDelivery()}</Text>
                                            {deliveryFeeData?.delivery_fee !== undefined && (
                                                <Text 
                                                    className={`text-xs mt-1 ${!isZeroMoney(deliveryFeeData.delivery_fee) ? (darkTheme ? "text-gray-400" : "text-gray-500") : "font-sans-bold"}`}
                                                    style={isZeroMoney(deliveryFeeData.delivery_fee) ? { color: TOAST.success } : {}}
                                                >
                                                    {isZeroMoney(deliveryFeeData.delivery_fee) ? "Free Delivery" : formatMoney(deliveryFeeData.delivery_fee)}
                                                </Text>
                                            )}
                                        </>
                                    )}
								</View>
							</View>

							{/* Vendor Snippet */}
							<View className="mb-6">
								<Text className={`text-lg font-sans-bold mb-3 ${darkTheme ? "text-white" : "text-black"}`}>Vendor</Text>
								<PressableScale 
									activeOpacity={0.9} 
									onPress={() => {
										if (Product?.vendor?.id || Product?.vendor_id) {
											router.push(`/(screens)/vendor/${Product?.vendor?.id || Product?.vendor_id}`);
										}
									}}
								>
									<View className="p-4 rounded-[20px] flex-row items-center justify-between border" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white, borderColor: darkTheme ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)" }}>
										<View className="flex-row items-center gap-3 flex-1">
											<View className="w-12 h-12 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden items-center justify-center">
												<Ionicons name="home" size={24} color={BRAND.primary} />
											</View>
											<View className="flex-1 pr-2">
												<Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`} numberOfLines={1}>
													{Product?.vendor?.business_name || "Vendor Name"}
												</Text>
												<Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-500"}`} numberOfLines={1}>
													{location}
												</Text>
											</View>
										</View>
										<View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-white/10" : "bg-black/5"}`}>
											<Image source={require("../../../assets/icons/maps-black.png")} className="w-4 h-4" tintColor={darkTheme ? "white" : "black"} />
										</View>
									</View>
								</PressableScale>
							</View>

							{/* Action Bar — inside scroll, directly below vendor */}
							<View className="mt-6">
								{/* Quantity Selector */}
								<View className="flex-row items-center justify-between mb-4">
									<Text className={`font-sans-bold text-base ${darkTheme ? "text-white" : "text-black"}`}>Quantity</Text>
									<View className="flex-row items-center justify-between px-2 py-2 rounded-full w-[130px]" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.gray200 }}>
										<PressableScale 
											activeOpacity={0.7} 
											onPress={() => setQuantity(Math.max(minQty, Quantity - 1))}
											disabled={Quantity <= minQty}
										>
											<View className={`w-10 h-10 rounded-full items-center justify-center ${Quantity <= minQty ? "opacity-30" : darkTheme ? "bg-white/10" : "bg-black/5"}`}>
												<Text className={`text-xl font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}>−</Text>
											</View>
										</PressableScale>
										
										<Text className={`font-sans-bold text-lg min-w-[28px] text-center ${darkTheme ? "text-white" : "text-black"}`}>{Quantity}</Text>
										
										<PressableScale 
											activeOpacity={0.7} 
											onPress={() => {
												const vendorType = Product?.vendor?.vendor_type;
												if (vendorType === "retail_refill" && Quantity >= 4) {
													Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
													Toast.error("Limit Reached", "Motorbikes can carry a maximum of 4 (20L) bottles per trip.");
													return;
												}
												if (Quantity < maxStock) setQuantity(Quantity + 1);
											}}
											disabled={!stockAvailable || Quantity >= maxStock}
										>
											<View className={`w-10 h-10 rounded-full items-center justify-center ${(!stockAvailable || Quantity >= maxStock) ? "opacity-30" : darkTheme ? "bg-white/10" : "bg-white shadow-sm"}`}>
												<Text className={`text-xl font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}>+</Text>
											</View>
										</PressableScale>
									</View>
								</View>

								{/* Subtotal */}
								<View className="flex-row items-center justify-between mb-5">
									<Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>Subtotal</Text>
									<Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
										KSH {Math.round(((Product?.price || 0) - (Product?.discount || 0)) * Quantity * 100) / 100}
									</Text>
								</View>

								{/* Add to Cart / Buy Now Buttons */}
								<View className="flex-row gap-3">
									<PressableScale activeOpacity={0.9} onPress={stockAvailable ? () => add_to_cart() : undefined} className="flex-1" disabled={!stockAvailable}>
										<View className={`h-[56px] rounded-full items-center justify-center border-2 ${!stockAvailable ? "opacity-40" : ""} ${darkTheme ? "bg-transparent" : "bg-white"}`} style={{ borderColor: BRAND.blue }}>
											<Text className="font-sans-bold text-sm" style={{ color: BRAND.blue }}>Add to Cart</Text>
										</View>
									</PressableScale>
									<PressableScale activeOpacity={0.9} onPress={stockAvailable ? () => directCheckout() : undefined} className="flex-1" disabled={!stockAvailable}>
										<View className={`h-[56px] rounded-full items-center justify-center ${!stockAvailable ? "opacity-40" : ""}`} style={{ backgroundColor: BRAND.blue, shadowColor: BRAND.blue, shadowOpacity: 0.3, shadowRadius: 4, shadowOffset: { width: 0, height: 4 }, elevation: 5 }}>
											<Text className="text-white font-sans-bold text-sm">Buy Now</Text>
										</View>
									</PressableScale>
								</View>
							</View>

						</View>
					</ScrollView>
				)}
			</View>

			<Modal visible={loading} transparent={true}>
				<View className="flex-1 items-center justify-center bg-black/50">
					<View className="p-6 rounded-[24px] items-center justify-center w-[80%] max-w-xs shadow-2xl" style={{ backgroundColor: darkTheme ? BRAND.gray800 : BRAND.white }}>
						<Ionicons name="sync" size={40} color={BRAND.primary} />
						<Text className={`font-sans-bold mt-2 ${darkTheme ? "text-white" : "text-black"}`}>Processing...</Text>
					</View>
				</View>
			</Modal>
		</>
	);
};

export default ProductDetails;
