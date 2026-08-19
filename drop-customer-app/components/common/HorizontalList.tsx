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
import { estimateDeliveryTime } from "@/utils/distance";
import { Skeleton, SkeletonText, SkeletonAvatar } from "../ui/Skeleton";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";
import ProductCard from "@/components/common/ProductCard";
import { useAddToCartAction } from "@/hooks/useAddToCartAction";

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
	const { addToCart, isAdding } = useAddToCartAction();


	// <----------------FUNCTIONS----------------> 
	// API CALLS
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
					renderItem={({ item }: { item: any }) =>
						/* Products render `components/common/ProductCard` — the same
						   component Deals & Offers uses. This markup used to live
						   here, and the offers screen carried its own copy with a
						   4pt radius against this one's 24, a bare `bg-black`
						   against a bordered surface, a plain `Image` against
						   `expo-image`, a 60pt discount ribbon against 65, and no
						   add control at all. Two hand-kept copies of one card
						   drift by definition; there is now one. */
						type === "product" ? (
							<ProductCard
								item={item}
								width={w * 0.38}
								darkTheme={darkTheme}
								onPress={() => router.push(`/product-details/${item.id}`)}
								onAddToCart={() => addToCart(item.id)}
								isAdding={isAdding(item.id)}
								userLat={User?.lat}
								userLng={User?.lng}
							/>
						) : (
							<PressableScale
								onPress={() => router.push(`/vendor/${item.id}`)}
								activeOpacity={0.9}
							>
								<View
									className={`overflow-hidden relative border ${darkTheme
											? "bg-surface-container border-outline-variant"
											: "bg-white border-gray-200"
										}`}
									style={darkTheme ? { width: w * 0.38, borderRadius: 24 } : { width: w * 0.38, borderRadius: 24, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
								>
									{/* IMAGE (PERFECT SQUARE) */}
									<View className="w-full" style={{ height: w * 0.38 }}>
										<Image
											source={{ uri: item.profile_pic }}
											style={{ width: '100%', height: '100%', borderRadius: 24 }}
											contentFit="cover"
											transition={200}
										/>
									</View>
									<View className="px-3 py-2">
										<Text
											className={`font-sans-bold text-sm ${darkTheme ? "text-white" : "text-gray-900"}`}
											numberOfLines={1}
										>
											{item.business_name}
										</Text>
										{/* A shut shop shows why it is shut instead of a delivery
										    estimate it cannot meet. The store page renders the same
										    component from the same server field — a card that says
										    open over a page that says paused is the version of this
										    bug people screenshot. */}
										{item.is_accepting_orders === false ? (
											<View className="mt-1">
												<StoreClosedNotice store={item} compact />
											</View>
										) : (
											<View className="flex-row gap-3 justify-between items-center mt-1">
												<View className="flex-row gap-1 items-center">
													<Ionicons name="bicycle" size={14} color={BRAND.primary} />
													<Text className={`text-xs ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
														{estimateDeliveryTime(item.lat, item.lng, User?.lat ?? undefined, User?.lng ?? undefined)}
													</Text>
												</View>
												<Text className={`text-xs font-sans-bold ${darkTheme ? "text-gray-400" : "text-gray-600"}`}>
													⭐ {Number(item.rating ?? 0).toFixed(1)}
												</Text>
											</View>
										)}
									</View>
								</View>
							</PressableScale>
						)
					}
				/>
			</View>
		</View>
	);
};

export default HorizontalList;
