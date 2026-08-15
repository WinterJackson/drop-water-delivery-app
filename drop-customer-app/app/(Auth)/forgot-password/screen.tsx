import { isClerkAPIResponseError, useSignIn } from "@clerk/clerk-expo";
import { ClerkAPIError } from "@clerk/types";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import React, { useContext, useState } from "react";
import {
    Dimensions,
    Image,
    ImageBackground,
    KeyboardAvoidingView,
    ScrollView,
    StatusBar,
    View,
} from "react-native";
import { Text } from '@/components/ui/Text';

import InputField from "@/components/ui/InputField";
import icons from "@/constants/icons/icons";
import images from "@/constants/images/images";
import { UIThemeContext } from "@/context/ThemeContext";
import { PressableScale } from "@/components/ui/PressableScale";
import { Ionicons } from "@expo/vector-icons";
import { BRAND } from "@/constants/brandColors";

const { height } = Dimensions.get("window");

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
    const [errors, setErrors] = useState<ClerkAPIError[]>();
    const [message, setMessage] = useState("");

    const statusBarHeight = StatusBar.currentHeight || 0;

    // Send the password reset code to the user's email
    async function onRequestReset() {
        setLoading(true);
        setErrors(undefined);
        setMessage("");

        try {
            await signIn?.create({
                strategy: "reset_password_email_code",
                identifier: emailAddress,
            });
            setSuccessfulCreation(true);
        } catch (err: unknown) {
            if (isClerkAPIResponseError(err)) setErrors(err.errors);
            else setMessage("An unexpected error occurred.");
        } finally {
            setLoading(false);
        }
    }

    // Reset the password using the code
    async function onReset() {
        setLoading(true);
        setErrors(undefined);
        setMessage("");

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
                setMessage("Reset failed. Please check your data.");
            }
        } catch (err: unknown) {
            if (isClerkAPIResponseError(err)) setErrors(err.errors);
            else setMessage("An unexpected error occurred.");
        } finally {
            setLoading(false);
        }
    }

    return (
        <>
            <StatusBar
                backgroundColor={'transparent'}
                barStyle={darkTheme ? "light-content" : "dark-content"}
            />
            <View
                className={darkTheme ? "bg-black" : ""}
                style={{ flex: 1 }}
            >
                <KeyboardAvoidingView
                    behavior="padding"
                    style={{ flex: 1 }}
                >
                    <ScrollView
                        className="flex-1 w-full"
                        overScrollMode="never"
                        showsVerticalScrollIndicator={false}
                        contentContainerStyle={{ paddingBottom: 120 }}
                    >
                        <ImageBackground
                            source={images.authBgLight}
                            style={{
                                height: height * 0.35,
                                marginBottom: -(height * 0.09),
                            }}
                        >
                            <LinearGradient
                                className="w-full h-full"
                                colors={[
                                    darkTheme ? "rgba(0, 0, 0, 0.2)" : "transparent",
                                    darkTheme ? "rgba(0, 0, 0, 0.6)" : "rgba(240, 240, 240, 0.7)",
                                    darkTheme ? "rgba(0, 0, 0, 1)" : "rgb(240, 240, 240)",
                                ]}
                            />
                        </ImageBackground>

                        <View className="w-full gap-3 px-6">
                            <View className="w-[90%] self-center">
                                <Text className={darkTheme ? "text-[30px] text-white" : "text-[30px] text-black"}>{"Reset Password"}</Text>
                            </View>

                            <View className="py-[50px] gap-[20px] items-center">
                                {!successfulCreation ? (
                                    <>
                                        <InputField
                                            label={"Email"}
                                            type={"email"}
                                            placeholder={"Enter your Email Address"}
                                            iconleft="mail"
                                            set={setEmailAddress}
                                        />
                                        
                                        {errors && (
                                            <View className="w-[90%] gap-2">
                                                {errors.map((el, index) => (
                                                    <View key={index} className="flex-row gap-2 items-center">
                                                        <Ionicons name="information-circle" size={20} color={"red"} />
                                                        <Text className="text-red-500">{el.longMessage}</Text>
                                                    </View>
                                                ))}
                                            </View>
                                        )}

                                        <PressableScale
                                            className="w-full items-center mt-4"
                                            activeOpacity={0.7}
                                            disabled={loading}
                                            onPress={onRequestReset}
                                        >
                                            <View
                                                className={`w-[90%] max-w-[320px] h-[45px] flex-row items-center justify-center gap-2 ${loading ? "bg-accentbg/60" : "bg-accentbg"} rounded-full`}
                                            >
                                                {loading ? (
                                                    <Ionicons name="sync" size={32} color={BRAND.white} />
                                                ) : (
                                                    <Text className={`text-white text-xl font-sans-semibold`}>
                                                        Send Reset Code
                                                    </Text>
                                                )}
                                            </View>
                                        </PressableScale>
                                    </>
                                ) : (
                                    <>
                                        <InputField
                                            label={"Reset Code"}
                                            type={"text"}
                                            placeholder={"Enter Reset Code"}
                                            set={setCode}
                                        />
                                        <InputField
                                            label={"New Password"}
                                            type={"password"}
                                            placeholder={"Enter New Password"}
                                            iconleft="key"
                                            set={setPassword}
                                        />

                                        {errors && (
                                            <View className="w-[90%] gap-2">
                                                {errors.map((el, index) => (
                                                    <View key={index} className="flex-row gap-2 items-center">
                                                        <Ionicons name="information-circle" size={20} color={"red"} />
                                                        <Text className="text-red-500">{el.longMessage}</Text>
                                                    </View>
                                                ))}
                                            </View>
                                        )}
                                        {message ? <Text className="text-red-500">{message}</Text> : null}

                                        <PressableScale
                                            className="w-full items-center mt-4"
                                            activeOpacity={0.7}
                                            disabled={loading}
                                            onPress={onReset}
                                        >
                                            <View
                                                className={`w-[90%] max-w-[320px] h-[45px] flex-row items-center justify-center gap-2 ${loading ? "bg-accentbg/60" : "bg-accentbg"} rounded-full`}
                                            >
                                                {loading ? (
                                                    <Ionicons name="sync" size={32} color={BRAND.white} />
                                                ) : (
                                                    <Text className={`text-white text-xl font-sans-semibold`}>
                                                        Reset Password
                                                    </Text>
                                                )}
                                            </View>
                                        </PressableScale>
                                    </>
                                )}
                            </View>

                            <View className="flex-row gap-2 items-center justify-center">
                                <Text className={darkTheme ? "text-white" : ""}>{"Remembered?"}</Text>
                                <PressableScale onPress={() => router.push("/(Auth)/sign-in/screen")}>
                                    <View className="h-7 items-center justify-center">
                                        <Text className={"text-accenttxt group-active:text-gray-400"}>{"Back to Sign In"}</Text>
                                    </View>
                                </PressableScale>
                            </View>
                        </View>
                    </ScrollView>
                </KeyboardAvoidingView>
            </View>
        </>
    );
}