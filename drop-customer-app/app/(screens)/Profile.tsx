import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import Button from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import icons from "@/constants/icons/icons";
import { ROUTES } from "@/API/routes/ApiRoutes";
import { errorMessage } from "@/API/errors";
import Context from "@/context/context";
import { UIThemeContext } from "@/context/ThemeContext";
import SecureUpload from "@/Helpers/imageUpload";
import { useFavorites } from "@/hooks/queries/useFavorites";
import { useUpdateProfilePic, useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { useAuth, useClerk, useUser } from "@clerk/clerk-expo";
import { useQueryClient } from "@tanstack/react-query";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import BottomSheet, {
    BottomSheetScrollView,
    BottomSheetView,
} from "@gorhom/bottom-sheet";
import * as Haptics from "expo-haptics";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import React, { useContext, useRef, useState } from "react";
import { PressableScale } from "@/components/ui/PressableScale";
import { Toast } from "@/lib/toast";
import { BRAND, TOAST as BRAND_TOAST } from "@/constants/brandColors";
import { Ionicons } from "@expo/vector-icons";
import { DataFallbackUI } from "@/components/ui/DataFallbackUI";
import {
    Dimensions,
    Modal,
    ScrollView,
    StatusBar,
    TouchableWithoutFeedback,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { formatMoney, formatMoneyShort, isZeroMoney } from "@/utils/money";

const { width, height } = Dimensions.get("window");

const Profile = () => {
	// <------------------------------HOOKES------------------------------>
	const router = useRouter();
	const queryClient = useQueryClient();
	const { signOut } = useClerk();
	const { clearPushToken } = usePushNotifications();
	const { user: clerkUser } = useUser();
	const { setTheme } = useContext(UIThemeContext);
	const { data: User, refetch: fetchUserDetails, isLoading: isUserLoading } = useUserDetails();
	const updateUser = useUpdateUser();
	const { getToken } = useAuth()
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";
    const { data: favorites = [] } = useFavorites();

	// <------------------------------STATES------------------------------>
	const [bottomSheetData, setBottomSheetData] = useState(""); //[ favourites , privacy , settings, help ]
	const [displayTopBar, setDisplayTopBar] = useState(true); //[ favourites , privacy , settings, help ]
	const [image, setImage] = useState<string | undefined>();
	const [ChangeProfileLoading, setChangeProfileLoading] = useState(false)

	// <------------------------------VARIABLES------------------------------>

	// <------------------------------FUNSTIONS------------------------------>
	// BOTTOM SHEET
	const bottomSheetRef = useRef<BottomSheet>(null);
	const handleClosePress = () => {
		bottomSheetRef.current?.close();
		setDisplayTopBar(true);
	};
	const handleExpandPress = () => {
		setDisplayTopBar(false);
		bottomSheetRef.current?.expand();
	};

	// LOGOUT
	const handleSignOut = async () => {
		try {
			// Detach the push token first — the endpoint is authenticated, so it
			// cannot be done once the session is gone. Skipping it leaves this
			// device receiving the previous account's order notifications.
			await clearPushToken();
			await signOut();
			// F-04 SECURE CACHE WIPE: Clear Query Cache & stored items to prevent session fixation
			queryClient.clear();
			
			// Redirect to your desired page
			Linking.openURL(Linking.createURL("/(Auth)/sign-in/screen"));
		} catch (err) {
			// error handling
		}
	};

	const { mutateAsync: mutateProfilePic } = useUpdateProfilePic();

	const ChangeProfileImage = async (profile_pic : string) => {
		setChangeProfileLoading(true)
		try {
			await mutateProfilePic(profile_pic);
			fetchUserDetails().then(() => {
				setChangeProfileLoading(false)
			})
		} catch (error: unknown) {
			if (__DEV__) console.error("Profile pic update failed:", (error as Error)?.message);
			setChangeProfileLoading(false)
		}
	}

	// picking file from device storage
	const pickFile = async () => {
		let result = await ImagePicker.launchImageLibraryAsync({
			// Images only. This is an avatar, and the endpoint content-sniffs and
			// refuses anything that is not one — offering the customer their video
			// library is offering them a choice that ends in an error.
			mediaTypes: ["images"],
			allowsEditing: true,
			quality: 1,
		});
		if (result.canceled) {
			return;
		}
		try {
			const uploadedImageData = await SecureUpload(
				result?.assets[0].uri,
				result?.assets[0].fileName,
				getToken
			);
			ChangeProfileImage(uploadedImageData.secure_url);
			setImage(uploadedImageData.secure_url);
		} catch {
			// `SecureUpload` has already shown the backend's own reason. Swallowing
			// it here only stops the unhandled rejection — it must not fall through
			// and set the avatar to an upload that did not happen.
		}
	};

	if (!User && !isUserLoading) {
		return (
			<DataFallbackUI 
				title="Profile Unavailable"
				message="We couldn't load your profile data. Please retry or go home."
				onRetry={() => fetchUserDetails()}
			/>
		);
	}

	return (
		<>
			<StatusBar
				backgroundColor={"transparent"}
				barStyle={darkTheme ? "light-content" : "dark-content"}
			/>
			<View
				style={{
					flex: 1,
					backgroundColor: darkTheme ? "black" : "white",
				}}
			>
				<View
					className="flex-1 "
					style={{
						marginTop: StatusBar.currentHeight,
					}}
				>
					{/* <-------------TOP_BAR-------------> */}
					{displayTopBar && (
						<View style={{ overflow: "hidden", paddingBottom: 4, zIndex: 20 }}>
							<View 
								className="flex-row items-center justify-between px-4 py-3 pb-4 mb-2"
								style={{ 
									backgroundColor: darkTheme ? "#000" : "#fff",
									borderBottomWidth: 1, 
									borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
									...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
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
								<Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
									Profile
								</Text>
								{/* THEME TOGGLE BUTTON */}
								<PressableScale accessibilityLabel={darkTheme ? "Switch to the light theme" : "Switch to the dark theme"}
									activeOpacity={0.7}
									onPress={() => {
										Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
										setTheme();
									}}
								>
									<View className="w-10 h-10 items-center justify-center">
										{!darkTheme ? (
											<Ionicons name="moon" size={24} color={BRAND.primary} />
										) : (
											<Ionicons name="sunny" size={24} color={BRAND.primary} />
										)}
									</View>
								</PressableScale>
							</View>
						</View>
					)}

					<ScrollView
						className=" rounded-xl flex-1"
						contentContainerStyle={{
							alignItems: "center",
							gap: 20,
							paddingTop: 10, paddingBottom: 120}}
						showsVerticalScrollIndicator={false}
						overScrollMode="never"
					>
						{/* <-------PROFILE DETAILS: [ PROFILE_PIC , USERNAME , EMAIL , EDIT_PROFILE_BUTTON ]-------> */}
						<View className="w-full items-center pt-3 pb-5 gap-2">
							{/* Cashback Banner */}
							{!isZeroMoney(User?.wallet_balance) && (
								<View className={`flex-row items-center px-4 py-2 rounded-full mb-2 border ${darkTheme ? "bg-green-500/20 border-green-500/30" : "bg-green-50 border-green-200"}`}>
									<Text style={{ fontSize: 18, marginRight: 6 }}>💸</Text>
									<Text className="font-sans-bold text-sm" style={{ color: BRAND_TOAST.success }}>
										Drop Cashback: {formatMoneyShort(User?.wallet_balance, 'KSh')}
									</Text>
								</View>
							)}

							{/* PROFILE_PIC */}
							<View className="h-[150px] w-[150px]">
								<Image
									source={{uri :  User?.profile_pic || image}}
									className={`w-full h-full rounded-full `}
								/>
							</View>
							{/* USERNAME , EMAIL */}
							<View className="w-full items-center py-2 ">
								<Text className={
										darkTheme
											? "text-xl text-white"
											: "text-xl"
									}>{User?.full_name || clerkUser?.fullName || "User"}</Text>
								<Text className={
										darkTheme
											? "text-gray-200"
											: "text-gray-400"
									}>{User?.email || clerkUser?.emailAddresses?.[0]?.emailAddress || ""}</Text>
							</View>
							{/* EDIT_PROFILE_BUTTON */}
							<PressableScale
								activeOpacity={0.7}
								onPress={() => {
									Haptics.selectionAsync();
									setBottomSheetData("edit-profile");
									handleExpandPress();
								}}
							>
								<Button
									style={" px-5 py-2 rounded-xl"}
									textStyle={
										darkTheme ? "text-black" : "text-white"
									}
									label={"Edit profile"}
								/>
							</PressableScale>
						</View>
						{/* <-------MENU BUTTONS: [FAVOURITES , PRIVACY , SETTINGS ,HELP & SUPPORT , LOGOUT ]-------> */}
						{/* FAVOURITES */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.selectionAsync();
								setBottomSheetData("favourites");
								handleExpandPress();
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="heart" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Favourites"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* NOTIFICATIONS */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.selectionAsync();
								// Fixed Bug: Navigate instead of opening bottomsheet
								router.push("/(screens)/Notifications");
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="notifications" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Notifications"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* PRIVACY */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.selectionAsync();
								setBottomSheetData("privacy");
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="lock-closed" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Privacy"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* SETTINGS */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.selectionAsync();
								setBottomSheetData("settings");
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="settings" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Settings"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* PAYMENT HISTORY */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								router.push('/(screens)/PaymentHistory');
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Text style={{ fontSize: 20 }}>💳</Text>
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Payment History"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* MY BOTTLES */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								router.push('/(screens)/BottleWallet');
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Text style={{ fontSize: 20 }}>🚰</Text>
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"My Bottles"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* HELP & SUPPORT */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.selectionAsync();
								setBottomSheetData("help");
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="help-circle" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: " text-lg"
										}>{"Help & Support"}</Text>
								</View>
								<View className="w-9 h-9 items-center justify-center ">
									<Ionicons name="chevron-forward" size={24} color={BRAND.primary} />
								</View>
							</View>
						</PressableScale>
						{/* LOGOUT */}
						<PressableScale
							activeOpacity={0.7}
							onPress={() => {
								Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
								handleSignOut();
							}}
						>
							<View
								className={`${
									darkTheme ? "bg-gray-200/15" : "bg-white"
								} py-3 px-5 w-[90%] rounded-full flex-row items-center gap-3`}
							>
								<View className="w-9 h-9 items-center justify-center">
									<Ionicons name="log-out" size={24} color={BRAND.primary} />
								</View>
								<View className="flex-1">
									<Text className={
											darkTheme
												? "text-lg text-white"
												: "text-lg"
										}>{"Logout"}</Text>
								</View>
							</View>
						</PressableScale>
					</ScrollView>
				</View>
				<BottomSheet
					ref={bottomSheetRef}
					index={-1}
					snapPoints={["100%"]}
					enableDynamicSizing={false}
					enableOverDrag={false}
					handleStyle={{
						display: "none",
					}}
				>
					<BottomSheetView
						style={{
							flexGrow: 1,
							zIndex: 30,
						}}
					>
						{/* <ImageBackground
								source={images.bg1light}
								style={{
									flex: 1,
								}}
							> */}
						<View
							className={`flex-1 w-full ${
								darkTheme ? "bg-black" : "bg-white"
							}`}
							style={{
								paddingTop: StatusBar.currentHeight,
							}}
						>
							{/* TOP_BAR */}
							<View className=" bg-blac py-6 flex-row justify-between items-center gap-[30px] px-5 ">
								{/* CLOSE BOTTOMSHEET */}
								<PressableScale accessibilityLabel="Close"
									activeOpacity={0.7}
									onPress={() => {
										Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
										handleClosePress();
									}}
								>
									<View className="w-[42px] h-[40px] items-center justify-center rounded-2xl">
										<Ionicons name="chevron-down" size={24} color={BRAND.primary} />
									</View>
								</PressableScale>

								{/* SAVE BUTTON */}
								<PressableScale
									activeOpacity={0.6}
									onPress={async () => {
										// HIGH-11: Actually save profile data to backend
										try {
											await updateUser.mutateAsync({
												full_name: User?.full_name || clerkUser?.fullName || undefined,
												phone_number: User?.phone_number,
											});
											Toast.success("Saved", "Profile information saved successfully.");
											handleClosePress();
										} catch (e) {
											Toast.error("Save Failed", errorMessage(e, "Could not update profile."));
										}
									}}
								>
									<View className=" px-6 py-2 bg-primary rounded-2xl shadow-2xl shadow-black">
										<Text className="text-lg text-white font-sans-bold">{"Save"}</Text>
									</View>
								</PressableScale>
							</View>
							{bottomSheetData === "edit-profile" && (
								<View className="w-full flex-1 items-center pt-3 pb-5 gap-2">
									{/* PROFILE_PIC */}
									<View className="h-[170px] w-[170px] ">
										<Image
											source={{uri: User?.profile_pic || image }} 
											className="w-full h-full z-0 rounded-full"
										/>
										{/* <------EDIT BUTTON------> */}
										<PressableScale accessibilityLabel="Change your profile photo"
											className="absolute bottom-0 right-0 "
											activeOpacity={0.7}
											onPress={pickFile}
										>
											<View className="bg-accenttxt p-3 rounded-full">
												<Ionicons name="pencil" size={24} color={BRAND.primary} />
											</View>
										</PressableScale>
									</View>
									<View
										className={`w-full flex-1 mt-5 ${
											darkTheme
												? "bg-gray-200/20"
												: "bg-white"
										} `}
									>
										<BottomSheetScrollView
											contentContainerStyle={{
												flexGrow: 1,
												width: width,
												paddingHorizontal: 20,
												paddingVertical: 50, paddingBottom: 120}}
											showsVerticalScrollIndicator={false}
											scrollEnabled={true}
										>
											<TouchableWithoutFeedback>
												<View>
													<Text className={
															darkTheme
																? "text-xl text-white"
																: "text-xl"
														}>{
															"Personal Infomation:"
														}</Text>
													{/* Name */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold text-xl ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Name
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{
																		User?.full_name || clerkUser?.fullName || "Your Name"
																	}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>

													{/* Email */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Email
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{User?.email || clerkUser?.emailAddresses?.[0]?.emailAddress || "No email"}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>

													{/* Phone No */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Phone No
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{User?.phone_number || "No phone"}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>

													{/* Address */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Default
																	Delivery
																	Address
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{`${"Ngong Memusi Navara Bungalows"}`}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>

													{/* Password */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Password
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{`${"Change Password"}`}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>

													{/* Payment Method */}
													<PressableScale
														activeOpacity={0.6}
													>
														<View
															className={`flex-row items-center justify-between border-b ${
																darkTheme
																	? "border-gray-300/20"
																	: "border-gray-200"
															} py-6`}
														>
															<View className="gap-2">
																<Text
																	className={`font-sans-semibold ${
																		darkTheme
																			? "text-gray-200"
																			: "text-gray-700"
																	}`}
																>
																	Payment
																	Method
																</Text>
																<Text className={
																		" text-gray-500"
																	}>{`${"Add payment method"}`}</Text>
															</View>
															<View>
																<Ionicons name="chevron-forward" size={28} color={BRAND.primary} />
															</View>
														</View>
													</PressableScale>
												</View>
											</TouchableWithoutFeedback>
										</BottomSheetScrollView>
									</View>
								</View>
							)}

							{bottomSheetData === "favourites" && (
								<View className="flex-1 w-full pt-3 pb-5 px-5">
									<Text className={`text-2xl font-heading-semibold mb-4 ${darkTheme ? "text-white" : "text-black"}`}>
										Saved Items
									</Text>
									<ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 120 }}>
										{favorites.length === 0 ? (
											<EmptyState mood="sad" title="No Saved Items" subtitle="You haven't saved any items yet." />
										) : (
											favorites.map((fav: any) => {
												const product = fav.product;
												if (!product) return null;
												return (
													<PressableScale
														key={fav.id || product.id}
														activeOpacity={0.7}
														onPress={() => {
															handleClosePress();
															router.push(`/(screens)/product-details/${product.id}`);
														}}
													>
														<View className={`flex-row items-center gap-4 p-4 mb-3 rounded-2xl ${darkTheme ? "bg-white/5" : "bg-white"}`}>
															{product.image_url ? (
																<Image source={{ uri: product.image_url }} className="w-14 h-14 rounded-xl" />
															) : (
																<View className="w-14 h-14 rounded-xl bg-sky-500 items-center justify-center">
																	<Text className="text-white text-xl">📦</Text>
																</View>
															)}
															<View className="flex-1">
																<Text className={`font-sans-bold text-lg ${darkTheme ? "text-white" : "text-black"}`}>{product.name}</Text>
																<Text className={`text-sm ${darkTheme ? "text-gray-400" : "text-gray-500"}`} numberOfLines={1}>
																	Tap to view details
																</Text>
															</View>
															<View className="items-end">
																<Text className="font-sans-bold text-green-500">{formatMoney(product.price)}</Text>
															</View>
														</View>
													</PressableScale>
												);
											})
										)}
									</ScrollView>
								</View>
							)}
						</View>
						{/* </ImageBackground> */}
					</BottomSheetView>
				</BottomSheet>
			</View>
			{/* loading modals */}
			<Modal visible={ChangeProfileLoading} backdropColor={"transparent"}>
				<View className={`items-center justify-end w-full h-full`}>
					<View
						className={`w-full h-[100px] ${darkTheme?"bg-black":"bg-white"} rounded items-center justify-center `}
					>
							<View className={`flex-row items-center gap-3`}>
								<View className={``}>
									<Ionicons name="sync" size={40} color={BRAND.primary} />
								</View>
								<Text className={`${darkTheme?"text-white":"text-black"}`}>Loading</Text>
							</View>
					</View>
				</View>
			</Modal>
		</>
	);
};

export default Profile;
