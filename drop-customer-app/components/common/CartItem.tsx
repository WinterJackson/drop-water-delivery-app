import { errorMessage } from "@/API/errors";
import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import { useAuth } from "@clerk/clerk-expo";
import * as Haptics from 'expo-haptics';
import { Image } from "expo-image";
import React, { useContext, useState, useEffect, memo } from "react";
import { Text, View } from "react-native";
import { PressableScale } from "@/components/ui/PressableScale";
import { useChangeCartQty, useDeleteCartItem } from "@/hooks/queries/useCart";
import { Toast } from "@/lib/toast";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "../../constants/brandColors";

type Props = {
	data?: any;
	func?: () => void;
};

const CartItem = ({ data, func }: Props) => {
	// <--------------------HOOKS--------------------->
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
	const { getToken } = useAuth();
	
	const { mutateAsync: changeQtyMutation, isPending: QuantityLoading } = useChangeCartQty();
	const { mutateAsync: deleteItemMutation, isPending: DeleteLoading } = useDeleteCartItem();

	// <-------------------STATES--------------------->
	const [changeQuantity, setChangeQuantity] = useState(false);
	const [NewQuantity, setNewQuantity] = useState(data?.quantity);

	useEffect(() => {
		setNewQuantity(data?.quantity);
	}, [data?.quantity]);

	// <-------------------FUNCTIONS--------------------->
	// API CALLS
	// change quantity of cart item
	const ChangeQuantity = async (id: string) => {
		try {
			await changeQtyMutation({
				id: data?.id,
				quantity: NewQuantity
			});
			setChangeQuantity(false);
			if (func) func();
		} catch (error: any) {
			setChangeQuantity(false);
            Toast.error("Update Failed", errorMessage(error, "Could not update quantity."));
		}
	};

	// remove item from cart
	const DeleteItem = async () => {
		try {
			await deleteItemMutation({
				id: data?.id,
			});
			if (func) func();
		} catch (error: any) {
			Toast.error("Delete Failed", errorMessage(error, "Could not delete item."));
		}
	};

	return (
		<View className={`w-full p-3 rounded-[24px] mb-3 flex-row items-center justify-between ${darkTheme ? "bg-[#1B1F24]" : "bg-white border border-gray-100"}`}>
			<View className="flex-row gap-3 items-center flex-1">
				{/* <--------------------<left>--------------------> */}
				<View className={`rounded-[16px] overflow-hidden ${darkTheme ? "bg-white/5" : "bg-white"}`}>
					<Image
						source={data?.product?.image_url}
						style={{ width: 80, height: 80 }}
						contentFit="cover"
					/>
				</View>
				{/* <--------------------<middle>--------------------> */}
				<View className="gap-1.5 flex-1 pr-2">
					<Text
						className={`font-semibold text-base ${
							darkTheme ? "text-white" : "text-black"
						}`}
						numberOfLines={2}
					>
						{data?.product?.name || "Unknown Product"}
					</Text>
					<Text className={`font-bold text-lg ${darkTheme ? "text-accentbg" : "text-primary"}`}>
						KSH {data?.price}
					</Text>

					{/* <--------<QUANTITY SECTION>--------> */}
						<View className="flex-row gap-4 items-center mt-1">
							{/* DECREASE */}
							<PressableScale
								activeOpacity={0.6}
								onPress={() => {
									if(NewQuantity > 1){
										Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
										setNewQuantity(NewQuantity - 1);
										setChangeQuantity(true);
									}
								}}
							>
								<View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-white/10" : "bg-white"}`}>
									<Image
										source={require("../../assets/icons/minus-black.png")}
										style={{ width: 14, height: 14 }}
										tintColor={darkTheme ? "white" : "black"}
									/>
								</View>
							</PressableScale>

							<Text className={`font-semibold text-lg ${darkTheme ? "text-white" : "text-black"}`}>
								{NewQuantity}
							</Text>

							{/* INCREASE */}
							<PressableScale
								activeOpacity={0.6}
								onPress={() => {
									const vendorType = data?.product?.vendor?.vendor_type;
									if (vendorType === "retail_refill" && NewQuantity >= 4) {
										Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
										Toast.error("Limit Reached", "Motorbikes can carry a maximum of 4 (20L) bottles per trip.");
										return;
									}
									Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
									setNewQuantity(NewQuantity + 1);
									setChangeQuantity(true);
								}}
							>
								<View className={`w-8 h-8 rounded-full items-center justify-center ${darkTheme ? "bg-white/10" : "bg-white"}`}>
									<Image
										source={require("../../assets/icons/add-black.png")}
										style={{ width: 14, height: 14 }}
										tintColor={darkTheme ? "white" : "black"}
									/>
								</View>
							</PressableScale>

							{/* COMMIT BUTTON */}
							{changeQuantity && (
								<PressableScale
									onPress={() => {
										Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
										ChangeQuantity(data?.id);
									}}
								>
									<View className={`py-1.5 px-3 rounded-full ${darkTheme ? "bg-accentbg" : "bg-primary"}`}>
										<Text className={`font-semibold text-xs text-white`}>
											{QuantityLoading ? "Saving" : "Update"}
										</Text>
									</View>
								</PressableScale>
							)}
						</View>
					</View>
				</View>

				{/* <--------------------<right>--------------------> */}
				<View className="gap-4 items-end justify-between py-1">
					{/* subtotal */}
					<Text className={`font-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>
						KSH {Math.round((data?.price * data?.quantity) * 100) / 100}
					</Text>
					{/* <--------<REMOVE BUTTON>--------> */}
					<PressableScale
						activeOpacity={0.6}
						onPress={() => {
							Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
							DeleteItem();
						}}
					>
						<View className={`w-10 h-10 rounded-full items-center justify-center ${darkTheme ? "bg-white/5" : "bg-white"}`}>
							{DeleteLoading ? (
								<Ionicons name="sync" size={24} color={BRAND.primary} />
							) : (
								<Image
									source={require("../../assets/icons/delete-black.png")}
									style={{ width: 20, height: 20 }}
									tintColor={darkTheme ? "#ef4444" : "#dc2626"}
								/>
							)}
						</View>
					</PressableScale>
				</View>
			</View>
	);
};

export default memo(CartItem, (prevProps, nextProps) => {
	// Only re-render if these specific properties change to avoid React Query reference changes causing re-renders
	return (
		prevProps.data?.id === nextProps.data?.id &&
		prevProps.data?.quantity === nextProps.data?.quantity &&
		prevProps.data?.price === nextProps.data?.price &&
		prevProps.data?.product?.name === nextProps.data?.product?.name
	);
});
