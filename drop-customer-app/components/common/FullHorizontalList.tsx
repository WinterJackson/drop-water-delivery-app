import { UIThemeContext } from "@/context/ThemeContext";
import Context from "@/context/context";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import React, { useContext } from "react";
import {
    useWindowDimensions,
    TouchableWithoutFeedback,
    View,
    StyleSheet,
    FlatList,
} from "react-native";
import { Text } from '@/components/ui/Text';

import { Skeleton, SkeletonText, SkeletonButton } from "../ui/Skeleton";
import { PressableScale } from "@/components/ui/PressableScale";
import { useUserDetails } from "@/hooks/queries/useUser";
import { estimateDeliveryTime } from "@/utils/distance";
import StoreClosedNotice from "@/components/common/StoreClosedNotice";

type Props = {
	data: any[];
	title?: string;
	loaded: boolean;
};

const FullHorizontalList = ({ title, data, loaded }: Props) => {
	const { width } = useWindowDimensions();
	const wid = Math.ceil(width);

	// <--------------------<HOOKS>-------------------->
	const router = useRouter();
	const { fetchCart } = useContext(Context)
	const { currentTheme } = useContext(UIThemeContext);
	const { data: User } = useUserDetails();
	const darkTheme = currentTheme === "dark";

	if (!loaded && (!data || data.length === 0)) {
		return (
			<View className="py-3">
				<View className="px-7 pb-2">
					<SkeletonText width={120} style={{ height: 16 }} />
				</View>
				<View style={{ height: 200, width: "100%" }}>
					<FlatList
						data={[...Array(3)]}
						renderItem={() => (
							<TouchableWithoutFeedback>
								<View
									className={`relative ${darkTheme ? "bg-gray-200/10" : "bg-white"
										} h-[190px] shadow-x overflow-hidden`}
									style={{ width: wid * 0.9, marginRight: wid * 0.05, borderRadius: 24 }}
								>
									<Skeleton width="100%" height="100%" style={{ position: 'absolute', borderRadius: 24 }} />
									<View className="w-full h-full justify-end overflow-hidden z-10">
										<LinearGradient
											className="w-full h-[80px] items-end flex-row gap-3 justify-between p-3 self-center"
											colors={[
												"transparent",
												darkTheme ? "rgba(0,0,0,0.8)" : "rgba(255,255,255,0.8)",
											]}
											style={{ borderRadius: 24 }}
										>
											<View className="items-start gap-2">
												<SkeletonText width={170} style={{ height: 14 }} />
												<SkeletonText width={100} style={{ height: 14 }} />
											</View>
											<SkeletonButton width={110} />
										</LinearGradient>
									</View>
								</View>
							</TouchableWithoutFeedback>
						)}
						keyExtractor={(_: any, index: number) => index.toString()}
						horizontal
						showsHorizontalScrollIndicator={false}
						contentContainerStyle={{
							paddingHorizontal: wid * 0.05,
							paddingVertical: 10
						}}
					/>
				</View>
			</View>
		);
	}

	if (loaded && (!data || !Array.isArray(data) || data.length === 0)) {
		return null;
	}

	return (
		<View className=" py-1">
			<View className="px-7 py-3">
				<Text className={`font-sans-semibold text-xl ${darkTheme ? "text-white" : "text-black"}`}>{title}</Text>
			</View>
			<View style={{ height: 200, width: "100%" }}>
				<FlatList
					data={Array.isArray(data) ? data : []}
					renderItem={({ item }: { item: any }) => (
						<TouchableWithoutFeedback onPress={() => router.push(`/vendor/${item.id}`)}>
							<View
								className={`relative border overflow-hidden h-[190px] ${darkTheme ? "bg-surface-container border-transparent" : "bg-white border-gray-200"}`}
								style={darkTheme ? { width: wid * 0.9, marginRight: wid * 0.05, borderRadius: 24 } : { width: wid * 0.9, marginRight: wid * 0.05, borderRadius: 24, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 }}
							>
								<View className="w-full h-full justify-end overflow-hidden">
									<Image
										source={{ uri: item?.products && item.products.length > 0 ? item.products[0].image_url : item.profile_pic }}
										className="absolute w-full h-full"
										style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0, borderRadius: 24 }}
										contentFit="cover"
									/>
									<LinearGradient
										className="w-full h-[60px] items-end flex-row gap-3  justify-between p-2 self-center"
										colors={[
											"transparent",
											darkTheme ? "black" : "white",
										]}
										style={{ borderRadius: 24 }}
									>
										<View className="items-start">
											<Text className={
													darkTheme
														? "text-white"
														: "text-black"
												}>{
													item.business_name.length >
														42
														? item.business_name
															.substring(
																0,
																39
															)
															.trim() + "..."
														: item.business_name
												}</Text>
											{/* A delivery estimate for a shop that is shut is a
											    promise the platform cannot keep. Same component,
											    same server field, as the store page. */}
											{item.is_accepting_orders === false ? (
												<StoreClosedNotice store={item} compact />
											) : (
											<View className="flex-row items-center gap-2">
												<Image
													source={require("../../assets/icons/bike-black.png")}
													className="w-5 h-5"
													tintColor={
														darkTheme
															? "white"
															: "black"
													}
													contentFit="contain"
												/>
												<Text className={
														darkTheme
															? "text-gray-200"
															: "text-gray-600"
													}>{estimateDeliveryTime(item.lat, item.lng, User?.lat ?? undefined, User?.lng ?? undefined)}</Text>
											</View>
											)}
										</View>
										{/* ORDER NOW BUTTON */}
										<PressableScale
											activeOpacity={0.6}
											onPress={() => {
												router.push(`/vendor/${item.id}`);
											}}
										>
											<View className="px-5 py-2 flex-row gap-1 items-center rounded-2xl bg-primary">
												<Text className="text-white ">
													Order Now
												</Text>
												<Image
													source={require("../../assets/icons/ordernow-black.png")}
													className="w-5 h-5"
													tintColor={"white"}
												/>
											</View>
										</PressableScale>
									</LinearGradient>
								</View>
							</View>
						</TouchableWithoutFeedback>
					)}
					keyExtractor={(item: any, index: number) => item.id ? item.id.toString() : index.toString()}
					horizontal
					showsHorizontalScrollIndicator={false}
					contentContainerStyle={{
						paddingHorizontal: wid * 0.05,
						paddingVertical: 10
					}}
				/>
			</View>
		</View>
	);
};

export default FullHorizontalList;
