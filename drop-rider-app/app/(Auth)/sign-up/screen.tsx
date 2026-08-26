import { UIThemeContext } from "@/context/ThemeContext";
import { isClerkAPIResponseError, useAuth, useSignUp } from "@clerk/clerk-expo";
import { apiFetch } from "@/API/apiFetch";
import { errorMessage } from "@/API/errors";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import * as Location from "expo-location";
import { useRouter } from "expo-router";
import React, { useContext, useState } from "react";
import {
    Dimensions,
    ScrollView,
    StatusBar,
    View,
    KeyboardAvoidingView,
    Platform,
    Image,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { LinearGradient } from "expo-linear-gradient";
import images from "@/constants/images/images";
import { ImageBackground } from "react-native";
import VehicleDropdown from "@/components/ui/VehicleDropdown";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";

const { width } = Dimensions.get("window");

export default function SignUp() {
    const { isLoaded, signUp, setActive } = useSignUp();
    const { getToken } = useAuth();
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";

    const [step, setStep] = useState(1);
    const [loading, setLoading] = useState(false);
    const [errors, setErrors] = useState("");

    // Form Data
    const [emailAddress, setEmailAddress] = useState("");
    const [password, setPassword] = useState("");
    const [fullName, setFullName] = useState("");
    const [code, setCode] = useState("");
    const [phoneNumber, setPhoneNumber] = useState("");
    const [vehicleType, setVehicleType] = useState("motorbike");
    const [idNumber, setIdNumber] = useState("");
    const [showPassword, setShowPassword] = useState(false);

    // Clerk IDs — captured at verification time so they survive into step 3
    const [clerkUserId, setClerkUserId] = useState<string | null>(null);
    const [clerkSessionId, setClerkSessionId] = useState<string | null>(null);

    const onSignUpPress = async () => {
        setLoading(true);
        setErrors("");
        if (!isLoaded) return;

        try {
            await signUp.create({
                emailAddress,
                password,
            });

            await signUp.prepareEmailAddressVerification({
                strategy: "email_code",
            });

            setStep(2);
        } catch (err: unknown) {
            if (isClerkAPIResponseError(err)) {
                setErrors(err.errors.map((e) => e.longMessage).join(", "));
            } else {
                setErrors("An unexpected error occurred.");
            }
        } finally {
            setLoading(false);
        }
    };

    const onVerifyPress = async () => {
        setLoading(true);
        setErrors("");
        if (!isLoaded) return;

        try {
            const signUpAttempt = await signUp.attemptEmailAddressVerification({
                code,
            });

            if (signUpAttempt.status === "complete") {
                // Capture IDs immediately — the signUp resource may clear them later
                setClerkUserId(signUpAttempt.createdUserId ?? signUp.createdUserId ?? null);
                setClerkSessionId(signUpAttempt.createdSessionId ?? signUp.createdSessionId ?? null);
                setStep(3);
            } else {
                setErrors("Verification incomplete.");
            }
        } catch (err: unknown) {
            if (isClerkAPIResponseError(err)) {
                setErrors(err.errors.map((e) => e.longMessage).join(", "));
            } else {
                setErrors("An unexpected error occurred.");
            }
        } finally {
            setLoading(false);
        }
    };

    const completeRiderRegistration = async () => {
        setLoading(true);
        setErrors("");
        
        try {
            // Use locally-saved IDs first, fall back to signUp resource
            const userId = clerkUserId || signUp?.createdUserId;
            const sessionId = clerkSessionId || signUp?.createdSessionId;

            if (!userId) {
                setErrors("Authentication failed. Missing user ID. Please try signing up again.");
                setLoading(false);
                return;
            }
            if (!idNumber || idNumber.trim() === "") {
                setErrors("National ID / Passport is required.");
                setLoading(false);
                return;
            }

            if (sessionId && setActive) {
                await setActive({ session: sessionId });
            }

            const payload = {
                clerk_id: userId,
                email: emailAddress,
                name: fullName,
                phone_number: phoneNumber || null,
                vehicle_type: vehicleType,
                ID_number: idNumber,
            };

            // This call was sent with no Authorization header. `create_rider`
            // takes the caller's identity from the verified token — it overwrites
            // the posted `clerk_id` with `user["sub"]` precisely so nobody can
            // claim someone else's account — so an unauthenticated POST was
            // rejected 401 and every sign-up ended on "Failed to save rider
            // details". `setActive` above has just established the session, so a
            // token is available here.
            const token = await getToken();
            await apiFetch(RiderApiRoutes.Register.path, {
                method: "POST",
                token,
                body: payload,
            });

            router.replace("/(screens)");
        } catch (error) {
            // `errorMessage` already flattens a Pydantic 422 array into a
            // sentence, so the hand-rolled `detail` unwrapping is gone.
            if (__DEV__) console.error("CREATE RIDER ERROR:", error);
            setErrors(errorMessage(error, "Failed to save rider details."));
            setLoading(false);
        }
    };

    return (
        <View className={darkTheme ? "bg-black" : "bg-[#f0f0f0]"} style={{ flex: 1, height: Dimensions.get('window').height }}>
            <ImageBackground source={images.authBgLight} style={{ position: 'absolute', width: '100%', height: Dimensions.get('window').height * 0.35 }}>
                <LinearGradient
                    className="w-full h-full"
                    colors={[
                        darkTheme ? "rgba(0, 0, 0, 0.2)" : "transparent",
                        darkTheme ? "rgba(0, 0, 0, 0.6)" : "rgba(240, 240, 240, 0.8)",
                        darkTheme ? "rgba(0, 0, 0, 1)" : "#f0f0f0",
                    ]}
                />
            </ImageBackground>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{flex: 1}}>
        <SafeAreaView className={`flex-1`}>
            <StatusBar backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} />
            
            <ScrollView contentContainerStyle={{ paddingHorizontal: 32, paddingTop: 40, paddingBottom: 100 }}>
                <View className="mb-8">
                    <Text className={`text-3xl font-heading-semibold mb-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>
                        {step === 1 ? "Create Rider Account" : step === 2 ? "Verify Email" : "Rider Details"}
                    </Text>
                    <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {step === 1 ? "Start your journey with Drop" : step === 2 ? "Check your email for the OTP" : "Tell us about your delivery profile"}
                    </Text>
                </View>

                {errors ? <Text className="text-red-500 text-sm mb-4">{errors}</Text> : null}

                {step === 1 && (
                    <View className="gap-4">
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Full Name</Text>
                            <TextInput
                                className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                placeholder="E.g., John Doe"
                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                value={fullName}
                                onChangeText={setFullName}
                            />
                        </View>
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Email</Text>
                            <TextInput
                                className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                placeholder="Enter your email"
                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                keyboardType="email-address"
                                autoCapitalize="none"
                                value={emailAddress}
                                onChangeText={setEmailAddress}
                            />
                        </View>
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Password</Text>
                            <View className="relative justify-center">
                                <TextInput
                                    className={`w-full p-4 pr-12 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                    placeholder="Enter your password"
                                    placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                    secureTextEntry={!showPassword}
                                    value={password}
                                    onChangeText={setPassword}
                                />
                                <View className="absolute right-2 top-0 bottom-0 justify-center">
                                    <PressableScale accessibilityLabel={showPassword ? "Hide password" : "Show password"} onPress={() => setShowPassword(!showPassword)} className="p-2">
                                        {showPassword ? (
                                            <Ionicons name="eye-off" size={20} color={BRAND.primary} />
                                        ) : (
                                            <Ionicons name="eye" size={20} color={BRAND.primary} />
                                        )}
                                    </PressableScale>
                                </View>
                            </View>
                        </View>

                        <PressableScale activeOpacity={0.8} disabled={loading} onPress={onSignUpPress} className={`w-full mt-4 py-4 rounded-2xl items-center ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}>
                            <Text className="text-white font-sans-bold text-lg">{loading ? "Processing..." : "Sign Up"}</Text>
                        </PressableScale>

                        <View className="flex-row items-center justify-center mt-6">
                            <Text className={`${darkTheme ? "text-gray-400" : "text-gray-700"}`}>Already have an account? </Text>
                            <PressableScale onPress={() => router.push("/(Auth)/sign-in/screen")}>
                                <Text className="text-accentbg font-sans-semibold">Log In</Text>
                            </PressableScale>
                        </View>
                    </View>
                )}

                {step === 2 && (
                    <View className="gap-4">
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>OTP Code</Text>
                            <TextInput
                                className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black text-center"}`}
                                placeholder="123456"
                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                keyboardType="number-pad"
                                value={code}
                                onChangeText={setCode}
                            />
                        </View>

                        <PressableScale activeOpacity={0.8} disabled={loading} onPress={onVerifyPress} className={`w-full mt-4 py-4 rounded-2xl items-center ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}>
                            <Text className="text-white font-sans-bold text-lg">{loading ? "Verifying..." : "Verify Code"}</Text>
                        </PressableScale>
                    </View>
                )}

                {step === 3 && (
                    <View className="gap-4">
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Phone Number</Text>
                            <TextInput
                                className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                placeholder="+2547..."
                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                keyboardType="phone-pad"
                                value={phoneNumber}
                                onChangeText={setPhoneNumber}
                            />
                        </View>
                        <View className="mb-2 w-full items-center justify-center">
                            <VehicleDropdown
                                label="Vehicle Type"
                                value={vehicleType}
                                onValueChange={setVehicleType}
                                containerStyle={{ width: "100%", maxWidth: "100%" }}
                            />
                        </View>
                        <View>
                            <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>National ID / Passport</Text>
                            <TextInput
                                className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                placeholder="ID Number"
                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                value={idNumber}
                                onChangeText={setIdNumber}
                            />
                        </View>

                        <PressableScale activeOpacity={0.8} disabled={loading} onPress={completeRiderRegistration} className={`w-full mt-4 py-4 rounded-2xl items-center ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}>
                            <Text className="text-white font-sans-bold text-lg">{loading ? "Saving..." : "Finish Registration"}</Text>
                        </PressableScale>
                    </View>
                )}
            </ScrollView>
        </SafeAreaView>
        </KeyboardAvoidingView>
        </View>
    );
}
