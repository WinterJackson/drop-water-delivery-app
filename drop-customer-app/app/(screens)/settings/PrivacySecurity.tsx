import React, { useContext, useState, useEffect } from "react";
import { useTabBarClearance } from '@/constants/layout';
import { SafeAreaView } from "react-native-safe-area-context";
import BackButtonMinimal from "@/components/ui/BackButtonMinimal";
import { View, ScrollView, Switch, Linking } from "react-native";
import { Text } from '@/components/ui/Text';
import { Stack, useRouter } from "expo-router";
import { UIThemeContext } from "@/context/ThemeContext";
import { Toast } from "@/lib/toast";
import { Popup } from "@/lib/popup";
import { BRAND, TOAST } from "@/constants/brandColors";
import { useUserDetails, useUpdateUser } from "@/hooks/queries/useUser";
import { PressableScale } from "@/components/ui/PressableScale";

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const ActionItem = ({ title, icon, description, onPress, darkTheme }: import("@/types/components").ActionItemProps & { darkTheme: boolean }) => (
    <PressableScale 
        activeOpacity={0.7} 
        onPress={onPress}
        className={`p-4 mb-4 rounded-xl border flex-row items-center justify-between ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"}`}
    >
        <View className="flex-row items-center gap-4 flex-1">
            <View className={`w-10 h-10 items-center justify-center rounded-full ${darkTheme ? "bg-black" : "bg-white"}`}>
                <Text style={{ fontSize: 18 }}>{icon}</Text>
            </View>
            <View className="flex-1 pr-4">
                <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{title}</Text>
                {description && (
                    <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{description}</Text>
                )}
            </View>
        </View>
        <Text className={`text-xl ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>›</Text>
    </PressableScale>
);

/**
 * At module scope, not inside the screen.
 *
 * A component declared in a render body is a new function object — and so a new
 * component *type* — on every render, which makes React unmount its subtree and
 * mount a fresh one instead of updating it. Even with no input and no state of
 * its own that is not free: every child is torn down and rebuilt, `PressableScale`
 * restarts its animation, and the reconciler does the most expensive kind of work
 * on the most ordinary re-render.
 *
 * What it closed over is passed in instead.
 */
const ToggleItem = ({ title, icon, description, value, onToggle, darkTheme }: import("@/types/components").ToggleItemProps & { darkTheme: boolean }) => (
    <View className={`p-4 mb-4 rounded-xl border flex-row items-center justify-between ${darkTheme ? "border-gray-800 bg-gray-900" : "border-gray-200 bg-white"}`}>
        <View className="flex-row items-center gap-4 flex-1 border-r border-transparent">
            <View className={`w-10 h-10 items-center justify-center rounded-full ${darkTheme ? "bg-black" : "bg-white"}`}>
                <Text style={{ fontSize: 18 }}>{icon}</Text>
            </View>
            <View className="flex-1 pr-4">
                <Text className={`text-lg font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>{title}</Text>
                {description && (
                    <Text className={`text-xs mt-1 ${darkTheme ? "text-gray-400" : "text-gray-500"}`}>{description}</Text>
                )}
            </View>
        </View>
        <Switch
            value={value}
            onValueChange={onToggle}
            trackColor={{ false: darkTheme ? "#333" : "#e5e7eb", true: "#3b82f6" }}
            thumbColor={BRAND.white}
        />
    </View>
);

export default function PrivacySecurity() {
    const tabBarClearance = useTabBarClearance();
    const { currentTheme } = useContext(UIThemeContext);
    const darkTheme = currentTheme === "dark";
    const router = useRouter();

    const { data: User } = useUserDetails();
    const updateUserMutation = useUpdateUser();

    const [dataTracking, setDataTracking] = useState(true);

    useEffect(() => {
        if (User?.preferences && User.preferences.analytics !== undefined) {
            setDataTracking(Boolean(User.preferences.analytics));
        }
    }, [User]);

    const handleDataTrackingToggle = async (val: boolean) => {
        setDataTracking(val);
        const newPrefs = { ...(User?.preferences || {}), analytics: val };
        try {
            await updateUserMutation.mutateAsync({ preferences: newPrefs });
        } catch (error) {
            setDataTracking(!val); // Revert
            Toast.error("Update Failed", "Could not save your preferences.");
        }
    };

    // This used to close the popup and announce "Link Sent" without sending
    // anything — the user waited for an email that was never requested. Hand off
    // to the real Clerk reset flow instead, which sends the code and takes the
    // new password.
    const handlePasswordChange = () => {
        Popup.show({
            title: "Change Password",
            message: "For your security, a password change is confirmed by email. We'll take you to the reset screen, where a verification code is sent to your registered address.",
            cancelText: "Cancel",
            confirmText: "Continue",
            onConfirm: () => {
                Popup.hide();
                router.push("/(Auth)/forgot-password/screen");
            }
        });
    };

    const handleOpenLink = async (url: string) => {
        const supported = await Linking.canOpenURL(url);
        if (supported) {
            await Linking.openURL(url);
        } else {
            Toast.error("Error", "Could not open the link securely.");
        }
    };

    const actionItemProps = { darkTheme };

    const toggleItemProps = { darkTheme };

    return (
        <SafeAreaView className={`flex-1 ${darkTheme ? "bg-black" : ""}`}>
            <Stack.Screen options={{ headerShown: false }} />
            <View style={{ overflow: "hidden", paddingBottom: 4 }}>
            <View 
                className="flex-row items-center px-4 py-3 pb-4 mb-2"
                style={{ 
                    backgroundColor: darkTheme ? "#000" : "#fff",
                    borderBottomWidth: 1, 
                    borderBottomColor: darkTheme ? BRAND.gray800 : BRAND.gray200,
                    ...(darkTheme ? { shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 4 } : { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.05, shadowRadius: 4, elevation: 2 })
                }}
            >
                <PressableScale onPress={() => router.back()} className="mr-4">
                    <BackButtonMinimal />
                </PressableScale>
                <Text className={`text-xl font-sans-bold ${darkTheme ? "text-white" : "text-black"}`}>
                    Privacy & Security
                </Text>
            </View>
            </View>

            <ScrollView contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 10, paddingBottom: tabBarClearance }}>
                
                <Text className={`text-sm font-sans-bold mb-3 uppercase tracking-widest mt-2 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Security
                </Text>
                <ActionItem {...actionItemProps} 
                    title="Change Password" 
                    icon="🔐"
                    description="Request a secure password modification link to your registered email."
                    onPress={handlePasswordChange}
                />

                <Text className={`text-sm font-sans-bold mb-3 uppercase tracking-widest mt-6 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Legal & Compliance
                </Text>
                <ActionItem {...actionItemProps} 
                    title="Privacy Policy" 
                    icon="📄"
                    description="Read our comprehensive privacy policy securely online."
                    onPress={() => handleOpenLink("https://drop.space/privacy")}
                />
                <ActionItem {...actionItemProps} 
                    title="Terms of Service" 
                    icon="⚖️"
                    description="Review the terms and conditions binding your usage."
                    onPress={() => handleOpenLink("https://drop.space/terms")}
                />

                <Text className={`text-sm font-sans-bold mb-3 uppercase tracking-widest mt-6 ${darkTheme ? "text-gray-500" : "text-gray-400"}`}>
                    Data Preferences
                </Text>
                <ToggleItem {...toggleItemProps} 
                    title="Analytics & Telemetry" 
                    icon="📊"
                    description="Allow anonymous usage data to be collected to improve the Drop platform ecosystem."
                    value={dataTracking}
                    onToggle={handleDataTrackingToggle}
                />

            </ScrollView>
        </SafeAreaView>
    );
}
