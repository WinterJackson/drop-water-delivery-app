import { UIThemeContext } from "@/context/ThemeContext";
import { isClerkAPIResponseError, useSignIn } from "@clerk/clerk-expo";
import { useRouter } from "expo-router";
import React, { useContext, useState } from "react";
import {
    Dimensions,
    ScrollView,
    StatusBar,
    View,
    KeyboardAvoidingView,
    Platform,
} from "react-native";
import { Text, TextInput } from '@/components/ui/Text';
import { SafeAreaView } from "react-native-safe-area-context";
import PressableScale from "@/components/ui/PressableScale";
import { Image } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";

const { width } = Dimensions.get("window");

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
    const [showPassword, setShowPassword] = useState(false);

    async function onRequestReset() {
        setLoading(true);
        setErrors("");
        try {
            await signIn?.create({
                strategy: "reset_password_email_code",
                identifier: emailAddress,
            });
            setSuccessfulCreation(true);
        } catch (err: unknown) {
            if (isClerkAPIResponseError(err)) {
                setErrors(err.errors.map((e) => e.longMessage).join(", "));
            } else {
                setErrors("An unexpected error occurred.");
            }
        } finally {
            setLoading(false);
        }
    }

    async function onReset() {
        setLoading(true);
        setErrors("");
        try {
            const result = await signIn?.attemptFirstFactor({
                strategy: "reset_password_email_code",
                code,
                password,
            });

            if (result?.status === "complete") {
                await setActive?.({ session: result.createdSessionId });
                router.replace("/(Auth)/sign-in/screen");
            } else {
                setErrors("Reset failed. Please check your inputs.");
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
    }

    return (
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{flex: 1}}>
        <SafeAreaView className={`flex-1 px-8 pt-10 ${darkTheme ? "bg-black" : "bg-white"}`}>
            <StatusBar
                backgroundColor="transparent"
                barStyle={darkTheme ? "light-content" : "dark-content"}
            />
            <ScrollView contentContainerStyle={{ paddingBottom: 100 }} showsVerticalScrollIndicator={false}>
                <View className="mb-8">
                    <Text className={`text-3xl font-heading-semibold mb-2 ${darkTheme ? "text-white" : "text-gray-900"}`}>
                        Reset Password
                    </Text>
                    <Text className={`text-base ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                        {successfulCreation ? "Enter your new password and code" : "Enter your email to receive a reset code"}
                    </Text>
                </View>

                <View className="gap-4">
                    {!successfulCreation ? (
                        <>
                            <View>
                                <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                    Email
                                </Text>
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

                            {errors ? <Text className="text-red-500 text-sm">{errors}</Text> : null}

                            <PressableScale
                                activeOpacity={0.8}
                                disabled={loading}
                                onPress={onRequestReset}
                                className={`w-full mt-4 py-4 rounded-2xl items-center ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}
                            >
                                <Text className="text-white font-sans-bold text-lg">
                                    {loading ? "Sending..." : "Send Reset Code"}
                                </Text>
                            </PressableScale>
                        </>
                    ) : (
                        <>
                            <View>
                                <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                    Reset Code
                                </Text>
                                <TextInput
                                    className={`w-full p-4 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                    placeholder="Enter 6-digit code"
                                    placeholderTextColor={darkTheme ? "#6B7280" : "#9CA3AF"}
                                    keyboardType="number-pad"
                                    value={code}
                                    onChangeText={setCode}
                                />
                            </View>
                            
                            <View>
                                <Text className={`text-sm font-sans-semibold mb-2 ${darkTheme ? "text-gray-300" : "text-gray-700"}`}>
                                    New Password
                                </Text>
                            <View className="relative justify-center">
                                <TextInput
                                    className={`w-full p-4 pr-12 rounded-xl border ${darkTheme ? "border-gray-800 bg-gray-900 text-white" : "border-gray-200 bg-white text-black"}`}
                                    placeholder="Enter new password"
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

                            {errors ? <Text className="text-red-500 text-sm">{errors}</Text> : null}

                            <PressableScale
                                activeOpacity={0.8}
                                disabled={loading}
                                onPress={onReset}
                                className={`w-full mt-4 py-4 rounded-2xl items-center ${loading ? "bg-accentbg/60" : "bg-accentbg"}`}
                            >
                                <Text className="text-white font-sans-bold text-lg">
                                    {loading ? "Resetting..." : "Set New Password"}
                                </Text>
                            </PressableScale>
                        </>
                    )}

                    <View className="flex-row justify-center mt-6">
                        <Text className={`${darkTheme ? "text-gray-400" : "text-gray-500"}`}>
                            Remembered?{" "}
                        </Text>
                        <PressableScale onPress={() => router.push("/(Auth)/sign-in/screen")}>
                            <Text className="text-accentbg font-sans-semibold">Back to Sign In</Text>
                        </PressableScale>
                    </View>
                </View>
            </ScrollView>
        </SafeAreaView>
        </KeyboardAvoidingView>
    );
}
