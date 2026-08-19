import { useApiClient } from "@/API/useApiClient";
import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth } from "@clerk/clerk-expo";
import { useUserDetails } from "@/hooks/queries/useUser";

import { BRAND } from '@/constants/brandColors';
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import React, { useContext, useState } from "react";
import {
    useWindowDimensions,
    View,
    FlatList,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { useAddToCart, isVendorConflict, vendorConflictInfo } from "@/hooks/queries/useCart";
import { estimateDeliveryTime } from "@/utils/distance";
import { Skeleton, SkeletonText, SkeletonAvatar } from "../ui/Skeleton";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { Popup } from "@/lib/popup";
import { Toast } from "@/lib/toast";
import { errorMessage } from "@/API/errors";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import { discountPercent, discountedPrice, formatMoney, isZeroMoney } from "@/utils/money";

type Props = {
	title: string;
	/** Optional right-hand action in the section header. */
	onSeeAll?: () => void;
	type?: string;
	data: any[];
	loaded?: boolean;
};

const HorizontalList = ({ title, type, data, loaded, onSeeAll }: Props) => {
	const { width, height } = useWindowDimensions();
	const w = Math.ceil(width);
	const h = Math.ceil(height);

	// <-----------------<HOOKS>----------------->
	const router = useRouter();
	const { currentTheme } = useContext(UIThemeContext);
	const { data: User } = useUserDetails()
	const darkTheme = currentTheme === "dark";
	const { mutate: addToCartMutation, isPending: AddToCartLoading } = useAddToCart();

	const [clickedItemId, setClickedItemId] = useState<string | null>(null);

	// <----------------FUNCTIONS----------------> 
	// API CALLS
	const AddToCart = (id: string, forceReplace = false) => {
		setClickedItemId(id);
		addToCartMutation({
			id: id,
			quantity: 1,
			force_replace: forceReplace,
		}, {
			onSettled: () => {
				setClickedItemId(null);
			},
			onError: (error: Error) => {
				// The vendor name lives on `ApiError.detail`; reading it off the
				// error itself rendered "Your cart has items from undefined."
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
							AddToCart(id, true);
						}
					});
					return;
				}
				// Every other failure used to be swallowed entirely: tapping "add"
				// on a sold-out item from the home screen did nothing at all, with
				// no explanation. This is the app's busiest add-to-cart surface.
				Toast.error("Couldn't add to cart", errorMessage(error, "Please try again."));
			}
		});
	}

	if (!loaded && (!data || data.length === 0)) {
		return (
			<View className={` ${darkTheme ? "" : ""} shadow-2x`}>
				<View className="px-5 justify-between flex-row items-center pt-2 pb-2">
					<SkeletonText width={120} style={{ height: 16 }} />
				</View>
				<View style={{ height: w * 0.4, width: '100%', marginTop: 5 }}>
					<FlatList
						horizontal={true}
						data={[...Array(3)]}
						showsHorizontalScrollIndicator={false}
						contentContainerStyle={{ paddingHorizontal: 20 }}
						ItemSeparatorComponent={() => <View style={{ width: 10 }} />}
						renderItem={({ index }: { index: number }) => (
							<View
								key={index}
								className={`relative overflow-hidden justify-end rounded shadow ${darkTheme ? "bg-gray-200/10" : "bg-white"
									}`}
								style={{ width: w * 0.36, height: '100%' }}
							>
								<Skeleton width="100%" height="100%" style={{ position: 'absolute' }} />
								<View
									className="justify-end h-[45%] z-10 w-full"
									style={{ backgroundColor: darkTheme ? "rgba(0,0,0,0.8)" : "rgba(255,255,255,0.8)" }}
								>
									<View className="gap-2 p-2">
										<SkeletonText width="70%" style={{ height: 12 }} />
										<SkeletonText width={type === "product" ? "60%" : "30%"} style={{ height: 12 }} />
										{type === "product" && (
											<View style={{ position: 'absolute', bottom: 4, right: 4 }}>
												<SkeletonAvatar size={30} />
											</View>
										)}
									</View>
								</View>
							</View>
						)}
					/>
				</View>
			</View>
		);
	}

	if (loaded && (!data || !Array.isArray(data) || data.length === 0)) {
		return null;
	}

	return (
		<View className={`  ${darkTheme ? "" : ""} shadow-2x`}>
			<View className="px-5 py-3 justify-between flex-row items-center">
				<Text className={` text-xl font-sans-semibold ${darkTheme ? "text-white" : "text-black"}`}>{title}</Text>
				{onSeeAll && (
					<PressableScale onPress={onSeeAll} hitSlop={8}>
						<Text className="text-sm font-sans-semibold" style={{ color: BRAND.primary }}>See all</Text>
					</PressableScale>
				)}
			</View>
			<View style={{ height: w * 0.52, width: '100%', marginTop: 5 }}>
				<FlatList
					horizontal
					data={data}
					// Products and vendors both carry an id. Keyed on position instead,
					// a refresh that reorders the row — a store going offline, a product
					// selling out — leaves the previous item's image in place.
					keyExtractor={(item: any, index: number) => String(item?.id ?? index)}
					showsHorizontalScrollIndicator={false}
					contentContainerStyle={{ paddingHorizontal: 20 }}
					ItemSeparatorComponent={() => <View style={{ width: 10 }} />}
					renderItem={({ item, index }: { item: any, index: number }) => (
						<PressableScale
							onPress={() => {
								if (type === "product") {
									router.push(`/product-details/${item.id}`);
								} else {
									router.push(`/vendor/${item.id}`);
								}
							}}
							activeOpacity={0.9}
						>
							<View
								className={`overflow-hidden relative h-full border ${darkTheme
										? "bg-surface-container border-outline-variant"
										: "bg-white border-gray-200"
									}`}
								style={darkTheme ? { width: w * 0.38, borderRadius: 24 } : { width: w * 0.38, borderRadius: 24, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
							>
								{type === "product" && !isZeroMoney(item.discount) && (
									<View
										className={`absolute w-[65px]  bg-red-500 z-20 top-0 right-0 items-center justify-center rotate-45 translate-x-5 translate-y-2`}
									>
										<Text className={`text-white font-sans-semibold`}>
											{item.price ? `${discountPercent(item.price, item.discount)}%` : "Sale"}
										</Text>
									</View>
								)}
								{/* IMAGE (PERFECT SQUARE) */}
								<View className="w-full" style={{ height: w * 0.38 }}>
									{
										type == "product" ? (
											<Image
												source={{ uri: item.image_url }}
												style={{ width: '100%', height: '100%', borderRadius: 24 }}
												contentFit="cover"
												transition={200}
											/>
										) : (
											<Image
												source={{ uri: item.profile_pic }}
												style={{ width: '100%', height: '100%', borderRadius: 24 }}
												contentFit="cover"
												transition={200}
											/>
										)
									}
								</View>
								{/* TEXT CONTENT WRAPPER — sized by its content, never `flex-1`.
								    The card is a fixed-width, auto-height column, so
								    `flex-1` resolves to `flexBasis: 0` with no free
								    space to grow into and the row collapses to zero
								    height under the card's `overflow-hidden`. Same
								    defect as the home grid: the name and the price
								    are there, laid out, and clipped to nothing. */}
								<View className="px-3 py-2">
									{/* <-----------------<RENDER ACCORDING TO TYPE OF LIST>-----------------> */}
									{type === "product" ? (
										/* `pr-9` reserves the gutter the add-to-cart button sits
										   in. That button is absolutely positioned inside this
										   same block (bottom-8 right-8, 32px wide), so it is out
										   of flow and the name knows nothing about it — a long
										   one runs straight underneath, and `numberOfLines={1}`
										   ellipsises against the card edge rather than against
										   the button. On the shelf that read as
										   "Bale 1L Branded (12-p[cart]ck)". Only the product
										   branch needs it; the vendor branch has no button. */
										<Text
											className={`font-sans-bold text-sm pr-9 ${darkTheme ? "text-white" : "text-gray-900"}`}
											numberOfLines={1}
										>
											{item.name}
										</Text>
									) : (
										<Text
											className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-gray-900"}`}
											numberOfLines={1}
										>
											{item.business_name}
										</Text>
									)}

									{/* <-----------------<RENDER ACCORDING TO TYPE OF LIST>-----------------> */}
									{type === "product" ? (
										// <---------------------<PRODUCT PRICE>--------------------->
										<View className={`flex-row gap-2 items-center mt-0.5 pr-9`}>
											<Text className={`font-sans-semibold text-sm ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
												{formatMoney(discountedPrice(item.price, item.discount))}
											</Text>
											{!isZeroMoney(item.discount) && (
												<Text
													className={`text-xs ${darkTheme ? "text-gray-500" : "text-gray-400"}`}
													style={{
														textDecorationLine: "line-through"
													}}
												>
													{item.price}
												</Text>
											)}
										</View>
									) : (
										// <------------------------<RATING>------------------------->
										// A shut shop shows why it is shut instead of a delivery
										// estimate it cannot meet. The store page renders the same
										// component from the same server field — a card that says
										// open over a page that says paused is the version of this
										// bug people screenshot.
										item.is_accepting_orders === false ? (
											<View className="mt-1">
												<StoreClosedNotice store={item} compact />
											</View>
										) : (
										<View className="flex-row gap-3 justify-between items-center mt-1">
											<View className="flex-row gap-1 items-center">
												<Ionicons name="bicycle" size={14} color={BRAND.primary} />
												<Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>{estimateDeliveryTime(item.lat, item.lng, User?.lat ?? undefined, User?.lng ?? undefined)}</Text>
											</View>
											<Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
												⭐ {Number(item.rating).toFixed(1)}
											</Text>
										</View>
										)
									)}

									{/* <--------------------<ADD TO CART BUTTON>--------------------> */}
									{type === "product" && (
										<PressableScale
											activeOpacity={0.6}
											style={{ position: "absolute", bottom: 8, right: 8 }}
											onPress={() => AddToCart(item.id)}
										>
											<View className={`${darkTheme ? 'bg-white/10' : 'bg-white'} p-2 w-[32px] h-[32px] items-center justify-center rounded-xl`}>
												{AddToCartLoading && clickedItemId === item.id ? (
													<SkeletonAvatar size={16} />
												) : (
													<Image
														source={require("../../assets/icons/addtocart-black.png")}
														style={{ width: 16, height: 16 }}
														tintColor={darkTheme ? "white" : "black"}
													/>
												)}
											</View>
										</PressableScale>
									)}
								</View>
							</View>
						</PressableScale>
					)}
				/>
			</View>
		</View>
	);
};

export default HorizontalList;
