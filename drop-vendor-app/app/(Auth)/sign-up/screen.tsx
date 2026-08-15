import InputField from "@/components/ui/InputField";
import images from "@/constants/images/images";

// @ts-ignore
import { isClerkAPIResponseError, useSSO, useSignUp, useAuth } from "@clerk/clerk-expo";
import { LinearGradient } from "expo-linear-gradient";
import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import React, { useCallback, useContext, useEffect, useState } from "react";
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
// import Modal from "react-native-modal";
import Button from "@/components/ui/Button";
import icons from "@/constants/icons/icons";
import { Toast } from "@/lib/toast";
import { BRAND } from "@/constants/brandColors";
import { UIThemeContext } from "@/context/ThemeContext";
import { ClerkAPIError } from "@clerk/types";
import * as AuthSession from "expo-auth-session";
import { OtpInput } from "react-native-otp-entry";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";

const { height } = Dimensions.get("window");

export default function SignUp() {
	// <--------------------------<HOOKES>---------------------------->
	const router = useRouter();
	const { isLoaded, signUp, setActive } = useSignUp();
	const { startSSOFlow } = useSSO();
	const { signOut } = useAuth();
	const { currentTheme } = useContext(UIThemeContext);
	const darkTheme = currentTheme === "dark";

	// <--------------------------<STATES>---------------------------->
	const [emailAddress, setEmail] = React.useState("");
	const [fullname, setFullname] = React.useState("");
	const [phoneNumber, setPhoneNumber] = React.useState("");
	const [profilePic, setProfilePic] = React.useState("");
	const [password, setPassword] = React.useState("");
	const [confirmPassword, setConfirmPassword] = React.useState("");
	const [verification, setVerification] = useState("default"); // pending , success
	const [code, setCode] = React.useState("");
	const [errors, setErrors] = React.useState<ClerkAPIError[]>();
	const [loading, setLoading] = useState(false);
	const [OAuthLoading, setOAuthLoading] = useState(false);

	useEffect(() => {
		const resetError = () => {
			setErrors(undefined);
		};
		resetError();
	}, []);

	// <-------------------------<VARIABLES>-------------------------->
	const statusBarHeight = StatusBar.currentHeight || 0;

	// <-------------------------<FUNCTIONS>-------------------------->
	// Confirm if password and confirm password are the same
	const checkPassword = () => {
		if (password === confirmPassword) {
			return true;
		} else {
			return false;
		}
	};

	const onSignUpPress = async () => {
		setLoading(true);
		setErrors(undefined);

		if (!isLoaded) return;
		checkPassword();
		if (!checkPassword()) {
			return;
		}

		// Start sign-up process using email and password provided
		try {
			await signUp.create({
				emailAddress,
				password,
			});
			// <-----------------CREATE USER ON THE DATABASE----------------->

			// Send user an email with verification code
			await signUp.prepareEmailAddressVerification({
				strategy: "email_code",
			});

			// Set 'pendingVerification' to true to display second form
			// and capture OTP code
			setVerification("pending");
		} catch (err: unknown) {
			// See https://clerk.com/docs/custom-flows/error-handling
			// for more info on error handling
			if (isClerkAPIResponseError(err)) setErrors(err.errors);
		} finally {
			setLoading(false);
		}
	};

	const onVerifyPress = async () => {
		let success = false
		if (!isLoaded) return;

		try {
			// Use the code the user provided to attempt verification
			const signUpAttempt = await signUp.attemptEmailAddressVerification({
				code,
			});

			// If verification was completed, set the session to active
			// and redirect the user
			if (signUpAttempt.status === "complete") {
				setVerification("success");
				const clerkId = signUpAttempt?.createdUserId
				if(clerkId === null) {
					return
				}

				await setActive({ session: signUpAttempt.createdSessionId });
				success = true
				// router.replace("/(screens)");
			} else {
				// If the status is not complete, check why. User may need to
				// complete further steps.
				success = false
			}
		} catch (err) {
			// See https://clerk.com/docs/custom-flows/error-handling
			// for more info on error handling
			// if (__DEV__) console.error(JSON.stringify((err as Error).message || (err as Error), null, 2));
			success = false
		}finally{
			if (success){
				setOAuthLoading(true)
			}
		}
	};

	// OAuth
	const SignInWithGoogle = useCallback(async () => {
		let success = false
		setOAuthLoading(true);
		try {
			// Start the authentication process by calling `startSSOFlow()`
			const { createdSessionId, setActive, signIn, signUp } =
				await startSSOFlow({
					strategy: "oauth_google",
					// For web, defaults to current path
					// For native, you must pass a scheme
					redirectUrl: Linking.createURL('/(Auth)/sign-up/screen', { scheme: 'drop-vendor' }),
				});

			// If sign in was successful, set the active session
			if (createdSessionId) {
				await setActive!({ session: createdSessionId })
				success = true
			} else {
				if (__DEV__) console.warn("OAuth: No session created, MFA or additional steps may be required.");
				success = false
			}
		} catch (err: unknown) {
			// Handle stale cache "signed out" error from Clerk
			if ((isClerkAPIResponseError(err) && err.errors.some((e) => e.code === "signed_out" || e.message === "Signed out")) || (err instanceof Error && err.message.includes("You are signed out"))) {
				if (__DEV__) console.log("OAuth: Stale session detected. Clearing Clerk cache...");
				await signOut();
				success = false;
				return;
			}
			
			if (__DEV__) console.error("OAuth sign-up error:", err);
			success = false
		} finally {
			if(success === false){
				setOAuthLoading(false);
			}
		}
	}, [startSSOFlow, signOut]);

	return (
		<>
			<StatusBar
				backgroundColor={'transparent'}
				barStyle={darkTheme?"light-content":"dark-content"}
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
						className="flex-1 w-full"
						overScrollMode="never"
						showsVerticalScrollIndicator={false}
						contentContainerStyle={{
							paddingBottom: 120,
						}}
					>
						<ImageBackground
							source={images.authBgLight}
							style={{
								height: height * 0.32,
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
								<Text className={darkTheme?"text-[30px] text-white":"text-[30px] text-black"}>{"Create An Account "}</Text>
							</View>
							<View className="py-[50px] gap-[20px] items-center">
								<InputField
									label={"Full Name"}
									type={"text"}
									placeholder={"Enter your full name"}
									set={(text: string) => {
										setFullname(text);
									}}
								/>
								<InputField
									label={"Email"}
									type={"email"}
									placeholder={"Enter your Email Address"}
									iconleft="mail"
									set={(text: string) => {
										setEmail(text);
									}}
								/>
								<InputField
									label={"Password"}
									type={"password"}
									placeholder={"Enter your Password"}
									iconleft="key"
									set={(text: string) => {
										setPassword(text);
									}}
								/>
								<InputField
									label={"Confirm Password"}
									type={"password"}
									placeholder={"Confirm your Password"}
									iconleft="key"
									set={(text: string) => {
										setConfirmPassword(text);
									}}
								/>
								{errors && (
									<View className="w-[90%] gap-2">
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
								{/* <View className="flex-row items-center justify-end w-[90%]">
									<Link
										href={"/(Auth)/forgot-password/screen"}
										className="group"
									>
										<Text className="text-accenttxt group-active:text-gray-400">
											Forgot Password?
										</Text>
									</Link>
								</View> */}
								<PressableScale
									className="w-full items-center mt-4"
									activeOpacity={0.7}
									disabled={loading}
									onPress={() => {
										onSignUpPress();
									}}
								>
									<View
										className={`w-[90%] max-w-[320px] h-[45px] flex-row items-center justify-center gap-2 ${
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
											<Text className={`text-white text-xl font-sans-semibold`}>
												Sign Up
											</Text>
										)}
									</View>
								</PressableScale>
								<View className="flex flex-row items-center gap-4 my-0">
									<View
										className={
											"border-b border-gray-400 w-[20%]"
										}
									/>
									<Text className="text-gray-400">Or </Text>
									<View
										className={
											"border-b border-gray-400 w-[20%]"
										}
									/>
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
										
									>
										<Image
											source={images.google_logo}
											className="w-[30px] h-[30px] rounded-full"
										/>
										<Text className={
												darkTheme
													? "text-lg text-gray-300"
													: "text-lg"
											}>{"Sign in with Google"}</Text>
									</View>
								</PressableScale>
							</View>
						</View>
						<View className="flex-row gap-2 items-center justify-center">
							<Text className={darkTheme?"text-white":""}>{"Already Have an Account?"}</Text>
							<PressableScale
								// href={"/(Auth)/sign-in/screen"}
								onPress={() => {
									router.push("/(Auth)/sign-in/screen");
								}}
							>
								<View className="px-2 h-7 items-center justify-center">
									<Text className={
											"text-accenttxt group-active:text-gray-400"
										}>{"Login"}</Text>
								</View>
							</PressableScale>
						</View>
					</ScrollView>
				</KeyboardAvoidingView>

				<Modal backdropColor={"transparent"} visible={OAuthLoading}>
					<View className="flex-1 items-center justify-center">
						<View className={""}>
							<Ionicons name="sync" size={24} color={BRAND.primary} />
						</View>
					</View>
				</Modal>

				<Modal backdropColor={"transparent"} visible={verification === "pending"}>
					<View className={`flex-1 items-center justify-center`}>
						<View className="bg-white p-[15px] rounded-3xl items-center gap-3 ">
							<View className="h-[160px] w-[160px] items-center justify-center bg-accentbg rounded-full shadow-xl ">
								<Ionicons name="mail-unread" size={24} color={"white"} />
							</View>

							<View className="w-full items-center gap-2">
								<Text className="font-heading-semibold text-2xl ">
									Verify Your Email Address
								</Text>
								<Text>{
										"Your Verification Code is sent via your email"
									}</Text>
							</View>

							<View className="w-full items-center flex-row gap-1 justify-center">
								{/* <Text className="font-sans-bold text-2xl ">Verify Your Email Address</Text> */}
								<Text>{"Didn't get the code?"}</Text>
								<PressableScale
									activeOpacity={0.7}
									onPress={async () => {
										try {
											await signUp?.prepareEmailAddressVerification({ strategy: "email_code" });
											Toast.success("Code Resent", "A new verification code has been sent to your email.");
										} catch (e: unknown) {
											Toast.error("Error", (isClerkAPIResponseError(e) ? e.errors[0]?.longMessage : undefined) || "Failed to resend code.");
										}
									}}
								>
									<View className=" h-[30px] px-2 items-center justify-center ">
										<Text className={"text-accentbg"}>{"Resend"}</Text>
									</View>
								</PressableScale>
							</View>

							<View className=" py-3 px-4  flex-row gap-3  rounded-2xl items-center">
								<OtpInput
									numberOfDigits={6}
									focusColor={BRAND.primary}
									autoFocus={false}
									hideStick={true}
									placeholder="******"
									blurOnFilled={true}
									disabled={false}
									type="numeric"
									secureTextEntry={false}
									focusStickBlinkingDuration={500}
									onFocus={() => {}}
									onBlur={() => {}}
									onTextChange={(text: string) => setCode(text)}
									onFilled={() =>
										// onVerifyPress()
										{}
									}
									textInputProps={{
										accessibilityLabel: "One-Time Password",
									}}
									textProps={{
										accessibilityRole: "text",
										accessibilityLabel: "OTP digit",
										allowFontScaling: false,
									}}
								/>
							</View>

							<PressableScale
								activeOpacity={0.7}
								onPress={() => {
									onVerifyPress();
								}}
							>
								<View>
									<Button
										style={"rounded-xl px-[30px]"}
										label={"Verify"}
										textStyle="text-xl"
									/>
								</View>
							</PressableScale>
						</View>
					</View>
				</Modal>

				<Modal backdropColor={"transparent"} visible={verification === "success"}>
					<View className={`flex-1 items-center justify-center`}>
						<View className="bg-white p-[15px] rounded-3xl items-center gap-3 ">
							<View className="h-[160px] w-[160px] items-center justify-center bg-green-500 rounded-full shadow-xl ">
								<Ionicons name="checkmark-circle" size={24} color={"white"} />
							</View>

							<View className="w-full items-center gap-2">
								<Text className="font-heading-semibold text-2xl ">
									Verified
								</Text>
								<Text className="text-gray-500 ">
									Your email address has been verified
									successfully
								</Text>
							</View>
						</View>
					</View>
				</Modal>
			</View>
		</>
	);
}
