import { UIThemeContext } from "@/context/ThemeContext";
// @ts-ignore
import { isClerkAPIResponseError, useSignIn } from "@clerk/clerk-expo";
import { useRouter, Link } from "expo-router";
import React, { useContext, useState } from "react";
import {
    Dimensions,
    ScrollView,
    StatusBar,
    View,
    KeyboardAvoidingView,
    Platform,
    ImageBackground,
    Image,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import images from "@/constants/images/images";
import { BRAND } from "@/constants/brandColors";

const { width, height } = Dimensions.get("window");

export default function ForgotPassword() {
    const { signIn, setActive, isLoaded } = useSignIn();
    const router = useRouter();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";

    const [emailAddress, setEmailAddress] = useState("");
    const [password, setPassword] = useState("");
    const [code, setCode] = useState("");
    const [successfulCreation, setSuccessfulCreation] = useState(false);
    const [loading, setLoading] = useState(false);
    const [errors, setErrors] = useState("");

    const [focusEmail, setFocusEmail] = useState(false);
    const [focusCode, setFocusCode] = useState(false);
    const [focusPassword, setFocusPassword] = useState(false);
    const [showPassword, setShowPassword] = useState(false);

    const handleFocus = (setter: React.Dispatch<React.SetStateAction<boolean>>) => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setter(true);
    };

    async function onRequestReset() {
        setLoading(true);
        setErrors("");
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            await signIn?.create({
                strategy: "reset_password_email_code",
                identifier: emailAddress.trim(),
            });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            setSuccessfulCreation(true);
        } catch (err: any) {
            if (isClerkAPIResponseError(err)) {
                setErrors(err.errors.map((e: any) => e.longMessage).join(", "));
            } else {
                setErrors("An unexpected error occurred.");
            }
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setLoading(false);
        }
    }

    async function onReset() {
        setLoading(true);
        setErrors("");
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
            const result = await signIn?.attemptFirstFactor({
                strategy: "reset_password_email_code",
                code,
                password,
            });

            if (result?.status === "complete") {
                await setActive?.({ session: result.createdSessionId });
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                router.replace("/(Auth)/sign-in/screen");
            } else {
                setErrors("Reset failed. Please check your inputs.");
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
            }
        } catch (err: any) {
            if (isClerkAPIResponseError(err)) {
                setErrors(err.errors.map((e: any) => e.longMessage).join(", "));
            } else {
                setErrors("An unexpected error occurred.");
            }
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        } finally {
            setLoading(false);
        }
    }

    return (
        <View className={darkTheme ? "bg-black" : ""} style={{ flex: 1 }}>
            <StatusBar backgroundColor="transparent" barStyle={darkTheme ? "light-content" : "dark-content"} translucent />
            
            <ImageBackground source={images.authBgLight} style={{ position: "absolute", width: "100%", height: height * 0.35 }}>
                <LinearGradient
                    className="w-full h-full"
                    colors={[
                        darkTheme ? "rgba(0, 0, 0, 0.2)" : "transparent",
                        darkTheme ? "rgba(0, 0, 0, 0.6)" : "rgba(240, 240, 240, 0.7)",
                        darkTheme ? "rgba(0, 0, 0, 1)" : "rgb(240, 240, 240)",
                    ]}
                />
            </ImageBackground>

            <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
                <SafeAreaView className="flex-1">
                    <ScrollView contentContainerStyle={{ paddingHorizontal: 32, paddingTop: 40, paddingBottom: 100 }} showsVerticalScrollIndicator={false}>
                        <View className="mb-8 mt-10">
                            <Text className={`text-3xl font-heading-semibold mb-2 tracking-tight ${darkTheme ? "text-white" : "text-gray-900"}`}>
                                Reset Password
                            </Text>
                            <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                {successfulCreation ? "Enter your new password and the code we sent" : "Enter your email to receive a reset code"}
                            </Text>
                        </View>

                        {errors ? (
                            <View className="flex-row items-center gap-2 mb-4 bg-red-500/10 p-3 rounded-lg">
                                <Ionicons name="alert-circle" size={20} color="#ef4444" />
                                <Text className="text-red-500 text-sm font-sans-medium flex-1">{errors}</Text>
                            </View>
                        ) : null}

                        <View className="gap-5">
                            {!successfulCreation ? (
                                <>
                                    <View>
                                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Email Address</Text>
                                        <View className={`flex-row items-center h-[55px] px-4 rounded-2xl border-2 ${focusEmail ? "border-accentbg bg-accentbg/5" : (darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white")}`}>
                                            <Ionicons name="mail" size={20} color={focusEmail ? "#d9a31b" : (darkTheme ? "#6B7280" : "#9CA3AF")} />
                                            <TextInput
                                                className={`flex-1 ml-3 text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                                placeholder="Enter your email"
                                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                                keyboardType="email-address"
                                                autoCapitalize="none"
                                                value={emailAddress}
                                                onChangeText={setEmailAddress}
                                                onFocus={() => handleFocus(setFocusEmail)}
                                                onBlur={() => setFocusEmail(false)}
                                            />
                                        </View>
                                    </View>

                                    <PressableScale
                                        activeOpacity={0.8}
                                        disabled={loading || !emailAddress}
                                        onPress={onRequestReset}
                                        className={`h-[55px] mt-4 rounded-full items-center justify-center ${loading || !emailAddress ? "bg-accentbg/50" : "bg-accentbg"}`}
                                    >
                                        {loading ? <Ionicons name="sync" size={32} color={BRAND.white} /> : <Text className="text-white font-sans-bold text-lg">Send Reset Code</Text>}
                                    </PressableScale>
                                </>
                            ) : (
                                <>
                                    <View>
                                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>Reset Code</Text>
                                        <View className={`flex-row items-center h-[55px] px-4 rounded-2xl border-2 ${focusCode ? "border-accentbg bg-accentbg/5" : (darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white")}`}>
                                            <Ionicons name="keypad" size={20} color={focusCode ? "#d9a31b" : (darkTheme ? "#6B7280" : "#9CA3AF")} />
                                            <TextInput
                                                className={`flex-1 ml-3 text-lg font-sans-bold tracking-[10px] text-center ${darkTheme ? "text-white" : "text-black"}`}
                                                placeholder="000000"
                                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                                keyboardType="number-pad"
                                                maxLength={6}
                                                value={code}
                                                onChangeText={setCode}
                                                onFocus={() => handleFocus(setFocusCode)}
                                                onBlur={() => setFocusCode(false)}
                                            />
                                        </View>
                                    </View>
                                    
                                    <View>
                                        <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>New Password</Text>
                                        <View className={`flex-row items-center h-[55px] px-4 rounded-2xl border-2 ${focusPassword ? "border-accentbg bg-accentbg/5" : (darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white")}`}>
                                            <Ionicons name="lock-closed" size={20} color={focusPassword ? "#d9a31b" : (darkTheme ? "#6B7280" : "#9CA3AF")} />
                                            <TextInput
                                                className={`flex-1 ml-3 text-base font-sans-medium ${darkTheme ? "text-white" : "text-black"}`}
                                                placeholder="Enter new password"
                                                placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                                secureTextEntry={!showPassword}
                                                value={password}
                                                onChangeText={setPassword}
                                                onFocus={() => handleFocus(setFocusPassword)}
                                                onBlur={() => setFocusPassword(false)}
                                            />
                                            <PressableScale accessibilityLabel={showPassword ? "Hide password" : "Show password"} onPress={() => setShowPassword(!showPassword)} className="p-2">
                                                {showPassword ? (
                                                    <Ionicons name="eye-off" size={20} color={darkTheme ? "#6B7280" : "#9CA3AF"} />
                                                ) : (
                                                    <Ionicons name="eye" size={20} color={darkTheme ? "#6B7280" : "#9CA3AF"} />
                                                )}
                                            </PressableScale>
                                        </View>
                                    </View>

                                    <PressableScale
                                        activeOpacity={0.8}
                                        disabled={loading || !code || !password}
                                        onPress={onReset}
                                        className={`h-[55px] mt-4 rounded-full items-center justify-center ${loading || !code || !password ? "bg-accentbg/50" : "bg-accentbg"}`}
                                    >
                                        {loading ? <Ionicons name="sync" size={32} color={BRAND.white} /> : <Text className="text-white font-sans-bold text-lg">Set New Password</Text>}
                                    </PressableScale>
                                </>
                            )}

                            <View className="flex-row justify-center mt-6">
                                <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                                    Remembered?{" "}
                                </Text>
                                <Link href={"/(Auth)/sign-in/screen"} asChild>
                                    <PressableScale hitSlop={10}>
                                        <Text className="text-accenttxt font-sans-bold">Back to Sign In</Text>
                                    </PressableScale>
                                </Link>
                            </View>
                        </View>
                    </ScrollView>
                </SafeAreaView>
            </KeyboardAvoidingView>
        </View>
    );
}
