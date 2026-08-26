// export const unstable_settings = {
//   animation: "slide_from_right", // Applies slide animation when navigating to this screen
// };

import InputField from "@/components/ui/InputField";
import icons from "@/constants/icons/icons";
import { BRAND } from "@/constants/brandColors";
import images from "@/constants/images/images";
import { UIThemeContext } from "@/context/ThemeContext";
import { isClerkAPIResponseError, useAuth, useSignIn, useSSO } from "@clerk/clerk-expo";
import { ClerkAPIError } from "@clerk/types";
import * as AuthSession from "expo-auth-session";
import { LinearGradient } from "expo-linear-gradient";
import * as Location from "expo-location";
import { Link, useRouter, useFocusEffect, Redirect } from "expo-router";
import * as Linking from "expo-linking";
import React, {
    useCallback,
    useContext,
    useEffect,
    useState,
} from "react";
import {
    Dimensions,
    Image,
    ImageBackground,
    KeyboardAvoidingView,
    Modal,
    ScrollView,
    StatusBar,
    View,
    ActivityIndicator,
} from "react-native";
import { Text } from '@/components/ui/Text';
import { useWarmUpBrowser } from "../_layout";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";

const { width, height } = Dimensions.get("window");

export default function SignIn() {
	// <-----------------------<HOOKES>------------------------>
	const { signIn, setActive, isLoaded } = useSignIn();
	const { getToken, isSignedIn, signOut } = useAuth()
	const router = useRouter();
	const { startSSOFlow } = useSSO();
	const { currentTheme } = useContext(UIThemeContext);

	const darkTheme = currentTheme === "dark";

	// <-----------------------<STATES>------------------------>
	const [emailAddress, setEmailAddress] = useState("");
	const [password, setPassword] = useState("");
	const [loading, setLoading] = useState(false);
	const [AuthLoading, setAuthLoading] = useState(false);
	const [errors, setErrors] = React.useState<ClerkAPIError[]>();
	const [LocationFinal, setLocation] = useState<Location.LocationObject | null>(null);
	const [ShowLocationPrompt, setShowLocationPrompt] = useState(false);

	useEffect(() => {
		const resetError = () => {
			setErrors(undefined);
		};
		resetError();
	}, []);

	// <----------------------<VARIABLES>---------------------->
	const statusBarHeight = StatusBar.currentHeight || 0;
	useWarmUpBrowser();

	// <----------------------<FUNCTIONS>---------------------->

	// GET CURRENT LOCATION
	async function getCurrentLocation() {
		setShowLocationPrompt(false);
		try {
			let { status } = await Location.requestForegroundPermissionsAsync();
			if (status !== "granted") {
				// setErrorMsg("Permission to access Location was denied");
				setShowLocationPrompt(true);
				return;
			}
			let location = await Location.getCurrentPositionAsync({});
			setLocation(location);
		} catch (error: unknown) {
			setShowLocationPrompt(true)
		} 
	}

	// UPDATE USER LOCATION
	// Omitted for Rider app in sign in since location gets updated via background tracking or rider data hooks.

	// SIGN IN ATTEMPT
	const onSignInPress = async () => {
		setLoading(true);
		setErrors(undefined);
		let success = false
		if (!isLoaded) return;

		try {
			const signInAttempt = await signIn.create({
				identifier: emailAddress,
				password,
			});

			if (signInAttempt.status === "complete") {
				await setActive({ session: signInAttempt.createdSessionId });
				success = true
			} else {
				if (__DEV__) console.warn("Sign-in incomplete, status:", signInAttempt.status);
				setErrors([{ code: "incomplete", message: "incomplete", longMessage: "Additional verification is required to sign in. Please check your email or contact support." } as ClerkAPIError]);
				success = false
			}
		} catch (err) {
			if (isClerkAPIResponseError(err)) setErrors(err.errors);
			success = false
		} finally {
			setLoading(false);
			setAuthLoading(false);
		}
	};

	// OAUTH
	const SignInWithGoogle = useCallback(async () => {
		setAuthLoading(true);
		let success = false;
		try {
			const ssoResult = await startSSOFlow({
				strategy: "oauth_google",
				redirectUrl: Linking.createURL('/(Auth)/sign-in/screen', { scheme: 'drop-rider' }),
			});

			if (__DEV__) console.log("SSO Flow Result:", JSON.stringify(ssoResult, null, 2));

			const { createdSessionId, setActive, signUp, signIn } = ssoResult;

			if (createdSessionId) {
				await setActive!({ session: createdSessionId });
				success = true;
			} else if (signUp?.createdSessionId) {
				await setActive!({ session: signUp.createdSessionId });
				success = true;
			} else {
				if (__DEV__) console.warn("OAuth: No session created. signIn status:", signIn?.status, "signUp status:", signUp?.status);
				success = false;
			}
		} catch (err: unknown) {
			if ((isClerkAPIResponseError(err) && err.errors.some((e) => e.message?.includes("already signed in"))) || (err instanceof Error && err.message.includes("already signed in"))) {
				if (__DEV__) console.log("OAuth: User already signed in. Redirecting...");
				router.replace("/");
				return;
			}
			
			// Handle stale cache "signed out" error from Clerk
			if ((isClerkAPIResponseError(err) && err.errors.some((e) => e.code === "signed_out" || e.message === "Signed out")) || (err instanceof Error && err.message.includes("You are signed out"))) {
				if (__DEV__) console.log("OAuth: Stale session detected. Clearing Clerk cache...");
				await signOut();
				success = false;
				return;
			}

			if (__DEV__) console.error("OAuth sign-in error:", err);
			success = false;
		} finally {
			setAuthLoading(false);
		}
	}, [startSSOFlow, router, signOut]);

	if (isLoaded && isSignedIn) {
		return <Redirect href="/" />;
	}

	return (
		<>
			<StatusBar
				backgroundColor={'transparent'}
				barStyle={darkTheme ? "light-content" : "dark-content"}
			/>

			<View
				className={darkTheme ? "bg-black" : "bg-[#f0f0f0]"}
				style={{
					flex: 1,
				}}
			>
				<KeyboardAvoidingView
					behavior="padding"
					style={{
						flex: 1,
					}}
				>
					<ScrollView
						className="flex-1 w-full "
						overScrollMode="never"
						showsVerticalScrollIndicator={false}
						contentContainerStyle={{
							paddingBottom: 120,
							flexGrow: 1,
						}}
					>
						<ImageBackground
							source={images.authBgLight}
							style={{
								height: height * 0.35,
								marginBottom: -(height * 0.09),
							}}
						>
							<LinearGradient
								className="w-full h-full "
									colors={[
									darkTheme
										? "rgba(0, 0, 0, 0.2)"
										: "transparent",
									darkTheme
										? "rgba(0, 0, 0, 0.6)"
										: "rgba(240, 240, 240, 0.8)",
									darkTheme
										? "rgba(0, 0, 0, 1)"
										: "#f0f0f0",
								]}
							></LinearGradient>
						</ImageBackground>
						<View className="w-full gap-3 px-6">
							<View className=" w-[90%] self-center">
								<Text className={
										darkTheme
											? "text-[26px] text-white"
											: "text-[26px] text-black"
									}>{"Sign In to Your Account"}</Text>
							</View>
							<View className="py-[50px] gap-[20px] items-center">
								<InputField
									label={"Email"}
									type={""}
									placeholder={"Enter Your Email"}
									iconleft="mail"
									set={(text: string) => {
										setEmailAddress(text);
									}}
								/>
								<InputField
									label={"Password"}
									type={"password"}
									placeholder={"Enter Your Password"}
									iconleft="key"
									set={(text: string) => {
										setPassword(text);
									}}
								/>
								{errors && (
									<View className="w-[90%]">
										{errors.map((el, index) => (
											<View
												key={index}
												className="flex-row gap-2 items-center "
											>
												<Ionicons name="information-circle" size={20} color={"red"} />
												<Text className="text-red-500">
													{el.longMessage}
												</Text>
											</View>
										))}
									</View>
								)}
								<View className="flex-row items-center justify-end w-[90%] max-w-[320px]">
									<Link
										href={"/(Auth)/forgot-password/screen"}
										className="group"
									>
										<Text className="text-accenttxt group-active:text-gray-400">
											Forgot Password?
										</Text>
									</Link>
								</View>
								<PressableScale
									className="w-full items-center"
									activeOpacity={0.7}
									disabled={loading}
									onPress={() => {
										onSignInPress();
									}}
								>
									<View
										className={`w-[90%] max-w-[320px] h-[45px] flex-row items-center justify-center gap-2  ${
											loading
												? "bg-accentbg/60"
												: "bg-accentbg"
										} rounded-full`}
									>
										{loading ? (
											<View
												className={""}
											>
												<Ionicons name="sync" size={32} color={BRAND.white} />
											</View>
										) : (
											<Text className={`text-white text-lg font-sans-semibold`}>
												Log In
											</Text>
										)}
									</View>
								</PressableScale>
								<View className="flex flex-row items-center gap-4 my-0">
									<View
										className={
											"border-b border-gray-400 w-[20%]"
										}
									></View>
									<Text className="text-gray-400">Or </Text>
									<View
										className={
											"border-b border-gray-400 w-[20%]"
										}
									></View>
								</View>
								<PressableScale
									activeOpacity={0.7}
									onPress={() => {
										SignInWithGoogle();
									}}
								>
									<View
										className={`flex-row gap-4 w-[260px] h-[40px] rounded-[30px]  ${
											darkTheme ? "bg-slate-50/15" : "bg-white border border-gray-200"
										} shadow-2xl items-center justify-center`}
										style={{
											width: width * 0.6,
										}}
									>
										<Image
											source={images.google_logo}
											className="w-[30px] h-[30px] rounded-full"
										/>
										<Text className={
												darkTheme
													? "text-base text-gray-300"
													: "text-base text-gray-700"
											}>{"Sign in with Google"}</Text>
									</View>
								</PressableScale>
							</View>
						</View>
						<View className="flex-row gap-2 items-center justify-center">
							<Text className={darkTheme ? "text-white" : "text-gray-700"}>{"Don't Have an Account?"}</Text>
							<PressableScale
								onPress={() => {
									router.push("/(Auth)/sign-up/screen");
								}}
							>
								<View className="px-2 h-7 items-center justify-center">
									<Text className={
											"text-accenttxt group-active:text-gray-400"
										}>{"Sign Up"}</Text>
								</View>
							</PressableScale>
						</View>
					</ScrollView>
				</KeyboardAvoidingView>

				<Modal visible={AuthLoading} transparent={true} animationType="fade">
					<View className="flex-1 items-center justify-center bg-black/50">
						<View className="bg-white p-6 rounded-2xl items-center shadow-xl">
							<ActivityIndicator size="large" color={BRAND.primary} />
							<Text className="mt-4 font-sans-semibold text-gray-700">Loading...</Text>
						</View>
					</View>
				</Modal>

				{/* <Modal isVisible={ShowLocationPrompt}>
						<View className="items-center">
							<View
								className={`bg-white w-[80%]  gap-6 max-w-[300px] rounded-3xl p-6`}
							>
								<View className={`flex-row gap-3 `}>
									<Ionicons name="locate" size={24} color={BRAND.primary} />
									<Text className="font-heading-semibold text-2xl text-blue-500">
										Location Access
									</Text>
								</View>
								<View className="">
									<View className="">
										<Text>
											This app requires access to your
											current location for it to work
											properly.{" "}
										</Text>
										<Text>
											Please grant permission to access
											your location in order to proceed
										</Text>
										<Text>
											If you have allowed location
											permission and are still getting
											this prompt it might be a Network
											issue so Please check your Network
											settings{" "}
										</Text>
									</View>
								</View>
								<PressableScale
									activeOpacity={0.8}
									onPress={() => {
										getCurrentLocation();
									}}
								>
									<View
										className={`bg-blue-500 p-3 px-6 rounded-xl items-center `}
									>
										<Text
											className={`text-white font-sans-bold`}
										>
											Allow Location Access
										</Text>
									</View>
								</PressableScale>
							</View>
						</View>
				</Modal> */}
			</View>
		</>
	);
}
