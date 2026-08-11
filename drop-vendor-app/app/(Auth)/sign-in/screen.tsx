// export const unstable_settings = {
//   animation: "slide_from_right", // Applies slide animation when navigating to this screen
// };

import InputField from "@/components/ui/InputField";
import icons from "@/constants/icons/icons";
import { BRAND } from "@/constants/brandColors";
import images from "@/constants/images/images";
import { UIThemeContext } from "@/context/ThemeContext";

// @ts-ignore
import { isClerkAPIResponseError, useAuth, useSignIn, useSSO } from "@clerk/clerk-expo";
import { ClerkAPIError } from "@clerk/types";
import * as AuthSession from "expo-auth-session";
import { LinearGradient } from "expo-linear-gradient";

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
				// If the status isn't complete, check why. User might need to
				// complete further steps.
				// if (__DEV__) console.error(JSON.stringify(signInAttempt, null, 2));
				success = false
			}
		} catch (err: any) {
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
		let success = false
		try {
			// Start the authentication process by calling `startSSOFlow()`
			const { createdSessionId, setActive, signIn, signUp } =
				await startSSOFlow({
					strategy: "oauth_google",
					// For web, defaults to current path
					// For native, you must pass a scheme
					redirectUrl: Linking.createURL('/(Auth)/sign-in/screen', { scheme: 'drop-vendor' }),
				});

			// If sign in was successful, set the active session
			if (createdSessionId) {
				await setActive!({ session: createdSessionId });
				success = true;
			} else if (signUp?.createdSessionId) {
				await setActive!({ session: signUp.createdSessionId });
				success = true;
			} else {
				// No session created — user may need MFA or additional steps
				if (__DEV__) console.warn("OAuth: No session created, MFA or additional steps may be required.");
				success = false;
			}
		} catch (err: any) {
			if (err?.errors?.[0]?.message?.includes("already signed in") || (err as Error)?.message?.includes("already signed in")) {
				if (__DEV__) console.log("OAuth: User already signed in. Redirecting...");
				router.replace("/");
				return;
			}
			
			// Handle stale cache "signed out" error from Clerk
			if (err?.errors?.[0]?.code === "signed_out" || err?.errors?.[0]?.message === "Signed out" || (err as Error)?.message?.includes("You are signed out")) {
				if (__DEV__) console.log("OAuth: Stale session detected. Clearing Clerk cache...");
				await signOut();
				success = false;
				return;
			}

			if (__DEV__) console.error("OAuth sign-in error:", err);
			success = false
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
				className={darkTheme ? "bg-black" : ""}
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
										: "rgba(240, 240, 240, 0.7)",
									darkTheme
										? "rgba(0, 0, 0, 1)"
										: "rgb(240, 240, 240)",
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
												<Ionicons name="sync" size={32} color={"white"} />
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
											darkTheme ? "bg-slate-50/15" : "bg-white"
										} shadow-2xl bg-slate-50/15 items-center justify-center`}
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
													: "text-base"
											}>{"Sign in with Google"}</Text>
									</View>
								</PressableScale>
							</View>
						</View>
						<View className="flex-row gap-2 items-center justify-center">
							<Text className={darkTheme?"text-white":""}>{"Don't Have an Account?"}</Text>
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

				<Modal visible={AuthLoading} backdropColor={"transparent"}>
					<View className="flex-1 items-center justify-center">
						<View className={""}>
							<Ionicons name="sync" size={24} color={BRAND.primary} />
						</View>
					</View>
				</Modal>

			</View>
		</>
	);
}
